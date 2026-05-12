"""Tests for src.providers.retry."""

import httpx
import pytest

from src.providers.retry import MAX_RETRIES, BASE_DELAY, retry


# ── helpers ───────────────────────────────────────────────────────


class _HttpError(Exception):
    """Generic HTTP error (not retryable)."""


class _Response(Exception):
    """Minimal mock response with a status_code attribute."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")

    def __repr__(self) -> str:
        return f"<_Response {self.status_code}>"


# ── success on first try ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_succeeds_immediately() -> None:
    call_count = 0

    async def _fn() -> str:
        nonlocal call_count
        call_count += 1
        return "ok"

    result = await retry(_fn)
    assert result == "ok"
    assert call_count == 1


# ── retries on timeout ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_retries_on_timeout() -> None:
    call_count = 0

    async def _fn() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.TimeoutException("timed out")
        return "ok"

    result = await retry(_fn)
    assert result == "ok"
    assert call_count == 3


# ── retries on connection error ──────────────────────────────────


@pytest.mark.asyncio
async def test_retries_on_connect_error() -> None:
    call_count = 0

    async def _fn() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise httpx.ConnectError("connection refused")
        return "ok"

    result = await retry(_fn)
    assert result == "ok"
    assert call_count == 2


# ── raises after max retries on timeout ──────────────────────────


@pytest.mark.asyncio
async def test_raises_after_max_retries_on_timeout() -> None:
    async def _fn() -> str:
        raise httpx.TimeoutException("timed out")

    with pytest.raises(httpx.TimeoutException):
        await retry(_fn)


# ── raises after max retries on connection error ─────────────────


@pytest.mark.asyncio
async def test_raises_after_max_retries_on_connect_error() -> None:
    async def _fn() -> str:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(httpx.ConnectError):
        await retry(_fn)


# ── retries on HTTP 5xx ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_retries_on_502() -> None:
    call_count = 0

    async def _fn() -> _Response:
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            return _Response(502)
        return _Response(200)

    result = await retry(_fn)
    assert result.status_code == 200
    assert call_count == 2


@pytest.mark.asyncio
async def test_retries_on_503() -> None:
    call_count = 0

    async def _fn() -> _Response:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return _Response(503)
        return _Response(200)

    result = await retry(_fn)
    assert result.status_code == 200
    assert call_count == 3


# ── raises after max retries on HTTP 5xx ────────────────────────


@pytest.mark.asyncio
async def test_raises_after_max_retries_on_5xx() -> None:
    async def _fn() -> _Response:
        return _Response(500)

    with pytest.raises(_Response):
        await retry(_fn)


# ── does NOT retry on HTTP 4xx ──────────────────────────────────


@pytest.mark.asyncio
async def test_does_not_retry_on_400() -> None:
    call_count = 0

    async def _fn() -> _Response:
        nonlocal call_count
        call_count += 1
        return _Response(400)

    result = await retry(_fn)
    assert result.status_code == 400
    assert call_count == 1


# ── does NOT retry on non-retryable exceptions ──────────────────


@pytest.mark.asyncio
async def test_does_not_retry_on_generic_error() -> None:
    async def _fn() -> str:
        raise _HttpError("bad request")

    with pytest.raises(_HttpError):
        await retry(_fn)


# ── exponential backoff timing ──────────────────────────────────


@pytest.mark.asyncio
async def test_exponential_backoff_delays() -> None:
    """Verify delays follow 2^attempt pattern (1s, 2s)."""
    import asyncio as _asyncio

    call_count = 0
    timestamps: list[float] = []

    async def _fn() -> str:
        nonlocal call_count
        timestamps.append(_asyncio.get_event_loop().time())
        call_count += 1
        if call_count < 3:
            raise httpx.TimeoutException("timed out")
        return "ok"

    await retry(_fn)

    # attempt 0 → delay = 1s (BASE_DELAY * 2^0)
    # attempt 1 → delay = 2s (BASE_DELAY * 2^1)
    assert abs(timestamps[1] - timestamps[0] - BASE_DELAY) < 0.5
    assert abs(timestamps[2] - timestamps[1] - BASE_DELAY * 2) < 0.5
