"""Query and session-configuration tests for the Wikimedia_Commons flow."""

from os import PathLike
from typing import cast

import pytest
from aiohttp import (
    ClientConnectionError,
    ClientPayloadError,
    ClientTimeout,
    TCPConnector,
)
from anyio import Path
from yarl import URL

from pyarchivist.types import Args, ExitCode
from pyarchivist.Wikimedia_Commons.__main__ import main
from pyarchivist.Wikimedia_Commons.main import archive
from tests.src.pyarchivist.Wikimedia_Commons.fakes import (
    _CapturingClientSession,
    _FakeClientSession,
    _names,
    _page,
    _patch_client,
    _patch_session_class,
)

"""Public symbols exported by this module (none)."""
__all__ = ()


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
async def test_query_failures_set_query_flag(
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
    assert code == ExitCode.QUERY_ERROR


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
    assert code == ExitCode.QUERY_ERROR


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
    assert code == ExitCode.QUERY_ERROR


@pytest.mark.anyio
async def test_query_transport_failure_is_not_bisected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A dropped connection reports the batch once instead of fanning out."""
    session = _FakeClientSession(
        {"File:A.jpg": _page("File:A.jpg"), "File:B.jpg": _page("File:B.jpg")}
    )
    session.api_error = ClientConnectionError("connection lost")
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(
            inputs=("File:A.jpg", "File:B.jpg"),
            dest=Path(tmp_path),
            index=None,
            max_retries=1,
            retry_delay=0,
        )
    )

    assert [error.phase for error in result.errors] == ["query"]
    assert result.errors[0].title == "File:A.jpg, File:B.jpg"
    assert len(session.query_urls) == 1


@pytest.mark.anyio
async def test_query_server_error_is_not_bisected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A 5xx answer is reported once; halving it cannot isolate a title."""
    session = _FakeClientSession(
        {"File:A.jpg": _page("File:A.jpg"), "File:B.jpg": _page("File:B.jpg")}
    )
    session.api_status = 503
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(inputs=("File:A.jpg", "File:B.jpg"), dest=Path(tmp_path), index=None)
    )

    assert [error.phase for error in result.errors] == ["query"]
    assert result.errors[0].title == "File:A.jpg, File:B.jpg"
    assert len(session.query_urls) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["payload", "timeout", "client_error"])
async def test_query_failure_classification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str], mode: str
) -> None:
    """Transport failures skip bisecting; a 4xx answer still bisects."""
    session = _FakeClientSession(
        {"File:A.jpg": _page("File:A.jpg"), "File:B.jpg": _page("File:B.jpg")}
    )
    if mode == "payload":
        session.api_error = ClientPayloadError("broken payload")
    elif mode == "timeout":
        session.api_error = TimeoutError("timed out")
    else:
        session.api_status = 400
    _patch_client(monkeypatch, session)

    result = await archive(
        Args(
            inputs=("File:A.jpg", "File:B.jpg"),
            dest=Path(tmp_path),
            index=None,
            max_retries=1,
            retry_delay=0,
        )
    )

    assert [error.phase for error in result.errors] == ["query"] * (
        1 if mode != "client_error" else 2
    )
    assert len(session.query_urls) == (1 if mode != "client_error" else 3)


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
