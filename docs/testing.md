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
| **Unit** | `tests/unit/` | Config loading, provider factory, log generator output, settings validation, watcher components (detector, context builder, dedup tracker), predictor (heuristic rules, rolling windows, thresholds), folder source (lifecycle, single-consumer, logging, path handling) | No |
| **Integration** | `tests/integration/` | Log source lifecycle (start/stop/stream), mock HTTP server for LLM pipeline, multi-service watcher scenarios, full watcher flow, end-to-end predict flow (watcher → predictor) | Mocked only |

## Coverage by Module

- **Config**: Default values, env overrides, OpenAI defaults, provider factory creation, unsupported provider error
- **Log Generator**: Entry count, severity cycling, service cycling, timestamp ordering, traceback inclusion, no LLM imports
- **Log Source**: Lifecycle (start/stop), streaming yields lines, sees appended lines, multiple services, name property, double-start safety, severity distribution
- **LLM Pipeline**: End-to-end with mocked HTTP server returning structured JSON
- **Watcher (Unit)**: Detector rule matching (26 rules), context builder window extraction, dedup tracker fingerprinting and TTL expiry, watcher orchestrator flow
- **Watcher (Integration)**: Multi-service incident detection, full watcher pipeline with mock log source
- **Predictor (Unit)**: Heuristic rule evaluation, rolling window logic, threshold triggering, service isolation, reset behavior
- **Predictor (Integration)**: End-to-end predict flow (watcher → predictor → output), multi-service prediction scenarios
