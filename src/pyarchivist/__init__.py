"""Minimal package surface for `pyarchivist`.

This package intentionally avoids re-exporting module internals from
`__init__`. Modules should import package metadata and configuration from
`pyarchivist.meta` (for example: ``from pyarchivist.meta import VERSION``).
"""

__all__ = ()
