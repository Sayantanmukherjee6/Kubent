"""Factory for creating LLM providers based on configuration."""

from src.config.settings import LlmProviderType, Settings
from src.providers.base import BaseLlmProvider


def create_llm_provider(settings: Settings) -> BaseLlmProvider:
    """Return the configured LLM provider instance.

    Args:
        settings: Application settings containing provider selection.

    Returns:
        An initialized BaseLlmProvider subclass.

    Raises:
        ValueError: If the configured provider type is not supported.
    """
    match settings.llm_provider:
        case LlmProviderType.LLAMA_CPP:
            from src.providers.llama_cpp import LlamaCppProvider
            return LlamaCppProvider(settings)

        case LlmProviderType.OPENAI:
            from src.providers.openai import OpenAiProvider
            return OpenAiProvider(settings)

        case unknown:  # pragma: no cover
            raise ValueError(f"Unsupported LLM provider: {unknown}")
