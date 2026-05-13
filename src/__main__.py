"""CLI entrypoint for the Kubernetes Agent."""

import asyncio
import sys
from pathlib import Path

import click

from src.config.settings import Settings, LlmProviderType
from src.core.log_sources.factory import create_log_source
from src.core.metrics.scenario_generator import generate_demo_metrics, list_available_scenarios, get_scenario_description
from src.core.predictor.models import RiskLevel
from mocks.generators.log_generator import generate_mock_logs_text


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _build_settings(source: str | None = None, log_dir: str | None = None) -> Settings:
    """Build Settings with optional CLI overrides for log source type and directory.

    All commands that consume logs (stream-logs, watch-logs, predict) use this
    helper so that source selection always goes through the factory.
    """
    overrides = {}
    if source is not None:
        overrides["log_source_type"] = source
    if log_dir is not None:
        overrides["log_source_folder_path"] = log_dir
    return Settings(**overrides)


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
@click.option("--source", "-S", default=None, type=click.Choice(["mock", "folder"], case_sensitive=False),
              help="Override log source type (mock or folder).")
@click.option("--log-dir", default=None, type=click.Path(),
              help="Override log directory path (used by mock and folder sources).")
def stream_logs(duration: float, source_file: str | None, source: str | None, log_dir: str | None) -> None:
    """Stream logs in real-time from the configured log source."""
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

    # Build settings with optional CLI overrides via shared helper
    settings = _build_settings(source, log_dir)
    log_source = create_log_source(settings)

    async def _run() -> None:
        await log_source.start()
        try:
            click.echo(f"Streaming from {log_source.name} (Ctrl+C to stop)...")
            count = 0
            start_time = asyncio.get_event_loop().time()
            async for log_line in log_source.stream():
                elapsed = asyncio.get_event_loop().time() - start_time
                if duration > 0 and elapsed > duration:
                    break
                click.echo(f"[{log_line.source}] {log_line.text}")
                count += 1
        except KeyboardInterrupt:
            pass
        finally:
            await log_source.stop()
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
@click.option("--source", "-S", default=None, type=click.Choice(["mock", "folder"], case_sensitive=False),
              help="Override log source type (mock or folder).")
@click.option("--log-dir", default=None, type=click.Path(),
              help="Override log directory path (used by mock and folder sources).")
