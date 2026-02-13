<!-- markdownlint-disable-file MD013 MD036 -->

# add-archive

## Purpose

Provide a reproducible, auditable workflow for adding new content to `archives/` and updating the corresponding `index.md` entry. This skill is intended for agents and humans that perform archival ingestion.

## Inputs

- Source identifier(s) to archive (e.g., Wikimedia title `File:Example.jpg`).
- Destination directory under `archives/<topic>/<YYYY>/` or a temporary directory for tests.
- Optional index file path (`index.md`) to update.

## Outputs

- File(s) downloaded to the destination directory.
- `index.md` updated with a properly formatted entry (`- [<filename>](<url-escaped-filename>): <credit>`).
- A short validation summary (success/fail) and any error logs.

## Preconditions

- Development environment set up (see `.github/instructions/agent-workflows.instructions.md`).
- `uv` dev extras installed and pre-commit hooks configured (`prek install`).

## Steps

1. Create a temporary destination directory (or use `archives/<topic>/<YYYY>/`).
2. Run the CLI to fetch and index a sample file to ensure flow correctness:

    ```powershell
    python -m pyarchivist Wikimedia_Commons -d .\tmp_dest -i .\tmp_dest\index.md "File:Example.jpg"
    ```

3. Validate index formatting: ensure the new entry matches `_index_formatter` output and that it appears in the final paragraph sorted by filename.
4. Run the unit tests and linting (`uv run pytest` and `uv run ruff check --fix .`).
5. Commit changes using Conventional Commits and sign release commits if required.

## Checks

- The downloaded file exists in the destination directory.
- `index.md` contains a new entry matching the expected format and is properly escaped.
- No partial error `ExitCode` flags were raised unless expected.

## Notes

- Prefer typing the pytest `tmp_path` fixture as `tmp_path: os.PathLike[str]` in test signatures. When converting path-like objects to strings, use `os.fspath(path_like)`. Use `tmp_path` and mocking for automated tests; avoid network calls in unit tests.
- When in doubt about credit formatting or metadata, ask a human reviewer first.
