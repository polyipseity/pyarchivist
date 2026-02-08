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
    uv sync --dev
    ```

3. Run formatting, linters and tests before committing:

    ```powershell
    uv run ruff check --fix .
    prek run --all-files
    uv run pytest -q
    ```

- Agents and contributors should prefer `prek` for pre-commit-style hooks (it can read `.pre-commit-config.yaml` or use `prek.toml`).

Script & CI conventions:

- Prefer `uv run` for invoking tools when a `pnpm` wrapper is not used.
- CI workflows should install dependencies deterministically (use `uv sync --locked` in CI).
- Ensure tests and ruff checks run on PRs; `AGENTS.md` lists the CI expectations.

Commit conventions:

- Use Conventional Commits (type(scope): description).
- When modifying production code, add or update tests to cover behaviour changes.

Agent & automation rules:

- Agents must run the same format & check steps locally (using `uv` wrappers)
  before making commits or opening PRs. This includes running pre-commit-style hooks (via `prek`) and the test suite.
- Agents must ask clarifying questions if intent is ambiguous rather than
  guessing when correctness matters.