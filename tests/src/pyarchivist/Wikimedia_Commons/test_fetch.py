"""Fetch-phase tests for the Wikimedia_Commons flow.

Each test runs ``archive`` against a fake session and asserts the observable
outcome: files on disk, reported errors and the resulting exit code.
"""

from logging import WARNING
from os import PathLike

import pytest
from anyio import Path

from pyarchivist.types import Args, ExitCode
from pyarchivist.Wikimedia_Commons.__main__ import main
from pyarchivist.Wikimedia_Commons.main import archive
from tests.src.pyarchivist.Wikimedia_Commons.fakes import (
    _FakeClientSession,
    _names,
    _page,
    _patch_client,
)

"""Public symbols exported by this module (none)."""
__all__ = ()


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
async def test_mime_mismatch_warns_but_downloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: PathLike[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A different server content type is a warning, not a failed download."""
    session = _FakeClientSession(
        {"File:A.png": _page("File:A.png", mime="image/png", size=8)}
    )
    session.file_bytes = b"PNGbytes"
    session.content_type = "image/jpeg"
    _patch_client(monkeypatch, session)

    with caplog.at_level(WARNING):
        result = await archive(
            Args(inputs=("File:A.png",), dest=Path(tmp_path), index=None)
        )

    assert "differs from API mime" in caplog.text
    assert result.downloaded == 1
    assert await (Path(tmp_path) / "A.png").read_bytes() == b"PNGbytes"


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
async def test_empty_body_without_api_size_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """An empty body is never media, even when the API reports no size."""
    session = _FakeClientSession({"File:Empty.jpg": _page("File:Empty.jpg")})
    session.file_bytes = b""
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(inputs=("File:Empty.jpg",), dest=Path(tmp_path), index=None)
    )

    assert result.downloaded == 0
    assert "Empty body" in result.errors[0].message
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
async def test_case_folded_filename_collision_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """Titles differing only in case cannot race one path on a case-insensitive FS."""
    session = _FakeClientSession(
        {
            "File:AB.jpg": _page("File:AB.jpg"),
            "File:Ab.jpg": _page("File:Ab.jpg"),
        }
    )
    session.file_bytes = b"collision"
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(inputs=("File:AB.jpg", "File:Ab.jpg"), dest=Path(tmp_path), index=None)
    )

    assert await _names(tmp_path) == ["AB.jpg"]
    assert result.downloaded == 1
    assert len(result.errors) == 1
    assert "already used by 'File:AB.jpg'" in result.errors[0].message


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
    assert not any("Three.jpg" in url for url in session.file_urls)


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
    "scenario,expected_written,expected_code,expected_downloaded",
    [
        ("missing_imageinfo", [], ExitCode.FETCH_ERROR_PARTIAL, 0),
        (
            "missing_imageinfo_partial",
            ["Good.jpg"],
            ExitCode.FETCH_ERROR_PARTIAL,
            1,
        ),
        ("network_error", ["Good.jpg"], ExitCode.FETCH_ERROR_PARTIAL, 1),
        ("stream_error", [], ExitCode.FETCH_ERROR_PARTIAL, 0),
        ("timeout", [], ExitCode.FETCH_ERROR_PARTIAL, 0),
        ("http_error", [], ExitCode.FETCH_ERROR_PARTIAL, 0),
        ("corrupt_chunks", ["Corrupt.jpg"], ExitCode(0), 1),
    ],
)
async def test_fetch_error_variants(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: PathLike[str],
    scenario: str,
    expected_written: list[str],
    expected_code: ExitCode,
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
    assert code == expected_code


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
