"""Unit tests for the mock log generator and log source configuration."""

from datetime import datetime, timezone

from mocks.generators.log_generator import (
    LogEntry,
    generate_log_entries,
    generate_mock_logs_text,
)
from src.config.settings import Settings


class TestLogEntry:
    """Tests for the LogEntry dataclass."""

    def test_format_basic(self) -> None:
        """LogEntry.format() should produce a K8s-style log line."""
        ts = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        entry = LogEntry(
            timestamp=ts,
            severity="error",
            service="auth-service",
            message="Connection refused to db-primary:5432",
            pod="auth-service-5c8d7f9a2b",
        )
        formatted = entry.format()
        assert "2025-01-15T10:30:00.000Z" in formatted
        assert "[ERROR   ]" in formatted
        assert "pod/auth-service-5c8d7f9a2b" in formatted
        assert "Connection refused to db-primary:5432" in formatted

    def test_format_without_pod(self) -> None:
        """LogEntry without a pod should use the service name."""
        ts = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        entry = LogEntry(
            timestamp=ts,
            severity="info",
            service="gateway",
            message="GET /api/v1/users 200 OK (12ms)",
        )
        formatted = entry.format()
        assert "gateway:" in formatted
        assert "pod/" not in formatted


class TestGenerateLogEntries:
    """Tests for the generate_log_entries function."""

    def test_returns_correct_count(self) -> None:
        """Should return exactly count entries."""
        entries = generate_log_entries(count=20)
        assert len(entries) == 20

    def test_severity_cycle(self) -> None:
        """Severities should cycle through the provided list."""
        entries = generate_log_entries(
            count=8,
            severities=["info", "error"],
        )
        severities = [e.severity for e in entries]
        assert severities == ["info", "error", "info", "error", "info", "error", "info", "error"]

    def test_service_cycle(self) -> None:
        """Services should cycle through the provided list."""
        services = ["auth-service", "payment-service"]
        entries = generate_log_entries(count=6, services=services)
        actual = [e.service for e in entries]
        assert actual == ["auth-service", "payment-service"] * 3

    def test_timestamps_are_ordered(self) -> None:
        """Timestamps should generally be in ascending order."""
        entries = generate_log_entries(count=10)
        timestamps = [e.timestamp for e in entries]
        # With jitter, we allow a few out-of-order, but most should be ordered
        ordered_count = sum(
            1 for i in range(1, len(timestamps))
            if timestamps[i] >= timestamps[i - 1]
        )
        assert ordered_count >= len(timestamps) * 0.5

    def test_tracebacks_on_error_entries(self) -> None:
        """ERROR and CRITICAL entries should include tracebacks by default."""
        entries = generate_log_entries(
            count=4,
            severities=["info", "error"],
            include_tracebacks=True,
        )
        for entry in entries:
            if entry.severity in ("error", "critical"):
                assert entry.include_traceback is True

    def test_no_tracebacks_when_disabled(self) -> None:
        """No entries should have tracebacks when disabled."""
        entries = generate_log_entries(
            count=4,
            severities=["info", "error"],
            include_tracebacks=False,
        )
        for entry in entries:
            assert entry.include_traceback is False

    def test_custom_base_time(self) -> None:
        """Should use the provided base_time."""
        base = datetime(2024, 6, 15, 3, 0, 0, tzinfo=timezone.utc)
        entries = generate_log_entries(count=3, base_time=base)
        for entry in entries:
            assert entry.timestamp >= base

    def test_default_services(self) -> None:
        """Default services should include the expected K8s-style names."""
        entries = generate_log_entries(count=8)
        services = {e.service for e in entries}
        assert "auth-service" in services
        assert "payment-service" in services
        assert "gateway" in services


class TestGenerateMockLogsText:
    """Tests for the generate_mock_logs_text convenience function."""

    def test_returns_string(self) -> None:
        result = generate_mock_logs_text(count=5)
        assert isinstance(result, str)

    def test_contains_newlines(self) -> None:
        result = generate_mock_logs_text(count=10)
        lines = [l for l in result.splitlines() if l.strip()]
        assert len(lines) >= 10

    def test_no_llm_calls(self) -> None:
        """This function should never call any LLM provider."""
        # If it imports src.providers, something is wrong
        import sys
        before = set(sys.modules.keys())
        generate_mock_logs_text(count=3)
        after = set(sys.modules.keys())
        provider_modules = {m for m in after - before if "providers" in m}
        assert len(provider_modules) == 0, f"Unexpected LLM imports: {provider_modules}"


class TestSettingsMockConfig:
    """Tests for mock log source settings."""

    def test_default_mock_settings(self) -> None:
        settings = Settings()
        assert settings.mock_log_count == 50
        assert settings.mock_log_interval == 1.0
        assert "auth-service" in settings.mock_log_services
        assert "payment-service" in settings.mock_log_services

    def test_env_override_mock_settings(self, monkeypatch: object) -> None:
        monkeypatch.setenv("MOCK_LOG_COUNT", "200")
        monkeypatch.setenv("MOCK_LOG_INTERVAL", "0.5")
        settings = Settings()
        assert settings.mock_log_count == 200
        assert settings.mock_log_interval == 0.5
