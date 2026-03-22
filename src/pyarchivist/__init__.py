"""Minimal package surface for `pyarchivist`.

This package intentionally avoids re-exporting module internals from
`__init__`. Modules should import package metadata and configuration from
`pyarchivist.meta` (for example: ``from pyarchivist.meta import VERSION``).
"""

from .meta import VERSION as __version__

"""Package public API exports."""
__all__ = ("__version__",)
