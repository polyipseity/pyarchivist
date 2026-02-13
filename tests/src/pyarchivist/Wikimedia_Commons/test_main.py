"""Integration-style unit tests for `Wikimedia_Commons.main` flows.

These tests mock `aiohttp.ClientSession` at the module level to avoid network
I/O and exercise the query -> fetch -> optional indexing code paths.
"""

import asyncio
import json
import re
import string
from argparse import _VersionAction
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import pytest
from anyio import Path
from hypothesis import given
from hypothesis import strategies as st

from pyarchivist.meta import VERSION
from pyarchivist.Wikimedia_Commons import main as commons_main
from pyarchivist.Wikimedia_Commons.main import Args
from pyarchivist.Wikimedia_Commons.models import (
    ExtMetadata,
    ImageInfoEntry,
    Page,
    Value,
)

__all__ = ()


class _FakeContent:
    """Lightweight async content-like object exposing `iter_any()`."""

    def __init__(self, chunks: list[bytes]) -> None:
        """Initialize with a list of byte chunks to yield."""
        self._chunks: list[bytes] = chunks

    async def iter_any(self) -> AsyncIterator[bytes]:
        """Async iterator that yields configured byte chunks."""
        for c in self._chunks:
            await asyncio.sleep(0)
            yield c


class _FakeResp:
    """Minimal async context manager mimicking parts of `aiohttp.Response`."""

    def __init__(
        self, *, json_data: Any | None = None, content_chunks: list[bytes] | None = None
    ) -> None:
        """Store provided JSON payload and content chunks for reads."""
        self._json: Any | None = json_data
        self.content: _FakeContent = _FakeContent(content_chunks or [])

    async def json(self) -> Any | None:
        """Return the stored JSON-like payload."""
        # mimic aiohttp.Response.json()
        await asyncio.sleep(0)
        return self._json

    async def text(self) -> str:
        """Return text; if JSON payload is present return its JSON string."""
        # mimic aiohttp.Response.text(); return a JSON string when json data set
        await asyncio.sleep(0)
        return json.dumps(self._json) if self._json is not None else ""

    async def __aenter__(self) -> "_FakeResp":
        """Enter async context (no-op)."""
        return self

    async def __aexit__(
        self, exc_type: type | None, exc: BaseException | None, tb: object | None
    ) -> bool:
        """Exit async context (no-op)."""
        return False


class _FakeClientSession:
    """Fake client session implementing minimal `get` and async context API."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize placeholders used by tests (api json and file bytes)."""
        # will be filled by the test via attributes
        self._api_json: dict[str, Any] | None = None
        self._file_bytes: bytes | None = None

    async def __aenter__(self) -> "_FakeClientSession":
        """Enter async context (no-op)."""
        return self

    async def __aexit__(
        self, exc_type: type | None, exc: BaseException | None, tb: object | None
    ) -> bool:
        """Exit async context (no-op)."""
        return False

    def get(self, url: object, *args: object, **kwargs: object) -> _FakeResp:
        """Return a `_FakeResp` for API or file-download URLs."""
        s = str(url)
        if "api.php" in s:
            return _FakeResp(json_data=self._api_json)
        else:
            # file download
            fb = self._file_bytes
            assert fb is not None
            chunks: list[bytes] = [fb[i : i + 8] for i in range(0, len(fb), 8)]
            return _FakeResp(content_chunks=chunks)


