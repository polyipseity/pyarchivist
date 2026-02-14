# update-index

## Purpose

Describe how to update an `index.md` after adding or modifying archive files in a directory. This skill ensures index entries remain machine-parseable and human-readable.

## Inputs

- Path to `index.md`.
- New or updated filename(s) and credit strings.

## Outputs

- Updated `index.md` with entries formatted as `- [<filename>](<url-escaped-filename>): <credit>`.
- Validation report confirming the index is sorted and no duplicated filenames exist.

## Preconditions

- The destination directory exists and contains intended files.
- The `index.md` can be opened for read/write (LOCALLY or via PR).

## Steps

1. Read the current `index.md` and parse the last paragraph (where entries are stored) using the regex `_INDEX_FORMAT_PATTERN` from `src/pyarchivist/Wikimedia_Commons/main.py`.
2. Merge or add entries and ensure filenames are escaped using the same rule as `_index_formatter` (escape backslashes `\\` and `]`).
3. Sort entries by filename and write back the file preserving other paragraphs.
4. Run linting and, if applicable, a local smoke run of the CLI to confirm the behavior.

## Checks

- No duplicate entries for the same filename.
- The index paragraph consists only of correctly formatted lines matching the regex.
- The file ends with a single trailing newline.

## Notes

- Prefer programmatic updates (scripts or CLI) to manual edits when possible to avoid formatting mistakes.
- If a change affects many entries, consider a small PR and ask for a human review to verify the metadata.
