"""Unit tests for the deduplication tracker."""

from datetime import datetime, timedelta, timezone

import pytest

from src.core.watcher.watcher import _DedupTracker


class TestDedupTracker:
    """Tests for the in-memory deduplication tracker."""

    def test_first_occurrence(self) -> None:
        """First occurrence should return count of 1."""
        tracker = _DedupTracker()
        now = datetime.now(timezone.utc)
        
        count = tracker.record("hash1", now)
        
        assert count == 1

    def test_duplicate_occurrence(self) -> None:
        """Duplicate occurrences should increment the count."""
        tracker = _DedupTracker()
        now = datetime.now(timezone.utc)
        
        tracker.record("hash1", now)
        count = tracker.record("hash1", now)
        
        assert count == 2

    def test_different_hashes(self) -> None:
        """Different hashes should be tracked independently."""
        tracker = _DedupTracker()
        now = datetime.now(timezone.utc)
        
        tracker.record("hash1", now)
        tracker.record("hash2", now)
        
        assert tracker.get_count("hash1") == 1
        assert tracker.get_count("hash2") == 1

    def test_unknown_hash(self) -> None:
        """Unknown hashes should return count of 0."""
        tracker = _DedupTracker()
        assert tracker.get_count("unknown_hash") == 0

    def test_should_emit_after_threshold(self) -> None:
        """should_emit should return True when count meets threshold."""
        tracker = _DedupTracker(repeat_threshold=1)
        now = datetime.now(timezone.utc)
        
        tracker.record("hash1", now)
        
        assert tracker.should_emit("hash1", now) is True

    def test_should_not_emit_below_threshold(self) -> None:
        """should_emit should return False when count is below threshold."""
        tracker = _DedupTracker(repeat_threshold=3)
        now = datetime.now(timezone.utc)
        
        tracker.record("hash1", now)
        
        assert tracker.should_emit("hash1", now) is False

    def test_should_emit_after_enough_occurrences(self) -> None:
        """should_emit should return True after enough occurrences."""
        tracker = _DedupTracker(repeat_threshold=3)
        now = datetime.now(timezone.utc)
        
        tracker.record("hash1", now)
        tracker.record("hash1", now)
        tracker.record("hash1", now)
        
        assert tracker.should_emit("hash1", now) is True

    def test_should_not_emit_unknown_hash(self) -> None:
        """should_emit should return False for unknown hashes."""
        tracker = _DedupTracker()
        now = datetime.now(timezone.utc)
        
        assert tracker.should_emit("unknown_hash", now) is False


class TestDedupTTL:
    """Tests for TTL-based expiration of dedup entries."""

    def test_expired_entry(self) -> None:
        """Expired entries should not be emitted."""
        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        tracker = _DedupTracker(ttl_seconds=60.0)  # 1 minute TTL
        
        tracker.record("hash1", base_time)
        
        # Within TTL
        assert tracker.should_emit("hash1", base_time + timedelta(seconds=30)) is True
        
        # Expired
        assert tracker.should_emit("hash1", base_time + timedelta(seconds=90)) is False

    def test_cleanup_expired(self) -> None:
        """cleanup should remove expired entries."""
        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        tracker = _DedupTracker(ttl_seconds=60.0)
        
        tracker.record("hash1", base_time)
        tracker.record("hash2", base_time)
        tracker.record("hash3", base_time + timedelta(seconds=30))
        
        removed = tracker.cleanup(base_time + timedelta(seconds=90))
        
        assert removed == 2  # hash1 and hash2 expired
        assert tracker.get_count("hash3") == 1

    def test_cleanup_no_expired(self) -> None:
        """cleanup should return 0 when no entries are expired."""
        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        tracker = _DedupTracker(ttl_seconds=60.0)
        
        tracker.record("hash1", base_time)
        
        removed = tracker.cleanup(base_time + timedelta(seconds=30))
        
        assert removed == 0


class TestDedupConfig:
    """Tests for configurable dedup settings."""

    def test_custom_ttl(self) -> None:
        """Custom TTL should be respected."""
        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        tracker = _DedupTracker(ttl_seconds=5.0)  # Very short TTL
        
        tracker.record("hash1", base_time)
        
        # Should expire after 5 seconds
        assert tracker.should_emit("hash1", base_time + timedelta(seconds=6)) is False

    def test_custom_threshold(self) -> None:
        """Custom repeat threshold should be respected."""
        tracker = _DedupTracker(repeat_threshold=5)
        now = datetime.now(timezone.utc)
        
        for _ in range(4):
            tracker.record("hash1", now)
        
        assert tracker.should_emit("hash1", now) is False
        
        tracker.record("hash1", now)
        assert tracker.should_emit("hash1", now) is True


class TestDedupPeriodicCleanup:
    """Tests for periodic cleanup invocation and bounded memory growth."""

    def test_cleanup_removes_expired_entries(self) -> None:
        """Expired entries should be removed by cleanup()."""
        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        tracker = _DedupTracker(ttl_seconds=60.0)

        # Add entries with different ages
        tracker.record("old_hash", base_time)
        tracker.record("old_hash2", base_time)
        tracker.record("fresh_hash", base_time + timedelta(seconds=30))

        # Cleanup after TTL expires for old entries
        removed = tracker.cleanup(base_time + timedelta(seconds=90))

        assert removed == 2
        assert "old_hash" not in tracker._entries
        assert "old_hash2" not in tracker._entries
        assert "fresh_hash" in tracker._entries

    def test_cleanup_bounded_memory(self) -> None:
        """Memory growth should be bounded by periodic cleanup."""
        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        tracker = _DedupTracker(ttl_seconds=10.0)

        # Simulate many unique hashes expiring over time
        now = base_time + timedelta(seconds=20)
        for i in range(50):
            tracker.record(f"hash_{i}", base_time)  # all will be expired

        assert len(tracker._entries) == 50

        # After cleanup, all expired entries removed
        removed = tracker.cleanup(now)
        assert removed == 50
        assert len(tracker._entries) == 0

    def test_cleanup_keeps_fresh_entries(self) -> None:
        """cleanup() should not remove non-expired entries."""
        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        tracker = _DedupTracker(ttl_seconds=60.0)

        for i in range(20):
            tracker.record(f"fresh_hash_{i}", base_time + timedelta(seconds=30))

        removed = tracker.cleanup(base_time + timedelta(seconds=45))

        assert removed == 0
        assert len(tracker._entries) == 20

    def test_cleanup_returns_zero_when_empty(self) -> None:
        """cleanup() on empty tracker should return 0."""
        tracker = _DedupTracker()
        now = datetime.now(timezone.utc)
        assert tracker.cleanup(now) == 0
