<!-- markdownlint-disable-file MD013 MD036 -->

# pyarchivist AGENTS

Treat this folder as the project root. This document describes repository conventions, developer workflow, and release steps for the pyarchivist submodule.

## Purpose

pyarchivist archives online content into the `archives/` tree and maintains index metadata. This AGENTS.md is intended for maintainers and contributors working inside this submodule.

## Repository layout (top-level view)

- `src/pyarchivist/meta.py` — package version and package metadata (update this when releasing).
- `pyproject.toml` (canonical) — use `[dependency-groups].dev` for development extras; `requirements.txt` is deprecated in favor of `pyproject.toml`.
- `tools/` or `scripts/` — helper scripts (if present).
- `archives/` — archive storage and `index.md` management (if included in the submodule).
- `tests/` — unit tests (pytest by default, if present).

Adjust the list above to match this submodule; paths below assume this folder is the repo root.

## Dependencies

- Declare project dependencies in `pyproject.toml` (this is the authoritative source).
- Use `uv` (astral-sh) for dependency management and prefer `uv sync --all-extras --dev` (use `--locked --all-extras --dev` in CI to enforce the lockfile) over using `pip install` directly.
- If `requirements.txt` exists in this repository it is a compatibility/delegation helper and should not be treated as the authoritative dependency list — it delegates to `setup.py`/packaging and does not itself store the canonical dependencies.

## Quick start (development)

1. Create and activate a Python virtual environment (Windows example):

    ```powershell
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    ```

2. Install development dependencies (recommended):

    ```powershell
    # Using PEP 722 dependency groups (preferred)
    # Add dev extras to `pyproject.toml` (under [dependency-groups].dev), then install:
    uv sync --all-extras --dev

    # or, if using older tooling, install the editable package with extras
    # (not recommended; prefer `uv sync --all-extras --dev`)
    ```

3. Run tests (if tests exist):

    ```powershell
    # Add pytest to dev extras or install via uv, then run:
    uv run pytest
    ```

## Formatting & linting

- Recommended tools: `ruff`, `flake8`, `mypy` (apply if configuration files are present). For Markdown, use `rumdl` (fast Rust-based linter & formatter).
- To run formatters locally:

    ```powershell
    # Ensure ruff and rumdl are in dev extras and run via uv for reproducibility
    uv run ruff check --fix
    uv run ruff format

    # Markdown lint & format with rumdl
    uv run --locked rumdl check
    uv run --locked rumdl check --fix
    uv run --locked rumdl fmt
    ```

## Agent workflow reminders

- **Read relevant skill and instruction files before use.** When performing tasks related to archiving, read the relevant `SKILL.md` or `.instructions.md` files under `.github/` first.
- **Ask instead of guessing.** If behaviour or intent is ambiguous, request clarification rather than making assumptions.
- **Use the Todo List Tool for multi-step tasks.** Plan steps, mark one step `in-progress`, complete it, and continue; keep the todo list updated.
- **Document everything.** Ensure modules and exported public symbols include clear module-level and object docstrings. Run `uv run pytest tests/test_docstrings.py` as part of your checks to validate docstring compliance.

## Project-specific notes for agents ⚡

- Quick CLI example (exercise Wikimedia_Commons flow):

    ```powershell
    # create a temporary dest and index, then run a sample
    python -m pyarchivist Wikimedia_Commons -d .\tmp_dest -i .\tmp_index.md "File:Example.jpg"
    ```

- Index format: entries are Markdown lines of the shape `- [<filename>](<url-escaped-filename>): <credit>` — the repository uses `_INDEX_FORMAT_PATTERN` in `src/pyarchivist/Wikimedia_Commons/main.py` to parse and update index files.

- Concurrency & batching: queries are batched by `_QUERY_LIMIT = 50` and the HTTP client uses `_MAX_CONCURRENT_REQUESTS_PER_HOST = 1` (see `Wikimedia_Commons/main.py`) — prefer small, deterministic runs when testing.

- Error handling: failures surface via `ExitCode` flags (e.g., `ExitCode.QUERY_ERROR`) and partial errors are handled by `_handle_partial_errors` (which may raise `ExceptionGroup` / `BaseExceptionGroup`). When writing agent tests, assert expected exit codes and logged exceptions where applicable.

