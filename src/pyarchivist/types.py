"""Source-agnostic types shared by all archive backends.

This module defines the fundamental data types used across
different archiving backends (Wikimedia Commons etc.).
Backend-specific logic lives in the respective subpackages.
"""

from collections.abc import Sequence
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
    """Exit code bits for failure phases and skipped-only runs.

    Each failure phase owns one bit, and ``SKIPPED`` marks a run where every
    file was already present. Errors win over ``SKIPPED``, and a run that did
    nothing exits 0.
    """

    __slots__: ClassVar = ()

    GENERIC_ERROR = auto()
    QUERY_ERROR = auto()
    FETCH_ERROR = auto()
    INDEX_ERROR = auto()
    SKIPPED = auto()


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
        skip_existing: if True (default), skip files that already exist at the
            destination with the size the API reports
        sanitize_filenames: if True (default), filenames derived from page titles
            are sanitized for Windows compatibility using pathvalidate
        trust_env: if True (default), honour HTTPS_PROXY/HTTP_PROXY env vars
        max_retries: maximum number of retries for failed operations
        retry_delay: delay in seconds between retries
        request_timeout: timeout in seconds for HTTP requests
        fail_fast: download one file at a time and stop at the first fetch error
        bisect_queries: split a failing query batch to isolate the failing titles
    """

    inputs: Sequence[str]
    dest: Path
    index: Path | None
    skip_existing: bool = True
    sanitize_filenames: bool = True
    trust_env: bool = True
    max_retries: int = 3
    retry_delay: float = 1.0
    request_timeout: float = 30.0
    fail_fast: bool = False
    bisect_queries: bool = True

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
