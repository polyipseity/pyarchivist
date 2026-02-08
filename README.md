# pyarchivist

Archive things from the Internet.

## Quick start ✅

Follow these steps to set up a reproducible development environment using `uv` (preferred over `pip`):

1. Create and activate a virtual environment (Windows example):

    ```powershell
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    ```

2. Install project dependencies and development extras:

    ```powershell
    uv sync --dev
    ```

3. Run tests and formatting (use `uv` wrappers for reproducibility):

    ```powershell
    uv run pytest -q
    uv run ruff check --fix .
    ```

Notes:

- Prefer `uv` for deterministic installs and `uv.lock` for reproducible environments.
- `requirements.txt` is deprecated in favor of `pyproject.toml` and dependency groups.