- Version & release single source-of-truth: bump `src/pyarchivist/meta.py::VERSION` and keep `pyproject.toml` in sync (there is a test `tests/pyarchivist/test___init__.py` that asserts this). Release commits must be GPG-signed and tag with `vX.Y.Z` as described below.

- Tests & formatting: use `uv` wrappers for reproducible runs: `uv sync --all-extras --dev`, `uv run pytest`, `uv run ruff check --fix .`, and `prek run --all-files` for pre-commit hooks.

- Files to read first (in order): `pyproject.toml`, `src/pyarchivist/meta.py`, `src/pyarchivist/Wikimedia_Commons/main.py`, `.github/instructions/*`, `tests/`.

## Agent Code Conventions

- Prefer `anyio.Path` for file/script identifiers and async filesystem operations. APIs that accept file/script identifiers must accept `os.PathLike` or `anyio.Path` (for example, call sites may pass `Path(__file__)` where `Path` is `anyio.Path`). When a string path is required use `os.fspath(path_like)` rather than `str(path_like)`.
- Use timezone-aware UTC datetimes: prefer `datetime.now(timezone.utc)` rather than `datetime.utcnow()` and keep ISO timestamps timezone-aware.
- Imports must be at module top-level (no inline/runtime imports). This is enforced by Ruff's `import-outside-top-level` rule (PLC0415).
- Avoid aliasing imports to short, underscore-prefixed names (for example `from module import name as _name`). This pattern reduces readability and is discouraged. Prefer importing the symbol by its natural name (`from module import name`) or importing the module and using qualified access (`import module; module.name`). Only use `as` when necessary to avoid a conflict or when there is a clear, documented reason.
- Docstrings & type annotations: Modules, classes, functions, and tests SHOULD include clear module-level docstrings and type annotations for public APIs and test functions. Prefer PEP 585 / PEP 604 style hints and `collections.abc` where applicable. Avoid using `from __future__ import annotations` in new code or tests; prefer native annotations (PEP 585/PEP 604) and, when needed to prevent runtime import cycles you can use `typing.TYPE_CHECKING` and string-literal annotations only in narrowly justified cases.
- Prefer `Ruff` as the single Python formatting/linting tool; do not add `black` or `isort` to CI or dev-dependencies.

## Pre-commit-style hooks (prek)

Use `prek` to install hooks locally. `prek` can read an existing `.pre-commit-config.yaml`, but we recommend adding a native `prek.toml` (see below):

```powershell
# Add `prek` to dev extras, then:
uv sync --all-extras --dev
prek install

# Run all configured hooks against the repository:
prek run --all-files
```

## Branching & pull request workflow

- Work on feature branches named `feat/description` or `fix/short-description`.
- Use Conventional Commits for commit messages (type(scope): description).
- Ensure tests and linters pass before opening a PR. Include a concise summary and list of changes in the PR description.

## Release checklist (semantic versioning)

When publishing a new release, follow these steps and keep the release commit minimal:

1. Update the version string in `src/pyarchivist/meta.py::VERSION` to the new semantic version (e.g. `1.2.3`). After changing the version (and before tagging), run `uv sync --all-extras --dev` to update `uv.lock` and commit the lockfile (either as part of the release commit or as an immediate follow-up commit). Edit only the version and lockfile in the release commit(s).

2. Commit the change with the commit message equal to the bare version string (no prefix). The commit must be GPG-signed.

    ```powershell
    git add pyproject.toml uv.lock src/pyarchivist/meta.py
    git commit -S -m "1.2.3"
    ```

3. Create a signed, annotated tag with the `v` prefix matching the version:

    ```powershell
    git tag -s -a v1.2.3 -m "v1.2.3"
    ```

4. Push the commit and tags to the remote:

    ```powershell
    git push origin HEAD
    git push origin --tags
    ```

Notes:

- Keep the release commit atomic (only version bump). Use separate Conventional Commit changes for other work.
- The tag must be signed to support reproducible release verification.

## Changelog and release notes

