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
- After changing `prek.toml` or on first setup, run `uv run prek install` to ensure hooks (including non-Python hooks like `commitlint`) are installed and available locally.

Script & CI conventions:

- Prefer `uv run` for invoking tools when a `pnpm` wrapper is not used.
- CI workflows should install dependencies deterministically (use `uv sync --locked` in CI).
- Ensure tests and ruff checks run on PRs; `AGENTS.md` lists the CI expectations.

Commit conventions:

- Use Conventional Commits (type(scope): description).
- Commit messages are linted with `commitlint` (Conventional Commits rules). Locally this runs via a `prek` hook (`commit-msg` stage); CI also runs commitlint via `wagoid/commitlint-github-action`.
- The repository commitlint configuration is authored as an ES module in `commitlint.config.mjs` (preferred). If you previously used a CommonJS config (`commitlint.config.cjs`), consider removing it to avoid ambiguity.
- Developers should have **Node.js (LTS)** installed to run the local commitlint hook. Install from `https://nodejs.org/` if not present.
- When modifying production code, add or update tests to cover behaviour changes.

Agent & automation rules:

- Agents must run the same format & check steps locally (using `uv` wrappers)
  before making commits or opening PRs. This includes running pre-commit-style hooks (via `prek`) and the test suite.
- Agents must ask clarifying questions if intent is ambiguous rather than
  guessing when correctness matters.
