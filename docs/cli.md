# CLI Commands

All commands are invoked via `python -m src <command>`.

## `generate-logs` — Write a batch of mock logs to a file

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

## `stream-logs` — Stream mock logs in real-time

**Mode 1: Full mock file source** (generates + streams):

```bash
python -m src stream-logs --duration 15   # Stream for 15 seconds
python -m src stream-logs --duration 0    # Infinite mode (Ctrl+C to stop)
```

**Mode 2: Tail an existing file**:

```bash
python -m src stream-logs --source-file mocks/logs/generated.log
```

## `simulate` — Generate mock logs and send to LLM for analysis

```bash
python -m src simulate
python -m src simulate --count 100 --provider openai
```

## Help

```bash
python -m src --help
python -m src generate-logs --help
python -m src stream-logs --help
python -m src simulate --help
```
