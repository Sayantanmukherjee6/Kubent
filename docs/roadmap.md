# Roadmap

## Phase 2 — Real Log Sources
- [ ] `KubernetesLogSource` — log ingestion via `kubectl logs` or kubelet API
- [ ] `LokiLogSource` — Grafana Loki log queries via Loki HTTP API
- [ ] `PrometheusAlertSource` — Prometheus alertmanager webhook ingestion

## Phase 3 — Real-Time Monitoring
- [ ] Continuous log tailing with `asyncio` streams (already scaffolded)
- [ ] Error pattern detection (regex-based pre-filtering before LLM)
- [ ] Alert thresholds and notification hooks (Slack, PagerDuty)

## Phase 4 — Web Interface
- [ ] FastAPI backend for REST API access
- [ ] Simple web dashboard for viewing analysis results
- [ ] Historical analysis tracking

## Phase 5 — Advanced AI Features
- [ ] Multi-turn conversation for deeper investigation
- [ ] Knowledge base integration (runbook lookup)
- [ ] Automatic remediation script generation
