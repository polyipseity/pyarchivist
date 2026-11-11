# SDD ledger — plan: /Users/polyipseity/.pi/agent/memory/session/plan-2026-11-11T143105.md

## Task 1 — request mime and size from API

- Added `mime` and `size` fields (optional, default `None`) to `ImageInfoEntry` with frozen config and docstring; `__all__` unchanged.
- Documented `_query` to request `iiprop=extmetadata|mime|size|url` for download verification; `archive` uses module-level `_query`.
- Added model tests for `mime`/`size` parsing and defaults; updated query batching test to assert `iiprop` includes `mime,size`.
- Validation: `uv run pytest tests/src/pyarchivist/Wikimedia_Commons/test_models.py tests/src/pyarchivist/Wikimedia_Commons/test_main.py -v` (62 passed), `uv run ty check` (pass), `uv run ruff check --fix . && uv run ruff format .` (pass).
