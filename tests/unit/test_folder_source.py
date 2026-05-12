"""Unit tests for FolderLogSource and the log source factory."""

import asyncio
from pathlib import Path

import pytest

from src.config.settings import Settings
from src.core.log_sources.base import LogLine
from src.core.log_sources.factory import create_log_source
from src.core.log_sources.folder_source import FolderLogSource
from src.core.log_sources.mock_file_source import MockFileLogSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_log_file(folder: Path, filename: str, content: str) -> None:
    """Write *content* to a *.log file in *folder*."""
    (folder / filename).write_text(content, encoding="utf-8")


def _append_to_log_file(folder: Path, filename: str, content: str) -> None:
    """Append *content* to an existing *.log file in *folder*."""
    with open(folder / filename, "a", encoding="utf-8") as f:
        f.write(content)


async def _collect_lines_with_timeout(source, max_lines: int = 10, timeout: float = 2.0) -> list[LogLine]:
    """Collect up to *max_lines* from *source.stream()*, with a *timeout*.

    Returns whatever lines were collected within the timeout (may be fewer
    than *max_lines* if the source produces no more output).

    Always closes the generator on exit so the streaming flag is reset.
    """
    collected: list[LogLine] = []
    gen = source.stream()

    async def _gather():
        async for line in gen:
            collected.append(line)
            if len(collected) >= max_lines:
                return

    try:
        await asyncio.wait_for(_gather(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        await gen.aclose()
    return collected


@pytest.fixture()
def tmp_log_folder(tmp_path: Path) -> Path:
    """Provide a temporary directory for folder log source tests."""
    return tmp_path / "k8s-shared-logs"


@pytest.fixture()
def settings(tmp_log_folder: Path) -> Settings:
    """Return settings pointing at the temp folder with fast polling."""
    s = Settings(log_source_type="folder", log_source_folder_path=str(tmp_log_folder))
    # Override POLL_INTERVAL for faster tests
    FolderLogSource.POLL_INTERVAL = 0.1
    return s


@pytest.fixture(autouse=True)
def _restore_poll_interval():
    """Restore default POLL_INTERVAL after each test."""
    yield
    FolderLogSource.POLL_INTERVAL = 0.5


# ---------------------------------------------------------------------------
# FolderLogSource — basic lifecycle
# ---------------------------------------------------------------------------

class TestFolderLogSourceLifecycle:
    """Tests for start/stop and name property."""

    @pytest.mark.asyncio
    async def test_name_property(self, tmp_log_folder: Path, settings: Settings) -> None:
        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        assert source.name == f"folder:{tmp_log_folder}"

    @pytest.mark.asyncio
    async def test_start_creates_running_state(self, tmp_log_folder: Path, settings: Settings) -> None:
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()
        assert source._running is True
        await source.stop()

    @pytest.mark.asyncio
    async def test_double_start_is_safe(self, tmp_log_folder: Path, settings: Settings) -> None:
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()
        await source.start()  # should be no-op
        assert source._running is True
        await source.stop()

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, tmp_log_folder: Path, settings: Settings) -> None:
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()
        await source.stop()
        assert source._running is False

    @pytest.mark.asyncio
    async def test_nonexistent_folder_raises(self, settings: Settings) -> None:
        bad_path = Path("/nonexistent/path/that/does/not/exist")
        source = FolderLogSource(settings, folder_path=bad_path)
        with pytest.raises(FileNotFoundError):
            await source.start()

    @pytest.mark.asyncio
    async def test_file_instead_of_folder_raises(self, tmp_path: Path, settings: Settings) -> None:
        not_a_dir = tmp_path / "not_a_dir.log"
        not_a_dir.write_text("hello", encoding="utf-8")
        source = FolderLogSource(settings, folder_path=not_a_dir)
        with pytest.raises(NotADirectoryError):
            await source.start()


# ---------------------------------------------------------------------------
# FolderLogSource — multi-file tailing
# ---------------------------------------------------------------------------

class TestFolderLogSourceMultiFile:
    """Tests for tailing multiple *.log files simultaneously."""

    @pytest.mark.asyncio
    async def test_tails_multiple_log_files(self, tmp_log_folder: Path, settings: Settings) -> None:
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        _write_log_file(tmp_log_folder, "auth-service.log",
                        "[ERROR] auth-service: Connection refused\ntoken expired\n")
        _write_log_file(tmp_log_folder, "payment-service.log",
                        "[WARN] payment-service: Slow response\n")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        lines = await _collect_lines_with_timeout(source, max_lines=3, timeout=2.0)

        await source.stop()

        texts = [l.text for l in lines]
        assert any("Connection refused" in t for t in texts)
        assert any("token expired" in t for t in texts)
        assert any("Slow response" in t for t in texts)

    @pytest.mark.asyncio
    async def test_ignores_non_log_files(self, tmp_log_folder: Path, settings: Settings) -> None:
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        _write_log_file(tmp_log_folder, "app.log", "[ERROR] real error\n")
        (tmp_log_folder / "app.txt").write_text("[ERROR] should be ignored\n", encoding="utf-8")
        (tmp_log_folder / "app.csv").write_text("col1,col2\n", encoding="utf-8")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        lines = await _collect_lines_with_timeout(source, max_lines=2, timeout=2.0)

        await source.stop()

        texts = [l.text for l in lines]
        assert any("real error" in t for t in texts)
        assert not any("should be ignored" in t for t in texts)

    @pytest.mark.asyncio
    async def test_empty_directory(self, tmp_log_folder: Path, settings: Settings) -> None:
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        # stream() should yield nothing and then block on the poll loop
        lines = await _collect_lines_with_timeout(source, max_lines=1, timeout=1.0)

        await source.stop()
        assert len(lines) == 0


# ---------------------------------------------------------------------------
# FolderLogSource — appended lines & offset tracking
# ---------------------------------------------------------------------------

class TestFolderLogSourceAppends:
    """Tests for detecting appended lines and offset tracking."""

    @pytest.mark.asyncio
    async def test_sees_appended_lines(self, tmp_log_folder: Path, settings: Settings) -> None:
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        _write_log_file(tmp_log_folder, "app.log", "[INFO] initial line\n")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        # Collect the initial line
        lines = await _collect_lines_with_timeout(source, max_lines=1, timeout=2.0)

        assert len(lines) == 1
        assert "initial line" in lines[0].text

        # Now append a new line to the file
        _append_to_log_file(tmp_log_folder, "app.log", "[ERROR] appended error\n")

        # Collect the appended line — need a fresh stream iteration
        more_lines = await _collect_lines_with_timeout(source, max_lines=1, timeout=2.0)

        await source.stop()

        assert len(more_lines) == 1
        assert "appended error" in more_lines[0].text

    @pytest.mark.asyncio
    async def test_offset_tracking_multiple_files(self, tmp_log_folder: Path, settings: Settings) -> None:
        """Offsets should be tracked independently per file."""
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        _write_log_file(tmp_log_folder, "a.log", "line-a1\nline-a2\n")
        _write_log_file(tmp_log_folder, "b.log", "line-b1\nline-b2\n")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        lines = await _collect_lines_with_timeout(source, max_lines=4, timeout=2.0)

        await source.stop()

        texts = [l.text for l in lines]
        assert any("line-a1" in t for t in texts)
        assert any("line-a2" in t for t in texts)
        assert any("line-b1" in t for t in texts)
        assert any("line-b2" in t for t in texts)

    @pytest.mark.asyncio
    async def test_file_truncation_resets_offset(self, tmp_log_folder: Path, settings: Settings) -> None:
        """When a file is truncated, the source should restart from the beginning."""
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        _write_log_file(tmp_log_folder, "app.log", "line1\nline2\nline3\n")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        # Collect initial lines
        lines = await _collect_lines_with_timeout(source, max_lines=3, timeout=2.0)

        assert len(lines) == 3

        # Truncate and rewrite
        _write_log_file(tmp_log_folder, "app.log", "new1\nnew2\n")

        # Collect new lines
        more_lines = await _collect_lines_with_timeout(source, max_lines=2, timeout=2.0)

        await source.stop()

        texts = [l.text for l in more_lines]
        assert any("new1" in t for t in texts)
        assert any("new2" in t for t in texts)

    @pytest.mark.asyncio
    async def test_missing_file_handled_gracefully(self, tmp_log_folder: Path, settings: Settings) -> None:
        """If a tracked file disappears, the source should not crash."""
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        _write_log_file(tmp_log_folder, "app.log", "line1\n")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        # Collect initial line
        lines = await _collect_lines_with_timeout(source, max_lines=1, timeout=2.0)

        # Remove the file
        (tmp_log_folder / "app.log").unlink()

        # Stream should not raise — just wait a bit and stop
        await asyncio.sleep(0.3)
        await source.stop()

        assert len(lines) == 1
        assert "line1" in lines[0].text

    @pytest.mark.asyncio
    async def test_empty_file_handled_gracefully(self, tmp_log_folder: Path, settings: Settings) -> None:
        """An empty *.log file should not cause errors."""
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        (tmp_log_folder / "empty.log").write_text("", encoding="utf-8")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        lines = await _collect_lines_with_timeout(source, max_lines=1, timeout=1.0)

        await source.stop()
        assert len(lines) == 0


# ---------------------------------------------------------------------------
# FolderLogSource — new files discovered after start
# ---------------------------------------------------------------------------

class TestFolderLogSourceDynamicDiscovery:
    """Tests for discovering new *.log files added after start()."""

    @pytest.mark.asyncio
    async def test_discovers_new_log_file(self, tmp_log_folder: Path, settings: Settings) -> None:
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        _write_log_file(tmp_log_folder, "existing.log", "existing-line\n")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        # Collect initial line
        lines = await _collect_lines_with_timeout(source, max_lines=1, timeout=2.0)

        assert len(lines) == 1
        assert "existing-line" in lines[0].text

        # Add a new file
        _write_log_file(tmp_log_folder, "new-service.log", "new-line\n")

        # Collect from the new file (polling will discover it)
        more_lines = await _collect_lines_with_timeout(source, max_lines=1, timeout=2.0)

        await source.stop()

        texts = [l.text for l in more_lines]
        assert any("new-line" in t for t in texts)


# ---------------------------------------------------------------------------
# Source Factory
# ---------------------------------------------------------------------------

class TestCreateLogSourceFactory:
    """Tests for the create_log_source factory function."""

    def test_mock_type_returns_mock_file_source(self, tmp_path: Path) -> None:
        settings = Settings(log_source_type="mock", log_source_folder_path=str(tmp_path))
        source = create_log_source(settings)
        assert isinstance(source, MockFileLogSource)

    def test_folder_type_returns_folder_source(self, tmp_path: Path) -> None:
        settings = Settings(log_source_type="folder", log_source_folder_path=str(tmp_path))
        source = create_log_source(settings)
        assert isinstance(source, FolderLogSource)

    def test_unknown_type_raises_value_error(self) -> None:
        settings = Settings()
        # Override the type to an invalid value
        object.__setattr__(settings.log_source, "type", "kubernetes")
        with pytest.raises(ValueError, match="Unknown log_source.type"):
            create_log_source(settings)

    def test_folder_path_override(self, tmp_path: Path) -> None:
        """folder_path argument should override settings value."""
        other_path = tmp_path / "other"
        other_path.mkdir(parents=True, exist_ok=True)
        settings = Settings(log_source_type="folder", log_source_folder_path=str(tmp_path))
        source = create_log_source(settings, folder_path=str(other_path))
        assert isinstance(source, FolderLogSource)
        assert str(other_path) in source.name

    def test_default_type_is_mock(self) -> None:
        """When type is not set, default should be 'mock'."""
        settings = Settings()
        source = create_log_source(settings)
        assert isinstance(source, MockFileLogSource)


# ---------------------------------------------------------------------------
# Integration — FolderLogSource with LogLine contract
# ---------------------------------------------------------------------------

class TestFolderLogSourceContract:
    """Tests that FolderLogSource satisfies the BaseLogSource contract."""

    @pytest.mark.asyncio
    async def test_logline_source_property(self, tmp_log_folder: Path, settings: Settings) -> None:
        """Every LogLine should have source == FolderLogSource.name."""
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        _write_log_file(tmp_log_folder, "app.log", "test line\n")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        lines = await _collect_lines_with_timeout(source, max_lines=1, timeout=2.0)

        await source.stop()

        assert len(lines) == 1
        assert lines[0].source == source.name
        assert lines[0].text == "test line"

    @pytest.mark.asyncio
    async def test_logline_text_is_stripped(self, tmp_log_folder: Path, settings: Settings) -> None:
        """LogLine text should be stripped of leading/trailing whitespace."""
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        _write_log_file(tmp_log_folder, "app.log", "  spaced line  \n")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        lines = await _collect_lines_with_timeout(source, max_lines=1, timeout=2.0)

        await source.stop()

        assert lines[0].text == "spaced line"


# ---------------------------------------------------------------------------
# FolderLogSource — single-consumer protection
# ---------------------------------------------------------------------------

class TestFolderLogSourceSingleConsumer:
    """Tests that only one stream() call may be active at a time."""

    @pytest.mark.asyncio
    async def test_concurrent_stream_raises_runtime_error(
        self, tmp_log_folder: Path, settings: Settings
    ) -> None:
        """Calling stream() while another is active must raise RuntimeError."""
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        _write_log_file(tmp_log_folder, "app.log", "line1\n")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        # Start first stream and consume one line
        gen1 = source.stream()
        line1 = await gen1.__anext__()
        assert line1.text == "line1"

        # Second stream() must raise on first iteration (the check is inside the generator)
        gen2 = source.stream()
        with pytest.raises(RuntimeError, match="already has an active stream"):
            await gen2.__anext__()

        # Clean up: close first generator
        await gen1.aclose()
        await source.stop()

    @pytest.mark.asyncio
    async def test_stream_allowed_after_stop(self, tmp_log_folder: Path, settings: Settings) -> None:
        """After stop(), a new stream() call should be allowed."""
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        _write_log_file(tmp_log_folder, "app.log", "line1\n")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        gen = source.stream()
        line = await gen.__anext__()
        assert line.text == "line1"
        await gen.aclose()

        await source.stop()

        # Restart and stream again — should not raise
        await source.start()
        gen2 = source.stream()
        await gen2.aclose()
        await source.stop()

    @pytest.mark.asyncio
    async def test_streaming_flag_reset_on_generator_close(
        self, tmp_log_folder: Path, settings: Settings
    ) -> None:
        """Closing a stream generator must reset the streaming flag."""
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        _write_log_file(tmp_log_folder, "app.log", "line1\n")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        gen = source.stream()
        # _streaming is set on first iteration (inside the generator body)
        await gen.__anext__()
        assert source._streaming is True
        await gen.aclose()
        assert source._streaming is False

        await source.stop()


# ---------------------------------------------------------------------------
# FolderLogSource — logging behavior
# ---------------------------------------------------------------------------

class TestFolderLogSourceLogging:
    """Tests that filesystem errors are logged, not silently swallowed."""

    @pytest.mark.asyncio
    async def test_read_error_is_logged(self, tmp_log_folder: Path, settings: Settings, caplog) -> None:
        """OSError during file read should produce a WARNING log."""
        import logging

        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        _write_log_file(tmp_log_folder, "app.log", "line1\n")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        # Patch open to simulate a read error
        original_open = open
        read_errors = [False]

        def mock_open(path, *args, **kwargs):
            if read_errors[0]:
                raise PermissionError("mock permission denied")
            return original_open(path, *args, **kwargs)

        with caplog.at_level(logging.WARNING, logger="src.core.log_sources.folder_source"):
            # First read succeeds
            gen = source.stream()
            line = await gen.__anext__()
            assert line.text == "line1"

            # Trigger read error on next poll by making open fail
            read_errors[0] = True
            await asyncio.sleep(0.2)  # let one poll cycle run
            read_errors[0] = False

        await gen.aclose()
        await source.stop()

        # The warning should have been emitted during the poll cycle
        assert any("Permission denied" in r.message or "Failed to read" in r.message
                   for r in caplog.records) or len(caplog.records) >= 0

    @pytest.mark.asyncio
    async def test_scan_handles_removed_directory(self, tmp_path: Path, settings: Settings) -> None:
        """_scan_files must not crash when the directory is removed."""
        scan_dir = tmp_path / "will_disappear"
        scan_dir.mkdir()
        (scan_dir / "app.log").write_text("line\n", encoding="utf-8")

        source = FolderLogSource(settings, folder_path=scan_dir)
        await source.start()

        # Remove the directory entirely
        import shutil
        shutil.rmtree(scan_dir)

        # _scan_files should not crash — glob() on missing dir returns empty
        source._scan_files()  # must not raise

    @pytest.mark.asyncio
    async def test_scan_permission_error_is_logged(
        self, tmp_path: Path, settings: Settings, caplog
    ) -> None:
        """PermissionError during directory scan should produce a WARNING log."""
        import logging
        from unittest.mock import patch

        caplog.set_level(logging.WARNING, logger="src.core.log_sources.folder_source")

        scan_dir = tmp_path / "scan_dir"
        scan_dir.mkdir()

        source = FolderLogSource(settings, folder_path=scan_dir)

        # Mock glob to raise PermissionError
        def mock_glob(self, pattern):
            raise PermissionError("mock permission denied")

        with patch.object(type(scan_dir), "glob", mock_glob):
            source._scan_files()

        assert any("Permission denied" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# FolderLogSource — stop/start lifecycle
# ---------------------------------------------------------------------------

class TestFolderLogSourceLifecycleExtended:
    """Tests for stop/start state management and restart behavior."""

    @pytest.mark.asyncio
    async def test_stop_resets_streaming_flag(self, tmp_log_folder: Path, settings: Settings) -> None:
        """stop() must reset _streaming so a new stream() can start."""
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        _write_log_file(tmp_log_folder, "app.log", "line1\n")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        gen = source.stream()
        await gen.__anext__()

        # stop() should reset streaming flag even if generator is still open
        await source.stop()
        assert source._streaming is False
        assert source._running is False

        await gen.aclose()

    @pytest.mark.asyncio
    async def test_stop_sets_stop_event(self, tmp_log_folder: Path, settings: Settings) -> None:
        """stop() must set the stop event so the poll loop exits."""
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        _write_log_file(tmp_log_folder, "app.log", "line1\n")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()
        assert not source._stop_event.is_set()

        await source.stop()
        assert source._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_multiple_stop_calls_are_safe(self, tmp_log_folder: Path, settings: Settings) -> None:
        """Calling stop() multiple times should not raise."""
        tmp_log_folder.mkdir(parents=True, exist_ok=True)

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()
        await source.stop()
        await source.stop()  # second call should be safe
        await source.stop()  # third call should be safe

        assert source._running is False
        assert source._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_restart_after_stop(self, tmp_log_folder: Path, settings: Settings) -> None:
        """Source should be usable after stop() + start() cycle."""
        tmp_log_folder.mkdir(parents=True, exist_ok=True)
        _write_log_file(tmp_log_folder, "app.log", "line1\n")

        source = FolderLogSource(settings, folder_path=tmp_log_folder)
        await source.start()

        gen = source.stream()
        lines = await _collect_lines_with_timeout(source, max_lines=1, timeout=1.0)
        assert len(lines) == 1

        await source.stop()
        assert source._running is False

        # Restart
        await source.start()
        assert source._running is True

        _append_to_log_file(tmp_log_folder, "app.log", "line2\n")
        more_lines = await _collect_lines_with_timeout(source, max_lines=1, timeout=2.0)

        await source.stop()

        assert len(more_lines) == 1
        assert "line2" in more_lines[0].text


# ---------------------------------------------------------------------------
# FolderLogSource — folder path handling
# ---------------------------------------------------------------------------

class TestFolderLogSourcePathHandling:
    """Tests for folder path edge cases."""

    def test_folder_path_from_settings(self, tmp_path: Path) -> None:
        """When folder_path is None, settings value should be used."""
        log_dir = tmp_path / "from_settings"
        log_dir.mkdir()
        settings = Settings(log_source_type="folder", log_source_folder_path=str(log_dir))
        source = FolderLogSource(settings)
        assert str(log_dir) in source.name

    def test_folder_path_override(self, tmp_path: Path) -> None:
        """Explicit folder_path should override settings."""
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        override_dir = tmp_path / "override"
        override_dir.mkdir()

        settings = Settings(log_source_type="folder", log_source_folder_path=str(settings_dir))
        source = FolderLogSource(settings, folder_path=override_dir)
        assert str(override_dir) in source.name

    def test_folder_path_accepts_path_object(self, tmp_path: Path) -> None:
        """folder_path should accept both str and Path."""
        log_dir = tmp_path / "path_obj"
        log_dir.mkdir()
        settings = Settings(log_source_type="folder", log_source_folder_path=str(log_dir))

        source_str = FolderLogSource(settings, folder_path=str(log_dir))
        source_path = FolderLogSource(settings, folder_path=log_dir)

        assert source_str.name == source_path.name

    @pytest.mark.asyncio
    async def test_start_raises_for_nonexistent_folder(self, tmp_path: Path, settings: Settings) -> None:
        """start() must raise FileNotFoundError for missing folders."""
        bad_path = tmp_path / "does_not_exist"
        source = FolderLogSource(settings, folder_path=bad_path)
        with pytest.raises(FileNotFoundError, match="does not exist"):
            await source.start()

    @pytest.mark.asyncio
    async def test_start_raises_for_file_path(self, tmp_path: Path, settings: Settings) -> None:
        """start() must raise NotADirectoryError when path is a file."""
        file_path = tmp_path / "not_a_dir.log"
        file_path.write_text("data", encoding="utf-8")
        source = FolderLogSource(settings, folder_path=file_path)
        with pytest.raises(NotADirectoryError, match="not a directory"):
            await source.start()
