"""Unit tests for the heuristic-based incident prediction engine.

Tests cover:
    - rolling window behavior
    - threshold triggering
    - event expiry (window overflow)
    - repeated incident escalation
    - multi-service isolation
    - bounded memory behavior
"""

from datetime import datetime, timezone

import pytest

from src.core.predictor.models import PredictorEvent, RiskLevel
from src.core.predictor.predictor import HeuristicPredictor, HeuristicRule
from src.core.watcher.models import IncidentEvent, WatcherSeverity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_incident(
    service_name: str = "web-api",
    error_type: str = "HTTP5xx",
    severity: WatcherSeverity = WatcherSeverity.HIGH,
) -> IncidentEvent:
    """Create a minimal IncidentEvent for predictor tests."""
    return IncidentEvent(
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        service_name=service_name,
        severity=severity,
        error_type=error_type,
        raw_line=f"[{service_name}] {error_type} occurred",
    )


# ---------------------------------------------------------------------------
# Rolling window behavior
# ---------------------------------------------------------------------------

class TestRollingWindow:
    """Tests for rolling-window mechanics."""

    async def test_window_truncates_at_max_size(self) -> None:
        """Events beyond window_size should cause oldest to be dropped."""
        predictor = HeuristicPredictor(window_size=3)

        # Fill the window with 4 events — only last 3 should remain
        for i in range(4):
            result = await predictor.process(
                _make_incident(error_type=f"HTTP5xx-{i}")
            )
            # No prediction yet (threshold is 3, but we need to check after fill)

        # The window should now contain exactly 3 events
        window = predictor._windows["web-api"]
        assert len(window._deque) == 3

    async def test_oldest_events_expire_from_window(self) -> None:
        """Oldest events should fall out of the rolling window."""
        predictor = HeuristicPredictor(window_size=3, rules=(
            HeuristicRule(
                name="test_rule",
                patterns=("HTTP5xx",),
                threshold=2,
                risk_level=RiskLevel.HIGH,
                description="Test pattern",
            ),
        ))

        # Add 3 matching events — should trigger
        for i in range(3):
            await predictor.process(_make_incident(error_type="HTTP5xx"))

        # Now add a non-matching event to push out old ones
        await predictor.process(_make_incident(error_type="Timeout"))

        # Only 2 HTTP5xx remain in window — still at threshold
        window = predictor._windows["web-api"]
        count = sum(1 for fp in window._deque if "HTTP5xx" in fp)
        assert count == 2

    async def test_window_resets_on_new_service(self) -> None:
        """A new service should get a fresh window."""
        predictor = HeuristicPredictor(window_size=3, rules=(
            HeuristicRule(
                name="test_rule",
                patterns=("HTTP5xx",),
                threshold=2,
                risk_level=RiskLevel.HIGH,
                description="Test pattern",
            ),
        ))

        # Fill window for service "alpha"
        await predictor.process(_make_incident(service_name="alpha", error_type="HTTP5xx"))
        await predictor.process(_make_incident(service_name="alpha", error_type="HTTP5xx"))

        # Service "beta" should have no predictions yet
        result = await predictor.process(_make_incident(service_name="beta", error_type="HTTP5xx"))
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Threshold triggering
# ---------------------------------------------------------------------------

