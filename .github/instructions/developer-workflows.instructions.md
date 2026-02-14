# Developer Workflows

This document describes common development workflows for contributors and
automation (agents) working inside the `pyarchivist` submodule.

Local development quick start:

1. Create and activate a virtual environment (Windows example):

    ```powershell
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    ```

2. Install development extras (use `uv`):

    ```powershell
    uv sync --all-extras --dev
    ```

3. Run formatting, linters and tests before committing:

    ```powershell
    uv run ruff check --fix .
    prek run --all-files
    uv run pytest
    ```

- Agents and contributors should prefer `prek` for pre-commit-style hooks (it can read `.pre-commit-config.yaml` or use `prek.toml`).
- After changing `prek.toml` or on first setup, run `uv run prek install` to ensure hooks (including non-Python hooks like `commitlint`) are installed and available locally.

Script & CI conventions:

- Prefer `uv run` for invoking tools when a `pnpm` wrapper is not used.
- CI workflows should install dependencies deterministically (use `uv sync --locked` in CI).
- Prefer the `uv_build` PEP 517 build backend for pure-Python projects; run packaging with `uv build --locked`. Add `uv_build` to `[build-system].requires` and pin it with an upper bound (for example: `uv_build>=0.10.0,<0.11.0`).
- Ensure tests and ruff checks run on PRs; `AGENTS.md` lists the CI expectations.

- Agents: see `.github/instructions/agent-workflows.instructions.md` for a concise, runnable pre-PR checklist and smoke-test examples.
- Quick CLI smoke test (use a temp dir):

    ```powershell
    mkdir .\tmp_dest
    python -m pyarchivist Wikimedia_Commons -d .\tmp_dest -i .\tmp_dest\index.md "File:Example.jpg"
    ```

- Version bumps: ensure both `src/pyarchivist/meta.py` and `pyproject.toml` match. The project has a unit test `tests/pyarchivist/test___init__.py` that asserts the two versions are equal; run `uv run pytest tests/pyarchivist/test___init__.py::test_pyproject_and_init_version_match` as a quick check.

Commit conventions:

- Use Conventional Commits (type(scope): description).
- The repository prefers a **soft limit of 72 characters** for the commit subject/header; the `commitlint` configuration will **warn** when subjects exceed 72. Tooling enforces a **hard limit of 100 characters** (commits will fail if subject or body lines exceed 100).
- Commit messages are linted with `commitlint` (Conventional Commits rules). Locally this runs via a `prek` hook (`commit-msg` stage); CI also runs commitlint via `wagoid/commitlint-github-action`.
- The repository commitlint configuration is authored as an ES module in `commitlint.config.mjs` (preferred). If you previously used a CommonJS config (`commitlint.config.cjs`), consider removing it to avoid ambiguity.
- Developers should have **Node.js (LTS)** installed to run the local commitlint hook. Install from `https://nodejs.org/` if not present.
- When modifying production code, add or update tests to cover behaviour changes.

Agent & automation rules:

- Agents must run the same format & check steps locally (using `uv` wrappers)
  before making commits or opening PRs. This includes running pre-commit-style hooks (via `prek`) and the test suite.
- When creating new folders for Python source or tests, include an `__init__.py` file so the directory is an explicit package; ensure mirrored test folders under `tests/` also contain `__init__.py`.
- Agents must not alias imports to short, underscore-prefixed names (for example `from module import name as _name`). Use direct imports (`from module import name`) or qualified module imports and avoid introducing underscore-prefixed import aliases.
- Prefer pydantic v2 model configuration using `ConfigDict`. When adding or updating `BaseModel` classes use `model_config = ConfigDict(...)` (import `ConfigDict` from `pydantic`) instead of legacy inner `Config` classes or raw dicts; update tests if model behaviour (for example immutability) is affected.
- Agents must ask clarifying questions if intent is ambiguous rather than
  guessing when correctness matters.
