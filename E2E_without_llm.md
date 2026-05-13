# End-to-End Testing Guide (without LLM)

## Overview

This document validates the complete deterministic monitoring pipeline before integrating:

* LLM analysis
* Gmail alerts
* Kubernetes
* Grafana
* Prometheus

Current validated architecture:

```text
Logs:
FolderLogSource / MockFileLogSource
        ↓
LogWatcher
        ↓
IncidentEvent
        ↓
HeuristicPredictor
        ↓
PredictorEvent

Metrics:
FolderMetricSource / MockMetricSource
        ↓
MetricPredictor
        ↓
MetricPredictionEvent
```

The `simulate` command is NOT part of the watcher/predictor architecture.

`simulate` currently validates ONLY:

```text
mock logs
    ↓
LLM provider
    ↓
AnalysisResult
```

It is standalone and only tests:

* LLM connectivity
* structured JSON parsing
* provider abstraction

---

# PART 1 — INITIAL VALIDATION

---

## STEP 1 — Activate Environment

From project root:

```bash
source ../venv/bin/activate
```

Verify:

```bash
which python
python --version
```

Expected:

* external virtualenv
* Python 3.11+

---

## STEP 2 — Install Package

```bash
pip install -e ".[test]"
```

---

## STEP 3 — Run Full Test Suite

```bash
pytest -v
```

Expected:

* all tests pass
* no hangs
* deterministic behavior
* no flaky streaming

---

## STEP 4 — Verify YAML Config

Open:

```text
config/config.yaml
```

Recommended local setup:

```yaml
log_source:
  type: mock

metrics:
  source:
    type: mock

  thresholds:
    cpu_percent: 85
    memory_percent: 90

  stream_interval_seconds: 5
```

---

# PART 2 — MOCK LOG PIPELINE TESTING

Validates:

* watcher
* heuristic predictor
* deduplication
* rolling windows
* escalation logic

---

## STEP 1 — Stream Mock Logs

```bash
python -m src stream-logs --duration 10
```

Expected:

* continuous log stream
* multiple services
* no crashes

---

## STEP 2 — Run Watcher

```bash
python -m src watch-logs --duration 15
```

Expected:

* IncidentEvent output
* regex detections
* severity classification
* context extraction

Validate:

* no duplicate spam
* no hangs
* deduplication works

---

## STEP 3 — Run Log Predictor

```bash
python -m src predict --duration 20
```

Expected pipeline:

```text
MockFileLogSource
    ↓
LogWatcher
    ↓
IncidentEvent
    ↓
HeuristicPredictor
    ↓
PredictorEvent
```

Expected output:

```text
[HIGH]
service=payment-service
pattern=Repeated HTTP 5xx error spikes detected
```

Validate:

* escalation works
* repeated incidents trigger predictions
* cooldown suppresses spam

---

# PART 3 — MOCK METRIC PIPELINE TESTING

Validates:

* statistical inference
* anomaly detection
* CPU forecasting
* memory forecasting
* OOM prediction

---

## STEP 1 — Stream Mock Metrics

```bash
python -m src stream-metrics --duration 15
```

Expected:

* MetricSample outputs
* multiple services
* realistic CPU/memory trends
* latency changes

Example:

```text
payment-service cpu=72 memory=68 latency=180
```

---

## STEP 2 — Run Metric Predictor

```bash
python -m src predict-metrics --duration 30
```

Expected pipeline:

```text
MockMetricSource
    ↓
MetricPredictor
    ↓
MetricPredictionEvent
```

Expected prediction examples:

```text
[HIGH]
service=payment-service
prediction=PREDICTED_CPU_BREACH
```

```text
[CRITICAL]
service=auth-service
prediction=PREDICTED_OOM
```

---

## STEP 3 — Validate Statistical Inference

Validate:

* moving averages stabilize noise
* anomaly spikes trigger events
* CPU threshold forecasting works
* memory threshold forecasting works
* cooldown suppresses repeated spam

---

# PART 4 — FOLDER LOG SOURCE TESTING

Validates realistic external log ingestion.

---

## STEP 1 — Create External Log Directory

```bash
mkdir -p ~/k8s-shared-logs
```

---

## STEP 2 — Create Service Log Files

```bash
touch ~/k8s-shared-logs/payment-service.log
touch ~/k8s-shared-logs/auth-service.log
touch ~/k8s-shared-logs/gateway.log
```

---

## STEP 3 — Configure Folder Source

Update:

```yaml
log_source:
  type: folder
  folder_path: /home/YOUR_USER/k8s-shared-logs
```

