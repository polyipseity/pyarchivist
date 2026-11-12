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
async def test_index_write_error_sets_index_flag(
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
    assert not await (Path(tmp_path) / ".index.md.tmp").exists()
    assert code == ExitCode.INDEX_ERROR


@pytest.mark.anyio
async def test_index_cleanup_failure_keeps_write_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A failing temp deletion must not replace the write error."""
    session = _FakeClientSession({"File:A.jpg": _page("File:A.jpg")})
    session.file_bytes = b"ok"
    _patch_client(monkeypatch, session)

    original_write_text = cast(Any, Path.write_text)

    async def failing_write_text(self: Path, text: str, **kwargs: Any) -> int:
        """Fail before the temp file is written."""
        if self.name == ".index.md.tmp":
            raise OSError("index write failure")
        return await original_write_text(self, text, **kwargs)

    original_unlink = cast(Any, Path.unlink)

    async def failing_unlink(self: Path, missing_ok: bool = False) -> None:
        """Fail the cleanup of the temp file only."""
        if self.name == ".index.md.tmp":
            raise OSError("cleanup failure")
        return await original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "write_text", failing_write_text)
    monkeypatch.setattr(Path, "unlink", failing_unlink)

    result = await archive(
        Args(
            inputs=("File:A.jpg",),
            dest=Path(tmp_path),
            index=Path(tmp_path) / "index.md",
        )
    )

    assert [error.phase for error in result.errors] == ["index"]
    assert "index write failure" in result.errors[0].message


@pytest.mark.anyio
async def test_index_with_invalid_utf8_reports_index_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """An index that is not UTF-8 is reported as an index failure."""
    session = _FakeClientSession({"File:A.jpg": _page("File:A.jpg")})
    session.file_bytes = b"ok"
    _patch_client(monkeypatch, session)

    index_path = Path(tmp_path) / "index.md"
    await index_path.write_bytes(b"\xff\xfe")

    code = await main(
        Args(inputs=("File:A.jpg",), dest=Path(tmp_path), index=index_path)
    )

    assert await (Path(tmp_path) / "A.jpg").exists()
    assert code == ExitCode.INDEX_ERROR


@pytest.mark.anyio
async def test_index_write_failure_removes_temp_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A failed index write still deletes the temp file it just wrote."""
    session = _FakeClientSession({"File:A.jpg": _page("File:A.jpg")})
    session.file_bytes = b"ok"
    _patch_client(monkeypatch, session)

    original = cast(Any, Path.write_text)

    async def failing_write_text(self: Path, text: str, **kwargs: Any) -> int:
        """Write the bytes, then fail the way a full disk would."""
        written = await original(self, text, **kwargs)
        if self.name == ".index.md.tmp":
            raise OSError("index write failure")
        return written

    monkeypatch.setattr(Path, "write_text", failing_write_text)

    code = await main(
        Args(
            inputs=("File:A.jpg",),
            dest=Path(tmp_path),
            index=Path(tmp_path) / "index.md",
        )
    )

    assert not await (Path(tmp_path) / ".index.md.tmp").exists()
    assert code == ExitCode.INDEX_ERROR


@pytest.mark.anyio
async def test_index_merge_folds_case_of_existing_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """A case-variant title replaces the old line instead of adding one."""
    session = _FakeClientSession({"File:ab.jpg": _page("File:ab.jpg")})
    session.file_bytes = b"data"
    _patch_client(monkeypatch, session)

    index_path = Path(tmp_path) / "index.md"
    await index_path.write_text("- [AB.jpg](AB.jpg): old credit\n", encoding="utf-8")

    await archive(
        Args(
            inputs=("File:ab.jpg",),
            dest=Path(tmp_path),
            index=index_path,
            skip_existing=False,
        )
    )

    lines = (await index_path.read_text(encoding="utf-8")).splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("- [ab.jpg](ab.jpg): ")


@pytest.mark.anyio
async def test_index_keeps_non_entry_lines_in_last_paragraph(
    monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike[str]
) -> None:
    """Prose in the last paragraph survives an index update."""
    session = _FakeClientSession({"File:B.jpg": _page("File:B.jpg")})
    session.file_bytes = b"data"
    _patch_client(monkeypatch, session)

    index_path = Path(tmp_path) / "index.md"
    await index_path.write_text(
        "Header\n\nnote above the list\n- [A.jpg](A.jpg): old\n", encoding="utf-8"
    )

    await archive(Args(inputs=("File:B.jpg",), dest=Path(tmp_path), index=index_path))

    lines = (await index_path.read_text(encoding="utf-8")).splitlines()
    assert lines[0] == "Header"
    assert "note above the list" in lines
    assert sum(line.startswith("- [") for line in lines) == 2


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
    """Indexing rewrites the last paragraph and keeps the text around it."""
    session = _FakeClientSession({"File:Zed.jpg": _page("File:Zed.jpg")})
    session.file_bytes = b"file-contents"
    _patch_client(monkeypatch, session)

    index_path = Path(tmp_path) / "index.md"
    await index_path.write_text(initial_index, encoding="utf-8")

    await archive(Args(inputs=("File:Zed.jpg",), dest=Path(tmp_path), index=index_path))

    lines = (await index_path.read_text(encoding="utf-8")).splitlines()
    paragraphs = "\n".join(lines).strip().split("\n\n")
    entries = [
        line
        for paragraph in paragraphs
        for line in paragraph.splitlines()
        if line.startswith("- [")
    ]
    assert paragraphs[0].startswith("Header")
    assert entries == sorted(expected_lines)
    assert paragraphs[-1].splitlines()[-len(expected_lines) :] == sorted(expected_lines)


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
