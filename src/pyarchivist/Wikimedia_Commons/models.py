"""Pydantic models for Wikimedia Commons API responses and CLI arguments.

This module centralizes strongly-typed models used by the Wikimedia Commons
subcommand. Using pydantic ensures that JSON responses are validated and
that CLI arguments are validated and canonicalized in a single place.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, DirectoryPath, FilePath, NewPath

__all__ = (
    "Value",
    "ExtMetadata",
    "ImageInfoEntry",
    "Page",
    "Query",
    "ResponseModel",
    "Args",
)


class Value(BaseModel):
    """A small container providing a textual ``value`` and its ``source``.

    Mirrors the small value structures returned in extended metadata blocks
    from the MediaWiki API (for example ``Artist`` and ``LicenseUrl``).
    """

    value: str | None = None
    source: str | None = None

    model_config = {"frozen": True}


class ExtMetadata(BaseModel):
    """Extended metadata block containing author and license information."""

    Artist: Value | None = None
    LicenseShortName: Value | None = None
    LicenseUrl: Value | None = None

    model_config = {"frozen": True}


class ImageInfoEntry(BaseModel):
    """Describes a single image variant including URL and metadata."""

    descriptionurl: str
    extmetadata: ExtMetadata | None = None
    url: str

    model_config = {"frozen": True}


class Page(BaseModel):
    """A page container with a title and optional image information."""

    title: str
    imageinfo: Sequence[ImageInfoEntry] | None = None

    model_config = {"frozen": True}


class Query(BaseModel):
    """Top-level query mapping containing page id -> :class:`Page`."""

    pages: Mapping[str, Page]

    model_config = {"frozen": True}


class ResponseModel(BaseModel):
    """Top-level response model for the MediaWiki API query flow."""

    query: Query

    model_config = {"frozen": True}


class Args(BaseModel):
    """Immutable, validated container for parsed CLI arguments.

    Fields are compatible with the values produced by the CLI parser and are
    validated on construction. ``inputs`` is normalized to a tuple to preserve
    immutability semantics.
    """

    inputs: tuple[str, ...]
    dest: DirectoryPath | NewPath
    index: FilePath | NewPath | None = None
    ignore_individual_errors: bool = False

    model_config = {"frozen": True}
