"""Typed shared helpers and fixtures used across the pyarchivist tests.

The helpers in this module mirror the ledger test style: keep utility behavior
in one place and expose typed fixtures via ``pytest_plugins`` in
``tests/conftest.py``.
"""

import runpy
import sys
from collections.abc import Callable
from typing import Any, Protocol

import asyncer
import pytest

"""Public symbols exported by this module."""
__all__ = ("RunModuleHelper", "run_module_helper")


class RunModuleHelper(Protocol):
    """Callable protocol for safely executing a module under ``runpy``.

    The helper executes the module as ``__main__`` while monkeypatching
    ``asyncer.runnify`` to avoid creating background event-loop side effects
    in tests.
    """

    def __call__(self, module_name: str, argv: list[str]) -> dict[str, object]:
        """Run ``module_name`` as ``__main__`` with ``argv`` and report calls."""
        ...


@pytest.fixture
def run_module_helper(monkeypatch: pytest.MonkeyPatch) -> RunModuleHelper:
    """Return a helper for running modules with a safe fake ``asyncer.runnify``.

    The returned callable runs ``runpy.run_module(..., run_name="__main__")`` and
    captures whether ``runnify`` was called and whether the returned wrapper
    function was invoked.
    """

    class _RunModule:
        """Run-module helper implementation used by test fixtures."""

        def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
            """Store the monkeypatch instance used for this helper."""
            self._monkeypatch = monkeypatch

        def __call__(self, module_name: str, argv: list[str]) -> dict[str, object]:
            """Run the requested module with patched ``runnify`` and ``sys.argv``."""
            called: dict[str, object] = {
                "runnify_called": False,
                "wrapper_called": False,
                "async_function": None,
            }

            def fake_runnify(
                async_func: Callable[..., Any], *_args: object, **_kwargs: object
            ) -> Callable[..., Any]:
                """Record the wrapped async function and return a safe wrapper."""
                called["runnify_called"] = True
                called["async_function"] = getattr(async_func, "__name__", None)

                def wrapper(*args: Any, **kwargs: Any) -> None:
                    """Invoke and close the coroutine to avoid runtime warnings."""
                    called["wrapper_called"] = True
                    try:
                        coro = async_func(*args, **kwargs)
                        close = getattr(coro, "close", None)
                        if callable(close):
                            close()
                    except Exception:
                        # Best-effort safety for test harness code.
                        pass

                return wrapper

            self._monkeypatch.setattr(asyncer, "runnify", fake_runnify)
            previous_argv = sys.argv[:]
            try:
                sys.argv[:] = argv
                sys.modules.pop(module_name, None)
                runpy.run_module(module_name, run_name="__main__")
            finally:
                sys.argv[:] = previous_argv
            return called

    return _RunModule(monkeypatch)
