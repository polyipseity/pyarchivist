"""Tests for the `pyarchivist.types` module."""

import dataclasses

from anyio import Path

from pyarchivist import types as pyarchivist_types

"""Public symbols exported by this module (none)."""
__all__ = ()


def test_module_docstring() -> None:
    """Verify the module has a docstring."""
    assert pyarchivist_types.__doc__


def test_all_is_tuple() -> None:
    """Verify `__all__` is a tuple of strings."""
    assert isinstance(pyarchivist_types.__all__, tuple)
    for name in pyarchivist_types.__all__:
        assert isinstance(name, str)


def test_all_symbols_exist() -> None:
    """Verify each exported symbol is importable."""
    for name in pyarchivist_types.__all__:
        assert hasattr(pyarchivist_types, name)


def test_skipped_exit_code_shares_no_bits() -> None:
    """Verify ``SKIPPED`` is a non-zero bit outside every error flag."""
    error_flags = (
        pyarchivist_types.ExitCode.GENERIC_ERROR,
        pyarchivist_types.ExitCode.QUERY_ERROR,
        pyarchivist_types.ExitCode.FETCH_ERROR,
        pyarchivist_types.ExitCode.INDEX_ERROR,
    )

    assert pyarchivist_types.ExitCode.SKIPPED != 0
    for flag in error_flags:
        assert pyarchivist_types.ExitCode.SKIPPED & flag == 0


def test_exit_code_bit_values() -> None:
    """Verify each ``ExitCode`` member owns one distinct bit."""
    codes = pyarchivist_types.ExitCode

    assert codes.GENERIC_ERROR == 1
    assert codes.QUERY_ERROR == 2
    assert codes.FETCH_ERROR == 4
    assert codes.INDEX_ERROR == 8
    assert codes.SKIPPED == 16


def test_phase_alias_is_exported() -> None:
    """Verify the ``Phase`` alias is exported and present."""
    assert "Phase" in pyarchivist_types.__all__
    assert hasattr(pyarchivist_types, "Phase")


def test_args_fields() -> None:
    """Verify Args has the expected fields."""
    fields = {f.name for f in dataclasses.fields(pyarchivist_types.Args)}
    expected = {
        "inputs",
        "dest",
        "index",
        "skip_existing",
        "sanitize_filenames",
        "trust_env",
        "max_retries",
        "retry_delay",
        "request_timeout",
        "fail_fast",
        "bisect_queries",
    }
    assert fields == expected


def test_args_defaults() -> None:
    """Verify a plain `Args` skips existing files and never fails fast."""
    args = pyarchivist_types.Args(inputs=(), dest=Path("."), index=None)

    assert args.skip_existing is True
    assert args.sanitize_filenames is True
    assert args.trust_env is True
    assert args.fail_fast is False
    assert args.bisect_queries is True
