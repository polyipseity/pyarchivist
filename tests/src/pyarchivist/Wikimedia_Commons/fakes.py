"""Shared fakes for the Wikimedia_Commons flow tests.

The aiohttp client, its responses and the retry wrapper are replaced by small
fakes that answer from a page registry and one file body, so the tests stay
offline and deterministic.
"""

import json
from collections.abc import AsyncIterator, Callable
from os import PathLike
from typing import ClassVar

import pytest
from anyio import CancelScope, Path, sleep
from yarl import URL

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
        cancel_scope: CancelScope | None = None,
    ) -> None:
        """Store the payload, body chunks, response metadata and cancel scope."""
        self._json = json_data
        self._text = text_data
        self._cancel_scope = cancel_scope
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
        """Leave the context, cancelling the configured scope on the way out."""
        if self._cancel_scope is not None:
            self._cancel_scope.cancel()
        return False


class _FakeClientSession:
    """Fake session answering API queries and downloads from a page registry."""

    def __init__(self, pages: dict[str, dict[str, object]] | None = None) -> None:
        """Create a session that serves *pages* keyed by page title."""
        self.pages = {} if pages is None else pages
        self.failing_titles: set[str] = set()
        self.api_status = 200
        self.api_text: str | None = None
        self.api_error: Exception | None = None
        self.file_bytes = b""
        self.content_type = "image/jpeg"
        self.status = 200
        self.fail_stream = False
        self.file_error: Exception | None = None
        self.file_fail_on: str | None = None
        self.cancel_scope: CancelScope | None = None
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
            cancel_scope=self.cancel_scope,
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
        if self.api_error is not None:
            raise self.api_error
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
