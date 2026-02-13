"""Integration-style unit tests for `Wikimedia_Commons.main` flows.

These tests mock `aiohttp.ClientSession` at the module level to avoid network
I/O and exercise the query -> fetch -> optional indexing code paths.
"""

from __future__ import annotations

from pydantic import ValidationError

__all__ = ()

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from anyio import Path

from pyarchivist.Wikimedia_Commons import main as commons_main
from pyarchivist.Wikimedia_Commons.main import Args


class _FakeContent:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks: list[bytes] = chunks

    async def iter_any(self) -> AsyncIterator[bytes]:
        for c in self._chunks:
            await asyncio.sleep(0)
            yield c


class _FakeResp:
    def __init__(
        self, *, json_data: Any | None = None, content_chunks: list[bytes] | None = None
    ) -> None:
        self._json: Any | None = json_data
        self.content: _FakeContent = _FakeContent(content_chunks or [])

    async def json(self) -> Any | None:
        # mimic aiohttp.Response.json()
        await asyncio.sleep(0)
        return self._json

    async def text(self) -> str:
        # mimic aiohttp.Response.text(); return a JSON string when json data set
        await asyncio.sleep(0)
        return json.dumps(self._json) if self._json is not None else ""

    async def __aenter__(self) -> "_FakeResp":
        return self

    async def __aexit__(
        self, exc_type: type | None, exc: BaseException | None, tb: object | None
    ) -> bool:
        return False


class _FakeClientSession:
    def __init__(self, *args: object, **kwargs: object) -> None:
        # will be filled by the test via attributes
        self._api_json: dict[str, Any] | None = None
        self._file_bytes: bytes | None = None

    async def __aenter__(self) -> "_FakeClientSession":
        return self

    async def __aexit__(
        self, exc_type: type | None, exc: BaseException | None, tb: object | None
    ) -> bool:
        return False

    def get(self, url: object, *args: object, **kwargs: object) -> _FakeResp:
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
        return fake_sess

    def _fake_exit(code: int | object) -> None:  # type: ignore[no-redef]
        return None

    monkeypatch.setattr(commons_main, "ClientSession", _client_session_factory)
    monkeypatch.setattr(commons_main, "exit", _fake_exit)

    args: Args = Args(
        inputs=("File:Example.jpg",),
        dest=tmp_path,
        index=None,
        ignore_individual_errors=False,
    )

    await commons_main.main(args)

    out: Path = Path(tmp_path) / "Example.jpg"
    assert await out.exists()
    assert await out.read_bytes() == file_bytes


@pytest.mark.asyncio
async def test_indexing_updates_index_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
        return fake_sess

    def _fake_exit_2(code: int | object) -> None:  # type: ignore[no-redef]
        return None

    monkeypatch.setattr(commons_main, "ClientSession", _client_session_factory_2)
    monkeypatch.setattr(commons_main, "exit", _fake_exit_2)

    # create an index file with an existing entry
    index_path: Path = Path(tmp_path) / "index.md"
    await index_path.write_text(
        "Header\n\n- [Existing](Existing): Existing credit\n", encoding="utf-8"
    )

    args: Args = Args(
        inputs=("File:Zed.jpg",),
        dest=tmp_path,
        index=index_path,
        ignore_individual_errors=False,
    )

    await commons_main.main(args)

    text: str = await index_path.read_text(encoding="utf-8")
    # last paragraph should contain both entries sorted (Existing, Zed.jpg)
    assert "Existing" in text
    assert "Zed.jpg" in text


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
        return fake_sess

    captured: dict[str, object] = {}

    def _fake_exit(code: int | object) -> None:  # type: ignore[no-redef]
        captured["code"] = code

    monkeypatch.setattr(commons_main, "ClientSession", _client_session_factory)
    monkeypatch.setattr(commons_main, "exit", _fake_exit)

    args: Args = Args(
        inputs=("File:Good.jpg", "File:Bad.jpg"),
        dest=tmp_path,
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
        return fake_sess

    captured: dict[str, object] = {}

    def _fake_exit(code: int | object) -> None:  # type: ignore[no-redef]
        captured["code"] = code

    monkeypatch.setattr(commons_main, "ClientSession", _client_session_factory)
    monkeypatch.setattr(commons_main, "exit", _fake_exit)

    args: Args = Args(
        inputs=("File:Bad.jpg",),
        dest=tmp_path,
        index=None,
        ignore_individual_errors=False,
    )

    await commons_main.main(args)

    assert "code" in captured
    assert isinstance(captured["code"], commons_main.ExitCode)
    assert bool(captured["code"] & commons_main.ExitCode.FETCH_ERROR)


@pytest.mark.asyncio
async def test_parser_validates_cli_args_with_pydantic() -> None:
    """The `parser` should validate CLI inputs via the pydantic `Args` model
    and raise `ValidationError` for invalid values (for example a non-existent
    directory for `--dest`).
    """

    parser = commons_main.parser()
    # provide a non-existent directory as dest; pydantic DirectoryPath will
    # reject this when the subcommand's `invoke` constructs/validates `Args`.
    ns = parser.parse_args(["-d", "./path/does/not/exist", "File:Example.jpg"])

    with pytest.raises(ValidationError):
        # invoke is an async function
        await ns.invoke(ns)
