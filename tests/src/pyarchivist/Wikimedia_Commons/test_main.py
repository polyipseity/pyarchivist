"""Flow tests for the Wikimedia_Commons query, fetch and index pipeline.

The aiohttp client, its responses and the retry wrapper are replaced with small
fakes that serve a page registry and one file body, so these tests stay offline
and deterministic. Each test asserts the observable outcome: files on disk, the
reported ``ArchiveResult`` errors, and the resulting exit code.
"""

import json
import re
import string
from argparse import _VersionAction
from collections.abc import AsyncIterator, Callable
from html import escape as html_escape
from os import PathLike, fspath
from typing import Any, ClassVar, cast
from urllib.parse import quote, unquote

import pytest
from aiohttp import (
    ClientConnectionError,
    ClientPayloadError,
    ClientTimeout,
    TCPConnector,
)
from anyio import Path, sleep
from hypothesis import given
from hypothesis import strategies as st
from yarl import URL

from pyarchivist.meta import VERSION
from pyarchivist.types import Args, ExitCode
from pyarchivist.Wikimedia_Commons.__main__ import main, parser
from pyarchivist.Wikimedia_Commons.main import (
    _INDEX_FORMAT_PATTERN,
    _PERCENT_ESCAPE_SAFE,
    _credit_formatter,
    _index_formatter,
    archive,
)
from pyarchivist.Wikimedia_Commons.models import (
    ExtMetadata,
    ImageInfoEntry,
    Page,
    Value,
)

"""Public symbols exported by this module (none)."""
__all__ = ()


class _FakeContent:
    """Async content object that yields prepared chunks and can fail after them."""

    def __init__(self, chunks: list[bytes], *, fail: bool = False) -> None:
        """Store the chunks and whether the stream fails once they are exhausted."""
        self._chunks = chunks
        self._fail = fail

    async def iter_any(self) -> AsyncIterator[bytes]:
        """Yield the chunks one by one, raising afterwards when configured to fail."""
        for chunk in self._chunks:
            await sleep(0)
            yield chunk
        if self._fail:
            raise RuntimeError("stream error")


class _FakeResp:
    """Minimal stand-in for an aiohttp response used by the flow."""

    def __init__(
        self,
        *,
        json_data: object | None = None,
        text_data: str | None = None,
        chunks: list[bytes] | None = None,
        content_type: str = "image/jpeg",
        status: int = 200,
        fail_stream: bool = False,
    ) -> None:
        """Store the payload, body chunks and response metadata."""
        self._json = json_data
        self._text = text_data
        self.content = _FakeContent(chunks or [], fail=fail_stream)
        self.content_type = content_type
        self.status = status

    async def text(self) -> str:
        """Return the raw body text, falling back to the JSON payload."""
        await sleep(0)
        if self._text is not None:
            return self._text
        return "" if self._json is None else json.dumps(self._json)

    async def __aenter__(self) -> "_FakeResp":
        """Enter the response context."""
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        """Leave the response context without suppressing exceptions."""
        return False


class _FakeClientSession:
    """Fake session answering API queries and downloads from a page registry."""

    def __init__(self, pages: dict[str, dict[str, object]] | None = None) -> None:
        """Create a session that serves *pages* keyed by page title."""
        self.pages = {} if pages is None else pages
        self.failing_titles: set[str] = set()
        self.api_status = 200
        self.api_text: str | None = None
        self.file_bytes = b""
        self.content_type = "image/jpeg"
        self.status = 200
        self.fail_stream = False
        self.file_error: Exception | None = None
        self.file_fail_on: str | None = None
        self.query_urls: list[str] = []
        self.file_urls: list[str] = []

    async def __aenter__(self) -> "_FakeClientSession":
        """Enter the session context."""
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        """Leave the session context without suppressing exceptions."""
        return False

    def get(self, url: object, *_args: object, **_kwargs: object) -> _FakeResp:
        """Return the API payload or the file body for *url*."""
        text = str(url)
        if "api.php" in text:
            return self._api_response(url)
        self.file_urls.append(text)
        if self.file_fail_on is not None and self.file_fail_on in text:
            raise RuntimeError("network error")
        if self.file_error is not None:
            raise self.file_error
        return _FakeResp(
            chunks=[self.file_bytes] if self.file_bytes else [],
            content_type=self.content_type,
            status=self.status,
            fail_stream=self.fail_stream,
        )

    def _api_response(self, url: object) -> _FakeResp:
        """Build the API response for the titles named in *url*.

        A registry title counts as requested when it appears in the decoded
        ``titles`` value; splitting that value on ``|`` would break titles that
        contain the separator themselves.
        """
        self.query_urls.append(str(url))
        parsed = url if isinstance(url, URL) else URL(str(url))
        titles = parsed.query["titles"]
        if any(title in titles for title in self.failing_titles):
            raise RuntimeError("api failure")
        if self.api_text is not None:
            return _FakeResp(text_data=self.api_text, status=self.api_status)
        requested = {
            str(index): page
            for index, (title, page) in enumerate(self.pages.items(), start=1)
            if title in titles
        }
        return _FakeResp(
            json_data={"query": {"pages": requested}}, status=self.api_status
        )

    async def request(
        self, method: str, url: object, *args: object, **kwargs: object
    ) -> _FakeResp:
        """Dispatch the retry client's ``request`` call to ``get``."""
        if method.upper() == "GET":
            return self.get(url, *args, **kwargs)
        raise NotImplementedError(f"Unsupported method: {method}")

    async def close(self) -> None:
        """Close nothing; the fake owns no resources."""


