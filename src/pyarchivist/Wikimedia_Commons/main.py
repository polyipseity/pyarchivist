"""Wikimedia Commons archive implementation.

This module implements the query, fetch and indexing flow for files on
Wikimedia Commons. It provides a top-level `main` coroutine and a `parser`
factory for the CLI subcommand. Helper utilities and small types used across
the flow are declared here as well.
"""

from argparse import ONE_OR_MORE, ArgumentParser
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass
from enum import IntFlag, auto, unique
from functools import wraps
from itertools import chain
from re import MULTILINE, compile
from sys import exit
from typing import ClassVar, Protocol, TypeVar, final
from urllib.parse import quote, unquote

from aiohttp import ClientSession, TCPConnector
from anyio import Path
from asyncer import SoonValue, asyncify, create_task_group
from html2text import HTML2Text
from yarl import URL

from pyarchivist.meta import LOGGER, OPEN_TEXT_OPTIONS, USER_AGENT, VERSION

from .models import Page, ResponseModel

"""Public symbols exported by this module."""
__all__ = (
    "ExitCode",
    "Args",
    "main",
    "parser",
)

"""Maximum concurrent HTTP requests per host for the aiohttp connector."""
_MAX_CONCURRENT_REQUESTS_PER_HOST = 1
"""Characters left unescaped in URL percent-encoding for Commons URLs."""
_PERCENT_ESCAPE_SAFE = "/,"
"""Number of page titles per API query batch."""
_QUERY_LIMIT = 50
"""Type variable for generic helpers in this module."""
_T = TypeVar("_T")


@final
@unique
class ExitCode(IntFlag):
    """Exit codes representing various error and partial-error conditions.

    Each member corresponds to a phase or a class of failure that may occur
    during a run. The bits can be combined to represent multiple simultaneous
    failure modes (for example partial fetch errors plus a generic error).
    """

    __slots__: ClassVar = ()

    GENERIC_ERROR = auto()
    QUERY_ERROR = auto()
    FETCH_ERROR = auto()
    INDEX_ERROR = auto()
    QUERY_ERROR_PARTIAL = auto()
    FETCH_ERROR_PARTIAL = auto()


@final
@dataclass(
    init=True,
    repr=True,
    eq=True,
    order=False,
    unsafe_hash=False,
    frozen=True,
    match_args=True,
    kw_only=True,
    slots=True,
)
class Args:
    """Immutable container for parsed CLI arguments.

    Attributes:
        inputs: sequence of input titles (strings)
        dest: destination path where files will be written
        index: optional index file path (Markdown)
        ignore_individual_errors: if True, continue on individual file errors
    """

    inputs: Sequence[str]
    dest: Path
    index: Path | None
    ignore_individual_errors: bool

    def __post_init__(self):
        """Normalize `inputs` to an immutable tuple after initialization."""
        object.__setattr__(self, "inputs", tuple(self.inputs))


# The CLI response models are provided by pydantic
# models in :mod:`.models` (see `Args` and `ResponseModel`). This keeps
# JSON parsing and validation centralized and more explicit.

"""Regex matching index.md lines: - [display](url): credit."""
_INDEX_FORMAT_PATTERN = compile(r"^- \[(.+?(?<!\\))]\((.+?(?<!\\))\): (.+)$", MULTILINE)


def _handle_partial_errors(
    results: Collection[_T | BaseException],
    *,
    ignore_individual_errors: bool,
    error_message: str = "Error",
) -> tuple[bool, Collection[_T]]:
    """Inspect a collection of results and propagate or aggregate errors.

    The `results` iterable may contain successful values or exception
    instances (when `gather(..., return_exceptions=True)` was used). This
    helper separates exceptions from values, optionally logs/raises grouped
    exceptions and returns a tuple `(error_flag, successful_results)` where
    `error_flag` is True when any exceptions were encountered and swallowed
    due to `ignore_individual_errors=True`.
    """

    error = False
    base_exceptions = tuple(
        query for query in results if isinstance(query, BaseException)
    )
    exceptions = tuple(exc for exc in base_exceptions if isinstance(exc, Exception))
    if len(exceptions) < len(base_exceptions):
        raise BaseExceptionGroup(error_message, base_exceptions)
    if exceptions:
        exception_group = ExceptionGroup(error_message, exceptions)
        if not ignore_individual_errors:
            raise exception_group
        try:
            raise exception_group
        except ExceptionGroup:
            LOGGER.exception(error_message)
            error = True
    return error, tuple(
        result for result in results if not isinstance(result, BaseException)
    )


def _index_formatter(filename: str, credit: str):
    """Format a Markdown index line for a file and its credit string.

    The filename is escaped for Markdown compatibility and URL-escaped for
    the link target. The returned string is suitable for appending to an
    `index.md` paragraph handled by the indexing logic.
    """

    escaped = filename.replace("\\", "\\\\").replace("]", "\\]")
    return f"- [{escaped}]({quote(filename, safe=_PERCENT_ESCAPE_SAFE)}): {credit}"


