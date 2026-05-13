# Kubernetes Agent — AI-Powered Observability Assistant

Monitors simulated Kubernetes/Grafana logs, detects errors via regex-based rules, and predicts recurring failure patterns using deterministic heuristics. LLM analysis is available as a standalone tool (`simulate`) but is not yet wired into the watcher pipeline.

## Quick Start

```bash
source ../venv/bin/activate
pip install -e ".[test]"
cp .env.example .env   # Edit with your settings
python -m src simulate
```

## Documentation

| Doc | Content |
|---|---|
| [Architecture](docs/architecture.md) | System overview, key abstractions, design principles |
| [Providers](docs/providers.md) | LLM backends (llama.cpp, OpenAI), factory, request flow |
| [Log Sources](docs/log_sources.md) | BaseLogSource abstraction, mock file source, folder source, log generator |
| [Metrics](docs/metrics.md) | Metric subsystem, MockMetricSource, FolderMetricSource, CSV ingestion |
| [Watcher](docs/watcher.md) | Log monitoring, regex detection (26 rules), context, dedup |
| [Predictor](docs/predictor.md) | Heuristic prediction engine (4 rules), rolling windows |
| [CLI](docs/cli.md) | All commands: generate-logs, stream-logs, watch-logs, predict, simulate |
| [Development](docs/development.md) | Prerequisites, setup, config reference, folder structure |
| [Testing](docs/testing.md) | Test architecture, running tests, coverage by module |
| [Prompting](docs/prompting.md) | System prompt format and structured JSON output |
| [Roadmap](docs/roadmap.md) | Implemented vs planned phases |

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    CLI (click)                       │
│  generate-logs | stream-logs | watch-logs | predict | predict-metrics │ simulate │
└──────┬──────────────────┬────────────────┬───────────┘
       │                  │                │
       ▼                  ▼                ▼
┌──────────────────┐  ┌──────────────────────────────┐
│ Log Source       │  │  LLM Providers               │
│ Factory          │  │  BaseLlmProvider (ABC)       │
│                  │  │   ├── LlamaCppProvider       │
│ create_log_      │  │   └── OpenAiProvider         │
│ source(settings) │  │                              │
│     → mock or    │  │  Factory: create_llm_provider│
│       folder     │  │      (settings) -> provider  │
└──────┬───────────┘  │                              │
       │              │  Can analyze raw logs via    │
   ┌────┴────┐        │  `python -m src simulate`    │
   │         │        │                              │
   ▼         ▼        │  (standalone, not wired to   │
┌──────────┐ ┌───────┐│      watcher pipeline)       │
│MockFile  │ │Folder ││                              │
│LogSource │ │Log-   ││                              │
│          │ │Source ││                              │
│- writes  │ │       ││                              │
│  mock    │ │- tails││                              │
│  logs    │ │  *.log││                              │
└──────────┘ └───────┘│                              │
       All CLI commands (stream-logs, watch-logs,    │
       predict) use create_log_source(settings)      │
       with optional --source and --log-dir overrides│
                      │                              │
┌──────────────────────────────────────┐             │
│         Watcher Subsystem            │             │
│                                      │             │
│  BaseLogSource (from factory)        │             │
│    → LogDetector                     │             │
│      → ContextBuilder                │             │
│        → DedupTracker                │             │
│          → IncidentEvent             │             │
└──────────────┬───────────────────────┘             │
               │                                     │
               ▼                                     │
┌──────────────────────────────────────┐             │
│         Predictor Subsystem          │             │
│                                      │             │
│  HeuristicPredictor                  │             │
│    → Rolling windows                 │             │
│    → Heuristic rules                 │             │
│      → PredictorEvent                │             │
└──────────────────────────────────────┘             │
┌──────────────────────────────────────┐
│         Metrics Subsystem            │
│                                      │
│  BaseMetricSource (from factory)     │
│    → MockMetricSource                │
│      → Trend-based simulation        │
│    → FolderMetricSource              │
│      → CSV tailing + parsing         │
│      → Offset tracking               │
└──────────────────────────────────────┘
┌──────────────────────────────────────┐
│   Statistical Metric Predictor       │
│                                      │
│  MetricPredictor                     │
│    → RollingWindow (per-service)     │
│    → Z-score anomaly detection       │
│    → Linear trend forecasting        │
│    → OOM risk heuristic              │
│    → PredictionRule evaluation       │
│      → MetricPredictionEvent         │
└──────────────────────────────────────┘
```

## Log Sources

The agent supports two log source modes, selected via `log_source.type` in `config/config.yaml`:

| Type | Description | Use Case |
|---|---|---|
| `mock` (default) | Generates synthetic K8s logs to a file and streams them | Development, testing, demos |
| `folder` | Tails `*.log` files in a shared directory | External log ingestion, sidecar patterns |

**Switching sources:**
```yaml
# config/config.yaml
log_source:
  type: folder              # "mock" or "folder"
  folder_path: /tmp/k8s-shared-logs
