#!/usr/bin/env python3
"""Generate realistic CSV metric files into /Users/anonymous/Documents/projects/hackathon/logs.

These files are consumed by FolderMetricSource for testing the metrics pipeline.

Usage:
    python generate_test_metrics.py

Or with custom options:
    python generate_test_metrics.py --output-dir ./logs --steps 100 --scenarios steady_cpu_growth,memory_leak,latency_spike
"""

import argparse
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.metrics.scenario_generator import generate_demo_metrics, generate_all_default_scenarios


def main():
    parser = argparse.ArgumentParser(description="Generate realistic CSV metric files for testing.")
    parser.add_argument(
        "--output-dir", "-o",
        default="/Users/anonymous/Documents/projects/hackathon/logs",
        help="Directory to write CSV files into (default: /Users/anonymous/Documents/projects/hackathon/logs)",
    )
    parser.add_argument(
        "--steps", "-s",
        type=int,
        default=60,
        help="Number of metric steps per service (default: 60)",
    )
    parser.add_argument(
        "--scenarios", "-c",
        type=str,
        default=None,
        help="Comma-separated scenario names (e.g. steady_cpu_growth,memory_leak,latency_spike). "
             "If omitted, uses per-service defaults.",
    )
    parser.add_argument(
        "--services", "-sv",
        type=str,
        default=None,
        help="Comma-separated service names (e.g. gateway,payment-service,auth-service). "
             "If omitted, uses all default services.",
    )
    args = parser.parse_args()

    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    scenarios = args.scenarios.split(",") if args.scenarios else None
    services = args.services.split(",") if args.services else None

    print(f"Generating metrics to: {output_path}")
    print(f"  Steps: {args.steps}")
    print(f"  Scenarios: {scenarios or 'per-service defaults'}")
    print(f"  Services: {services or 'all defaults'}")

    if scenarios:
        results = generate_demo_metrics(
            output_dir=str(output_path),
            scenarios=scenarios,
            services=services,
            total_steps=args.steps,
        )
    else:
        results = generate_all_default_scenarios(
            output_dir=str(output_path),
            total_steps=args.steps,
        )

    print(f"\nGenerated {len(results)} CSV file(s):")
    for svc, path in sorted(results.items()):
        size = path.stat().st_size
        lines = sum(1 for _ in open(path)) - 1  # subtract header
        print(f"  {svc}: {path} ({lines} samples, {size} bytes)")

    print("\nDone! These files can be consumed by FolderMetricSource.")


if __name__ == "__main__":
    main()
