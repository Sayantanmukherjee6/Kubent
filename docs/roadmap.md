# Roadmap

## Phase 2 — Real Log Sources
- [ ] `KubernetesLogSource` — log ingestion via `kubectl logs` or kubelet API
- [ ] `LokiLogSource` — Grafana Loki log queries via Loki HTTP API
- [ ] `PrometheusAlertSource` — Prometheus alertmanager webhook ingestion

## Phase 3 — Real-Time Monitoring
- [ ] Continuous log tailing with `asyncio` streams (already scaffolded)
- [x] Error pattern detection (regex-based pre-filtering before LLM) — **implemented** (see [Watcher Subsystem](watcher.md))
- [x] Heuristic incident prediction (rolling-window, bounded-memory) — **implemented** (see [predictor.md](predictor.md))
- [ ] Alert thresholds and notification hooks (Slack, PagerDuty)

## Phase 4 — Watcher → LLM Orchestration
- [ ] Connect `IncidentEvent` output to `BaseLlmProvider.analyze()`
- [ ] Route detected incidents to LLM for automated root cause analysis
- [ ] Store `AnalysisResult` alongside `IncidentEvent` for historical tracking
- [ ] Configurable routing rules (e.g. only CRITICAL/HIGH severity → LLM)

## Phase 5 — Web Interface
- [ ] FastAPI backend for REST API access
- [ ] Simple web dashboard for viewing analysis results
- [ ] Historical analysis tracking

## Phase 6 — Advanced AI Features
- [ ] Multi-turn conversation for deeper investigation
- [ ] Knowledge base integration (runbook lookup)
- [ ] Automatic remediation script generation