- Maintain a `CHANGELOG.md` or use an automated changelog generator based on Conventional Commits.
- If you add release notes, do so in a separate commit (e.g., `chore(release): add release notes for 1.2.3`).

## CI expectations

- CI should run tests, linters, and formatting checks on PRs. If a CI workflow file exists, follow its requirements.

## Packaging & publishing (optional)

- To build artifacts locally:

    ```powershell
    # Use uv's native build backend (uv_build) for pure-Python packages
    # Ensure pyproject.toml [build-system].requires = ["uv_build>=0.10.0,<0.11.0"]
    uv build --locked
    ```

- To publish to PyPI, use `twine` and keep credentials out of the repo (use CI secrets):

    ```powershell
    # Build artifacts with `uv build --locked` then upload with twine via uv
    uv build --locked
    uv run --locked twine upload dist/*
    ```

## Security and reporting

- Report security issues privately to the maintainers. If there's a `SECURITY.md`, follow its instructions.

## Contributor guidelines

- Follow the Conventional Commits convention, add tests for new behavior, and include short documentation/examples.

## GPG and signed commits/tags

- This project requires signed release commits and annotated tags. To sign commits and tags, configure your GPG key and set `user.signingkey` in git config.

    Example commit verification:

    ```powershell
    git verify-commit HEAD
    git verify-tag v1.2.3
    ```

## Using this submodule from the parent repo

- When you update the submodule in the parent repository, update the submodule pointer and commit in the parent repo:

    ```powershell
    git submodule update --remote --merge
    git add .
    git commit -m "chore(submodules): update pyarchivist to v1.2.3"
    ```

## Badges & metadata

- Optionally add CI, PyPI, and coverage badges to the top of `README.md` for quick status visibility.

---

## Documentation Structure 🔎

Core instructions (add under `.github/instructions/`):

- `architecture.instructions.md` — Overall repository & archive layout and important invariants.
- `archive-format.instructions.md` — Expected layout, naming, and metadata for archives and `index.md` files.
- `developer-workflows.instructions.md` — Local development tooling, running tests, formatting, and release steps.
- `common-workflows.instructions.md` — Common developer tasks and checklist (`prek` hooks, pre-push, working with archives).
- `editing-guidelines.instructions.md` — Formatting, markdown and metadata conventions, and recommended editors.
- `security.instructions.md` — Handling secrets, encryption, and private metadata (GPG usage, private.yaml.gpg conventions).
- `dependencies.instructions.md` — How to install platform dependencies (Python, uv) and manage `uv.lock`.
- `git-commits.instructions.md` — Conventional commit headers, wrapping rules, and agent commit conventions.

If you add additional instruction files, reference them here and add brief summaries.

Additional canonical instruction files in this repository (see `.github/instructions/`):

- `formatting.instructions.md` — Ruff configuration, `prek` integration, and editor guidance.
- `testing.instructions.md` — Test structure, async testing rules, running pytest locally, and CI expectations.
- `release.instructions.md` — Release checklist, GPG-signed version commit, tagging, and CI publishing guidance.

Link these documents from `AGENTS.md` when you add or update them so agents and maintainers can find authoritative workflows quickly.

## Agent Skills (samples)

Add skill folders under `.github/skills/` (each skill gets a `SKILL.md`):

- `add-archive/` — Add or update an archive and update indexes.
- `validate-archives/` — Run validation and consistency checks across the `archives/` tree.
- `prune-archives/` — Prune, compress, or migrate archives following repository policy.
- `update-index/` — Update `index.md` files and metadata after archive changes.
- `edit-instructions/` — Update instruction files and document reasoning for non-trivial changes.

Each `SKILL.md` should include: purpose, inputs, outputs, preconditions, and step-by-step instructions including checks to run locally.

## Module exports & tests ✅

- All modules intended to export a public surface MUST define an explicit `__all__` **tuple** at the top of the module (immediately after the module docstring and imports). Use a tuple (`('name',)`) — do not use a list for `__all__`.

