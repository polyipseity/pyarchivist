"""Tests that the package version defined in pyproject.toml matches the `VERSION`
constant defined in `src/pyarchivist/meta.py`.

This test reads `pyproject.toml` using `tomllib` and imports the package
module to assert the two version values are equal.
"""

import importlib.util
import tomllib

import pytest
from anyio import Path

import pyarchivist
from pyarchivist.meta import VERSION as META_VERSION

"""Public symbols exported by this module (none)."""
__all__ = ()


@pytest.mark.anyio
async def test_pyproject_and_init_version_match():
    """Ensure [project].version in pyproject.toml equals `src/pyarchivist/meta.py::VERSION`.

    This test loads the project metadata from the TOML file and imports the
    package module to compare versions.
    """
    pyproject_text = await Path("pyproject.toml").read_text(encoding="utf-8")
    pyproject = tomllib.loads(pyproject_text)
    assert "project" in pyproject and "version" in pyproject["project"], (
        "pyproject.toml is missing [project].version"
    )
    py_version = pyproject["project"]["version"]

    meta_path = Path("src/pyarchivist/meta.py")
    spec = importlib.util.spec_from_file_location("pyarchivist.meta", str(meta_path))
    assert spec is not None and spec.loader is not None, (
        f"Could not load module from {meta_path}"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "VERSION"), (
        "Could not find VERSION in src/pyarchivist/meta.py"
    )
    meta_version = module.VERSION

    assert py_version == meta_version, (
        f"Version mismatch: pyproject.toml has {py_version!r} but src/pyarchivist/meta.py has {meta_version!r}"
    )


def test_package_dunder_version_matches_meta():
    """Ensure public pyarchivist.__version__ matches pyarchivist.meta.VERSION."""

    assert hasattr(pyarchivist, "__version__"), "pyarchivist.__version__ is missing"
    assert pyarchivist.__version__ == META_VERSION