Replace `YOUR_USER` with your actual Linux username.

---

## STEP 4 — Stream Folder Logs

```bash
python -m src stream-logs --duration 0
```

Leave running.

---

## STEP 5 — Append Logs Externally

Open another terminal:

```bash
echo "ERROR HTTP 503 upstream service" >> ~/k8s-shared-logs/payment-service.log
```

Expected:

* line appears immediately

Append more:

```bash
echo "ERROR timeout connecting to db" >> ~/k8s-shared-logs/payment-service.log
```

---

## STEP 6 — Run Watcher Validation

```bash
python -m src watch-logs --duration 0
```

Append additional logs externally.

Expected:

* incidents detected in real time
* severity classification works
* context extraction works

---

## STEP 7 — Run Full Predictor Validation

```bash
python -m src predict --duration 0
```

Append repeated failures:

```bash
echo "ERROR HTTP 503 upstream" >> ~/k8s-shared-logs/payment-service.log
echo "ERROR HTTP 503 upstream" >> ~/k8s-shared-logs/payment-service.log
echo "ERROR HTTP 503 upstream" >> ~/k8s-shared-logs/payment-service.log
```

Expected:

```text
[HIGH]
service=payment-service
pattern=Repeated HTTP 5xx error spikes detected
```

---

# PART 5 — FOLDER METRIC SOURCE TESTING

Validates realistic external metric ingestion.

---

## STEP 1 — Create Metric Directory

```bash
mkdir -p ~/k8s-shared-metrics
```

---

## STEP 2 — Create CSV Metric Files

```bash
touch ~/k8s-shared-metrics/payment-service.csv
touch ~/k8s-shared-metrics/auth-service.csv
```

---

## STEP 3 — Configure Metric Folder Source

Update:

```yaml
metrics:
  source:
    type: folder
    folder_path: /home/YOUR_USER/k8s-shared-metrics
```

---

## STEP 4 — Stream Metrics

```bash
python -m src stream-metrics --duration 0
```

---

## STEP 5 — Append Metrics Externally

Append realistic metric data:

```bash
echo "2026-01-01T10:00:00Z,payment-service,72,68,120,0.01" >> ~/k8s-shared-metrics/payment-service.csv
```

Append escalating metrics:

```bash
echo "2026-01-01T10:00:15Z,payment-service,82,78,180,0.04" >> ~/k8s-shared-metrics/payment-service.csv

echo "2026-01-01T10:00:30Z,payment-service,91,88,320,0.12" >> ~/k8s-shared-metrics/payment-service.csv
```

Expected:

* streamed MetricSample output
* no crashes
* proper parsing

---

## STEP 6 — Run Metric Predictor

```bash
python -m src predict-metrics --duration 0
```

Expected outputs:

```text
[HIGH]
prediction=PREDICTED_CPU_BREACH
```

```text
[CRITICAL]
prediction=PREDICTED_OOM
```

---

## STEP 7 — Validate Anomaly Detection

Append anomaly spike:

```bash
echo "2026-01-01T10:01:00Z,payment-service,40,35,1200,0.30" >> ~/k8s-shared-metrics/payment-service.csv
```

Expected:

```text
LATENCY_ANOMALY
```

Validate:

* z-score anomaly detection works
* predictor remains stable
* no event spam

---

# PART 6 — COMBINED PIPELINE VALIDATION

This simulates realistic production-like behavior.

Run simultaneously:

Terminal 1:

```bash
python -m src predict --duration 0
```

Terminal 2:

```bash
python -m src predict-metrics --duration 0
```

Terminal 3:

append logs + metrics continuously.

Validate:

* independent pipelines
* service isolation
* no cross contamination
* stable long-running behavior

---

# PART 7 — LONG STABILITY TEST

Run for extended duration:

```bash
python -m src predict --duration 120
```

and:

```bash
python -m src predict-metrics --duration 120
```

Validate:

* memory stability
* bounded rolling windows
* no CPU spikes
* no duplicate floods
* graceful shutdown

---

# Success Criteria

If all tests pass:

```text
external append
    ↓
source ingestion
    ↓
watcher/predictor detection
    ↓
prediction generation
```

then the deterministic monitoring system is complete.

At this point:

* Kubernetes integration becomes optional
* Grafana integration becomes optional
* Prometheus integration becomes optional

because the architecture already simulates:

* shared cluster log volumes
* shared metric volumes
* centralized observability
* predictive monitoring

very realistically.

Next phase:

```text
PredictorEvent / MetricPredictionEvent
                ↓
              LLM
                ↓
          Gmail Alert
```
