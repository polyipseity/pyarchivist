<!-- markdownlint-disable-file MD013 MD036 -->

# Editing & Formatting Guidelines

This document provides guidance for editing source and documentation files
in a consistent and review-friendly manner.

General rules:

- Use `UTF-8` encoding and preserve newline at end-of-file.
- Keep paragraphs short and prefer wrapping commit body lines at **72 characters** for readability. The `commitlint` configuration will **warn** when lines exceed **72** (soft limit) and will **fail** when lines exceed **100** (hard limit). Aim to keep lines ≤72 for best readability.
- Use `README.md` and `AGENTS.md` for high-level project guidance.

Markdown:

- Use consistent heading levels, and add short summaries at the top of docs.
- Prefer fenced code blocks and explicit language markers.
- Use `.markdownlint.jsonc` if present for compatibility, but prefer `rumdl` for Markdown linting and formatting. Add `rumdl` to `[dependency-groups].dev` in `pyproject.toml` and run `uv sync --all-extras --dev` to install it into the project `.venv`; then use `uv run --locked rumdl check`, `uv run --locked rumdl check --fix`, or `uv run --locked rumdl fmt`.

Python style & typing:

- Prefer PEP 585/PEP 604 styles in annotations (e.g., `list[int]`, `str | None`).
- Avoid `from __future__ import annotations`; prefer native annotations and use `typing.TYPE_CHECKING` when you need to import types for type-checking only.
- Add module-level docstrings and type annotations for public APIs. Public modules, classes and functions should include clear, concise docstrings describing purpose, parameters and return values where applicable. Prefer Google-style docstrings (short summary line, blank line, optional extended description and sections for Args, Returns, Raises) for consistency across the repository.
- Avoid aliasing imports to short, underscore-prefixed names (for example `from module import name as _name`). This reduces readability and makes diffs noisy; prefer `from module import name` or `import module` with qualified access. Use `as` only to avoid collisions or when a clear, documented reason exists.
- Add `__all__` tuples to modules that export a public surface. Test modules
  should set `__all__ = ()`.

  Guidance:
  - Use a **tuple** for `__all__`, not a list (e.g. `__all__ = ("name",)`).
  - Place `__all__` immediately after the imports and module docstring for visibility.
  - Export **only** intended public symbols and avoid adding underscore-prefixed names to `__all__`.
  - When adding public API, update `__all__`, add or update tests, and document the change in the package docs.

Tests:

- Name tests `test_*.py` and keep them alongside the module under `tests/`.
- When testing async code, use `async def` tests with `@pytest.mark.asyncio`.

Commits & PRs:

- Small, focused commits are easier to review. Use Conventional Commits.
- For agent-generated changes, include the rationale in the commit body when
  deviating from conventions or making non-obvious changes.
