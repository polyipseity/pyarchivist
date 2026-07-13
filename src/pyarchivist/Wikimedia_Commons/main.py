"""Wikimedia Commons archive implementation.

This module implements the query, fetch and indexing flow for files on
Wikimedia Commons. It provides a top-level `archive` coroutine and the
library-oriented API. Helper utilities and small types used across the flow
are declared here as well.
"""

from collections.abc import Awaitable, Callable, Collection, Iterable, Sequence
from dataclasses import dataclass
from enum import IntFlag, auto, unique
from html import escape as html_escape
from itertools import chain
from random import random as _random
from re import MULTILINE, compile
from typing import ClassVar, TypeVar, final
from urllib.parse import quote, unquote

from aiohttp import ClientSession, ClientTimeout, TCPConnector
from anyio import Path, sleep
from asyncer import SoonValue, asyncify, create_task_group
from yarl import URL

from pyarchivist.meta import LOGGER, OPEN_TEXT_OPTIONS, USER_AGENT

from .models import Page, ResponseModel

"""Public symbols exported by this module."""
__all__ = (
    "ExitCode",
    "Args",
    "ArchiveError",
    "ArchiveResult",
    "archive",
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
    QUERY_ERROR_PARTIAL = QUERY_ERROR | 16
    FETCH_ERROR_PARTIAL = FETCH_ERROR | 32


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
    """Immutable container for archive operation parameters.

    Attributes:
        inputs: sequence of input titles (strings)
        dest: destination path where files will be written
        index: optional index file path (Markdown)
        ignore_individual_errors: if True, continue on individual file errors
        skip_existing: if True, skip files that already exist at the destination
        max_retries: maximum number of retries for failed operations
        retry_delay: delay in seconds between retries
        request_timeout: timeout in seconds for HTTP requests
        progress_callback: optional callback for progress updates (current, total)
    """

    inputs: Sequence[str]
    dest: Path
    index: Path | None
    ignore_individual_errors: bool
    skip_existing: bool = False
    max_retries: int = 3
    retry_delay: float = 1.0
    request_timeout: float = 30.0
    progress_callback: Callable[[int, int], None] | None = None

    def __post_init__(self):
        """Normalize `inputs` to an immutable tuple after initialization."""
        object.__setattr__(self, "inputs", tuple(self.inputs))


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
class ArchiveError:
    """Represents an error that occurred during an archive operation.

    Attributes:
        phase: the phase in which the error occurred (e.g. "query", "fetch", "index")
        title: the title of the item that caused the error
        message: a human-readable error message
    """

    phase: str
    title: str
    message: str


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
class ArchiveResult:
    """The result of an archive operation.

    Attributes:
        downloaded: number of files successfully downloaded
        skipped: number of files skipped (e.g. because they already exist)
        errors: tuple of ArchiveError objects collected during the operation
    """

    downloaded: int
    skipped: int
    errors: tuple[ArchiveError, ...]


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

    ii = page.imageinfo[0]
    emd = ii.extmetadata

    # Defensive access: pydantic fields may be None; ensure we pass `str` to
    # regex operations and call string methods only on `str`.
    raw_author = ""
    if emd and emd.Artist and emd.Artist.value:
        raw_author = emd.Artist.value
    # Strip HTML-like tags using simple regex pattern, then normalize whitespace
    author = compile(r"<[^>]*>", flags=MULTILINE).sub("", raw_author)
    author = compile(r"\s+").sub(" ", author.replace("\n", " ")).strip()

    if "Unknown author".casefold() in author.casefold():
        author = ""

    raw_lic = ""
    if emd and emd.LicenseShortName and emd.LicenseShortName.value:
        raw_lic = emd.LicenseShortName.value
    # Strip HTML-like tags and treat whitespace-only values as absent
    lic = compile(r"<[^>]*>", flags=MULTILINE).sub("", raw_lic)
    lic = compile(r"\s+").sub(" ", lic.replace("\n", " ")).strip()
    if "Unknown license".casefold() in lic.casefold():
        lic = ""

    lic_url = ""
    if emd and emd.LicenseUrl and emd.LicenseUrl.value:
        lic_url = emd.LicenseUrl.value

    lic_lnk = "".join(
        (
            f'<a href="{lic_url}">' if lic_url else "",
            (html_escape(lic) if lic else "See page for license"),
            "</a>" if lic_url else "",
        )
    )

    author = html_escape(author) or "See page for author"
    return (
        f'<a href="{ii.descriptionurl}">{author}</a>, {lic_lnk}, via Wikimedia Commons'
    )


def _separate_results(
    results: Collection[_T | BaseException],
    phase: str,
    title: str = "",
) -> tuple[list[_T], list[ArchiveError]]:
    """Separate results into successes and ArchiveErrors.

    Re-raises non-Exception BaseExceptions (e.g. KeyboardInterrupt,
    SystemExit) as a BaseExceptionGroup.
    """
    base_exceptions = [r for r in results if isinstance(r, BaseException)]
    exceptions = [e for e in base_exceptions if isinstance(e, Exception)]
    non_exceptions = [e for e in base_exceptions if not isinstance(e, Exception)]
    if non_exceptions:
        raise BaseExceptionGroup(f"Error during {phase}", non_exceptions)
    errors = [
        ArchiveError(phase=phase, title=title, message=str(e)) for e in exceptions
    ]
    successful = [r for r in results if not isinstance(r, BaseException)]
    return successful, errors


async def _with_retry[_T](
    fn: Callable[[], Awaitable[_T | BaseException]],
    max_retries: int,
    retry_delay: float,
    phase: str,
) -> _T | BaseException:
    """Execute ``fn`` with exponential backoff + jitter up to ``max_retries``.

    Retries only when ``fn`` returns an ``Exception`` (not
    ``BaseException``). The delay doubles each retry with ±10% jitter.
    """
    attempt = 0
    while True:
        result = await fn()
        if not isinstance(result, BaseException):
            return result
        if attempt < max_retries:
            delay = retry_delay * (2**attempt)
            delay += delay * 0.1 * (_random() - 0.5)  # ±10 % jitter
            LOGGER.info("Retrying %s (attempt %d/%d)", phase, attempt + 1, max_retries)
            await sleep(delay)
            attempt += 1
        else:
            return result


async def archive(args: Args) -> ArchiveResult:
    """Primary coroutine implementing the query-fetch-index flow.

    Executes the following steps:
    1. Query Wikimedia Commons for page and image metadata for requested inputs.
    2. Fetch image binary content for the discovered pages.
    3. Optionally update a Markdown index file using `_index_formatter`.

    Returns an ``ArchiveResult`` with download/skip counts and any errors
    encountered during the operation. Does not call ``exit()``.
    """
    downloaded = 0
    skipped = 0
    all_errors: list[ArchiveError] = []

    try:
        inputs = tuple(dict.fromkeys(args.inputs))
        async with ClientSession(
            connector=TCPConnector(limit_per_host=_MAX_CONCURRENT_REQUESTS_PER_HOST),
            headers={
                "Accept-Encoding": "gzip",
                "User-Agent": USER_AGENT,
            },
            timeout=ClientTimeout(total=args.request_timeout),
        ) as sess:
            try:
                LOGGER.info(f"Querying {len(inputs)} files")

                async def query(
                    inputs: Iterable[str],
                ) -> Iterable[tuple[str, Page]] | BaseException:
                    """Query the Wikimedia Commons API for the given titles and
                    return the parsed pages items, or the exception if the query
                    fails.
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
                # the ``SoonValue`` objects capture return values that we can
                # inspect after the task group closes (see Asyncer documentation).
                svs: list[SoonValue[Iterable[tuple[str, Page]] | BaseException]] = []
                async with create_task_group() as tg:
                    for idx in range(0, len(inputs), _QUERY_LIMIT):
                        svs.append(
                            tg.soonify(_with_retry)(
                                lambda batch=inputs[idx : idx + _QUERY_LIMIT]: query(
                                    batch
                                ),
                                args.max_retries,
                                args.retry_delay,
                                "query",
                            )
                        )
                # at this point the task group has exited and all queries have
                # completed; we can safely access ``.value`` on each SoonValue.
                queries = [sv.value for sv in svs]
                queries, query_errors = _separate_results(queries, phase="query")
                all_errors.extend(query_errors)
                if not queries:
                    return ArchiveResult(
                        downloaded=0, skipped=0, errors=tuple(all_errors)
                    )
                # ``id`` is a builtin, so rename to ``page_id`` for clarity and
                # to keep static type checkers happy with an explicit variable
                # name.
                pages = tuple(
                    {
                        page_id: page for page_id, page in chain.from_iterable(queries)
                    }.values()
                )
            except Exception:
                LOGGER.exception("Error querying")
                all_errors.append(
                    ArchiveError(phase="query", title="", message="Error querying")
                )
                return ArchiveResult(downloaded=0, skipped=0, errors=tuple(all_errors))
            try:
                LOGGER.info(f"Fetching {len(pages)} files")

                async def fetch(page: Page) -> tuple[str, str, bool] | BaseException:
                    """Download the binary content for ``page`` and return a tuple
                    of ``(filename, index_line, was_skipped)``, or the exception
                    if the fetch fails.
                    """
                    try:
                        filename = page.title.split(":", 1)[-1]
                        # Input validation: reject empty, path separators, or
                        # dot-directories
                        if not filename or "/" in filename or filename in (".", ".."):
                            return ValueError(
                                f"Invalid filename derived from title: '{page.title}'"
                            )
                        if page.imageinfo is None:
                            raise ValueError(f"Failed to fetch '{filename}'")
                        dest_path = args.dest
                        await dest_path.mkdir(parents=True, exist_ok=True)
                        dest_file = dest_path / filename
                        # Skip existing files when skip_existing is True
                        if args.skip_existing and await dest_file.exists():
                            LOGGER.info("Skipping existing '%s'", filename)
                            credit = await asyncify(_credit_formatter)(page)
                            index_line = await asyncify(_index_formatter)(
                                filename, credit
                            )
                            return filename, index_line, True
                        async with (
                            sess.get(page.imageinfo[0].url) as resp,
                            await dest_file.open(mode="wb") as file,
                        ):
                            LOGGER.info("Fetching '%s'", filename)
                            async for chunk in resp.content.iter_any():
                                await file.write(chunk)
                        credit = await asyncify(_credit_formatter)(page)
                        index_line = await asyncify(_index_formatter)(filename, credit)
                        return filename, index_line, False
                    except BaseException as e:
                        return e

                if args.progress_callback is not None:
                    args.progress_callback(0, len(pages))
                # fetch pages concurrently, capturing their return values with
                # SoonValue so we can access them after the task group exits.
                fetch_svs: list[SoonValue[tuple[str, str, bool] | BaseException]] = []
                async with create_task_group() as tg:
                    for page in pages:
                        fetch_svs.append(
                            tg.soonify(_with_retry)(
                                lambda p=page: fetch(p),
                                args.max_retries,
                                args.retry_delay,
                                "fetch",
                            )
                        )
                raw_entries = [sv.value for sv in fetch_svs]
                raw_entries, fetch_errors = _separate_results(
                    raw_entries, phase="fetch"
                )
                all_errors.extend(fetch_errors)
                entries: list[tuple[str, str]] = []
                for filename, index_line, was_skipped in raw_entries:
                    if was_skipped:
                        skipped += 1
                    else:
                        downloaded += 1
                    entries.append((filename, index_line))
                if args.progress_callback is not None:
                    args.progress_callback(downloaded, len(pages))
            except Exception:
                LOGGER.info("Error fetching")
                all_errors.append(
                    ArchiveError(phase="fetch", title="", message="Error fetching")
                )
                return ArchiveResult(
                    downloaded=downloaded,
                    skipped=skipped,
                    errors=tuple(all_errors),
                )
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
                all_errors.append(
                    ArchiveError(phase="index", title="", message="Error indexing")
                )
    except Exception:
        LOGGER.exception("Error")
        all_errors.append(ArchiveError(phase="general", title="", message="Error"))

    return ArchiveResult(
        downloaded=downloaded,
        skipped=skipped,
        errors=tuple(all_errors),
    )
