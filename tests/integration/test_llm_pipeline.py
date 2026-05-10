"""Integration test for the LLM analysis pipeline using a mock server."""

import json

import httpx
import pytest

from src.config.settings import Settings
from src.providers.factory import create_llm_provider


@pytest.fixture()
def settings() -> Settings:
    """Return settings pointing at the mock server."""
    return Settings(
        llm_provider="llama_cpp",
        llama_cpp_base_url="http://localhost:19876/v1",
        llama_cpp_model_name="test-model",
    )


def _make_mock_response() -> dict:
    """Build the mock API response dict."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "root_cause": "Database connection pool exhausted due to leaked connections.",
                        "severity": "high",
                        "remediation_suggestions": [
                            "Restart the affected service to release leaked connections.",
                            "Increase connection pool size temporarily.",
                        ],
                        "preventive_actions": [
                            "Implement connection leak detection.",
                            "Add circuit breaker pattern for database calls.",
                        ],
                    }),
                },
            },
        ],
    }


@pytest.fixture()
def mock_async_client_post(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch httpx.AsyncClient.post at the class level so all instances are mocked."""
    mock_response = httpx.Response(200, json=_make_mock_response())
    # Attach a dummy request so raise_for_status() works
    mock_response.request = httpx.Request("POST", "http://localhost:19876/v1/chat/completions")

    async def mock_post(*args, **kwargs):  # type: ignore[no-untyped-def]
        return mock_response

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)


@pytest.mark.asyncio
async def test_analysis_pipeline(settings: Settings, mock_async_client_post: None) -> None:
    """End-to-end test: generate logs, send to provider, verify structured result."""
    llm = create_llm_provider(settings)

    log_context = (
        "2025-01-15T10:00:01Z [ERROR   ] user-db: Connection refused to db-primary:5432\n"
        "2025-01-15T10:00:02Z [WARNING ] api-gateway: Response time exceeded 500ms threshold\n"
        "2025-01-15T10:00:03Z [CRITICAL] auth-service: Circuit breaker OPEN after 10 failures"
    )

    result = await llm.analyze(log_context)

    assert result.root_cause == "Database connection pool exhausted due to leaked connections."
    assert result.severity == "high"
    assert len(result.remediation_suggestions) == 2
    assert len(result.preventive_actions) == 2
    assert "Restart the affected service" in result.remediation_suggestions[0]
