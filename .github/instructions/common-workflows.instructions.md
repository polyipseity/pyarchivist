# Common Workflows & Local Hook Usage

This document provides step-by-step guidance for common local workflows:

Pre-commit-style hooks (local, using `prek`):

- Install `prek` into the dev extras (ensure it's in `pyproject.toml` dev group),
  then run:

    ```powershell
    uv sync --dev
    prek install
    prek run --all-files
    ```

- If a hook auto-fixes files, re-run `prek run --all-files` to verify no
  further changes are required.

Formatting & linting:

- Use Ruff as the single formatting/linting tool. Format via:

    ```powershell
    uv run ruff check --fix .
    uv run ruff format .
    ```

Testing:

- Run tests locally with `pytest` via `uv`:

    ```powershell
    uv run pytest -q
    ```

- When adding new behavior, add tests that reflect the intended usage. Keep
  tests small and focused; one test file per module is preferred.

Push & PR checks:

- Ensure pre-commit and tests pass locally before creating a PR. CI will
  re-run these checks and block merge on failures.
- Use a descriptive PR title and summary with bullet points for key changes.

Husky / Git hooks note:

- If repository uses Husky or other Git hook manager, run the package install
  script to register hooks (for Node-enabled repositories). For this Python
  focused project, `pre-commit` is the canonical local hook manager.