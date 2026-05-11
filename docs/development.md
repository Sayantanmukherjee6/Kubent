# Development

## Prerequisites

- **Python 3.11+** (required for `match` statements and type features)
- **External virtualenv** at `../venv/` relative to this project root

## Setup

### 1. Activate the External Virtualenv

```bash
cd /Users/anonymous/Documents/projects/hackathon/kubernetes-agent
source ../venv/bin/activate
python --version   # Should show Python 3.11+ from the virtualenv
which python        # Should point to ../venv/bin/python
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
# Or with test extras:
pip install -e ".[test]"
```

### 3. Configure Environment Variables

```bash
cp .env.example .env
# Edit .env with your actual values
```

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `llama_cpp` | Provider: `llama_cpp` or `openai` |
| `LLAMA_CPP_BASE_URL` | `http://localhost:8080/v1` | llama.cpp server endpoint |
| `LLAMA_CPP_MODEL_NAME` | `./models/llama-model.gguf` | Model identifier |
| `OPENAI_API_KEY` | *(empty)* | OpenAI API key (required for openai provider) |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint URL |
| `OPENAI_MODEL_NAME` | `gpt-4o` | Model name for OpenAI requests |
| `MOCK_LOG_COUNT` | `50` | Mock log lines per batch |
| `MOCK_LOG_SEVERITIES` | `info,warn,error,critical` | Comma-separated severity levels |
| `MOCK_LOG_DIR` | `mocks/logs` | Directory for mock log files |
| `MOCK_LOG_INTERVAL` | `1.0` | Seconds between appended log batches |
| `MOCK_LOG_SERVICES` | comma-separated list | Services to include in generated logs |

## Programmatic Configuration

```python
from src.config.settings import Settings

settings = Settings(
    llm_provider="openai",
    openai_api_key="sk-...",
    mock_log_count=200,
    mock_log_interval=0.5,
)
```

## Folder Structure

```
project/
├── src/                          # Main source code
│   ├── __main__.py               # CLI entrypoint (click-based)
│   ├── config/                   # Configuration module
│   │   └── settings.py           # Pydantic Settings from .env
│   ├── core/log_sources/         # Log source abstraction layer
│   │   ├── base.py               # BaseLogSource ABC + LogLine dataclass
│   │   └── mock_file_source.py   # Mock file-based log source
│   ├── providers/                # LLM provider implementations
│   │   ├── base.py               # Abstract base class + AnalysisResult
│   │   ├── llama_cpp.py          # Local llama.cpp provider
│   │   ├── openai.py             # OpenAI API provider
│   │   └── factory.py            # Provider creation factory
│   └── utils/                    # Utility functions (future)
├── tests/                        # Test suite
│   ├── unit/                     # Unit tests (no network calls)
│   │   ├── test_config.py
│   │   └── test_log_sources.py
│   └── integration/              # Integration tests (mock HTTP / file I/O)
│       ├── test_llm_pipeline.py  # End-to-end pipeline with mock server
│       └── test_log_sources.py   # Log source lifecycle + streaming tests
├── mocks/                        # Mock/simulation resources
│   ├── logs/                     # Sample log files
│   │   └── sample_k8s_errors.log
│   └── generators/               # Log generation utilities
│       └── log_generator.py      # Reusable mock log generator + async streamer
├── .env.example
├── pyproject.toml                # Project metadata + pytest config
└── requirements.txt              # pip dependencies
```
