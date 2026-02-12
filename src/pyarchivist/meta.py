"""Package metadata and configuration.

This module contains package-level metadata and configuration constants. Modules
should import package metadata directly from this module instead of relying on
re-exports from `pyarchivist.__init__` (for example: ``from pyarchivist.meta import VERSION``).
"""

from logging import getLogger
from sys import version
from typing import Literal, TypedDict, final

__all__ = (
    "AUTHORS",
    "NAME",
    "VERSION",
    "LOGGER",
    "OPEN_TEXT_OPTIONS",
    "USER_AGENT",
)


@final
class _OpenOptions(TypedDict):
    """Options accepted by :func:`open` when opening text files.

    This TypedDict documents the small subset of ``open()`` options the
    package uses when creating or reading text files. The keys mirror the
    corresponding arguments to the built-in ``open`` and are used to create
    the canonical ``OPEN_TEXT_OPTIONS`` mapping.
    """

    encoding: str
    errors: Literal[
        "strict",
        "ignore",
        "replace",
        "surrogateescape",
        "xmlcharrefreplace",
        "backslashreplace",
        "namereplace",
    ]
    newline: None | Literal["", "\n", "\r", "\r\n"]


# update `pyproject.toml`
AUTHORS = (
    {
        "name": "William So",
        "email": "polyipseity@gmail.com",
    },
)
NAME = "pyarchivist"
VERSION = "2.0.1"

LOGGER = getLogger(NAME)
OPEN_TEXT_OPTIONS: _OpenOptions = {
    "encoding": "UTF-8",
    "errors": "strict",
    "newline": None,
}
USER_AGENT = f"{NAME}/{VERSION} ({AUTHORS[0]['email']}) Python/{version}"
