"""CLI entrypoint for the Kubernetes Agent."""

import asyncio
import sys

import click

from src.config.settings import Settings
from src.providers.factory import create_llm_provider


def _generate_mock_logs(count: int, severities: list[str]) -> str:
    """Generate simulated log lines for testing.

    Args:
        count: Number of log lines to generate.
        severities: List of severity levels to cycle through.

    Returns:
        A multi-line string of mock log entries.
    """
    services = ["api-gateway", "auth-service", "payment-processor", "user-db"]
    messages_by_severity = {
        "info": [
            "Request processed successfully in 42ms",
            "Health check passed",
            "Connection pool size: 10/50",
        ],
        "warning": [
            "Response time exceeded 500ms threshold",
            "Connection pool utilization at 80%",
            "Retry attempt 2/3 for downstream call",
        ],
        "error": [
            "Connection refused to database host db-primary:5432",
            "HTTP 503 from upstream service payment-processor",
            "Failed to deserialize request body: unexpected token",
        ],
        "critical": [
            "Out of memory: killed process 1234 (java) total-vm:8GB",
            "Disk space critical: /var/log is 98% full",
            "Circuit breaker OPEN for auth-service after 10 failures",
        ],
    }

    lines: list[str] = []
    for i in range(count):
        severity = severities[i % len(severities)]
        service = services[i % len(services)]
        message = messages_by_severity.get(severity, ["Unknown event"])[i % 3]
        lines.append(f"2025-01-15T10:{i // 60:02d}:{i % 60:02d}Z [{severity.upper():8s}] "
                      f"{service}: {message}")

    return "\n".join(lines)


@click.group()
def cli() -> None:
    """AI-powered observability assistant for Kubernetes/Grafana logs."""


@cli.command()
@click.option("--count", default=None, type=int, help="Number of mock log lines to generate.")
@click.option("--provider", default=None, type=str, help="Override LLM provider (llama_cpp or openai).")
def simulate(count: int | None, provider: str | None) -> None:
    """Generate mock logs and send them to the configured LLM for analysis."""
    settings = Settings()

    if provider is not None:
        from src.config.settings import LlmProviderType
        settings.llm_provider = LlmProviderType(provider)

    log_count = count if count is not None else settings.mock_log_count
    severities = settings.mock_log_severities

    click.echo(f"Generating {log_count} mock log lines...")
    mock_logs = _generate_mock_logs(log_count, severities)

    click.echo(f"\n--- Mock Logs (first 500 chars) ---")
    click.echo(mock_logs[:500])
    if len(mock_logs) > 500:
        click.echo(f"... ({len(mock_logs)} total characters)")
    click.echo("--- End of mock logs ---\n")

    click.echo(f"Creating LLM provider: {settings.llm_provider.value}")
    llm = create_llm_provider(settings)

    click.echo("Sending logs to LLM for analysis...")
    try:
        result = asyncio.run(llm.analyze(mock_logs))
    except Exception as exc:  # noqa: BLE001
        click.echo(click.style(f"ERROR: {exc}", fg="red"), err=True)
        sys.exit(1)

    click.echo("\n" + "=" * 60)
    click.echo("ANALYSIS RESULT")
    click.echo("=" * 60)
    click.echo(click.style(f"Root Cause:     {result.root_cause}", fg="yellow"))
    click.echo(click.style(f"Severity:       {result.severity}", fg="red" if result.severity in ("critical", "high") else "green"))
    click.echo(click.style("Remediation:", fg="cyan"))
    for suggestion in result.remediation_suggestions:
        click.echo(f"  - {suggestion}")
    click.echo(click.style("Preventive Actions:", fg="cyan"))
    for action in result.preventive_actions:
        click.echo(f"  - {action}")
    click.echo("=" * 60)


def main() -> None:
    """Entry point when running ``python -m src``."""
    cli()


if __name__ == "__main__":
    main()
