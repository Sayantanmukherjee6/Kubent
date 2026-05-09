"""Integration test for the LLM analysis pipeline using a mock server."""

import json
from collections.abc import AsyncGenerator

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


@pytest.fixture()
async def mock_server() -> AsyncGenerator[None, None]:
    """Start a minimal mock HTTP server that mimics the llama.cpp API response."""

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        user_content = ""
        for msg in body["messages"]:
            if msg["role"] == "user":
                user_content = msg["content"]

        mock_response = {
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
        return httpx.Response(200, json=mock_response)

    async with httpx.AsyncClient() as client:
        # Use a real socket by starting a server in the background
        import asyncio
        from unittest.mock import AsyncMock, patch

        original_post = client.post

        async def mock_post(url: str, **kwargs):  # type: ignore[no-untyped-def]
            request = httpx.Request("POST", url, **kwargs)
            return await handler(request)

        with patch.object(client, "post", mock_post):
            yield


@pytest.mark.asyncio
async def test_analysis_pipeline(settings: Settings, mock_server: None) -> None:
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
