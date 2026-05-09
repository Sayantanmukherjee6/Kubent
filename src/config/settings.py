"""Application settings loaded from environment variables."""

from enum import StrEnum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LlmProviderType(StrEnum):
    LLAMA_CPP = "llama_cpp"
    OPENAI = "openai"


class Settings(BaseSettings):
    """All application settings, loaded from .env or environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM Provider Selection ---
    llm_provider: LlmProviderType = LlmProviderType.LLAMA_CPP

    # --- Local llama.cpp Server ---
    llama_cpp_base_url: str = "http://localhost:8080/v1"
    llama_cpp_model_name: str = "./models/llama-model.gguf"

    # --- OpenAI API ---
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model_name: str = "gpt-4o"

    # --- Mock Log Simulation ---
    mock_log_count: int = 50
    mock_log_severities: list[str] = Field(
        default_factory=lambda: ["info", "warn", "error", "critical"],
    )

    # --- Mock Log Source ---
    mock_log_dir: str = "mocks/logs"
    mock_log_interval: float = 1.0
    mock_log_services: list[str] = Field(
        default_factory=lambda: [
            "auth-service",
            "payment-service",
            "gateway",
            "inventory-service",
            "user-api",
            "order-processor",
        ],
    )
