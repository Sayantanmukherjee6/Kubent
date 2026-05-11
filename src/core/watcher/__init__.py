"""Log watcher pipeline — incident detection from streamed logs.

This package sits between log sources and future LLM analysis.  Its
responsibility is to:

1. Watch streamed logs from any ``BaseLogSource``
2. Detect incidents/errors using configurable regex rules
3. Collect surrounding context via a rolling buffer
4. Deduplicate noisy repeated events (in-memory)
5. Emit structured ``IncidentEvent`` objects for downstream consumers

Public API
----------

- ``LogWatcher`` — main orchestrator (async generator over log sources)
- ``IncidentEvent`` — structured incident output
- ``WatcherSeverity`` — severity levels (LOW, MEDIUM, HIGH, CRITICAL)
- ``LogDetector`` — regex-based error detection engine
- ``ContextBuilder`` — rolling buffer + context extraction
- ``RollingBuffer`` — bounded in-memory log line storage
- ``watch`` — convenience one-shot function

Example
-------

.. code-block:: python

    from src.core.log_sources.mock_file_source import MockFileLogSource
    from src.core.watcher import LogWatcher, WatcherSeverity
    from src.config.settings import Settings

    settings = Settings()
    source = MockFileLogSource(settings)

    watcher = LogWatcher(min_severity=WatcherSeverity.MEDIUM)
    async for incident in watcher.watch(source):
        print(incident)
"""

from src.core.watcher.context_builder import ContextBuilder, RollingBuffer
from src.core.watcher.detector import LogDetector, detect
from src.core.watcher.models import (
    DetectionResult,
    IncidentEvent,
    WatcherLogLine,
    WatcherSeverity,
)
from src.core.watcher.watcher import LogWatcher, watch

__all__ = [
    # Models
    "IncidentEvent",
    "WatcherLogLine",
    "WatcherSeverity",
    "DetectionResult",
    # Detector
    "LogDetector",
    "detect",
    # Context builder
    "ContextBuilder",
    "RollingBuffer",
    # Watcher
    "LogWatcher",
    "watch",
]
