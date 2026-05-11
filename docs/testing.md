# Testing

## Running Tests

```bash
pytest                          # All tests
pytest tests/unit/              # Unit tests only
pytest tests/integration/       # Integration tests only
pytest -v                       # Verbose output
coverage run -m pytest          # With coverage
coverage report
```

## Test Architecture

| Layer | Location | What it tests | Network calls? |
|---|---|---|---|
| **Unit** | `tests/unit/` | Config loading, provider factory, log generator output, settings validation | No |
| **Integration** | `tests/integration/` | Log source lifecycle (start/stop/stream), mock HTTP server for LLM pipeline | Mocked only |

## Coverage by Module

- **Config**: Default values, env overrides, OpenAI defaults, provider factory creation, unsupported provider error
- **Log Generator**: Entry count, severity cycling, service cycling, timestamp ordering, traceback inclusion, no LLM imports
- **Log Source**: Lifecycle (start/stop), streaming yields lines, sees appended lines, multiple services, name property, double-start safety, severity distribution
- **LLM Pipeline**: End-to-end with mocked HTTP server returning structured JSON
