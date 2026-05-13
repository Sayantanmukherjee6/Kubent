"""Demo metric file generator — writes realistic CSV metric streams.

Generates deterministic, scenario-driven CSV files into a demo directory for
use with ``FolderMetricSource`` or manual inspection.

Usage
-----

.. code-block:: bash

    python -m src generate-metrics --scenarios steady_cpu_growth,memory_leak \\
        --services payment-service auth-service gateway --duration 60

.. code-block:: python

    from src.core.metrics.scenario_generator import generate_demo_metrics

    generate_demo_metrics(
        output_dir="./demo_metrics",
        scenarios=["steady_cpu_growth", "memory_leak"],
        services=["payment-service", "auth-service", "gateway"],
        total_steps=60,
    )
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

from src.core.metrics.scenarios import ScenarioEngine


def generate_demo_metrics(
    output_dir: str = "./demo_metrics",
    scenarios: List[str] | None = None,
    services: List[str] | None = None,
    total_steps: int = 60,
    start_time: datetime | None = None,
) -> Dict[str, Path]:
    """Generate realistic CSV metric files for demo purposes.

    Args:
        output_dir: Directory to write CSV files into. Created if missing.
        scenarios: Scenario names to use. If None, uses per-service defaults.
        services: Service names to generate metrics for.
        total_steps: Number of metric steps (samples) per service.
        start_time: Starting timestamp (default: now).

    Returns:
        Dict mapping service name to the generated CSV file path.
    """
    if start_time is None:
        start_time = datetime.now(timezone.utc)

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    engine = ScenarioEngine(scenarios=scenarios, services=services)
    results: Dict[str, Path] = {}

    for svc in engine._services:
        csv_file = out_path / f"{svc}.csv"
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "service", "cpu", "memory", "latency", "error_rate"])

            for step in range(total_steps):
                state = engine.advance(svc)
                ts = start_time + timedelta(seconds=step * 5)
                writer.writerow([
                    ts.isoformat(),
                    svc,
                    f"{state.cpu:.2f}",
                    f"{state.memory:.2f}",
                    f"{state.latency:.2f}",
                    f"{state.error_rate:.4f}",
                ])
        results[svc] = csv_file

    return results


def generate_all_default_scenarios(
    output_dir: str = "./demo_metrics",
    total_steps: int = 60,
    start_time: datetime | None = None,
) -> Dict[str, Path]:
    """Generate metrics for all default service-scenario pairings.

    This is the quickest way to get a full demo set:
        - gateway → steady_cpu_growth
        - payment-service → latency_spike
        - auth-service → memory_leak
        - others → steady_cpu_growth (fallback)
    """
    return generate_demo_metrics(
        output_dir=output_dir,
        scenarios=None,  # uses per-service defaults
        services=None,   # uses default service list
        total_steps=total_steps,
        start_time=start_time,
    )


def list_available_scenarios() -> List[str]:
    """Return all available scenario names."""
    return ScenarioEngine.list_scenarios()


def get_scenario_description(name: str) -> str | None:
    """Return the description for a scenario, or None if not found."""
    info = ScenarioEngine.get_scenario_info(name)
    return info["description"] if info else None
