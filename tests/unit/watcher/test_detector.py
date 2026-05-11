"""Unit tests for the log detector (regex-based error detection)."""

import pytest

from src.core.watcher.detector import LogDetector, _DEFAULT_RULES
from src.core.watcher.models import WatcherSeverity


class TestLogDetectorDefaultRules:
    """Test that default detection rules match expected patterns."""

    @pytest.mark.parametrize(
        "text,expected_severity,expected_type",
        [
            # CRITICAL
            ("OOMKilled in payment-service-7d4f", WatcherSeverity.CRITICAL, "OOMKilled"),
            ("Out of memory: killed process 12345 (java)", WatcherSeverity.CRITICAL, "OutOfMemoryKill"),
            ("Network partition detected between zones", WatcherSeverity.CRITICAL, "NetworkPartition"),
            ("quorum at risk for cluster", WatcherSeverity.CRITICAL, "ClusterQuorumRisk"),
            ("Data corruption detected in block 42", WatcherSeverity.CRITICAL, "DataCorruption"),
            ("Database primary failover initiated", WatcherSeverity.CRITICAL, "DatabaseFailover"),
            ("SSL certificate expired for domain", WatcherSeverity.CRITICAL, "SSLCertificateExpired"),
            # HIGH
            ("Traceback (most recent call last)", WatcherSeverity.HIGH, "ExceptionTraceback"),
            ("HTTP 503 from upstream service", WatcherSeverity.HIGH, "HTTP5xx"),
            ("HTTP 500 Internal Server Error", WatcherSeverity.HIGH, "HTTP5xx"),
            ("Connection refused to database host", WatcherSeverity.HIGH, "ConnectionRefused"),
            ("ECONNREFUSED 127.0.0.1:5432", WatcherSeverity.HIGH, "ConnectionRefused"),
            ("request timeout after 30s", WatcherSeverity.HIGH, "Timeout"),
            ("connection timed out", WatcherSeverity.HIGH, "Timeout"),
            ("Circuit breaker OPEN for payment-service", WatcherSeverity.HIGH, "CircuitBreakerOpen"),
            ("retry exhausted after 3 retries", WatcherSeverity.HIGH, "RetryExhausted"),
            ("Pod crash-looping: OOMKilled", WatcherSeverity.CRITICAL, "OOMKilled"),
            ("Disk space critical on /dev/sda1", WatcherSeverity.HIGH, "DiskSpaceCritical"),
            ("no space left on device", WatcherSeverity.HIGH, "DiskSpaceCritical"),
            # MEDIUM
            ("ERROR: connection pool exhausted", WatcherSeverity.MEDIUM, "ErrorMessage"),
            ("Redis connection lost: READERR OOM", WatcherSeverity.MEDIUM, "RedisError"),
            ("liveness check failed for pod", WatcherSeverity.MEDIUM, "KubernetesProbeFailed"),
            ("probe failed: connection refused", WatcherSeverity.HIGH, "ConnectionRefused"),
            ("consumer lag exceeded 10000", WatcherSeverity.MEDIUM, "ConsumerLag"),
            ("invalid JSON in response body", WatcherSeverity.MEDIUM, "MalformedResponse"),
            # LOW
            ("WARN: high memory usage", WatcherSeverity.LOW, "WarningMessage"),
            ("Retry attempt 2/5 for request", WatcherSeverity.LOW, "RetryAttempt"),
            ("Circuit breaker half-open for inventory", WatcherSeverity.LOW, "CircuitBreakerHalfOpen"),
            ("Memory usage above 80% threshold", WatcherSeverity.LOW, "MemoryThreshold"),
            ("Response time exceeded 500ms threshold", WatcherSeverity.LOW, "LatencyThreshold"),
        ],
    )
    def test_detection_rules(self, text: str, expected_severity: WatcherSeverity,
                             expected_type: str) -> None:
        """Detection rules match expected severity and error type."""
        detector = LogDetector()
        result = detector.detect(text)

        assert result.is_incident is True
        assert result.severity == expected_severity
        assert result.error_type == expected_type

    def test_no_match_returns_not_incident(self) -> None:
        """Normal log lines should not be detected as incidents."""
        detector = LogDetector()
        
        normal_lines = [
            "GET /api/v1/users 200 OK (12ms)",
            "Health check passed — all dependencies healthy",
            "Cache hit ratio: 94.2%",
            "Starting request processing",
            "Connection established to db-primary:5432",
        ]
        
        for line in normal_lines:
            result = detector.detect(line)
            assert result.is_incident is False, f"Expected no match for: {line}"

    def test_rule_count(self) -> None:
        """Detector should have the default number of rules."""
        detector = LogDetector()
        assert detector.rule_count == len(_DEFAULT_RULES)
        assert detector.rule_count > 20


