"""Watcher orchestrator — the main pipeline for incident detection.

Consumes ``BaseLogSource.stream()``, runs detection, builds context,
deduplicates noisy events, and yields structured ``IncidentEvent`` objects
as an async generator.

This module does NOT know about:
- LLMs or providers
- Remediation suggestions
- Dashboards
- Kubernetes integration (beyond consuming BaseLogSource)
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from src.core.log_sources.base import BaseLogSource, LogLine
from src.core.watcher.context_builder import ContextBuilder, RollingBuffer
from src.core.watcher.detector import LogDetector
from src.core.watcher.models import (
    IncidentEvent,
    WatcherLogLine,
    WatcherSeverity,
)


# ---------------------------------------------------------------------------
# Deduplication tracker — in-memory only, no Redis/DB
# ---------------------------------------------------------------------------

class _DedupTracker:
    """Tracks incident fingerprints for deduplication.

    Uses a simple in-memory dict mapping event_hash -> last_seen timestamp
    and occurrence count.  Expired entries are lazily cleaned up.

    Args:
        ttl_seconds:   How long to remember a fingerprint (default 300s).
        repeat_threshold: Minimum occurrences before emitting (default 1).
    """

    def __init__(self, ttl_seconds: float = 300.0, repeat_threshold: int = 1) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._threshold = repeat_threshold
        # hash -> {"count": int, "last_seen": datetime}
        self._entries: dict[str, dict[str, object]] = {}

    def record(self, event_hash: str, now: datetime | None = None) -> int:
        """Record an occurrence of *event_hash*.

        Returns the updated occurrence count.
        """
        ts = now or datetime.now(timezone.utc)
        if event_hash not in self._entries:
            self._entries[event_hash] = {"count": 0, "last_seen": ts}
        entry = self._entries[event_hash]
        entry["count"] += 1
        entry["last_seen"] = ts
        return entry["count"]

    def should_emit(self, event_hash: str, now: datetime | None = None) -> bool:
        """Check whether an incident with *event_hash* should be emitted.

        Returns True if the occurrence count meets the threshold and the
        fingerprint has not expired.
        """
        ts = now or datetime.now(timezone.utc)
        entry = self._entries.get(event_hash)
        if entry is None:
            return False
        # Check expiry
        last_seen = entry["last_seen"]  # type: ignore[assignment]
        if isinstance(last_seen, datetime) and (ts - last_seen) > self._ttl:
            return False
        return entry["count"] >= self._threshold  # type: ignore[return-value]

    def get_count(self, event_hash: str) -> int:
        """Get the current occurrence count for *event_hash*."""
        entry = self._entries.get(event_hash)
        if entry is None:
            return 0
        return entry["count"]  # type: ignore[return-value]

    def cleanup(self, now: datetime | None = None) -> int:
        """Remove expired entries. Returns number of entries removed."""
        ts = now or datetime.now(timezone.utc)
        expired = [
            h for h, e in self._entries.items()
            if isinstance(e["last_seen"], datetime) and (ts - e["last_seen"]) > self._ttl
        ]
        for h in expired:
            del self._entries[h]
        return len(expired)


# ---------------------------------------------------------------------------
# Service name extraction — lightweight heuristic
# ---------------------------------------------------------------------------

_POD_NAME_PATTERN = re.compile(
    r"pod/([a-z][a-z0-9-]*-[a-f0-9]{6,12})",
)

_ALT_SERVICE_PATTERN = re.compile(
    r"(?:^|\[.*?\]\s+)([a-z][a-z0-9-]*-[a-f0-9]{6,12})(?:\s|$|:)",
    re.IGNORECASE,
)


_POD_NAME_IN_CONTEXT_PATTERN = re.compile(
    r"pod/([a-z][a-z0-9-]*-[a-f0-9]{6,12})",
)


def _extract_service_name(text: str, source_hint: str = "", last_known: str | None = None,
                          context_lines: list[str] | None = None) -> str:
    """Heuristically extract a service name from a log line.

    Tries to match Kubernetes-style pod names (e.g. ``auth-service-5c8d7f9a2b``)
    appearing in the log text first.  Falls back to source_hint, then last_known.

    Args:
        text:           The raw log line text.
        source_hint:    Fallback name from the log source.
        last_known:     Previously extracted service name for this source (continuity).
        context_lines:  Optional surrounding context lines to search for pod names.

    Returns:
        A best-effort service name string.
    """
    # Try explicit "pod/<name>" pattern first (most reliable)
    match = _POD_NAME_PATTERN.search(text)
    if match:
        return match.group(1)

    # Try pod name embedded in log text (without "pod/" prefix)
    match = _ALT_SERVICE_PATTERN.search(text)
    if match:
        candidate = match.group(1)
        skip_words = {"line", "file", "from", "the", "and", "for", "with", "this"}
        if candidate.lower() not in skip_words:
            return candidate

    # Search context lines for a pod name (useful for traceback-first incidents)
    if context_lines:
        for ctx_line in context_lines:
            match = _POD_NAME_IN_CONTEXT_PATTERN.search(ctx_line)
            if match:
                return match.group(1)

    # Try bare service name from source hint (e.g. "pod/auth-service-5c8d")
    for part in source_hint.split("/"):
        if "-" in part and len(part) > 3 and part.lower() not in {"mock", "file", "logs"}:
            return part

    # Fall back to last known service name (for multi-line tracebacks etc.)
    if last_known is not None:
        return last_known

    return source_hint or "unknown"


# ---------------------------------------------------------------------------
# Watcher — the main orchestrator
# ---------------------------------------------------------------------------

class LogWatcher:
    """Orchestrates log watching, detection, context building, and deduplication.

    This is the primary entry point for the incident pipeline.  It consumes
    ``BaseLogSource.stream()`` (or any async iterable of ``LogLine``) and
    yields ``IncidentEvent`` objects as structured incidents are detected.

    Args:
        detector:         A ``LogDetector`` instance (creates a default one).
        context_builder:  A ``ContextBuilder`` instance (creates a default one).
        dedup_ttl:        Deduplication TTL in seconds (default 300).
        dedup_threshold:  Minimum occurrences before emitting (default 1).
        min_severity:     Minimum severity to emit (default MEDIUM).
        context_before:   Number of preceding context lines (default 5).
        context_after:    Number of following context lines (default 3).

    Example::

        watcher = LogWatcher(min_severity=WatcherSeverity.MEDIUM)
        async for incident in watcher.watch(source):
            print(incident)
    """

    def __init__(
        self,
        detector: LogDetector | None = None,
        context_builder: ContextBuilder | None = None,
        dedup_ttl: float = 300.0,
        dedup_threshold: int = 1,
        min_severity: WatcherSeverity = WatcherSeverity.MEDIUM,
        context_before: int = 5,
        context_after: int = 3,
    ) -> None:
        self._detector = detector or LogDetector()
        self._context_builder = context_builder or ContextBuilder(
            before_count=context_before,
            after_count=context_after,
        )
        self._dedup = _DedupTracker(
            ttl_seconds=dedup_ttl,
            repeat_threshold=dedup_threshold,
        )
        self._min_severity = min_severity
        self._line_counters: dict[str, int] = defaultdict(int)
        self._last_service: dict[str, str] = {}
        self._cleanup_counter: int = 0
        self._cleanup_interval: int = 100  # call cleanup() every N lines

    # -- public API ----------------------------------------------------------

    async def watch(self, source: BaseLogSource):
        """Consume a ``BaseLogSource`` and yield incident events.

        This is an async generator that runs until the source stops.

        Args:
            source: A ``BaseLogSource`` instance to watch.

        Yields:
            ``IncidentEvent`` objects for detected incidents.
        """
        await source.start()
        try:
            async for log_line in source.stream():
                self._cleanup_counter += 1
                if self._cleanup_counter % self._cleanup_interval == 0:
                    self._dedup.cleanup()
                async for incident in self._process_line(log_line):
                    yield incident
        finally:
            await source.stop()

    async def watch_lines(self, lines):
        """Consume an async iterable of ``LogLine`` objects and yield incidents.

        Convenience method when you already have a stream of log lines
        from any source (not just ``BaseLogSource``).

        Args:
            lines: An async iterable yielding ``LogLine`` objects.

        Yields:
            ``IncidentEvent`` objects for detected incidents.
        """
        async for log_line in lines:
            async for incident in self._process_line(log_line):
                yield incident

    @property
    def detector(self) -> LogDetector:
        """The underlying ``LogDetector`` instance."""
        return self._detector

    @property
    def context_builder(self) -> ContextBuilder:
        """The underlying ``ContextBuilder`` instance."""
        return self._context_builder

    # -- internal ------------------------------------------------------------

    async def _process_line(self, log_line: LogLine):
        """Process a single log line through the full pipeline.

        Steps:
            1. Add to rolling buffer (for context)
            2. Run detection rules
            3. If incident detected, build context window
            4. Check deduplication
            5. Emit structured ``IncidentEvent`` if all checks pass
        """
        # Step 1: Add to rolling buffer for context building
        await self._context_builder.add_line(log_line.source, log_line.text)

        # Track line index per source for precise context extraction
        source = log_line.source
        idx = self._line_counters[source]
        self._line_counters[source] += 1

        # Step 2: Run detection
        result = self._detector.detect(log_line.text)
        if not result.is_incident or result.severity is None:
            return

        # Step 3: Check minimum severity threshold
        if self._severity_rank(result.severity) < self._severity_rank(self._min_severity):
            return

        # Step 4: Build context window
        context = await self._context_builder.build_context(source, incident_line_index=idx)

        # Step 5: Extract service name
        # Track last known service name per source for multi-line logs
        if source not in self._last_service:
            self._last_service[source] = "unknown"
        service_name = _extract_service_name(
            log_line.text, log_line.source, self._last_service[source],
            context_lines=context.all_lines,
        )
        self._last_service[source] = service_name

        # Step 6: Create the incident event (without hash yet for dedup)
        now = datetime.now(timezone.utc)
        raw_event = IncidentEvent(
            timestamp=now,
            service_name=service_name,
            severity=result.severity,
            error_type=result.error_type,
            raw_line=log_line.text,
            context_lines=context.all_lines,
            source_name=log_line.source,
        )

        # Step 7: Deduplication check
        event_hash = raw_event.event_hash
        count = self._dedup.record(event_hash, now)

        if not self._dedup.should_emit(event_hash, now):
            return

        # Step 8: Emit the final incident event with updated occurrence count
        yield IncidentEvent(
            timestamp=raw_event.timestamp,
            service_name=raw_event.service_name,
            severity=raw_event.severity,
            error_type=raw_event.error_type,
            raw_line=raw_event.raw_line,
            context_lines=raw_event.context_lines,
            source_name=raw_event.source_name,
            occurrence_count=count,
            event_hash=event_hash,
        )

    @staticmethod
    def _severity_rank(severity: WatcherSeverity) -> int:
        """Convert a severity to a numeric rank for comparison."""
        return {
            WatcherSeverity.LOW: 0,
            WatcherSeverity.MEDIUM: 1,
            WatcherSeverity.HIGH: 2,
            WatcherSeverity.CRITICAL: 3,
        }[severity]


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

async def watch(source: BaseLogSource):
    """Quick one-shot watcher using default settings.

    Args:
        source: A ``BaseLogSource`` instance to watch.

    Yields:
        ``IncidentEvent`` objects for detected incidents.
    """
    watcher = LogWatcher()
    async for incident in watcher.watch(source):
        yield incident