@pytest.mark.asyncio
async def test_query_and_fetch_writes_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Full flow: query returns metadata and a subsequent fetch writes the file."""
    fake_sess = _FakeClientSession()

    # sample API response matching the models used by the code
    fake_sess._api_json = {
        "query": {
            "pages": {
                "1": {
                    "title": "File:Example.jpg",
                    "imageinfo": [
                        {
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                            "url": "https://upload.wikimedia.org/example.jpg",
                            "extmetadata": {
                                "Artist": {"value": "Jane Doe", "source": ""},
                                "LicenseShortName": {
                                    "value": "CC BY-SA 4.0",
                                    "source": "",
                                },
                                "LicenseUrl": {
                                    "value": "https://creativecommons.org/licenses/by-sa/4.0/",
                                    "source": "",
                                },
                            },
                        }
                    ],
                }
            }
        }
    }

    file_bytes = b"\x00\x01binarycontent"
    fake_sess._file_bytes = file_bytes

    def _client_session_factory(*_a: object, **_k: object) -> _FakeClientSession:
        """Return the configured fake session for the test."""
        return fake_sess

    def _fake_exit(code: int | object) -> None:
        """No-op replacement for sys.exit used in tests."""
        return None

    monkeypatch.setattr(commons_main, "ClientSession", _client_session_factory)
    monkeypatch.setattr(commons_main, "exit", _fake_exit)

    args: Args = Args(
        inputs=("File:Example.jpg",),
        dest=Path(tmp_path),
        index=None,
        ignore_individual_errors=False,
    )

    await commons_main.main(args)

    out: Path = Path(tmp_path) / "Example.jpg"
    assert await out.exists()
    assert await out.read_bytes() == file_bytes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial_index,expected_lines",
    [
        (
            "Header\n\n",
            [
                '- [Zed.jpg](Zed.jpg): <a href="https://commons.wikimedia.org/wiki/File:Zed.jpg">See page for author</a>, See page for license, via Wikimedia Commons'
            ],
        ),
        (
            "Header\n\n- [Existing](Existing): Existing credit\n",
            [
                "- [Existing](Existing): Existing credit",
                '- [Zed.jpg](Zed.jpg): <a href="https://commons.wikimedia.org/wiki/File:Zed.jpg">See page for author</a>, See page for license, via Wikimedia Commons',
            ],
        ),
    ],
)
async def test_indexing_updates_index_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    initial_index: str,
    expected_lines: list[str],
) -> None:
    """When indexing, update or create the index paragraph while preserving header."""
    fake_sess = _FakeClientSession()

    fake_sess._api_json = {
        "query": {
            "pages": {
                "1": {
                    "title": "File:Zed.jpg",
                    "imageinfo": [
                        {
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Zed.jpg",
                            "url": "https://upload.wikimedia.org/zed.jpg",
                            "extmetadata": {},
                        }
                    ],
                }
            }
        }
    }

    fake_sess._file_bytes = b"file-contents"

    def _client_session_factory_2(*_a: object, **_k: object) -> _FakeClientSession:
        """Return prepared fake session for indexing test."""
        return fake_sess

    def _fake_exit_2(code: int | object) -> None:
        """No-op exit replacement for tests."""
        return None

    monkeypatch.setattr(commons_main, "ClientSession", _client_session_factory_2)
    monkeypatch.setattr(commons_main, "exit", _fake_exit_2)

    # write the parametrized initial index content
    index_path: Path = Path(tmp_path) / "index.md"
    await index_path.write_text(initial_index, encoding="utf-8")

    args: Args = Args(
        inputs=("File:Zed.jpg",),
        dest=Path(tmp_path),
        index=Path(index_path),
        ignore_individual_errors=False,
    )

    await commons_main.main(args)

    text: str = await index_path.read_text(encoding="utf-8")
    paragraphs = text.strip().split("\n\n")

    # When the initial index already contained entries, the header paragraph
    # should be preserved and the last paragraph updated. Otherwise the
    # implementation replaces the last paragraph (so a header-only file will
    # be replaced by the index paragraph).
    if "- [" in initial_index:
        assert paragraphs[0].startswith("Header")
        lines = paragraphs[-1].splitlines()
        assert lines == sorted(expected_lines)
    else:
        # header-only file — result should be a single paragraph with index lines
        assert paragraphs == expected_lines


@pytest.mark.asyncio
async def test_fetch_partial_error_is_swallowed_with_ignore_flag_and_sets_partial_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When one page lacks imageinfo and --ignore-individual-errors is set the
    fetch stage should swallow the individual error and set FETCH_ERROR_PARTIAL.
    """
    fake_sess = _FakeClientSession()

    # Two pages: one valid, one with missing imageinfo
    fake_sess._api_json = {
        "query": {
            "pages": {
                "1": {
                    "title": "File:Good.jpg",
                    "imageinfo": [
                        {
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Good.jpg",
                            "url": "https://upload.wikimedia.org/good.jpg",
                            "extmetadata": {},
                        }
                    ],
                },
                "2": {"title": "File:Bad.jpg", "imageinfo": None},
            }
        }
    }

    fake_sess._file_bytes = b"good-bytes"

    def _client_session_factory(*_a: object, **_k: object) -> _FakeClientSession:
        """Return the prepared fake session for the fetch-partial test."""
        return fake_sess

    captured: dict[str, object] = {}

    def _fake_exit(code: int | object) -> None:
        """Capture exit code for assertions in the test."""
        captured["code"] = code

    monkeypatch.setattr(commons_main, "ClientSession", _client_session_factory)
    monkeypatch.setattr(commons_main, "exit", _fake_exit)

    args: Args = Args(
        inputs=("File:Good.jpg", "File:Bad.jpg"),
        dest=Path(tmp_path),
        index=None,
        ignore_individual_errors=True,
    )

    await commons_main.main(args)

    # Good file should be written
    out: Path = Path(tmp_path) / "Good.jpg"
    assert await out.exists()
    assert await out.read_bytes() == b"good-bytes"

    # Exit code should include the FETCH_ERROR_PARTIAL flag
    assert "code" in captured
    assert isinstance(captured["code"], commons_main.ExitCode)
    assert bool(captured["code"] & commons_main.ExitCode.FETCH_ERROR_PARTIAL)


