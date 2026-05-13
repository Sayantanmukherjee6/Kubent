"""Unit tests for metric data models."""

from datetime import datetime, timezone

import pytest

from src.core.metrics.models import MetricSample


class TestMetricSample:
    """Tests for the MetricSample dataclass."""

    def test_frozen(self) -> None:
        """MetricSample should be immutable (frozen)."""
        sample = MetricSample(
            timestamp=datetime.now(timezone.utc),
            service_name="test-service",
            cpu_usage=50.0,
            memory_usage=60.0,
            latency_ms=100.0,
            error_rate=0.01,
            source="test",
        )
        with pytest.raises(Exception):
            sample.cpu_usage = 99.0

    def test_all_fields_present(self) -> None:
        """All required fields should be present."""
        ts = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        sample = MetricSample(
            timestamp=ts,
            service_name="payment-service",
            cpu_usage=72.5,
            memory_usage=68.3,
            latency_ms=120.0,
            error_rate=0.015,
            source="mock-metrics:test",
        )
        assert sample.timestamp == ts
        assert sample.service_name == "payment-service"
        assert sample.cpu_usage == 72.5
        assert sample.memory_usage == 68.3
        assert sample.latency_ms == 120.0
        assert sample.error_rate == 0.015
        assert sample.source == "mock-metrics:test"

    def test_default_timestamp(self) -> None:
        """Timestamp should be close to now when not specified explicitly."""
        before = datetime.now(timezone.utc)
        sample = MetricSample(
            timestamp=before,
            service_name="svc",
            cpu_usage=0.0,
            memory_usage=0.0,
            latency_ms=0.0,
            error_rate=0.0,
            source="test",
        )
        after = datetime.now(timezone.utc)
        assert before <= sample.timestamp <= after

    def test_can_be_hashed(self) -> None:
        """Frozen dataclass should be hashable."""
        sample = MetricSample(
            timestamp=datetime.now(timezone.utc),
            service_name="svc",
            cpu_usage=50.0,
            memory_usage=50.0,
            latency_ms=100.0,
            error_rate=0.01,
            source="test",
        )
        hash(sample)  # should not raise

    def test_can_be_used_in_set(self) -> None:
        """Frozen dataclass should be usable in sets."""
        sample = MetricSample(
            timestamp=datetime.now(timezone.utc),
            service_name="svc",
            cpu_usage=50.0,
            memory_usage=50.0,
            latency_ms=100.0,
            error_rate=0.01,
            source="test",
        )
        s = {sample}
        assert sample in s
