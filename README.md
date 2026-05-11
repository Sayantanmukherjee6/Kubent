# Kubernetes Agent — AI-Powered Observability Assistant

An AI-powered observability assistant that monitors simulated Kubernetes/Grafana logs, detects errors, and sends them to an LLM for root cause analysis, severity classification, remediation suggestions, and preventive actions.

## Quick Start

```bash
source ../venv/bin/activate
pip install -e ".[test]"
cp .env.example .env   # Edit with your settings
python -m src simulate
```

## Documentation

| Doc | Content |
|---|---|
| [Architecture](docs/architecture.md) | System overview, key abstractions, design principles |
| [Providers](docs/providers.md) | LLM backends (llama.cpp, OpenAI), factory, request flow |
| [Log Sources](docs/log_sources.md) | BaseLogSource abstraction, mock file source, log generator |
| [Watcher](docs/watcher.md) | Log monitoring and analysis trigger subsystem |
| [CLI](docs/cli.md) | All commands: generate-logs, stream-logs, watch-logs, simulate |
| [Development](docs/development.md) | Prerequisites, setup, config reference, folder structure |
| [Testing](docs/testing.md) | Test architecture, running tests, coverage by module |
| [Prompting](docs/prompting.md) | System prompt format and structured JSON output |
| [Roadmap](docs/roadmap.md) | Planned phases (real log sources, web interface, advanced AI) |

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    CLI (click)                       │
│  generate-logs | stream-logs | watch-logs | simulate │
└──────┬──────────────────────┬───────────────────────┘
       │                      │
       ▼                      ▼
┌──────────────────┐  ┌──────────────────────────────┐
│ Mock File Log    │  │  LLM Providers               │
│ Source           │  │  BaseLlmProvider (ABC)       │
│ src/core/log_sources/ │ ├── LlamaCppProvider       │
│                  │  │   └── OpenAiProvider         │
│ - reads mock     │  │                              │
│   files          │  │  Factory: create_llm_provider│
│ - streams        │  │      (settings) -> provider  │
│   appended lines │  │                              │
│ - start/stop     │  │  Can analyze raw logs via    │
│   lifecycle      │  │  `python -m src simulate`    │
└──────────────────┘  └──────────────┬───────────────┘
       │                             │ (standalone, not wired to watcher)
       ▼                             │
┌──────────────────┐                 │
│ Mock Log         │                 │
│ Generator        │                 │
│ mocks/generators/│                 │
│ log_generator.py │                 │
└──────────────────┘                 │
  Generates realistic                │
  K8s-style logs with:               │
  - tracebacks, HTTP errors,         │
    DB failures, OOM kills,          │
    pod restarts, retry fails        │
                                       │
┌──────────────────────────────────────┐
│         Watcher Subsystem            │
│                                      │
│  MockFileLogSource                   │
│    → LogDetector (regex rules)       │
│      → ContextBuilder (rolling buf)  │
│        → DedupTracker                │
│          → IncidentEvent             │
└──────────────────────────────────────┘
```

## Design Principles

- **Local-first**: Runs entirely on your machine with a local llama.cpp server.
- **Minimal dependencies**: No LangChain, CrewAI, or AutoGen — just `asyncio`, `httpx`, and `pydantic`.
- **Log source abstraction**: Swapping log sources requires implementing one interface.
- **Provider abstraction**: Swapping the LLM backend requires changing one environment variable.
- **Mock-first development**: Full mock log generation with streaming simulation for testing without external infrastructure.

## Quick Reference

```bash
source ../venv/bin/activate
pip install -e ".[test]"
python -m src generate-logs --count 100
python -m src stream-logs --duration 15
python -m src watch-logs --duration 15
python -m src simulate
pytest -v
echo 'LLM_PROVIDER=openai' >> .env   # Switch to OpenAI
```
