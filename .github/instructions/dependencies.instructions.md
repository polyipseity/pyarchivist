<!-- markdownlint-disable-file MD013 MD036 -->

# Dependencies & Environment

This document explains how dependencies are managed and how to create a
reproducible environment.

Dependency management:

- `pyproject.toml` is the canonical dependency file for Python packages and
  development extras. Use PEP 722 dependency groups for dev extras where
  possible.
- Use `uv` (astral-sh) for deterministic installs and `uv.lock` for reproducible
  install snapshots.
- For packaging, prefer the `uv_build` PEP 517 build backend for pure-Python projects. Add `uv_build` to `pyproject.toml` under `[build-system].requires`, and include an upper bound (for example: `uv_build>=0.10.0,<0.11.0`) to ensure compatibility with `uv`.

Creating an environment:

1. Create a virtual environment and activate it:

    ```powershell
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    ```

2. Install dependencies:

    ```powershell
    uv sync --all-extras --dev
    ```

Notes for CI:

- CI should run `uv sync --locked --all-extras --dev` to install development extras
  deterministically.
- Pin long-lived tooling (for example: `ruff`, `pytest`, `pre-commit`) in the
  `[dependency-groups].dev` section to ensure reproducible behaviour.

When adding a new dependency:

- Add the package to `pyproject.toml` under the appropriate section and run
  `uv sync` to update `uv.lock` and commit the lockfile.