class TestThresholdTriggering:
    """Tests for threshold-based prediction triggering."""

    async def test_below_threshold_no_prediction(self) -> None:
        """Events below threshold should not produce predictions."""
        predictor = HeuristicPredictor(window_size=10, rules=(
            HeuristicRule(
                name="test_rule",
                patterns=("HTTP5xx",),
                threshold=5,
                risk_level=RiskLevel.HIGH,
                description="Test pattern",
            ),
        ))

        for i in range(4):
            result = await predictor.process(_make_incident(error_type="HTTP5xx"))
            assert len(result) == 0

    async def test_at_threshold_triggers_prediction(self) -> None:
        """Events meeting threshold should produce a prediction."""
        predictor = HeuristicPredictor(window_size=10, rules=(
            HeuristicRule(
                name="test_rule",
                patterns=("HTTP5xx",),
                threshold=3,
                risk_level=RiskLevel.HIGH,
                description="Test pattern",
            ),
        ))

        for i in range(3):
            await predictor.process(_make_incident(error_type="HTTP5xx"))

        # The 3rd event should trigger
        result = await predictor.process(_make_incident(error_type="HTTP5xx"))
        assert len(result) == 1
        assert result[0].trigger_count >= 3

    async def test_default_http_5xx_threshold(self) -> None:
        """Default HTTP 5xx rule should trigger at threshold of 3."""
        predictor = HeuristicPredictor()

        for i in range(3):
            await predictor.process(_make_incident(error_type="HTTP5xx"))

        result = await predictor.process(_make_incident(error_type="HTTP5xx"))
        assert len(result) == 1
        assert result[0].pattern == "Repeated HTTP 5xx error spikes detected"
        assert result[0].risk_level == RiskLevel.HIGH

    async def test_default_oomkilled_lower_threshold(self) -> None:
        """Default OOMKilled rule should trigger at threshold of 2."""
        predictor = HeuristicPredictor()

        for i in range(2):
            await predictor.process(_make_incident(error_type="OOMKilled"))

        result = await predictor.process(_make_incident(error_type="OOMKilled"))
        assert len(result) == 1
        assert result[0].risk_level == RiskLevel.CRITICAL

    async def test_multiple_rules_trigger_simultaneously(self) -> None:
        """Multiple rules matching the same event should all trigger."""
        predictor = HeuristicPredictor(window_size=20, rules=(
            HeuristicRule(
                name="rule_a",
                patterns=("ERROR",),
                threshold=1,
                risk_level=RiskLevel.HIGH,
                description="Pattern A",
            ),
            HeuristicRule(
                name="rule_b",
                patterns=("ERROR",),
                threshold=1,
                risk_level=RiskLevel.CRITICAL,
                description="Pattern B",
            ),
        ))

        result = await predictor.process(_make_incident(error_type="ERROR"))
        assert len(result) == 2
        patterns = {r.pattern for r in result}
        assert "Pattern A" in patterns
        assert "Pattern B" in patterns

    async def test_no_match_returns_empty(self) -> None:
        """Events not matching any rule should return empty predictions."""
        predictor = HeuristicPredictor(window_size=10, rules=(
            HeuristicRule(
                name="test_rule",
                patterns=("HTTP5xx",),
                threshold=1,
                risk_level=RiskLevel.HIGH,
                description="Test pattern",
            ),
        ))

        result = await predictor.process(_make_incident(error_type="Timeout"))
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Event expiry (window overflow)
# ---------------------------------------------------------------------------

class TestEventExpiry:
    """Tests for event expiry via window overflow."""

    async def test_old_events_no_longer_count(self) -> None:
        """Events that fell out of the window should no longer count."""
        predictor = HeuristicPredictor(window_size=3, rules=(
            HeuristicRule(
                name="test_rule",
                patterns=("HTTP5xx",),
                threshold=2,
                risk_level=RiskLevel.HIGH,
                description="Test pattern",
            ),
        ))

        # Fill window with 3 matching events — triggers at count 2+
        for i in range(3):
            await predictor.process(_make_incident(error_type="HTTP5xx"))

        # Add 2 non-matching events to push out all HTTP5xx entries
        for i in range(2):
            await predictor.process(_make_incident(error_type="Timeout"))

        # Window now has: [HTTP5xx, Timeout, Timeout] — only 1 HTTP5xx remains
        result = await predictor.process(_make_incident(error_type="Timeout"))
        assert len(result) == 0  # Below threshold of 2

    async def test_window_size_zero_still_works(self) -> None:
        """Even a window of size 1 should function correctly."""
        predictor = HeuristicPredictor(window_size=1, rules=(
            HeuristicRule(
                name="test_rule",
                patterns=("HTTP5xx",),
                threshold=1,
                risk_level=RiskLevel.HIGH,
                description="Test pattern",
            ),
        ))

        result = await predictor.process(_make_incident(error_type="HTTP5xx"))
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Repeated incident escalation
# ---------------------------------------------------------------------------

