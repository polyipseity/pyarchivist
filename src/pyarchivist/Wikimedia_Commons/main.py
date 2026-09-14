"""Wikimedia Commons archive implementation.

This module implements the query, fetch and indexing flow for files on
Wikimedia Commons. It provides a top-level `archive` coroutine and the
library-oriented API. Helper utilities and small types used across the flow
are declared here as well.
"""

from collections.abc import Collection, Iterable
from html import escape as html_escape
from itertools import chain
from re import MULTILINE, compile
from typing import TypeVar, override
from urllib.parse import quote, unquote

from aiohttp import ClientSession, ClientTimeout, TCPConnector
from aiohttp_retry import JitterRetry, RetryClient
from asyncer import SoonValue, asyncify, create_task_group
from pathvalidate import sanitize_filename
from yarl import URL

from pyarchivist.meta import LOGGER, OPEN_TEXT_OPTIONS, USER_AGENT
from pyarchivist.types import ArchiveError, ArchiveResult, Args

from .models import Page, ResponseModel

"""Public symbols exported by this module."""
__all__ = ("archive",)

"""Maximum concurrent HTTP requests per host for the aiohttp connector."""
_MAX_CONCURRENT_REQUESTS_PER_HOST = 1
"""Characters left unescaped in URL percent-encoding for Commons URLs."""
_PERCENT_ESCAPE_SAFE = "/,"
"""Number of page titles per API query batch."""
_QUERY_LIMIT = 50
"""Type variable for generic helpers in this module."""
_T = TypeVar("_T")

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


def _index_formatter(filename: str, credit: str, *, display: str | None = None):
    """Format a Markdown index line for a file and its credit string.

    *filename* is URL-escaped for the link target.  *display* (when given)
    is used as the visible link text; when omitted the *filename* is used
    instead.  The returned string is suitable for appending to an
    ``index.md`` paragraph handled by the indexing logic.
    """

    escaped = (display or filename).replace("\\", "\\\\").replace("]", "\\]")
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


class _WikimediaRetry(JitterRetry):
    """Exponential retry that reads the Retry-After header from 429 responses."""

    @override
    def get_timeout(self, attempt: int, response=None) -> float:
        """Return the delay before the next retry attempt.

        Reads the ``Retry-After`` header from 429 responses when available,
        falling back to the parent class exponential backoff.
        """
        if response is not None and response.status == 429:
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    return max(float(retry_after), self._start_timeout)
                except ValueError:
                    pass
        return super().get_timeout(attempt, response)


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
            connector=TCPConnector(limit_per_host=1),
            headers={
                "Accept-Encoding": "gzip",
                "User-Agent": USER_AGENT,
            },
            timeout=ClientTimeout(total=args.request_timeout),
        ) as raw_sess:
            sess = RetryClient(
                client_session=raw_sess,
                retry_options=_WikimediaRetry(
                    attempts=args.max_retries,
                    start_timeout=args.retry_delay,
                    max_timeout=30.0,
                    statuses={429},
                ),
                raise_for_status=False,
            )
            try:
                LOGGER.info(f"Querying {len(inputs)} files")

                async def query(
                    inputs: Iterable[str],
                ) -> Iterable[tuple[str, Page]] | BaseException:
                    """Query the Wikimedia Commons API for the given titles.

                    RetryClient handles HTTP retries (429, 5xx) at session level.
                    """
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

                svs: list[SoonValue[Iterable[tuple[str, Page]] | BaseException]] = []
                async with create_task_group() as tg:
                    for idx in range(0, len(inputs), _QUERY_LIMIT):
                        svs.append(
                            tg.soonify(query)(tuple(inputs[idx : idx + _QUERY_LIMIT]))
                        )
                queries = [sv.value for sv in svs]
                queries, query_errors = _separate_results(queries, phase="query")
                all_errors.extend(query_errors)
                if not queries:
                    return ArchiveResult(
                        downloaded=0, skipped=0, errors=tuple(all_errors)
                    )
                pages = tuple(
                    {
                        page_id: page for page_id, page in chain.from_iterable(queries)
                    }.values()
                )

                LOGGER.info(f"Fetching {len(pages)} files")

                async def fetch(page: Page) -> tuple[str, str, str, bool]:
                    """Download the binary content for ``page``.

                    Returns ``(page_title, filename, index_line, was_skipped)``.
                    RetryClient handles HTTP retries (429, 5xx) at session level.
                    """
                    page_display = page.title.split(":", 1)[-1]
                    filename = page_display
                    if args.sanitize_filenames:
                        filename = sanitize_filename(
                            filename, platform="windows", replacement_text="_"
                        )
                    if not filename or "/" in filename or filename in (".", ".."):
                        raise ValueError(
                            f"Invalid filename derived from title: '{page.title}'"
                        )
                    if page.imageinfo is None:
                        raise ValueError(f"Failed to fetch '{filename}'")
                    dest_path = args.dest
                    await dest_path.mkdir(parents=True, exist_ok=True)
                    dest_file = dest_path / filename
                    if args.skip_existing and await dest_file.exists():
                        LOGGER.info("Skipping existing '%s'", filename)
                        credit = await asyncify(_credit_formatter)(page)
                        index_line = await asyncify(_index_formatter)(
                            filename, credit, display=page_display
                        )
                        return page_display, filename, index_line, True
                    async with sess.get(page.imageinfo[0].url) as resp:
                        if resp.status >= 400:
                            raise ValueError(
                                f"HTTP {resp.status} fetching '{filename}'"
                            )
                        content_type = resp.content_type or ""
                        if not content_type.startswith(
                            ("image/", "application/octet-stream", "video/", "audio/")
                        ):
                            raise ValueError(
                                f"Unexpected content-type {content_type!r} for '{filename}'"
                            )
                        LOGGER.info("Fetching '%s'", filename)
                        async with await dest_file.open(mode="wb") as file:
                            async for chunk in resp.content.iter_any():
                                await file.write(chunk)
                    credit = await asyncify(_credit_formatter)(page)
                    index_line = await asyncify(_index_formatter)(
                        filename, credit, display=page_display
                    )
                    return page_display, filename, index_line, False

                if args.progress_callback is not None:
                    args.progress_callback(0, len(pages))
                fetch_svs: list[SoonValue[tuple[str, str, str, bool]]] = []
                async with create_task_group() as tg:
                    for page in pages:
                        fetch_svs.append(tg.soonify(fetch)(page))
                raw_entries = [sv.value for sv in fetch_svs]
                entries: list[tuple[str, str, str]] = []
                for page_title, filename, index_line, was_skipped in raw_entries:
                    if was_skipped:
                        skipped += 1
                    else:
                        downloaded += 1
                    entries.append((page_title, filename, index_line))
                if args.progress_callback is not None:
                    args.progress_callback(downloaded, len(pages))

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
                        for page_title, _filename, entry in entries:
                            index[page_title] = entry
                        paragraphs[-1] = "\n".join(
                            value
                            for _, value in sorted(
                                index.items(), key=lambda item: item[0]
                            )
                        )
                        text = "\n\n".join(paragraphs) + "\n"
                        await file.write(text)
                        await file.truncate()
            finally:
                await sess.close()
    except Exception:
        LOGGER.exception("Error")
        all_errors.append(ArchiveError(phase="general", title="", message="Error"))

    return ArchiveResult(
        downloaded=downloaded,
        skipped=skipped,
        errors=tuple(all_errors),
    )
