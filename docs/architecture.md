# Architecture

## Current Implementation

```
┌─────────────────────────────────────────────────────┐
│                    CLI (click)                       │
│  generate-logs | stream-logs | watch-logs | simulate │
└──────┬──────────────────────┬───────────────────────┘
       │                      │
       ▼                      ▼
┌──────────────────┐  ┌──────────────────────────────┐
│ Mock File Log    │  │  LLM Providers (standalone)  │
│ Source           │  │                              │
│ src/core/        │  │  BaseLlmProvider (ABC)       │
│ log_sources/     │  │   ├── LlamaCppProvider       │
│                  │  │   └── OpenAiProvider         │
│ - reads mock     │  │                              │
│   files          │  │  Factory: create_llm_provider│
│ - streams        │  │      (settings) -> provider  │
│   appended lines │  │                              │
│ - start/stop     │  │  Can analyze raw logs via    │
│   lifecycle      │  │  `python -m src simulate`    │
└──────────────────┘  └──────────────┬───────────────┘
       │                             │ (not wired to watcher pipeline)
       ▼                             │
┌──────────────────┐                 │
│ Mock Log         │                 │
│ Generator        │                 │
│ mocks/generators/│                 │
│ log_generator.py │                 │
└──────────────────┘                 │
  Generates realistic                │
  K8s-style logs with:               │
  - tracebacks, HTTP errors,         │
    DB failures, OOM kills,          │
    pod restarts, retry fails        │
                                       │
┌──────────────────────────────────────┐
│         Watcher Subsystem            │
│                                      │
│  MockFileLogSource                   │
│    → LogDetector (regex rules)       │
│      → ContextBuilder (rolling buf)  │
│        → DedupTracker                │
│          → IncidentEvent             │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│         Predictor Subsystem          │
│                                      │
│  HeuristicPredictor                  │
│    → Rolling window per service      │
│    → HeuristicRule matching          │
│      → PredictorEvent                │
│                                      │
│  See [predictor.md](predictor.md)    │
└──────────────────────────────────────┘
```

## Key Abstractions

### Log Sources

- **`BaseLogSource`** (`src/core/log_sources/base.py`): ABC defining `start()`, `stop()`, and async `stream()` interface.
- **`MockFileLogSource`**: Reads mock files, appends new lines in a background task, tails via async generator. Note: `MockFileLogSource` directly imports and calls `generate_mock_logs_text` from the generator, so they are tightly coupled rather than independent components.

### Watcher Pipeline

- **`LogDetector`** (`src/core/watcher/detector.py`): Regex-based rule engine that classifies log lines into incident types with severity levels.
- **`ContextBuilder`** (`src/core/watcher/context_builder.py`): Maintains a rolling buffer of recent log lines per source and extracts surrounding context around detected incidents.
- **`RollingBuffer`**: Async-safe bounded in-memory buffer (deque) per source.
- **`_DedupTracker`**: In-memory deduplication using event fingerprints with TTL-based expiry.
- **`LogWatcher`** (`src/core/watcher/watcher.py`): Orchestrates the full pipeline — consumes `BaseLogSource.stream()`, runs detection, builds context, deduplicates, yields `IncidentEvent`.

### LLM Providers (standalone)

- **`BaseLlmProvider`** (`src/providers/base.py`): ABC defining `analyze(log_context: str) -> AnalysisResult`.
- **`AnalysisResult`**: Frozen dataclass holding structured LLM output (root_cause, severity, remediation_suggestions, preventive_actions).
- **`create_llm_provider(settings)`**: Factory that instantiates the correct provider based on `LLM_PROVIDER` in `.env`.

**Note:** Providers exist as independent infrastructure. They can analyze raw logs via `python -m src simulate`, but are NOT yet integrated into the watcher pipeline. The "(not wired to watcher pipeline)" annotation refers specifically to the watcher → provider integration, not the providers themselves (which ARE wired into the `simulate` CLI command).

## Design Principles

- **Local-first**: Runs entirely on your machine with a local llama.cpp server.
- **Minimal dependencies**: No LangChain, CrewAI, or AutoGen — just `asyncio`, `httpx`, and `pydantic`.
- **Log source abstraction**: Swapping log sources is done by implementing one interface.
- **Provider abstraction**: Swapping the LLM backend requires changing one environment variable.
- **Mock-first development**: Full mock log generation with streaming simulation for testing without external infrastructure.

## Future Architecture (planned)

The watcher pipeline will eventually feed detected incidents to LLM providers for automated analysis:

```
Watcher → IncidentEvent → LLM Provider → AnalysisResult → remediation
```

This integration is not yet implemented. See [roadmap.md](roadmap.md) for planned phases.