class TestRepeatedIncidentEscalation:
    """Tests for repeated incident escalation behavior."""

    async def test_trigger_count_increases_with_repeats(self) -> None:
        """Each additional matching event should increase trigger_count."""
        predictor = HeuristicPredictor(window_size=20, rules=(
            HeuristicRule(
                name="test_rule",
                patterns=("HTTP5xx",),
                threshold=2,
                risk_level=RiskLevel.HIGH,
                description="Test pattern",
            ),
        ))

        # First trigger at count 2
        await predictor.process(_make_incident(error_type="HTTP5xx"))
        result1 = await predictor.process(_make_incident(error_type="HTTP5xx"))
        assert result1[0].trigger_count == 2

        # Second trigger at count 3
        result2 = await predictor.process(_make_incident(error_type="HTTP5xx"))
        assert result2[0].trigger_count == 3

    async def test_predictions_returned_on_each_trigger(self) -> None:
        """Each event that meets threshold should return a prediction."""
        predictor = HeuristicPredictor(window_size=20, rules=(
            HeuristicRule(
                name="test_rule",
                patterns=("HTTP5xx",),
                threshold=2,
                risk_level=RiskLevel.HIGH,
                description="Test pattern",
            ),
        ))

        await predictor.process(_make_incident(error_type="HTTP5xx"))

        # Each subsequent event should produce a prediction
        for i in range(5):
            result = await predictor.process(_make_incident(error_type="HTTP5xx"))
            assert len(result) == 1
            assert result[0].trigger_count == i + 2

    async def test_escalation_with_different_severity(self) -> None:
        """Repeated incidents should escalate with increasing counts."""
        predictor = HeuristicPredictor(window_size=50, rules=(
            HeuristicRule(
                name="test_rule",
                patterns=("OOMKilled",),
                threshold=2,
                risk_level=RiskLevel.CRITICAL,
                description="Repeated OOMKilled events detected",
            ),
        ))

        await predictor.process(_make_incident(error_type="OOMKilled"))

        counts = []
        for _ in range(4):
            result = await predictor.process(_make_incident(error_type="OOMKilled"))
            counts.append(result[0].trigger_count)

        assert counts == [2, 3, 4, 5]


# ---------------------------------------------------------------------------
# Multi-service isolation
# ---------------------------------------------------------------------------

class TestMultiServiceIsolation:
    """Tests for per-service window isolation."""

    async def test_services_have_independent_windows(self) -> None:
        """Each service should maintain its own rolling window."""
        predictor = HeuristicPredictor(window_size=10, rules=(
            HeuristicRule(
                name="test_rule",
                patterns=("HTTP5xx",),
                threshold=2,
                risk_level=RiskLevel.HIGH,
                description="Test pattern",
            ),
        ))

        # Service "alpha" gets 1 event — below threshold
        await predictor.process(_make_incident(service_name="alpha", error_type="HTTP5xx"))

        # Service "beta" gets 2 events — should trigger independently
        await predictor.process(_make_incident(service_name="beta", error_type="HTTP5xx"))
        result = await predictor.process(_make_incident(service_name="beta", error_type="HTTP5xx"))

        assert len(result) == 1
        assert result[0].service_name == "beta"

    async def test_reset_service_clears_only_that_service(self) -> None:
        """reset_service should only clear the specified service."""
        predictor = HeuristicPredictor(window_size=10, rules=(
            HeuristicRule(
                name="test_rule",
                patterns=("HTTP5xx",),
                threshold=2,
                risk_level=RiskLevel.HIGH,
                description="Test pattern",
            ),
        ))

        await predictor.process(_make_incident(service_name="alpha", error_type="HTTP5xx"))
        await predictor.process(_make_incident(service_name="beta", error_type="HTTP5xx"))

        await predictor.reset_service("alpha")

        # Alpha should have no predictions now (threshold is 2, only 1 event)
        result_alpha = await predictor.process(_make_incident(service_name="alpha", error_type="HTTP5xx"))
        assert len(result_alpha) == 0

        # Beta should still have its events
        result_beta = await predictor.process(_make_incident(service_name="beta", error_type="HTTP5xx"))
        assert len(result_beta) == 1

    async def test_reset_all_clears_everything(self) -> None:
        """reset_all should clear all service windows."""
        predictor = HeuristicPredictor(window_size=10, rules=(
            HeuristicRule(
                name="test_rule",
                patterns=("HTTP5xx",),
                threshold=1,
                risk_level=RiskLevel.HIGH,
                description="Test pattern",
            ),
        ))

        await predictor.process(_make_incident(service_name="alpha", error_type="HTTP5xx"))
        await predictor.process(_make_incident(service_name="beta", error_type="HTTP5xx"))

        await predictor.reset_all()

        # Both services should have empty windows
        assert "alpha" not in predictor._windows
        assert "beta" not in predictor._windows

    async def test_cross_service_events_dont_interfere(self) -> None:
        """Events from different services should never affect each other's counts."""
        predictor = HeuristicPredictor(window_size=10, rules=(
            HeuristicRule(
                name="test_rule",
                patterns=("HTTP5xx",),
                threshold=3,
                risk_level=RiskLevel.HIGH,
                description="Test pattern",
            ),
        ))

        # Add 2 events to each of 3 services — none should trigger
        for svc in ["svc-a", "svc-b", "svc-c"]:
            await predictor.process(_make_incident(service_name=svc, error_type="HTTP5xx"))
            await predictor.process(_make_incident(service_name=svc, error_type="HTTP5xx"))

        # No predictions yet
        for svc in ["svc-a", "svc-b", "svc-c"]:
            result = await predictor.process(_make_incident(service_name=svc, error_type="HTTP5xx"))
            assert len(result) == 1  # Only the triggering service gets a prediction
            assert result[0].service_name == svc