def watch_logs(duration: float, min_severity: str, dedup_ttl: float,
               dedup_threshold: int, context_before: int, context_after: int,
               source: str | None, log_dir: str | None) -> None:
    """Stream logs and detect incidents (no LLM calls).

    Watches a log source for errors, extracts surrounding context,
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

    # Build settings with optional CLI overrides via shared helper
    settings = _build_settings(source, log_dir)
    log_source = create_log_source(settings)

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

        click.echo(click.style(f"Watching {log_source.name}", fg="cyan"))
        click.echo(click.style(f"Min severity: {min_severity} | Dedup TTL: {dedup_ttl}s | "
                               f"Dedup threshold: {dedup_threshold}", fg="black"))
        click.echo(click.style("-" * 70, fg="black"))

        try:
            async for incident in watcher.watch(log_source):
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
            await log_source.stop()
            elapsed = asyncio.get_event_loop().time() - start_time
            click.echo(click.style(f"\n{'=' * 70}", fg="black"))
            click.echo(click.style(f"Stopped after {elapsed:.1f}s. Detected {incident_count} incident(s).",
                                   fg="green"))
            click.echo(click.style("=" * 70, fg="black"))

    asyncio.run(_run())



# ---------------------------------------------------------------------------
# predict — stream logs, run watcher + predictor, print PredictorEvent summaries
# ---------------------------------------------------------------------------

_RISK_LABELS = {
    RiskLevel.CRITICAL: "[CRITICAL]",
    RiskLevel.HIGH:     "[HIGH]",
    RiskLevel.MEDIUM:   "[MEDIUM]",
    RiskLevel.LOW:      "[LOW]",
}

_RISK_COLORS = {
    RiskLevel.CRITICAL: "red",
    RiskLevel.HIGH:     "magenta",
    RiskLevel.MEDIUM:   "yellow",
    RiskLevel.LOW:      "cyan",
}


def _format_prediction(pred, number):
    """Format a single PredictorEvent for terminal display."""
    label = _RISK_LABELS.get(pred.risk_level, "[UNKNOWN]")
    color = _RISK_COLORS.get(pred.risk_level, "white")
    parts = [
        click.style(f"{label}  #{number}", fg=color, bold=True),
        f"  service   = {pred.service_name}",
        f"  pattern   = {pred.pattern}",
        f"  trigger_count = {pred.trigger_count}",
    ]
    if pred.related_hash:
        parts.append(f"  related   = {pred.related_hash[:12]}")
    return click.style("\n".join(parts), fg=color)


@cli.command()
@click.option("--duration", "-d", default=15, type=float, help="Seconds to watch (0 = infinite).")
@click.option("--min-severity", "-s", default="medium",
              type=click.Choice(["low", "medium", "high", "critical"], case_sensitive=False),
              help="Minimum severity level for watcher detection.")
@click.option("--dedup-ttl", "-t", default=300, type=float, help="Deduplication TTL in seconds.")
@click.option("--dedup-threshold", "-n", default=1, type=int,
              help="Minimum occurrences before emitting deduplicated event.")
@click.option("--source", "-S", default=None, type=click.Choice(["mock", "folder"], case_sensitive=False),
              help="Override log source type (mock or folder).")
@click.option("--log-dir", default=None, type=click.Path(),
              help="Override log directory path (used by mock and folder sources).")
def predict(duration, min_severity, dedup_ttl, dedup_threshold, source, log_dir):
    """Stream logs, run watcher and predictor, print PredictorEvent summaries.

    Wires the LogWatcher pipeline into HeuristicPredictor so that every
    detected IncidentEvent is fed through the heuristic engine and any
    resulting PredictorEvents are printed to the console.

    CLI flags (--source, --log-dir) temporarily override YAML config
    without modifying the file.
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

    # Build settings with optional CLI overrides via shared helper
    settings = _build_settings(source, log_dir)
    log_source = create_log_source(settings)

    watcher = LogWatcher(
        min_severity=min_sev,
        dedup_ttl=dedup_ttl,
        dedup_threshold=dedup_threshold,
    )
    predictor = HeuristicPredictor()

    async def _run():
        incident_count = 0
        prediction_count = 0
        start_time = asyncio.get_event_loop().time()

        click.echo(click.style(f"Predicting on {log_source.name}", fg="cyan", bold=True))
        click.echo(click.style(
            f"Min severity: {min_severity} | Dedup TTL: {dedup_ttl}s | "
            f"Dedup threshold: {dedup_threshold}", fg="bright_black"))
        click.echo(click.style("-" * 70, fg="bright_black"))

        try:
            async for incident in watcher.watch(log_source):
                elapsed = asyncio.get_event_loop().time() - start_time
                if duration > 0 and elapsed > duration:
                    break

                incident_count += 1
                predictions = await predictor.process(incident)

                for pred in predictions:
                    prediction_count += 1
                    click.echo(_format_prediction(pred, prediction_count))

        except KeyboardInterrupt:
            pass
        finally:
            try:
                await asyncio.wait_for(log_source.stop(), timeout=3.0)
            except (asyncio.TimeoutError, RuntimeError):
                # Fallback: cancel if stop hangs
                if hasattr(log_source, "_writer_task") and log_source._writer_task is not None:
                    log_source._writer_task.cancel()
                elif hasattr(log_source, "_stop_event"):
                    log_source._stop_event.set()
            elapsed = asyncio.get_event_loop().time() - start_time
            click.echo(click.style("\n" + "=" * 70, fg="bright_black"))
            click.echo(click.style(
                f"Stopped after {elapsed:.1f}s. "
                f"{incident_count} incident(s), {prediction_count} prediction(s).",
                fg="green"))
            click.echo(click.style("=" * 70, fg="bright_black"))

    asyncio.run(_run())


# predict-metrics — stream metrics and run statistical predictor
# ---------------------------------------------------------------------------

@cli.command("predict-metrics")
@click.option("--duration", "-d", default=15, type=float, help="Seconds to stream (0 = infinite).")
@click.option("--source", "-S", default=None, type=click.Choice(["mock", "folder"], case_sensitive=False),
              help="Override metric source type (mock or folder).")
@click.option("--metric-dir", default=None, type=click.Path(),
              help="Override metric directory path (used by folder source).")
