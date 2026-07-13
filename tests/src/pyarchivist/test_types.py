"""Tests for the `pyarchivist.types` module."""

from __future__ import annotations

import dataclasses

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


def test_args_fields() -> None:
    """Verify Args has the expected fields."""
    fields = {f.name for f in dataclasses.fields(pyarchivist_types.Args)}
    expected = {
        "inputs",
        "dest",
        "index",
        "ignore_individual_errors",
        "skip_existing",
        "max_retries",
        "retry_delay",
        "request_timeout",
        "progress_callback",
    }
    assert fields == expected
