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

# ---------------------------------------------------------------------------
# watch-logs — stream logs and detect incidents (no LLM)
# ---------------------------------------------------------------------------

@cli.command("watch-logs")
@click.option("--duration", "-d", default=15, type=float, help="Seconds to watch (0 = infinite).")
@click.option("--min-severity", "-s", default="medium",
              type=click.Choice(["low", "medium", "high", "critical"], case_sensitive=False),
              help="Minimum severity level to report.")
@click.option("--dedup-ttl", "-t", default=300, type=float, help="Deduplication TTL in seconds.")
@click.option("--dedup-threshold", "-n", default=1, type=int,
              help="Minimum occurrences before emitting deduplicated event.")
@click.option("--context-before", "-b", default=5, type=int,
              help="Number of preceding context lines to capture.")
@click.option("--context-after", "-a", default=3, type=int,
              help="Number of following context lines to capture.")
def watch_logs(duration: float, min_severity: str, dedup_ttl: float,
               dedup_threshold: int, context_before: int, context_after: int) -> None:
    """Stream mock logs and detect incidents (no LLM calls).

    Watches a mock log source for errors, extracts surrounding context,
    deduplicates noisy repeated events, and prints structured incident
    summaries to the console.
    """
    from src.core.watcher import LogWatcher, WatcherSeverity

    severity_map = {
        "low": WatcherSeverity.LOW,
        "medium": WatcherSeverity.MEDIUM,
        "high": WatcherSeverity.HIGH,
        "critical": WatcherSeverity.CRITICAL,
    }
    min_sev = severity_map[min_severity.lower()]

    settings = Settings()
    log_dir = Path(settings.mock_log_dir) if hasattr(settings, "mock_log_dir") else Path("mocks/logs")
    source = MockFileLogSource(settings, log_dir=log_dir)

    watcher = LogWatcher(
        min_severity=min_sev,
        dedup_ttl=dedup_ttl,
        dedup_threshold=dedup_threshold,
        context_before=context_before,
        context_after=context_after,
    )

    severity_colors = {
        WatcherSeverity.LOW: "yellow",
        WatcherSeverity.MEDIUM: "white",
        WatcherSeverity.HIGH: "magenta",
        WatcherSeverity.CRITICAL: "red",
    }

    async def _run() -> None:
        incident_count = 0
        start_time = asyncio.get_event_loop().time()

        click.echo(click.style(f"Watching {source.name}", fg="cyan"))
        click.echo(click.style(f"Min severity: {min_severity} | Dedup TTL: {dedup_ttl}s | "
                               f"Dedup threshold: {dedup_threshold}", fg="black"))
        click.echo(click.style("-" * 70, fg="black"))

        try:
            async for incident in watcher.watch(source):
                elapsed = asyncio.get_event_loop().time() - start_time
                if duration > 0 and elapsed > duration:
                    break

                incident_count += 1
                color = severity_colors.get(incident.severity, "white")

                click.echo(click.style(f"\n[INCIDENT #{incident_count}]", fg=color, bold=True))
                click.echo(f"  Timestamp   : {incident.timestamp.isoformat()}")
                click.echo(f"  Service     : {incident.service_name}")
                click.echo(click.style(f"  Severity    : {incident.severity.value}", fg=color))
                click.echo(f"  Error Type  : {incident.error_type}")
                click.echo(f"  Occurrences : {incident.occurrence_count}")
                click.echo(f"  Hash        : {incident.event_hash[:12]}...")
                click.echo(click.style(f"  Raw line    : {incident.raw_line[:120]}", fg="black"))

                if incident.context_lines:
                    click.echo(click.style(f"  Context     : {len(incident.context_lines)} lines", fg="black"))
                    for ctx_line in incident.context_lines[:3]:
                        click.echo(f"    > {ctx_line[:100]}")
                    if len(incident.context_lines) > 3:
                        click.echo(f"    ... and {len(incident.context_lines) - 3} more")

        except KeyboardInterrupt:
            pass
        finally:
            await source.stop()
            elapsed = asyncio.get_event_loop().time() - start_time
            click.echo(click.style(f"\n{'=' * 70}", fg="black"))
            click.echo(click.style(f"Stopped after {elapsed:.1f}s. Detected {incident_count} incident(s).",
                                   fg="green"))
            click.echo(click.style("=" * 70, fg="black"))

    asyncio.run(_run())