class _PassthroughRetryClient:
    """Bypass RetryClient and hand requests straight to the fake session."""

    def __init__(
        self, *, client_session: _FakeClientSession | None = None, **_kwargs: object
    ) -> None:
        """Keep the raw session this wrapper forwards to."""
        self._client = (
            _FakeClientSession() if client_session is None else client_session
        )

    def get(self, url: object, *args: object, **kwargs: object) -> _FakeResp:
        """Forward ``get`` to the underlying session."""
        return self._client.get(url, *args, **kwargs)

    async def close(self) -> None:
        """Close the underlying session."""
        await self._client.close()


class _CapturingClientSession:
    """Fake session that records the constructor kwargs the flow passes."""

    captured: ClassVar[dict[str, object]] = {}

    def __init__(self, *_args: object, **kwargs: object) -> None:
        """Record every keyword argument for later assertions."""
        _CapturingClientSession.captured.clear()
        _CapturingClientSession.captured.update(kwargs)

    async def __aenter__(self) -> "_CapturingClientSession":
        """Enter the session context."""
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        """Leave the session context without suppressing exceptions."""
        return False

    def get(self, _url: object, *_args: object, **_kwargs: object) -> object:
        """Fail every request; these tests inspect configuration only."""
        raise RuntimeError("no network in configuration tests")

    async def close(self) -> None:
        """Close nothing; the fake owns no resources."""


@pytest.fixture(autouse=True)
def _patch_retry_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace RetryClient with a passthrough for every test in this module."""
    monkeypatch.setattr(
        "pyarchivist.Wikimedia_Commons.main.RetryClient", _PassthroughRetryClient
    )


def _patch_client(monkeypatch: pytest.MonkeyPatch, session: object) -> None:
    """Make the flow reuse *session* instead of a real ``ClientSession``."""
    monkeypatch.setattr(
        "pyarchivist.Wikimedia_Commons.main.ClientSession",
        lambda *_args, **_kwargs: session,
    )


def _patch_session_class(
    monkeypatch: pytest.MonkeyPatch, factory: Callable[..., object]
) -> None:
    """Make the flow construct its session through *factory*."""
    monkeypatch.setattr("pyarchivist.Wikimedia_Commons.main.ClientSession", factory)


def _page(
    title: str,
    *,
    mime: str | None = None,
    size: int | None = None,
    extmetadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return one API page payload carrying a single imageinfo entry."""
    info: dict[str, object] = {
        "descriptionurl": f"https://commons.wikimedia.org/wiki/{title}",
        "url": f"https://upload.wikimedia.org/{title.split(':', 1)[-1]}",
        "extmetadata": {} if extmetadata is None else extmetadata,
    }
    if mime is not None:
        info["mime"] = mime
    if size is not None:
        info["size"] = size
    return {"title": title, "imageinfo": [info]}


async def _names(dest: PathLike[str]) -> list[str]:
    """Return the sorted names of the directory entries in *dest*."""
    return sorted([entry.name async for entry in Path(dest).iterdir()])


@pytest.mark.anyio
async def test_query_and_fetch_writes_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """The query result is downloaded under the title-derived filename."""
    session = _FakeClientSession(
        {
            "File:Example.jpg": _page(
                "File:Example.jpg",
                extmetadata={
                    "Artist": {"value": "Jane Doe", "source": ""},
                    "LicenseShortName": {"value": "CC BY-SA 4.0", "source": ""},
                    "LicenseUrl": {
                        "value": "https://creativecommons.org/licenses/by-sa/4.0/",
                        "source": "",
                    },
                },
            )
        }
    )
    session.file_bytes = b"\x00\x01binarycontent"
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(inputs=("File:Example.jpg",), dest=Path(tmp_path), index=None)
    )

    assert result.downloaded == 1
    assert await (Path(tmp_path) / "Example.jpg").read_bytes() == session.file_bytes


@pytest.mark.anyio
async def test_query_requests_mime_and_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """``iiprop`` asks for the MIME type and size that downloads are checked on."""
    session = _FakeClientSession({"File:A.jpg": _page("File:A.jpg")})
    session.file_bytes = b"a"
    _patch_client(monkeypatch, session)

    await archive(Args(inputs=("File:A.jpg",), dest=Path(tmp_path), index=None))

    assert len(session.query_urls) == 1
    iiprop = set(URL(session.query_urls[0]).query["iiprop"].split("|"))
    assert {"mime", "size"} <= iiprop


@pytest.mark.anyio
@pytest.mark.parametrize("content_type", ["application/ogg", "video/ogg", "audio/ogg"])
async def test_ogg_content_types_are_accepted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: PathLike[str],
    content_type: str,
) -> None:
    """Ogg media is accepted whatever ogg content type the server chooses."""
    session = _FakeClientSession(
        {"File:A.ogv": _page("File:A.ogv", mime="application/ogg", size=8)}
    )
    session.file_bytes = b"OggSdata"
    session.content_type = content_type
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(inputs=("File:A.ogv",), dest=Path(tmp_path), index=None)
    )

    assert result.downloaded == 1
    assert result.errors == ()
    assert await (Path(tmp_path) / "A.ogv").read_bytes() == b"OggSdata"


@pytest.mark.anyio
async def test_html_error_page_is_rejected_and_leaves_no_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """An HTML error document is never written under a media filename."""
    session = _FakeClientSession({"File:A.jpg": _page("File:A.jpg", size=999)})
    session.file_bytes = b"<html></html>"
    session.content_type = "text/html"
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(inputs=("File:A.jpg",), dest=Path(tmp_path), index=None)
    )

    assert result.downloaded == 0
    assert [error.phase for error in result.errors] == ["fetch"]
    assert "content-type" in result.errors[0].message
    assert await _names(tmp_path) == []