# ---------------------------------------------------------------------------
# Bounded memory behavior
# ---------------------------------------------------------------------------

class TestBoundedMemory:
    """Tests for bounded memory guarantees."""

    async def test_window_memory_bounded_by_max_size(self) -> None:
        """Window deque should never exceed max_size regardless of input."""
        predictor = HeuristicPredictor(window_size=10)

        # Add 1000 events — window should still be size 10
        for i in range(1000):
            await predictor.process(_make_incident(error_type=f"HTTP5xx-{i}"))

        window = predictor._windows["web-api"]
        assert len(window._deque) == 10

    async def test_many_services_bounded(self) -> None:
        """Memory should be bounded even with many services."""
        predictor = HeuristicPredictor(window_size=5)

        # Create events for 100 different services
        for i in range(100):
            await predictor.process(_make_incident(service_name=f"service-{i}", error_type="HTTP5xx"))

        assert len(predictor._windows) == 100
        for window in predictor._windows.values():
            assert len(window._deque) <= 5

    async def test_reset_frees_memory(self) -> None:
        """reset_service should free the window for that service."""
        predictor = HeuristicPredictor(window_size=200)

        for i in range(10):
            await predictor.process(_make_incident(service_name=f"svc-{i}", error_type="HTTP5xx"))

        assert len(predictor._windows) == 10

        await predictor.reset_service("svc-0")
        assert "svc-0" not in predictor._windows
        assert len(predictor._windows) == 9

    async def test_reset_all_frees_all_memory(self) -> None:
        """reset_all should clear all windows."""
        predictor = HeuristicPredictor(window_size=200)

        for i in range(50):
            await predictor.process(_make_incident(service_name=f"svc-{i}", error_type="HTTP5xx"))

        assert len(predictor._windows) == 50

        await predictor.reset_all()
        assert len(predictor._windows) == 0


# ---------------------------------------------------------------------------
# PredictorEvent model tests
# ---------------------------------------------------------------------------

