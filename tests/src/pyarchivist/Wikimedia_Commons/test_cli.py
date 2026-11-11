"""Command-line parser tests for the Wikimedia_Commons subcommand."""

from argparse import _VersionAction
from os import PathLike, fspath
from typing import cast

import pytest
from anyio import Path

from pyarchivist.meta import VERSION
from pyarchivist.types import Args
from pyarchivist.Wikimedia_Commons.__main__ import parser
from pyarchivist.Wikimedia_Commons.main import archive
from tests.src.pyarchivist.Wikimedia_Commons.fakes import (
    _CapturingClientSession,
    _patch_session_class,
)

"""Public symbols exported by this module (none)."""
__all__ = ()


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