# ---------------------------------------------------------------------------
# predict — stream logs, run watcher + predictor, print PredictorEvent summaries
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--duration", "-d", default=15, type=float, help="Seconds to watch (0 = infinite).")
@click.option("--min-severity", "-s", default="medium",
              type=click.Choice(["low", "medium", "high", "critical"], case_sensitive=False),
              help="Minimum severity level for watcher detection.")
@click.option("--dedup-ttl", "-t", default=300, type=float, help="Deduplication TTL in seconds.")
@click.option("--dedup-threshold", "-n", default=1, type=int,
              help="Minimum occurrences before emitting deduplicated event.")
def predict(duration: float, min_severity: str, dedup_ttl: float, dedup_threshold: int) -> None:
    """Stream logs, run watcher and predictor, print PredictorEvent summaries.

    Wires the LogWatcher pipeline into HeuristicPredictor so that every
    detected IncidentEvent is fed through the heuristic engine and any
    resulting PredictorEvents are printed to the console.
    """
    from src.core.watcher import LogWatcher, WatcherSeverity
    from src.core.predictor import HeuristicPredictor, RiskLevel

    severity_map = {
        "low": WatcherSeverity.LOW,
        "medium": WatcherSeverity.MEDIUM,
        "high": WatcherSeverity.HIGH,
        "critical": WatcherSeverity.CRITICAL,
    }
    min_sev = severity_map[min_severity.lower()]

    settings = Settings()
    log_dir = Path(settings.mock_log_dir) if hasattr(settings, "mock_log_dir") else Path("mocks/logs")
    source = MockFileLogSource(settings, log_dir=log_dir)

    watcher = LogWatcher(
        min_severity=min_sev,
        dedup_ttl=dedup_ttl,
        dedup_threshold=dedup_threshold,
    )
    predictor = HeuristicPredictor()

    risk_colors = {
        RiskLevel.LOW: "yellow",
        RiskLevel.MEDIUM: "white",
        RiskLevel.HIGH: "magenta",
        RiskLevel.CRITICAL: "red",
    }

    async def _run() -> None:
        incident_count = 0
        prediction_count = 0
        start_time = asyncio.get_event_loop().time()

        click.echo(click.style(f"Predicting on {source.name}", fg="cyan"))
        click.echo(click.style(f"Min severity: {min_severity} | Dedup TTL: {dedup_ttl}s", fg="black"))
        click.echo(click.style("-" * 70, fg="black"))

        try:
            async for incident in watcher.watch(source):
                elapsed = asyncio.get_event_loop().time() - start_time
                if duration > 0 and elapsed > duration:
                    break

                incident_count += 1

                # Feed incident into predictor
                predictions = await predictor.process(incident)

                for pred in predictions:
                    prediction_count += 1
                    color = risk_colors.get(pred.risk_level, "white")
                    click.echo(click.style(f"\n[PREDICTION #{prediction_count}]", fg=color, bold=True))
                    click.echo(f"  Timestamp     : {pred.timestamp.isoformat()}")
                    click.echo(f"  Service       : {pred.service_name}")
                    click.echo(click.style(f"  Risk Level    : {pred.risk_level.value}", fg=color))
                    click.echo(f"  Pattern       : {pred.pattern}")
                    click.echo(f"  Trigger Count : {pred.trigger_count}")
                    if pred.related_hash:
                        click.echo(f"  Related Hash  : {pred.related_hash[:12]}...")

        except KeyboardInterrupt:
            pass
        finally:
            await source.stop()
            elapsed = asyncio.get_event_loop().time() - start_time
            click.echo(click.style(f"\n{'=' * 70}", fg="black"))
            click.echo(click.style(f"Stopped after {elapsed:.1f}s. "
                                   f"{incident_count} incident(s), {prediction_count} prediction(s).",
                                   fg="green"))
            click.echo(click.style("=" * 70, fg="black"))

    asyncio.run(_run())

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
