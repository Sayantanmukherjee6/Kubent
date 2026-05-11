"""Rolling buffer and context builder for the log watcher pipeline.

Maintains a bounded in-memory buffer of recent log lines per source and
extracts surrounding context when an incident is detected.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class ContextWindow:
    """A window of log lines around an incident.

    Attributes:
        before:   Lines preceding the incident line (up to *before_count*).
        after:    Lines following the incident line (up to *after_count*).
                  Populated when the watcher has already seen them.
    """

    before: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)

    @property
    def all_lines(self) -> list[str]:
        """All context lines in chronological order (before + after)."""
        return self.before + self.after

    @property
    def line_count(self) -> int:
        """Total number of context lines."""
        return len(self.before) + len(self.after)


class RollingBuffer:
    """Async-safe rolling buffer for log lines.

    Stores the most recent N lines per source name in a deque.  When the
    buffer is full, oldest lines are discarded to maintain bounded memory.

    Args:
        max_size: Maximum number of lines to keep per source (default 200).
    """

    def __init__(self, max_size: int = 200) -> None:
        self._max_size = max_size
        self._buffers: dict[str, deque[str]] = {}
        self._lock = asyncio.Lock()

    # -- public API ----------------------------------------------------------

    async def add(self, source: str, line: str) -> None:
        """Append a log line to the buffer for *source*.

        Args:
            source: The log source name.
            line:   The raw log line text.
        """
        async with self._lock:
            if source not in self._buffers:
                self._buffers[source] = deque(maxlen=self._max_size)
            self._buffers[source].append(line)

    async def get_recent(self, source: str, count: int | None = None) -> list[str]:
        """Return the most recent *count* lines for *source*.

        Args:
            source: The log source name.
            count:  Number of lines to return (default: all).

        Returns:
            A list of log line strings in chronological order.
        """
        async with self._lock:
            buf = self._buffers.get(source)
            if buf is None:
                return []
            if count is None:
                return list(buf)
            # Take the last *count* items efficiently
            n = len(buf)
            start = max(0, n - count)
            return list(buf)[start:n]

    async def clear_source(self, source: str) -> None:
        """Remove all buffered lines for a specific source."""
        async with self._lock:
            self._buffers.pop(source, None)

    async def clear_all(self) -> None:
        """Clear all buffered lines."""
        async with self._lock:
            self._buffers.clear()

    @property
    def sources(self) -> set[str]:
        """Names of sources currently in the buffer."""
        return set(self._buffers.keys())

    @property
    def total_lines(self) -> int:
        """Total number of lines across all sources."""
        return sum(len(buf) for buf in self._buffers.values())


class ContextBuilder:
    """Builds context windows around detected incidents.

    Uses a ``RollingBuffer`` to capture surrounding log lines.  When an
    incident is detected, the builder extracts *before_count* lines prior
    to the incident line and optionally *after_count* lines that have
    already been buffered.

    Args:
        buffer:       The shared ``RollingBuffer`` instance.
        before_count: Number of preceding lines to capture (default 5).
        after_count:  Number of following lines to capture (default 3).
    """

    def __init__(
        self,
        buffer: RollingBuffer | None = None,
        before_count: int = 5,
        after_count: int = 3,
    ) -> None:
        self._buffer = buffer or RollingBuffer()
        self._before_count = before_count
        self._after_count = after_count

    # -- public API ----------------------------------------------------------

    async def add_line(self, source: str, line: str) -> None:
        """Add a log line to the rolling buffer.

        Call this for every incoming log line (incident or not).
        """
        await self._buffer.add(source, line)

    async def build_context(
        self,
        source: str,
        incident_line_index: int | None = None,
    ) -> ContextWindow:
        """Extract a context window around the most recent incident.

        If *incident_line_index* is provided, uses that index into the
        buffer to determine which line triggered the incident.  Otherwise,
        captures the last ``before_count`` lines before the current position.

        Args:
            source:              The log source name.
            incident_line_index: Optional index of the incident line in the
                                 buffer (for precise context extraction).

        Returns:
            A ``ContextWindow`` with ``before`` and ``after`` lists.
        """
        all_lines = await self._buffer.get_recent(source)
        if not all_lines:
            return ContextWindow()

        if incident_line_index is not None:
            # Precise extraction around a known index
            start = max(0, incident_line_index - self._before_count)
            end_exclusive = min(len(all_lines), incident_line_index + 1 + self._after_count)
            before = all_lines[start:incident_line_index]
            after = all_lines[incident_line_index + 1:end_exclusive]
        else:
            # Default: take the last N lines as context
            before = all_lines[-self._before_count:] if len(all_lines) >= self._before_count else all_lines
            after: list[str] = []

        return ContextWindow(before=before, after=after)

    @property
    def buffer(self) -> RollingBuffer:
        """The underlying rolling buffer."""
        return self._buffer
