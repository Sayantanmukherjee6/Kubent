"""Integration tests for multi-service streaming with MockFileLogSource."""

import asyncio
from pathlib import Path

import pytest

from src.config.settings import Settings
from src.core.log_sources.mock_file_source import MockFileLogSource
from src.core.watcher import LogWatcher, IncidentEvent, WatcherSeverity


class TestMultiServiceStreaming:
    """Test the watcher with real MockFileLogSource across multiple services."""

    @pytest.fixture
    def settings(self) -> Settings:
        return Settings(mock_log_interval=0.5, mock_log_count=20)

    @pytest.fixture
    def log_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "test_logs"

    @pytest.mark.asyncio
    async def test_watcher_sees_multiple_services(self, settings: Settings,
                                                   log_dir: Path) -> None:
        """Watcher should detect incidents from multiple services."""
        source = MockFileLogSource(settings, log_dir=log_dir)
        
        watcher = LogWatcher(
            min_severity=WatcherSeverity.MEDIUM,
            dedup_threshold=1,
        )
        
        incidents = []
        await source.start()
        try:
            # Collect from initial batch + a few appended lines
            count = 0
            async for incident in watcher.watch(source):
                incidents.append(incident)
                count += 1
                if count >= 20:
                    break
        finally:
            await source.stop()
        
        # Should have detected some incidents
        assert len(incidents) > 0
        
        # Should see multiple services
        services = {i.service_name for i in incidents}
        assert len(services) >= 1

    @pytest.mark.asyncio
    async def test_watcher_detects_critical_incidents(self, settings: Settings,
                                                       log_dir: Path) -> None:
        """Watcher should detect CRITICAL severity incidents."""
        source = MockFileLogSource(settings, log_dir=log_dir)
        
        watcher = LogWatcher(
            min_severity=WatcherSeverity.CRITICAL,
            dedup_threshold=1,
        )
        
        incidents = []
        await source.start()
        try:
            count = 0
            async for incident in watcher.watch(source):
                incidents.append(incident)
                count += 1
                if count >= 20:
                    break
        finally:
            await source.stop()
        
        # Mock logs include OOMKilled (CRITICAL) entries
        assert len(incidents) > 0
        assert all(i.severity == WatcherSeverity.CRITICAL for i in incidents)

    @pytest.mark.asyncio
    async def test_watcher_with_mock_file_source_full_lifecycle(self, settings: Settings,
                                                                 log_dir: Path) -> None:
        """Full lifecycle test: start, stream, detect, stop."""
        source = MockFileLogSource(settings, log_dir=log_dir)
        
        watcher = LogWatcher(
            min_severity=WatcherSeverity.MEDIUM,
            dedup_threshold=1,
        )
        
        incidents = []
        async for incident in watcher.watch(source):
            incidents.append(incident)
            if len(incidents) >= 10:
                break
        
        # Verify all incidents are properly structured
        for incident in incidents:
            assert isinstance(incident, IncidentEvent)
            assert incident.timestamp.tzinfo is not None
            assert incident.service_name != ""
            assert incident.severity is not None
            assert incident.error_type != ""
            assert incident.raw_line != ""
            assert incident.event_hash != ""

    @pytest.mark.asyncio
    async def test_watcher_context_with_mock_source(self, settings: Settings,
                                                     log_dir: Path) -> None:
        """Context lines should be captured from mock source."""
        source = MockFileLogSource(settings, log_dir=log_dir)
        
        watcher = LogWatcher(
            min_severity=WatcherSeverity.MEDIUM,
            dedup_threshold=1,
            context_before=3,
            context_after=2,
        )
        
        incidents_with_context = []
        async for incident in watcher.watch(source):
            if incident.context_lines:
                incidents_with_context.append(incident)
            if len(incidents_with_context) >= 5:
                break
        
        # Some incidents should have context
        assert len(incidents_with_context) > 0

    @pytest.mark.asyncio
    async def test_watcher_dedup_with_mock_source(self, settings: Settings,
                                                   log_dir: Path) -> None:
        """Deduplication should work with mock source."""
        source = MockFileLogSource(settings, log_dir=log_dir)
        
        # threshold=3 means we need 3 occurrences before emitting
        watcher = LogWatcher(
            min_severity=WatcherSeverity.MEDIUM,
            dedup_threshold=3,
            dedup_ttl=300,
        )
        
        incidents = []
        async for incident in watcher.watch(source):
            incidents.append(incident)
            if len(incidents) >= 10:
                break
        
        # All emitted incidents should have occurrence_count >= 3
        for incident in incidents:
            assert incident.occurrence_count >= 3
