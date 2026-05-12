"""Folder log source - tails *.log files in a shared directory.

Polling-based implementation that tracks per-file offsets and emits
``LogLine`` objects as new lines are appended to any ``*.log`` file
in the configured directory.

No external dependencies (watchdog, inotify, etc.) - pure asyncio +
standard library.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Dict

from src.config.settings import Settings
from src.core.log_sources.base import BaseLogSource, LogLine


class FolderLogSource(BaseLogSource):
    """Watches a directory for ``*.log`` files and tails them.

    Lifecycle:
        1. ``start()`` - scans the directory for ``*.log`` files, records
           their current sizes as initial offsets, then begins polling.
        2. ``stream()`` - polls every ``POLL_INTERVAL`` seconds, reads new
           lines from every tracked file, yields ``LogLine`` objects.
        3. ``stop()`` - signals the polling loop to exit.

    Features:
        - Polling-based (no inotify/watchdog)
        - Per-file offset tracking
        - Detects appended lines only
        - Ignores non-``*.log`` files
        - Handles missing/empty files gracefully
        - Async-safe (all I/O on the event loop thread)
    """

    POLL_INTERVAL: float = 0.5  # seconds between polls

    def __init__(self, settings: Settings, folder_path: str | Path | None = None) -> None:
        self._settings = settings
        self._folder_path = Path(folder_path) if folder_path else Path(settings.log_source.folder_path)
        self._running = False
        self._stop_event = asyncio.Event()
        # offset tracking: filepath_str -> current byte offset
        self._offsets: Dict[str, int] = {}

    @property
    def name(self) -> str:
        return f"folder:{self._folder_path}"

    async def start(self) -> None:
        """Scan the directory and begin polling for new lines."""
        if self._running:
            return

        if not self._folder_path.exists():
            raise FileNotFoundError(f"Log folder does not exist: {self._folder_path}")

        if not self._folder_path.is_dir():
            raise NotADirectoryError(f"Log path is not a directory: {self._folder_path}")

        self._running = True
        self._stop_event.clear()
        # Initial scan - record offsets for all existing *.log files
        self._scan_files()

    async def stop(self) -> None:
        """Stop polling."""
        self._running = False
        self._stop_event.set()

    async def stream(self):
        """Async generator that yields LogLine objects as new lines appear.

        On each call, re-scans the directory for ``*.log`` files and reads
        any new or updated content.  This allows callers to obtain fresh
        lines even after the previous iteration stopped (e.g. via ``break``).
        """
        try:
            # Re-scan at the start so newly-added files are picked up
            self._scan_files()

            # Yield any existing / new content first
            for filepath_str, offset in list(self._offsets.items()):
                filepath = Path(filepath_str)
                if not filepath.exists():
                    continue
                try:
                    current_size = filepath.stat().st_size
                except OSError:
                    continue
                # Handle truncation: if file shrank, restart from beginning
                if current_size < offset:
                    effective_offset = 0
                else:
                    effective_offset = offset
                async for line in self._read_new_lines(filepath, effective_offset):
                    yield line

            # Poll loop - use wait_for with stop_event so break/stop is responsive
            while self._running:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.POLL_INTERVAL)
                    return  # stop_event was set
                except asyncio.TimeoutError:
                    pass
                except asyncio.CancelledError:
                    return

                # Re-scan for new files (files added after start)
                self._scan_files()

                # Check all tracked files for new content
                for filepath_str in list(self._offsets.keys()):
                    filepath = Path(filepath_str)
                    if not filepath.exists():
                        # File was removed - reset offset so it picks up on re-creation
                        self._offsets[filepath_str] = 0
                        continue

                    try:
                        current_size = filepath.stat().st_size
                    except OSError:
                        continue

                    if current_size < self._offsets.get(filepath_str, 0):
                        # File was truncated - restart from beginning
                        self._offsets[filepath_str] = 0

                    if current_size > self._offsets.get(filepath_str, 0):
                        async for line in self._read_new_lines(filepath, self._offsets[filepath_str]):
                            yield line
        finally:
            # Ensure stop_event is set when generator is closed (e.g. via break)
            self._stop_event.set()

    def _scan_files(self) -> None:
        """Discover all *.log files in the folder and initialize offsets."""
        try:
            for log_file in sorted(self._folder_path.glob("*.log")):
                if log_file.is_file():
                    filepath_str = str(log_file)
                    if filepath_str not in self._offsets:
                        # Start from 0 so existing content is yielded on first pass
                        self._offsets[filepath_str] = 0
        except OSError:
            # Directory disappeared between scans - handled in stream loop
            pass

    async def _read_new_lines(self, filepath: Path, start_offset: int):
        """Read new lines from *filepath* starting at *start_offset*.

        Yields ``LogLine`` objects for each new line found.  Updates the
        offset tracking dict in place.
        """
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                f.seek(start_offset)
                new_data = f.read()
                new_offset = f.tell()
        except OSError:
            return

        self._offsets[str(filepath)] = new_offset

        for line in new_data.splitlines():
            stripped = line.strip()
            if stripped:
                yield LogLine(text=stripped, source=self.name)
