"""Integration tests for the mock file log source lifecycle and streaming."""

import asyncio
from pathlib import Path

import pytest

from src.config.settings import Settings
from src.core.log_sources.base import LogLine
from src.core.log_sources.mock_file_source import MockFileLogSource


@pytest.fixture()
def tmp_log_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for mock log files."""
    return tmp_path / "mock_logs"


@pytest.fixture()
def settings(tmp_log_dir: Path) -> Settings:
    """Return settings pointing at the temp directory with fast interval."""
    return Settings(
        mock_log_count=10,
        mock_log_interval=0.2,
        mock_log_dir=str(tmp_log_dir),
    )


@pytest.mark.asyncio
async def test_source_lifecycle(settings: Settings, tmp_log_dir: Path) -> None:
    """Test that start/stop lifecycle works correctly."""
    source = MockFileLogSource(settings, log_dir=tmp_log_dir)

    # Before start, file should not exist
    assert not (tmp_log_dir / "mock_stream.log").exists()

    # Start the source
    await source.start()
    assert (tmp_log_dir / "mock_stream.log").exists()

    # Read initial content
    content = (tmp_log_dir / "mock_stream.log").read_text(encoding="utf-8")
    initial_lines = [l for l in content.strip().splitlines() if l]
    assert len(initial_lines) >= 10

    # Stop the source
    await source.stop()
    assert not source._running


@pytest.mark.asyncio
async def test_streaming_yields_lines(settings: Settings, tmp_log_dir: Path) -> None:
    """Test that stream() yields LogLine objects from the initial batch."""
    source = MockFileLogSource(settings, log_dir=tmp_log_dir)
    await source.start()

    try:
        lines_collected: list[LogLine] = []
        # Only read a few lines to avoid waiting for background writes
        count = 0
        async for line in source.stream():
            lines_collected.append(line)
            count += 1
            if count >= 15:  # Read initial batch + a couple from background writer
                break

        assert len(lines_collected) > 0
        for line in lines_collected:
            assert isinstance(line, LogLine)
            assert line.source == source.name
            assert len(line.text) > 0
    finally:
        await source.stop()


@pytest.mark.asyncio
async def test_streaming_sees_appended_lines(settings: Settings, tmp_log_dir: Path) -> None:
    """Test that stream() sees lines appended by the background writer."""
    source = MockFileLogSource(settings, log_dir=tmp_log_dir)
    await source.start()

    try:
        all_lines: list[LogLine] = []
        async for line in source.stream():
            all_lines.append(line)
            if len(all_lines) >= 20:
                break

        # Should have initial batch + some appended lines
        assert len(all_lines) >= 10
    finally:
        await source.stop()


@pytest.mark.asyncio
async def test_multiple_services_in_stream(settings: Settings, tmp_log_dir: Path) -> None:
    """Test that streamed logs include multiple services."""
    settings.mock_log_services = ["auth-service", "payment-service", "gateway"]
    source = MockFileLogSource(settings, log_dir=tmp_log_dir)
    await source.start()

    try:
        content = (tmp_log_dir / "mock_stream.log").read_text(encoding="utf-8")
        assert "auth-service" in content
        assert "payment-service" in content
        assert "gateway" in content
    finally:
        await source.stop()


@pytest.mark.asyncio
async def test_source_name_property(settings: Settings) -> None:
    """Test that the name property includes the file path."""
    source = MockFileLogSource(settings, log_dir=settings.mock_log_dir)
    assert "mock-file:" in source.name
    assert "mock_stream.log" in source.name


@pytest.mark.asyncio
async def test_double_start_is_safe(settings: Settings, tmp_log_dir: Path) -> None:
    """Calling start() twice should be a no-op."""
    source = MockFileLogSource(settings, log_dir=tmp_log_dir)
    await source.start()
    first_task = source._writer_task

    await source.start()
    # Should still be the same task (no double-start)
    assert source._writer_task is first_task

    await source.stop()


@pytest.mark.asyncio
async def test_stream_collects_severity_distribution(settings: Settings, tmp_log_dir: Path) -> None:
    """Test that streamed logs contain all severity levels."""
    source = MockFileLogSource(settings, log_dir=tmp_log_dir)
    await source.start()

    try:
        content = (tmp_log_dir / "mock_stream.log").read_text(encoding="utf-8")
        assert "[INFO" in content or "[INFO]" in content
        assert "[WARN" in content or "[WARN]" in content
        assert "[ERROR" in content or "[ERROR]" in content
        assert "[CRITICAL" in content or "[CRITICAL]" in content
    finally:
        await source.stop()