class TestPredictorEvent:
    """Tests for the PredictorEvent data model."""

    def test_predictor_event_creation(self) -> None:
        """PredictorEvent should be creatable with required fields."""
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        event = PredictorEvent(
            timestamp=ts,
            service_name="web-api",
            risk_level=RiskLevel.HIGH,
            pattern="Test pattern",
            trigger_count=3,
            related_hash="abc123",
        )

        assert event.service_name == "web-api"
        assert event.risk_level == RiskLevel.HIGH
        assert event.trigger_count == 3
        assert event.related_hash == "abc123"

    def test_predictor_event_defaults(self) -> None:
        """PredictorEvent should have sensible defaults."""
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        event = PredictorEvent(
            timestamp=ts,
            service_name="web-api",
            risk_level=RiskLevel.LOW,
            pattern="Test",
            trigger_count=1,
        )

        assert event.related_hash == ""
        assert event.metadata == {}

    def test_predictor_event_str(self) -> None:
        """PredictorEvent.__str__ should produce a readable representation."""
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        event = PredictorEvent(
            timestamp=ts,
            service_name="web-api",
            risk_level=RiskLevel.HIGH,
            pattern="Test pattern",
            trigger_count=5,
        )

        s = str(event)
        assert "high" in s
        assert "web-api" in s
        assert "Test pattern" in s
        assert "5" in s

    def test_predictor_event_is_frozen(self) -> None:
        """PredictorEvent should be immutable."""
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        event = PredictorEvent(
            timestamp=ts,
            service_name="web-api",
            risk_level=RiskLevel.HIGH,
            pattern="Test",
            trigger_count=1,
        )

        with pytest.raises(Exception):
            event.service_name = "other"

    def test_risk_level_values(self) -> None:
        """RiskLevel enum should have expected values."""
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.CRITICAL.value == "critical"


# ---------------------------------------------------------------------------
# HeuristicRule tests
# ---------------------------------------------------------------------------

class TestHeuristicRule:
    """Tests for the HeuristicRule data model."""

    def test_rule_is_frozen(self) -> None:
        """HeuristicRule should be immutable (frozen)."""
        rule = HeuristicRule(
            name="test",
            patterns=("ERROR",),
            threshold=3,
            risk_level=RiskLevel.HIGH,
            description="Test",
        )

        with pytest.raises(Exception):
            rule.threshold = 5

    def test_rule_patterns_tuple(self) -> None:
        """Rule patterns should be a tuple."""
        rule = HeuristicRule(
            name="test",
            patterns=("A", "B", "C"),
            threshold=1,
            risk_level=RiskLevel.LOW,
            description="Test",
        )

        assert isinstance(rule.patterns, tuple)
        assert len(rule.patterns) == 3


# ---------------------------------------------------------------------------
# Default rules verification
# ---------------------------------------------------------------------------

class TestDefaultRules:
    """Tests for the built-in default heuristic rules."""

    async def test_default_rules_exist(self) -> None:
        """HeuristicPredictor should have 4 default rules."""
        predictor = HeuristicPredictor()
        assert len(predictor.rules) == 4

    async def test_default_rule_names(self) -> None:
        """Default rules should have expected names."""
        predictor = HeuristicPredictor()
        names = {r.name for r in predictor.rules}

        assert "repeated_http_5xx" in names
        assert "repeated_timeout" in names
        assert "repeated_oomkilled" in names
        assert "repeated_conn_refused" in names

    async def test_default_http_5xx_threshold_is_3(self) -> None:
        """HTTP 5xx rule should have threshold of 3."""
        predictor = HeuristicPredictor()
        rule = next(r for r in predictor.rules if r.name == "repeated_http_5xx")
        assert rule.threshold == 3

    async def test_default_oomkilled_threshold_is_2(self) -> None:
        """OOMKilled rule should have threshold of 2."""
        predictor = HeuristicPredictor()
        rule = next(r for r in predictor.rules if r.name == "repeated_oomkilled")
        assert rule.threshold == 2

    async def test_default_timeout_threshold_is_3(self) -> None:
        """Timeout rule should have threshold of 3."""
        predictor = HeuristicPredictor()
        rule = next(r for r in predictor.rules if r.name == "repeated_timeout")
        assert rule.threshold == 3

    async def test_default_conn_refused_threshold_is_3(self) -> None:
        """Connection refused rule should have threshold of 3."""
        predictor = HeuristicPredictor()
        rule = next(r for r in predictor.rules if r.name == "repeated_conn_refused")
        assert rule.threshold == 3

    async def test_default_oomkilled_is_critical(self) -> None:
        """OOMKilled rule should have CRITICAL risk level."""
        predictor = HeuristicPredictor()
        rule = next(r for r in predictor.rules if r.name == "repeated_oomkilled")
        assert rule.risk_level == RiskLevel.CRITICAL

    async def test_default_http_5xx_is_high(self) -> None:
        """HTTP 5xx rule should have HIGH risk level."""
        predictor = HeuristicPredictor()
        rule = next(r for r in predictor.rules if r.name == "repeated_http_5xx")
        assert rule.risk_level == RiskLevel.HIGH

    async def test_default_timeout_patterns(self) -> None:
        """Timeout rule should match common timeout patterns."""
        predictor = HeuristicPredictor()
        rule = next(r for r in predictor.rules if r.name == "repeated_timeout")
        assert "Timeout" in rule.patterns
        assert "timed out" in rule.patterns
        assert "deadline exceeded" in rule.patterns

    async def test_default_5xx_patterns(self) -> None:
        """HTTP 5xx rule should match common 5xx patterns."""
        predictor = HeuristicPredictor()
        rule = next(r for r in predictor.rules if r.name == "repeated_http_5xx")
        assert "HTTP5xx" in rule.patterns
        assert "500 " in rule.patterns
        assert "502 " in rule.patterns
        assert "503 " in rule.patterns
        assert "504 " in rule.patterns


