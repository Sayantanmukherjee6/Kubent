"""Mock file log source — reads mock files and streams appended lines asynchronously."""

import asyncio
from pathlib import Path

from src.config.settings import Settings
from src.core.log_sources.base import BaseLogSource, LogLine
from mocks.generators.log_generator import generate_mock_logs_text


class MockFileLogSource(BaseLogSource):
    """Log source that writes mock logs to a file and streams appended lines.

    Lifecycle:
        1. ``start()`` — generates an initial batch of logs into the target file,
           then enters a loop that periodically appends new lines.
        2. ``stream()`` — tails the file, yielding new ``LogLine`` objects as they
           are appended. Runs until ``stop()`` is called.
        3. ``stop()`` — signals the background writer and streamer to exit.
    """

    def __init__(self, settings: Settings, log_dir: Path | None = None) -> None:
        self._settings = settings
        self._log_dir = log_dir or Path("mocks/logs")
        self._filename = "mock_stream.log"
        self._filepath = self._log_dir / self._filename
        self._running = False
        self._writer_task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        return f"mock-file:{self._filepath}"

    async def start(self) -> None:
        """Generate initial batch and begin streaming."""
        if self._running:
            return

        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._running = True

        # Write initial batch to the file
        initial_count = self._settings.mock_log_count
        initial_text = generate_mock_logs_text(count=initial_count)
        self._filepath.write_text(initial_text + "\n", encoding="utf-8")

        # Start background writer that appends new lines periodically
        interval = getattr(self._settings, "mock_log_interval", 1.0)
        self._writer_task = asyncio.create_task(
            self._background_writer(interval),
        )

    async def stop(self) -> None:
        """Stop streaming and clean up."""
        self._running = False
        if self._writer_task is not None:
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass
            self._writer_task = None

    async def stream(self):
        """Async generator that yields LogLine objects as they are appended.

        Reads the file from the end and yields new lines as they appear.
        """
        # Read existing content first
        if self._filepath.exists():
            content = self._filepath.read_text(encoding="utf-8")
            for line in content.strip().splitlines():
                if line:
                    yield LogLine(text=line, source=self.name)

        # Tail the file for new lines
        last_pos = self._filepath.stat().st_size
        while self._running:
            try:
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                return

            if not self._filepath.exists():
                continue

            try:
                current_size = self._filepath.stat().st_size
            except OSError:
                continue

            if current_size < last_pos:
                # File was truncated — restart from beginning
                last_pos = 0

            if current_size > last_pos:
                try:
                    with open(self._filepath, "r", encoding="utf-8") as f:
                        f.seek(last_pos)
                        new_data = f.read()
                        last_pos = f.tell()

                    for line in new_data.splitlines():
                        if line.strip():
                            yield LogLine(text=line.strip(), source=self.name)
                except OSError:
                    continue

    async def _background_writer(self, interval: float) -> None:
        """Periodically append new mock log lines to the file."""
        batch_size = 5
        while self._running:
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                return

            new_text = generate_mock_logs_text(count=batch_size)
            with open(self._filepath, "a", encoding="utf-8") as f:
                f.write(new_text + "\n")
