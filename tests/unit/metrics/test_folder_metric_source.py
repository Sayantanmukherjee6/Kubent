"""Unit tests for FolderMetricSource and CSV metric parsing."""

import asyncio
from pathlib import Path

import pytest

from src.config.settings import Settings
from src.core.metrics.folder_metric_source import FolderMetricSource
from src.core.metrics.factory import create_metric_source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_csv_file(folder: Path, filename: str, content: str) -> None:
    """Write *content* to a *.csv file in *folder*."""
    (folder / filename).write_text(content, encoding="utf-8")


def _append_to_csv_file(folder: Path, filename: str, content: str) -> None:
    """Append *content* to an existing *.csv file in *folder*."""
    with open(folder / filename, "a", encoding="utf-8") as f:
        f.write(content)


async def _collect_samples(source, max_samples: int = 10, timeout: float = 2.0):
    """Collect up to *max_samples* from *source.stream()*, with a *timeout*."""
    collected = []
    gen = source.stream()

    async def _gather():
        async for sample in gen:
            collected.append(sample)
            if len(collected) >= max_samples:
                return

    try:
        await asyncio.wait_for(_gather(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        await gen.aclose()
    return collected


@pytest.fixture()
def tmp_metrics_folder(tmp_path: Path) -> Path:
    """Provide a temporary directory for folder metric source tests."""
    return tmp_path / "demo_metrics"


@pytest.fixture()
def settings(tmp_metrics_folder: Path) -> Settings:
    """Return settings pointing at the temp folder with fast polling."""
    s = Settings(
        metrics_source_type="folder",
        metrics_folder_path=str(tmp_metrics_folder),
    )
    FolderMetricSource.POLL_INTERVAL = 0.1
    return s


@pytest.fixture(autouse=True)
def _restore_poll_interval():
    """Restore default POLL_INTERVAL after each test."""
    yield
    FolderMetricSource.POLL_INTERVAL = 0.5


# ---------------------------------------------------------------------------
# CSV Parsing Tests
# ---------------------------------------------------------------------------

class TestCsvParsing:
    """Tests for CSV metric line parsing."""

    def test_parse_valid_line(self) -> None:
        """Should parse a valid CSV metric line."""
        line = "2026-01-01T10:00:00Z,payment-service,72,68,120,0.01"
        sample = FolderMetricSource._parse_csv_line(line, "test.csv")
        assert sample is not None
        assert sample.service_name == "payment-service"
        assert sample.cpu_usage == 72.0
        assert sample.memory_usage == 68.0
        assert sample.latency_ms == 120.0
        assert sample.error_rate == 0.01
        assert sample.source == "test.csv"

    def test_parse_line_with_spaces(self) -> None:
        """Should handle spaces around fields."""
        line = " 2026-01-01T10:00:00Z , payment-service , 72 , 68 , 120 , 0.01 "
        sample = FolderMetricSource._parse_csv_line(line, "test.csv")
        assert sample is not None
        assert sample.service_name == "payment-service"

    def test_parse_invalid_field_count(self) -> None:
        """Should return None for lines with wrong field count."""
        line = "2026-01-01T10:00:00Z,payment-service,72"
        sample = FolderMetricSource._parse_csv_line(line, "test.csv")
        assert sample is None

    def test_parse_invalid_timestamp(self) -> None:
        """Should return None for invalid timestamps."""
        line = "not-a-date,payment-service,72,68,120,0.01"
        sample = FolderMetricSource._parse_csv_line(line, "test.csv")
        assert sample is None

    def test_parse_invalid_numbers(self) -> None:
        """Should return None for non-numeric metric values."""
        line = "2026-01-01T10:00:00Z,payment-service,abc,68,120,0.01"
        sample = FolderMetricSource._parse_csv_line(line, "test.csv")
        assert sample is None

    def test_parse_empty_string(self) -> None:
        """Should return None for empty strings."""
        sample = FolderMetricSource._parse_csv_line("", "test.csv")
        assert sample is None

    def test_parse_with_z_suffix(self) -> None:
        """Should handle ISO 8601 timestamps with Z suffix."""
        line = "2026-01-01T10:00:00Z,svc,50,50,100,0.0"
        sample = FolderMetricSource._parse_csv_line(line, "test.csv")
        assert sample is not None
        assert sample.timestamp.tzinfo is not None

    def test_parse_with_offset_suffix(self) -> None:
        """Should handle ISO 8601 timestamps with offset."""
        line = "2026-01-01T10:00:00+00:00,svc,50,50,100,0.0"
        sample = FolderMetricSource._parse_csv_line(line, "test.csv")
        assert sample is not None


# ---------------------------------------------------------------------------
# FolderMetricSource — basic lifecycle
# ---------------------------------------------------------------------------

class TestFolderMetricSourceLifecycle:
    """Tests for start/stop and name property."""

    @pytest.mark.asyncio
    async def test_name_property(self, tmp_metrics_folder: Path, settings: Settings) -> None:
        source = FolderMetricSource(settings, folder_path=tmp_metrics_folder)
        assert source.name == f"folder-metrics:{tmp_metrics_folder}"

    @pytest.mark.asyncio
    async def test_start_creates_running_state(self, tmp_metrics_folder: Path, settings: Settings) -> None:
        tmp_metrics_folder.mkdir(parents=True, exist_ok=True)
        source = FolderMetricSource(settings, folder_path=tmp_metrics_folder)
        await source.start()
        assert source._running is True
        await source.stop()

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, tmp_metrics_folder: Path, settings: Settings) -> None:
        tmp_metrics_folder.mkdir(parents=True, exist_ok=True)
        source = FolderMetricSource(settings, folder_path=tmp_metrics_folder)
        await source.start()
        await source.stop()
        assert source._running is False

    @pytest.mark.asyncio
    async def test_nonexistent_folder_raises(self, settings: Settings) -> None:
        bad_path = Path("/nonexistent/path/that/does/not/exist")
        source = FolderMetricSource(settings, folder_path=bad_path)
        with pytest.raises(FileNotFoundError):
            await source.start()

    @pytest.mark.asyncio
    async def test_file_instead_of_folder_raises(self, tmp_path: Path, settings: Settings) -> None:
        not_a_dir = tmp_path / "not_a_dir.csv"
        not_a_dir.write_text("data", encoding="utf-8")
        source = FolderMetricSource(settings, folder_path=not_a_dir)
        with pytest.raises(NotADirectoryError):
            await source.start()


# ---------------------------------------------------------------------------
# FolderMetricSource — multi-file tailing
# ---------------------------------------------------------------------------

class TestFolderMetricSourceMultiFile:
    """Tests for tailing multiple *.csv files simultaneously."""

    @pytest.mark.asyncio
    async def test_tails_multiple_csv_files(self, tmp_metrics_folder: Path, settings: Settings) -> None:
        tmp_metrics_folder.mkdir(parents=True, exist_ok=True)
        _write_csv_file(tmp_metrics_folder, "auth-service.csv",
                        "2026-01-01T10:00:00Z,auth-service,70,65,110,0.02\n"
                        "2026-01-01T10:01:00Z,auth-service,72,67,115,0.03\n")
        _write_csv_file(tmp_metrics_folder, "payment-service.csv",
                        "2026-01-01T10:00:00Z,payment-service,60,55,90,0.01\n")

        source = FolderMetricSource(settings, folder_path=tmp_metrics_folder)
        await source.start()

        samples = await _collect_samples(source, max_samples=3, timeout=2.0)

        await source.stop()

        service_names = {s.service_name for s in samples}
        assert "auth-service" in service_names
        assert "payment-service" in service_names

    @pytest.mark.asyncio
    async def test_ignores_non_csv_files(self, tmp_metrics_folder: Path, settings: Settings) -> None:
        tmp_metrics_folder.mkdir(parents=True, exist_ok=True)
        _write_csv_file(tmp_metrics_folder, "metrics.csv",
                        "2026-01-01T10:00:00Z,svc,50,50,100,0.01\n")
        (tmp_metrics_folder / "app.log").write_text("[ERROR] should be ignored\n", encoding="utf-8")
        (tmp_metrics_folder / "app.txt").write_text("should also be ignored\n", encoding="utf-8")

        source = FolderMetricSource(settings, folder_path=tmp_metrics_folder)
        await source.start()

        samples = await _collect_samples(source, max_samples=2, timeout=2.0)

        await source.stop()

        assert len(samples) == 1
        assert samples[0].service_name == "svc"

    @pytest.mark.asyncio
    async def test_empty_directory(self, tmp_metrics_folder: Path, settings: Settings) -> None:
        tmp_metrics_folder.mkdir(parents=True, exist_ok=True)
        source = FolderMetricSource(settings, folder_path=tmp_metrics_folder)
        await source.start()

        samples = await _collect_samples(source, max_samples=1, timeout=1.0)

        await source.stop()
        assert len(samples) == 0


# ---------------------------------------------------------------------------
# FolderMetricSource — appended lines & offset tracking
# ---------------------------------------------------------------------------

class TestFolderMetricSourceAppends:
    """Tests for detecting appended lines and offset tracking."""

    @pytest.mark.asyncio
    async def test_sees_appended_lines(self, tmp_metrics_folder: Path, settings: Settings) -> None:
        tmp_metrics_folder.mkdir(parents=True, exist_ok=True)
        _write_csv_file(tmp_metrics_folder, "app.csv",
                        "2026-01-01T10:00:00Z,svc-a,50,50,100,0.01\n")

        source = FolderMetricSource(settings, folder_path=tmp_metrics_folder)
        await source.start()

        samples = await _collect_samples(source, max_samples=1, timeout=2.0)

        assert len(samples) == 1
        assert samples[0].service_name == "svc-a"
        assert samples[0].cpu_usage == 50.0

        # Append a new line
        _append_to_csv_file(tmp_metrics_folder, "app.csv",
                            "2026-01-01T10:01:00Z,svc-a,55,53,110,0.02\n")

        # Collect the appended line with a fresh stream iteration
        more_samples = await _collect_samples(source, max_samples=1, timeout=2.0)

        await source.stop()

        assert len(more_samples) == 1
        assert more_samples[0].cpu_usage == 55.0

    @pytest.mark.asyncio
    async def test_offset_tracking_multiple_files(self, tmp_metrics_folder: Path, settings: Settings) -> None:
        """Offsets should be tracked independently per file."""
        tmp_metrics_folder.mkdir(parents=True, exist_ok=True)
        _write_csv_file(tmp_metrics_folder, "a.csv",
                        "2026-01-01T10:00:00Z,svc-a,50,50,100,0.01\n"
                        "2026-01-01T10:01:00Z,svc-a,52,51,105,0.02\n")
        _write_csv_file(tmp_metrics_folder, "b.csv",
                        "2026-01-01T10:00:00Z,svc-b,60,55,90,0.01\n"
                        "2026-01-01T10:01:00Z,svc-b,62,57,95,0.02\n")

        source = FolderMetricSource(settings, folder_path=tmp_metrics_folder)
        await source.start()

        samples = await _collect_samples(source, max_samples=4, timeout=2.0)

        await source.stop()

        service_names = {s.service_name for s in samples}
        assert "svc-a" in service_names
        assert "svc-b" in service_names

    @pytest.mark.asyncio
    async def test_file_truncation_resets_offset(self, tmp_metrics_folder: Path, settings: Settings) -> None:
        """When a file is truncated, the source should restart from the beginning."""
        tmp_metrics_folder.mkdir(parents=True, exist_ok=True)
        _write_csv_file(tmp_metrics_folder, "app.csv",
                        "2026-01-01T10:00:00Z,svc,50,50,100,0.01\n"
                        "2026-01-01T10:01:00Z,svc,51,51,101,0.01\n")

        source = FolderMetricSource(settings, folder_path=tmp_metrics_folder)
        await source.start()

        samples = await _collect_samples(source, max_samples=2, timeout=2.0)
        assert len(samples) == 2

        # Truncate and rewrite
        _write_csv_file(tmp_metrics_folder, "app.csv",
                        "2026-01-01T11:00:00Z,svc,99,99,500,0.10\n")

        more_samples = await _collect_samples(source, max_samples=1, timeout=2.0)

        await source.stop()

        assert len(more_samples) == 1
        assert more_samples[0].cpu_usage == 99.0


# ---------------------------------------------------------------------------
# FolderMetricSource — single-consumer protection
# ---------------------------------------------------------------------------

class TestFolderMetricSourceSingleConsumer:
    """Tests that only one stream() call may be active at a time."""

    @pytest.mark.asyncio
    async def test_concurrent_stream_raises_runtime_error(
        self, tmp_metrics_folder: Path, settings: Settings
    ) -> None:
        tmp_metrics_folder.mkdir(parents=True, exist_ok=True)
        _write_csv_file(tmp_metrics_folder, "app.csv",
                        "2026-01-01T10:00:00Z,svc,50,50,100,0.01\n")

        source = FolderMetricSource(settings, folder_path=tmp_metrics_folder)
        await source.start()

        gen1 = source.stream()
        sample1 = await gen1.__anext__()
        assert sample1.service_name == "svc"

        gen2 = source.stream()
        with pytest.raises(RuntimeError, match="already has an active stream"):
            await gen2.__anext__()

        await gen1.aclose()
        await source.stop()


# ---------------------------------------------------------------------------
# Source Factory — metrics
# ---------------------------------------------------------------------------

class TestCreateMetricSourceFactory:
    """Tests for the create_metric_source factory function."""

    def test_mock_type_returns_mock_source(self, tmp_path: Path) -> None:
        settings = Settings(metrics_source_type="mock")
        source = create_metric_source(settings)
        from src.core.metrics.mock_metric_source import MockMetricSource
        assert isinstance(source, MockMetricSource)

    def test_folder_type_returns_folder_source(self, tmp_path: Path) -> None:
        settings = Settings(
            metrics_source_type="folder",
            metrics_folder_path=str(tmp_path),
        )
        source = create_metric_source(settings)
        assert isinstance(source, FolderMetricSource)

    def test_unknown_type_raises_value_error(self) -> None:
        settings = Settings()
        object.__setattr__(settings.metrics.source, "type", "prometheus")
        with pytest.raises(ValueError, match="Unknown metrics.source.type"):
            create_metric_source(settings)

    def test_folder_path_override(self, tmp_path: Path) -> None:
        """folder_path argument should override settings value."""
        other_path = tmp_path / "other"
        other_path.mkdir(parents=True, exist_ok=True)
        settings = Settings(
            metrics_source_type="folder",
            metrics_folder_path=str(tmp_path),
        )
        source = create_metric_source(settings, folder_path=str(other_path))
        assert isinstance(source, FolderMetricSource)
        assert str(other_path) in source.name

    def test_default_type_is_mock(self) -> None:
        """When type is not set, default should be 'mock'."""
        settings = Settings()
        source = create_metric_source(settings)
        from src.core.metrics.mock_metric_source import MockMetricSource
        assert isinstance(source, MockMetricSource)


# ---------------------------------------------------------------------------
# Integration — FolderMetricSource with MetricSample contract
# ---------------------------------------------------------------------------

class TestFolderMetricSourceContract:
    """Tests that FolderMetricSource satisfies the BaseMetricSource contract."""

    @pytest.mark.asyncio
    async def test_sample_source_property(self, tmp_metrics_folder: Path, settings: Settings) -> None:
        """Every MetricSample should have source matching the file name."""
        tmp_metrics_folder.mkdir(parents=True, exist_ok=True)
        _write_csv_file(tmp_metrics_folder, "app.csv",
                        "2026-01-01T10:00:00Z,svc,50,50,100,0.01\n")

        source = FolderMetricSource(settings, folder_path=tmp_metrics_folder)
        await source.start()

        samples = await _collect_samples(source, max_samples=1, timeout=2.0)

        await source.stop()

        assert len(samples) == 1
        assert samples[0].source == "app.csv"

    @pytest.mark.asyncio
    async def test_sample_timestamp_parsed(self, tmp_metrics_folder: Path, settings: Settings) -> None:
        """Timestamps should be parsed from CSV data."""
        tmp_metrics_folder.mkdir(parents=True, exist_ok=True)
        _write_csv_file(tmp_metrics_folder, "app.csv",
                        "2026-01-01T15:30:45Z,svc,50,50,100,0.01\n")

        source = FolderMetricSource(settings, folder_path=tmp_metrics_folder)
        await source.start()

        samples = await _collect_samples(source, max_samples=1, timeout=2.0)

        await source.stop()

        assert len(samples) == 1
        assert samples[0].timestamp.year == 2026
        assert samples[0].timestamp.month == 1
        assert samples[0].timestamp.day == 1
        assert samples[0].timestamp.hour == 15
        assert samples[0].timestamp.minute == 30
        assert samples[0].timestamp.second == 45
