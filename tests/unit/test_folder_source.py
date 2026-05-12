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
    """
    collected: list[LogLine] = []

    async def _gather():
        async for line in source.stream():
            collected.append(line)
            if len(collected) >= max_lines:
                return

    try:
        await asyncio.wait_for(_gather(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
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
