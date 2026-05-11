# Roadmap

## Phase 1 — Watcher Pipeline ✅

Implemented:

* async log streaming
* regex-based incident detection
* rolling context extraction
* deduplication
* structured `IncidentEvent` emission

Key components:

* `LogWatcher`
* `LogDetector`
* `ContextBuilder`
* `_DedupTracker`

---

## Phase 2 — Predictive Heuristics ✅

Implemented:

* rolling incident windows
* heuristic anomaly detection
* repeated incident escalation
* bounded-memory predictor subsystem
* structured `PredictorEvent` emission

Current heuristic coverage:

* repeated HTTP 5xx
* repeated timeouts
* repeated OOMKilled
* repeated connection refused

Key components:

* `HeuristicPredictor`
* `PredictorEvent`
* `RiskLevel`

---

## Phase 3 — Real Log Sources

Planned:

* [ ] Folder-based log ingestion
* [ ] Kubernetes log ingestion (`kubectl logs`) (Not for POC, but future extension)
* [ ] Loki/Grafana log ingestion (Not for POC, but future extension)
* [ ] Configurable log source selection (Not for POC, but future extension)

Goal:
Support realistic production-style log replay and live tailing without changing the watcher/predictor pipeline.

---

## Phase 4 — Predictor → LLM Orchestration

Planned:

* [ ] Connect `PredictorEvent` → `BaseLlmProvider`
* [ ] AI-generated incident summaries
* [ ] Mitigation suggestions
* [ ] Probable impact explanations
* [ ] Configurable severity-based routing

Goal:
Use deterministic heuristics for detection and LLMs only for explanation/summarization.

---

## Phase 5 — Email Alerts

Planned:

* [ ] SMTP email notifications
* [ ] HIGH/CRITICAL severity alerting
* [ ] AI-generated alert summaries
* [ ] Failure-safe notification handling

Goal:
Automatically notify operators when predictive anomalies are detected.

---

## Future Extensions (Optional)

Possible future improvements after the hackathon:

* Slack/Discord notifications
* Historical event persistence
* Dashboard visualization
* Additional heuristic rules
* More log source integrations

These are intentionally out of scope for the current MVP.
