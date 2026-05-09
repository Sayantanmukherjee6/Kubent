# Kubernetes Agent — AI-Powered Observability Assistant

An AI-powered observability assistant that monitors simulated Kubernetes/Grafana logs, detects errors, and sends them to an LLM for root cause analysis, severity classification, remediation suggestions, and preventive actions.

## Table of Contents

- [Project Overview](#project-overview)
- [Architecture Overview](#architecture-overview)
- [Folder Structure](#folder-structure)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Configuration](#configuration)
- [Running the App](#running-the-app)
- [Running Tests](#running-tests)
- [Local LLM Integration (llama.cpp)](#local-llm-integration-llamacpp)
- [OpenAI Integration](#openai-integration)
- [Future Roadmap](#future-roadmap)

---

## Project Overview

This project is a **hackathon MVP** that demonstrates an AI-powered observability pipeline:

1. **Log ingestion** — Currently uses mock/simulated logs (real Kubernetes, Grafana, and Prometheus integrations are planned).
2. **Error detection** — Identifies error and critical severity log entries.
3. **LLM analysis** — Sends log context to an LLM (local llama.cpp or OpenAI) which returns:
   - Root cause analysis
   - Severity classification (critical / high / medium / low)
   - Remediation suggestions
   - Preventive actions

### Design Principles

- **Local-first**: Runs entirely on your machine with a local llama.cpp server.
- **Minimal dependencies**: No LangChain, no CrewAI, no AutoGen — just clean Python with `asyncio`, `httpx`, and `pydantic`.
- **Provider abstraction**: Swapping the LLM backend is as simple as changing one environment variable.
- **Mock-first development**: Full mock log generation for testing without any external infrastructure.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                    CLI (click)                       │
│           python -m src simulate                     │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              Mock Log Generator                      │
│   mocks/generators/log_generator.py                  │
│   Generates realistic K8s/Grafana-style logs         │
└──────────────────────┬──────────────────────────────┘
                       │  log_context (str)
                       ▼
┌─────────────────────────────────────────────────────┐
│              Provider Factory                        │
│        src/providers/factory.py                      │
│   Creates the correct LLM provider based on config   │
└──────────────────────┬──────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
┌──────────────────┐    ┌──────────────────┐
│  LlamaCppProvider│    │  OpenAiProvider  │
│ src/providers/   │    │ src/providers/   │
│ llama_cpp.py     │    │ openai.py        │
│                  │    │                  │
│ Calls local      │    │ Calls OpenAI     │
│ llama.cpp server │    │ API (or any      │
│ via OpenAI-compat│    │ compatible       │
│ endpoint         │    │ endpoint)        │
└──────────────────┘    └──────────────────┘
          │                         │
          ▼                         ▼
┌─────────────────────────────────────────────────────┐
│              AnalysisResult (dataclass)              │
│  - root_cause: str                                   │
│  - severity: str                                     │
│  - remediation_suggestions: list[str]                │
│  - preventive_actions: list[str]                     │
└─────────────────────────────────────────────────────┘
```

### Key Abstractions

- **`BaseLlmProvider`** (`src/providers/base.py`): Abstract base class defining the `analyze(log_context: str) -> AnalysisResult` interface.
- **`AnalysisResult`**: Frozen dataclass holding the structured LLM output.
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
│   ├── providers/                # LLM provider implementations
│   │   ├── __init__.py
│   │   ├── base.py               # Abstract base class + AnalysisResult
│   │   ├── llama_cpp.py          # Local llama.cpp provider
│   │   ├── openai.py             # OpenAI API provider
│   │   └── factory.py            # Provider creation factory
│   │
│   ├── core/                     # Core business logic (future)
│   │   └── __init__.py
│   │
│   └── utils/                    # Utility functions (future)
│       └── __init__.py
│
├── tests/                        # Test suite (separated from source)
│   ├── __init__.py
│   ├── unit/                     # Unit tests (no network calls)
│   │   ├── __init__.py
│   │   └── test_config.py        # Config loading + provider factory tests
│   │
│   └── integration/              # Integration tests (mock HTTP)
│       ├── __init__.py
│       └── test_llm_pipeline.py  # End-to-end pipeline with mock server
│
├── mocks/                        # Mock/simulation resources
│   ├── __init__.py
│   ├── logs/                     # Sample log files
│   │   ├── __init__.py
│   │   └── sample_k8s_errors.log # Pre-generated sample logs
│   │
│   └── generators/               # Log generation utilities
│       ├── __init__.py
│       └── log_generator.py      # Reusable mock log generator
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
| `MOCK_LOG_COUNT` | `50` | Number of mock log lines to generate |
| `MOCK_LOG_SEVERITIES` | `info,warning,error,critical` | Comma-separated severity levels |

### Programmatic Configuration

You can also override settings in code:

```python
from src.config.settings import Settings

settings = Settings(llm_provider="openai", openai_api_key="sk-...")
```

---

## Running the App

### Simulate and Analyze Mock Logs

With the virtualenv activated, run:

```bash
python -m src simulate
```

This will:
1. Generate mock log lines (default: 50)
2. Display the first 500 characters of generated logs
3. Send all logs to the configured LLM for analysis
4. Print a formatted analysis result

### Custom Options

```bash
# Generate a specific number of log lines
python -m src simulate --count 100

# Override the LLM provider at runtime
python -m src simulate --provider openai

# Combine options
python -m src simulate --count 200 --provider llama_cpp
```

### CLI Help

```bash
python -m src --help
python -m src simulate --help
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

- **Unit tests** (`tests/unit/`): Test configuration loading, provider factory creation, and settings validation. No network calls.
- **Integration tests** (`tests/integration/`): Test the full analysis pipeline using a mocked HTTP server. Validates that logs flow through the provider and produce structured `AnalysisResult` objects.

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

1. The CLI generates mock logs (or you provide real logs in a future version).
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
- [ ] Kubernetes log ingestion (via `kubectl logs` or kubelet API)
- [ ] Grafana Loki log queries (via Loki API)
- [ ] Prometheus alert ingestion

### Phase 3 — Real-Time Monitoring
- [ ] Continuous log tailing with `asyncio` streams
- [ ] Error pattern detection (regex-based pre-filtering)
- [ ] Alert thresholds and notification hooks

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

# Run simulation
python -m src simulate

# Run tests
pytest -v

# Switch to OpenAI
echo 'LLM_PROVIDER=openai' >> .env
python -m src simulate
```
