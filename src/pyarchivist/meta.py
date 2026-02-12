"""Package metadata and configuration.

This module contains package-level metadata and configuration constants. Modules
should import package metadata directly from this module instead of relying on
re-exports from `pyarchivist.__init__` (for example: ``from pyarchivist.meta import VERSION``).
"""

from logging import getLogger
from sys import version
from typing import Literal, TypedDict, final

from pydantic import BaseModel, ConfigDict

__all__ = (
    "AUTHORS",
    "NAME",
    "VERSION",
    "LOGGER",
    "OPEN_TEXT_OPTIONS",
    "USER_AGENT",
    "PackageConfig",
    "PACKAGE_CONFIG",
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


class PackageConfig(BaseModel):
    """Validated package configuration view.

    Provides a pydantic view over a small set of package-level constants so
    callers that prefer runtime validation or programmatic access can use a
    single validated object. The module-level constants remain as the
    canonical exports for backwards compatibility.
    """

    name: str
    version: str
    authors: tuple[dict[str, str], ...]
    open_text_options: _OpenOptions
    user_agent: str

    model_config = ConfigDict(frozen=True)


# exported validated instance for convenience
PACKAGE_CONFIG = PackageConfig(
    name=NAME,
    version=VERSION,
    authors=AUTHORS,
    open_text_options=OPEN_TEXT_OPTIONS,
    user_agent=USER_AGENT,
)
