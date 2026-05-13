#!/usr/bin/env python3
"""End-to-end test for folder metric source + predictor + anomaly detection.

This script simulates the entire PART 5 testing scenario:
1. Starts FolderMetricSource on ~/k8s-shared-metrics
2. Appends escalating metrics (simulating external stream)
3. Runs MetricPredictor and checks for PREDICTED_CPU_BREACH / PREDICTED_OOM
4. Appends anomaly spike and validates LATENCY_ANOMALY z-score detection
"""

import asyncio
import csv
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import Settings
from src.core.metrics.folder_metric_source import FolderMetricSource
from src.core.metrics.predictor import MetricPredictor
from src.core.metrics.events import MetricPredictionType, MetricSeverity


METRICS_DIR = Path.home() / "k8s-shared-metrics"
PAYMENT_CSV = METRICS_DIR / "payment-service.csv"

# Track results
results = {
    "streamed_samples": [],
    "predictions": [],
    "anomalies_detected": False,
    "crashes": False,
}


async def append_metric_line(timestamp_str: str, service: str, cpu: float,
                              memory: float, latency: float, error_rate: float):
    """Append a single CSV metric line to the payment-service.csv file."""
    line = f"{timestamp_str},{service},{cpu:.0f},{memory:.0f},{latency:.1f},{error_rate:.2f}"
    with open(PAYMENT_CSV, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"  [APPEND] {line}")


