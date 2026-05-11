# Watcher Subsystem

The watcher subsystem monitors log streams for error patterns using regex-based detection rules. It consumes from `BaseLogSource.stream()`, builds surrounding context, deduplicates noisy events, and emits structured `IncidentEvent` objects.

**The watcher does NOT integrate with LLM providers.** It operates entirely independently — detection is rule-based, not AI-driven.

## Pipeline Flow

```
BaseLogSource.stream()
  → RollingBuffer (async log ingestion)
    → LogDetector (regex/rule matching)
      → ContextBuilder (rolling context windows)
        → DedupTracker (fingerprinting + TTL expiry)
          → IncidentEvent emission
```

## Key Modules

### `watcher.py` — LogWatcher orchestrator

The main pipeline coordinator. Consumes a `BaseLogSource`, runs detection on each line, builds context, checks deduplication, and yields `IncidentEvent` objects as an async generator.

```python
from src.core.watcher import LogWatcher, WatcherSeverity

watcher = LogWatcher(
    min_severity=WatcherSeverity.MEDIUM,
    dedup_ttl=300.0,
    dedup_threshold=1,
    context_before=5,
    context_after=3,
)

async for incident in watcher.watch(source):
    print(incident)
```

### `detector.py` — LogDetector

Regex-based rule engine with 32 built-in detection rules covering:

- **CRITICAL** (7 rules): OOMKilled, OutOfMemoryKill, NetworkPartition, ClusterQuorumRisk, DataCorruption, DatabaseFailover, SSLCertificateExpired
- **HIGH** (8 rules): ExceptionTraceback, HTTP5xx, ConnectionRefused, Timeout, CircuitBreakerOpen, RetryExhausted, CrashLoopBackOff, DiskSpaceCritical
- **MEDIUM** (5 rules): ErrorMessage, RedisError, KubernetesProbeFailed, ConsumerLag, MalformedResponse
- **LOW** (4 rules): WarningMessage, RetryAttempt, CircuitBreakerHalfOpen, MemoryThreshold, LatencyThreshold

Rules are evaluated in order; the first match wins. Custom rules can be added at runtime via `add_rule()`.

### `context_builder.py` — ContextBuilder + RollingBuffer

Maintains a bounded in-memory buffer of recent log lines per source (default 200 lines). When an incident is detected, extracts `before_count` preceding lines and `after_count` following lines as context.

- **`RollingBuffer`**: Async-safe deque-based buffer with per-source tracking.
- **`ContextBuilder`**: Wraps the buffer and provides `build_context()` for extracting surrounding lines around a detected incident.

### `models.py` — Data models

Lightweight frozen dataclasses:

- **`WatcherSeverity`**: Enum — LOW, MEDIUM, HIGH, CRITICAL.
- **`WatcherLogLine`**: Lightweight wrapper around raw log text with source and timestamp.
- **`IncidentEvent`**: Structured incident output containing service_name, severity, error_type, raw_line, context_lines, occurrence_count, and a stable SHA-256 `event_hash` fingerprint for deduplication.
- **`DetectionResult`**: Intermediate result from the detector (is_incident, severity, error_type).

## Usage

```python
from src.core.watcher import LogWatcher, WatcherSeverity
from src.core.log_sources.mock_file_source import MockFileLogSource
from src.config.settings import Settings

settings = Settings()
source = MockFileLogSource(settings)

watcher = LogWatcher(min_severity=WatcherSeverity.MEDIUM)

async for incident in watcher.watch(source):
    print(incident)
```

Or via CLI:

```bash
python -m src watch-logs --duration 15 --min-severity medium
python -m src watch-logs --dedup-ttl 600 --context-before 10 --context-after 5
```

## Configuration

Watcher behavior is controlled via constructor parameters (not exposed as environment variables):

| Parameter | Default | Description |
|---|---|---|
| `min_severity` | MEDIUM | Minimum severity to emit |
| `dedup_ttl` | 300s | Deduplication fingerprint TTL |
| `dedup_threshold` | 1 | Min occurrences before emitting |
| `context_before` | 5 | Preceding context lines |
| `context_after` | 3 | Following context lines |

These can be set via CLI flags (e.g., `python -m src watch-logs --min-severity high --dedup-ttl 600`) or programmatically when constructing a `LogWatcher`.
