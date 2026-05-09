"""CLI entrypoint for the Kubernetes Agent."""

import asyncio
import sys
from pathlib import Path

import click

from src.config.settings import Settings, LlmProviderType
from src.core.log_sources.mock_file_source import MockFileLogSource
from mocks.generators.log_generator import generate_mock_logs_text


@click.group()
def cli() -> None:
    """AI-powered observability assistant for Kubernetes/Grafana logs."""


# ---------------------------------------------------------------------------
# generate-logs — write a batch of mock logs to a file
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--count", default=None, type=int, help="Number of log lines to generate.")
@click.option("--output", "-o", default=None, type=click.Path(), help="Output file path.")
@click.option("--services", "-s", default=None, help="Comma-separated service names.")
@click.option("--severities", default=None, help="Comma-separated severities (info,warn,error,critical).")
def generate_logs(count: int | None, output: str | None, services: str | None, severities: str | None) -> None:
    """Generate a batch of mock logs and write them to a file."""
    settings = Settings()

    log_count = count if count is not None else settings.mock_log_count

    svc_list = None
    if services is not None:
        svc_list = [s.strip() for s in services.split(",")]
    elif hasattr(settings, "mock_log_services"):
        svc_list = settings.mock_log_services

    sev_list = None
    if severities is not None:
        sev_list = [s.strip() for s in severities.split(",")]
    else:
        sev_list = settings.mock_log_severities

    out_path = Path(output) if output else Path("mocks/logs/generated.log")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    click.echo(f"Generating {log_count} mock log lines -> {out_path}")
    text = generate_mock_logs_text(
        count=log_count,
        severities=sev_list,
        services=svc_list,
    )
    out_path.write_text(text + "\n", encoding="utf-8")
    line_count = text.count("\n") + 1
    click.echo(click.style(f"Done. Wrote {line_count} lines to {out_path}", fg="green"))


# ---------------------------------------------------------------------------
# stream-logs — tail mock logs in real-time
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--duration", "-d", default=10, type=float, help="Seconds to stream (0 = infinite).")
@click.option("--source-file", "-f", default=None, type=str, help="Existing log file to tail.")
def stream_logs(duration: float, source_file: str | None) -> None:
    """Stream mock logs in real-time from the configured mock log source."""
    settings = Settings()

    if source_file is not None:
        # Simple mode: tail an existing file
        filepath = Path(source_file)
        if not filepath.exists():
            click.echo(click.style(f"ERROR: File not found: {filepath}", fg="red"), err=True)
            sys.exit(1)

        click.echo(f"Tailing {filepath} (Ctrl+C to stop)...")
        with open(filepath, "r", encoding="utf-8") as f:
            # Seek to end
            f.seek(0, 2)
            try:
                while True:
                    line = f.readline()
                    if line:
                        click.echo(line.rstrip())
                    else:
                        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.3))
            except KeyboardInterrupt:
                click.echo("\nStopped tailing.")
        return

    # Full mock file source mode
    log_dir = Path(settings.mock_log_dir) if hasattr(settings, "mock_log_dir") else Path("mocks/logs")
    source = MockFileLogSource(settings, log_dir=log_dir)

    async def _run() -> None:
        await source.start()
        try:
            click.echo(f"Streaming from {source.name} (Ctrl+C to stop)...")
            count = 0
            start_time = asyncio.get_event_loop().time()
            async for log_line in source.stream():
                elapsed = asyncio.get_event_loop().time() - start_time
                if duration > 0 and elapsed > duration:
                    break
                click.echo(f"[{log_line.source}] {log_line.text}")
                count += 1
        except KeyboardInterrupt:
            pass
        finally:
            await source.stop()
            click.echo(click.style(f"\nStopped. Received {count} log lines.", fg="green"))

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# simulate — generate mock logs and send to LLM for analysis (existing)
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--count", default=None, type=int, help="Number of mock log lines to generate.")
@click.option("--provider", default=None, type=str, help="Override LLM provider (llama_cpp or openai).")
def simulate(count: int | None, provider: str | None) -> None:
    """Generate mock logs and send them to the configured LLM for analysis."""
    settings = Settings()

    if provider is not None:
        settings.llm_provider = LlmProviderType(provider)

    log_count = count if count is not None else settings.mock_log_count
    severities = settings.mock_log_severities

    svc_list = None
    if hasattr(settings, "mock_log_services"):
        svc_list = settings.mock_log_services

    click.echo(f"Generating {log_count} mock log lines...")
    mock_logs = generate_mock_logs_text(
        count=log_count,
        severities=severities,
        services=svc_list,
    )

    click.echo(f"\n--- Mock Logs (first 500 chars) ---")
    click.echo(mock_logs[:500])
    if len(mock_logs) > 500:
        click.echo(f"... ({len(mock_logs)} total characters)")
    click.echo("--- End of mock logs ---\n")

    click.echo(f"Creating LLM provider: {settings.llm_provider.value}")
    from src.providers.factory import create_llm_provider
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
