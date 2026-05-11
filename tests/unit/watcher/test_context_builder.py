"""Unit tests for the context builder and rolling buffer."""

import asyncio

import pytest

from src.core.watcher.context_builder import ContextBuilder, ContextWindow, RollingBuffer


class TestRollingBuffer:
    """Tests for the RollingBuffer class."""

    @pytest.mark.asyncio
    async def test_add_and_get_recent(self) -> None:
        """Adding lines should make them available via get_recent."""
        buffer = RollingBuffer(max_size=10)
        
        await buffer.add("source1", "line 1")
        await buffer.add("source1", "line 2")
        await buffer.add("source1", "line 3")
        
        result = await buffer.get_recent("source1")
        assert result == ["line 1", "line 2", "line 3"]

    @pytest.mark.asyncio
    async def test_max_size_enforced(self) -> None:
        """Buffer should discard oldest lines when max_size is reached."""
        buffer = RollingBuffer(max_size=3)
        
        await buffer.add("src", "line 1")
        await buffer.add("src", "line 2")
        await buffer.add("src", "line 3")
        await buffer.add("src", "line 4")  # Should push out "line 1"
        
        result = await buffer.get_recent("src")
        assert len(result) == 3
        assert result == ["line 2", "line 3", "line 4"]

    @pytest.mark.asyncio
    async def test_get_recent_with_count(self) -> None:
        """get_recent should return only the last N lines when count is specified."""
        buffer = RollingBuffer(max_size=10)
        
        for i in range(10):
            await buffer.add("src", f"line {i}")
        
        result = await buffer.get_recent("src", count=3)
        assert len(result) == 3
        assert result == ["line 7", "line 8", "line 9"]

    @pytest.mark.asyncio
    async def test_get_recent_empty_source(self) -> None:
        """get_recent should return empty list for unknown source."""
        buffer = RollingBuffer()
        result = await buffer.get_recent("unknown_source")
        assert result == []

    @pytest.mark.asyncio
    async def test_clear_source(self) -> None:
        """clear_source should remove all lines for a specific source."""
        buffer = RollingBuffer()
        
        await buffer.add("src1", "line 1")
        await buffer.add("src2", "line 1")
        
        await buffer.clear_source("src1")
        
        assert await buffer.get_recent("src1") == []
        assert await buffer.get_recent("src2") == ["line 1"]

    @pytest.mark.asyncio
    async def test_clear_all(self) -> None:
        """clear_all should remove all lines from all sources."""
        buffer = RollingBuffer()
        
        await buffer.add("src1", "line 1")
        await buffer.add("src2", "line 2")
        
        await buffer.clear_all()
        
        assert await buffer.get_recent("src1") == []
        assert await buffer.get_recent("src2") == []

    @pytest.mark.asyncio
    async def test_sources_property(self) -> None:
        """sources should return the set of source names."""
        buffer = RollingBuffer()
        
        await buffer.add("src1", "line 1")
        await buffer.add("src2", "line 2")
        await buffer.add("src3", "line 3")
        
        assert buffer.sources == {"src1", "src2", "src3"}

    @pytest.mark.asyncio
    async def test_total_lines(self) -> None:
        """total_lines should return the sum of all lines across sources."""
        buffer = RollingBuffer()
        
        await buffer.add("src1", "line 1")
        await buffer.add("src1", "line 2")
        await buffer.add("src2", "line 3")
        
        assert buffer.total_lines == 3


class TestContextBuilder:
    """Tests for the ContextBuilder class."""

    @pytest.mark.asyncio
    async def test_add_line(self) -> None:
        """add_line should add lines to the rolling buffer."""
        builder = ContextBuilder()
        
        await builder.add_line("src", "line 1")
        
        result = await builder.buffer.get_recent("src")
        assert result == ["line 1"]

    @pytest.mark.asyncio
    async def test_build_context_default(self) -> None:
        """build_context should return recent lines when no index is given."""
        buffer = RollingBuffer(max_size=20)
        builder = ContextBuilder(buffer=buffer, before_count=3, after_count=1)
        
        for i in range(10):
            await builder.add_line("src", f"line {i}")
        
        context = await builder.build_context("src")
        
        assert len(context.before) == 3
        assert context.before == ["line 7", "line 8", "line 9"]
        assert context.after == []

    @pytest.mark.asyncio
    async def test_build_context_with_index(self) -> None:
        """build_context should extract lines around a specific index."""
        buffer = RollingBuffer(max_size=20)
        builder = ContextBuilder(buffer=buffer, before_count=2, after_count=2)
        
        for i in range(10):
            await builder.add_line("src", f"line {i}")
        
        # Index 5 is "line 5"
        context = await builder.build_context("src", incident_line_index=5)
        
        assert context.before == ["line 3", "line 4"]
        assert context.after == ["line 6", "line 7"]

    @pytest.mark.asyncio
    async def test_build_context_empty_buffer(self) -> None:
        """build_context should return empty ContextWindow for empty buffer."""
        builder = ContextBuilder()
        
        context = await builder.build_context("unknown_src")
        
        assert context.before == []
        assert context.after == []
        assert context.line_count == 0

    @pytest.mark.asyncio
    async def test_build_context_near_start(self) -> None:
        """build_context should handle indices near the start of buffer."""
        buffer = RollingBuffer(max_size=20)
        builder = ContextBuilder(buffer=buffer, before_count=5, after_count=2)
        
        for i in range(5):
            await builder.add_line("src", f"line {i}")
        
        # Index 1 is "line 1"
        context = await builder.build_context("src", incident_line_index=1)
        
        assert context.before == ["line 0"]
        assert context.after == ["line 2", "line 3"]

    @pytest.mark.asyncio
    async def test_context_window_all_lines(self) -> None:
        """ContextWindow.all_lines should return before + after in order."""
        window = ContextWindow(before=["a", "b"], after=["c", "d"])
        
        assert window.all_lines == ["a", "b", "c", "d"]

    @pytest.mark.asyncio
    async def test_context_window_line_count(self) -> None:
        """ContextWindow.line_count should return total lines."""
        window = ContextWindow(before=["a", "b"], after=["c"])
        
        assert window.line_count == 3


class TestContextBuilderConfig:
    """Tests for configurable context builder settings."""

    @pytest.mark.asyncio
    async def test_custom_before_count(self) -> None:
        """before_count should control how many preceding lines are captured."""
        buffer = RollingBuffer(max_size=100)
        builder = ContextBuilder(buffer=buffer, before_count=10, after_count=2)
        
        for i in range(20):
            await builder.add_line("src", f"line {i}")
        
        context = await builder.build_context("src", incident_line_index=15)
        
        assert len(context.before) == 10
        assert context.before[0] == "line 5"

    @pytest.mark.asyncio
    async def test_custom_after_count(self) -> None:
        """after_count should control how many following lines are captured."""
        buffer = RollingBuffer(max_size=100)
        builder = ContextBuilder(buffer=buffer, before_count=2, after_count=10)
        
        for i in range(20):
            await builder.add_line("src", f"line {i}")
        
        context = await builder.build_context("src", incident_line_index=5)
        
        assert len(context.after) == 10
        assert context.after[-1] == "line 15"
