<!-- markdownlint-disable-file MD013 MD036 -->

# Archive Format & Indexing

This file documents the expected layout, naming, and metadata for archives
stored under `archives/` (if this repository uses an archives tree). The
guidelines are intentionally conservative to ensure reproducibility and
machine-friendly metadata.

Directory layout and naming:

- `archives/<topic>/<YYYY>/...` — group archives by topic and year.
- Files should use stable, human-readable names and avoid personal or
  confidential identifiers. When sensitive data is required, store it in an
  encrypted store (`private.yaml.gpg`).

`index.md` files:

- Each archive directory SHOULD include an `index.md` (Markdown) file listing
  its contents and providing brief descriptions and canonical metadata (date,
  source URL, license, and a short summary).
- Use YAML frontmatter for machine-readable metadata if the repo uses it.
- The `Wikimedia_Commons` flow manages `index.md` paragraphs programmatically: entries are lines of the form `- [<filename>](<url-escaped-filename>): <credit>` and are parsed using `_INDEX_FORMAT_PATTERN` in `src/pyarchivist/Wikimedia_Commons/main.py`. When programmatically updating indexes, ensure filenames are escaped the same way as `_index_formatter` (it escapes backslashes and `]`).

Metadata guidelines:

- Include `source`, `date`, `license`, and `sha256` (or similar) where
  available. Keep metadata minimal but sufficient for verification and reuse.
- When content originates from an external service, record the original URL
  and the retrieval datetime in UTC.

Validation & tooling:

- Add tests that verify `index.md` entries are consistent with files in the
  directory (for example: checksums match, required metadata fields are present).
- Prefer simple scripts for validation that can be run in CI and locally via
  `uv` wrappers.
