# Architecture

## Overview

```
┌─────────────────────────────────────────────────────────┐
│                      CLI (click)                         │
│  generate-logs | stream-logs | watch-logs | predict     │
│  simulate                                               │
└──────┬───────────────────┬──────────────────┬───────────┘
       │                   │                  │
       ▼                   ▼                  ▼
┌──────────────────┐  ┌────────────────────────────────┐
│ Log Source       │  │  LLM Providers (standalone)    │
│ Factory          │  │                                │
│                  │  │  BaseLlmProvider (ABC)          │
│ create_log_      │  │   ├── LlamaCppProvider         │
│ source(settings) │  │   └── OpenAiProvider           │
│   → mock or      │  │                                │
│     folder       │  │  Factory: create_llm_provider  │
└──────┬───────────┘  │     (settings) → provider      │
       │              │                                │
   ┌────┴────┐        │  Analyze raw logs via          │
   │         │        │  `python -m src simulate`      │
   ▼         ▼        │  (not wired to watcher pipeline│
┌──────────┐ ┌───────┐│                              │
│MockFile  │ │Folder ││                              │
│LogSource │ │Log-   ││                              │
│          │ │Source ││                              │
│- writes  │ │- tails││                              │
│  mock    │ │  *.log││                              │
│  logs    │ │       ││                              │
└──────────┘ └───────┘│                              │
       All CLI commands (stream-logs, watch-logs,     │
       predict) use create_log_source(settings)       │
       with optional --source and --log-dir overrides │
                      │                               │
┌────────────────────────────────────────────────────┐ │
│         Watcher Subsystem                          │ │
│                                                    │ │
│  BaseLogSource (from factory)                      │ │
│    → LogDetector (regex rules)                     │ │
│      → ContextBuilder (rolling buf)                │ │
│        → DedupTracker                              │ │
│          → IncidentEvent                           │ │
└──────────────┬─────────────────────────────────────┘│
               │                                      │
               ▼                                      │
┌────────────────────────────────────────────────────┐│
│         Predictor Subsystem                        ││
│                                                    ││
│  HeuristicPredictor                                ││
│    → Rolling windows                               ││
│    → Heuristic rules                               ││
│      → PredictorEvent                              ││
│                                                    ││
│  See [predictor.md](predictor.md)                  ││
└────────────────────────────────────────────────────┘│
```

## Key Abstractions

### Log Sources & Factory

- **`BaseLogSource`** (`src/core/log_sources/base.py`): ABC defining `start()`, `stop()`, and async `stream()` interface.
- **`create_log_source(settings)`** (`src/core/log_sources/factory.py`): Factory that returns the correct source based on `log_source.type` in settings:
  - `"mock"` → `MockFileLogSource` (default, generates synthetic K8s logs)
  - `"folder"` → `FolderLogSource` (tails `*.log` files in a shared directory)
- **`MockFileLogSource`** (`src/core/log_sources/mock_file_source.py`): Writes mock logs to a file and streams appended lines.
- **`FolderLogSource`** (`src/core/log_sources/folder_source.py`): Polling-based watcher that tails multiple `*.log` files in a directory.

### CLI Source Selection

All log-consuming CLI commands (`stream-logs`, `watch-logs`, `predict`) use a shared
`_build_settings(source, log_dir)` helper that applies CLI overrides to Settings,
then calls `create_log_source(settings)`. No command instantiates a log source directly.

Override source type and directory without modifying config:

```bash
python -m src stream-logs --source folder --log-dir /tmp/k8s-logs
python -m src watch-logs --source mock --log-dir /tmp/demo-logs
python -m src predict --source folder --log-dir /var/log/apps
```

### Watcher Pipeline