def _credit_formatter(page: Page):
    """Produce a credit string (HTML fragment) for an image page.

    The function extracts author and license information from the page
    metadata, sanitizes common 'Unknown' markers and returns a concise
    HTML snippet linking back to the file description page on Commons.
    """

    assert page.imageinfo is not None

    htm_esc = HTML2Text()
    htm_esc.emphasis_mark = "_"
    htm_esc.ignore_links = True
    htm_esc.single_line_break = True
    htm_esc.strong_mark = "__"
    htm_esc.ul_item_mark = "-"

    ii = page.imageinfo[0]
    emd = ii.extmetadata

    # Defensive access: pydantic fields may be None; ensure we pass `str` to
    # html2text and call string methods only on `str`.
    raw_author = ""
    if emd and emd.Artist and emd.Artist.value:
        raw_author = emd.Artist.value
    author = htm_esc.handle(raw_author).strip()
    # html2text may convert tags to emphasis markers (we use `_` / `__`).
    # treat values that are only emphasis markers or whitespace as absent so
    # entirely-tagged authors (e.g. "<b> </b>") fall back to the default.
    if not author.replace("_", "").strip():
        author = ""
    if "Unknown author".casefold() in author.casefold():
        author = ""

    raw_lic = ""
    if emd and emd.LicenseShortName and emd.LicenseShortName.value:
        raw_lic = emd.LicenseShortName.value
    # treat whitespace-only values as absent
    lic = raw_lic.strip()
    if "Unknown license".casefold() in lic.casefold():
        lic = ""

    lic_url = ""
    if emd and emd.LicenseUrl and emd.LicenseUrl.value:
        lic_url = emd.LicenseUrl.value

    lic_lnk = "".join(
        (
            f'<a href="{lic_url}">' if lic_url else "",
            (lic.replace("\n", "") if lic else "See page for license"),
            "</a>" if lic_url else "",
        )
    )

    author = author.replace("\n", "") or "See page for author"
    return (
        f'<a href="{ii.descriptionurl}">{author}</a>, {lic_lnk}, via Wikimedia Commons'
    )