@pytest.mark.asyncio
async def test_fetch_missing_imageinfo_without_ignore_sets_fetch_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If an individual fetch error occurs and errors aren't ignored the
    overall exit code should include FETCH_ERROR.
    """
    fake_sess = _FakeClientSession()

    fake_sess._api_json = {
        "query": {"pages": {"1": {"title": "File:Bad.jpg", "imageinfo": None}}}
    }

    def _client_session_factory(*_a: object, **_k: object) -> _FakeClientSession:
        """Return the fake session containing the bad API payload."""
        return fake_sess

    captured: dict[str, object] = {}

    def _fake_exit(code: int | object) -> None:
        """Capture the exit code produced by the run.

        Tests assert on the captured value.
        """
        captured["code"] = code

    monkeypatch.setattr(commons_main, "ClientSession", _client_session_factory)
    monkeypatch.setattr(commons_main, "exit", _fake_exit)

    args: Args = Args(
        inputs=("File:Bad.jpg",),
        dest=Path(tmp_path),
        index=None,
        ignore_individual_errors=False,
    )

    await commons_main.main(args)

    assert "code" in captured
    assert isinstance(captured["code"], commons_main.ExitCode)
    assert bool(captured["code"] & commons_main.ExitCode.FETCH_ERROR)


@pytest.mark.parametrize(
    "raw,has_bracket,has_backslash,has_safe",
    [
        (r"a]b\\c", True, True, False),
        ("simple-name.jpg", False, False, False),
        ("path/with/slash", False, False, True),
        ("comma,name.jpg", False, False, True),
        (r"brackets[]\\back", True, True, False),
        ("percent%sign", False, False, False),
    ],
)
def test_index_formatter_handles_various_filenames(
    raw: str, has_bracket: bool, has_backslash: bool, has_safe: bool
) -> None:
    """Verify `_index_formatter` handles brackets, backslashes and safe chars."""
    out = commons_main._index_formatter(raw, "credit")

    # label is the human-readable portion between [ and ]
    m = re.search(r"^- \[(.*?)]\((.*?)\): ", out)
    assert m is not None
    label, link = m.groups()

    if has_bracket:
        # label should contain the escape backslash and the link must contain %5D
        assert "\\" in label
        assert "%5D" in link
    if has_backslash:
        # backslashes are doubled in the label; escaping ']' also inserts a backslash
        assert label.count("\\") == raw.count("\\") * 2 + raw.count("]")
        # percent-encoding for backslash present in link
        assert "%5C" in link
    if has_safe:
        # '/', ',' are in the safe set and must NOT be percent-encoded
        for ch in ("/", ","):
            if ch in raw:
                assert ch in link

    # final suffix must be present
    assert out.endswith(": credit")


# Property-based tests for _index_formatter
@given(
    st.tuples(
        # prefix may include spaces (possibly empty), up to 59 chars
        st.text(
            alphabet=string.ascii_letters + string.digits + r" ]\\/_.-%,()",
            min_size=0,
            max_size=59,
        ),
        # ensure at least one non-space character is present
        st.text(
            alphabet=string.ascii_letters + string.digits + r"]\\/_.-%,()",
            min_size=1,
            max_size=1,
        ),
    ).map(lambda t: t[0] + t[1])
)
def test_index_formatter_property(fname: str) -> None:
    """Property-based check ensuring `_index_formatter` escapes and quotes."""
    out = commons_main._index_formatter(fname, "credit")
    m = re.search(r"^- \[(.*?)]\((.*?)\): ", out)
    assert m is not None
    label, link = m.groups()

    # label should contain the escape backslash when ']' is present
    if "]" in fname:
        assert "\\" in label
        assert "%5D" in link
    if "\\" in fname or "]" in fname:
        # account for doubled backslashes and the backslashes inserted when
        # escaping ']' characters in the label
        assert label.count("\\") == fname.count("\\") * 2 + fname.count("]")

    # link should be the quoted filename (preserving safe chars)
    expected = quote(fname, safe=commons_main._PERCENT_ESCAPE_SAFE)
    assert expected in link


def test_parser_produces_typed_namespace(tmp_path: Path) -> None:
    """Ensure the Wikimedia subparser produces a typed argparse namespace."""
    p = commons_main.parser()
    ns = p.parse_args(["-d", str(tmp_path), "File:Foo.jpg"])

    # argparse should have converted dest to an anyio.Path and set defaults
    assert isinstance(ns.dest, Path)
    assert ns.index is None
    assert ns.ignore_individual_errors is False
    assert ns.inputs == ["File:Foo.jpg"]


def test_handle_partial_errors_behaviour() -> None:
    """Verify `_handle_partial_errors` swallows exceptions when configured."""
    # mixed successful result + an Exception should be swallowed when ignoring
    results = [ValueError("x"), "ok"]
    flag, vals = commons_main._handle_partial_errors(
        results, ignore_individual_errors=True, error_message="err"
    )
    assert flag is True
    assert vals == ("ok",)

    # presence of a non-Exception BaseException should raise BaseExceptionGroup
    with pytest.raises(BaseExceptionGroup):
        commons_main._handle_partial_errors(
            [ValueError("x"), KeyboardInterrupt()], ignore_individual_errors=True
        )


def test_handle_partial_errors_no_exceptions_returns_values() -> None:
    """When no exceptions are present `_handle_partial_errors` should return values."""
    results = [1, 2, 3]
    flag, vals = commons_main._handle_partial_errors(
        results, ignore_individual_errors=False
    )
    assert flag is False
    assert vals == tuple(results)


def test_handle_partial_errors_raises_when_not_ignoring() -> None:
    """If ignore_individual_errors is False, exceptions should propagate."""
    # when exceptions are present and not ignored an ExceptionGroup is raised
    with pytest.raises(ExceptionGroup):
        commons_main._handle_partial_errors(
            [ValueError("a"), ValueError("b")], ignore_individual_errors=False
        )


# Property-based tests for _handle_partial_errors
@given(
    items=st.lists(
        st.sampled_from([KeyboardInterrupt(), SystemExit()]),
        min_size=1,
        max_size=30,
    ),
)
def test_handle_partial_errors_raises_on_non_exception_base(
    items: list[BaseException],
) -> None:
    """If a non-Exception BaseException (e.g. KeyboardInterrupt) is present the
    helper must raise a BaseExceptionGroup regardless of the ignore flag.
    """
    with pytest.raises(BaseExceptionGroup):
        commons_main._handle_partial_errors(items, ignore_individual_errors=True)


@given(
    # ensure generated lists always contain at least one Exception instance
    # (avoid .filter(...) which can cause many rejected examples)
    items=st.tuples(
        st.lists(
            st.one_of(
                st.integers(),
                st.text(),
                st.builds(ValueError, st.text()),
                st.builds(OSError, st.text()),
            ),
            min_size=0,
            max_size=29,
        ),
        st.one_of(
            st.builds(ValueError, st.text()),
            st.builds(OSError, st.text()),
        ),
    ).map(lambda t: t[0] + [t[1]]),
)
def test_handle_partial_errors_swallow_exceptions_and_return_values(
    items: list[int | str | Exception],
) -> None:
    """When only Exception-derived exceptions are present and
    `ignore_individual_errors=True`, the function should return (True, values)
    containing only the successful (non-exception) results in order.
    """
    # derive expected non-exception values
    expected = tuple(x for x in items if not isinstance(x, BaseException))

    flag, vals = commons_main._handle_partial_errors(
        items, ignore_individual_errors=True
    )

    assert flag is True
    assert vals == expected

    # when not ignoring, the same input must raise an ExceptionGroup
    with pytest.raises(ExceptionGroup):
        commons_main._handle_partial_errors(items, ignore_individual_errors=False)


def test_credit_formatter_unknown_and_license_url_variants() -> None:
    """Check `_credit_formatter` fallback behavior for unknown author/license."""
    ii = ImageInfoEntry(
        descriptionurl="https://commons.wikimedia.org/wiki/File:Test.jpg",
        url="https://upload.wikimedia.org/test.jpg",
        extmetadata=ExtMetadata(
            Artist=Value(value="Unknown author (reported)", source=""),
            LicenseShortName=Value(value="Unknown license", source=""),
            LicenseUrl=Value(value="https://example.org/license", source=""),
        ),
    )
    page = Page(title="File:Test.jpg", imageinfo=(ii,))

    credit = commons_main._credit_formatter(page)
    # unknown author should fall back to the 'See page for author' text
    assert "See page for author" in credit
    # unknown license text should be replaced by fallback but still linked
    assert '<a href="https://example.org/license">See page for license</a>' in credit


def _wrap_bold(s: str) -> str:
    """Wrap `s` in a <b> tag (helper used by property tests)."""
    return f"<b>{s}</b>"


# Property-based tests for _credit_formatter (broader variants)
@given(
    artist=st.one_of(
        st.text(alphabet=string.ascii_letters + " \n<>-", min_size=0, max_size=40),
        st.just("Unknown author"),
        st.builds(
            _wrap_bold,
            st.text(string.ascii_letters, min_size=1, max_size=10),
        ),
    ),
    lic=st.one_of(
        st.text(alphabet=string.ascii_letters + " \n-", min_size=0, max_size=30),
        st.just("Unknown license"),
    ),
    lic_url=st.one_of(st.none(), st.just(""), st.just("https://example.org/license")),
)
def test_credit_formatter_property_variants(
    artist: str, lic: str, lic_url: str | None
) -> None:
    """Fuzz combinations of artist/license/license-url and assert the
    output contains the expected fallbacks, HTML stripping, and links.
    """
    emd = ExtMetadata(
        Artist=Value(value=artist if artist != "" else None),
        LicenseShortName=Value(value=lic if lic != "" else None),
        LicenseUrl=Value(value=lic_url if lic_url else None),
    )
    ii = ImageInfoEntry(
        descriptionurl="https://commons.wikimedia.org/wiki/File:Prop.jpg",
        url="https://upload.wikimedia.org/prop.jpg",
        extmetadata=emd,
    )
    page = Page(title="File:Prop.jpg", imageinfo=(ii,))

    out = commons_main._credit_formatter(page)

    # unknown author -> fallback text
    if artist and "unknown author" in artist.casefold():
        assert "See page for author" in out
    else:
        # HTML should be stripped and whitespace normalized
        expected_author = re.sub(r"<[^>]*>", "", (artist or ""), flags=re.DOTALL)
        expected_author = re.sub(
            r"\s+", " ", expected_author.replace("\n", " ")
        ).strip()
        if expected_author:
            assert expected_author.split()[0] in out
        else:
            assert "See page for author" in out

    # license handling
    if lic and "unknown license" in lic.casefold():
        assert "See page for license" in out
    else:
        expected_lic = re.sub(r"\s+", " ", (lic or "").replace("\n", " ")).strip()
        if expected_lic:
            assert expected_lic.split()[0] in out
        else:
            assert "See page for license" in out

    # license URL
    if lic_url:
        assert f'<a href="{lic_url}"' in out


def test_credit_formatter_strips_html_and_newlines() -> None:
    """Ensure `_credit_formatter` strips HTML tags and normalizes newlines."""
    raw_author = "<b>Jane\nDoe</b>"
    ii = ImageInfoEntry(
        descriptionurl="https://commons.wikimedia.org/wiki/File:Html.jpg",
        url="https://upload.wikimedia.org/html.jpg",
        extmetadata=ExtMetadata(Artist=Value(value=raw_author, source="")),
    )
    page = Page(title="File:Html.jpg", imageinfo=(ii,))

    credit = commons_main._credit_formatter(page)
    # HTML tags and raw newlines from the metadata should be sanitized
    assert "<b>" not in credit
    assert "\n" not in credit
    assert "Jane" in credit and "Doe" in credit
    # output is an HTML fragment that links back to the description page
    assert '<a href="https://commons.wikimedia.org/wiki/File:Html.jpg">' in credit


def test_parser_version_action_contains_workspace_version() -> None:
    """Verify the parser's --version action contains the workspace VERSION."""
    # find the version action and verify it contains the project VERSION

    p = commons_main.parser()
    version_actions = [
        a for a in p._actions if "--version" in getattr(a, "option_strings", [])
    ]
    assert version_actions, "--version action missing"
    assert isinstance(version_actions[0], _VersionAction)
    assert version_actions[0].version is not None
    assert version_actions[0].version.endswith(f"v{VERSION}")


