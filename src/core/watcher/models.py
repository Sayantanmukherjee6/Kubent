"""Data models for the log watcher incident pipeline.

Lightweight, frozen dataclasses — no pydantic, no external dependencies.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Severity levels used by the watcher pipeline
# ---------------------------------------------------------------------------

class WatcherSeverity(str, Enum):
    """Incident severity as determined by detection rules."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Internal log line representation (lightweight copy of base.LogLine)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class WatcherLogLine:
    """A single log line as seen by the watcher pipeline.

    This is a lightweight wrapper around the raw text that carries only the
    metadata needed for detection and context building.
    """

    text: str
    source: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Incident event model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IncidentEvent:
    """A structured incident event emitted by the watcher.

    This is the primary output of the watcher pipeline.  It captures a
    detected error/incident along with surrounding context, deduplication
    metadata, and a stable fingerprint for de-duplication.

    Attributes:
        timestamp:          When this incident was detected (UTC).
        service_name:       The Kubernetes service that produced the log.
        severity:           Detected severity level.
        error_type:         Human-readable classification of the error.
        raw_line:           The original log line that triggered detection.
        context_lines:      Surrounding log lines for context (before/after).
        source_name:        Name of the log source (e.g. ``mock-file:...``).
        occurrence_count:   How many times this fingerprint has been seen.
        event_hash:         Stable fingerprint for deduplication.
        metadata:           Optional extra key-value pairs.
    """

    timestamp: datetime
    service_name: str
    severity: WatcherSeverity
    error_type: str
    raw_line: str
    context_lines: list[str] = field(default_factory=list)
    source_name: str = ""
    occurrence_count: int = 1
    event_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Auto-compute event_hash if not provided."""
        if not self.event_hash:
            object.__setattr__(
                self,
                "event_hash",
                _compute_fingerprint(self.service_name, self.error_type, self.raw_line),
            )

    def __str__(self) -> str:
        return (
            f"IncidentEvent(severity={self.severity.value}, "
            f"service={self.service_name}, "
            f"type={self.error_type}, "
            f"count={self.occurrence_count}, "
            f"hash={self.event_hash[:8]})"
        )


# ---------------------------------------------------------------------------
# Detection result (internal, short-lived)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DetectionResult:
    """Intermediate result from the detector for a single log line.

    Only set when a line matches a detection rule.
    """

    is_incident: bool
    severity: WatcherSeverity | None = None
    error_type: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_fingerprint(service_name: str, error_type: str, raw_line: str) -> str:
    """Compute a stable SHA-256 fingerprint for deduplication.

    The fingerprint is based on service + error type + a truncated version
    of the raw line (to normalize timestamps and IDs).
    """
    # Strip common variable parts: timestamps, hex IDs, numeric durations
    import re
    normalized = re.sub(
        r"\d{4}-\d{2}-\d{2}T[\d:.]+Z?", "", raw_line
    )
    normalized = re.sub(r"0x[0-9a-fA-F]+", "0x...", normalized)
    normalized = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+\b", "IP:PORT", normalized)
    normalized = re.sub(r"\b\d+(ms|s|GB|MB|kB)\b", "N\\1", normalized)
    key = f"{service_name}|{error_type}|{normalized}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
