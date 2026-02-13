<!-- markdownlint-disable-file MD013 MD036 -->

# Agent Workflows & Quick Checklist

This short reference is for AI agents and automation that will be making changes in this repository. It's intentionally concise and focused on executable steps and project-specific checks — do the steps in order.

## Quick setup (reproducible)

1. Create and activate a venv (Windows):

    ```powershell
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    ```

2. Install deps and dev extras (use `uv`):

    ```powershell
    uv sync --all-extras --dev
    ```

3. Install pre-commit hooks with `prek`:

    ```powershell
    prek install
    prek run --all-files
    ```

## Run the checks (minimal agent pre-PR checklist)

- `uv run ruff check --fix .` (format & lint)
- `uv run pytest` (run tests)
- `uv run pytest --cov=./ --cov-report=term-missing` (if coverage needed)
- `prek run --all-files` (pre-commit local checks including commitlint)

Agents should fail fast and report the first failing step with logs and commands to reproduce locally.

- Agents should avoid aliasing imports to short, underscore-prefixed names (for example `from module import name as _name`). Prefer `from module import name` or `import module` and qualify names; only use `as` when necessary and document the reason.

Docstrings: Ensure that modules and exported public symbols are documented. The test suite now includes `tests/test_docstrings.py` which asserts the presence of module-level docstrings and docstrings for exported functions and classes. Run the tests locally to validate docstring compliance before opening PRs.

## CLI smoke checks (how to exercise the main flow)

- The package exposes a CLI: `python -m pyarchivist`.
- To run the Wikimedia Commons archive flow locally (example):

    ```powershell
    mkdir .\tmp_dest
    python -m pyarchivist Wikimedia_Commons -d .\tmp_dest -i .\tmp_dest\index.md "File:Example.jpg"
    ```

- The index file format is parsed using `_INDEX_FORMAT_PATTERN` in `src/pyarchivist/Wikimedia_Commons/main.py`. When testing index updates, use a temp dir and assert the final `index.md` contains sorted entries matching the formatting helper `_index_formatter`.

## Tests & important test notes

- There is a dedicated test ensuring `pyproject.toml` and `src/pyarchivist/meta.py::VERSION` match: `tests/pyarchivist/test___init__.py`. If you bump version, update both places.
- Tests use `pytest` and `pytest-asyncio` for async tests. Use `@pytest.mark.asyncio` for coroutine tests.
- Tests must define `__all__ = ()` at top-level in test modules (project rule).
- When adding new folders for Python code (source or tests), include an `__init__.py` file so the directory is an explicit Python package. Mirror the `src/` layout under `tests/` and ensure any package-style test subfolders also include `__init__.py`.

## Build & validate

- Build reproducibly: `uv build --locked` (requires `uv_build` present and pinned in `[build-system].requires`).
- Validate by installing the wheel in a fresh venv and importing the library to check `pyarchivist.meta.VERSION` (for example: ``python -c "import pyarchivist.meta as m; print(m.VERSION)"``).
- See `.github/skills/validate-builds/SKILL.md` for a full programmable checklist for build validation.

## Release steps (agent-friendly summary)

1. Bump `src/pyarchivist/meta.py::VERSION` only.
2. Run `uv sync --all-extras --dev` and commit `uv.lock` changes.
3. Commit with message equal to the raw version (e.g., `1.2.3`) and sign it with GPG (`git commit -S -m "1.2.3"`).
4. Create a signed annotated tag: `git tag -s -a v1.2.3 -m "v1.2.3"` and push commit + tag.

## When to ask a human

- If the change requires judgment about content or metadata (e.g., deciding how to represent a complex author credit).
- On ambiguous indexing rules or when an external API (Wikimedia) changes format.

---

If you'd like, I can also add small helper scripts (under `scripts/`) to run the smoke CLI tests and provide machine-readable JSON results for agent automation.
