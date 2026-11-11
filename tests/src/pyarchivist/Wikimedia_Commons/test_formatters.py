"""Formatter tests for Wikimedia_Commons credit text and index lines."""

import re
import string
from html import escape as html_escape
from urllib.parse import quote, unquote

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pyarchivist.Wikimedia_Commons.main import (
    _INDEX_FORMAT_PATTERN,
    _PERCENT_ESCAPE_SAFE,
    _credit_formatter,
    _index_formatter,
)
from pyarchivist.Wikimedia_Commons.models import (
    ExtMetadata,
    ImageInfoEntry,
    Page,
    Value,
)

"""Public symbols exported by this module (none)."""
__all__ = ()


@pytest.mark.parametrize(
    "raw,has_bracket,has_backslash,has_safe",
    [
        (r"a]b\\c", True, True, False),
        ("simple-name.jpg", False, False, False),
        ("path/with/slash", False, False, True),
        ("comma,name.jpg", False, False, True),
        (r"brackets[]\\back", True, True, False),
        ("percent%sign", False, False, False),
    ],
)
def test_index_formatter_handles_various_filenames(
    raw: str, has_bracket: bool, has_backslash: bool, has_safe: bool
) -> None:
    """Brackets, backslashes and safe characters are handled as documented."""
    out = _index_formatter(raw, "credit")

    match = re.search(r"^- \[((?:\\.|[^\]])*?)\]\((.*?)\): ", out)
    assert match is not None
    label, link = match.groups()

    if has_bracket:
        assert "\\" in label
        assert "%5D" in link
    if has_backslash:
        assert label.count("\\") == raw.count("\\") * 2 + raw.count("]")
        assert "%5C" in link
    if has_safe:
        for character in ("/", ","):
            if character in raw:
                assert character in link

    assert out.endswith(": credit")


@given(
    st.tuples(
        st.text(
            alphabet=string.ascii_letters + string.digits + r" ]\\/_.-%,()",
            min_size=0,
            max_size=59,
        ),
        st.text(
            alphabet=string.ascii_letters + string.digits + r"]\\/_.-%,()",
            min_size=1,
            max_size=1,
        ),
    ).map(lambda parts: parts[0] + parts[1])
)
def test_index_formatter_property(fname: str) -> None:
    """Generated filenames are escaped in the label and quoted in the link."""
    out = _index_formatter(fname, "credit")
    match = re.search(r"^- \[((?:\\.|[^\]])*?)\]\((.*?)\): ", out)
    assert match is not None
    label, link = match.groups()

    if "]" in fname:
        assert "\\" in label
        assert "%5D" in link
    if "\\" in fname or "]" in fname:
        assert label.count("\\") == fname.count("\\") * 2 + fname.count("]")

    assert quote(fname, safe=_PERCENT_ESCAPE_SAFE) in link


@pytest.mark.parametrize(
    "filename",
    ["simple.jpg", "a]b", r"folder\\item].png", "comma,name.jpg"],
)
def test_index_formatter_output_matches_index_pattern(filename: str) -> None:
    """Formatted lines parse back through ``_INDEX_FORMAT_PATTERN``."""
    line = _index_formatter(filename, "credit")
    match = _INDEX_FORMAT_PATTERN.match(line)

    assert match is not None
    assert match.group(0) == line
    assert unquote(match.group(2)) == filename


def test_index_formatter_display_overrides_link_text() -> None:
    """A given ``display`` becomes the visible link text."""
    line = _index_formatter("sanitized.jpg", "credit", display="Original Name.jpg")
    match = re.search(r"^- \[(.+?)\]\((.+?)\): ", line)
    assert match is not None
    label, link = match.groups()

    assert label == "Original Name.jpg"
    assert unquote(link) == "sanitized.jpg"