def predict_metrics(duration: float, source: str | None, metric_dir: str | None) -> None:
    """Stream metrics and run the statistical predictor.

    Streams MetricSample objects from the configured metric source,
    feeds them through MetricPredictor, and prints prediction events
    to the console in real-time.
    """
    from src.core.metrics import MetricPredictor, MetricPredictionType, MetricSeverity
    from src.core.metrics.factory import create_metric_source

    # Build settings with optional CLI overrides
    overrides = {}
    if source is not None:
        overrides["metrics_source_type"] = source
    if metric_dir is not None:
        overrides["metrics_folder_path"] = metric_dir
    settings = Settings(**overrides)

    metric_source = create_metric_source(settings)
    predictor = MetricPredictor(
        window_size=settings.metrics.predictor_window_size,
        cpu_threshold=settings.metrics.thresholds.cpu_percent,
        memory_threshold=settings.metrics.thresholds.memory_percent,
    )

    severity_colors = {
        MetricSeverity.LOW: "yellow",
        MetricSeverity.MEDIUM: "white",
        MetricSeverity.HIGH: "magenta",
        MetricSeverity.CRITICAL: "red",
    }

    async def _run() -> None:
        event_count = 0
        sample_count = 0
        start_time = asyncio.get_event_loop().time()

        click.echo(click.style(f"Streaming from {metric_source.name} (Ctrl+C to stop)...", fg="cyan"))
        click.echo(click.style(
            f"CPU threshold: {settings.metrics.thresholds.cpu_percent:.0f}% | "
            f"Memory threshold: {settings.metrics.thresholds.memory_percent:.0f}% | "
            f"Window: {settings.metrics.predictor_window_size}",
            fg="bright_black"))
        click.echo(click.style("-" * 70, fg="bright_black"))

        try:
            await metric_source.start()
            async for sample in metric_source.stream():
                elapsed = asyncio.get_event_loop().time() - start_time
                if duration > 0 and elapsed > duration:
                    break

                sample_count += 1
                events = await predictor.process(sample)

                for event in events:
                    event_count += 1
                    color = severity_colors.get(event.severity, "white")
                    click.echo(click.style(f"[{event.prediction_type.value}]", fg=color, bold=True))
                    click.echo(f"  Service     : {event.service_name}")
                    click.echo(click.style(f"  Severity    : {event.severity.value}", fg=color))
                    click.echo(f"  Message     : {event.message}")
                    click.echo(f"  Current     : {event.current_value:.1f}")
                    click.echo(f"  Predicted   : {event.predicted_value:.1f}")
                    click.echo(f"  Threshold   : {event.threshold:.1f}")

        except KeyboardInterrupt:
            pass
        finally:
            await metric_source.stop()
            elapsed = asyncio.get_event_loop().time() - start_time
            click.echo(click.style("=" * 70, fg="bright_black"))
            click.echo(click.style(
                f"Stopped after {elapsed:.1f}s. Processed {sample_count} samples, "
                f"emitted {event_count} prediction event(s).",
                fg="green"))
            click.echo(click.style("=" * 70, fg="bright_black"))

    asyncio.run(_run())


# generate-metrics — write realistic demo metric CSV files
# ---------------------------------------------------------------------------

@cli.command("generate-metrics")
@click.option("--scenarios", default=None, help="Comma-separated scenario names (e.g. steady_cpu_growth,memory_leak).")
@click.option("--services", "-s", default=None, help="Comma-separated service names.")
@click.option("--output", "-o", default="./demo_metrics", type=click.Path(), help="Output directory for CSV files.")
@click.option("--duration", "-d", default=60, type=int, help="Number of metric steps per service (each step = 5s).")
@click.option("--list", "-l", is_flag=True, help="List available scenarios and exit.")
def generate_metrics(scenarios: str | None, services: str | None, output: str, duration: int, list: bool) -> None:
    """Generate realistic demo metric CSV files for predictive demonstrations.

    Writes deterministic, scenario-driven metric streams into the output directory.
    Each service gets its own CSV file with correlated CPU, memory, latency, and error_rate.
    """
    if list:
        click.echo(click.style("Available scenarios:", fg="cyan", bold=True))
        for name in list_available_scenarios():
            desc = get_scenario_description(name)
            click.echo(f"  {click.style(name, fg='yellow')} — {desc}")
        return

    svc_list = None
    if services is not None:
        svc_list = [s.strip() for s in services.split(",")]

    scen_list = None
    if scenarios is not None:
        scen_list = [s.strip() for s in scenarios.split(",")]
        # Validate scenarios
        for s in scen_list:
            if get_scenario_description(s) is None:
                click.echo(click.style(f"ERROR: Unknown scenario {s!r}", fg="red"), err=True)
                available = ", ".join(list_available_scenarios())
                click.echo(f"Available scenarios: {available}")
                sys.exit(1)

    click.echo(f"Generating demo metrics -> {output}/")
    if scen_list:
        click.echo(f"  Scenarios: {', '.join(scen_list)}")
    else:
        click.echo("  Scenarios: per-service defaults (gateway=cpu_growth, payment=latency_spike, auth=memory_leak)")
    if svc_list:
        click.echo(f"  Services: {', '.join(svc_list)}")
    click.echo(f"  Steps: {duration} ({duration * 5}s of simulated time)")

    results = generate_demo_metrics(
        output_dir=output,
        scenarios=scen_list,
        services=svc_list,
        total_steps=duration,
    )

    for svc, path in results.items():
        click.echo(click.style(f"  ✓ {svc} -> {path}", fg="green"))

    total = sum(1 for p in results.values() if p.exists())
    click.echo(click.style(f"\nDone. Generated metrics for {total} service(s).", fg="green"))


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