```

Or via environment variable: `LOG_SOURCE_TYPE=folder`

**Folder source notes:**
- Only `*.log` files in the configured directory are watched
- Single-consumer: only one `stream()` call may be active at a time (raises `RuntimeError` otherwise)
- Filesystem errors (permission denied, missing files) are logged at WARNING level

## Metrics Subsystem

The agent includes a lightweight metric subsystem that mirrors the log source
architecture. It supports mock metric streaming and folder-based CSV ingestion,
providing a foundation for future predictive analysis.

```
┌──────────────────────────────────────┐
│  Metric Source Factory               │
│                                      │
│  create_metric_source(settings)      │
│    → mock or                         │
│      folder                          │
└──────┬───────────────────────────────┘
       │
   ┌────┴────┐
   │         │
   ▼         ▼
┌──────────┐ ┌────────────────┐
│MockMetric│ │FolderMetric    │
│Source    │ │Source          │
│          │ │               ││
│- generates│- tails *.csv   ││
│  metrics │- parses CSV     ││
│- trends   │- offset tracking││
└──────────┘ └────────────────┘
```

**Metric source types:**

| Type | Description | Use Case |
|---|---|---|
| `mock` (default) | Generates synthetic K8s-style metrics with natural trends | Development, testing |
| `folder` | Tails `*.csv` metric files in a shared directory | External metric ingestion |

**CSV format:**

```
timestamp,service,cpu,memory,latency,error_rate
2026-01-01T10:00:00Z,payment-service,72,68,120,0.01
```

**Switching sources:**
```yaml
# config/config.yaml
metrics:
  source:
    type: folder              # "mock" or "folder"
    folder_path: ./demo_metrics
```

Or via environment variable: `METRICS_SOURCE_TYPE=folder`

## Statistical Metric Predictor (Lightweight Forecasting)

The agent includes a **lightweight statistical forecasting** engine that predicts
resource threshold breaches and anomalies using basic statistical inference — no
machine learning, no external libraries.

```
┌──────────────────────────────────────┐
│  MetricPredictor                     │
│                                      │
│  process(MetricSample)               │
│    → RollingWindow (per-service)     │
│      → Z-score anomaly detection     │
│      → Linear trend forecasting      │
│      → OOM risk heuristic            │
│      → PredictionRule evaluation     │
│    → list[MetricPredictionEvent]     │
└──────────────────────────────────────┘
```

**Supported prediction types:**

| Type | Description |
|---|---|
| `PREDICTED_CPU_BREACH` | CPU usage predicted to cross threshold via linear trend |
| `PREDICTED_MEMORY_BREACH` | Memory usage predicted to cross threshold via linear trend |
| `PREDICTED_OOM` | Out-of-memory risk (rising memory + rising latency near threshold) |
| `CPU_ANOMALY` | CPU value deviates significantly from baseline (z-score > 2.5) |
| `MEMORY_ANOMALY` | Memory value deviates significantly from baseline (z-score > 2.5) |
| `LATENCY_ANOMALY` | Latency value deviates significantly from baseline (z-score > 2.5) |

**Statistical methods used:**

- **Moving Average** — rolling average over recent samples for smoothing
- **Median** — stable baseline resistant to outliers
- **Standard Deviation** — spread analysis for anomaly detection
- **Z-Score Anomaly Detection** — flags values where |z| > 2.5
- **Linear Trend Forecasting** — simple slope-based prediction: `future = current + slope * steps`

**Prediction cooldown:** Duplicate prediction events for the same `(service, prediction_type)` are
suppressed for a configurable cooldown period (default 30 seconds). This prevents event spam when a
condition persists across multiple samples. Cooldown is per-service and per-prediction-type, so
different services or different prediction types are not affected by each other. Set
`cooldown_seconds=0` to disable.

**Threshold forecasting:** Reads thresholds from `config.yaml` (`metrics.thresholds.cpu_percent`, `metrics.thresholds.memory_percent`). If the linear trend predicts crossing a threshold within 10 samples, a breach prediction event is emitted.

**OOM risk heuristic (simple):**
- IF memory is rising steadily (positive slope)
- AND memory is near threshold (> 80% of threshold)
- AND latency is increasing (positive slope)
- THEN emit `PREDICTED_OOM` event

**CLI usage:**

```bash
# Stream metrics with predictor (15s default)
python -m src predict-metrics

# Custom duration and source override
python -m src predict-metrics --duration 30 --source folder --metric-dir /tmp/metrics
```

**Example output:**

```
Streaming from mock-metrics (Ctrl+C to stop)...
CPU threshold: 85% | Memory threshold: 90% | Window: 100
----------------------------------------------------------------------
[PREDICTED_CPU_BREACH]
  Service     : payment-service
  Severity    : medium
  Message     : CPU predicted to breach 85% threshold (forecast: 86.3%)
  Current     : 84.0
  Predicted   : 86.3
  Threshold   : 85.0
