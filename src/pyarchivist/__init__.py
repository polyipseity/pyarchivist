"""Minimal package surface for `pyarchivist`.

Re-exports the library API from subpackages. Modules should also import
package metadata and configuration from `pyarchivist.meta` (for example:
``from pyarchivist.meta import VERSION``).
"""

from .meta import VERSION as __version__
from .Wikimedia_Commons import ArchiveError, ArchiveResult, Args, archive

"""Package public API exports."""
__all__ = ("__version__", "ArchiveError", "ArchiveResult", "Args", "archive")
