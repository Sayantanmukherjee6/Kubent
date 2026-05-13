# CLI Commands

All commands are invoked via `python -m src <command>`.

## Implemented Commands

### `generate-logs` — Write a batch of mock logs to a file

```bash
# Generate default (50 lines) to mocks/logs/generated.log
python -m src generate-logs

# Custom count and output path
python -m src generate-logs --count 200 -o /tmp/my-logs.log

# Specific services and severities
python -m src generate-logs \
    --services "auth-service,payment-service,gateway" \
    --severities "error,critical" \
    --count 100
```

Options:

| Option | Short | Default | Description |
|---|---|---|---|
| `--count` | -c | 50 | Number of log lines to generate |
| `--output` | -o | mocks/logs/generated.log | Output file path |
| `--services` | -s | All configured services | Comma-separated service names |
| `--severities` | — | info,warn,error,critical | Comma-separated severity levels |

### `stream-logs` — Stream logs in real-time

Uses the log source factory. Override source type and directory via `--source` and `--log-dir`.

```bash
python -m src stream-logs --duration 10   # Stream for 10 seconds
python -m src stream-logs --duration 0    # Infinite mode (Ctrl+C to stop)
python -m src stream-logs --source folder --log-dir /tmp/k8s-logs
```

Options:

| Option | Short | Default | Description |
|---|---|---|---|
| `--duration` | -d | 10 | Seconds to stream (0 = infinite) |
| `--source-file` | -f | None | Existing log file to tail (bypasses factory) |
| `--source` | -S | (from config) | Override: mock or folder |
| `--log-dir` | — | (from config) | Override log directory path |

### `watch-logs` — Stream logs and detect incidents (no LLM)

Watches a log source for errors using regex-based detection, extracts surrounding context, deduplicates noisy events, and prints structured incident summaries.

```bash
python -m src watch-logs --duration 15
python -m src watch-logs --min-severity high --dedup-ttl 600
python -m src watch-logs --source folder --log-dir /tmp/k8s-logs
```

Options:

| Option | Short | Default | Description |
|---|---|---|---|
| `--duration` | -d | 15 | Seconds to watch (0 = infinite) |
| `--min-severity` | -s | medium | low, medium, high, critical |
| `--dedup-ttl` | -t | 300 | Deduplication TTL in seconds |
| `--dedup-threshold` | -n | 1 | Min occurrences before emitting |
| `--context-before` | -b | 5 | Preceding context lines |
| `--context-after` | -a | 3 | Following context lines |
| `--source` | -S | (from config) | Override: mock or folder |
| `--log-dir` | — | (from config) | Override log directory path |

### `predict` — Stream logs, run watcher + predictor, print predictions

Wires the LogWatcher pipeline into HeuristicPredictor so that every detected
IncidentEvent is fed through the heuristic engine and resulting PredictorEvents
are printed as color-coded terminal output.

```bash
# Default: mock source, 15s duration, medium severity
python -m src predict

# Custom duration and severity
python -m src predict --duration 30 --min-severity high

# Override log source
python -m src predict --source folder --log-dir /var/log/k8s-apps
python -m src predict --source mock --log-dir /tmp/demo-logs

# Combine all options
python -m src predict -S folder -d 20 -s high -t 600 -n 2 --log-dir /tmp/logs
```

**Output format:**

```
[HIGH]  #1
  service   = payment-service
  pattern   = Repeated HTTP 5xx error spikes detected
  trigger_count = 5
  related   = abc123def456

[CRITICAL]  #2
  service   = auth-service
  pattern   = Repeated OOMKilled events detected
  trigger_count = 3
```

Options:

| Option | Short | Default | Description |
|---|---|---|---|
| `--duration` | -d | 15 | Seconds to watch (0 = infinite) |
| `--min-severity` | -s | medium | low, medium, high, critical |
| `--dedup-ttl` | -t | 300 | Deduplication TTL in seconds |
| `--dedup-threshold` | -n | 1 | Min occurrences before emitting |
| `--source` | -S | (from config) | Override: mock or folder |
| `--log-dir` | — | (from config) | Override log directory path |

### `stream-metrics` — Stream metrics in real-time

Streams `MetricSample` objects from the configured metric source and prints
formatted output to the terminal. Supports both `mock` (synthetic) and `folder`
(CSV-based) metric sources. No prediction or alerting — raw metric streaming only.

```bash
python -m src stream-metrics --duration 10   # Stream for 10 seconds (mock source)
python -m src stream-metrics --duration 0    # Infinite mode (Ctrl+C to stop)
python -m src stream-metrics --source folder --metric-dir ./demo_metrics
```

**Example output:**

```
Streaming from mock-metrics:auth-service,payment-service,gateway (Ctrl+C to stop)...
----------------------------------------------------------------------
[10:30:45] auth-service                CPU= 52.3%  MEM= 55.0%  LAT= 105.2ms  ERR=0.0100
[10:30:45] payment-service             CPU= 48.7%  MEM= 50.2%  LAT=  98.5ms  ERR=0.0050
[10:30:45] gateway                     CPU= 60.1%  MEM= 62.8%  LAT= 120.0ms  ERR=0.0150
...
Stopped. Received 18 metric samples.
```

Options:

| Option | Short | Default | Description |
|---|---|---|---|
| `--duration` | -d | 10 | Seconds to stream (0 = infinite) |
| `--source` | -S | (from config) | Override: mock or folder |
| `--metric-dir` | — | (from config) | Override metric directory path |

### `simulate` — Generate mock logs and send to LLM for analysis

```bash
python -m src simulate
python -m src simulate --count 100 --provider openai
```

Options:

| Option | Short | Default | Description |
|---|---|---|---|
| `--count` | — | 50 | Number of mock log lines |
| `--provider` | — | (from config) | Override LLM provider |

## Log Source Overrides

All commands that consume logs (`stream-logs`, `watch-logs`, `predict`) use the
log source factory. Override the source type and directory without modifying
`config/config.yaml`:

```bash
# Override source type
python -m src predict --source folder

# Override directory
python -m src predict --log-dir /tmp/k8s-logs

# Override both
python -m src predict --source folder --log-dir /tmp/k8s-logs
```

## Help

```bash
python -m src --help
python -m src generate-logs --help
python -m src stream-logs --help
python -m src stream-metrics --help
python -m src watch-logs --help
python -m src predict --help
python -m src simulate --help
```
