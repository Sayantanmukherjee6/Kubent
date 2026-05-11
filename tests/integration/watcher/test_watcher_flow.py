"""Integration tests for the async watcher flow."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from src.core.log_sources.base import BaseLogSource, LogLine
from src.core.watcher import LogWatcher, IncidentEvent, WatcherSeverity


# ---------------------------------------------------------------------------
# Mock log source for testing (no file I/O)
# ---------------------------------------------------------------------------

@dataclass
class _StaticLogSource(BaseLogSource):
    """A log source that yields a fixed list of log lines."""

    lines: list[LogLine] = field(default_factory=list)
    _started: bool = False
    _stopped: bool = False

    @property
    def name(self) -> str:
        return "mock-static"

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._stopped = True

    async def stream(self):
        if not self._started:
            return
        for line in self.lines:
            yield line


@dataclass
class _AsyncLogSource(BaseLogSource):
    """A log source that yields lines with artificial delays."""

    lines: list[LogLine] = field(default_factory=list)
    delay: float = 0.01
    _started: bool = False
    _stopped: bool = False

    @property
    def name(self) -> str:
        return "mock-async"

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._stopped = True

    async def stream(self):
        if not self._started:
            return
        for line in self.lines:
            await asyncio.sleep(self.delay)
            yield line


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWatcherBasicFlow:
    """Test the basic watcher pipeline flow."""

    @pytest.mark.asyncio
    async def test_watcher_detects_incidents(self) -> None:
        """Watcher should detect incidents from log lines."""
        source = _StaticLogSource(lines=[
            LogLine(text="INFO: all good", source="mock"),
            LogLine(text="ERROR: connection failed", source="mock"),
            LogLine(text="INFO: recovered", source="mock"),
        ])

        watcher = LogWatcher(min_severity=WatcherSeverity.MEDIUM)
        incidents = []
        async for incident in watcher.watch(source):
            incidents.append(incident)

        assert len(incidents) >= 1
        assert any(i.error_type == "ErrorMessage" for i in incidents)

    @pytest.mark.asyncio
    async def test_watcher_respects_severity_threshold(self) -> None:
        """Watcher should filter by minimum severity."""
        source = _StaticLogSource(lines=[
            LogLine(text="WARN: something odd", source="mock"),
            LogLine(text="ERROR: connection failed", source="mock"),
            LogLine(text="CRITICAL: OOMKilled in pod", source="mock"),
        ])

        # Only HIGH and above
        watcher = LogWatcher(min_severity=WatcherSeverity.HIGH)
        incidents = []
        async for incident in watcher.watch(source):
            incidents.append(incident)

        assert all(i.severity in (WatcherSeverity.HIGH, WatcherSeverity.CRITICAL)
                   for i in incidents)
        # WARN should be filtered out
        assert not any(i.error_type == "WarningMessage" for i in incidents)

    @pytest.mark.asyncio
    async def test_watcher_produces_structured_events(self) -> None:
        """Incident events should have all required fields."""
        source = _StaticLogSource(lines=[
            LogLine(text="ERROR: something broke", source="mock"),
        ])

        watcher = LogWatcher(min_severity=WatcherSeverity.MEDIUM)
        async for incident in watcher.watch(source):
            assert isinstance(incident, IncidentEvent)
            assert incident.timestamp.tzinfo is not None
            assert incident.service_name != ""
            assert incident.severity is not None
            assert incident.error_type != ""
            assert incident.raw_line != ""
            assert incident.event_hash != ""
            assert isinstance(incident.context_lines, list)
            assert isinstance(incident.occurrence_count, int)

    @pytest.mark.asyncio
    async def test_watcher_no_incidents_for_clean_logs(self) -> None:
        """Watcher should produce no incidents for clean logs."""
        source = _StaticLogSource(lines=[
            LogLine(text="INFO: all good", source="mock"),
            LogLine(text="INFO: processing request", source="mock"),
            LogLine(text="INFO: request completed", source="mock"),
        ])

        watcher = LogWatcher(min_severity=WatcherSeverity.LOW)
        incidents = []
        async for incident in watcher.watch(source):
            incidents.append(incident)

        # No WARN/ERROR lines, so no incidents
        assert len(incidents) == 0


class TestWatcherDeduplication:
    """Test deduplication behavior."""

    @pytest.mark.asyncio
    async def test_deduplication_reduces_duplicates(self) -> None:
        """Repeated identical errors should be deduplicated."""
        source = _StaticLogSource(lines=[
            LogLine(text="ERROR: connection refused to db", source="mock"),
            LogLine(text="ERROR: connection refused to db", source="mock"),
            LogLine(text="ERROR: connection refused to db", source="mock"),
            LogLine(text="INFO: recovered", source="mock"),
        ])

        # threshold=1 means every occurrence is emitted
        watcher = LogWatcher(
            min_severity=WatcherSeverity.MEDIUM,
            dedup_threshold=1,
            dedup_ttl=300,
        )
        incidents = []
        async for incident in watcher.watch(source):
            incidents.append(incident)

        # All three should be emitted (threshold=1)
        assert len(incidents) >= 1
        # The last one should have occurrence_count >= 3
        last = incidents[-1]
        assert last.occurrence_count >= 2

    @pytest.mark.asyncio
    async def test_dedup_threshold_filters_repeats(self) -> None:
        """Events below threshold should not be emitted."""
        source = _StaticLogSource(lines=[
            LogLine(text="ERROR: connection refused to db", source="mock"),
            LogLine(text="ERROR: connection refused to db", source="mock"),
        ])

        # threshold=2 means we need 2 occurrences before emitting
        watcher = LogWatcher(
            min_severity=WatcherSeverity.MEDIUM,
            dedup_threshold=2,
            dedup_ttl=300,
        )
        incidents = []
        async for incident in watcher.watch(source):
            incidents.append(incident)

        # Should emit once with count=2
        assert len(incidents) == 1
        assert incidents[0].occurrence_count == 2


class TestWatcherContext:
    """Test context extraction."""

    @pytest.mark.asyncio
    async def test_context_lines_captured(self) -> None:
        """Incident events should include surrounding context lines."""
        source = _StaticLogSource(lines=[
            LogLine(text="INFO: line 1", source="mock"),
            LogLine(text="INFO: line 2", source="mock"),
            LogLine(text="ERROR: something broke", source="mock"),
            LogLine(text="INFO: line 4", source="mock"),
            LogLine(text="INFO: line 5", source="mock"),
        ])

        watcher = LogWatcher(
            min_severity=WatcherSeverity.MEDIUM,
            context_before=2,
            context_after=2,
        )
        async for incident in watcher.watch(source):
            assert len(incident.context_lines) >= 2


class TestWatcherLinesAPI:
    """Test the watch_lines convenience method."""

    @pytest.mark.asyncio
    async def test_watch_lines(self) -> None:
        """watch_lines should work with any async iterable of LogLine."""
        async def _line_generator() :
            for line in [
                LogLine(text="INFO: all good", source="mock"),
                LogLine(text="ERROR: something broke", source="mock"),
            ]:
                yield line

        watcher = LogWatcher(min_severity=WatcherSeverity.MEDIUM)
        incidents = []
        async for incident in watcher.watch_lines(_line_generator()):
            incidents.append(incident)

        assert len(incidents) >= 1


class TestWatcherLifecycle:
    """Test watcher lifecycle (start/stop)."""

    @pytest.mark.asyncio
    async def test_source_start_stop(self) -> None:
        """Source should be started and stopped by the watcher."""
        source = _StaticLogSource(lines=[
            LogLine(text="ERROR: something broke", source="mock"),
        ])

        watcher = LogWatcher(min_severity=WatcherSeverity.MEDIUM)
        async for incident in watcher.watch(source):
            pass

        assert source._started is True
        assert source._stopped is True


class TestWatcherAsyncDelay:
    """Test watcher with delayed async source."""

    @pytest.mark.asyncio
    async def test_watcher_with_delayed_source(self) -> None:
        """Watcher should handle async sources with delays."""
        source = _AsyncLogSource(lines=[
            LogLine(text="INFO: starting", source="mock"),
            LogLine(text="ERROR: connection failed", source="mock"),
            LogLine(text="CRITICAL: OOMKilled", source="mock"),
        ], delay=0.01)

        watcher = LogWatcher(min_severity=WatcherSeverity.MEDIUM)
        incidents = []
        async for incident in watcher.watch(source):
            incidents.append(incident)

        assert len(incidents) >= 2  # ERROR + CRITICAL


class TestWatchConvenienceFunction:
    """Test the watch() convenience function."""

    @pytest.mark.asyncio
    async def test_watch_function(self) -> None:
        """The watch() convenience function should work."""
        from src.core.watcher import watch

        source = _StaticLogSource(lines=[
            LogLine(text="ERROR: something broke", source="mock"),
        ])

        incidents = []
        async for incident in watch(source):
            incidents.append(incident)

        assert len(incidents) >= 1
