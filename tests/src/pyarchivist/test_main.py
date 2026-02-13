"""Tests for top-level CLI and property-based checks for formatting helpers.

Covers:
- `pyarchivist.parser()` integration with subcommands
- property-based tests for `_index_formatter` and `_credit_formatter`
"""

import argparse
import re
import string
from argparse import ArgumentParser, _SubParsersAction, _VersionAction
from typing import Any
from urllib.parse import quote

import pytest
from anyio import Path
from html2text import HTML2Text
from hypothesis import given
from hypothesis import strategies as st

from pyarchivist import main as pkg_main
from pyarchivist.meta import VERSION
from pyarchivist.Wikimedia_Commons import main as commons_main
from pyarchivist.Wikimedia_Commons.models import (
    ExtMetadata,
    ImageInfoEntry,
    Page,
    Value,
)

__all__ = ()


def test_top_level_parser_includes_wikimedia_subparser(tmp_path: Path) -> None:
    """Verify the top-level parser includes the Wikimedia_Commons subparser."""
    p: ArgumentParser = pkg_main.parser()

    # ensure subcommand exists and delegates to the Wikimedia_Commons parser
    ns = p.parse_args(["Wikimedia_Commons", "-d", str(tmp_path), "File:Foo.jpg"])

    # subparser should have produced an `invoke` coroutine factory
    assert hasattr(ns, "invoke")
    assert getattr(ns, "inputs") == ["File:Foo.jpg"]
    assert isinstance(ns.dest, Path)


def test_top_level_parser_version_action_contains_version() -> None:
    """Ensure the top-level parser exposes a `--version` action containing VERSION."""

    p = pkg_main.parser()
    version_actions = [
        a for a in p._actions if "--version" in getattr(a, "option_strings", [])
    ]
    assert version_actions, "--version action missing"
    assert isinstance(version_actions[0], _VersionAction)
    assert version_actions[0].version is not None
    assert version_actions[0].version.endswith(f"v{VERSION}")


# Property-based tests for _index_formatter
@given(
    st.text(
        alphabet=string.ascii_letters + string.digits + r" ]\\/_.-",
        min_size=1,
        max_size=40,
    )
)
def test_index_formatter_escapes_and_quotes_property(fname: str) -> None:
    """Property test: ensure `_index_formatter` escapes labels and quotes links."""
    # ensure generated filename contains characters we expect (guard)
    out = commons_main._index_formatter(fname, "credit")

    # label is between the first '[' and the following ']'
    m = re.search(r"^- \[(.*?)]\((.*?)\): ", out)
    assert m is not None
    label, link = m.groups()

    # label should contain escaped ']' and doubled backslashes when present
    if "]" in fname:
        assert "\\]" in label
    if "\\" in fname:
        assert "\\\\" in label

    # link target should be the quoted filename
    expected = quote(fname, safe=commons_main._PERCENT_ESCAPE_SAFE)
    assert expected in link


def _wrap_bold(text: str) -> str:
    """Wrap `text` in a simple <b/> HTML tag (helper for property tests)."""
    return f"<b>{text}</b>"


# Property-based tests for _credit_formatter
@given(
    author=st.one_of(
        st.text(alphabet=string.ascii_letters + " \n<>-", min_size=0, max_size=30),
        st.just("Unknown author"),
        st.builds(
            _wrap_bold,
            st.text(alphabet=string.ascii_letters + " ", min_size=1, max_size=10),
        ),
    ),
    lic=st.one_of(
        st.text(alphabet=string.ascii_letters + " \n-", min_size=0, max_size=20),
        st.just("Unknown license"),
    ),
    lic_url=st.one_of(st.none(), st.just(""), st.just("https://example.org/license")),
)
def test_credit_formatter_property(author: str, lic: str, lic_url: str | None) -> None:
    """Property test: `_credit_formatter` sanitizes metadata and provides fallbacks."""
    # build an ImageInfoEntry with the generated metadata and verify that
    # the output contains sanitized/expected content.
    emd = ExtMetadata(
        Artist=Value(value=author if author != "" else None),
        LicenseShortName=Value(value=lic if lic != "" else None),
        LicenseUrl=Value(value=lic_url if lic_url else None),
    )
    ii = ImageInfoEntry(
        descriptionurl="https://commons.wikimedia.org/wiki/File:Prop.jpg",
        url="https://upload.wikimedia.org/prop.jpg",
        extmetadata=emd,
    )
    page = Page(title="File:Prop.jpg", imageinfo=(ii,))

    out = commons_main._credit_formatter(page)

    # unknown author -> fallback text
    if author and "unknown author" in author.casefold():
        assert "See page for author" in out
    else:
        # normalize author the same way the implementation does: run through
        # html2text (which may turn tags into emphasis markers), then collapse
        # whitespace and treat emphasis-only values as absent.

        _ht = HTML2Text()
        _ht.emphasis_mark = "_"
        _ht.ignore_links = True
        _ht.single_line_break = True
        _ht.strong_mark = "__"
        _ht.ul_item_mark = "-"

        expected_author = _ht.handle(author or "").strip()
        # treat values composed only of emphasis markers/whitespace as empty
        if not expected_author.replace("_", "").strip():
            expected_author = ""
        expected_author = re.sub(
            r"\s+", " ", expected_author.replace("\n", " ")
        ).strip()
        if expected_author:
            assert expected_author.split()[0] in out
        else:
            # empty/entirely-tagged author should fall back
            assert "See page for author" in out

    # license handling
    if lic and "unknown license" in lic.casefold():
        assert "See page for license" in out
    else:
        expected_lic = re.sub(r"\s+", " ", (lic or "").replace("\n", " ")).strip()
        if expected_lic:
            assert expected_lic.split()[0] in out
        else:
            assert "See page for license" in out

    # license URL, if present, should appear as an <a href=...> wrapper
    if lic_url:
        assert f'<a href="{lic_url}"' in out


def test_parser_accepts_parent_factory_and_forwards_kwargs() -> None:
    """Verify `parser(parent=...)` forwards kwargs to the parent factory."""
    called: dict[str, object] = {}

    def factory(*_a: object, **kwargs: Any) -> ArgumentParser:
        """Factory that records received kwargs and returns a simple ArgumentParser."""
        # record that the factory received the expected prog kwarg
        called["prog"] = kwargs.get("prog")
        return ArgumentParser(**kwargs)

    p = pkg_main.parser(parent=factory)
    # parent factory should have been called and prog forwarded
    assert called.get("prog") is not None
    assert isinstance(p, ArgumentParser)


def test_subparser_name_sanitized_and_description_present() -> None:
    """Ensure the top-level subparser for Wikimedia_Commons is present and described."""
    p = pkg_main.parser()
    # find the subparsers action (ensure `.choices` is populated)
    group_untyped = next(
        a for a in p._actions if getattr(a, "choices", None) is not None
    )
    assert isinstance(group_untyped, _SubParsersAction)
    group: _SubParsersAction[Any] = group_untyped  # type: ignore[reportUnknownVariableType]
    choices = group.choices
    # subparser for Wikimedia_Commons should be present and have the expected description
    assert choices is not None
    assert "Wikimedia_Commons" in choices
    sp = choices["Wikimedia_Commons"]
    assert "archive data from Wikimedia Commons" in (sp.description or "")


def test_parser_requires_subcommand_raises_system_exit() -> None:
    """Verify calling the top-level parser without a subcommand raises ArgumentError."""
    p = pkg_main.parser()
    # parser was created with exit_on_error=False so argparse raises
    # ArgumentError rather than calling sys.exit()
    with pytest.raises(argparse.ArgumentError):
        p.parse_args([])