- Placement and style rules:
  - Put `__all__` directly after imports and any module docstring; keep the declaration visible and near the top of the file so reviewers can quickly see the module's public surface.
  - Use string names that match the exact symbol names defined in the module (e.g. `__all__ = ('ExitCode', 'Args', 'main', 'parser')`).
  - Do not include private names (leading underscore) in `__all__`.
  - Test modules must set `__all__ = ()` — test modules should not export public symbols.

- When to export:
  - Export only the symbols that are intended to be part of the module's public API. Internal helpers should remain underscore-prefixed and omitted from `__all__`.
  - For packages (`__init__.py`), avoid re-exporting module internals. Prefer placing package metadata and configuration in dedicated modules (for example `pyarchivist.meta`) and import them directly using `from pyarchivist.meta import VERSION`. If the package intentionally has no public surface, use `__all__ = ()`.
  - Add a module-level test that enforces `__all__` presence and that it is a tuple. The repository contains a test that parses source files' AST and asserts `__all__` is declared.
  - When you add public symbols, update `__all__`, add tests for the new API, and update the package docs and `README.md` as appropriate.

- Examples:

```python
"""Module docstring."""

from typing import Any

__all__ = ("public_function", "PUBLIC_CONSTANT")

PUBLIC_CONSTANT = 1

def public_function() -> None:
    ...

# Internal helper (not exported)
def _internal() -> None:
    ...
```

- Rationale: explicitly declaring `__all__` improves static analysis, makes the public surface self-documenting, and prevents accidental exports. Keep the `__all__` tuple updated as the public API evolves.

## Formatting & Tooling (Ruff + UV) 🔧

- We use **Ruff** as the single Python formatting/linting tool. Do not add `black` or `isort` to CI or dev-dependencies.
- Use `uv` for Python dependency management and installs. Prefer deterministic installs with `uv sync --all-extras --dev` and use `--locked --all-extras --dev` in CI or when you need to strictly enforce the lockfile; commit `uv.lock` if present.
- Local formatting commands:

    ```powershell
    uv run ruff check --fix
    uv run ruff format
    ```

- Use `prek` to register quick hooks (see `.pre-commit-config.yaml` or `prek.toml`). Install via:

    ```powershell
    uv sync --all-extras --dev
    prek install
    prek run --all-files
    ```

## Agent commits & release policy 🧾

- Use **Conventional Commits** for all changes: `type(scope): short description`.
- Tooling enforces a **hard maximum of 100 characters** for both the commit subject/header and body lines, but the repository prefers a **soft limit of 72 characters** for readability. The `commitlint` configuration will **warn** when lines exceed 72 characters (soft limit) and will **fail** when lines exceed 100 characters (hard limit); aim to keep subject ≤72 and wrap body lines at 72 where possible.
- When changing production code add or update tests. Include short rationale in the commit body for non-trivial design decisions.
- Release workflow (semantic versioning):
  - Update version in `src/pyarchivist/meta.py` only and commit with message equal to the version (GPG-signed).
  - Create a signed annotated tag `vX.Y.Z` (GPG) and push commit and tag.

## Quick start (development) ⚡

1. Create & activate a venv (Windows example):

    ```powershell
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    ```

2. Install development extras (use `uv`):

    ```powershell
    uv sync --all-extras --dev
    ```

3. Run format & checks before committing:

    ```powershell
    uv run ruff check --fix .
    prek run --all-files
    uv run pytest
    ```

## VS Code setup 🧭

- Recommend enabling `chat.useAgentsMdFile` in workspace settings to help agent workflows.
- Use `.editorconfig` and `markdownlint.jsonc` for consistent Markdown formatting. Format docs via the CLI when needed.

## Todo List Tool Reminder ✅

- Plan multi-step or complex tasks with the Todo List Tool: mark one step `in-progress`, complete it, and mark it done before moving on.

---

## Troubleshooting

- Missing GPG key: ensure your key is available to Git and that `gpg` is in PATH.
- Failed tests: run `pytest` locally; ensure dependencies are installed in the venv.

## Maintainers

- List of maintainers or contact details (add e-mail or GitHub handles here).

- Missing GPG key: ensure your key is available to Git and that `gpg` is in PATH.
- Failed tests: run `pytest` locally; ensure dependencies are installed in the venv.