@pytest.mark.asyncio
async def test_main_query_error_sets_query_and_generic_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the API returns invalid/invalidatable JSON the query stage should set
    QUERY_ERROR (and the outer handler will set GENERIC_ERROR too).
    """

    class BadAPIClient(_FakeClientSession):
        """Fake client that returns deliberately malformed API JSON."""

        def __init__(self) -> None:
            """Initialize with a malformed API payload (for error path tests)."""
            super().__init__()
            # deliberately malformed payload (title should be a str)
            self._api_json = {"query": {"pages": {"1": {"title": 1}}}}

    fake = BadAPIClient()

    def _client_session_factory(*_a: object, **_k: object) -> BadAPIClient:
        """Return the BadAPIClient instance for this test."""
        return fake

    captured: dict[str, object] = {}

    def _fake_exit(code: int | object) -> None:
        """Capture the exit code supplied by the tested function."""
        captured["code"] = code

    monkeypatch.setattr(commons_main, "ClientSession", _client_session_factory)
    monkeypatch.setattr(commons_main, "exit", _fake_exit)

    args: Args = Args(
        inputs=("File:Broken.jpg",),
        dest=Path(tmp_path),
        index=None,
        ignore_individual_errors=False,
    )

    await commons_main.main(args)

    assert "code" in captured
    assert isinstance(captured["code"], commons_main.ExitCode)
    assert bool(captured["code"] & commons_main.ExitCode.QUERY_ERROR)
    assert bool(captured["code"] & commons_main.ExitCode.GENERIC_ERROR)


@pytest.mark.asyncio
async def test_main_deduplicates_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ensure duplicate inputs are deduplicated by `main`."""
    fake_sess = _FakeClientSession()

    fake_sess._api_json = {
        "query": {
            "pages": {
                "1": {
                    "title": "File:Single.jpg",
                    "imageinfo": [
                        {
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Single.jpg",
                            "url": "https://upload.wikimedia.org/single.jpg",
                            "extmetadata": {},
                        }
                    ],
                }
            }
        }
    }

    fake_sess._file_bytes = b"abc"

    def _client_session_factory(*_a: object, **_k: object) -> _FakeClientSession:
        """Return the fake session used for deduplication test."""
        return fake_sess

    def _fake_exit(code: int | object) -> None:
        """No-op replacement for sys.exit used in tests."""
        return None

    monkeypatch.setattr(commons_main, "ClientSession", _client_session_factory)
    monkeypatch.setattr(commons_main, "exit", _fake_exit)

    # duplicate inputs should be deduplicated by `main`
    args: Args = Args(
        inputs=("File:Single.jpg", "File:Single.jpg"),
        dest=Path(tmp_path),
        index=None,
        ignore_individual_errors=False,
    )

    await commons_main.main(args)

    out = Path(tmp_path) / "Single.jpg"
    assert await out.exists()
    assert await out.read_bytes() == b"abc"


