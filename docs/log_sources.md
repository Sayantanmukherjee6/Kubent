# Log Sources

## Abstraction

All log sources implement `BaseLogSource` (`src/core/log_sources/base.py`):

```python
class BaseLogSource(ABC):
    @property
    def name(self) -> str: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def stream(self):  # async generator yielding LogLine
        ...
```

Consumers treat all sources uniformly:

```python
source: BaseLogSource = MockFileLogSource(settings)
await source.start()
async for log_line in source.stream():
    await analyzer.analyze(log_line.text)
await source.stop()
```

## Mock File Log Source

`MockFileLogSource` (`src/core/log_sources/mock_file_source.py`) is the default. It:

1. Writes an initial batch of mock logs on `start()`.
2. Appends new batches periodically via a background `asyncio.Task`.
3. Streams by tailing the file — reads new lines as they appear using file position tracking.

**Lifecycle:**
```python
source = MockFileLogSource(settings)
await source.start()       # Write initial batch + start background writer
async for line in source.stream():  # Tail file, yield LogLine objects
    print(line.text)
await source.stop()        # Cancel background task, clean up
```

**Features:** Handles file truncation (restarts from beginning if file shrinks), thread-safe via asyncio event loop, configurable write interval via `MOCK_LOG_INTERVAL`.

## Mock Log Generator

`mocks/generators/log_generator.py` produces realistic Kubernetes/Grafana-style logs.

**Services:** auth-service, payment-service, gateway, inventory-service, user-api, order-processor, notification-worker, cache-redis

**Severities & Messages:**
| Severity | Examples |
|---|---|
| INFO | `GET /api/v1/users 200 OK (12ms)`, `Health check passed — all dependencies healthy` |
| WARN | `Response time exceeded 500ms threshold`, `Connection pool utilization at 82%` |
| ERROR | `Connection refused to database host db-primary:5432`, `HTTP 503 from upstream service` |
| CRITICAL | `Out of memory: killed process 12345 (java)`, `Pod crash-looping: OOMKilled` |

**Realistic details:** Kubernetes pod names, full Python tracebacks on ERROR/CRITICAL, HTTP error codes, DB connection failures, retry attempts, OOM kills, circuit breaker states, realistic timestamps with jitter.

**API:**
```python
from mocks.generators.log_generator import (
    generate_log_entries,       # Returns list[LogEntry]
    generate_mock_logs_text,    # Returns multi-line string
    stream_log_entries,         # Async generator for real-time simulation
)

entries = generate_log_entries(count=100, services=["auth-service", "gateway"])
text = generate_mock_logs_text(count=50)

async for entry in stream_log_entries(count=50, interval=0.5):
    print(entry.format())
```

## Planned Sources (Future)

- `KubernetesLogSource` — tails `kubectl logs` or kubelet API
- `LokiLogSource` — queries Grafana Loki via HTTP API
- `PrometheusAlertSource` — ingests Prometheus alertmanager webhooks