async def main(args: Args):
    """Primary coroutine implementing the query-fetch-index flow.

    Executes the following steps:
    1. Query Wikimedia Commons for page and image metadata for requested inputs.
    2. Fetch image binary content for the discovered pages.
    3. Optionally update a Markdown index file using `_index_formatter`.

    On error, the function will log and set appropriate `ExitCode` flags before
    calling `sys.exit` with the resulting exit code.
    """

    ec = ExitCode(0)

    try:
        inputs = tuple(dict.fromkeys(args.inputs))
        async with ClientSession(
            connector=TCPConnector(limit_per_host=_MAX_CONCURRENT_REQUESTS_PER_HOST),
            headers={
                "Accept-Encoding": "gzip",
                "User-Agent": USER_AGENT,
            },
        ) as sess:
            try:
                LOGGER.info(f"Querying {len(inputs)} files")

                async def query(
                    inputs: Iterable[str],
                ) -> Iterable[tuple[str, Page]] | BaseException:
                    """Query the Wikimedia Commons API for the given titles and
                    return the parsed pages items, or the exception if the query fails.
                    """
                    try:
                        async with sess.get(
                            URL.build(
                                scheme="https",
                                host="commons.wikimedia.org",
                                path="/w/api.php",
                                query={
                                    "format": "json",
                                    "action": "query",
                                    "titles": "|".join(inputs),
                                    "prop": "imageinfo",
                                    "iiprop": "extmetadata|url",
                                },
                            )
                        ) as resp:
                            text = await resp.text()
                        data = ResponseModel.model_validate_json(text)
                        return data.query.pages.items()
                    except BaseException as e:
                        return e

                # run query batches concurrently using structural concurrency
                # run query batches concurrently using soonify for brevity
                # run query batches concurrently using structural concurrency
                # the ``SoonValue`` objects capture return values that we can
                # inspect after the task group closes (see Asyncer documentation).
                svs: list[SoonValue[Iterable[tuple[str, Page]] | BaseException]] = []
                async with create_task_group() as tg:
                    for idx in range(0, len(inputs), _QUERY_LIMIT):
                        svs.append(tg.soonify(query)(inputs[idx : idx + _QUERY_LIMIT]))
                # at this point the task group has exited and all queries have
                # completed; we can safely access ``.value`` on each SoonValue.
                queries = [sv.value for sv in svs]
                error, queries = _handle_partial_errors(
                    queries,
                    ignore_individual_errors=args.ignore_individual_errors,
                    error_message="Error querying",
                )
                if error:
                    ec |= ExitCode.QUERY_ERROR_PARTIAL
                # ``id`` is a builtin, so rename to ``page_id`` for clarity and
                # to give mypy/pyright an explicit variable name.
                pages = tuple(
                    {
                        page_id: page for page_id, page in chain.from_iterable(queries)
                    }.values()
                )
            except Exception:
                LOGGER.exception("Error querying")
                ec |= ExitCode.QUERY_ERROR
                raise
            try:
                LOGGER.info(f"Fetching {len(pages)} files")

                async def fetch(page: Page) -> tuple[str, str] | BaseException:
                    """Download the binary content for ``page`` and return a tuple of
                    ``(filename, index_line)``, or the exception if the fetch fails.
                    """
                    try:
                        filename = page.title.split(":", 1)[-1]
                        if page.imageinfo is None:
                            raise ValueError(f"Failed to fetch '{filename}'")
                        dest_path = args.dest
                        # ensure destination directory exists before writing files
                        await dest_path.mkdir(parents=True, exist_ok=True)
                        async with (
                            sess.get(page.imageinfo[0].url) as resp,
                            await (dest_path / filename).open(mode="wb") as file,
                        ):
                            LOGGER.info(f"Fetching '{filename}'")
                            async for chunk in resp.content.iter_any():
                                await file.write(chunk)
                        # compute credit/index lines off the event loop
                        credit = await asyncify(_credit_formatter)(page)
                        index_line = await asyncify(_index_formatter)(filename, credit)
                        return filename, index_line
                    except BaseException as e:
                        return e

                # fetch pages concurrently, capturing their return values with
                # SoonValue so we can access them after the task group exits.
                fetch_svs: list[SoonValue[tuple[str, str] | BaseException]] = []
                async with create_task_group() as tg:
                    for page in pages:
                        fetch_svs.append(tg.soonify(fetch)(page))
                entries = [sv.value for sv in fetch_svs]
                error, entries = _handle_partial_errors(
                    entries,
                    ignore_individual_errors=args.ignore_individual_errors,
                    error_message="Error fetching",
                )
                if error:
                    ec |= ExitCode.FETCH_ERROR_PARTIAL
            except Exception:
                LOGGER.info("Error fetching")
                ec |= ExitCode.FETCH_ERROR
                raise
            try:
                if args.index is None:
                    LOGGER.info("Skipped indexing")
                else:
                    LOGGER.info(f"Indexing {len(entries)} files")

                    idx = args.index
                    await idx.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        file = await idx.open(mode="xt", **OPEN_TEXT_OPTIONS)
                    except FileExistsError:
                        pass
                    else:
                        await file.aclose()

                    async with await idx.open(mode="r+t", **OPEN_TEXT_OPTIONS) as file:
                        read = await file.read()
                        await file.seek(0)
                        paragraphs = read.strip().split("\n\n")
                        index: dict[str, str] = {
                            unquote(match[2]): match[0]
                            for match in _INDEX_FORMAT_PATTERN.finditer(paragraphs[-1])
                        }
                        for filename, entry in entries:
                            index[filename] = entry
                        paragraphs[-1] = "\n".join(
                            value
                            for _, value in sorted(
                                index.items(), key=lambda item: item[0]
                            )
                        )
                        text = "\n\n".join(paragraphs) + "\n"
                        await file.write(text)
                        await file.truncate()
            except Exception:
                LOGGER.exception("Error indexing")
                ec |= ExitCode.INDEX_ERROR
                raise
    except Exception:
        LOGGER.exception("Error")
        ec |= ExitCode.GENERIC_ERROR

    exit(ec)


class _ParserNamespace(Protocol):
    """Typed namespace returned by the Wikimedia subparser."""

    dest: Path
    index: Path | None
    inputs: list[str]
    ignore_individual_errors: bool


def parser(parent: Callable[..., ArgumentParser] | None = None):
    """Return an argparse parser configured for the Wikimedia Commons subcommand.

    When embedded, `parent` can be a callable that produces an `ArgumentParser`.
    """

    prog = __package__ or __name__

    parser = (ArgumentParser if parent is None else parent)(
        prog=f"python -m {prog}",
        description="archive data from Wikimedia Commons",
        add_help=True,
        allow_abbrev=False,
        exit_on_error=False,
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"{prog} v{VERSION}",
        help="print version and exit",
    )
    parser.add_argument(
        "-d",
        "--dest",
        action="store",
        type=Path,
        required=True,
        help="destination directory",
    )
    parser.add_argument(
        "-i",
        "--index",
        action="store",
        type=Path,
        help="Markdown-based index file",
    )
    parser.add_argument(
        "--ignore-individual-errors",
        action="store_true",
        default=False,
        help="ignore errors from individual files",
        dest="ignore_individual_errors",
    )
    parser.add_argument(
        "inputs",
        action="store",
        nargs=ONE_OR_MORE,
        type=str,
        help="sequence of input(s) to read",
    )

    @wraps(main)
    async def invoke(args: _ParserNamespace):
        """Adapter converting an argparse namespace into `Args` and calling
        `main`."""
        await main(
            Args(
                inputs=tuple(args.inputs),
                dest=args.dest,
                index=args.index,
                ignore_individual_errors=args.ignore_individual_errors,
            )
        )

    parser.set_defaults(invoke=invoke)
    return parser
