"""Package-wide fixtures for the Wikimedia_Commons flow tests."""

import pytest

from tests.src.pyarchivist.Wikimedia_Commons.fakes import _PassthroughRetryClient

"""Public symbols exported by this module (none)."""
__all__ = ()


@pytest.fixture(autouse=True)
def _patch_retry_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace RetryClient with a passthrough for every test in this package."""
    monkeypatch.setattr(
        "pyarchivist.Wikimedia_Commons.main.RetryClient", _PassthroughRetryClient
    )