# ---------------------------------------------------------------------------
# Custom rules
# ---------------------------------------------------------------------------

class TestCustomRules:
    """Tests for custom heuristic rule configuration."""

    async def test_custom_rules_replace_defaults(self) -> None:
        """Providing custom rules should replace defaults entirely."""
        custom_rule = HeuristicRule(
            name="custom",
            patterns=("CUSTOM",),
            threshold=1,
            risk_level=RiskLevel.MEDIUM,
            description="Custom pattern",
        )
        predictor = HeuristicPredictor(rules=(custom_rule,))

        assert len(predictor.rules) == 1
        assert predictor.rules[0].name == "custom"

    async def test_custom_rule_triggers(self) -> None:
        """Custom rules should trigger predictions normally."""
        custom_rule = HeuristicRule(
            name="custom",
            patterns=("CUSTOM",),
            threshold=2,
            risk_level=RiskLevel.MEDIUM,
            description="Custom pattern",
        )
        predictor = HeuristicPredictor(rules=(custom_rule,))

        await predictor.process(_make_incident(error_type="CUSTOM"))
        result = await predictor.process(_make_incident(error_type="CUSTOM"))

        assert len(result) == 1
        assert result[0].risk_level == RiskLevel.MEDIUM
        assert result[0].pattern == "Custom pattern"

    async def test_custom_rule_with_high_threshold(self) -> None:
        """High-threshold custom rules should require more events."""
        custom_rule = HeuristicRule(
            name="custom",
            patterns=("ERROR",),
            threshold=10,
            risk_level=RiskLevel.LOW,
            description="Custom pattern",
        )
        predictor = HeuristicPredictor(rules=(custom_rule,))

        for i in range(10):
            await predictor.process(_make_incident(error_type="ERROR"))

        # Should trigger on the 10th (10 >= threshold of 10)
        result = await predictor.process(_make_incident(error_type="ERROR"))
        assert len(result) == 1
        assert result[0].trigger_count == 11


# ---------------------------------------------------------------------------
# Async safety (basic lock test)
# ---------------------------------------------------------------------------

class TestAsyncSafety:
    """Basic tests for async lock behavior."""

    async def test_process_is_async_safe(self) -> None:
        """process() should be callable in async context without errors."""
        predictor = HeuristicPredictor()

        # Sequential calls should work fine
        for i in range(10):
            result = await predictor.process(_make_incident(error_type="HTTP5xx"))
            assert isinstance(result, list)

    async def test_reset_is_async_safe(self) -> None:
        """reset_all() should be callable in async context."""
        predictor = HeuristicPredictor()

        await predictor.process(_make_incident())
        await predictor.reset_all()

        assert len(predictor._windows) == 0

    async def test_reset_service_nonexistent(self) -> None:
        """reset_service should not raise for unknown services."""
        predictor = HeuristicPredictor()
        await predictor.reset_service("nonexistent-service")
        # Should not raise
