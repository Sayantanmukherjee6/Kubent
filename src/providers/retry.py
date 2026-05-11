"""Lightweight retry helper for HTTP calls."""

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

MAX_RETRIES = 2
BASE_DELAY = 1.0  # seconds


def _is_server_error(response: object) -> bool:
    """Return True for HTTP 5xx status codes."""
    return hasattr(response, "status_code") and 500 <= response.status_code < 600


async def retry(
    func: Callable[[], Awaitable[T]],
) -> T:
    """Call *func* with exponential backoff on retryable errors.

    Retries at most *MAX_RETRIES* times.  Only retries on:
      - httpx.TimeoutException
      - httpx.ConnectError
      - HTTP 5xx responses
    """
    import httpx

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = await func()
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt == MAX_RETRIES:
                raise
            delay = BASE_DELAY * (2 ** attempt)
            logger.warning(
                "Retryable error on attempt %d/%d: %s — retrying in %.1fs",
                attempt + 1, MAX_RETRIES, exc, delay,
            )
            await asyncio.sleep(delay)
            continue

        if _is_server_error(result):
            last_exc = result
            if attempt == MAX_RETRIES:
                raise result
            delay = BASE_DELAY * (2 ** attempt)
            logger.warning(
                "Server error %d on attempt %d/%d — retrying in %.1fs",
                result.status_code, attempt + 1, MAX_RETRIES, delay,
            )
            await asyncio.sleep(delay)
            continue

        return result

    # Should not reach here, but mypy needs a return.
    raise last_exc or RuntimeError("retry exited without result")  # type: ignore[return-value]