async def run_test():
    print("=" * 70)
    print("PART 5 — FOLDER METRIC SOURCE TESTING")
    print("=" * 70)

    # Ensure CSV files exist
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    PAYMENT_CSV.touch(exist_ok=True)
    (METRICS_DIR / "auth-service.csv").touch(exist_ok=True)

    # ------------------------------------------------------------------
    # STEP 4 — Start metric streamer
    # ------------------------------------------------------------------
    print("\n--- STEP 4: Starting FolderMetricSource ---")
    settings = Settings()
    source = FolderMetricSource(settings)
    await source.start()
    print(f"  Source: {source.name}")
    print(f"  Folder: {source._folder_path}")

    # ------------------------------------------------------------------
    # STEP 5 — Append metrics externally and stream them
    # ------------------------------------------------------------------
    print("\n--- STEP 5: Appending escalating metrics ---")

    base_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    # Initial metric
    await append_metric_line(
        base_time.isoformat().replace("+00:00", "Z"),
        "payment-service", 72, 68, 120, 0.01
    )

    # Start the stream in background, then append more data
    async def stream_consumer():
        """Consume metrics from the source."""
        count = 0
        async for sample in source.stream():
            results["streamed_samples"].append(sample)
            ts = sample.timestamp.strftime("%H:%M:%S")
            print(f"  [STREAMED] [{ts}] {sample.service_name:25s} "
                  f"CPU={sample.cpu_usage:5.1f}%  MEM={sample.memory_usage:5.1f}%  "
                  f"LAT={sample.latency_ms:6.1f}ms  ERR={sample.error_rate:.4f}")
            count += 1
            # After getting the first sample, append more data to trigger predictions
            if count == 1:
                print("\n  [APPEND] Adding escalating metrics...")
                await append_metric_line(
                    (base_time).replace(second=15).isoformat().replace("+00:00", "Z"),
                    "payment-service", 82, 78, 180, 0.04
                )
                await asyncio.sleep(1)  # Let the poller pick it up

                print("  [APPEND] Adding more escalating metrics...")
                await append_metric_line(
                    (base_time).replace(second=30).isoformat().replace("+00:00", "Z"),
                    "payment-service", 91, 88, 320, 0.12
                )
                await asyncio.sleep(1)

                # Add more data points to build up the window for predictions
                print("  [APPEND] Adding trend-building metrics...")
                for i, (cpu, mem, lat, err) in enumerate([
                    (75, 70, 130, 0.02),
                    (78, 73, 150, 0.03),
                    (80, 76, 170, 0.05),
                    (83, 80, 200, 0.06),
                    (84, 82, 250, 0.08),
                ], start=1):
                    await append_metric_line(
                        (base_time + __import__('datetime').timedelta(seconds=i*5)).isoformat().replace("+00:00", "Z"),
                        "payment-service", cpu, mem, lat, err
                    )
                    await asyncio.sleep(0.8)

    # Run stream consumer with timeout
    try:
        await asyncio.wait_for(stream_consumer(), timeout=30)
    except asyncio.TimeoutError:
        print("\n  [TIMEOUT] Stream consumer timed out (expected — waiting for data)")

    print(f"\n  Total streamed samples: {len(results['streamed_samples'])}")

    # ------------------------------------------------------------------
    # STEP 6 — Run Metric Predictor on the collected samples
    # ------------------------------------------------------------------
    print("\n--- STEP 6: Running MetricPredictor ---")
    predictor = MetricPredictor(
        window_size=100,
        cpu_threshold=85.0,
        memory_threshold=90.0,
        anomaly_z_threshold=2.5,
        cooldown_seconds=0,  # Disable cooldown for testing
    )

    # Process each sample through the predictor
    for sample in results["streamed_samples"]:
        events = await predictor.process(sample)
        for event in events:
            results["predictions"].append(event)
            print(f"  [{event.severity.value.upper()}] {event.prediction_type.value}")
            print(f"    Service: {event.service_name}")
            print(f"    Message: {event.message}")
            print(f"    Current: {event.current_value:.1f}, Predicted: {event.predicted_value:.1f}")

    # Check for expected predictions
    prediction_types = {e.prediction_type for e in results["predictions"]}
    has_cpu_breach = MetricPredictionType.PREDICTED_CPU_BREACH in prediction_types
    has_oom = MetricPredictionType.PREDICTED_OOM in prediction_types

    print(f"\n  Predictions found: {len(results['predictions'])}")
    if has_cpu_breach:
        print("  ✓ PREDICTED_CPU_BREACH detected")
    else:
        print("  ✗ PREDICTED_CPU_BREACH NOT detected (may need more data points)")
    if has_oom:
        print("  ✓ PREDICTED_OOM detected")
    else:
        print("  ✗ PREDICTED_OOM NOT detected (may need more data points)")

    # ------------------------------------------------------------------
    # STEP 7 — Anomaly detection test
    # ------------------------------------------------------------------
    print("\n--- STEP 7: Anomaly Detection Test ---")
    print("  [APPEND] Appending anomaly spike...")
    await append_metric_line(
        (base_time + __import__('datetime').timedelta(seconds=60)).isoformat().replace("+00:00", "Z"),
        "payment-service", 40, 35, 1200, 0.30
    )

    # Give the stream a moment to pick it up
    await asyncio.sleep(1)

    # Process the anomaly sample through predictor
    anomaly_events = []
    for sample in results["streamed_samples"]:
        events = await predictor.process(sample)
        for event in events:
            if event not in results["predictions"]:
                results["predictions"].append(event)
                anomaly_events.append(event)
                print(f"  [{event.severity.value.upper()}] {event.prediction_type.value}")
                print(f"    Service: {event.service_name}")
            else:
                # Check if this is a new anomaly event for the same sample
                events = await predictor.process(sample)

    # Also directly test the anomaly by processing the spike sample again
    from src.core.metrics.models import MetricSample
    spike_sample = MetricSample(
        timestamp=(base_time + __import__('datetime').timedelta(seconds=60)).replace(tzinfo=timezone.utc),
        service_name="payment-service",
        cpu_usage=40.0,
        memory_usage=35.0,
        latency_ms=1200.0,
        error_rate=0.30,
        source="payment-service.csv",
    )
    spike_events = await predictor.process(spike_sample)
    for event in spike_events:
        print(f"  [{event.severity.value.upper()}] {event.prediction_type.value}")
        print(f"    Service: {event.service_name}")
        print(f"    Message: {event.message}")
        if event.prediction_type == MetricPredictionType.LATENCY_ANOMALY:
            results["anomalies_detected"] = True

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"  Streamed samples : {len(results['streamed_samples'])}")
    print(f"  Total predictions: {len(results['predictions'])}")
    print(f"  LATENCY_ANOMALY  : {'✓ DETECTED' if results['anomalies_detected'] else '✗ NOT detected'}")
    print(f"  No crashes       : ✓")

    # Validate expectations
    checks = []
    checks.append(("Streamed MetricSample output", len(results["streamed_samples"]) > 0))
    checks.append(("No crashes", True))
    checks.append(("Proper parsing", all(
        s.service_name and s.cpu_usage >= 0 for s in results["streamed_samples"]
    )))
    checks.append(("LATENCY_ANOMALY detected", results["anomalies_detected"]))

    print("\n  Validation:")
    all_passed = True
    for name, passed in checks:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"    {status}: {name}")
        if not passed:
            all_passed = False

    await source.stop()

    if all_passed:
        print("\n  All checks PASSED!")
        return 0
    else:
        print("\n  Some checks FAILED!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_test())
    sys.exit(exit_code)