@pytest.mark.asyncio
async def test_index_file_created_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When the index file is missing, `main` should create it before writing."""
    fake_sess = _FakeClientSession()

    fake_sess._api_json = {
        "query": {
            "pages": {
                "1": {
                    "title": "File:NewIndex.jpg",
                    "imageinfo": [
                        {
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:NewIndex.jpg",
                            "url": "https://upload.wikimedia.org/newindex.jpg",
                            "extmetadata": {},
                        }
                    ],
                }
            }
        }
    }
    fake_sess._file_bytes = b"data"

    def _client_session_factory(*_a: object, **_k: object) -> _FakeClientSession:
        """Return the fake session used to create a missing index file."""
        return fake_sess

    def _fake_exit(code: int | object) -> None:
        """No-op replacement for sys.exit used in this test."""
        return None

    monkeypatch.setattr(commons_main, "ClientSession", _client_session_factory)
    monkeypatch.setattr(commons_main, "exit", _fake_exit)

    index_path: Path = Path(tmp_path) / "subdir" / "index.md"
    # ensure file does not exist beforehand
    assert not await index_path.exists()

    args: Args = Args(
        inputs=("File:NewIndex.jpg",),
        dest=Path(tmp_path),
        index=Path(index_path),
        ignore_individual_errors=False,
    )

    await commons_main.main(args)

    assert await index_path.exists()
    text = await index_path.read_text(encoding="utf-8")
    assert "NewIndex.jpg" in text


@pytest.mark.asyncio
async def test_query_batching_respects_query_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With a small `_QUERY_LIMIT` the implementation should batch queries."""
    # set a small query limit to force batching
    monkeypatch.setattr(commons_main, "_QUERY_LIMIT", 1)

    class CountingClient(_FakeClientSession):
        """Client that counts API query calls to validate batching behaviour."""

        def __init__(self) -> None:
            """Initialize counters and placeholder responses."""
            super().__init__()
            self.query_calls = 0
            self._file_bytes = b"x"
            # prepare api responses for two distinct inputs
            self._api_json = None

        def get(self, url: object, *args: object, **kwargs: object) -> _FakeResp:
            """Return different API payloads depending on the 'titles' query."""
            s = str(url)
            if "api.php" in s:
                self.query_calls += 1
                # examine the 'titles' query param to return the expected page
                if "First" in s:
                    return _FakeResp(
                        json_data={
                            "query": {
                                "pages": {
                                    "1": {
                                        "title": "File:First.jpg",
                                        "imageinfo": [
                                            {
                                                "descriptionurl": "https://commons.wikimedia.org/wiki/File:First.jpg",
                                                "url": "https://upload.wikimedia.org/first.jpg",
                                                "extmetadata": dict[str, str](),
                                            }
                                        ],
                                    }
                                }
                            }
                        }
                    )
                return _FakeResp(
                    json_data={
                        "query": {
                            "pages": {
                                "2": {
                                    "title": "File:Second.jpg",
                                    "imageinfo": [
                                        {
                                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Second.jpg",
                                            "url": "https://upload.wikimedia.org/second.jpg",
                                            "extmetadata": dict[str, str](),
                                        }
                                    ],
                                }
                            }
                        }
                    }
                )
            return super().get(url, *args, **kwargs)

    fake = CountingClient()

    def _client_session_factory(*_a: object, **_k: object) -> CountingClient:
        """Return the counting client used to verify batching behaviour."""
        return fake

    def _fake_exit(code: int | object) -> None:
        """No-op replacement for sys.exit used in this test."""
        return None

    monkeypatch.setattr(commons_main, "ClientSession", _client_session_factory)
    monkeypatch.setattr(commons_main, "exit", _fake_exit)

    args: Args = Args(
        inputs=("File:First.jpg", "File:Second.jpg"),
        dest=Path(tmp_path),
        index=None,
        ignore_individual_errors=False,
    )

    await commons_main.main(args)

    # with _QUERY_LIMIT == 1 there should be two separate query calls
    assert fake.query_calls == 2


