---
name: Python entry points
description: Convention for writing Python scripts and modules with __name__ == "__main__" entry points
applyTo: "**/*.py"
---

# Python Entry Points Convention (pyarchivist)

This document establishes the convention for Python scripts and modules in the pyarchivist project that expose entry points for direct execution. All `__main__.py` modules must follow this pattern.

**Inheritance note:** This project largely follows the parent repository's Python entry points convention (see `../../../../.agents/instructions/python-entry-points.instructions.md`). Refer to that document for comprehensive guidance. This file provides pyarchivist-specific context and highlights key patterns used in the project.

## Standard Pattern (Async)

```python
"""Module purpose and usage."""

import sys
from asyncer import runnify


async def main(argv: list[str] | None = None) -> None:
    """Main async entry point.

    Args:
        argv: Command-line arguments; defaults to sys.argv[1:] if None.
    """
    if argv is None:
        argv = sys.argv[1:]

    # Application logic here
    pass


def __main__() -> None:
    """Entry point for running the module directly."""
    runnify(main, backend_options={"use_uvloop": True})()


if __name__ == "__main__":
    __main__()
```

## Standard Pattern (Sync)

```python
"""Module purpose and usage."""

import sys


def main(argv: list[str] | None = None) -> None:
    """Main sync entry point.

    Args:
        argv: Command-line arguments; defaults to sys.argv[1:] if None.
    """
    if argv is None:
        argv = sys.argv[1:]

    # Application logic here
    pass


def __main__() -> None:
    """Entry point for running the module directly."""
    main()


if __name__ == "__main__":
    __main__()
```

## Pyarchivist-Specific Rules

1. **Module structure**: The pyarchivist package uses `__main__.py` files for archive operations (e.g., `src/pyarchivist/__main__.py`, `src/pyarchivist/Wikimedia_Commons/__main__.py`). Each module follows the same entry-point pattern.

2. **Argument handling**: Pyarchivist commands parse arguments via argparse inside `main()`. All entry points accept optional `argv` for testing compatibility.

3. **Error handling**: Use consistent exit codes:
   - `0`: Success
   - `1`: General/processing error
   - `2`: Argument parsing error
   - `3`: File/IO error (network timeout, permission denied, etc.)

4. **Type hints**: Include complete type hints on `main()` and `__main__()` functions. Use `collections.abc.Sequence[str]` for argument lists.

5. **Docstrings**: Include module-level and function docstrings explaining purpose, usage, and key operations. Example:

   ```python
   """Archive and download Wikimedia Commons media files.

   Usage:
       python -m pyarchivist.Wikimedia_Commons --help

   Fetches media metadata, downloads files, and organizes into
   archive directory structure with index metadata.
   """
   ```

6. **Async operations**: Pyarchivist typically performs network I/O (downloading files). Use `asyncify` for blocking operations and keep network logic inside `main()`:

   ```python
   from asyncer import asyncify

   async def main(argv: ...):
       # Network operations here
       files = await asyncify(download_media)(urls)
   ```

7. **Testing**: Import `main` directly in tests; do not trigger the entry-point guard:

   ```python
   @pytest.mark.anyio
   async def test_main_archives_metadata():
       from pyarchivist.Wikimedia_Commons.__main__ import main
       await main(["--help"])  # or provide arguments
   ```

## Pyarchivist Entry Points Examples

### Main Module (**main**.py)

```python
"""Pyarchivist: archive online content and media.

Usage:
    python -m pyarchivist [--help]
    python -m pyarchivist COMMAND [args...]

Main commands: Wikimedia_Commons (archive Wikimedia media).
"""

import sys
from asyncer import runnify


async def main(argv: list[str] | None = None) -> None:
    """Main entry point for pyarchivist package.

    Dispatches to archive-specific subcommands.

    Args:
        argv: Command-line arguments.
    """
    if argv is None:
        argv = sys.argv[1:]

    # Dispatcher logic: delegate to subcommands
    # (implementation details omitted)
    pass


def __main__() -> None:
    """Entry point for running the module directly."""
    runnify(main, backend_options={"use_uvloop": True})()


if __name__ == "__main__":
    __main__()
```

### Archive Subcommand (Wikimedia_Commons/**main**.py)

```python
"""Archive and download Wikimedia Commons media files.

Usage:
    python -m pyarchivist.Wikimedia_Commons [URLs or query]

Downloads media metadata and files from Wikimedia Commons,
organizes into archive directory structure, and creates index.
"""

import sys
from asyncer import runnify, asyncify
from httpx import AsyncClient
import argparse

__all__ = ("main",)


async def fetch_media_metadata(
    client: AsyncClient, file_titles: list[str]
) -> dict:
    """Fetch Wikimedia Commons metadata asynchronously."""
    # Implementation uses async client
    pass


async def main(argv: list[str] | None = None) -> None:
    """Main async entry point for Wikimedia Commons archiving.

    Args:
        argv: Query terms or file titles to archive.
    """
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        description="Archive Wikimedia Commons media"
    )
    parser.add_argument("query", nargs="*", help="Media titles or search query")
    parser.add_argument("--limit", type=int, default=100, help="Max files to download")
    parser.add_argument("--output-dir", required=True, help="Archive output directory")
    args = parser.parse_args(argv)

    try:
        async with AsyncClient() as client:
            metadata = await fetch_media_metadata(client, args.query)
            # Download and organize files...
            return exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return exit(1)


def __main__() -> None:
    """Entry point for running the module directly."""
    runnify(main, backend_options={"use_uvloop": True})()


if __name__ == "__main__":
    __main__()
```

## Implementation Checklist

When creating or updating a pyarchivist `__main__.py`:

- [ ] Define `main()` as the primary logic (async or sync)
- [ ] Accept optional `argv: Sequence[str] | None = None` in `main()`
- [ ] Define `__main__()` sync wrapper (with `runnify` for async)
- [ ] Place `if __name__ == "__main__":` guard at end
- [ ] Include return type hints (`-> None` is typical)
- [ ] Add module-level docstring with usage example
- [ ] Add docstrings to `main()` and `__main__()`
- [ ] Use appropriate exit codes (0, 1, 2, 3)
- [ ] For network operations, use `AsyncClient` (httpx) inside `main()`
- [ ] Test by importing `main()` directly in pytest with `@pytest.mark.anyio`
- [ ] Run `ty check`, `ruff check`, and `pytest` before committing

## Integration with Parent Convention

For comprehensive guidance on entry points, async patterns, and error handling, see the parent repository's convention:

**File:** `../../../../.agents/instructions/python-entry-points.instructions.md`

**Key sections:**

- Detailed rationale and background
- Integration with argparse
- Comprehensive testing patterns
- Error handling best practices
- Asyncer helper functions reference

## Related Documentation

- `developer-workflows.instructions.md` — Testing and local development
- `testing.instructions.md` — Test structure and pytest patterns
- `formatting.instructions.md` — Code style and linting
- `archive-format.instructions.md` — Archive structure and metadata
- Parent AGENTS.md async guidance — Core async/concurrency patterns