def test_index_formatter_display_none_falls_back_to_filename() -> None:
    """Without ``display`` the filename is the link text."""
    line = _index_formatter("file.jpg", "credit")
    match = re.search(r"^- \[(.+?)\]\((.+?)\): ", line)
    assert match is not None
    label, link = match.groups()

    assert label == "file.jpg"
    assert unquote(link) == "file.jpg"


def test_credit_formatter_unknown_and_license_url_variants() -> None:
    """Unknown author and license markers fall back to descriptive text."""
    ii = ImageInfoEntry(
        descriptionurl="https://commons.wikimedia.org/wiki/File:Test.jpg",
        url="https://upload.wikimedia.org/test.jpg",
        extmetadata=ExtMetadata(
            Artist=Value(value="Unknown author (reported)", source=""),
            LicenseShortName=Value(value="Unknown license", source=""),
            LicenseUrl=Value(value="https://example.org/license", source=""),
        ),
    )
    page = Page(title="File:Test.jpg", imageinfo=(ii,))

    credit = _credit_formatter(page)

    assert "See page for author" in credit
    assert '<a href="https://example.org/license">See page for license</a>' in credit


def test_credit_formatter_strips_html_and_newlines() -> None:
    """Embedded HTML tags and newlines are removed from the credit."""
    ii = ImageInfoEntry(
        descriptionurl="https://commons.wikimedia.org/wiki/File:Html.jpg",
        url="https://upload.wikimedia.org/html.jpg",
        extmetadata=ExtMetadata(Artist=Value(value="<b>Jane\nDoe</b>", source="")),
    )
    page = Page(title="File:Html.jpg", imageinfo=(ii,))

    credit = _credit_formatter(page)

    assert "<b>" not in credit
    assert "\n" not in credit
    assert "Jane" in credit and "Doe" in credit
    assert '<a href="https://commons.wikimedia.org/wiki/File:Html.jpg">' in credit


def _wrap_bold(text: str) -> str:
    """Wrap *text* in a bold tag for the property test."""
    return f"<b>{text}</b>"


@given(
    artist=st.one_of(
        st.text(alphabet=string.ascii_letters + " \n<>-", min_size=0, max_size=40),
        st.just("Unknown author"),
        st.builds(_wrap_bold, st.text(string.ascii_letters, min_size=1, max_size=10)),
    ),
    lic=st.one_of(
        st.text(alphabet=string.ascii_letters + " \n-", min_size=0, max_size=30),
        st.just("Unknown license"),
    ),
    lic_url=st.one_of(st.none(), st.just(""), st.just("https://example.org/license")),
)
def test_credit_formatter_property_variants(
    artist: str, lic: str, lic_url: str | None
) -> None:
    """Generated metadata is sanitized and falls back to descriptive text."""
    emd = ExtMetadata(
        Artist=Value(value=artist if artist else None),
        LicenseShortName=Value(value=lic if lic else None),
        LicenseUrl=Value(value=lic_url if lic_url else None),
    )
    ii = ImageInfoEntry(
        descriptionurl="https://commons.wikimedia.org/wiki/File:Prop.jpg",
        url="https://upload.wikimedia.org/prop.jpg",
        extmetadata=emd,
    )
    page = Page(title="File:Prop.jpg", imageinfo=(ii,))

    out = _credit_formatter(page)

    if artist and "unknown author" in artist.casefold():
        assert "See page for author" in out
    else:
        expected_author = re.sub(r"<[^>]*>", "", artist, flags=re.DOTALL)
        expected_author = re.sub(
            r"\s+", " ", expected_author.replace("\n", " ")
        ).strip()
        if expected_author:
            assert html_escape(expected_author.split()[0]) in out
        else:
            assert "See page for author" in out

    if lic and "unknown license" in lic.casefold():
        assert "See page for license" in out
    else:
        expected_lic = re.sub(r"\s+", " ", lic.replace("\n", " ")).strip()
        if expected_lic:
            assert html_escape(expected_lic.split()[0]) in out
        else:
            assert "See page for license" in out

    if lic_url:
        assert f'<a href="{lic_url}"' in out
