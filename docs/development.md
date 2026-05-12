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
pip install -e ".[test]"
```

### 3. Configure Environment Variables

```bash
cp .env.example .env
# Edit .env with your actual values
```

## Configuration Reference

Configuration is loaded from `config/config.yaml` with environment variable overrides.

### config/config.yaml

```yaml
log_source:
  type: mock                        # "mock" or "folder"
  folder_path: mocks/logs           # base directory for logs

mock:
  log_count: 50                     # initial batch size
  interval: 1.0                     # seconds between batches
  severities: [info, warn, error, critical]
  services: [auth-service, payment-service, gateway, ...]

watcher:
  min_severity: medium              # LOW | MEDIUM | HIGH | CRITICAL
  dedup_ttl: 300                    # seconds
  dedup_threshold: 1                # min occurrences before emitting
  context_before: 5                 # preceding context lines
  context_after: 3                  # following context lines

predictor:
  window_size: 200                  # max events per service

llm:
  provider: llama_cpp               # "llama_cpp" or "openai"
  llama_cpp:
    base_url: http://localhost:8080/v1
    model_name: ./models/llama-model.gguf
  openai:
    api_key: ""
    base_url: https://api.openai.com/v1
    model_name: gpt-4o
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `llama_cpp` | Provider: `llama_cpp` or `openai` |
| `LLAMA_CPP_BASE_URL` | `http://localhost:8080/v1` | llama.cpp server endpoint |
| `LLAMA_CPP_MODEL_NAME` | `./models/llama-model.gguf` | Model path |
| `OPENAI_API_KEY` | *(empty)* | OpenAI API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `OPENAI_MODEL_NAME` | `gpt-4o` | Model name for OpenAI |
| `MOCK_LOG_COUNT` | `50` | Mock log lines per batch |
| `MOCK_LOG_SEVERITIES` | `info,warn,error,critical` | Comma-separated severities |
| `MOCK_LOG_DIR` | `mocks/logs` | Directory for mock log files |
| `MOCK_LOG_INTERVAL` | `1.0` | Seconds between appended batches |
| `MOCK_LOG_SERVICES` | comma-separated list | Services in generated logs |
| `LOG_SOURCE_TYPE` | `mock` | Override log source type |
| `LOG_SOURCE_FOLDER_PATH` | `mocks/logs` | Override log source directory |

## Watcher Configuration

Watcher behavior is controlled via constructor parameters (not exposed as environment variables):

| Parameter | Default | Description |
|---|---|---|
| `min_severity` | MEDIUM | Minimum severity to emit (LOW, MEDIUM, HIGH, CRITICAL) |
| `dedup_ttl` | 300s | Deduplication fingerprint TTL in seconds |
| `dedup_threshold` | 1 | Min occurrences before emitting deduplicated event |
| `context_before` | 5 | Preceding context lines to capture |
| `context_after` | 3 | Following context lines to capture |

These can be set via CLI flags (e.g., `python -m src watch-logs --min-severity high --dedup-ttl 600`) or programmatically when constructing a `LogWatcher`.

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
├── config/
│   └── config.yaml               # Central runtime configuration
├── src/
│   ├── __init__.py
│   ├── __main__.py               # CLI entrypoint (click-based)
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py           # Settings from config.yaml + env vars
│   ├── core/
│   │   ├── __init__.py
│   │   ├── log_sources/
│   │   │   ├── __init__.py
│   │   │   ├── base.py           # BaseLogSource ABC + LogLine dataclass
│   │   │   ├── factory.py        # create_log_source(settings) factory
│   │   │   ├── mock_file_source.py  # Mock file-based log source
│   │   │   └── folder_source.py  # Tails *.log files in a directory
│   │   ├── watcher/
│   │   │   ├── __init__.py
│   │   │   ├── watcher.py        # LogWatcher orchestrator
│   │   │   ├── detector.py       # Regex-based rule engine (26 rules)
│   │   │   ├── context_builder.py  # Rolling buffer + context extraction
│   │   │   └── models.py         # WatcherSeverity, IncidentEvent, etc.
│   │   └── predictor/
│   │       ├── __init__.py
│   │       ├── predictor.py      # HeuristicPredictor (4 rules)
│   │       └── models.py         # RiskLevel, PredictorEvent
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py               # Abstract base class + AnalysisResult
│   │   ├── llama_cpp.py          # Local llama.cpp provider
│   │   ├── openai.py             # OpenAI API provider
│   │   ├── factory.py            # Provider creation factory
│   │   └── retry.py              # Retry logic for LLM calls
│   └── utils/
│       └── __init__.py
├── tests/
│   ├── __init__.py
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_config.py
│   │   ├── test_log_sources.py
│   │   ├── test_folder_source.py
│   │   ├── test_cli_factory.py
│   │   ├── predictor/
│   │   │   ├── __init__.py
│   │   │   └── test_predictor.py
│   │   ├── providers/
│   │   │   ├── __init__.py
│   │   │   ├── test_base.py
│   │   │   └── test_retry.py
│   │   └── watcher/
│   │       ├── __init__.py
│   │       ├── test_context_builder.py
│   │       ├── test_dedup.py
│   │       └── test_detector.py
│   └── integration/
│       ├── __init__.py
│       ├── test_llm_pipeline.py
│       ├── test_log_sources.py
│       ├── predictor/
│       │   ├── __init__.py
│       │   └── test_predict_flow.py
│       └── watcher/
│           ├── __init__.py
│           ├── test_multi_service.py
│           └── test_watcher_flow.py
├── mocks/
│   ├── logs/                     # Sample log files
│   └── generators/
│       └── log_generator.py      # Mock log generation
├── .env.example
└── pyproject.toml                # Project metadata + pytest config
```

## Logging

`FolderLogSource` logs filesystem errors (permission denied, missing files, stat failures)
at WARNING level via the standard `logging` module. To see these messages:

```python
import logging
logging.getLogger("src.core.log_sources.folder_source").setLevel(logging.WARNING)
logging.basicConfig(level=logging.WARNING)
```

No external observability frameworks are used — only the stdlib `logging` module.