@pytest.mark.asyncio
async def test_query_partial_error_with_ignore_sets_partial_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Simulate one API query raising while the other succeeds; with
    --ignore-individual-errors the partial query should be swallowed and
    QUERY_ERROR_PARTIAL should be set.
    """
    monkeypatch.setattr(commons_main, "_QUERY_LIMIT", 1)

    class PartialFailClient(_FakeClientSession):
        """Client that simulates one successful and one failing API batch."""

        def __init__(self) -> None:
            """Configure a successful payload for the first batch."""
            super().__init__()
            self._file_bytes = b"ok"

        def get(self, url: object, *args: object, **kwargs: object) -> _FakeResp:
            """Return a valid response for the first title, raise for the second."""
            s = str(url)
            if "api.php" in s:
                if "First" in s:
                    return _FakeResp(
                        json_data={
                            "query": {
                                "pages": {
                                    "1": {
                                        "title": "File:First.jpg",
                                        "imageinfo": [
                                            {
                                                "descriptionurl": "https://commons.wikimedia.org/wiki/File:First.jpg",
                                                "url": "https://upload.wikimedia.org/first.jpg",
                                                "extmetadata": dict[str, str](),
                                            }
                                        ],
                                    }
                                }
                            }
                        }
                    )
                # simulate network/query failure for second batch
                raise RuntimeError("api-failure")
            return super().get(url, *args, **kwargs)

    fake = PartialFailClient()

    def _client_session_factory(*_a: object, **_k: object) -> PartialFailClient:
        """Return the partial-fail client for this test scenario."""
        return fake

    captured: dict[str, object] = {}

    def _fake_exit(code: int | object) -> None:
        """Capture the exit code for assertions on partial error handling."""
        captured["code"] = code

    monkeypatch.setattr(commons_main, "ClientSession", _client_session_factory)
    monkeypatch.setattr(commons_main, "exit", _fake_exit)

    args: Args = Args(
        inputs=("File:First.jpg", "File:Second.jpg"),
        dest=Path(tmp_path),
        index=None,
        ignore_individual_errors=True,
    )

    await commons_main.main(args)

    # successful file should be written despite the partial query failure
    out = Path(tmp_path) / "First.jpg"
    assert await out.exists()
    assert await out.read_bytes() == b"ok"

    assert "code" in captured
    assert isinstance(captured["code"], commons_main.ExitCode)
    assert bool(captured["code"] & commons_main.ExitCode.QUERY_ERROR_PARTIAL)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,ignore,expect_written,expected_flags",
    [
        ("missing_imageinfo_single", False, [], (commons_main.ExitCode.FETCH_ERROR,)),
        (
            "missing_imageinfo_partial",
            True,
            ["Good.jpg"],
            (commons_main.ExitCode.FETCH_ERROR_PARTIAL,),
        ),
        (
            "network_error_non_ignored",
            False,
            [],
            (commons_main.ExitCode.FETCH_ERROR, commons_main.ExitCode.GENERIC_ERROR),
        ),
        (
            "network_error_ignored",
            True,
            [],
            (commons_main.ExitCode.FETCH_ERROR_PARTIAL,),
        ),
        ("iter_error_ignored", True, [], (commons_main.ExitCode.FETCH_ERROR_PARTIAL,)),
        (
            "timeout_non_ignored",
            False,
            [],
            (commons_main.ExitCode.FETCH_ERROR, commons_main.ExitCode.GENERIC_ERROR),
        ),
        ("timeout_ignored", True, [], (commons_main.ExitCode.FETCH_ERROR_PARTIAL,)),
        ("corrupt_chunks", False, ["Corrupt.jpg"], ()),
    ],
)
async def test_fetch_error_variants(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scenario: str,
    ignore: bool,
    expect_written: list[str],
    expected_flags: tuple[commons_main.ExitCode, ...],
) -> None:
    """Parameterized fetch error scenarios.

    Scenarios:
    - missing_imageinfo_single: single page lacking imageinfo (non-ignored)
    - missing_imageinfo_partial: mixed good/bad pages with ignore=True
    - network_error_non_ignored: GET raises during download (non-ignored)
    - network_error_ignored: GET raises but errors are ignored
    - iter_error_ignored: response.iter_any() raises but errors are ignored
    - timeout_*: simulate asyncio.TimeoutError during download
    - corrupt_chunks: server returns corrupted/altered chunks (no fetch error)
    """

    # build clients per scenario
    if scenario == "missing_imageinfo_single":
        fake = _FakeClientSession()
        fake._api_json = {
            "query": {"pages": {"1": {"title": "File:Bad.jpg", "imageinfo": None}}}
        }

    elif scenario == "missing_imageinfo_partial":
        fake = _FakeClientSession()
        fake._api_json = {
            "query": {
                "pages": {
                    "1": {
                        "title": "File:Good.jpg",
                        "imageinfo": [
                            {
                                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Good.jpg",
                                "url": "https://upload.wikimedia.org/good.jpg",
                                "extmetadata": {},
                            }
                        ],
                    },
                    "2": {"title": "File:Bad.jpg", "imageinfo": None},
                }
            }
        }
        fake._file_bytes = b"good-bytes"

    elif scenario in ("network_error_non_ignored", "network_error_ignored"):

        class MixedFetchClient(_FakeClientSession):
            """Client mixing successful and failing file-download behaviour."""

            def __init__(self) -> None:
                """Configure API pages and a valid file payload for one page."""
                super().__init__()
                # two pages to allow mixing broken/good behaviour
                self._api_json = {
                    "query": {
                        "pages": {
                            "1": {
                                "title": "File:Good.jpg",
                                "imageinfo": [
                                    {
                                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Good.jpg",
                                        "url": "https://upload.wikimedia.org/good.jpg",
                                        "extmetadata": {},
                                    }
                                ],
                            },
                            "2": {
                                "title": "File:BrokenFetch.jpg",
                                "imageinfo": [
                                    {
                                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:BrokenFetch.jpg",
                                        "url": "https://upload.wikimedia.org/broken.jpg",
                                        "extmetadata": {},
                                    }
                                ],
                            },
                        }
                    }
                }
                self._file_bytes = b"ok"

            def get(self, url: object, *args: object, **kwargs: object) -> _FakeResp:
                """Return API payload or raise for the simulated broken file URL."""
                s = str(url)
                if "api.php" in s:
                    return _FakeResp(json_data=self._api_json)
                if "broken.jpg" in s:
                    raise RuntimeError("network error")
                return _FakeResp(
                    content_chunks=None
                    if self._file_bytes is None
                    else [self._file_bytes]
                )

        fake = MixedFetchClient()

    elif scenario == "iter_error_ignored":

        class IterErrorContent(_FakeContent):
            """Content-like object whose iterator raises to simulate stream errors."""

            async def iter_any(self) -> AsyncIterator[bytes]:
                """Raise a runtime error when iterated to simulate stream failure."""
                await asyncio.sleep(0)
                raise RuntimeError("stream error")
                if False:
                    yield b""

        class IterErrorResp(_FakeResp):
            """Response-like object that uses `IterErrorContent` for content."""

            def __init__(self, *, json_data: Any | None = None) -> None:
                """Initialize base response and attach the error-producing content."""
                super().__init__(json_data=json_data, content_chunks=None)
                self.content = IterErrorContent([])

        class IterErrorClient(_FakeClientSession):
            """Client that returns a response whose content iterator raises."""

            def __init__(self) -> None:
                """Prepare an API payload referencing the broken-stream file."""
                super().__init__()
                self._api_json = {
                    "query": {
                        "pages": {
                            "1": {
                                "title": "File:BrokenStream.jpg",
                                "imageinfo": [
                                    {
                                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:BrokenStream.jpg",
                                        "url": "https://upload.wikimedia.org/brokenstream.jpg",
                                        "extmetadata": {},
                                    }
                                ],
                            }
                        }
                    }
                }

            def get(self, url: object, *args: object, **kwargs: object) -> _FakeResp:
                """Return the API payload or an `IterErrorResp` for downloads."""
                s = str(url)
                if "api.php" in s:
                    return _FakeResp(json_data=self._api_json)
                return IterErrorResp()

        fake = IterErrorClient()

    elif scenario in ("timeout_non_ignored", "timeout_ignored"):

        class TimeoutClient(_FakeClientSession):
            """Client that raises asyncio.TimeoutError for file downloads."""

            def __init__(self) -> None:
                """Prepare API payload pointing at a file URL that times out."""
                super().__init__()
                self._api_json = {
                    "query": {
                        "pages": {
                            "1": {
                                "title": "File:Timeout.jpg",
                                "imageinfo": [
                                    {
                                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Timeout.jpg",
                                        "url": "https://upload.wikimedia.org/timeout.jpg",
                                        "extmetadata": {},
                                    }
                                ],
                            }
                        }
                    }
                }

            def get(self, url: object, *args: object, **kwargs: object) -> _FakeResp:
                """Return API response or raise TimeoutError for download URL."""
                s = str(url)
                if "api.php" in s:
                    return _FakeResp(json_data=self._api_json)
                raise asyncio.TimeoutError("timeout")

        fake = TimeoutClient()

    elif scenario == "corrupt_chunks":

        class CorruptClient(_FakeClientSession):
            """Client that returns intentionally corrupted download chunks."""

            def __init__(self) -> None:
                """Prepare API payload for the corrupt-chunks scenario."""
                super().__init__()
                self._api_json = {
                    "query": {
                        "pages": {
                            "1": {
                                "title": "File:Corrupt.jpg",
                                "imageinfo": [
                                    {
                                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Corrupt.jpg",
                                        "url": "https://upload.wikimedia.org/corrupt.jpg",
                                        "extmetadata": {},
                                    }
                                ],
                            }
                        }
                    }
                }

            def get(self, url: object, *args: object, **kwargs: object) -> _FakeResp:
                """Return a response whose content chunks are intentionally corrupted."""
                s = str(url)
                if "api.php" in s:
                    return _FakeResp(json_data=self._api_json)
                # return intentionally corrupted chunks
                return _FakeResp(content_chunks=[b"good-", b"corrupt", b"-tail"])

        fake = CorruptClient()

    else:
        raise AssertionError("unknown scenario")

    def _client_session_factory(*_a: object, **_k: object) -> _FakeClientSession:
        """Return the configured fake client for the scenario."""
        return fake

    captured: dict[str, object] = {}

    def _fake_exit(code: int | object) -> None:
        """Capture the exit code emitted by the run for assertions."""
        captured["code"] = code

    monkeypatch.setattr(commons_main, "ClientSession", _client_session_factory)
    monkeypatch.setattr(commons_main, "exit", _fake_exit)

    # choose inputs depending on scenario
    if scenario in (
        "missing_imageinfo_partial",
        "network_error_non_ignored",
        "network_error_ignored",
    ):
        inputs = (
            ("File:Good.jpg", "File:BrokenFetch.jpg")
            if "network" in scenario
            else ("File:Good.jpg", "File:Bad.jpg")
        )
    else:
        inputs = ("File:Bad.jpg",)

    args: Args = Args(
        inputs=inputs,
        dest=Path(tmp_path),
        index=None,
        ignore_individual_errors=ignore,
    )

    await commons_main.main(args)

    # check written files
    for fname in expect_written:
        out = Path(tmp_path) / fname
        assert await out.exists()

    # check expected exit flags
    assert "code" in captured
    code = captured["code"]
    assert isinstance(code, commons_main.ExitCode)
    for flag in expected_flags:
        assert bool(code & flag)


@pytest.mark.asyncio
async def test_indexing_merges_percent_encoded_existing_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Existing index lines with percent-encoded filenames should be
    matched and updated rather than duplicated.
    """
    fake_sess = _FakeClientSession()

    fake_sess._api_json = {
        "query": {
            "pages": {
                "1": {
                    "title": "File:a]b",
                    "imageinfo": [
                        {
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:a]b",
                            "url": "https://upload.wikimedia.org/a%5Db.jpg",
                            "extmetadata": {},
                        }
                    ],
                }
            }
        }
    }
    fake_sess._file_bytes = b"d"

    def _client_session_factory(*_a: object, **_k: object) -> _FakeClientSession:
        """Return the prepared fake session for indexing/merge checks."""
        return fake_sess

    def _fake_exit(code: int | object) -> None:
        """No-op replacement for sys.exit used in tests."""
        return None

    monkeypatch.setattr(commons_main, "ClientSession", _client_session_factory)
    monkeypatch.setattr(commons_main, "exit", _fake_exit)

    # index contains a percent-encoded link target and an escaped label
    index_path: Path = Path(tmp_path) / "index.md"
    await index_path.write_text(
        "Header\n\n- [a\\]b](a%5Db): Old credit\n- [Other](Other): Other credit\n",
        encoding="utf-8",
    )

    args: Args = Args(
        inputs=("File:a]b",),
        dest=Path(tmp_path),
        index=Path(index_path),
        ignore_individual_errors=False,
    )

    await commons_main.main(args)

    text = await index_path.read_text(encoding="utf-8")
    paragraphs = text.strip().split("\n\n")
    last = paragraphs[-1]

    # Old credit should have been replaced and no duplicate entry created
    assert "Old credit" not in last
    assert "a]b" in last
    # ensure Other entry still present
    assert "Other credit" in last