@pytest.mark.anyio
async def test_size_mismatch_is_rejected_and_leaves_no_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A body shorter than the API size is a failed download, not a file."""
    session = _FakeClientSession(
        {"File:A.jpg": _page("File:A.jpg", mime="image/jpeg", size=1000)}
    )
    session.file_bytes = b"short"
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(inputs=("File:A.jpg",), dest=Path(tmp_path), index=None)
    )

    assert result.downloaded == 0
    assert "Size mismatch" in result.errors[0].message
    assert await _names(tmp_path) == []


@pytest.mark.anyio
async def test_stream_failure_leaves_no_partial_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A body that fails mid-stream leaves neither the target nor its ``.part``."""
    session = _FakeClientSession({"File:A.jpg": _page("File:A.jpg")})
    session.file_bytes = b"partial"
    session.fail_stream = True
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(inputs=("File:A.jpg",), dest=Path(tmp_path), index=None)
    )

    assert result.downloaded == 0
    assert [error.phase for error in result.errors] == ["fetch"]
    assert await _names(tmp_path) == []


@pytest.mark.anyio
async def test_existing_file_of_wrong_size_is_redownloaded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A stored file whose size differs from the API size is fetched again."""
    target = Path(tmp_path) / "A.jpg"
    await target.write_bytes(b"x")
    session = _FakeClientSession({"File:A.jpg": _page("File:A.jpg", size=5)})
    session.file_bytes = b"12345"
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(inputs=("File:A.jpg",), dest=Path(tmp_path), index=None)
    )

    assert (result.downloaded, result.skipped) == (1, 0)
    assert await target.read_bytes() == b"12345"


@pytest.mark.anyio
async def test_existing_file_of_exact_size_is_skipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """Skipping is the default and trusts only a file of the reported size."""
    target = Path(tmp_path) / "A.jpg"
    await target.write_bytes(b"12345")
    session = _FakeClientSession({"File:A.jpg": _page("File:A.jpg", size=5)})
    session.file_bytes = b"12345"
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(inputs=("File:A.jpg",), dest=Path(tmp_path), index=None)
    )

    assert (result.downloaded, result.skipped) == (0, 1)
    assert session.file_urls == []


@pytest.mark.anyio
async def test_fetch_isolates_failures_and_keeps_successes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """One broken page does not discard the file that did transfer."""
    session = _FakeClientSession(
        {
            "File:Good.jpg": _page("File:Good.jpg"),
            "File:Bad.jpg": {"title": "File:Bad.jpg", "imageinfo": None},
        }
    )
    session.file_bytes = b"good-bytes"
    _patch_client(monkeypatch, session)

    index_path = Path(tmp_path) / "index.md"
    result = await archive(
        Args(
            inputs=("File:Good.jpg", "File:Bad.jpg"),
            dest=Path(tmp_path),
            index=index_path,
        )
    )

    assert result.downloaded == 1
    assert [(error.phase, error.title) for error in result.errors] == [
        ("fetch", "Bad.jpg")
    ]
    assert await (Path(tmp_path) / "Good.jpg").exists()
    content = await index_path.read_text(encoding="utf-8")
    assert "Good.jpg" in content
    assert "Bad.jpg" not in content


@pytest.mark.anyio
async def test_filename_collision_is_reported_and_not_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """Two titles sanitizing to one filename become one file plus one error."""
    session = _FakeClientSession(
        {
            "File:A*B.jpg": _page("File:A*B.jpg"),
            "File:A?B.jpg": _page("File:A?B.jpg"),
        }
    )
    session.file_bytes = b"collision"
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(inputs=("File:A*B.jpg", "File:A?B.jpg"), dest=Path(tmp_path), index=None)
    )

    assert await _names(tmp_path) == ["A_B.jpg"]
    assert result.downloaded == 1
    assert len(result.errors) == 1
    assert "already used by 'File:A*B.jpg'" in result.errors[0].message


@pytest.mark.anyio
async def test_fail_fast_stops_after_first_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """``fail_fast`` abandons the rest of the run and skips the index update."""
    session = _FakeClientSession(
        {
            "File:One.jpg": _page("File:One.jpg"),
            "File:Two.jpg": _page("File:Two.jpg"),
            "File:Three.jpg": _page("File:Three.jpg"),
        }
    )
    session.file_bytes = b"data"
    session.file_fail_on = "Two.jpg"
    _patch_client(monkeypatch, session)

    index_path = Path(tmp_path) / "index.md"
    result = await archive(
        Args(
            inputs=("File:One.jpg", "File:Two.jpg", "File:Three.jpg"),
            dest=Path(tmp_path),
            index=index_path,
            fail_fast=True,
        )
    )

    assert await _names(tmp_path) == ["One.jpg"]
    assert not await index_path.exists()
    assert (result.downloaded, result.skipped) == (1, 0)
    assert [error.phase for error in result.errors] == ["fetch"]


@pytest.mark.anyio
async def test_missing_page_reports_does_not_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A page reported missing explains that the title does not exist."""
    session = _FakeClientSession(
        {"File:No.jpg": {"title": "File:No.jpg", "missing": ""}}
    )
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(inputs=("File:No.jpg",), dest=Path(tmp_path), index=None)
    )

    assert len(result.errors) == 1
    assert "does not exist" in result.errors[0].message
    assert "not a valid title" not in result.errors[0].message