```

## Predict Workflow

The `predict` command wires the full watcher + predictor pipeline together for real-time
incident prediction. It streams logs through detection, deduplication, and heuristic
prediction rules, printing color-coded predictions to the terminal.

```bash
# Basic usage (mock source, 15s duration)
python -m src predict

# Custom duration and severity
python -m src predict --duration 30 --min-severity high

# Override log source type and directory (no config file changes needed)
python -m src predict --source folder --log-dir /var/log/k8s-apps
python -m src predict --source mock --log-dir /tmp/demo-logs

# Low severity to catch everything
python -m src predict -s low -t 600 -n 2
```

**Example output:**

```
Predicting on mock-file:mocks/logs/mock_stream.log
Min severity: high | Dedup TTL: 300s | Dedup threshold: 1
----------------------------------------------------------------------
[HIGH]  #1
  service   = payment-service
  pattern   = Repeated HTTP 5xx error spikes detected
  trigger_count = 5
  related   = abc123def456

[CRITICAL]  #2
  service   = auth-service
  pattern   = Repeated OOMKilled events detected
  trigger_count = 3
----------------------------------------------------------------------
Stopped after 15.2s. 8 incident(s), 2 prediction(s).
```

**Demo setup with external logs:**

```bash
# Write external logs to a shared directory
python -m src generate-logs --count 200 -o /tmp/demo-logs/app.log

# Predict on the external log directory
python -m src predict --source folder --log-dir /tmp/demo-logs --duration 5
```

## Scenario-Based Metric Generation

The agent includes deterministic, scenario-driven metric simulation that produces
realistic, correlated metrics for demo and testing purposes. Each scenario models a
specific failure pattern with natural metric correlations.

**Available scenarios:**

| Scenario | Behavior | Triggers |
|---|---|---|
| `steady_cpu_growth` | CPU climbs from 40→93% over 60 steps; latency correlates upward | CPU breach prediction |
| `memory_leak` | Memory leaks from 55→93%; error_rate spikes near OOM threshold | OOM risk, memory breach |
| `latency_spike` | Periodic latency spikes (every ~20 steps) with brief recovery | Latency anomaly detection |
| `cascading_failure` | Multi-phase: normal → degrade → cascade → recover | Multiple prediction types |
| `recovery_phase` | Metrics converge from degraded state back to healthy baselines | Predictor stops firing |

**Service-specific defaults:** When no scenarios are specified, each service gets a
default scenario: `gateway` → CPU growth, `payment-service` → latency spikes,
`auth-service` → memory leak.

**Per-service step isolation:** Each service maintains its own independent step counter within the
scenario engine. Advancing one service does not affect the step progression of another, ensuring
deterministic, isolated metric generation regardless of call ordering.

**Generate demo CSV files:**

```bash
# List available scenarios
python -m src generate-metrics --list

# Generate with per-service defaults (60 steps = 5 minutes of simulated time)
python -m src generate-metrics --output ./demo_metrics

# Specify specific scenarios and services
python -m src generate-metrics \
    --scenarios steady_cpu_growth,memory_leak \
    --services gateway auth-service \
    --duration 60

# Output directory structure
demo_metrics/
├── gateway.csv              # CPU growth scenario
├── auth-service.csv         # Memory leak scenario
└── payment-service.csv      # Latency spike scenario
```

**Use scenarios with MockMetricSource:** Set `metrics.scenarios` in `config.yaml`:

```yaml
metrics:
  source:
    type: mock
  scenarios:
    - steady_cpu_growth
    - memory_leak
```

Or via environment variable: `METRICS_SCENARIOS=steady_cpu_growth,memory_leak`

Then stream with scenario-driven metrics:

```bash
python -m src predict-metrics --duration 60
```

## Design Principles

- **Local-first**: Runs entirely on your machine with a local llama.cpp server.
- **Minimal dependencies**: No LangChain, CrewAI, or AutoGen — just `asyncio`, `httpx`, and `pydantic`.
- **Log source abstraction**: Swapping log sources requires implementing one interface (`BaseLogSource`).
- **Provider abstraction**: Swapping the LLM backend requires changing one environment variable.
- **Metric source abstraction**: Swapping metric sources requires implementing one interface (`BaseMetricSource`).
- **Mock-first development**: Full mock log generation with streaming simulation for testing without external infrastructure.

## Quick Reference

```bash
source ../venv/bin/activate
pip install -e ".[test]"
python -m src generate-logs --count 100
python -m src stream-logs --duration 15
python -m src watch-logs --duration 15
python -m src predict --duration 15
python -m src simulate (depreciated, will be removed soon)
python -m src stream-metrics --duration 15   # Stream raw metrics (no prediction)
python -m src predict-metrics --duration 15   # Stream metrics + statistical predictions
python -m src generate-metrics --list       # List available scenarios
python -m src generate-metrics              # Generate demo CSV files
pytest -v
echo 'LLM_PROVIDER=openai' >> .env   # Switch to OpenAI
```
