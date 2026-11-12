"""Query, download and index files from Wikimedia Commons.

The flow has three phases: query the API for page metadata, fetch each file into
the destination directory, and merge the resulting lines into an optional
Markdown index. Every phase isolates failures per item, so one bad title or one
broken transfer does not discard the work done for the others.
"""

from collections.abc import Iterable, Sequence
from html import escape as html_escape
from re import MULTILINE, compile
from typing import NamedTuple, override
from urllib.parse import quote, unquote

from aiohttp import (
    ClientConnectionError,
    ClientPayloadError,
    ClientSession,
    ClientTimeout,
    TCPConnector,
)
from aiohttp_retry import JitterRetry, RetryClient
from anyio import CancelScope, Path
from asyncer import SoonValue, asyncify, create_task_group
from pathvalidate import sanitize_filename
from yarl import URL

from pyarchivist.meta import LOGGER, OPEN_TEXT_OPTIONS, USER_AGENT
from pyarchivist.types import ArchiveError, ArchiveResult, Args

from .models import ImageInfoEntry, Page, ResponseModel

"""Public symbols exported by this module."""
__all__ = ("archive",)

"""Maximum concurrent HTTP requests per host for the aiohttp connector."""
_MAX_CONCURRENT_REQUESTS_PER_HOST = 1
"""Characters left unescaped in URL percent-encoding for Commons URLs."""
_PERCENT_ESCAPE_SAFE = "/,"
"""Number of page titles per API query batch."""
_QUERY_LIMIT = 50
"""Content types that indicate an error document rather than media bytes."""
_DOCUMENT_CONTENT_TYPES = frozenset(("application/xhtml+xml", "text/html"))
"""Content types a server may send when it serves a file without its own MIME."""
_GENERIC_CONTENT_TYPES = frozenset(("application/octet-stream", "binary/octet-stream"))
"""Matches HTML-like tags stripped from credit metadata."""
_HTML_TAG_PATTERN = compile(r"<[^>]*>", MULTILINE)
"""Collapses whitespace runs in credit metadata."""
_WHITESPACE_PATTERN = compile(r"\s+")
"""Regex matching index.md lines: - [display](url): credit."""
_INDEX_FORMAT_PATTERN = compile(r"^- \[(.+?(?<!\\))]\((.+?(?<!\\))\): (.+)$", MULTILINE)


class _QueryHTTPError(ValueError):
    """Query failure carrying the HTTP status that caused it."""

    status: int

    def __init__(self, status: int, message: str) -> None:
        """Store the status alongside the usual exception message."""
        super().__init__(message)
        self.status = status


def _fails_whole_batch(exc: BaseException) -> bool:
    """Return whether splitting the batch would only repeat the same failure.

    A dropped connection, a timeout or a server error answers every smaller
    batch the same way, so bisecting an outage turns one failed request into
    roughly twice as many.
    """
    if isinstance(exc, _QueryHTTPError):
        return exc.status >= 500
    return isinstance(exc, (OSError, ClientConnectionError, ClientPayloadError))


