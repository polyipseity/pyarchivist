"""pyarchivist package metadata and configuration.

This module exposes package-level constants and a configured logger used by
other modules in the package. Keep the package version here as the single
source-of-truth for releases.

Exports:
- AUTHORS: author metadata
- NAME: package name
- VERSION: package version string
- LOGGER: configured logger for the package
- OPEN_TEXT_OPTIONS: defaults for opening text files
- USER_AGENT: default HTTP User-Agent used by HTTP clients
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
