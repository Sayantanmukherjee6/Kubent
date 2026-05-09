"""Mock log generator for simulating Kubernetes/Grafana-style logs."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LogEntry:
    """A single structured log entry."""

    timestamp: str
    severity: str
    service: str
    message: str

    def __str__(self) -> str:
        return (
            f"{self.timestamp} [{self.severity.upper():8s}] "
            f"{self.service}: {self.message}"
        )


# Predefined messages grouped by severity.
_MESSAGES: dict[str, list[str]] = {
    "info": [
        "Request processed successfully in 42ms",
        "Health check passed",
        "Connection pool size: 10/50",
        "Cache hit ratio: 94%",
        "Scheduled job completed in 1.2s",
    ],
    "warning": [
        "Response time exceeded 500ms threshold",
        "Connection pool utilization at 80%",
        "Retry attempt 2/3 for downstream call",
        "Memory usage above 75% threshold",
        "Slow query detected: 2.3s on users table",
    ],
    "error": [
        "Connection refused to database host db-primary:5432",
        "HTTP 503 from upstream service payment-processor",
        "Failed to deserialize request body: unexpected token",
        "TLS handshake failed with upstream cert-service",
        "Disk write error on /var/data/ingest: no space left",
    ],
    "critical": [
        "Out of memory: killed process 1234 (java) total-vm:8GB",
        "Disk space critical: /var/log is 98% full",
        "Circuit breaker OPEN for auth-service after 10 failures",
        "Pod crash-looping: OOMKilled in payment-processor-7d4f",
        "Cluster node etcd-3 unreachable for 30s",
    ],
}

_SERVICES: list[str] = [
    "api-gateway",
    "auth-service",
    "payment-processor",
    "user-db",
    "cache-redis",
    "scheduler",
]


def generate_log_entries(
    count: int = 50,
    severities: list[str] | None = None,
    services: list[str] | None = None,
    base_hour: int = 10,
) -> list[LogEntry]:
    """Generate a list of mock log entries.

    Args:
        count: Number of log entries to generate.
        severities: Severity levels to cycle through. Defaults to all four.
        services: Service names to cycle through. Defaults to built-in list.
        base_hour: Starting hour for timestamps (0-23).

    Returns:
        A list of LogEntry dataclasses.
    """
    if severities is None:
        severities = ["info", "warning", "error", "critical"]
    if services is None:
        services = _SERVICES

    entries: list[LogEntry] = []
    for i in range(count):
        severity = severities[i % len(severities)]
        service = services[i % len(services)]
        messages = _MESSAGES.get(severity, ["Unknown event"])
        message = messages[i % len(messages)]

        minute = (base_hour * 60 + i) // 60 % 24
        second = (base_hour * 3600 + i) % 60
        timestamp = f"2025-01-15T{minute:02d}:{(i // 60) % 60:02d}:{second:02d}Z"

        entries.append(LogEntry(
            timestamp=timestamp,
            severity=severity,
            service=service,
            message=message,
        ))

    return entries


def generate_mock_logs_text(
    count: int = 50,
    severities: list[str] | None = None,
    services: list[str] | None = None,
) -> str:
    """Generate mock logs as a plain text string.

    Convenience wrapper around generate_log_entries that joins entries
    with newlines.

    Args:
        count: Number of log lines to generate.
        severities: Severity levels to cycle through.
        services: Service names to cycle through.

    Returns:
        Multi-line string of log entries.
    """
    entries = generate_log_entries(count, severities, services)
    return "\n".join(str(entry) for entry in entries)
