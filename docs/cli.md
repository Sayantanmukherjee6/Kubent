# CLI Commands

All commands are invoked via `python -m src <command>`.

## Implemented Commands

### `generate-logs` — Write a batch of mock logs to a file

```bash
# Generate default (50 lines) to mocks/logs/generated.log
# Default count comes from MOCK_LOG_COUNT env var (default: 50)
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
| `--count` | -c | 50 (from MOCK_LOG_COUNT) | Number of log lines to generate |
| `--output` | -o | mocks/logs/generated.log | Output file path |
| `--services` | -s | All configured services | Comma-separated service names |
| `--severities` | - | info,warn,error,critical | Comma-separated severity levels |

### `stream-logs` — Stream mock logs in real-time

**Mode 1: Full mock file source** (generates + streams):

```bash
python -m src stream-logs --duration 10   # Stream for 10 seconds (default duration)
python -m src stream-logs --duration 0    # Infinite mode (Ctrl+C to stop)
```

**Mode 2: Tail an existing file**:

```bash
python -m src stream-logs --source-file mocks/logs/generated.log
```

Options:

| Option | Short | Default | Description |
|---|---|---|---|
| `--duration` | -d | 10 | Seconds to stream (0 = infinite) |
| `--source-file` | -f | None | Existing log file to tail |

### `watch-logs` — Stream logs and detect incidents (no LLM)

Watches a mock log source for errors using regex-based detection, extracts surrounding context, deduplicates noisy events, and prints structured incident summaries.

```bash
python -m src watch-logs --duration 15
python -m src watch-logs --min-severity high --dedup-ttl 600
python -m src watch-logs --context-before 10 --context-after 5 --dedup-threshold 3
```

Options:

| Option | Default | Description |
|---|---|---|
| `--duration` / `-d` | 15 | Seconds to watch (0 = infinite) |
| `--min-severity` / `-s` | medium | Minimum severity: low, medium, high, critical |
| `--dedup-ttl` / `-t` | 300 | Deduplication TTL in seconds |
| `--dedup-threshold` / `-n` | 1 | Min occurrences before emitting |
| `--context-before` / `-b` | 5 | Preceding context lines |
| `--context-after` / `-a` | 3 | Following context lines |

### `predict` — Run predictive anomaly detection

Streams logs through the watcher subsystem and applies heuristic prediction rules.

```bash
python -m src predict
python -m src predict --duration 30
```

### `simulate` — Generate mock logs and send to LLM for analysis

```bash
python -m src simulate
python -m src simulate --count 100 --provider openai
```

## Help

```bash
python -m src --help
python -m src generate-logs --help
python -m src stream-logs --help
python -m src watch-logs --help
python -m src simulate --help
```
