"""Mock log generator for simulating Kubernetes/Grafana-style logs.

Generates realistic, structured log entries with:
- Multiple services (auth-service, payment-service, gateway, inventory-service, etc.)
- Realistic severities (INFO, WARN, ERROR, CRITICAL)
- Realistic timestamps that advance in real-time
- Tracebacks, HTTP errors, DB failures, retry failures, OOM messages, pod restarts
- Async streaming via an async generator for real-time simulation
"""

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Message pools — realistic K8s/Grafana-style log messages
# ---------------------------------------------------------------------------

_MESSAGES: dict[str, list[str]] = {
    "info": [
        "GET /api/v1/users 200 OK (12ms)",
        "POST /api/v1/orders 201 Created (45ms)",
        "Health check passed — all dependencies healthy",
        "Connection pool size: 10/50, active: 3",
        "Cache hit ratio: 94.2% (redis-primary:6379)",
        "Scheduled job 'cleanup-sessions' completed in 1.2s",
        "TLS certificate valid for 89 days",
        "Request traced: span_id=0x4f2a trace_id=0xa1b2c3d4",
        "Grpc call to inventory-service completed in 23ms",
        "Config reload successful — 14 keys updated",
    ],
    "warn": [
        "Response time exceeded 500ms threshold: GET /api/v1/reports (823ms)",
        "Connection pool utilization at 82% (41/50 connections)",
        "Retry attempt 2/3 for downstream call to payment-service",
        "Memory usage above 75% threshold: 78.3% (6.2GB/8GB)",
        "Slow query detected: SELECT * FROM orders WHERE ... (2.3s)",
        "Circuit breaker half-open for inventory-service (1 success, 9 failures)",
        "Disk usage on /var/log at 72% — approaching threshold",
        "Rate limiter triggered for client 10.0.3.45: 120 req/s > 100 limit",
        "Pod restart count increasing: payment-service-7d4f (restarts: 4)",
        "Stale connection detected on db-replica-2 — reconnecting",
    ],
    "error": [
        "Connection refused to database host db-primary:5432 — ECONNREFUSED",
        "HTTP 503 from upstream service payment-service at 10.0.5.12:8080",
        "Failed to deserialize request body: unexpected token at position 142",
        "TLS handshake failed with upstream cert-service: certificate expired",
        "Disk write error on /var/data/ingest: no space left on device",
        "Kubernetes probe failed: liveness check failed for pod auth-service-5c8d",
        "Redis connection lost to cache-redis-0: READERR OOM command not allowed",
        "Message queue consumer lag exceeded threshold: 15000 messages behind",
        "Failed to acquire distributed lock after 3 retries: lock-key=order-sync",
        "Upstream service returned invalid JSON: payment-service response body truncated",
    ],
    "critical": [
        "Out of memory: killed process 12345 (java) total-vm:8234567kB, anon-rss:7890123kB",
        "Disk space critical: /var/log is 98% full — emergency cleanup triggered",
        "Circuit breaker OPEN for auth-service after 10 consecutive failures",
        "Pod crash-looping: OOMKilled in payment-service-7d4f (restart count: 5)",
        "Cluster node etcd-3 unreachable for 30s — quorum at risk",
        "Database primary failover initiated: promoting db-replica-1 to primary",
        "SSL certificate expired for gateway.example.com — HTTPS requests failing",
        "Data corruption detected in order table: 3 rows with invalid checksums",
        "Network partition detected between zones us-east-1a and us-east-1b",
        "Memory pressure critical: OOM score adjusted to -998 for container api-gateway",
    ],
}

# Traceback templates for ERROR and CRITICAL entries
_TRACEBACKS: list[str] = [
    (
        "Traceback (most recent call last):\n"
        "  File \"/app/src/database/connection_pool.py\", line 87, in acquire\n"
        "    conn = self._pool.get(timeout=5)\n"
        "  File \"/usr/lib/python3.11/asyncio/queues.py\", line 132, in get\n"
        "    raise asyncio.TimeoutError\n"
        "asyncio.TimeoutError: Get from queue timed out after 5.0 seconds"
    ),
    (
        "Traceback (most recent call last):\n"
        "  File \"/app/src/http/client.py\", line 204, in request\n"
        "    resp = await self._session.request(method, url, **kwargs)\n"
        "  File \"/usr/local/lib/python3.11/site-packages/httpx/_client.py\", line 892\n"
        "    raise RemoteProtocolError(\"Server disconnected\")\n"
        "httpx.RemoteProtocolError: Server disconnected — connection reset by peer"
    ),
    (
        "Traceback (most recent call last):\n"
        "  File \"/app/src/workers/processor.py\", line 56, in process\n"
        "    result = await self._handler(event)\n"
        "  File \"/app/src/handlers/order.py\", line 112, in handle_order\n"
        "    raise ValidationError(f\"Invalid order ID: {order_id}\")\n"
        "src.exceptions.ValidationError: Invalid order ID: null — expected UUID v4"
    ),
]

_SERVICES: list[str] = [
    "auth-service",
    "payment-service",
    "gateway",
    "inventory-service",
    "user-api",
    "order-processor",
    "notification-worker",
    "cache-redis",
]

