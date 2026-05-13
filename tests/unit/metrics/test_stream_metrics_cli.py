"""Tests for the stream-metrics CLI command.

Covers CLI command execution, mock metric streaming, folder metric streaming,
and duration handling.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from click.testing import CliRunner

from src.__main__ import cli
from src.core.metrics.models import MetricSample


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _make_sample(service: str = "test-service", cpu: float = 50.0, mem: float = 50.0,
                 latency: float = 100.0, error_rate: float = 0.01, source: str = "mock-metrics") -> MetricSample:
    """Create a MetricSample for testing."""
    return MetricSample(
        timestamp=datetime.now(timezone.utc),
        service_name=service,
        cpu_usage=cpu,
        memory_usage=mem,
        latency_ms=latency,
        error_rate=error_rate,
        source=source,
    )


def _make_mock_source(name: str = "mock-metrics:test", samples: list[MetricSample] | None = None) -> MagicMock:
    """Create a mock metric source that yields *samples*."""
    if samples is None:
        samples = [_make_sample()]

    mock_source = MagicMock()
    mock_source.name = name
    mock_source.start = AsyncMock()
    mock_source.stop = AsyncMock()

    async def mock_stream():
        for s in samples:
            yield s

    mock_source.stream = mock_stream
    return mock_source


# ---------------------------------------------------------------------------
# CLI command registration
# ---------------------------------------------------------------------------

class TestStreamMetricsCliRegistration:
    """Tests that the stream-metrics command is properly registered."""

    def test_command_exists(self, runner: CliRunner) -> None:
        """stream-metrics should be a registered CLI command."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "stream-metrics" in result.output

    def test_help_shows_options(self, runner: CliRunner) -> None:
        """stream-metrics --help should show available options."""
        result = runner.invoke(cli, ["stream-metrics", "--help"])
        assert result.exit_code == 0
        assert "--duration" in result.output
        assert "--source" in result.output
        assert "--metric-dir" in result.output


# ---------------------------------------------------------------------------
# Mock metric streaming
# ---------------------------------------------------------------------------

class TestStreamMetricsMockSource:
    """Tests for stream-metrics with mock metric source."""

    def test_mock_source_streams_samples(self, runner: CliRunner) -> None:
        """Should stream metric samples from mock source."""
        sample = _make_sample("test-service")
        mock_source = _make_mock_source("mock-metrics:test", [sample])

        with patch("src.core.metrics.factory.create_metric_source", return_value=mock_source):
            result = runner.invoke(cli, ["stream-metrics", "--duration", "1", "--source", "mock"])

        assert result.exit_code == 0
        assert "Streaming from" in result.output
        assert "Stopped. Received" in result.output
        assert "CPU=" in result.output
        assert "MEM=" in result.output

    def test_mock_source_shows_service_names(self, runner: CliRunner) -> None:
        """Output should include service names."""
        sample = _make_sample("auth-service")
        mock_source = _make_mock_source("mock-metrics:auth-service", [sample])

        with patch("src.core.metrics.factory.create_metric_source", return_value=mock_source):
            result = runner.invoke(cli, ["stream-metrics", "--duration", "1", "--source", "mock"])

        assert result.exit_code == 0
        assert "auth-service" in result.output

    def test_mock_source_shows_all_metric_fields(self, runner: CliRunner) -> None:
        """Output should include CPU, MEM, LAT, and ERR fields."""
        sample = _make_sample("test-svc", cpu=72.5, mem=68.0, latency=120.0, error_rate=0.015)
        mock_source = _make_mock_source("mock-metrics:test-svc", [sample])

        with patch("src.core.metrics.factory.create_metric_source", return_value=mock_source):
            result = runner.invoke(cli, ["stream-metrics", "--duration", "1", "--source", "mock"])

        assert result.exit_code == 0
        assert "CPU=" in result.output
        assert "MEM=" in result.output
        assert "LAT=" in result.output
        assert "ERR=" in result.output


# ---------------------------------------------------------------------------
# Folder metric streaming
# ---------------------------------------------------------------------------

class TestStreamMetricsFolderSource:
    """Tests for stream-metrics with folder metric source."""

    def test_folder_source_streams_csv_samples(self, runner: CliRunner) -> None:
        """Should stream metric samples from folder source."""
        sample = _make_sample("test-service", source="service.csv")
        mock_source = _make_mock_source("folder-metrics:/tmp/metrics", [sample])

        with patch("src.core.metrics.factory.create_metric_source", return_value=mock_source):
            result = runner.invoke(
                cli,
                ["stream-metrics", "--duration", "1", "--source", "folder", "--metric-dir", "/tmp/metrics"],
            )

        assert result.exit_code == 0
        assert "Streaming from" in result.output
        assert "test-service" in result.output
        assert "Stopped. Received" in result.output

    def test_folder_source_empty_directory(self, runner: CliRunner) -> None:
        """Should handle empty metric directory gracefully (no samples)."""
        mock_source = MagicMock()
        mock_source.name = "folder-metrics:/tmp/empty"
        mock_source.start = AsyncMock()
        mock_source.stop = AsyncMock()

        async def mock_stream():
            return
            yield  # Make this a generator

        mock_source.stream = mock_stream

        with patch("src.core.metrics.factory.create_metric_source", return_value=mock_source):
            result = runner.invoke(
                cli,
                ["stream-metrics", "--duration", "1", "--source", "folder", "--metric-dir", "/tmp/empty"],
            )

        assert result.exit_code == 0
        assert "Stopped. Received 0 metric samples" in result.output

    def test_folder_source_shows_folder_name(self, runner: CliRunner) -> None:
        """Source name should include the folder path."""
        sample = _make_sample("svc", source="app.csv")
        mock_source = _make_mock_source("folder-metrics:/custom/path", [sample])

        with patch("src.core.metrics.factory.create_metric_source", return_value=mock_source):
            result = runner.invoke(
                cli,
                ["stream-metrics", "--duration", "1", "--source", "folder", "--metric-dir", "/custom/path"],
            )

        assert result.exit_code == 0
        assert "folder-metrics:" in result.output