@pytest.mark.anyio
async def test_invalid_title_reports_invalid_title(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A rejected title reports the API reason instead of a fetch failure."""
    session = _FakeClientSession(
        {"File:?|": {"title": "File:?|", "invalidreason": "bad title"}}
    )
    _patch_client(monkeypatch, session)

    result = await archive(Args(inputs=("File:?|",), dest=Path(tmp_path), index=None))

    assert len(result.errors) == 1
    assert "not a valid title" in result.errors[0].message
    assert "bad title" in result.errors[0].message
    assert "does not exist" not in result.errors[0].message


@pytest.mark.anyio
async def test_index_merge_is_keyed_by_filename_not_display(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A sanitized title keeps one index line across repeated runs."""
    session = _FakeClientSession({"File:A?B.jpg": _page("File:A?B.jpg")})
    session.file_bytes = b"data"
    _patch_client(monkeypatch, session)

    index_path = Path(tmp_path) / "index.md"
    args = Args(
        inputs=("File:A?B.jpg",),
        dest=Path(tmp_path),
        index=index_path,
        skip_existing=False,
    )
    await archive(args)
    await archive(args)

    lines = (await index_path.read_text(encoding="utf-8")).splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("- [A?B.jpg](A_B.jpg): ")


@pytest.mark.anyio
async def test_index_write_replaces_the_file_atomically(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """The index is written to a sibling temp file and then replaced."""
    session = _FakeClientSession({"File:A.jpg": _page("File:A.jpg")})
    session.file_bytes = b"data"
    _patch_client(monkeypatch, session)

    replaced: list[tuple[str, str]] = []
    original = cast(Any, Path.replace)

    async def recording_replace(self: Path, target: Path) -> Path:
        """Record the replacement pair and delegate to the real method."""
        replaced.append((self.name, target.name))
        return await original(self, target)

    monkeypatch.setattr(Path, "replace", recording_replace)

    index_path = Path(tmp_path) / "index.md"
    await archive(Args(inputs=("File:A.jpg",), dest=Path(tmp_path), index=index_path))

    assert (".index.md.tmp", "index.md") in replaced
    assert not await (Path(tmp_path) / ".index.md.tmp").exists()
    assert await index_path.exists()


@pytest.mark.anyio
async def test_index_write_error_sets_index_and_generic_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A failed index write is reported while the downloaded file survives."""
    session = _FakeClientSession({"File:A.jpg": _page("File:A.jpg")})
    session.file_bytes = b"ok"
    _patch_client(monkeypatch, session)

    original = cast(Any, Path.replace)

    async def failing_replace(self: Path, target: Path) -> Path:
        """Fail only for the index temp file, leaving downloads untouched."""
        if self.name == ".index.md.tmp":
            raise OSError("index replace failure")
        return await original(self, target)

    monkeypatch.setattr(Path, "replace", failing_replace)

    code = await main(
        Args(
            inputs=("File:A.jpg",),
            dest=Path(tmp_path),
            index=Path(tmp_path) / "index.md",
        )
    )

    assert await (Path(tmp_path) / "A.jpg").exists()
    assert code & ExitCode.INDEX_ERROR
    assert code & ExitCode.GENERIC_ERROR


@pytest.mark.anyio
async def test_index_file_created_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A missing index file and its directory are created before writing."""
    session = _FakeClientSession({"File:New.jpg": _page("File:New.jpg")})
    session.file_bytes = b"data"
    _patch_client(monkeypatch, session)

    index_path = Path(tmp_path) / "subdir" / "index.md"
    await archive(Args(inputs=("File:New.jpg",), dest=Path(tmp_path), index=index_path))

    assert await index_path.exists()
    assert "New.jpg" in await index_path.read_text(encoding="utf-8")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "initial_index,expected_lines",
    [
        (
            "Header\n\n",
            [
                '- [Zed.jpg](Zed.jpg): <a href="https://commons.wikimedia.org/wiki/'
                'File:Zed.jpg">See page for author</a>, See page for license, '
                "via Wikimedia Commons"
            ],
        ),
        (
            "Header\n\n- [Existing](Existing): Existing credit\n",
            [
                "- [Existing](Existing): Existing credit",
                '- [Zed.jpg](Zed.jpg): <a href="https://commons.wikimedia.org/wiki/'
                'File:Zed.jpg">See page for author</a>, See page for license, '
                "via Wikimedia Commons",
            ],
        ),
    ],
)
async def test_indexing_updates_index_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: PathLike[str],
    initial_index: str,
    expected_lines: list[str],
) -> None:
    """Indexing updates the last paragraph and keeps earlier paragraphs."""
    session = _FakeClientSession({"File:Zed.jpg": _page("File:Zed.jpg")})
    session.file_bytes = b"file-contents"
    _patch_client(monkeypatch, session)

    index_path = Path(tmp_path) / "index.md"
    await index_path.write_text(initial_index, encoding="utf-8")

    await archive(Args(inputs=("File:Zed.jpg",), dest=Path(tmp_path), index=index_path))

    text = await index_path.read_text(encoding="utf-8")
    paragraphs = text.strip().split("\n\n")
    if "- [" in initial_index:
        assert paragraphs[0].startswith("Header")
        assert paragraphs[-1].splitlines() == sorted(expected_lines)
    else:
        assert paragraphs == expected_lines