- **`LogDetector`** (`src/core/watcher/detector.py`): Regex-based rule engine that classifies log lines into incident types with severity levels.
- **`ContextBuilder`** (`src/core/watcher/context_builder.py`): Maintains a rolling buffer of recent log lines per source and extracts surrounding context around detected incidents.
- **`_DedupTracker`**: In-memory deduplication using event fingerprints with TTL-based expiry.
- **`LogWatcher`** (`src/core/watcher/watcher.py`): Orchestrates the full pipeline — consumes `BaseLogSource.stream()`, runs detection, builds context, deduplicates, yields `IncidentEvent`.

### LLM Providers (standalone)

- **`BaseLlmProvider`** (`src/providers/base.py`): ABC defining `analyze(log_context: str) -> AnalysisResult`.
- **`AnalysisResult`**: Frozen dataclass holding structured LLM output (root_cause, severity, remediation_suggestions, preventive_actions).
- **`create_llm_provider(settings)`**: Factory that instantiates the correct provider based on `LLM_PROVIDER` in `.env`.

**Note:** Providers exist as independent infrastructure. They can analyze raw logs via `python -m src simulate`, but are NOT yet integrated into the watcher pipeline.

### Metrics Subsystem

- **`BaseMetricSource`** (`src/core/metrics/base.py`): ABC defining `start()`, `stop()`, and async `stream()` interface for metric sources.
- **`MetricSample`** (`src/core/metrics/models.py`): Frozen dataclass holding timestamp, service name, CPU/memory/latency/error-rate values.
- **`create_metric_source(settings)`** (`src/core/metrics/factory.py`): Factory that returns the correct source based on `metrics.source.type` in settings:
  - `"mock"` → `MockMetricSource` (default, generates synthetic K8s metrics)
  - `"folder"` → `FolderMetricSource` (tails `*.csv` files in a directory)
- **`MockMetricSource`** (`src/core/metrics/mock_metric_source.py`): Generates realistic Kubernetes-style metrics with natural trend-based progression for CPU, memory, latency, and error rate.
- **`FolderMetricSource`** (`src/core/metrics/folder_metric_source.py`): Polling-based watcher that tails `*.csv` metric files, parses CSV lines, and tracks per-file offsets.

CSV format: `timestamp,service,cpu,memory,latency,error_rate`

### Statistical Metric Predictor (Lightweight Forecasting)

- **`RollingWindow`** (`src/core/metrics/predictor.py`): Bounded deque-based rolling window with statistical methods — moving average, median, standard deviation, z-score computation, and linear trend forecasting.
- **`MetricPredictor`** (`src/core/metrics/predictor.py`): Processes `MetricSample` objects through four analysis stages:
  1. Z-score anomaly detection (|z| > 2.5) for CPU, memory, and latency
  2. Linear trend forecasting against configured thresholds for breach prediction
  3. OOM risk heuristic (rising memory + rising latency near threshold)
  4. Custom `PredictionRule` evaluation
- **`MetricPredictionEvent`** (`src/core/metrics/events.py`): Frozen dataclass holding prediction details including type, severity, current/predicted values, and threshold.
- **`PredictionRule`** (`src/core/metrics/rules.py`): Configurable rule with threshold-based or custom condition evaluation.

This subsystem uses only stdlib modules (statistics, math, asyncio, collections.deque, dataclasses) — no ML frameworks, no pandas/numpy.

See [metrics.md](metrics.md) for the metric source architecture.
## Design Principles

- **Local-first**: Runs entirely on your machine with a local llama.cpp server.
- **Minimal dependencies**: No LangChain, CrewAI, or AutoGen — just `asyncio`, `httpx`, and `pydantic`.
- **Log source abstraction**: Swapping log sources is done via the factory — implement one interface.
- **Provider abstraction**: Swapping the LLM backend requires changing one environment variable.
- **Mock-first development**: Full mock log generation with streaming simulation for testing without external infrastructure.

## Future Architecture (planned)

The watcher pipeline will eventually feed detected incidents to LLM providers for automated analysis:

```
Watcher → IncidentEvent → LLM Provider → AnalysisResult → remediation
```

This integration is not yet implemented. See [roadmap.md](roadmap.md) for planned phases.
