# Watcher Subsystem

The watcher subsystem monitors log streams for error patterns and triggers LLM analysis when thresholds are met. It operates as a background process that consumes from `BaseLogSource.stream()` and coordinates with the provider factory to route relevant logs for analysis.

## Key Concepts

- **Watchers** subscribe to log sources and apply configurable filters (severity, regex patterns, service names).
- **Analysis triggers** fire when conditions are met, sending log context to the LLM provider.
- **Results** are emitted as structured events containing `AnalysisResult` data.

## Usage

```python
from src.watcher import Watcher
from src.core.log_sources.base import BaseLogSource

source: BaseLogSource = MockFileLogSource(settings)
watcher = Watcher(source, settings)

await watcher.start()
# Watcher runs in background, emitting analysis events
await watcher.stop()
```

## Configuration

Watcher behavior is controlled via environment variables and `Settings`. See `.env.example` for available options.
