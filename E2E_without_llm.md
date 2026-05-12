# End-to-End Testing Guide(without llm)

## Overview

This document validates the full deterministic pipeline before integrating the LLM layer.

Current validated architecture:

```text
FolderLogSource / MockFileLogSource
        ↓
LogWatcher
        ↓
IncidentEvent
        ↓
HeuristicPredictor
        ↓
PredictorEvent
```

The `simulate` command is NOT part of the watcher/predictor pipeline.

`simulate` currently does:

```text
mock logs
    ↓
LLM provider
    ↓
AnalysisResult
```

It is standalone and only validates LLM connectivity and structured responses.

---

# PART 1 — MOCK SOURCE TESTING

This validates:

* watcher
* predictor
* pipeline wiring
* deduplication
* heuristics

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
* no flaky behavior

---

## STEP 4 — Verify YAML Config

Open:

```text
config/config.yaml
```

Set:

```yaml
log_source:
  type: mock
```

---

## STEP 5 — Run Stream Test

```bash
python -m src stream-logs --duration 10
```

Here duration is in seconds. For running indefinitely, use `--duration 0`.

Expected:

* streaming logs
* multiple services
* no crashes

---

## STEP 6 — Run Watcher Test

```bash
python -m src watch-logs --duration 15
```

Expected:

* IncidentEvent outputs
* regex detections
* severity classifications
* extracted context

Validate:

* dedup works
* no spam flood
* no hangs

---

## STEP 7 — Run Predictor Test

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
* repeated incidents trigger prediction
* output formatting is readable

---

# PART 2 — FOLDER SOURCE TESTING (REALISTIC DEMO)

This validates realistic external log ingestion.

---

## STEP 1 — Create External Log Directory

Do NOT use `mocks/`.

Use an external shared-style directory:

```bash
mkdir -p ~/k8s-shared-logs
```

---

## STEP 2 — Create Service Logs

```bash
touch ~/k8s-shared-logs/payment-service.log
touch ~/k8s-shared-logs/auth-service.log
touch ~/k8s-shared-logs/gateway.log
```

---

## STEP 3 — Switch YAML Config

Update:

```yaml
log_source:
  type: folder
  folder_path: /home/YOUR_USER/k8s-shared-logs
```

Replace `YOUR_USER` with your actual Linux username.

---

## STEP 4 — Run Stream Validation

```bash
python -m src stream-logs --duration 0
```

Leave it running.

---

## STEP 5 — Append Logs Externally

Open another terminal.

Append:

```bash
echo "ERROR HTTP 503 upstream service" >> ~/k8s-shared-logs/payment-service.log
```

Expected:

* streamed line appears immediately

Append more:

```bash
echo "ERROR timeout connecting to db" >> ~/k8s-shared-logs/payment-service.log
```

---

## STEP 6 — Run Watcher Validation

Terminal 1:

```bash
python -m src watch-logs --duration 0
```

Terminal 2:

append additional logs.

Expected:

* incidents detected in real time
* severity classification works
* context extraction works

---

## STEP 7 — Run Full Predictor Validation

Terminal 1:

```bash
python -m src predict --duration 0
```

Terminal 2:

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

## STEP 8 — Test Critical Escalation

Append:

```bash
echo "CRITICAL OOMKilled" >> ~/k8s-shared-logs/auth-service.log
echo "CRITICAL OOMKilled" >> ~/k8s-shared-logs/auth-service.log
```

Expected:

```text
[CRITICAL]
service=auth-service
pattern=Repeated OOMKilled events detected
```

---

## STEP 9 — Multi-Service Validation

Append simultaneously:

```bash
echo "ERROR timeout connecting to db" >> ~/k8s-shared-logs/payment-service.log

echo "ERROR connection refused" >> ~/k8s-shared-logs/gateway.log
```

Validate:

* services remain isolated
* rolling windows are per-service
* no cross-contamination

---

## STEP 10 — Long Stability Test

Run:

```bash
python -m src predict --duration 120
```

Append logs continuously.

Watch for:

* memory stability
* no duplicate floods
* no CPU spikes
* clean shutdown behavior

---

# Success Criteria

If all tests pass successfully:

```text
external log append
    ↓
watcher detects
    ↓
predictor escalates
```

then the deterministic monitoring pipeline is complete.

At this point:

* Kubernetes integration becomes optional
* Grafana integration becomes optional

because the architecture already simulates:

* shared cluster log volumes
* pod log ingestion
* centralized monitoring

very realistically.