@pytest.mark.anyio
async def test_indexing_merges_percent_encoded_existing_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A percent-encoded link target is matched instead of duplicated."""
    session = _FakeClientSession({"File:a]b": _page("File:a]b")})
    session.file_bytes = b"d"
    _patch_client(monkeypatch, session)

    index_path = Path(tmp_path) / "index.md"
    await index_path.write_text(
        "Header\n\n- [a\\]b](a%5Db): Old credit\n- [Other](Other): Other credit\n",
        encoding="utf-8",
    )

    await archive(Args(inputs=("File:a]b",), dest=Path(tmp_path), index=index_path))

    last = (await index_path.read_text(encoding="utf-8")).strip().split("\n\n")[-1]
    assert "Old credit" not in last
    assert "a]b" in last
    assert "Other credit" in last


@pytest.mark.anyio
async def test_main_deduplicates_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """Repeated input titles are queried and downloaded only once."""
    session = _FakeClientSession({"File:Single.jpg": _page("File:Single.jpg")})
    session.file_bytes = b"abc"
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(
            inputs=("File:Single.jpg", "File:Single.jpg"),
            dest=Path(tmp_path),
            index=None,
        )
    )

    assert len(session.query_urls) == 1
    assert result.downloaded == 1
    assert await (Path(tmp_path) / "Single.jpg").read_bytes() == b"abc"


@pytest.mark.anyio
async def test_query_batching_respects_query_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """Titles are queried in batches of ``_QUERY_LIMIT``."""
    monkeypatch.setattr("pyarchivist.Wikimedia_Commons.main._QUERY_LIMIT", 1)
    session = _FakeClientSession(
        {
            "File:First.jpg": _page("File:First.jpg"),
            "File:Second.jpg": _page("File:Second.jpg"),
        }
    )
    session.file_bytes = b"x"
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(
            inputs=("File:First.jpg", "File:Second.jpg"),
            dest=Path(tmp_path),
            index=None,
        )
    )

    assert len(session.query_urls) == 2
    assert result.downloaded == 2


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["malformed_json", "http_error"])
async def test_query_failures_set_query_and_generic_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str], mode: str
) -> None:
    """An invalid payload and an HTTP error both surface as query errors."""
    session = _FakeClientSession({"File:Broken.jpg": _page("File:Broken.jpg")})
    if mode == "malformed_json":
        session.api_text = '{"query": {"pages": {"1": {"title": 1}}}}'
    else:
        session.api_status = 500
    _patch_client(monkeypatch, session)

    code = await main(
        Args(inputs=("File:Broken.jpg",), dest=Path(tmp_path), index=None)
    )

    assert await _names(tmp_path) == []
    assert code & ExitCode.QUERY_ERROR_PARTIAL
    assert code & ExitCode.GENERIC_ERROR


@pytest.mark.anyio
async def test_query_bisect_isolates_failing_title(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A failing title is isolated from the batch-mates it shared a query with."""
    monkeypatch.setattr("pyarchivist.Wikimedia_Commons.main._QUERY_LIMIT", 3)
    session = _FakeClientSession(
        {
            "File:First.jpg": _page("File:First.jpg"),
            "File:Second.jpg": _page("File:Second.jpg"),
        }
    )
    session.failing_titles = {"File:Bad.jpg"}
    session.file_bytes = b"x"
    _patch_client(monkeypatch, session)

    args = Args(
        inputs=("File:First.jpg", "File:Second.jpg", "File:Bad.jpg"),
        dest=Path(tmp_path),
        index=None,
    )
    result = await archive(args)

    assert [(error.phase, error.title) for error in result.errors] == [
        ("query", "File:Bad.jpg")
    ]
    assert result.downloaded == 2
    assert await _names(tmp_path) == ["First.jpg", "Second.jpg"]

    code = await main(args)
    assert code & ExitCode.QUERY_ERROR_PARTIAL


@pytest.mark.anyio
async def test_query_bisect_disabled_reports_one_batch_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """Without bisecting, a failed batch is reported as a single error."""
    monkeypatch.setattr("pyarchivist.Wikimedia_Commons.main._QUERY_LIMIT", 3)
    session = _FakeClientSession(
        {
            "File:First.jpg": _page("File:First.jpg"),
            "File:Second.jpg": _page("File:Second.jpg"),
        }
    )
    session.failing_titles = {"File:Bad.jpg"}
    session.file_bytes = b"x"
    _patch_client(monkeypatch, session)

    args = Args(
        inputs=("File:First.jpg", "File:Second.jpg", "File:Bad.jpg"),
        dest=Path(tmp_path),
        index=None,
        bisect_queries=False,
    )
    result = await archive(args)

    assert [error.phase for error in result.errors] == ["query"]
    assert result.errors[0].title == "File:First.jpg, File:Second.jpg, File:Bad.jpg"
    assert result.downloaded == 0
    assert await _names(tmp_path) == []

    code = await main(args)
    assert code & ExitCode.QUERY_ERROR_PARTIAL


