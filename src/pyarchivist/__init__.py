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

from logging import getLogger as _getLogger
from sys import version as _ver
from typing import Literal as _Lit
from typing import TypedDict as _TDict
from typing import final as _fin

__all__ = (
    "AUTHORS",
    "NAME",
    "VERSION",
    "LOGGER",
    "OPEN_TEXT_OPTIONS",
    "USER_AGENT",
)


@_fin
class _OpenOptions(_TDict):
    encoding: str
    errors: _Lit[
        "strict",
        "ignore",
        "replace",
        "surrogateescape",
        "xmlcharrefreplace",
        "backslashreplace",
        "namereplace",
    ]
    newline: None | _Lit["", "\n", "\r", "\r\n"]


# update `pyproject.toml`
AUTHORS = (
    {
        "name": "William So",
        "email": "polyipseity@gmail.com",
    },
)
NAME = "pyarchivist"
VERSION = "2.0.1"

LOGGER = _getLogger(NAME)
OPEN_TEXT_OPTIONS: _OpenOptions = {
    "encoding": "UTF-8",
    "errors": "strict",
    "newline": None,
}
USER_AGENT = f"{NAME}/{VERSION} ({AUTHORS[0]['email']}) Python/{_ver}"
