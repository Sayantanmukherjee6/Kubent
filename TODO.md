# TODO

## Code Review — 2026-05-10 10:39:37 IST

### Summary

Well-structured hackathon POC. Clean abstractions (`BaseLogSource`, `BaseLlmProvider`, factory pattern). Good README. 20/29 tests passing, 9 failing. Issues below are mostly test bugs and minor code fixes — nothing architectural.

---

### 🔴 Test Failures (9 tests broken)

#### 1. `tests/unit/test_config.py::TestSettings::test_default_settings`
- **Issue**: Test expects `["info", "warning", "error", "critical"]` but `Settings` defaults to `["info", "warn", "error", "critical"]`.
- **Fix**: Change test assertion to `["info", "warn", "error", "critical"]` (the code is correct, the test is wrong).

#### 2. `tests/unit/test_config.py::TestProviderFactory::test_create_unsupported_provider`
- **Issue**: Setting `LLM_PROVIDER=unknown_provider` via env var causes pydantic StrEnum validation to crash *before* the factory runs. The test never reaches `create_llm_provider()`.
- **Fix**: Either mock the enum directly or test with `Settings(llm_provider=LlmProviderType("unknown"))` if pydantic allows it.

#### 3. `tests/unit/test_log_sources.py::TestLogEntry::test_format_basic`
- **Issue**: Test calls `str(entry)` but `LogEntry` has no `__str__` method — it has `format()`. `str(entry)` returns the dataclass repr.
- **Fix**: Change `formatted = str(entry)` to `formatted = entry.format()`.

#### 4. `tests/unit/test_log_sources.py::TestLogEntry::test_format_without_pod`
- **Issue**: Same as #3 — `str(entry)` should be `entry.format()`.

#### 5. `tests/unit/test_log_sources.py::TestGenerateLogEntries::test_timestamps_are_ordered`
- **Issue**: Jitter of ±0.5s with step of 0.5–3.0s causes more out-of-order entries than the 30% threshold allows.
- **Fix**: Increase threshold to `0.6` or reduce jitter range.

#### 6. `tests/integration/test_llm_pipeline.py::test_analysis_pipeline`
- **Issue**: The mock server fixture patches `client.post` on a *new* `AsyncClient` instance, but `LlamaCppProvider.analyze()` creates its *own* `AsyncClient`. The patch never applies.
- **Fix**: Use `respx` library or `unittest.mock.patch` on `httpx.AsyncClient.post` at the class level.

#### 7. `tests/integration/test_log_sources.py::test_streaming_yields_lines`
- **Issue**: `async for i, line in enumerate(source.stream())` — `source.stream()` is an async generator, not `enumerate()`. The unpacking is wrong.
- **Fix**: Use `async for line in source.stream()` and track count manually, or wrap with `enumerate` properly: `async for i, line in enumerate(source.stream()):` (this actually works in Python 3.10+ but the error suggests the enumerate isn't being awaited correctly).

#### 8. `tests/integration/test_log_sources.py::test_source_name_property`
- **Issue**: Passes `log_dir=settings.mock_log_dir` which is a `str`, but `MockFileLogSource.__init__` expects `Path | None`. String `/` operator fails.
- **Fix**: Convert to `Path` in `__init__`: `self._log_dir = Path(log_dir) if log_dir else Path("mocks/logs")`.

#### 9. `tests/integration/test_log_sources.py::test_double_start_is_safe`
- **Issue**: Missing `tmp_log_dir` fixture parameter in the function signature. `tmp_log_dir` resolves to the raw fixture function object.
- **Fix**: Add `tmp_log_dir: Path` parameter to the test function signature.

---

### 🟡 Code Quality (non-blocking)

#### 10. Duplicate `_parse_json` method
- `src/providers/llama_cpp.py` and `src/providers/openai.py` have identical `_parse_json()` methods.
- **Suggestion**: Move to `BaseLlmProvider` as a static method or a shared utility.

#### 11. Duplicate `_SYSTEM_PROMPT`
- Same prompt string in both provider files.
- **Suggestion**: Define in `src/providers/base.py` and import.

#### 12. `stream_log_entries` return type annotation
- `mocks/generators/log_generator.py` declares `-> None` but it's an async generator that yields `LogEntry`.
- **Suggestion**: Change to `-> AsyncIterator[LogEntry]`.

#### 13. `MockFileLogSource` doesn't accept `str` for `log_dir`
- Type hint says `Path | None` but callers may pass strings (e.g., from settings).
- **Suggestion**: Accept `Path | str | None` and convert internally.

#### 14. `stream-logs` sync file tail uses `asyncio.get_event_loop().run_until_complete()`
- `src/__main__.py` line ~85: mixing sync file I/O with async sleep in a blocking loop.
- **Suggestion**: For a POC this is fine, but could use `watchfiles` or `aiofiles` for a cleaner approach.

#### 15. `LogEntry` missing `__str__`
- Has `format()` but no `__str__`. Tests call `str(entry)` expecting formatted output.
- **Suggestion**: Add `def __str__(self) -> str: return self.format()`.

---

### 🟢 Nice-to-Have

#### 16. `.env.example` severity mismatch
- `.env.example` lists `MOCK_LOG_SEVERITIES=info,warning,error,critical` but code defaults to `info,warn,error,critical`.
- **Suggestion**: Align the example file with actual defaults.

#### 17. No `__init__.py` in `src/core/log_sources/`
- Missing `__init__.py` in the log_sources package directory.
- **Suggestion**: Add one (even if empty) for explicit package declaration.

#### 18. `requirements.txt` duplicates `pyproject.toml`
- Both files list the same dependencies.
- **Suggestion**: Pick one source of truth (prefer `pyproject.toml`).

---

### ✅ What's Done Well

- Clean ABC design for `BaseLogSource` and `BaseLlmProvider`
- Factory pattern for provider selection
- Realistic mock log generator with tracebacks, pod names, K8s-style formatting
- Good separation of unit vs integration tests
- Comprehensive README with architecture diagram
- Minimal dependencies (no LangChain/CrewAI bloat)
