"""Package surface re-exporting source-agnostic types.

Backend-specific archive functions are available from individual
subpackages (e.g. ``from pyarchivist.Wikimedia_Commons import archive``).
"""

from .meta import VERSION as __version__
from .types import ArchiveError, ArchiveResult, Args, ExitCode

"""Package public API exports."""
__all__ = (
    "__version__",
    "ArchiveError",
    "ArchiveResult",
    "Args",
    "ExitCode",
)
