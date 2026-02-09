---
name: Releases
description: Release checklist and best practices for publishing new versions.
---

<!-- markdownlint-disable-file MD013 MD036 -->

# Releases

This document describes a minimal, reproducible release process for `pyarchivist`.

## Versioning

- Use semantic versioning (MAJOR.MINOR.PATCH).
- Update the canonical version in `src/pyarchivist/__init__.py` (or `__init__.py` at package root) only.

## Release checklist

1. Update the package `__init__` with the new version string (for example, `1.2.3`). After updating the version and before tagging, run `uv sync --all-extras --dev` to refresh `uv.lock` and commit the lockfile (either as part of the release commit or as a separate follow-up commit).

   - Important: ensure `pyproject.toml` [project].version matches `src/pyarchivist/__init__.py::VERSION`. The repository contains a unit test (`tests/pyarchivist/test___init__.py`) that enforces this; run `uv run pytest` to verify the version sync before tagging.

2. Commit using the version string as the commit message and sign the commit with GPG:

```powershell
git add pyproject.toml uv.lock src/pyarchivist/__init__.py
git commit -S -m "1.2.3"
```

1. Create a signed annotated tag:

```powershell
git tag -s -a v1.2.3 -m "v1.2.3"
```

1. Push the release commit and the tag:

```powershell
git push origin HEAD
git push origin --tags
```

1. Build artifacts and publish (CI can handle packaging and publishing; use a manual flow only when needed):

```powershell
# Build with uv: uses bundled uv_build if compatible
uv build --locked
uv run --locked twine upload dist/*
```

## Release notes

- If release notes are required, add them in a separate commit and reference them from the release tag or the repository release page.

## CI & automation

- Prefer publishing from CI using stored secrets (PyPI API tokens in CI secrets) and secure workflows.
- Ensure the CI job performs the following checks before publishing: tests, linters, and package build. Use `uv build --locked` to create artifacts and ensure `pyproject.toml` declares `uv_build` in `[build-system].requires` (for example: `uv_build>=0.10.0,<0.11.0`).

## Post-release

- Update any downstream references or submodules if applicable.
- Verify release artifacts are available on the package index and that checksum verification passes.