@pytest.mark.anyio
async def test_sanitize_filenames_replaces_quote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A quote in the title is replaced when sanitizing is on."""
    session = _FakeClientSession(
        {'File:File with "quotes".jpg': _page('File:File with "quotes".jpg')}
    )
    session.file_bytes = b"img"
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(inputs=('File:File with "quotes".jpg',), dest=Path(tmp_path), index=None)
    )

    written = [p async for p in Path(tmp_path).iterdir()]
    assert len(written) == 1
    assert '"' not in written[0].name
    assert result.downloaded == 1


@pytest.mark.anyio
async def test_sanitize_filenames_false_preserves_original(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """With sanitizing off the title-derived filename is kept as is."""
    session = _FakeClientSession(
        {'File:File with "quotes".jpg': _page('File:File with "quotes".jpg')}
    )
    session.file_bytes = b"img"
    _patch_client(monkeypatch, session)

    await archive(
        Args(
            inputs=('File:File with "quotes".jpg',),
            dest=Path(tmp_path),
            index=None,
            sanitize_filenames=False,
        )
    )

    written = [p async for p in Path(tmp_path).iterdir()]
    assert len(written) == 1
    assert '"' in written[0].name


@pytest.mark.anyio
@pytest.mark.parametrize(
    "title,expected_name",
    [
        ("File:Asterisk*.jpg", "Asterisk_.jpg"),
        ("File:Question?.jpg", "Question_.jpg"),
        ("File:Angle<>.jpg", "Angle__.jpg"),
        ("File:Pipe|.jpg", "Pipe_.jpg"),
    ],
)
async def test_sanitize_filenames_various_illegal_chars(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: PathLike[str],
    title: str,
    expected_name: str,
) -> None:
    """Each Windows-illegal character becomes an underscore."""
    session = _FakeClientSession({title: _page(title)})
    session.file_bytes = b"x"
    _patch_client(monkeypatch, session)

    await archive(Args(inputs=(title,), dest=Path(tmp_path), index=None))

    assert await _names(tmp_path) == [expected_name]


@pytest.mark.anyio
async def test_sanitize_filenames_index_uses_unsanitized_display(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """The index link text keeps the unsanitized title."""
    title = 'File:A "quoted" name.jpg'
    session = _FakeClientSession({title: _page(title)})
    session.file_bytes = b"img"
    _patch_client(monkeypatch, session)

    index_path = Path(tmp_path) / "index.md"
    await archive(Args(inputs=(title,), dest=Path(tmp_path), index=index_path))

    content = await index_path.read_text(encoding="utf-8")
    assert 'A "quoted" name.jpg' in content
    assert "A%20_quoted_%20name.jpg" in content


@pytest.mark.anyio
async def test_skip_existing_after_sanitize(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A second run skips the file the sanitized name already points at."""
    session = _FakeClientSession({"File:A?B.jpg": _page("File:A?B.jpg")})
    session.file_bytes = b"data"
    _patch_client(monkeypatch, session)

    args = Args(inputs=("File:A?B.jpg",), dest=Path(tmp_path), index=None)

    first = await archive(args)
    second = await archive(args)

    assert (first.downloaded, first.skipped) == (1, 0)
    assert (second.downloaded, second.skipped) == (0, 1)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "scenario,expected_written,expected_flags,expected_downloaded",
    [
        ("missing_imageinfo", [], (ExitCode.FETCH_ERROR_PARTIAL,), 0),
        (
            "missing_imageinfo_partial",
            ["Good.jpg"],
            (ExitCode.FETCH_ERROR_PARTIAL,),
            1,
        ),
        ("network_error", ["Good.jpg"], (ExitCode.FETCH_ERROR_PARTIAL,), 1),
        ("stream_error", [], (ExitCode.FETCH_ERROR_PARTIAL,), 0),
        ("timeout", [], (ExitCode.FETCH_ERROR_PARTIAL,), 0),
        ("http_error", [], (ExitCode.FETCH_ERROR_PARTIAL,), 0),
        ("corrupt_chunks", ["Corrupt.jpg"], (), 1),
    ],
)
async def test_fetch_error_variants(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: PathLike[str],
    scenario: str,
    expected_written: list[str],
    expected_flags: tuple[ExitCode, ...],
    expected_downloaded: int,
) -> None:
    """Fetch failures are reported per file; intact bodies still land."""
    session, inputs = _scenario_client(scenario)
    _patch_client(monkeypatch, session)
    args = Args(
        inputs=inputs,
        dest=Path(tmp_path),
        index=None,
        skip_existing=False,
    )

    result = await archive(args)
    code = await main(args)

    assert result.downloaded == expected_downloaded
    assert await _names(tmp_path) == expected_written
    if expected_flags:
        for flag in expected_flags:
            assert code & flag
    else:
        assert code == ExitCode(0)


def _scenario_client(
    scenario: str,
) -> tuple[_FakeClientSession, tuple[str, ...]]:
    """Build the fake session and inputs for one fetch failure scenario."""
    if scenario == "missing_imageinfo":
        session = _FakeClientSession(
            {"File:Bad.jpg": {"title": "File:Bad.jpg", "imageinfo": None}}
        )
        return session, ("File:Bad.jpg",)
    if scenario == "missing_imageinfo_partial":
        session = _FakeClientSession(
            {
                "File:Good.jpg": _page("File:Good.jpg"),
                "File:Bad.jpg": {"title": "File:Bad.jpg", "imageinfo": None},
            }
        )
        session.file_bytes = b"good"
        return session, ("File:Good.jpg", "File:Bad.jpg")
    if scenario == "network_error":
        session = _FakeClientSession(
            {
                "File:Good.jpg": _page("File:Good.jpg"),
                "File:Broken.jpg": _page("File:Broken.jpg"),
            }
        )
        session.file_bytes = b"good"
        session.file_fail_on = "Broken.jpg"
        return session, ("File:Good.jpg", "File:Broken.jpg")
    if scenario == "stream_error":
        session = _FakeClientSession({"File:Stream.jpg": _page("File:Stream.jpg")})
        session.file_bytes = b"partial"
        session.fail_stream = True
        return session, ("File:Stream.jpg",)
    if scenario == "timeout":
        session = _FakeClientSession({"File:Timeout.jpg": _page("File:Timeout.jpg")})
        session.file_error = TimeoutError("timeout")
        return session, ("File:Timeout.jpg",)
    if scenario == "http_error":
        session = _FakeClientSession({"File:HTTP.jpg": _page("File:HTTP.jpg")})
        session.status = 500
        return session, ("File:HTTP.jpg",)
    if scenario == "corrupt_chunks":
        session = _FakeClientSession({"File:Corrupt.jpg": _page("File:Corrupt.jpg")})
        session.file_bytes = b"good-corrupt-tail"
        return session, ("File:Corrupt.jpg",)
    raise AssertionError(f"unknown scenario: {scenario}")


@pytest.mark.anyio
async def test_client_session_timeout_and_connector_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """The session has no transfer cap and a single connection per host."""
    _patch_session_class(monkeypatch, _CapturingClientSession)

    await archive(
        Args(
            inputs=("File:X.jpg",),
            dest=Path(tmp_path),
            index=None,
            request_timeout=7.0,
        )
    )

    captured = _CapturingClientSession.captured
    timeout = cast(ClientTimeout, captured["timeout"])
    connector = cast(TCPConnector, captured["connector"])
    try:
        assert timeout.total is None
        assert timeout.sock_connect == 7.0
        assert timeout.sock_read == 7.0
        assert connector.limit_per_host == 1
    finally:
        await connector.close()


