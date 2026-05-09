# Kubernetes Agent — AI-Powered Observability Assistant

An AI-powered observability assistant that monitors simulated Kubernetes/Grafana logs, detects errors, and sends them to an LLM for root cause analysis, severity classification, remediation suggestions, and preventive actions.

## Table of Contents

- [Project Overview](#project-overview)
- [Architecture Overview](#architecture-overview)
- [Folder Structure](#folder-structure)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Configuration](#configuration)
- [CLI Commands](#cli-commands)
- [Mock Log Source System](#mock-log-source-system)
  - [Log Source Abstraction](#log-source-abstraction)
  - [Mock File Log Source](#mock-file-log-source)
  - [Mock Log Generator](#mock-log-generator)
- [Running Tests](#running-tests)
- [Local LLM Integration (llama.cpp)](#local-llm-integration-llamacpp)
- [OpenAI Integration](#openai-integration)
- [Future Roadmap](#future-roadmap)

---

## Project Overview

This project is a **hackathon MVP** that demonstrates an AI-powered observability pipeline:

1. **Log ingestion** — Currently uses mock/simulated logs via a pluggable log source abstraction (real Kubernetes, Grafana Loki, and Prometheus integrations are planned).
2. **Error detection** — Identifies error and critical severity log entries.
3. **LLM analysis** — Sends log context to an LLM (local llama.cpp or OpenAI) which returns:
   - Root cause analysis
   - Severity classification (critical / high / medium / low)
   - Remediation suggestions
   - Preventive actions

### Design Principles

- **Local-first**: Runs entirely on your machine with a local llama.cpp server.
- **Minimal dependencies**: No LangChain, no CrewAI, no AutoGen — just clean Python with `asyncio`, `httpx`, and `pydantic`.
- **Log source abstraction**: Swapping the log source (mock file → Kubernetes → Loki) is done by implementing one interface — downstream logic never changes.
- **Provider abstraction**: Swapping the LLM backend is as simple as changing one environment variable.
- **Mock-first development**: Full mock log generation with streaming simulation for testing without any external infrastructure.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                    CLI (click)                       │
│  generate-logs | stream-logs | simulate             │
└──────┬──────────────────────┬───────────────────────┘
       │                      │
       ▼                      ▼
┌──────────────────┐  ┌──────────────────────────────┐
│ Mock File Log    │  │  LLM Providers               │
│ Source           │  │                              │
│ src/core/        │  │  BaseLlmProvider (ABC)       │
│ log_sources/     │  │   ├── LlamaCppProvider       │
│                  │  │   └── OpenAiProvider         │
│ - reads mock     │  │                              │
│   files          │  │  Factory: create_llm_provider│
│ - streams        │  │      (settings) -> provider  │
│   appended lines │  │                              │
│ - start/stop     │  └──────────────┬───────────────┘
│   lifecycle      │                 │
└──────────────────┘                 ▼
       │                    ┌──────────────────┐
       ▼                    │ AnalysisResult   │
┌──────────────────┐        │ (dataclass)      │
│ Mock Log         │        │ - root_cause     │
│ Generator        │        │ - severity       │
│ mocks/generators/│        │ - remediation    │
│ log_generator.py │        │ - preventive     │
└──────────────────┘        └──────────────────┘
  Generates realistic
  K8s-style logs with:
  - tracebacks, HTTP errors,
    DB failures, OOM kills,
    pod restarts, retry fails
```

### Key Abstractions

- **`BaseLogSource`** (`src/core/log_sources/base.py`): Abstract base class defining the `start()`, `stop()`, and async `stream()` interface. Every log source (mock file, Kubernetes, Loki) implements this.
- **`MockFileLogSource`**: Reads mock files, writes new lines in a background task, and tails the file via an async generator.
- **`BaseLlmProvider`** (`src/providers/base.py`): Abstract base class defining `analyze(log_context: str) -> AnalysisResult`.
- **`AnalysisResult`**: Frozen dataclass holding structured LLM output.
- **`create_llm_provider(settings)`**: Factory function that instantiates the correct provider based on `LLM_PROVIDER` in `.env`.

---

## Folder Structure

```
project/
│
├── src/                          # Main source code
│   ├── __init__.py
│   ├── __main__.py               # CLI entrypoint (click-based)
│   │
│   ├── config/                   # Configuration module
│   │   ├── __init__.py
│   │   └── settings.py           # Pydantic Settings loaded from .env
│   │
│   ├── core/                     # Core business logic
│   │   ├── __init__.py
│   │   └── log_sources/          # Log source abstraction layer
│   │       ├── base.py           # BaseLogSource ABC + LogLine dataclass
│   │       └── mock_file_source.py  # Mock file-based log source
│   │
│   ├── providers/                # LLM provider implementations
│   │   ├── __init__.py
│   │   ├── base.py               # Abstract base class + AnalysisResult
│   │   ├── llama_cpp.py          # Local llama.cpp provider
│   │   ├── openai.py             # OpenAI API provider
│   │   └── factory.py            # Provider creation factory
│   │
│   └── utils/                    # Utility functions (future)
│       └── __init__.py
│
├── tests/                        # Test suite (separated from source)
│   ├── __init__.py
│   ├── unit/                     # Unit tests (no network calls)
│   │   ├── __init__.py
│   │   ├── test_config.py        # Config loading + provider factory tests
│   │   └── test_log_sources.py   # Log generator + settings tests
│   │
│   └── integration/              # Integration tests (mock HTTP / file I/O)
│       ├── __init__.py
│       ├── test_llm_pipeline.py  # End-to-end pipeline with mock server
│       └── test_log_sources.py   # Log source lifecycle + streaming tests
│
├── mocks/                        # Mock/simulation resources
│   ├── __init__.py
│   ├── logs/                     # Sample log files
│   │   ├── __init__.py
│   │   └── sample_k8s_errors.log # Pre-generated sample logs
│   │
│   └── generators/               # Log generation utilities
│       ├── __init__.py
│       └── log_generator.py      # Reusable mock log generator + async streamer
│
├── .env.example                  # Environment variable template
├── .gitignore                    # Git ignore rules
├── pyproject.toml                # Project metadata + pytest config
└── requirements.txt              # pip dependencies
```

---

## Prerequisites

- **Python 3.11+** (required for `match` statements and type features)
- **External virtualenv** at `../venv/` relative to this project root
- **(Optional)** A running [llama.cpp server](#local-llm-integration-llamacpp) for local LLM analysis

---

## Setup

### 1. Activate the External Virtualenv

The virtualenv lives **outside** the project directory at `../venv/`:

```bash
cd /Users/anonymous/Documents/projects/hackathon/kubernetes-agent
source ../venv/bin/activate
```

Verify:

```bash
python --version
# Should show Python 3.11+ from the virtualenv, NOT your system Python
which python
# Should point to ../venv/bin/python
```

### 2. Install Dependencies

With the virtualenv activated, install dependencies from `requirements.txt`:

```bash
pip install -r requirements.txt
```

Or using `pyproject.toml` with test extras:

```bash
pip install -e ".[test]"
```

### 3. Configure Environment Variables

Copy the example environment file and customize it:

```bash
cp .env.example .env
```

Edit `.env` to set your actual values (see [Configuration](#configuration) below).

---

## Configuration

All settings are loaded from environment variables via `pydantic-settings`. The `.env` file is automatically read when the application starts.

### Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `llama_cpp` | Provider to use: `llama_cpp` or `openai` |
| `LLAMA_CPP_BASE_URL` | `http://localhost:8080/v1` | llama.cpp server endpoint |
| `LLAMA_CPP_MODEL_NAME` | `./models/llama-model.gguf` | Model identifier (passed to the API) |
| `OPENAI_API_KEY` | *(empty)* | OpenAI API key (required when using OpenAI) |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint URL |
| `OPENAI_MODEL_NAME` | `gpt-4o` | Model name for OpenAI requests |
| `MOCK_LOG_COUNT` | `50` | Number of mock log lines to generate per batch |
| `MOCK_LOG_SEVERITIES` | `info,warn,error,critical` | Comma-separated severity levels |
| `MOCK_LOG_DIR` | `mocks/logs` | Directory where mock log files are written |
| `MOCK_LOG_INTERVAL` | `1.0` | Seconds between appended log batches during streaming |
| `MOCK_LOG_SERVICES` | comma-separated list | Services to include in generated logs (see below) |

### Programmatic Configuration

You can also override settings in code:

```python
from src.config.settings import Settings

settings = Settings(
    llm_provider="openai",
    openai_api_key="sk-...",
    mock_log_count=200,
    mock_log_interval=0.5,
)
```

---

## CLI Commands

### `generate-logs` — Write a batch of mock logs to a file

Generates realistic Kubernetes-style logs and writes them to a file:

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

### `stream-logs` — Stream mock logs in real-time

Two modes:

**Mode 1: Full mock file source** (generates + streams):

```bash
# Stream for 15 seconds (default is 10s)
python -m src stream-logs --duration 15

# Infinite mode (Ctrl+C to stop)
python -m src stream-logs --duration 0
```

This starts a `MockFileLogSource` that writes mock logs to a file in the background and tails them in real-time, simulating a live production system.

**Mode 2: Tail an existing file**:

```bash
# Tail a previously generated log file
python -m src stream-logs --source-file mocks/logs/generated.log
```

### `simulate` — Generate mock logs and send to LLM for analysis

The original command, now using the improved generator:

```bash
# Default simulation
python -m src simulate

# Custom count and provider override
python -m src simulate --count 100 --provider openai
```

### CLI Help

```bash
python -m src --help
python -m src generate-logs --help
python -m src stream-logs --help
python -m src simulate --help
```

---

## Mock Log Source System

### Log Source Abstraction

The `BaseLogSource` interface (`src/core/log_sources/base.py`) defines a universal contract for all log sources:

```python
class BaseLogSource(ABC):
    @property
    def name(self) -> str: ...

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def stream(self):  # async generator yielding LogLine
        ...
```

Every log source implements this interface, so downstream consumers (error detectors, LLM analyzers, dashboards) can treat all sources uniformly:

```python
source: BaseLogSource = MockFileLogSource(settings)
# Later, swap in a real source without changing consumer code:
# source = KubernetesLogSource(kube_config)

await source.start()
async for log_line in source.stream():
    # Process each log line uniformly
    await analyzer.analyze(log_line.text)
await source.stop()
```

Future sources to implement:
- `KubernetesLogSource` — tails `kubectl logs` or kubelet API
- `LokiLogSource` — queries Grafana Loki via HTTP API
- `PrometheusAlertSource` — ingests Prometheus alertmanager webhooks

### Mock File Log Source

The `MockFileLogSource` (`src/core/log_sources/mock_file_source.py`) is the default log source. It:

1. **Writes** an initial batch of mock logs to a file on `start()`.
2. **Appends** new batches periodically via a background `asyncio.Task`.
3. **Streams** by tailing the file — reads new lines as they appear using file position tracking.

Lifecycle:

```python
source = MockFileLogSource(settings)
await source.start()       # Write initial batch + start background writer
async for line in source.stream():  # Tail file, yield LogLine objects
    print(line.text)
await source.stop()        # Cancel background task, clean up
```

Key features:
- Handles file truncation (restarts from beginning if file shrinks)
- Thread-safe via asyncio event loop (no threading needed)
- Configurable write interval via `MOCK_LOG_INTERVAL`

### Mock Log Generator

The generator (`mocks/generators/log_generator.py`) produces realistic Kubernetes/Grafana-style logs with:

**Services**: `auth-service`, `payment-service`, `gateway`, `inventory-service`, `user-api`, `order-processor`, `notification-worker`, `cache-redis`

**Severities & Messages**:
| Severity | Examples |
|---|---|
| INFO | `GET /api/v1/users 200 OK (12ms)`, `Health check passed — all dependencies healthy`, `Cache hit ratio: 94.2%` |
| WARN | `Response time exceeded 500ms threshold`, `Connection pool utilization at 82%`, `Circuit breaker half-open for inventory-service` |
| ERROR | `Connection refused to database host db-primary:5432 — ECONNREFUSED`, `HTTP 503 from upstream service payment-service`, `Redis connection lost: READERR OOM command not allowed` |
| CRITICAL | `Out of memory: killed process 12345 (java) total-vm:8234567kB`, `Pod crash-looping: OOMKilled in payment-service-7d4f`, `Network partition detected between zones us-east-1a and us-east-1b` |

**Realistic details**:
- Kubernetes pod names (e.g., `auth-service-5c8d7f9a2b`)
- Full Python tracebacks on ERROR/CRITICAL entries
- HTTP error codes, DB connection failures, retry attempts
- OOM kills, disk space warnings, circuit breaker states
- Realistic timestamps with jitter

**API**:

```python
from mocks.generators.log_generator import (
    generate_log_entries,   # Returns list[LogEntry]
    generate_mock_logs_text,  # Returns multi-line string
    stream_log_entries,     # Async generator for real-time simulation
)

# Batch generation
entries = generate_log_entries(count=100, services=["auth-service", "gateway"])
text = generate_mock_logs_text(count=50)

# Real-time streaming (async)
async for entry in stream_log_entries(count=50, interval=0.5):
    print(entry.format())
```

---

## Running Tests

With the virtualenv activated:

```bash
# Run all tests
pytest

# Run only unit tests
pytest tests/unit/

# Run only integration tests
pytest tests/integration/

# Run with verbose output
pytest -v

# Run with coverage
pip install coverage
coverage run -m pytest
coverage report
```

### Test Architecture

| Layer | Location | What it tests | Network calls? |
|---|---|---|---|
| **Unit** | `tests/unit/` | Config loading, provider factory, log generator output, settings validation | No |
| **Integration** | `tests/integration/` | Log source lifecycle (start/stop/stream), mock HTTP server for LLM pipeline | Mocked only |

### Test Coverage by Module

- **Config**: Default values, env overrides, OpenAI defaults, provider factory creation, unsupported provider error
- **Log Generator**: Entry count, severity cycling, service cycling, timestamp ordering, traceback inclusion, no LLM imports
- **Log Source**: Lifecycle (start/stop), streaming yields lines, sees appended lines, multiple services, name property, double-start safety, severity distribution
- **LLM Pipeline**: End-to-end with mocked HTTP server returning structured JSON

---

## Local LLM Integration (llama.cpp)

### How It Works

The llama.cpp provider communicates with a local llama.cpp server via an **OpenAI-compatible API endpoint**. The llama.cpp server exposes a `/v1/chat/completions` endpoint that accepts the same request format as OpenAI's API.

### Starting the llama.cpp Server

```bash
# Example: start llama.cpp server with a GGUF model
llama-server \
  --model ./models/your-model.gguf \
  --host 127.0.0.1 \
  --port 8080 \
  --ctx-size 4096
```

The server will be available at `http://localhost:8080/v1`.

### Configuration for llama.cpp

In your `.env`:

```env
LLM_PROVIDER=llama_cpp
LLAMA_CPP_BASE_URL=http://localhost:8080/v1
LLAMA_CPP_MODEL_NAME=./models/your-model.gguf
```

### Request Flow

1. The CLI generates mock logs (or you provide real logs from a `BaseLogSource`).
2. Logs are sent as a `user` message in a chat completion request.
3. A system prompt instructs the model to return structured JSON with:
   - `root_cause`: string
   - `severity`: one of `critical`, `high`, `medium`, `low`
   - `remediation_suggestions`: array of strings
   - `preventive_actions`: array of strings
4. The provider parses the JSON response and returns an `AnalysisResult` dataclass.

### Recommended Models

- **Mistral 7B Instruct** — Good balance of quality and speed on CPU
- **Llama 3 8B Instruct** — Strong reasoning capabilities
- **Phi-3 Mini** — Fast inference on consumer hardware

---

## OpenAI Integration

### How It Works

The OpenAI provider sends requests to the OpenAI API (or any OpenAI-compatible endpoint) using the same chat completion format. This allows you to switch from local llama.cpp to cloud-based models seamlessly.

### Configuration for OpenAI

In your `.env`:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-actual-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL_NAME=gpt-4o
```

### Switching Providers

Change one line in `.env`:

```env
# From:
LLM_PROVIDER=llama_cpp

# To:
LLM_PROVIDER=openai
```

Then run the app as usual — the factory will automatically create an `OpenAiProvider` instead of a `LlamaCppProvider`.

### Using Other OpenAI-Compatible Endpoints

You can point the OpenAI provider at any compatible service (e.g., vLLM, Ollama with OpenAI compat, Together AI):

```env
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://api.together.xyz/v1
OPENAI_MODEL_NAME=mistralai/Mixtral-8x7B-Instruct-v0.1
OPENAI_API_KEY=your-together-api-key
```

---

## Future Roadmap

### Phase 2 — Real Log Sources
- [ ] `KubernetesLogSource` — log ingestion via `kubectl logs` or kubelet API
- [ ] `LokiLogSource` — Grafana Loki log queries via Loki HTTP API
- [ ] `PrometheusAlertSource` — Prometheus alertmanager webhook ingestion

### Phase 3 — Real-Time Monitoring
- [ ] Continuous log tailing with `asyncio` streams (already scaffolded)
- [ ] Error pattern detection (regex-based pre-filtering before LLM)
- [ ] Alert thresholds and notification hooks (Slack, PagerDuty)

### Phase 4 — Web Interface
- [ ] FastAPI backend for REST API access
- [ ] Simple web dashboard for viewing analysis results
- [ ] Historical analysis tracking

### Phase 5 — Advanced AI Features
- [ ] Multi-turn conversation for deeper investigation
- [ ] Knowledge base integration (runbook lookup)
- [ ] Automatic remediation script generation

---

## Quick Reference

```bash
# Activate virtualenv
source ../venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Generate a batch of mock logs
python -m src generate-logs --count 100

# Stream mock logs in real-time
python -m src stream-logs --duration 15

# Simulate and send to LLM for analysis
python -m src simulate

# Run tests
pytest -v

# Switch to OpenAI
echo 'LLM_PROVIDER=openai' >> .env
python -m src simulate
```
