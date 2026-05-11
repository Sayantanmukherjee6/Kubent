"""Rule-based error detection for the log watcher pipeline.

Uses configurable regex patterns to classify log lines into incident types
with associated severity levels.  Designed to be fast, deterministic, and
free of false positives where possible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.core.watcher.models import DetectionResult, WatcherSeverity


# ---------------------------------------------------------------------------
# Default detection rules — each rule is (compiled_regex, severity, error_type)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Rule:
    """A single detection rule."""

    pattern: re.Pattern[str]
    severity: WatcherSeverity
    error_type: str


# Build the default rule set.  Rules are evaluated in order; the first match wins.
_DEFAULT_RULES: list[_Rule] = [
    # --- CRITICAL ---
    _Rule(
        re.compile(r"OOMKilled", re.IGNORECASE),
        WatcherSeverity.CRITICAL,
        "OOMKilled",
    ),
    _Rule(
        re.compile(r"Out of memory.*killed process", re.IGNORECASE),
        WatcherSeverity.CRITICAL,
        "OutOfMemoryKill",
    ),
    _Rule(
        re.compile(r"Network partition detected", re.IGNORECASE),
        WatcherSeverity.CRITICAL,
        "NetworkPartition",
    ),
    _Rule(
        re.compile(r"quorum at risk|cluster node.*unreachable", re.IGNORECASE),
        WatcherSeverity.CRITICAL,
        "ClusterQuorumRisk",
    ),
    _Rule(
        re.compile(r"Data corruption detected", re.IGNORECASE),
        WatcherSeverity.CRITICAL,
        "DataCorruption",
    ),
    _Rule(
        re.compile(r"Database primary failover initiated", re.IGNORECASE),
        WatcherSeverity.CRITICAL,
        "DatabaseFailover",
    ),
    _Rule(
        re.compile(r"SSL certificate expired|TLS.*certificate expired", re.IGNORECASE),
        WatcherSeverity.CRITICAL,
        "SSLCertificateExpired",
    ),

    # --- HIGH ---
    _Rule(
        re.compile(r"Traceback", re.IGNORECASE),
        WatcherSeverity.HIGH,
        "ExceptionTraceback",
    ),
    _Rule(
        re.compile(r"\bHTTP 5\d{2}\b", re.IGNORECASE),
        WatcherSeverity.HIGH,
        "HTTP5xx",
    ),
    _Rule(
        re.compile(r"Connection refused", re.IGNORECASE),
        WatcherSeverity.HIGH,
        "ConnectionRefused",
    ),
    _Rule(
        re.compile(r"ECONNREFUSED", re.IGNORECASE),
        WatcherSeverity.HIGH,
        "ConnectionRefused",
    ),
    _Rule(
        re.compile(r"timeout|timed out", re.IGNORECASE),
        WatcherSeverity.HIGH,
        "Timeout",
    ),
    _Rule(
        re.compile(r"Circuit breaker OPEN", re.IGNORECASE),
        WatcherSeverity.HIGH,
        "CircuitBreakerOpen",
    ),
    _Rule(
        re.compile(r"retry.*exhausted|after \d+ retries|after 3 retries", re.IGNORECASE),
        WatcherSeverity.HIGH,
        "RetryExhausted",
    ),
    _Rule(
        re.compile(r"crash-looping", re.IGNORECASE),
        WatcherSeverity.HIGH,
        "CrashLoopBackOff",
    ),
    _Rule(
        re.compile(r"Disk space critical|no space left on device", re.IGNORECASE),
        WatcherSeverity.HIGH,
        "DiskSpaceCritical",
    ),

    # --- MEDIUM ---
    _Rule(
        re.compile(r"\bERROR\b", re.IGNORECASE),
        WatcherSeverity.MEDIUM,
        "ErrorMessage",
    ),
    _Rule(
        re.compile(r"Redis connection lost|READERR OOM", re.IGNORECASE),
        WatcherSeverity.MEDIUM,
        "RedisError",
    ),
    _Rule(
        re.compile(r"probe failed|liveness check failed", re.IGNORECASE),
        WatcherSeverity.MEDIUM,
        "KubernetesProbeFailed",
    ),
    _Rule(
        re.compile(r"consumer lag exceeded", re.IGNORECASE),
        WatcherSeverity.MEDIUM,
        "ConsumerLag",
    ),
    _Rule(
        re.compile(r"invalid JSON|response body truncated", re.IGNORECASE),
        WatcherSeverity.MEDIUM,
        "MalformedResponse",
    ),

    # --- LOW ---
    _Rule(
        re.compile(r"\bWARN\b", re.IGNORECASE),
        WatcherSeverity.LOW,
        "WarningMessage",
    ),
    _Rule(
        re.compile(r"Retry attempt \d+/\d+", re.IGNORECASE),
        WatcherSeverity.LOW,
        "RetryAttempt",
    ),
    _Rule(
        re.compile(r"Circuit breaker half-open", re.IGNORECASE),
        WatcherSeverity.LOW,
        "CircuitBreakerHalfOpen",
    ),
    _Rule(
        re.compile(r"Memory usage above \d+% threshold", re.IGNORECASE),
        WatcherSeverity.LOW,
        "MemoryThreshold",
    ),
    _Rule(
        re.compile(r"Response time exceeded \d+ms threshold", re.IGNORECASE),
        WatcherSeverity.LOW,
        "LatencyThreshold",
    ),
]


# ---------------------------------------------------------------------------
# Detector class
# ---------------------------------------------------------------------------

class LogDetector:
    """Regex-based log line detector.

    Evaluates each incoming log line against a list of compiled regex rules.
    The first matching rule determines the severity and error type.

    Args:
        rules:  Optional list of ``_Rule`` objects.  Defaults to the built-in
                rule set.  Pass an empty list to disable all detection.
    """

    def __init__(self, rules: list[_Rule] | None = None) -> None:
        # Copy the default rules to avoid mutating the global _DEFAULT_RULES
        if rules is not None:
            self._rules: list[_Rule] = list(rules)
        else:
            self._rules: list[_Rule] = list(_DEFAULT_RULES)

    # -- public API ----------------------------------------------------------

    def detect(self, text: str) -> DetectionResult:
        """Evaluate *text* against all detection rules.

        Returns a ``DetectionResult`` with ``is_incident=True`` when at least
        one rule matches, along with the matched severity and error type.

        Args:
            text: The raw log line text to evaluate.

        Returns:
            A ``DetectionResult`` describing whether this line is an incident.
        """
        for rule in self._rules:
            if rule.pattern.search(text):
                return DetectionResult(
                    is_incident=True,
                    severity=rule.severity,
                    error_type=rule.error_type,
                )
        return DetectionResult(is_incident=False)

    @property
    def rule_count(self) -> int:
        """Number of active detection rules."""
        return len(self._rules)

    def add_rule(self, pattern: str, severity: WatcherSeverity, error_type: str) -> None:
        """Add a custom detection rule at runtime.

        Args:
            pattern:  Regex pattern string.
            severity: Severity to assign on match.
            error_type: Human-readable error classification.
        """
        self._rules.insert(0, _Rule(
            pattern=re.compile(pattern, re.IGNORECASE),
            severity=severity,
            error_type=error_type,
        ))

    def remove_rule_by_error_type(self, error_type: str) -> None:
        """Remove a rule by its error_type label.

        Args:
            error_type: The error_type string of the rule to remove.
        """
        self._rules = [r for r in self._rules if r.error_type != error_type]


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def detect(text: str) -> DetectionResult:
    """Quick one-shot detection using the default rule set.

    Args:
        text: The raw log line text to evaluate.

    Returns:
        A ``DetectionResult`` describing whether this line is an incident.
    """
    return LogDetector().detect(text)