@pytest.mark.anyio
async def test_retry_options_cover_connection_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """Connection and payload errors are retried alongside 429 responses."""
    captured: dict[str, object] = {}

    def recording_retry(**kwargs: object) -> None:
        """Record retry option kwargs instead of building an options object."""
        captured.update(kwargs)

    _patch_session_class(monkeypatch, _CapturingClientSession)
    monkeypatch.setattr(
        "pyarchivist.Wikimedia_Commons.main._WikimediaRetry", recording_retry
    )

    await archive(Args(inputs=("File:X.jpg",), dest=Path(tmp_path), index=None))

    assert captured["statuses"] == {429}
    exceptions = cast(set[type[Exception]], captured["exceptions"])
    assert {ClientConnectionError, ClientPayloadError} <= exceptions


@pytest.mark.anyio
@pytest.mark.parametrize("trust_env", [True, False])
async def test_trust_env_passed_to_client_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str], trust_env: bool
) -> None:
    """``trust_env`` reaches the ``ClientSession`` constructor unchanged."""
    _patch_session_class(monkeypatch, _CapturingClientSession)

    await archive(
        Args(
            inputs=("File:X.jpg",),
            dest=Path(tmp_path),
            index=None,
            trust_env=trust_env,
        )
    )

    assert _CapturingClientSession.captured["trust_env"] is trust_env


def test_parser_produces_typed_namespace(tmp_path: PathLike[str]) -> None:
    """The parser converts ``--dest`` to an anyio path and keeps the inputs."""
    namespace = parser().parse_args(["-d", fspath(tmp_path), "File:Foo.jpg"])

    assert isinstance(namespace.dest, Path)
    assert namespace.index is None
    assert namespace.inputs == ["File:Foo.jpg"]
    assert namespace.trust_env is True


def test_parser_version_action_contains_workspace_version() -> None:
    """The ``--version`` action reports the package version."""
    actions = [
        action
        for action in parser()._actions
        if "--version" in getattr(action, "option_strings", [])
    ]
    assert actions, "--version action missing"
    assert isinstance(actions[0], _VersionAction)
    assert actions[0].version is not None
    assert actions[0].version.endswith(f"v{VERSION}")


def test_parser_skip_existing_flags(tmp_path: PathLike[str]) -> None:
    """Skipping is on by default and both flag forms are accepted."""
    p = parser()
    default = p.parse_args(["-d", fspath(tmp_path), "File:X.jpg"])
    negated = p.parse_args(["-d", fspath(tmp_path), "--no-skip-existing", "File:X.jpg"])
    asserted = p.parse_args(["-d", fspath(tmp_path), "--skip-existing", "File:X.jpg"])

    assert default.skip_existing is True
    assert negated.skip_existing is False
    assert asserted.skip_existing is True


def test_parser_sanitize_filenames_flags(tmp_path: PathLike[str]) -> None:
    """Sanitizing is on by default and both flag forms are accepted."""
    p = parser()
    default = p.parse_args(["-d", fspath(tmp_path), "File:X.jpg"])
    negated = p.parse_args(
        ["-d", fspath(tmp_path), "--no-sanitize-filenames", "File:X.jpg"]
    )
    asserted = p.parse_args(
        ["-d", fspath(tmp_path), "--sanitize-filenames", "File:X.jpg"]
    )

    assert default.sanitize_filenames is True
    assert negated.sanitize_filenames is False
    assert asserted.sanitize_filenames is True


def test_parser_fail_fast_flag(tmp_path: PathLike[str]) -> None:
    """``--fail-fast`` is off unless asked for."""
    p = parser()
    default = p.parse_args(["-d", fspath(tmp_path), "File:X.jpg"])
    enabled = p.parse_args(["-d", fspath(tmp_path), "--fail-fast", "File:X.jpg"])

    assert default.fail_fast is False
    assert enabled.fail_fast is True


def test_parser_bisect_queries_flags(tmp_path: PathLike[str]) -> None:
    """Bisecting is on by default and can be switched off."""
    p = parser()
    default = p.parse_args(["-d", fspath(tmp_path), "File:X.jpg"])
    negated = p.parse_args(
        ["-d", fspath(tmp_path), "--no-bisect-queries", "File:X.jpg"]
    )

    assert default.bisect_queries is True
    assert negated.bisect_queries is False


@pytest.mark.anyio
async def test_parser_invoke_builds_args_and_calls_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """The parser ``invoke`` adapter forwards every flag into ``Args``."""
    captured: dict[str, object] = {}

    async def fake_main(args: Args) -> None:
        """Capture the Args instance passed by the parser invoke adapter."""
        captured["args"] = args

    monkeypatch.setattr("pyarchivist.Wikimedia_Commons.__main__.main", fake_main)

    root = Path(tmp_path)
    namespace = parser().parse_args(
        [
            "-d",
            fspath(root),
            "-i",
            fspath(root / "index.md"),
            "--no-skip-existing",
            "--no-sanitize-filenames",
            "--fail-fast",
            "--no-bisect-queries",
            "--no-trust-env",
            "File:One.jpg",
            "File:Two.jpg",
        ]
    )

    await namespace.invoke(namespace)

    args = cast(Args, captured["args"])
    assert args.inputs == ("File:One.jpg", "File:Two.jpg")
    assert args.dest == root
    assert args.index == root / "index.md"
    assert args.skip_existing is False
    assert args.sanitize_filenames is False
    assert args.fail_fast is True
    assert args.bisect_queries is False
    assert args.trust_env is False


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
    """Brackets, backslashes and safe characters are handled as documented."""
    out = _index_formatter(raw, "credit")

    match = re.search(r"^- \[((?:\\.|[^\]])*?)\]\((.*?)\): ", out)
    assert match is not None
    label, link = match.groups()

    if has_bracket:
        assert "\\" in label
        assert "%5D" in link
    if has_backslash:
        assert label.count("\\") == raw.count("\\") * 2 + raw.count("]")
        assert "%5C" in link
    if has_safe:
        for character in ("/", ","):
            if character in raw:
                assert character in link

    assert out.endswith(": credit")


