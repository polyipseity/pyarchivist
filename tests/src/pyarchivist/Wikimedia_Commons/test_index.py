"""Index-phase tests for the Wikimedia_Commons flow.

Merge keying, atomic replacement, file creation and error mapping are
asserted through ``archive`` and the ``main`` exit codes.
"""

from os import PathLike
from typing import Any, cast

import pytest
from anyio import Path

from pyarchivist.types import Args, ExitCode
from pyarchivist.Wikimedia_Commons.__main__ import main
from pyarchivist.Wikimedia_Commons.main import archive
from tests.src.pyarchivist.Wikimedia_Commons.fakes import (
    _FakeClientSession,
    _page,
    _patch_client,
)

"""Public symbols exported by this module (none)."""
__all__ = ()


@pytest.mark.anyio
async def test_index_merge_is_keyed_by_filename_not_display(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A sanitized title keeps one index line across repeated runs."""
    session = _FakeClientSession({"File:A?B.jpg": _page("File:A?B.jpg")})
    session.file_bytes = b"data"
    _patch_client(monkeypatch, session)

    index_path = Path(tmp_path) / "index.md"
    args = Args(
        inputs=("File:A?B.jpg",),
        dest=Path(tmp_path),
        index=index_path,
        skip_existing=False,
    )
    await archive(args)
    await archive(args)

    lines = (await index_path.read_text(encoding="utf-8")).splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("- [A?B.jpg](A_B.jpg): ")


@pytest.mark.anyio
async def test_index_write_replaces_the_file_atomically(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """The index is written to a sibling temp file and then replaced."""
    session = _FakeClientSession({"File:A.jpg": _page("File:A.jpg")})
    session.file_bytes = b"data"
    _patch_client(monkeypatch, session)

    replaced: list[tuple[str, str]] = []
    original = cast(Any, Path.replace)

    async def recording_replace(self: Path, target: Path) -> Path:
        """Record the replacement pair and delegate to the real method."""
        replaced.append((self.name, target.name))
        return await original(self, target)

    monkeypatch.setattr(Path, "replace", recording_replace)

    index_path = Path(tmp_path) / "index.md"
    await archive(Args(inputs=("File:A.jpg",), dest=Path(tmp_path), index=index_path))

    assert (".index.md.tmp", "index.md") in replaced
    assert not await (Path(tmp_path) / ".index.md.tmp").exists()
    assert await index_path.exists()


@pytest.mark.anyio
async def test_index_write_error_sets_index_and_generic_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A failed index write is reported while the downloaded file survives."""
    session = _FakeClientSession({"File:A.jpg": _page("File:A.jpg")})
    session.file_bytes = b"ok"
    _patch_client(monkeypatch, session)

    original = cast(Any, Path.replace)

    async def failing_replace(self: Path, target: Path) -> Path:
        """Fail only for the index temp file, leaving downloads untouched."""
        if self.name == ".index.md.tmp":
            raise OSError("index replace failure")
        return await original(self, target)

    monkeypatch.setattr(Path, "replace", failing_replace)

    code = await main(
        Args(
            inputs=("File:A.jpg",),
            dest=Path(tmp_path),
            index=Path(tmp_path) / "index.md",
        )
    )

    assert await (Path(tmp_path) / "A.jpg").exists()
    assert code & ExitCode.INDEX_ERROR
    assert code & ExitCode.GENERIC_ERROR


@pytest.mark.anyio
async def test_index_file_created_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A missing index file and its directory are created before writing."""
    session = _FakeClientSession({"File:New.jpg": _page("File:New.jpg")})
    session.file_bytes = b"data"
    _patch_client(monkeypatch, session)

    index_path = Path(tmp_path) / "subdir" / "index.md"
    await archive(Args(inputs=("File:New.jpg",), dest=Path(tmp_path), index=index_path))

    assert await index_path.exists()
    assert "New.jpg" in await index_path.read_text(encoding="utf-8")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "initial_index,expected_lines",
    [
        (
            "Header\n\n",
            [
                '- [Zed.jpg](Zed.jpg): <a href="https://commons.wikimedia.org/wiki/'
                'File:Zed.jpg">See page for author</a>, See page for license, '
                "via Wikimedia Commons"
            ],
        ),
        (
            "Header\n\n- [Existing](Existing): Existing credit\n",
            [
                "- [Existing](Existing): Existing credit",
                '- [Zed.jpg](Zed.jpg): <a href="https://commons.wikimedia.org/wiki/'
                'File:Zed.jpg">See page for author</a>, See page for license, '
                "via Wikimedia Commons",
            ],
        ),
    ],
)
async def test_indexing_updates_index_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: PathLike[str],
    initial_index: str,
    expected_lines: list[str],
) -> None:
    """Indexing updates the last paragraph and keeps earlier paragraphs."""
    session = _FakeClientSession({"File:Zed.jpg": _page("File:Zed.jpg")})
    session.file_bytes = b"file-contents"
    _patch_client(monkeypatch, session)

    index_path = Path(tmp_path) / "index.md"
    await index_path.write_text(initial_index, encoding="utf-8")

    await archive(Args(inputs=("File:Zed.jpg",), dest=Path(tmp_path), index=index_path))

    text = await index_path.read_text(encoding="utf-8")
    paragraphs = text.strip().split("\n\n")
    if "- [" in initial_index:
        assert paragraphs[0].startswith("Header")
        assert paragraphs[-1].splitlines() == sorted(expected_lines)
    else:
        assert paragraphs == expected_lines


@pytest.mark.anyio
async def test_indexing_merges_percent_encoded_existing_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A percent-encoded link target is matched instead of duplicated."""
    session = _FakeClientSession({"File:a]b": _page("File:a]b")})
    session.file_bytes = b"d"
    _patch_client(monkeypatch, session)

    index_path = Path(tmp_path) / "index.md"
    await index_path.write_text(
        "Header\n\n- [a\\]b](a%5Db): Old credit\n- [Other](Other): Other credit\n",
        encoding="utf-8",
    )

    await archive(Args(inputs=("File:a]b",), dest=Path(tmp_path), index=index_path))

    last = (await index_path.read_text(encoding="utf-8")).strip().split("\n\n")[-1]
    assert "Old credit" not in last
    assert "a]b" in last
    assert "Other credit" in last


@pytest.mark.anyio
async def test_sanitize_filenames_index_uses_unsanitized_display(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """The index link text keeps the unsanitized title."""
    title = 'File:A "quoted" name.jpg'
    session = _FakeClientSession({title: _page(title)})
    session.file_bytes = b"img"
    _patch_client(monkeypatch, session)

    index_path = Path(tmp_path) / "index.md"
    await archive(Args(inputs=(title,), dest=Path(tmp_path), index=index_path))

    content = await index_path.read_text(encoding="utf-8")
    assert 'A "quoted" name.jpg' in content
    assert "A%20_quoted_%20name.jpg" in content