# Kubernetes pod name patterns per service
_POD_SUFFIXES: dict[str, list[str]] = {
    "auth-service": ["5c8d7f9a2b", "3e1f6b4c8d", "7a2d9e5f1c"],
    "payment-service": ["7d4f2a8e3b", "1c9e5d7f4a", "4b8a2c6e9d"],
    "gateway": ["2f5e8a1d3c", "9d3b7f2e5a", "6c1a4e8b2f"],
    "inventory-service": ["8e2d5f9a1c", "3a7c1e5d9b", "5d9b3a7c1e"],
    "user-api": ["1a2b3c4d5e", "6f7g8h9i0j", "k1l2m3n4o5"],
    "order-processor": ["9z8y7x6w5v", "4u3t2s1r0q", "p9o8n7m6l5"],
    "notification-worker": ["a1b2c3d4e5", "f6g7h8i9j0", "k1l2m3n4o5"],
    "cache-redis": ["redis-0", "redis-1", "redis-2"],
}


@dataclass(frozen=True)
class LogEntry:
    """A single structured log entry."""

    timestamp: datetime
    severity: str
    service: str
    message: str
    pod: str | None = None
    include_traceback: bool = False

    def format(self) -> str:
        """Format as a Kubernetes-style log line."""
        ts = self.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        sev = self.severity.upper().ljust(8)
        pod_label = f"pod/{self.pod}" if self.pod else self.service
        line = f"{ts} [{sev}] {pod_label}: {self.message}"
        if self.include_traceback:
            line += f"\n{_TRACEBACKS[hash(self.message) % len(_TRACEBACKS)]}"
        return line


def _random_timestamp(base: datetime, offset_seconds: int) -> datetime:
    """Generate a slightly randomized timestamp around base + offset."""
    jitter = random.uniform(-0.5, 0.5)
    return base + timedelta(seconds=offset_seconds + jitter)


def generate_log_entries(
    count: int = 50,
    severities: list[str] | None = None,
    services: list[str] | None = None,
    base_time: datetime | None = None,
    include_tracebacks: bool = True,
) -> list[LogEntry]:
    """Generate a batch of mock log entries.

    Args:
        count: Number of log entries to generate.
        severities: Severity levels to cycle through. Defaults to all four.
        services: Service names to cycle through. Defaults to built-in list.
        base_time: Starting timestamp. Defaults to now minus 1 hour.
        include_tracebacks: Whether ERROR/CRITICAL entries include tracebacks.

    Returns:
        A list of LogEntry dataclasses.
    """
    if severities is None:
        severities = ["info", "warn", "error", "critical"]
    if services is None:
        services = _SERVICES
    if base_time is None:
        base_time = datetime.now(timezone.utc) - timedelta(hours=1)

    entries: list[LogEntry] = []
    for i in range(count):
        severity = severities[i % len(severities)]
        service = services[i % len(services)]
        messages = _MESSAGES.get(severity, ["Unknown event"])
        message = messages[i % len(messages)]

        ts = _random_timestamp(base_time, i * random.uniform(0.5, 3.0))
        pod = None
        if service in _POD_SUFFIXES:
            pod = f"{service}-{_POD_SUFFIXES[service][i % len(_POD_SUFFIXES[service])]}"

        include_tb = include_tracebacks and severity in ("error", "critical")
        entries.append(LogEntry(
            timestamp=ts,
            severity=severity,
            service=service,
            message=message,
            pod=pod,
            include_traceback=include_tb,
        ))

    return entries


def generate_mock_logs_text(
    count: int = 50,
    severities: list[str] | None = None,
    services: list[str] | None = None,
    base_time: datetime | None = None,
    include_tracebacks: bool = True,
) -> str:
    """Generate mock logs as a plain text string.

    Args:
        count: Number of log lines to generate.
        severities: Severity levels to cycle through.
        services: Service names to cycle through.
        base_time: Starting timestamp.
        include_tracebacks: Whether ERROR/CRITICAL entries include tracebacks.

    Returns:
        Multi-line string of formatted log entries.
    """
    entries = generate_log_entries(
        count, severities, services, base_time, include_tracebacks,
    )
    return "\n".join(e.format() for e in entries)


async def stream_log_entries(
    count: int = 100,
    interval: float = 0.3,
    severities: list[str] | None = None,
    services: list[str] | None = None,
    base_time: datetime | None = None,
) -> None:
    """Async generator that yields LogEntry objects one at a time.

    Simulates real-time log production by yielding entries with a configurable
    delay between each. Useful for testing streaming consumers.

    Args:
        count: Total number of entries to yield.
        interval: Seconds to wait between each entry.
        severities: Severity levels to cycle through.
        services: Service names to cycle through.
        base_time: Starting timestamp. Defaults to now minus 1 hour.
    """
    if severities is None:
        severities = ["info", "warn", "error", "critical"]
    if services is None:
        services = _SERVICES
    if base_time is None:
        base_time = datetime.now(timezone.utc) - timedelta(hours=1)

    for i in range(count):
        entry = generate_log_entries(
            count=1,
            severities=severities,
            services=services,
            base_time=base_time,
            include_tracebacks=True,
        )[0]
        yield entry
        await asyncio.sleep(interval)
