from .. import (
    LOGGER as _LOGGER,
    OPEN_TEXT_OPTIONS as _OPEN_TXT_OPTS,
    USER_AGENT as _U_AG,
    VERSION as _VER,
)
from aiohttp import ClientSession as _CliSess, TCPConnector as _TCPConn
from anyio import Path as _Path
from argparse import (
    ArgumentParser as _ArgParser,
    Namespace as _NS,
    ONE_OR_MORE as _ONE_OR_MORE,
)
from asyncio import create_task, gather as _gather
from dataclasses import dataclass as _dc
from enum import IntFlag as _IntFlag, auto as _auto, unique as _unq
from functools import partial as _part, wraps as _wraps
from html2text import HTML2Text as _HTM2TXT
from itertools import chain as _chain
from json import loads as _loads
from re import MULTILINE as _MULTILINE, compile as _re_comp
from sys import exit as _exit
from types import SimpleNamespace as _SimpNS
from typing import (
    Callable as _Call,
    ClassVar as _ClsVar,
    Collection as _Coll,
    Generic as _Generic,
    Iterable as _Iter,
    Mapping as _Map,
    Protocol as _Proto,
    Sequence as _Seq,
    TypeVar as _TVar,
    cast as _cast,
    final as _fin,
)
from urllib.parse import unquote as _pct_unesc, quote as _pct_esc
from yarl import URL as _URL

_MAX_CONCURRENT_REQUESTS_PER_HOST = 1
_PERCENT_ESCAPE_SAFE = "/,"
_QUERY_LIMIT = 50
_T = _TVar("_T")


@_fin
@_unq
class ExitCode(_IntFlag):
    __slots__: _ClsVar = ()

    GENERIC_ERROR = _auto()
    QUERY_ERROR = _auto()
    FETCH_ERROR = _auto()
    INDEX_ERROR = _auto()
    QUERY_ERROR_PARTIAL = _auto()
    FETCH_ERROR_PARTIAL = _auto()


