---
name: Testing
description: Test structure, how to write tests, and async testing guidance.
---

<!-- markdownlint-disable-file MD013 MD036 -->

# Testing

Tests use `pytest` and `pytest-asyncio` for async test support. Test configuration is provided in `pyproject.toml` under `[tool.pytest.ini_options]`.

## Test layout and conventions

- All tests live under `tests/` and follow `test_*.py` naming.
- When creating new test directories (or source directories), include an `__init__.py` file so the folder is an explicit Python package. Mirror the `src/` structure under `tests/` (for example `src/module/sub.py` → `tests/module/test_sub.py`) and ensure package-style test subfolders contain `__init__.py`.
- **One test file per source file** is the preferred layout. Mirror the `src/` structure under `tests/` (for example `src/module/sub.py` → `tests/module/test_sub.py`).
- Test modules must define `__all__ = ()` at the top (tests do not export public symbols).
- All tests and public code must include type annotations and module-level docstrings. Do not use `from __future__ import annotations` in tests; prefer using `typing.TYPE_CHECKING` and explicit string annotations only where necessary to avoid runtime imports.

Docstrings & enforcement:

- Tests should include a module-level docstring summarizing the file's purpose and any important rules.
- Public functions and classes exported via `__all__` must include non-empty docstrings describing their behaviour and parameters.
- A unit test (`tests/test_docstrings.py`) is provided to assert that every module has a module-level docstring and that every exported function/class has a docstring. Agents should run the test suite to confirm compliance before opening PRs.

Enforcing `__all__`:

- Add a unit test that parses all repository modules' AST to check for a top-level `__all__` assignment and assert that it is a tuple of string constants. This avoids importing modules (which can execute top-level code) while ensuring the `__all__` policy is followed.
- When a module intentionally exports no public symbol, set `__all__ = ()` instead of leaving it undefined.
- Update the `tests/` tree whenever a new public symbol is added to ensure coverage and to keep the public surface documented and tested.

## Async tests

- For async code use `async def` tests decorated with `@pytest.mark.asyncio` and `await` coroutines in the test body.
- Do not use `asyncio.run`, `anyio.run`, or similar event-loop wrappers inside tests.

## Running tests locally

```powershell
uv run pytest
# With coverage
uv run pytest --cov=./ --cov-report=term-missing
```

## CI expectations

- CI runs the full test suite and reports coverage. Fast feedback jobs may run a subset; full CI runs the full suite.
- Mark slow or flaky tests appropriately and document mitigation strategies.

## Writing good tests

- Aim for small, deterministic, and fast tests.
- Use fixtures for shared setup. Keep fixture scope appropriate (function or module) for isolation and speed.
- When changing behaviour, add or update tests to cover the change; keep coverage stable or improved.
- Pydantic models: when testing `BaseModel` behaviour, expect pydantic v2 idioms — models may declare `model_config = ConfigDict(...)`. Tests should assert the model's runtime behaviour (for example immutability when `frozen=True`) rather than implementation details like the exact `model_config` representation.

## Testing integration flows

- For integration-like tests around `Wikimedia_Commons`, mock `aiohttp.ClientSession` and responses instead of calling the external API. Use `pytest` fixtures or `monkeypatch` to replace `ClientSession.get` with an async context manager that returns stubbed `.json()` and `.content` behaviour.
- When asserting index updates, leverage the code's pattern: entries are formatted using `_index_formatter` and parsed with `_INDEX_FORMAT_PATTERN` (see `src/pyarchivist/Wikimedia_Commons/main.py`). Tests should assert the final `index.md` paragraph contains sorted entries and properly escaped filenames (backslashes and `]` are escaped by `_index_formatter`).
- To verify error paths, assert exit codes produced by `ExitCode` flags (e.g., `ExitCode.QUERY_ERROR`, `ExitCode.FETCH_ERROR`) are reflected when invoking the CLI invocation coroutine; capture logs with `caplog` to assert expected logged messages for partial error handling.

## Common pitfalls

- Avoid reliance on external services in unit tests; use mocks, fixtures, or recorded responses.
- For filesystem tests, use `tmp_path` fixtures and avoid assumptions about current working directory.
