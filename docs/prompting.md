# Prompting

## System Prompt

The LLM receives a system prompt instructing it to return structured JSON with:

- `root_cause` (string): Analysis of the underlying issue
- `severity` (enum): One of `critical`, `high`, `medium`, `low`
- `remediation_suggestions` (array of strings): Actionable fix steps
- `preventive_actions` (array of strings): Measures to prevent recurrence

## Request Format

Logs are sent as a `user` message in a chat completion request. The provider parses the JSON response and returns an `AnalysisResult` dataclass.

## Provider Parameters

Both providers use the following parameters for API calls:

| Parameter | Value | Description |
|---|---|---|
| `temperature` | 0.0 | Deterministic output (no randomness) |
| `max_tokens` | 1024 | Maximum tokens in the response |

## Provider-Agnostic

The same prompt format works across both `llama_cpp` and `openai` providers — only the API endpoint changes.
