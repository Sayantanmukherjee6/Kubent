"""Folder metric source — tails CSV metric files in a shared directory.

Polling-based implementation that tracks per-file offsets and emits
``MetricSample`` objects as new lines are appended to any ``*.csv`` file
in the configured directory.

CSV format expected:

    timestamp,service,cpu,memory,latency,error_rate

Example:

    2026-01-01T10:00:00Z,payment-service,72,68,120,0.01

No external dependencies (watchdog, inotify, etc.) — pure asyncio +
standard library.
"""

from __future__ import annotations

import asyncio
import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from src.config.settings import Settings
from src.core.metrics.base import BaseMetricSource
from src.core.metrics.models import MetricSample

logger = logging.getLogger(__name__)


class FolderMetricSource(BaseMetricSource):
    """Watches a directory for ``*.csv`` metric files and tails them.

    Lifecycle:
        1. ``start()`` — scans the directory for ``*.csv`` files, records
           their current sizes as initial offsets, then begins polling.
        2. ``stream()`` — polls every ``POLL_INTERVAL`` seconds, reads new
           lines from every tracked file, yields ``MetricSample`` objects.
        3. ``stop()`` — signals the polling loop to exit.

    Features:
        - Polling-based (no inotify/watchdog)
        - Per-file offset tracking
        - Detects appended lines only
        - Ignores non-``*.csv`` files
        - Handles missing/empty files gracefully
        - Async-safe (all I/O on the event loop thread)
        - Single-consumer: only one ``stream()`` call may be active at a time

    Logging:
        Filesystem errors (permission denied, missing files, stat failures)
        are logged via the standard ``logging`` module at WARNING level.
    """

    POLL_INTERVAL: float = 0.5  # seconds between polls

    def __init__(self, settings: Settings, folder_path: str | Path | None = None) -> None:
        self._settings = settings
        self._folder_path = Path(folder_path) if folder_path else Path(
            settings.metrics.source.folder_path
        )
        self._running = False
        self._stop_event = asyncio.Event()
        self._streaming = False  # single-consumer guard
        # offset tracking: filepath_str -> current byte offset
        self._offsets: Dict[str, int] = {}

    @property
    def name(self) -> str:
        return f"folder-metrics:{self._folder_path}"

    async def start(self) -> None:
        """Scan the directory and begin polling for new lines."""
        if self._running:
            return

        if not self._folder_path.exists():
            raise FileNotFoundError(f"Metrics folder does not exist: {self._folder_path}")

        if not self._folder_path.is_dir():
            raise NotADirectoryError(f"Metrics path is not a directory: {self._folder_path}")

        self._running = True
        self._stop_event.clear()
        # Initial scan — record offsets for all existing *.csv files
        self._scan_files()

        if not self._offsets:
            logger.warning(
                "No *.csv files found in %s. FolderMetricSource will poll but emit no samples. "
                "Generate metrics with: python generate_test_metrics.py --output-dir %s",
                self._folder_path, self._folder_path,
            )

    async def stop(self) -> None:
        """Stop polling and reset internal state for clean restart."""
        self._running = False
        self._stop_event.set()
        self._streaming = False

    async def stream(self):
        """Async generator that yields MetricSample objects as new lines appear.

        Only one consumer may iterate this generator at a time. Calling
        ``stream()`` while another iteration is active raises ``RuntimeError``.

        On each call, re-scans the directory for ``*.csv`` files and reads
        any new or updated content.  This allows callers to obtain fresh
        lines even after the previous iteration stopped (e.g. via ``break``).
        """
        if self._streaming:
            raise RuntimeError(
                "FolderMetricSource already has an active stream(). "
                "Only one consumer is allowed at a time."
            )
        self._streaming = True
        try:
            # Re-scan at the start so newly-added files are picked up
            self._scan_files()

            # Yield any existing / new content first
            for filepath_str in list(self._offsets.keys()):
                filepath = Path(filepath_str)
                if not filepath.exists():
                    continue
                try:
                    current_size = filepath.stat().st_size
                except OSError as exc:
                    logger.warning("Failed to stat %s: %s", filepath, exc)
                    continue
                # Handle truncation: if file shrank, restart from beginning
                if current_size < self._offsets.get(filepath_str, 0):
                    effective_offset = 0
                else:
                    effective_offset = self._offsets[filepath_str]
                async for sample in self._read_new_samples(filepath, effective_offset):
                    yield sample

            # Poll loop — use wait_for with stop_event so break/stop is responsive
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
                        # File was removed — reset offset so it picks up on re-creation
                        self._offsets[filepath_str] = 0
                        continue

                    try:
                        current_size = filepath.stat().st_size
                    except OSError as exc:
                        logger.warning("Failed to stat %s: %s", filepath, exc)
                        continue

                    if current_size < self._offsets.get(filepath_str, 0):
                        # File was truncated — restart from beginning
                        self._offsets[filepath_str] = 0

                    if current_size > self._offsets.get(filepath_str, 0):
                        async for sample in self._read_new_samples(
                            filepath, self._offsets[filepath_str]
                        ):
                            yield sample
        finally:
            # Ensure stop_event is set when generator is closed (e.g. via break)
            self._stop_event.set()
            self._streaming = False

    def _scan_files(self) -> None:
        """Discover all *.csv files in the folder and initialize offsets."""
        try:
            for csv_file in sorted(self._folder_path.glob("*.csv")):
                if csv_file.is_file():
                    filepath_str = str(csv_file)
                    if filepath_str not in self._offsets:
                        # Start from 0 so existing content is yielded on first pass
                        self._offsets[filepath_str] = 0
        except PermissionError as exc:
            logger.warning("Permission denied scanning directory %s: %s", self._folder_path, exc)
        except OSError as exc:
            logger.warning("Failed to scan directory %s: %s", self._folder_path, exc)

    async def _read_new_samples(self, filepath: Path, start_offset: int):
        """Read new lines from *filepath* starting at *start_offset*.

        Parses each line as CSV and yields ``MetricSample`` objects.
        Updates the offset tracking dict in place.
        """
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                f.seek(start_offset)
                new_data = f.read()
                new_offset = f.tell()
        except PermissionError as exc:
            logger.warning("Permission denied reading %s: %s", filepath, exc)
            return
        except OSError as exc:
            logger.warning("Failed to read %s: %s", filepath, exc)
            return

        self._offsets[str(filepath)] = new_offset

        for line in new_data.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            sample = self._parse_csv_line(stripped, filepath.name)
            if sample is not None:
                yield sample

    @staticmethod
    def _parse_csv_line(line: str, file_source: str) -> MetricSample | None:
        """Parse a single CSV metric line into a ``MetricSample``.

        Expected format: timestamp,service,cpu,memory,latency,error_rate

        Returns ``None`` if the line cannot be parsed.
        """
        try:
            reader = csv.reader([line])
            fields = next(reader)
            if len(fields) != 6:
                return None

            ts_str, service, cpu_str, mem_str, lat_str, err_str = (
                f.strip() for f in fields
            )

            # Parse timestamp — support ISO 8601 format
            ts_str_clean = ts_str.replace("Z", "+00:00")
            try:
                timestamp = datetime.fromisoformat(ts_str_clean)
            except ValueError:
                return None

            cpu = float(cpu_str)
            memory = float(mem_str)
            latency = float(lat_str)
            error_rate = float(err_str)

            return MetricSample(
                timestamp=timestamp,
                service_name=service,
                cpu_usage=cpu,
                memory_usage=memory,
                latency_ms=latency,
                error_rate=error_rate,
                source=file_source,
            )
        except (ValueError, StopIteration):
            return None