# ---------------------------------------------------------------------------
# Duration handling
# ---------------------------------------------------------------------------

class TestStreamMetricsDuration:
    """Tests for duration handling in stream-metrics."""

    def test_duration_zero_runs_briefly(self, runner: CliRunner) -> None:
        """Duration 0 should still run briefly (initial samples)."""
        sample = _make_sample()
        mock_source = _make_mock_source("mock-metrics", [sample])

        with patch("src.core.metrics.factory.create_metric_source", return_value=mock_source):
            result = runner.invoke(cli, ["stream-metrics", "--duration", "0", "--source", "mock"])

        assert result.exit_code == 0
        assert "Stopped. Received" in result.output

    def test_short_duration_stops_quickly(self, runner: CliRunner) -> None:
        """Short duration should complete quickly."""
        sample = _make_sample()
        mock_source = _make_mock_source("mock-metrics", [sample])

        with patch("src.core.metrics.factory.create_metric_source", return_value=mock_source):
            result = runner.invoke(cli, ["stream-metrics", "--duration", "1", "--source", "mock"])

        assert result.exit_code == 0
        assert "Stopped. Received" in result.output


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

class TestStreamMetricsOutputFormat:
    """Tests for the formatted output of stream-metrics."""

    def test_output_has_timestamp(self, runner: CliRunner) -> None:
        """Each line should have a timestamp in [HH:MM:SS] format."""
        sample = _make_sample("test-service", cpu=52.3, mem=55.0, latency=105.2)
        mock_source = _make_mock_source("mock-metrics", [sample])

        with patch("src.core.metrics.factory.create_metric_source", return_value=mock_source):
            result = runner.invoke(cli, ["stream-metrics", "--duration", "1", "--source", "mock"])

        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        metric_lines = [l for l in lines if "CPU=" in l]
        assert len(metric_lines) > 0
        for line in metric_lines:
            assert line.strip().startswith("["), f"Expected timestamp in: {line}"

    def test_output_has_separator_line(self, runner: CliRunner) -> None:
        """Output should include a separator line after header."""
        sample = _make_sample()
        mock_source = _make_mock_source("mock-metrics", [sample])

        with patch("src.core.metrics.factory.create_metric_source", return_value=mock_source):
            result = runner.invoke(cli, ["stream-metrics", "--duration", "1", "--source", "mock"])

        assert result.exit_code == 0
        assert "------" in result.output

    def test_output_shows_sample_count(self, runner: CliRunner) -> None:
        """Final output should show total sample count."""
        sample = _make_sample()
        mock_source = _make_mock_source("mock-metrics", [sample])

        with patch("src.core.metrics.factory.create_metric_source", return_value=mock_source):
            result = runner.invoke(cli, ["stream-metrics", "--duration", "1", "--source", "mock"])

        assert result.exit_code == 0
        assert "metric samples" in result.output


# ---------------------------------------------------------------------------
# Source override
# ---------------------------------------------------------------------------

class TestStreamMetricsSourceOverride:
    """Tests for --source and --metric-dir overrides."""

    def test_source_mock_explicit(self, runner: CliRunner) -> None:
        """Explicit --source mock should work."""
        sample = _make_sample()
        mock_source = _make_mock_source("mock-metrics:svc", [sample])

        with patch("src.core.metrics.factory.create_metric_source", return_value=mock_source):
            result = runner.invoke(cli, ["stream-metrics", "--duration", "1", "--source", "mock"])

        assert result.exit_code == 0
        assert "mock-metrics" in result.output

    def test_source_folder_with_metric_dir(self, runner: CliRunner) -> None:
        """--source folder with --metric-dir should use the specified directory."""
        sample = _make_sample("custom-svc", source="data.csv")
        mock_source = _make_mock_source("folder-metrics:/custom", [sample])

        with patch("src.core.metrics.factory.create_metric_source", return_value=mock_source):
            result = runner.invoke(
                cli,
                ["stream-metrics", "--duration", "1", "--source", "folder", "--metric-dir", "/custom"],
            )

        assert result.exit_code == 0
        assert "custom-svc" in result.output