class TestLogDetectorCustomRules:
    """Test custom rule management."""

    def test_add_custom_rule(self) -> None:
        """Adding a custom rule should detect new patterns."""
        detector = LogDetector()
        initial_count = detector.rule_count
        
        detector.add_rule(
            pattern=r"CUSTOM_ERROR_CODE_42",
            severity=WatcherSeverity.HIGH,
            error_type="CustomError",
        )
        
        assert detector.rule_count == initial_count + 1
        result = detector.detect("Got CUSTOM_ERROR_CODE_42 from upstream")
        assert result.is_incident is True
        assert result.severity == WatcherSeverity.HIGH
        assert result.error_type == "CustomError"

    def test_remove_rule_by_error_type(self) -> None:
        """Removing a rule should stop detection for that error type."""
        detector = LogDetector()
        initial_count = detector.rule_count
        
        # Remove an existing rule
        detector.remove_rule_by_error_type("WarningMessage")
        
        assert detector.rule_count == initial_count - 1
        
        # Warning lines should no longer match
        result = detector.detect("WARN: something happened")
        assert result.is_incident is False

    def test_custom_rule_takes_precedence(self) -> None:
        """Custom rules added first should match before default rules."""
        detector = LogDetector()
        
        # Add a custom rule that matches ERROR but with different severity
        detector.add_rule(
            pattern=r"\bERROR\b",
            severity=WatcherSeverity.CRITICAL,
            error_type="CriticalErrorMessage",
        )
        
        result = detector.detect("ERROR: something went wrong")
        assert result.is_incident is True
        assert result.severity == WatcherSeverity.CRITICAL
        assert result.error_type == "CriticalErrorMessage"


class TestDetectFunction:
    """Test the convenience detect() function."""

    def test_detect_function_basic(self) -> None:
        """The detect() function should work with default rules."""
        from src.core.watcher.detector import detect
        
        result = detect("ERROR: connection failed")
        assert result.is_incident is True
        assert result.severity == WatcherSeverity.MEDIUM

    def test_detect_function_no_match(self) -> None:
        """The detect() function should return non-incident for normal lines."""
        from src.core.watcher.detector import detect
        
        result = detect("INFO: all good")
        assert result.is_incident is False


class TestSeverityOrdering:
    """Test severity level ordering and comparison."""

    def test_severity_enum_values(self) -> None:
        """Severity enum should have expected values."""
        assert WatcherSeverity.LOW.value == "low"
        assert WatcherSeverity.MEDIUM.value == "medium"
        assert WatcherSeverity.HIGH.value == "high"
        assert WatcherSeverity.CRITICAL.value == "critical"

    def test_severity_ranking(self) -> None:
        """Watcher should rank severities correctly."""
        from src.core.watcher.watcher import LogWatcher
        
        assert LogWatcher._severity_rank(WatcherSeverity.LOW) < \
               LogWatcher._severity_rank(WatcherSeverity.MEDIUM)
        assert LogWatcher._severity_rank(WatcherSeverity.MEDIUM) < \
               LogWatcher._severity_rank(WatcherSeverity.HIGH)
        assert LogWatcher._severity_rank(WatcherSeverity.HIGH) < \
               LogWatcher._severity_rank(WatcherSeverity.CRITICAL)
