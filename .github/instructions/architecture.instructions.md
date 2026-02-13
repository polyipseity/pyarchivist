<!-- markdownlint-disable-file MD013 MD036 -->

# Architecture & Repository Layout

This document describes the overall layout and important invariants for the
`pyarchivist` submodule. Keep it brief and authoritative — other docs may
reference these rules.

Repository layout (top-level view):

- `src/pyarchivist/` — package sources.
- `pyproject.toml` — canonical dependency and build metadata.
- `.github/` — workflows, instructions, and agent skills.
- `.pre-commit-config.yaml` — pre-commit hooks for local checks.
- `tests/` — unit tests using `pytest`.
- `archives/` (optional) — storage of archived content and `index.md` management.

Important invariants:

- `pyproject.toml` is the canonical source of dependency metadata and build
  configuration. Do not add `requirements.txt` as the primary source of truth.
- Prefer using the `uv_build` backend for pure-Python packages. Configure `[build-system].requires` to include `uv_build` with an upper bound (for example: `uv_build>=0.10.0,<0.11.0`) and use `uv build` for packaging.
- Follow the `src/` layout so source files are importable only when installed or
  in a test environment.
- When adding new package-style directories (source or tests), include an `__init__.py` file so the folder is an explicit Python package; update the mirrored `tests/` tree accordingly.
- Tests mirror the module layout; one test file per module is preferred.
- Use `uv` (astral-sh) for Python dependency management and `uv.lock` for
  reproducible installs.

If you add new top-level folders, update this document and the AGENTS.md
references to keep discoverability consistent.