async def _query(
    sess: RetryClient, inputs: Sequence[str]
) -> Iterable[tuple[str, Page]]:
    """Query the Wikimedia Commons API for one batch of titles.

    ``mime`` and ``size`` are requested with the URL so a download can be
    verified against what the API says the file is. ``RetryClient`` handles
    429/5xx at session level.
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
                "iiprop": "extmetadata|mime|size|url",
            },
        )
    ) as resp:
        if resp.status >= 400:
            raise _QueryHTTPError(
                resp.status, f"HTTP {resp.status} querying {len(inputs)} titles"
            )
        text = await resp.text()
    return ResponseModel.model_validate_json(text).query.pages.items()


async def _query_with_bisect(
    sess: RetryClient, inputs: Sequence[str], *, bisect: bool
) -> tuple[list[tuple[str, Page]], list[ArchiveError]]:
    """Query a batch, isolating failing titles by halving it.

    A failed batch reports one error for every title in it; splitting until each
    failing title stands alone keeps one bad input from failing its
    batch-mates. Failures are rare, so halving sequentially is cheaper than the
    machinery needed to do it concurrently. Failures that would repeat at any
    batch size are reported without splitting.
    """
    try:
        return list(await _query(sess, inputs)), []
    except Exception as exc:
        if not bisect or len(inputs) < 2 or _fails_whole_batch(exc):
            return [], [
                ArchiveError(phase="query", title=", ".join(inputs), message=str(exc))
            ]
        middle = len(inputs) // 2
        left_pages, left_errors = await _query_with_bisect(
            sess, inputs[:middle], bisect=bisect
        )
        right_pages, right_errors = await _query_with_bisect(
            sess, inputs[middle:], bisect=bisect
        )
        return left_pages + right_pages, left_errors + right_errors


def _index_formatter(filename: str, credit: str, *, display: str | None = None) -> str:
    """Format a Markdown index line for a file and its credit string.

    ``filename`` is URL-escaped for the link target and used as the link text
    unless ``display`` overrides it.
    """
    escaped = (display or filename).replace("\\", "\\\\").replace("]", "\\]")
    return f"- [{escaped}]({quote(filename, safe=_PERCENT_ESCAPE_SAFE)}): {credit}"


def _credit_formatter(page: Page) -> str:
    """Produce the credit fragment for a page from its extended metadata.

    Author and license short names have embedded HTML stripped and whitespace
    collapsed; markers such as ``Unknown author`` fall back to a link to the
    description page.
    """
    assert page.imageinfo is not None

    ii = page.imageinfo[0]
    emd = ii.extmetadata

    raw_author = ""
    if emd and emd.Artist and emd.Artist.value:
        raw_author = emd.Artist.value
    author = _HTML_TAG_PATTERN.sub("", raw_author)
    author = _WHITESPACE_PATTERN.sub(" ", author.replace("\n", " ")).strip()
    if "Unknown author".casefold() in author.casefold():
        author = ""

    raw_lic = ""
    if emd and emd.LicenseShortName and emd.LicenseShortName.value:
        raw_lic = emd.LicenseShortName.value
    lic = _HTML_TAG_PATTERN.sub("", raw_lic)
    lic = _WHITESPACE_PATTERN.sub(" ", lic.replace("\n", " ")).strip()
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


class _Fetched(NamedTuple):
    """Outcome of a file that was downloaded or deliberately skipped."""

    display: str
    filename: str
    index_line: str
    skipped: bool


def _resolve_filename(page: Page, *, sanitize: bool) -> tuple[str, str]:
    """Return the ``(display, filename)`` pair a page is archived under."""
    display = page.title.split(":", 1)[-1]
    filename = display
    if sanitize:
        filename = sanitize_filename(filename, platform="windows", replacement_text="_")
    if not filename or "/" in filename or filename in (".", ".."):
        raise ValueError(f"Invalid filename derived from title: '{page.title}'")
    return display, filename


def _plan_targets(
    pages: Iterable[Page], *, dest: Path, sanitize: bool
) -> tuple[list[tuple[Page, str, str, Path]], list[ArchiveError]]:
    """Resolve one destination per page and reject titles that collide.

    Sanitizing different titles can map them onto one filename, and a
    case-insensitive filesystem treats letter case as the same name; two
    concurrent downloads to one path would interleave their bytes, so the later
    page is rejected instead of racing the first.
    """
    targets: list[tuple[Page, str, str, Path]] = []
    errors: list[ArchiveError] = []
    claimed: dict[str, str] = {}
    for page in pages:
        try:
            display, filename = _resolve_filename(page, sanitize=sanitize)
        except ValueError as exc:
            errors.append(
                ArchiveError(phase="fetch", title=page.title, message=str(exc))
            )
            continue
        owner = claimed.setdefault(filename.casefold(), page.title)
        if owner != page.title:
            errors.append(
                ArchiveError(
                    phase="fetch",
                    title=page.title,
                    message=f"Filename '{filename}' is already used by '{owner}'",
                )
            )
            continue
        targets.append((page, display, filename, dest / filename))
    return targets, errors


def _mime_consistent(api_mime: str, content_type: str) -> bool:
    """Return whether a response content type agrees with the API-declared MIME.

    ``content_type`` is aiohttp's parsed, lower-cased header value, or
    ``application/octet-stream`` when the header is absent, so a generic value
    carries no information and always agrees.
    """
    return api_mime.lower() == content_type or content_type in _GENERIC_CONTENT_TYPES


async def _is_complete(dest_file: Path, ii: ImageInfoEntry) -> bool:
    """Return whether an existing file is a complete earlier download.

    Comparing against the size the API reports turns skipping into an integrity
    check; with no API size only a non-empty file counts, because an empty file
    is never media.
    """
    try:
        stored = (await dest_file.stat()).st_size
    except FileNotFoundError:
        return False
    if ii.size is None:
        return stored > 0
    return stored == ii.size


async def _download(
    sess: RetryClient, page: Page, dest_file: Path, *, filename: str
) -> None:
    """Download a page's file, replacing *dest_file* only when complete.

    Bytes stream into ``<filename>.part`` and the target name is replaced on
    success, so a failed or cancelled transfer never leaves a truncated file
    under the real name. A killed process can leave that ``.part`` behind; it
    never shadows the target and the next attempt overwrites it.
    """
    assert page.imageinfo is not None
    ii = page.imageinfo[0]
    part = dest_file.with_name(f"{dest_file.name}.part")
    try:
        async with sess.get(ii.url) as resp:
            if resp.status >= 400:
                raise ValueError(f"HTTP {resp.status} fetching '{filename}'")
            if resp.content_type in _DOCUMENT_CONTENT_TYPES:
                raise ValueError(
                    f"Unexpected content-type {resp.content_type!r} for '{filename}'"
                )
            if ii.mime is not None and not _mime_consistent(ii.mime, resp.content_type):
                LOGGER.warning(
                    "Content-type %r differs from API mime %r for '%s'",
                    resp.content_type,
                    ii.mime,
                    filename,
                )
            written = 0
            async with await part.open(mode="wb") as file:
                async for chunk in resp.content.iter_any():
                    written += len(chunk)
                    await file.write(chunk)
        if written == 0:
            raise ValueError(f"Empty body for '{filename}'")
        if ii.size is not None and written != ii.size:
            raise ValueError(
                f"Size mismatch for '{filename}': wrote {written} bytes, "
                f"API reports {ii.size}"
            )
        await part.replace(dest_file)
    except BaseException:
        # Shielded: a cancelled scope would otherwise fail the unlink at its first
        # checkpoint and leave the partial bytes behind.
        with CancelScope(shield=True):
            await part.unlink(missing_ok=True)
        raise


async def _fetch_one(
    sess: RetryClient,
    page: Page,
    dest_file: Path,
    *,
    display: str,
    filename: str,
    skip_existing: bool,
) -> _Fetched:
    """Download or skip one page and build its index line."""
    if page.missing is not None:
        raise ValueError(f"'{page.title}' does not exist on Wikimedia Commons")
    if page.invalidreason is not None:
        raise ValueError(f"'{page.title}' is not a valid title: {page.invalidreason}")
    if page.imageinfo is None:
        raise ValueError(f"No image info for '{page.title}'")
    ii = page.imageinfo[0]
    skipped = False
    if skip_existing and await _is_complete(dest_file, ii):
        LOGGER.info("Skipping existing '%s'", filename)
        skipped = True
    else:
        LOGGER.info("Fetching '%s'", filename)
        await _download(sess, page, dest_file, filename=filename)
    credit = await asyncify(_credit_formatter)(page)
    index_line = await asyncify(_index_formatter)(filename, credit, display=display)
    return _Fetched(display, filename, index_line, skipped)


async def _update_index(index: Path, entries: Sequence[tuple[str, str]]) -> None:
    """Merge *entries* into the last paragraph of *index*, writing atomically.

    Entries are keyed by the case-folded on-disk filename because that is what an
    existing line encodes in its link target; keying by the display title would
    append a second line for a file that sanitization renamed, and a case-only
    variant of the same name would add one too. Folding also means one line per
    name on a case-insensitive filesystem, so a later case-variant title drops
    the earlier line even when both files exist on a case-sensitive one. Lines in
    the last paragraph that are not entries are hoisted to its top. Rewriting
    through a sibling temp file keeps the index intact if the process dies
    mid-write.
    """
    await index.parent.mkdir(parents=True, exist_ok=True)
    try:
        text = await index.read_text(
            encoding=OPEN_TEXT_OPTIONS["encoding"],
            errors=OPEN_TEXT_OPTIONS["errors"],
        )
    except FileNotFoundError:
        text = ""
    paragraphs = text.strip().split("\n\n")
    by_name: dict[str, str] = {}
    kept: list[str] = []
    for line in paragraphs[-1].splitlines():
        match = _INDEX_FORMAT_PATTERN.match(line)
        if match is None:
            kept.append(line)
        else:
            by_name[unquote(match[2]).casefold()] = match[0]
    by_name.update((filename.casefold(), line) for filename, line in entries)
    paragraphs[-1] = "\n".join([*kept, *(line for _, line in sorted(by_name.items()))])
    temporary = index.with_name(f".{index.name}.tmp")
    try:
        await temporary.write_text("\n\n".join(paragraphs) + "\n", **OPEN_TEXT_OPTIONS)
        await temporary.replace(index)
    except BaseException:
        with CancelScope(shield=True):
            try:
                await temporary.unlink(missing_ok=True)
            except OSError:
                # Keep the write or replace failure as the reported cause.
                pass
        raise


async def archive(args: Args) -> ArchiveResult:
    """Run the query-fetch-index flow and report what it achieved.

    Query and fetch failures are collected per item, so a failure never hides
    the files that did transfer. Returns an ``ArchiveResult`` with the download
    and skip counts plus every error; does not call ``exit()``.
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
            timeout=ClientTimeout(
                total=None,
                sock_connect=args.request_timeout,
                sock_read=args.request_timeout,
            ),
            trust_env=args.trust_env,
        ) as raw_sess:
            sess = RetryClient(
                client_session=raw_sess,
                retry_options=_WikimediaRetry(
                    attempts=args.max_retries,
                    start_timeout=args.retry_delay,
                    max_timeout=30.0,
                    statuses={429},
                    exceptions={ClientConnectionError, ClientPayloadError},
                ),
                raise_for_status=False,
            )
            try:
                LOGGER.info(f"Querying {len(inputs)} files")
                query_svs: list[
                    SoonValue[tuple[list[tuple[str, Page]], list[ArchiveError]]]
                ] = []
                async with create_task_group() as tg:
                    for idx in range(0, len(inputs), _QUERY_LIMIT):
                        query_svs.append(
                            tg.soonify(_query_with_bisect)(
                                sess,
                                tuple(inputs[idx : idx + _QUERY_LIMIT]),
                                bisect=args.bisect_queries,
                            )
                        )
                pages_by_id: dict[str, Page] = {}
                for batch_pages, batch_errors in (sv.value for sv in query_svs):
                    all_errors.extend(batch_errors)
                    pages_by_id.update(batch_pages)
                if not pages_by_id:
                    return ArchiveResult(
                        downloaded=0, skipped=0, errors=tuple(all_errors)
                    )
                pages = tuple(pages_by_id.values())

                LOGGER.info(f"Fetching {len(pages)} files")
                await args.dest.mkdir(parents=True, exist_ok=True)
                targets, target_errors = _plan_targets(
                    pages, dest=args.dest, sanitize=args.sanitize_filenames
                )
                all_errors.extend(target_errors)

                async def fetch(
                    page: Page, dest_file: Path, *, display: str, filename: str
                ) -> _Fetched | ArchiveError:
                    """Run one fetch, converting a failure into reportable data."""
                    try:
                        return await _fetch_one(
                            sess,
                            page,
                            dest_file,
                            display=display,
                            filename=filename,
                            skip_existing=args.skip_existing,
                        )
                    except Exception as exc:
                        LOGGER.warning("Error fetching '%s': %s", filename, exc)
                        return ArchiveError(
                            phase="fetch", title=display, message=str(exc)
                        )

                entries: list[tuple[str, str]] = []
                aborted = False
                if args.fail_fast:
                    for page, display, filename, dest_file in targets:
                        item = await fetch(
                            page, dest_file, display=display, filename=filename
                        )
                        if isinstance(item, ArchiveError):
                            all_errors.append(item)
                            aborted = True
                            LOGGER.warning("Aborted after the first fetch error")
                            break
                        if item.skipped:
                            skipped += 1
                        else:
                            downloaded += 1
                        entries.append((item.filename, item.index_line))
                else:
                    fetch_svs: list[SoonValue[_Fetched | ArchiveError]] = []
                    async with create_task_group() as tg:
                        for page, display, filename, dest_file in targets:
                            fetch_svs.append(
                                tg.soonify(fetch)(
                                    page, dest_file, display=display, filename=filename
                                )
                            )
                    for item in (sv.value for sv in fetch_svs):
                        if isinstance(item, ArchiveError):
                            all_errors.append(item)
                            continue
                        if item.skipped:
                            skipped += 1
                        else:
                            downloaded += 1
                        entries.append((item.filename, item.index_line))

                if args.index is None:
                    LOGGER.info("Skipped indexing")
                elif entries and not aborted:
                    LOGGER.info(f"Indexing {len(entries)} files")
                    try:
                        await _update_index(args.index, entries)
                    except (OSError, UnicodeError) as exc:
                        all_errors.append(
                            ArchiveError(phase="index", title="", message=str(exc))
                        )
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
