"""Unit tests for configuration and provider factory."""

import os

from src.config.settings import LlmProviderType, Settings
from src.providers.factory import create_llm_provider


class TestSettings:
    """Tests for the Settings configuration class."""

    def test_default_settings(self) -> None:
        """Default settings should use llama_cpp provider with sensible defaults."""
        settings = Settings()
        assert settings.llm_provider == LlmProviderType.LLAMA_CPP
        assert settings.llama_cpp_base_url == "http://localhost:8080/v1"
        assert settings.mock_log_count == 50
        assert settings.mock_log_severities == ["info", "warning", "error", "critical"]

    def test_env_override(self, monkeypatch: object) -> None:
        """Environment variables should override defaults."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_MODEL_NAME", "gpt-4-turbo")
        monkeypatch.setenv("MOCK_LOG_COUNT", "100")

        settings = Settings()
        assert settings.llm_provider == LlmProviderType.OPENAI
        assert settings.openai_model_name == "gpt-4-turbo"
        assert settings.mock_log_count == 100

    def test_openai_defaults(self) -> None:
        """OpenAI settings should have sensible defaults."""
        settings = Settings()
        assert settings.openai_base_url == "https://api.openai.com/v1"
        assert settings.openai_model_name == "gpt-4o"


class TestProviderFactory:
    """Tests for the LLM provider factory."""

    def test_create_llama_cpp_provider(self) -> None:
        """Factory should return LlamaCppProvider when configured."""
        settings = Settings(llm_provider=LlmProviderType.LLAMA_CPP)
        provider = create_llm_provider(settings)
        assert type(provider).__name__ == "LlamaCppProvider"

    def test_create_openai_provider(self) -> None:
        """Factory should return OpenAiProvider when configured."""
        settings = Settings(
            llm_provider=LlmProviderType.OPENAI,
            openai_api_key="test-key",
        )
        provider = create_llm_provider(settings)
        assert type(provider).__name__ == "OpenAiProvider"

    def test_create_unsupported_provider(self) -> None:
        """Factory should raise ValueError for unsupported providers."""
        settings = Settings(llm_provider=LlmProviderType.OPENAI)  # type: ignore[arg-type]
        # Force an invalid enum value by bypassing the type system
        original_value = settings.llm_provider
        try:
            os.environ["LLM_PROVIDER"] = "unknown_provider"
            settings = Settings()
            try:
                create_llm_provider(settings)
                assert False, "Expected ValueError"
            except ValueError as exc:
                assert "Unsupported LLM provider" in str(exc)
        finally:
            os.environ.pop("LLM_PROVIDER", None)
