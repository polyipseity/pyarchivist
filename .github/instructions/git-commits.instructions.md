# Git Commit & Commit Message Conventions

This file documents the repository's expectations for commit messages, signing,
and release commits.

Conventional commits:

- Use the Conventional Commit format (`type(scope): short description`).
  Example: `chore(tests): add async file factory fixture`.

Commit header & body lengths:

- Tooling enforces a **hard maximum of 100 characters** for both the commit subject/header and body lines (this is enforced by `commitlint` via `header-max-length` and `body-max-line-length`).
- The repository prefers a **soft limit of 72 characters** for both subject/header and body lines. The `commitlint` configuration includes warning-level rules that will warn when lines exceed 72 characters but still allow up to 100 characters; aim to keep the subject ≤72 and wrap body lines at 72 for best readability.
Signed release commits & tags:

- Release commits that bump the package version MUST be signed with GPG.
  Example steps:

    ```powershell
    git add src/pyarchivist/__init__.py
    git commit -S -m "1.2.3"
    git tag -s -a v1.2.3 -m "v1.2.3"
    git push origin HEAD && git push origin --tags
    ```

Pre-commit & validation:

- Run `prek run --all-files` locally before pushing changes (or run individual hooks with `prek run <hook-id>`).
- Ensure tests and linters pass; CI will re-run these and block the PR if they fail.

Agent & automation notes:

- Agents must include a short rationale in the commit body when deviating from
  usual conventions or performing non-trivial changes.
- Transaction or domain-data commits (if applicable) may follow stricter
  machine-parseable formats; follow domain-specific policies if present.
