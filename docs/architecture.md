# Architecture

## Overview

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

## Key Abstractions

- **`BaseLogSource`** (`src/core/log_sources/base.py`): ABC defining `start()`, `stop()`, and async `stream()` interface. Every log source implements this.
- **`MockFileLogSource`**: Reads mock files, appends new lines in a background task, tails via async generator.
- **`BaseLlmProvider`** (`src/providers/base.py`): ABC defining `analyze(log_context: str) -> AnalysisResult`.
- **`AnalysisResult`**: Frozen dataclass holding structured LLM output (root_cause, severity, remediation, preventive_actions).
- **`create_llm_provider(settings)`**: Factory that instantiates the correct provider based on `LLM_PROVIDER` in `.env`.

## Design Principles

- **Local-first**: Runs entirely on your machine with a local llama.cpp server.
- **Minimal dependencies**: No LangChain, CrewAI, or AutoGen — just `asyncio`, `httpx`, and `pydantic`.
- **Log source abstraction**: Swapping log sources is done by implementing one interface.
- **Provider abstraction**: Swapping the LLM backend requires changing one environment variable.
- **Mock-first development**: Full mock log generation with streaming simulation for testing without external infrastructure.