@_fin
@_dc(
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
    inputs: _Seq[str]
    dest: _Path
    index: _Path | None
    ignore_individual_errors: bool

    def __post_init__(self):
        object.__setattr__(self, "inputs", tuple(self.inputs))


@_fin
class _JSONDict(_SimpNS, _Generic[_T]):
    __slots__: _ClsVar = ()

    def __init__(self, dict: _Map[str, _T]):
        super().__init__(**dict)

    def __getattr__(self, name: str):
        try:
            return getattr(self.__dict__, name)
        except AttributeError:
            return None

    def __getitem__(self, key: str):
        return getattr(self, key)


@_fin
class _Response(_Proto):
    __slots__: _ClsVar = ()

    @_fin
    class Value(_Proto):
        __slots__: _ClsVar = ()

        @property
        def value(self) -> str: ...

        @property
        def source(self) -> str: ...

    @_fin
    class ExtMetadata(_Proto):
        __slots__: _ClsVar = ()

        @property
        def Artist(self) -> "_Response.Value | None": ...

        @property
        def LicenseShortName(self) -> "_Response.Value | None": ...

        @property
        def LicenseUrl(self) -> "_Response.Value | None": ...

    @_fin
    class ImageInfoEntry(_Proto):
        __slots__: _ClsVar = ()

        @property
        def descriptionurl(self) -> str: ...

        @property
        def extmetadata(self) -> "_Response.ExtMetadata": ...

        @property
        def url(self) -> str: ...

    @_fin
    class Page(_Proto):
        __slots__: _ClsVar = ()

        @property
        def title(self) -> str: ...

        @property
        def imageinfo(self) -> "_Seq[_Response.ImageInfoEntry] | None": ...

    @_fin
    class Query(_Proto):
        __slots__: _ClsVar = ()

        @property
        def pages(self) -> "_Map[str, _Response.Page]": ...

    query: Query


_INDEX_FORMAT_PATTERN = _re_comp(
    r"^- \[(.+?(?<!\\))]\((.+?(?<!\\))\): (.+)$", _MULTILINE
)


def _handle_partial_errors(
    results: _Coll[_T | BaseException],
    *,
    ignore_individual_errors: bool,
    error_message: str = "Error",
) -> tuple[bool, _Coll[_T]]:
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
            _LOGGER.exception(error_message)
            error = True
    return error, tuple(
        result for result in results if not isinstance(result, BaseException)
    )


def _index_formatter(filename: str, credit: str):
    escaped = filename.replace("\\", "\\\\").replace("]", "\\]")
    return f"- [{escaped}]({_pct_esc(filename, safe=_PERCENT_ESCAPE_SAFE)}): {credit}"


def _credit_formatter(page: _Response.Page):
    assert page.imageinfo is not None

    htm_esc = _HTM2TXT()
    htm_esc.emphasis_mark = "_"
    htm_esc.ignore_links = True
    htm_esc.single_line_break = True
    htm_esc.strong_mark = "__"
    htm_esc.ul_item_mark = "-"

    ii = page.imageinfo[0]
    emd = ii.extmetadata
    author = htm_esc.handle(emd.Artist.value).strip() if emd.Artist else ""
    if "Unknown author".casefold() in author.casefold():
        author = ""
    lic = emd.LicenseShortName.value if emd.LicenseShortName else ""
    if "Unknown license".casefold() in lic.casefold():
        lic = ""
    lic_url = emd.LicenseUrl.value if lic and emd.LicenseUrl else ""
    lic_lnk = "".join(
        (
            f'<a href="{lic_url}">' if lic_url else "",
            lic.replace("\n", "") or "See page for license",
            "</a>" if lic_url else "",
        )
    )
    author = author.replace("\n", "") or "See page for author"
    return (
        f'<a href="{ii.descriptionurl}">{author}</a>, {lic_lnk}, via Wikimedia Commons'
    )


async def main(args: Args):
    ec = ExitCode(0)

    try:
        inputs = tuple(dict.fromkeys(args.inputs))
        async with _CliSess(
            connector=_TCPConn(limit_per_host=_MAX_CONCURRENT_REQUESTS_PER_HOST),
            headers={
                "Accept-Encoding": "gzip",
                "User-Agent": _U_AG,
            },
        ) as sess:
            try:
                _LOGGER.info(f"Querying {len(inputs)} files")

                async def query(inputs: _Iter[str]):
                    async with sess.get(
                        _URL.build(
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
                        data: _Response = await resp.json(
                            loads=_part(_loads, object_hook=_JSONDict)
                        )
                    return data.query.pages.items()

                queries = await _gather(
                    *map(
                        lambda idx: query(inputs[idx : idx + _QUERY_LIMIT]),
                        range(0, len(inputs), _QUERY_LIMIT),
                    ),
                    return_exceptions=True,
                )
                error, queries = _handle_partial_errors(
                    queries,
                    ignore_individual_errors=args.ignore_individual_errors,
                    error_message="Error querying",
                )
                if error:
                    ec |= ExitCode.QUERY_ERROR_PARTIAL
                pages = tuple(
                    {id: page for id, page in _chain.from_iterable(queries)}.values()
                )
            except Exception:
                _LOGGER.exception("Error querying")
                ec |= ExitCode.QUERY_ERROR
                raise
            try:
                _LOGGER.info(f"Fetching {len(pages)} files")

                async def fetch(page: _Response.Page):
                    filename = page.title.split(":", 1)[-1]
                    if page.imageinfo is None:
                        raise ValueError(f"Failed to fetch '{filename}'")
                    async with (
                        sess.get(page.imageinfo[0].url) as resp,
                        await (args.dest / filename).open(mode="wb") as file,
                    ):
                        _LOGGER.info(f"Fetching '{filename}'")
                        async for chunk in resp.content.iter_any():
                            await file.write(chunk)
                    return filename, _index_formatter(filename, _credit_formatter(page))

                entries = await _gather(*map(fetch, pages), return_exceptions=True)
                error, entries = _handle_partial_errors(
                    entries,
                    ignore_individual_errors=args.ignore_individual_errors,
                    error_message="Error fetching",
                )
                if error:
                    ec |= ExitCode.FETCH_ERROR_PARTIAL
            except Exception:
                _LOGGER.info("Error fetching")
                ec |= ExitCode.FETCH_ERROR
                raise
            try:
                if args.index is None:
                    _LOGGER.info("Skipped indexing")
                else:
                    _LOGGER.info(f"Indexing {len(entries)} files")

                    await args.index.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        file = await args.index.open(mode="xt", **_OPEN_TXT_OPTS)
                    except FileExistsError:
                        pass
                    else:
                        await file.aclose()

                    async with await args.index.open(
                        mode="r+t", **_OPEN_TXT_OPTS
                    ) as file:
                        read = await file.read()
                        seek = create_task(file.seek(0))
                        try:
                            paragraphs = read.strip().split("\n\n")
                            index = {
                                _pct_unesc(match[2]): match[0]
                                for match in _INDEX_FORMAT_PATTERN.finditer(
                                    paragraphs[-1]
                                )
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
                            await seek
                            await file.write(text)
                            await file.truncate()
                        finally:
                            seek.cancel()
            except Exception:
                _LOGGER.exception("Error indexing")
                ec |= ExitCode.INDEX_ERROR
                raise
    except Exception:
        _LOGGER.exception("Error")
        ec |= ExitCode.GENERIC_ERROR

    _exit(ec)


def parser(parent: _Call[..., _ArgParser] | None = None):
    prog = __package__ or __name__

    parser = (_ArgParser if parent is None else parent)(
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
        version=f"{prog} v{_VER}",
        help="print version and exit",
    )
    parser.add_argument(
        "-d",
        "--dest",
        action="store",
        type=_Path,
        required=True,
        help="destination directory",
    )
    parser.add_argument(
        "-i",
        "--index",
        action="store",
        type=_Path,
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
        nargs=_ONE_OR_MORE,
        type=str,
        help="sequence of input(s) to read",
    )

    @_wraps(main)
    async def invoke(args: _NS):
        await main(
            Args(
                inputs=args.inputs,
                dest=args.dest,
                index=args.index,
                ignore_individual_errors=args.ignore_individual_errors,
            )
        )

    parser.set_defaults(invoke=invoke)
    return parser
