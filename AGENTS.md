# pyarchivist AGENTS

Treat this folder as the project root. This document describes repository conventions, developer workflow, and release steps for the pyarchivist submodule.

## Purpose

pyarchivist archives online content into the `archives/` tree and maintains index metadata. This AGENTS.md is intended for maintainers and contributors working inside this submodule.

## Repository layout (top-level view)

- `__init__.py` — package version and package metadata (update this when releasing).
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
    uv run pytest -q
    ```

## Formatting & linting

- Recommended tools: `ruff`, `flake8`, `mypy` (apply if configuration files are present).
- To run formatters locally:

    ```powershell
    # Ensure ruff is in dev extras and run via uv for reproducibility
    uv run ruff check --fix .
    uv run ruff format .
    ```

## Agent workflow reminders

- **Read relevant skill and instruction files before use.** When performing tasks related to archiving, read the relevant `SKILL.md` or `.instructions.md` files under `.github/` first.
- **Ask instead of guessing.** If behaviour or intent is ambiguous, request clarification rather than making assumptions.
- **Use the Todo List Tool for multi-step tasks.** Plan steps, mark one step `in-progress`, complete it, and continue; keep the todo list updated.

## Agent Code Conventions

- Use `os.PathLike` for file/script identifiers: APIs that accept file/script identifiers must accept `os.PathLike` (for example, `pathlib.Path`) and call sites should pass `Path(__file__)` or another `os.PathLike` instance. When a string path is required use `os.fspath(path_like)` rather than `str(path_like)`.
- Use timezone-aware UTC datetimes: prefer `datetime.now(timezone.utc)` rather than `datetime.utcnow()` and keep ISO timestamps timezone-aware.
- Imports must be at module top-level (no inline/runtime imports). This is enforced by Ruff's `import-outside-top-level` rule (PLC0415).
- Docstrings & type annotations: Modules, classes, functions, and tests SHOULD include clear module-level docstrings and type annotations for public APIs and test functions. Prefer PEP 585 / PEP 604 style hints and `collections.abc` where applicable.
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

1. Update the version string in `__init__.py` to the new semantic version (e.g. `1.2.3`). After changing the version (and before tagging), run `uv sync --all-extras --dev` to update `uv.lock` and commit the lockfile (either as part of the release commit or as an immediate follow-up commit). Edit only the version and lockfile in the release commit(s).

2. Commit the change with the commit message equal to the bare version string (no prefix). The commit must be GPG-signed.

    ```powershell
    git add pyproject.toml uv.lock src/pyarchivist/__init__.py
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

- All modules intended to export a public surface MUST define an explicit `__all__` tuple at the top of the module (immediately after docstring and imports).
- Test modules should set `__all__ = ()` (tests should not export public symbols).
- For new functionality add tests mirroring the source tree under `tests/` (one test file per source module preferred).

## Formatting & Tooling (Ruff + UV) 🔧

- We use **Ruff** as the single Python formatting/linting tool. Do not add `black` or `isort` to CI or dev-dependencies.
- Use `uv` for Python dependency management and installs. Prefer deterministic installs with `uv sync --all-extras --dev` and use `--locked --all-extras --dev` in CI or when you need to strictly enforce the lockfile; commit `uv.lock` if present.
- Local formatting commands:

    ```powershell
    uv run ruff check --fix .
    uv run ruff format .
    ```

- Use `prek` to register quick hooks (see `.pre-commit-config.yaml` or `prek.toml`). Install via:

    ```powershell
    uv sync --all-extras --dev
    prek install
    prek run --all-files
    ```

## Agent commits & release policy 🧾

- Use **Conventional Commits** for all changes: `type(scope): short description`.
- Wrap commit body lines to **100 characters** or fewer — failing to do so may be blocked by commitlint/`prek` rules.
- When changing production code add or update tests. Include short rationale in the commit body for non-trivial design decisions.
- Release workflow (semantic versioning):
  - Update version in `__init__.py` only and commit with message equal to the version (GPG-signed).
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
    uv run pytest -q
    ```

## VS Code setup 🧭

- Recommend enabling `chat.useAgentsMdFile` in workspace settings to help agent workflows.
- Use `.editorconfig` and `markdownlint.jsonc` for consistent Markdown formatting. Format docs via the CLI when needed.

## Todo List Tool Reminder ✅

- Plan multi-step or complex tasks with the Todo List Tool: mark one step `in-progress`, complete it, and mark it done before moving on.

---

## Troubleshooting

- Missing GPG key: ensure your key is available to Git and that `gpg` is in PATH.
- Failed tests: run `pytest -q` locally; ensure dependencies are installed in the venv.

## Maintainers

- List of maintainers or contact details (add e-mail or GitHub handles here).

- Missing GPG key: ensure your key is available to Git and that `gpg` is in PATH.
- Failed tests: run `pytest -q` locally; ensure dependencies are installed in the venv.

## Maintainers

- List of maintainers or contact details (add e-mail or GitHub handles here).
