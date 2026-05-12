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
source: BaseLogSource = create_log_source(settings)
await source.start()
async for log_line in source.stream():
    await analyzer.analyze(log_line.text)
await source.stop()
```

## Source Factory

`create_log_source(settings)` (`src/core/log_sources/factory.py`) returns the configured source:

| `log_source.type` | Returns              | Description                        |
|-------------------|----------------------|------------------------------------|
| `"mock"`          | `MockFileLogSource`  | Generates synthetic K8s logs       |
| `"folder"`        | `FolderLogSource`    | Tails `*.log` files in a directory |

```python
from src.config.settings import Settings
from src.core.log_sources.factory import create_log_source

settings = Settings()
source = create_log_source(settings)  # Returns configured source type
```

**CLI usage:** All CLI commands (`stream-logs`, `watch-logs`, `predict`) use the factory.
Override source type and directory without modifying config:

```bash
python -m src stream-logs --source folder --log-dir /tmp/k8s-logs
python -m src watch-logs --source mock --log-dir /tmp/demo-logs
python -m src predict --source folder --log-dir /var/log/apps
```

## Configuration

```yaml
# config/config.yaml
log_source:
  type: mock                        # "mock" or "folder"
  folder_path: mocks/logs           # base directory for logs
```

Or via environment variables:

| Variable | Default | Description |
|---|---|---|
| `LOG_SOURCE_TYPE` | `mock` | Override log source type |
| `LOG_SOURCE_FOLDER_PATH` | `mocks/logs` | Override log directory |

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

## Folder Log Source

`FolderLogSource` (`src/core/log_sources/folder_source.py`) tails existing `*.log` files in a shared directory. Designed for ingesting logs produced by external processes (e.g. sidecar containers writing to a shared volume).

**Configuration:**
```yaml
log_source:
  type: folder
  folder_path: /tmp/k8s-shared-logs
```

**Expected folder layout:**
```
/tmp/k8s-shared-logs/
├── auth-service.log
├── payment-service.log
└── gateway.log
```
Only `*.log` files are watched. All other files are ignored.

**Lifecycle:**
```python
source = FolderLogSource(settings, folder_path="/tmp/k8s-shared-logs")
await source.start()       # Scan directory for *.log files
async for line in source.stream():  # Poll and yield new lines
    print(line.text)
await source.stop()
```

**Features:**
- Polling-based (no inotify/watchdog) — works on all platforms including macOS
- Per-file offset tracking — each `*.log` file is tracked independently
- Detects appended lines only — does not re-read already-consumed content
- Ignores non-`*.log` files — only files matching `*.log` are watched
- Handles missing/empty files gracefully — no crashes on file removal
- Discovers new files dynamically — files added after `start()` are picked up on the next poll
- Handles file truncation — if a file shrinks, offset resets to 0

**Single-consumer limitation:**
Only one `stream()` call may be active at a time. Calling `stream()` while
another iteration is in progress raises `RuntimeError`. This prevents
duplicate or missed lines from concurrent consumers.

**Logging behavior:**
Filesystem errors are logged at WARNING level using the standard `logging`
module. Errors that are logged include:
- Permission denied when reading a log file
- Permission denied when scanning the directory
- Failed `stat()` calls on tracked files
- Failed directory scans (e.g. directory removed between polls)

Configure logging to see these messages:
```python
import logging
logging.getLogger("src.core.log_sources.folder_source").setLevel(logging.WARNING)
logging.basicConfig(level=logging.WARNING)
```

## Mock Log Generator

`mocks/generators/log_generator.py` produces realistic Kubernetes/Grafana-style logs.

**Default Services:** auth-service, payment-service, gateway, inventory-service, user-api, order-processor (6 services by default, configurable via `MOCK_LOG_SERVICES` env var or `--services` CLI flag)

**Severities & Messages:**
| Severity | Examples |
|---|---|
| INFO | `GET /api/v1/users 200 OK (12ms)`, `Health check passed` |
| WARN | `Response time exceeded 500ms threshold`, `Connection pool utilization at 82%` |
| ERROR | `Connection refused to database host db-primary:5432`, `HTTP 503 from upstream` |
| CRITICAL | `Out of memory: killed process 12345 (java)`, `Pod crash-looping: OOMKilled` |

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
