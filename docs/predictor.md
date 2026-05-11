# Predictor Layer

Heuristic-based incident prediction engine. Deterministic, bounded-memory, no ML.

## Overview

`HeuristicPredictor` consumes `IncidentEvent` objects from the watcher pipeline and emits `PredictorEvent` predictions when recurring error patterns exceed configured thresholds within a rolling time window.

## Data Models

### `RiskLevel`

| Value    | Meaning                        |
|----------|--------------------------------|
| `low`    | Minor recurrence               |
| `medium` | Moderate recurrence            |
| `high`   | Significant pattern detected   |
| `critical` | Critical recurring failure   |

### `PredictorEvent`

| Field           | Type              | Description                          |
|-----------------|-------------------|--------------------------------------|
| `timestamp`     | `datetime` (UTC)  | When the prediction was made         |
| `service_name`  | `str`             | Kubernetes service at risk           |
| `risk_level`    | `RiskLevel`       | Predicted severity                   |
| `pattern`       | `str`             | Human-readable pattern description   |
| `trigger_count` | `int`             | Matching events in rolling window    |
| `related_hash`  | `str`             | SHA-256 fingerprint of related event |
| `metadata`      | `dict[str, str]`  | Optional extra key-value pairs       |

## Heuristic Rules

Each `HeuristicRule` defines:

| Field        | Type               | Description                          |
|--------------|--------------------|--------------------------------------|
| `name`       | `str`              | Unique rule identifier               |
| `patterns`   | `tuple[str, ...]`  | Substrings matched against `event_hash` |
| `threshold`  | `int`              | Occurrences in window to trigger     |
| `risk_level` | `RiskLevel`        | Predicted risk when triggered        |
| `description`| `str`              | Human-readable description           |

### Built-in Rules

| Rule Name               | Patterns Matched                        | Threshold | Risk Level |
|-------------------------|-----------------------------------------|-----------|------------|
| `repeated_http_5xx`     | `HTTP5xx`, `500 `, `502 `, `503 `, `504 ` | 3         | HIGH       |
| `repeated_timeout`      | `Timeout`, `timed out`, `deadline exceeded` | 3      | HIGH       |
| `repeated_oomkilled`    | `OOMKilled`, `OutOfMemoryKill`, `OOM`   | 2         | CRITICAL   |
| `repeated_conn_refused` | `ConnectionRefused`, `connection refused`, `ECONNREFUSED` | 3 | HIGH    |

Custom rules can be passed via the `rules` constructor parameter.

## Rolling Window Logic

- **Per-service**: Each Kubernetes service has its own `_ServiceWindow` instance.
- **Bounded deque**: Uses `collections.deque(maxlen=200)` — oldest entries are automatically evicted when the window is full.
- **Pattern matching**: For each incoming `IncidentEvent`, the engine pushes the event's `error_type` into the service's window, then counts how many entries match each rule's patterns (substring containment check).
- **Threshold check**: If any rule's count meets or exceeds its threshold, a `PredictorEvent` is emitted for that rule.
- **No expiry**: The window is size-bounded, not time-bounded — old events are evicted by count, not by timestamp.
- This simplified bounded-window approach is intentional for quick POC and deterministic behavior.

## Predictive Pipeline Flow

```
IncidentEvent (from watcher)
        │
        ▼
HeuristicPredictor.process()
        │
        ├── Acquire asyncio.Lock (async-safe)
        │
        ├── Ensure _ServiceWindow exists for service_name
        │
        ├── Push incident.error_type into rolling window
        │
        ├── For each HeuristicRule:
        │       └── Count matching entries in window
        │
        └── If count >= threshold:
                └── Emit PredictorEvent
```

### API

| Method                  | Description                              |
|-------------------------|------------------------------------------|
| `process(incident)`     | Process one `IncidentEvent`, return list of `PredictorEvent` |
| `reset_service(name)`   | Clear rolling window for a specific service |
| `reset_all()`           | Clear all rolling windows                |

## Design Constraints

- **Deterministic**: No randomness, no ML, no forecasting.
- **Bounded memory**: Fixed-size deque per service; no unbounded growth.
- **Async-safe**: All mutations protected by `asyncio.Lock`.
- **No external dependencies**: Uses only `asyncio`, `collections`, and `dataclasses`.
