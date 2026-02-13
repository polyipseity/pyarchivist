"""Unit tests for Wikimedia_Commons pydantic models and credit formatting.

Covers parsing of typical and partial MediaWiki JSON payloads and ensures
that `_credit_formatter` handles missing/partial metadata without raising.
"""

from typing import Any

from pyarchivist.Wikimedia_Commons.main import _credit_formatter
from pyarchivist.Wikimedia_Commons.models import (
    ImageInfoEntry,
    Page,
    ResponseModel,
)

__all__ = ()


def _sample_response_with_metadata() -> dict[str, Any]:
    """Return a sample API response containing extended metadata."""
    return {
        "query": {
            "pages": {
                "1": {
                    "title": "File:Example.jpg",
                    "imageinfo": [
                        {
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                            "url": "https://upload.wikimedia.org/example.jpg",
                            "extmetadata": {
                                "Artist": {"value": "Jane Doe", "source": ""},
                                "LicenseShortName": {
                                    "value": "CC BY-SA 4.0",
                                    "source": "",
                                },
                                "LicenseUrl": {
                                    "value": "https://creativecommons.org/licenses/by-sa/4.0/",
                                    "source": "",
                                },
                            },
                        }
                    ],
                }
            }
        }
    }


def _sample_response_without_metadata() -> dict[str, Any]:
    """Return a sample API response with empty/absent extmetadata."""
    return {
        "query": {
            "pages": {
                "2": {
                    "title": "File:NoMeta.jpg",
                    "imageinfo": [
                        {
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:NoMeta.jpg",
                            "url": "https://upload.wikimedia.org/nometa.jpg",
                            "extmetadata": {},
                        }
                    ],
                }
            }
        }
    }


def test_response_model_parses_extended_metadata():
    """Ensure ResponseModel parses extended metadata into expected fields."""
    raw = _sample_response_with_metadata()
    model = ResponseModel.model_validate(raw)
    page = model.query.pages["1"]

    assert isinstance(page, Page)
    assert page.title == "File:Example.jpg"
    assert page.imageinfo is not None
    ii = page.imageinfo[0]
    assert isinstance(ii, ImageInfoEntry)
    assert ii.extmetadata is not None
    assert ii.extmetadata.Artist is not None
    assert ii.extmetadata.Artist.value == "Jane Doe"


def test_response_model_handles_missing_fields_and_credit_formatter():
    """Verify model handles missing extmetadata and `_credit_formatter` falls back."""
    raw = _sample_response_without_metadata()
    model = ResponseModel.model_validate(raw)
    page = model.query.pages["2"]

    assert page.imageinfo is not None
    ii = page.imageinfo[0]
    # extmetadata may be present but empty; its fields should be None
    assert ii.extmetadata is not None
    assert ii.extmetadata.Artist is None

    # ensure _credit_formatter does not raise and returns fallback strings
    credit = _credit_formatter(page)
    assert "See page for author" in credit
    assert "See page for license" in credit