@given(
    st.tuples(
        st.text(
            alphabet=string.ascii_letters + string.digits + r" ]\\/_.-%,()",
            min_size=0,
            max_size=59,
        ),
        st.text(
            alphabet=string.ascii_letters + string.digits + r"]\\/_.-%,()",
            min_size=1,
            max_size=1,
        ),
    ).map(lambda parts: parts[0] + parts[1])
)
def test_index_formatter_property(fname: str) -> None:
    """Generated filenames are escaped in the label and quoted in the link."""
    out = _index_formatter(fname, "credit")
    match = re.search(r"^- \[((?:\\.|[^\]])*?)\]\((.*?)\): ", out)
    assert match is not None
    label, link = match.groups()

    if "]" in fname:
        assert "\\" in label
        assert "%5D" in link
    if "\\" in fname or "]" in fname:
        assert label.count("\\") == fname.count("\\") * 2 + fname.count("]")

    assert quote(fname, safe=_PERCENT_ESCAPE_SAFE) in link


@pytest.mark.parametrize(
    "filename",
    ["simple.jpg", "a]b", r"folder\\item].png", "comma,name.jpg"],
)
def test_index_formatter_output_matches_index_pattern(filename: str) -> None:
    """Formatted lines parse back through ``_INDEX_FORMAT_PATTERN``."""
    line = _index_formatter(filename, "credit")
    match = _INDEX_FORMAT_PATTERN.match(line)

    assert match is not None
    assert match.group(0) == line
    assert unquote(match.group(2)) == filename


def test_index_formatter_display_overrides_link_text() -> None:
    """A given ``display`` becomes the visible link text."""
    line = _index_formatter("sanitized.jpg", "credit", display="Original Name.jpg")
    match = re.search(r"^- \[(.+?)\]\((.+?)\): ", line)
    assert match is not None
    label, link = match.groups()

    assert label == "Original Name.jpg"
    assert unquote(link) == "sanitized.jpg"


def test_index_formatter_display_none_falls_back_to_filename() -> None:
    """Without ``display`` the filename is the link text."""
    line = _index_formatter("file.jpg", "credit")
    match = re.search(r"^- \[(.+?)\]\((.+?)\): ", line)
    assert match is not None
    label, link = match.groups()

    assert label == "file.jpg"
    assert unquote(link) == "file.jpg"


def test_credit_formatter_unknown_and_license_url_variants() -> None:
    """Unknown author and license markers fall back to descriptive text."""
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

    credit = _credit_formatter(page)

    assert "See page for author" in credit
    assert '<a href="https://example.org/license">See page for license</a>' in credit


def test_credit_formatter_strips_html_and_newlines() -> None:
    """Embedded HTML tags and newlines are removed from the credit."""
    ii = ImageInfoEntry(
        descriptionurl="https://commons.wikimedia.org/wiki/File:Html.jpg",
        url="https://upload.wikimedia.org/html.jpg",
        extmetadata=ExtMetadata(Artist=Value(value="<b>Jane\nDoe</b>", source="")),
    )
    page = Page(title="File:Html.jpg", imageinfo=(ii,))

    credit = _credit_formatter(page)

    assert "<b>" not in credit
    assert "\n" not in credit
    assert "Jane" in credit and "Doe" in credit
    assert '<a href="https://commons.wikimedia.org/wiki/File:Html.jpg">' in credit


def _wrap_bold(text: str) -> str:
    """Wrap *text* in a bold tag for the property test."""
    return f"<b>{text}</b>"


@given(
    artist=st.one_of(
        st.text(alphabet=string.ascii_letters + " \n<>-", min_size=0, max_size=40),
        st.just("Unknown author"),
        st.builds(_wrap_bold, st.text(string.ascii_letters, min_size=1, max_size=10)),
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
    """Generated metadata is sanitized and falls back to descriptive text."""
    emd = ExtMetadata(
        Artist=Value(value=artist if artist else None),
        LicenseShortName=Value(value=lic if lic else None),
        LicenseUrl=Value(value=lic_url if lic_url else None),
    )
    ii = ImageInfoEntry(
        descriptionurl="https://commons.wikimedia.org/wiki/File:Prop.jpg",
        url="https://upload.wikimedia.org/prop.jpg",
        extmetadata=emd,
    )
    page = Page(title="File:Prop.jpg", imageinfo=(ii,))

    out = _credit_formatter(page)

    if artist and "unknown author" in artist.casefold():
        assert "See page for author" in out
    else:
        expected_author = re.sub(r"<[^>]*>", "", artist, flags=re.DOTALL)
        expected_author = re.sub(
            r"\s+", " ", expected_author.replace("\n", " ")
        ).strip()
        if expected_author:
            assert html_escape(expected_author.split()[0]) in out
        else:
            assert "See page for author" in out

    if lic and "unknown license" in lic.casefold():
        assert "See page for license" in out
    else:
        expected_lic = re.sub(r"\s+", " ", lic.replace("\n", " ")).strip()
        if expected_lic:
            assert html_escape(expected_lic.split()[0]) in out
        else:
            assert "See page for license" in out

    if lic_url:
        assert f'<a href="{lic_url}"' in out
