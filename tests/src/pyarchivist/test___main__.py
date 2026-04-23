"""Tests for ``pyarchivist.__main__`` entrypoint wiring and behavior."""

from collections.abc import Awaitable, Callable
from logging import INFO
from types import SimpleNamespace

import pytest

from pyarchivist import __main__ as package_main
from tests.utils import RunModuleHelper

"""Public symbols exported by this module (none)."""
__all__ = ()


def test_module_execution_uses_runnify(run_module_helper: RunModuleHelper) -> None:
    """Running the module as ``__main__`` should call ``asyncer.runnify``."""
    called = run_module_helper("pyarchivist.__main__", ["pyarchivist"])

    assert called["runnify_called"] is True
    assert called["wrapper_called"] is True
    assert called["async_function"] == "main"


@pytest.mark.anyio
async def test_main_configures_logging_and_invokes_parsed_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The async ``main`` should configure logging and invoke parsed namespace."""
    seen: dict[str, object] = {}

    async def fake_invoke(namespace: object) -> None:
        """Record the namespace passed by ``main`` to ``entry.invoke``."""
        seen["namespace"] = namespace

    class _FakeParser:
        """Simple parser stub that captures argv and returns a fake namespace."""

        def parse_args(self, args: list[str]) -> SimpleNamespace:
            """Capture parse args and provide an ``invoke`` coroutine."""
            seen["argv"] = list(args)
            return SimpleNamespace(invoke=fake_invoke)

    def fake_basic_config(*_args: object, **kwargs: object) -> None:
        """Capture logging configuration kwargs used by the entrypoint."""
        seen["level"] = kwargs.get("level")

    monkeypatch.setattr(package_main, "parser", lambda: _FakeParser())
    monkeypatch.setattr(package_main, "basicConfig", fake_basic_config)
    monkeypatch.setattr(
        package_main,
        "argv",
        ["pyarchivist", "Wikimedia_Commons", "--help"],
    )

    await package_main.main()

    assert seen["level"] == INFO
    assert seen["argv"] == ["Wikimedia_Commons", "--help"]
    assert seen["namespace"] is not None


def test_dunder_main_uses_uvloop_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """``__main__`` should call ``runnify(main, backend_options={...})``."""
    captured: dict[str, object] = {}

    def fake_runnify(
        async_func: Callable[[], Awaitable[None]],
        *,
        backend_options: dict[str, object],
    ) -> Callable[[], None]:
        """Capture ``runnify`` inputs and return a callable sentinel wrapper."""
        captured["async_func"] = async_func
        captured["backend_options"] = backend_options

        def _runner() -> None:
            """Record that the wrapper returned by ``runnify`` was executed."""
            captured["runner_called"] = True

        return _runner

    monkeypatch.setattr(package_main, "runnify", fake_runnify)

    package_main.__main__()

    assert captured["async_func"] is package_main.main
    assert captured["backend_options"] == {"use_uvloop": True}
    assert captured["runner_called"] is True
