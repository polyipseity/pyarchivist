"""Source-agnostic types shared by all archive backends.

This module defines the fundamental data types used across
different archiving backends (Wikimedia Commons etc.).
Backend-specific logic lives in the respective subpackages.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import IntFlag, auto, unique
from typing import ClassVar, final

from anyio import Path

"""Public symbols exported by this module."""
__all__ = (
    "ExitCode",
    "Args",
    "ArchiveError",
    "ArchiveResult",
)


@final
@unique
class ExitCode(IntFlag):
    """Exit codes representing various error and partial-error conditions.

    Each member corresponds to a phase or a class of failure that may occur
    during a run. The bits can be combined to represent multiple simultaneous
    failure modes (for example partial fetch errors plus a generic error).
    """

    __slots__: ClassVar = ()

    GENERIC_ERROR = auto()
    QUERY_ERROR = auto()
    FETCH_ERROR = auto()
    INDEX_ERROR = auto()
    QUERY_ERROR_PARTIAL = QUERY_ERROR | 16
    FETCH_ERROR_PARTIAL = FETCH_ERROR | 32


@final
@dataclass(
    init=True,
    repr=True,
    eq=True,
    order=False,
    unsafe_hash=False,
    frozen=True,
    match_args=True,
    kw_only=True,
    slots=True,
)
class Args:
    """Immutable container for archive operation parameters.

    Attributes:
        inputs: sequence of input titles (strings)
        dest: destination path where files will be written
        index: optional index file path (Markdown)
        ignore_individual_errors: if True, continue on individual file errors
        skip_existing: if True, skip files that already exist at the destination
        max_retries: maximum number of retries for failed operations
        retry_delay: delay in seconds between retries
        request_timeout: timeout in seconds for HTTP requests
        progress_callback: optional callback for progress updates (current, total)
    """

    inputs: Sequence[str]
    dest: Path
    index: Path | None
    ignore_individual_errors: bool
    skip_existing: bool = False
    max_retries: int = 3
    retry_delay: float = 1.0
    request_timeout: float = 30.0
    progress_callback: Callable[[int, int], None] | None = None

    def __post_init__(self):
        """Normalize `inputs` to an immutable tuple after initialization."""
        object.__setattr__(self, "inputs", tuple(self.inputs))


@final
@dataclass(
    init=True,
    repr=True,
    eq=True,
    order=False,
    unsafe_hash=False,
    frozen=True,
    match_args=True,
    kw_only=True,
    slots=True,
)
class ArchiveError:
    """Represents an error that occurred during an archive operation.

    Attributes:
        phase: the phase in which the error occurred (e.g. "query", "fetch", "index")
        title: the title of the item that caused the error
        message: a human-readable error message
    """

    phase: str
    title: str
    message: str


@final
@dataclass(
    init=True,
    repr=True,
    eq=True,
    order=False,
    unsafe_hash=False,
    frozen=True,
    match_args=True,
    kw_only=True,
    slots=True,
)
class ArchiveResult:
    """The result of an archive operation.

    Attributes:
        downloaded: number of files successfully downloaded
        skipped: number of files skipped (e.g. because they already exist)
        errors: tuple of ArchiveError objects collected during the operation
    """

    downloaded: int
    skipped: int
    errors: tuple[ArchiveError, ...]
