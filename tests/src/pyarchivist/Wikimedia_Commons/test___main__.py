"""Tests for ``pyarchivist.Wikimedia_Commons.__main__`` entrypoint behavior."""

from collections.abc import Awaitable, Callable
from logging import INFO
from types import SimpleNamespace

import pytest

from pyarchivist.Wikimedia_Commons import __main__ as commons_module_main
from tests.utils import RunModuleHelper

"""Public symbols exported by this module (none)."""
__all__ = ()


def test_module_execution_uses_runnify(run_module_helper: RunModuleHelper) -> None:
    """Running the subcommand module as ``__main__`` should call ``runnify``."""
    called = run_module_helper(
        "pyarchivist.Wikimedia_Commons.__main__",
        ["pyarchivist.Wikimedia_Commons"],
    )

    assert called["runnify_called"] is True
    assert called["wrapper_called"] is True
    assert called["async_function"] == "main"


@pytest.mark.anyio
async def test_main_configures_logging_and_invokes_parsed_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The async ``main`` should parse argv and await ``entry.invoke(entry)``."""
    seen: dict[str, object] = {}

    async def fake_invoke(namespace: object) -> None:
        """Capture namespace passed to ``invoke``."""
        seen["namespace"] = namespace

    class _FakeParser:
        """Parser stub that captures parsed argv for assertions."""

        def parse_args(self, args: list[str]) -> SimpleNamespace:
            """Return a namespace exposing an async ``invoke`` method."""
            seen["argv"] = list(args)
            return SimpleNamespace(invoke=fake_invoke)

    def fake_basic_config(*_args: object, **kwargs: object) -> None:
        """Capture logging setup kwargs used by ``main``."""
        seen["level"] = kwargs.get("level")

    monkeypatch.setattr(commons_module_main, "parser", lambda: _FakeParser())
    monkeypatch.setattr(commons_module_main, "basicConfig", fake_basic_config)
    monkeypatch.setattr(
        commons_module_main,
        "argv",
        ["pyarchivist.Wikimedia_Commons", "-d", "tmp", "File:Example.jpg"],
    )

    await commons_module_main.main()

    assert seen["level"] == INFO
    assert seen["argv"] == ["-d", "tmp", "File:Example.jpg"]
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

    monkeypatch.setattr(commons_module_main, "runnify", fake_runnify)

    commons_module_main.__main__()

    assert captured["async_func"] is commons_module_main.main
    assert captured["backend_options"] == {"use_uvloop": True}
    assert captured["runner_called"] is True
