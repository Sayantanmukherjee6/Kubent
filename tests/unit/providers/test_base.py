"""Tests for BaseLlmProvider._parse_json edge cases."""

import pytest

from src.providers.base import AnalysisResult, BaseLlmProvider


class _ConcreteProvider(BaseLlmProvider):
    """Minimal concrete subclass so we can call _parse_json via self."""

    async def analyze(self, log_context: str) -> AnalysisResult:
        raise NotImplementedError


@pytest.fixture()
def provider() -> BaseLlmProvider:
    return _ConcreteProvider()


# ── Malformed JSON ────────────────────────────────────────────────


class TestMalformedJson:

    def test_completely_invalid_json(self, provider) -> None:
        result = provider._parse_json("not json at all {{{")
        assert result.root_cause == "Unable to parse analysis result."
        assert result.severity == "low"
        assert result.remediation_suggestions == ["Retry the analysis."]
        assert result.preventive_actions == []

    def test_truncated_json(self, provider) -> None:
        result = provider._parse_json('{"root_cause": "')
        assert result.root_cause == "Unable to parse analysis result."
        assert result.severity == "low"

    def test_json_with_syntax_error(self, provider) -> None:
        result = provider._parse_json('{"root_cause": "ok", severity: 5}')
        assert result.root_cause == "Unable to parse analysis result."
        assert result.severity == "low"


# ── Empty responses ──────────────────────────────────────────────


class TestEmptyResponses:

    def test_empty_string(self, provider) -> None:
        result = provider._parse_json("")
        assert result.root_cause == "Unable to parse analysis result."
        assert result.severity == "low"

    def test_whitespace_only(self, provider) -> None:
        result = provider._parse_json("   \n\t  ")
        assert result.root_cause == "Unable to parse analysis result."
        assert result.severity == "low"


# ── Partial JSON (missing keys) ──────────────────────────────────


class TestPartialJson:

    def test_missing_keys(self, provider) -> None:
        """Partially valid JSON with missing required keys raises KeyError."""
        result = provider._parse_json('{"root_cause": "something"}')
        assert result.root_cause == "Unable to parse analysis result."
        assert result.severity == "low"


# ── Valid inputs still work ──────────────────────────────────────


class TestValidInputs:

    def test_clean_json(self, provider) -> None:
        raw = '{"root_cause":"db down","severity":"critical","remediation_suggestions":["fix it"],"preventive_actions":[]}'
        result = provider._parse_json(raw)
        assert result.root_cause == "db down"
        assert result.severity == "critical"
        assert result.remediation_suggestions == ["fix it"]
        assert result.preventive_actions == []

    def test_markdown_fence_stripping(self, provider) -> None:
        raw = '```json\n{"root_cause":"ok","severity":"low","remediation_suggestions":[],"preventive_actions":[]}\n```'
        result = provider._parse_json(raw)
        assert result.root_cause == "ok"
        assert result.severity == "low"

    def test_markdown_fence_without_language(self, provider) -> None:
        raw = '```\n{"root_cause":"ok","severity":"medium","remediation_suggestions":[],"preventive_actions":[]}\n```'
        result = provider._parse_json(raw)
        assert result.root_cause == "ok"
        assert result.severity == "medium"
