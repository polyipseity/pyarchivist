---
name: Formatting & Linters
description: How to run and configure formatters and linters for consistent code style.
---

# Formatting & Linters

This repository uses a small, consistent set of tooling for formatting and linting. The goal is to be fast, deterministic, and easy to run locally and in CI.

## Canonical formatter

- **Ruff** is the canonical Python formatter and linter for this project. Do not add `black` or `isort` to CI or dev tooling; Ruff covers formatting and import ordering.
- **Line length**: 88 characters (configured in `pyproject.toml`).

## Common tasks

- Format repository (auto-fix where possible):

```powershell
uv run ruff check --fix .
uv run ruff format .
```

- Run static type checks (pyright/Pylance): ensure `pyrightconfig.json` uses `typeCheckingMode: "strict"` for CI parity.

## Editor integration

- Use the editor's Ruff/pyright integration where available. Keep the editor settings consistent with `.editorconfig` and `pyrightconfig.json`.

## Pre-commit-style checks (prek)

- The repository provides `.pre-commit-config.yaml` for compatibility and we recommend a native `prek.toml` for `prek`-first configuration. The same hooks (for example `pre-commit-hooks` and the Ruff hooks) work with `prek`.

Install and run locally:

```powershell
uv sync --dev
prek install
prek run --all-files
```

- If a hook is too strict for the repo's needs (for example `forbid-submodules` in a repo that uses submodules intentionally), adjust the `prek.toml` (or `.pre-commit-config.yaml`) accordingly.

## Notes

- These hooks are a recommended baseline. If a particular hook is undesired, remove or configure that hook in `prek.toml`.
- Keep hook repositories pinned (set `rev`) to an explicit release to ensure reproducible behaviour.


## Markdown & other formats

- Use `markdownlint-cli2` (if present) for `.md` files and respect `.markdownlint.jsonc` when present.
- Avoid introducing conflicting formatters for Python files.

## Notes

- Always run formatters and linters before committing to avoid CI failures.
- For large formatting changes, prefer small, focused commits and run the test suite locally after formatting to catch regressions.
