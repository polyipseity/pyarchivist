"""Wikimedia Commons archive subpackage.

Re-exports the library API from :mod:`.main`.
"""

from .main import ArchiveError, ArchiveResult, Args, ExitCode, archive

"""Public API exports."""
__all__ = (
    "ExitCode",
    "Args",
    "ArchiveError",
    "ArchiveResult",
    "archive",
)
