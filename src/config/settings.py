"""Application settings loaded from config/config.yaml with .env fallbacks.

The Settings class is the single source of truth for all runtime configuration.
It loads defaults from ``config/config.yaml`` and allows environment variables
(from ``.env`` or the shell) to override any value.

Usage
-----

.. code-block:: python

    from src.config.settings import Settings

    settings = Settings()
    print(settings.llm.provider)            # "llama_cpp"
    print(settings.mock.log_count)          # 50
    print(settings.watcher.dedup_ttl)       # 300
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class LlmProviderType(StrEnum):
    LLAMA_CPP = "llama_cpp"
    OPENAI = "openai"


# ---------------------------------------------------------------------------
# Nested dataclasses — typed accessors for each config section
# ---------------------------------------------------------------------------

@dataclass
class LogSourceConfig:
    type: str = "mock"
    folder_path: str = "mocks/logs"


@dataclass
class MockConfig:
    log_count: int = 50
    interval: float = 1.0
    severities: list[str] = field(
        default_factory=lambda: ["info", "warn", "error", "critical"],
    )
    services: list[str] = field(
        default_factory=lambda: [
            "auth-service",
            "payment-service",
            "gateway",
            "inventory-service",
            "user-api",
            "order-processor",
        ],
    )


@dataclass
class WatcherConfig:
    min_severity: str = "medium"
    dedup_ttl: float = 300.0
    dedup_threshold: int = 1
    context_before: int = 5
    context_after: int = 3


@dataclass
class PredictorConfig:
    window_size: int = 200


@dataclass
class MetricSourceConfig:
    type: str = "mock"
    folder_path: str = "./demo_metrics"


@dataclass
class MetricsThresholds:
    cpu_percent: float = 85.0
    memory_percent: float = 90.0


@dataclass
class MetricsConfig:
    source: MetricSourceConfig = field(default_factory=MetricSourceConfig)
    thresholds: MetricsThresholds = field(default_factory=MetricsThresholds)
    stream_interval_seconds: float = 5.0
    predictor_window_size: int = 100
    scenarios: list[str] = field(default_factory=list)


@dataclass
class LlamaCppConfig:
    base_url: str = "http://localhost:8080/v1"
    model_name: str = "./models/llama-model.gguf"


@dataclass
class OpenAiConfig:
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model_name: str = "gpt-4o"


@dataclass
class LlmConfig:
    provider: LlmProviderType = LlmProviderType.LLAMA_CPP
    llama_cpp: LlamaCppConfig = field(default_factory=LlamaCppConfig)
    openai: OpenAiConfig = field(default_factory=OpenAiConfig)


# ---------------------------------------------------------------------------
# Top-level Settings
# ---------------------------------------------------------------------------

class Settings:
    """All application settings, loaded from ``config/config.yaml``.

    Environment variables (from ``.env`` or the shell) override YAML values.
    The mapping uses a simple convention: uppercase section + field name
    replaces dots with underscores, e.g. ``LLM_PROVIDER``,
    ``MOCK_LOG_COUNT``, ``WATCHER_DEDUP_TTL``.

    Attributes are exposed as nested objects for clean access:

    .. code-block:: python

        settings.llm.provider          # LlmProviderType.LLAMA_CPP
        settings.mock.log_count        # 50
        settings.watcher.dedup_ttl     # 300.0
        settings.metrics.source.type   # "mock"
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        **overrides: Any,
    ) -> None:
        # Apply keyword overrides (bypass YAML / env) — must be set before _build_* calls
        self._overrides: dict[str, Any] = {}
        for key, value in overrides.items():
            self._overrides[key] = value
        self._yaml = self._load_yaml(config_path)
        self.log_source = self._build_log_source()
        self.mock = self._build_mock()
        self.watcher = self._build_watcher()
        self.predictor = self._build_predictor()
        self.metrics = self._build_metrics()
        self.llm = self._build_llm()

    # ------------------------------------------------------------------
    # YAML loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_yaml(config_path: str | Path | None) -> dict[str, Any]:
        """Load config.yaml, falling back to built-in defaults."""
        if config_path is None:
            # Resolve relative to project root (parent of src/)
            config_path = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
        path = Path(config_path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    return data
        return {}

    @staticmethod
    def _env(key: str, default: Any) -> Any:
        """Read an environment variable and coerce it to *default*'s type."""
        raw = os.environ.get(key)
        if raw is None:
            return default
        if isinstance(default, bool):
            return raw.lower() in ("1", "true", "yes")
        if isinstance(default, int):
            try:
                return int(raw)
            except ValueError:
                return default
        if isinstance(default, float):
            try:
                return float(raw)
            except ValueError:
                return default
        if isinstance(default, list):
            return [s.strip() for s in raw.split(",") if s.strip()]
        return raw

    def _resolve(self, yaml_path: str, env_key: str | None = None, default: Any = None) -> Any:
        """Get a value from constructor overrides, env var, then YAML, then *default*."""
        # 0. Constructor overrides (highest priority)
        flat_key = yaml_path.replace(".", "_").lower()
        if flat_key in self._overrides:
            return self._overrides[flat_key]
        # 1. Environment variable
        if env_key is not None and env_key in os.environ:
            return self._env(env_key, default)
        # 2. YAML
        parts = yaml_path.split(".")
        node: Any = self._yaml
        for part in parts:
            if isinstance(node, dict):
                node = node.get(part)
            else:
                node = None
                break
        if node is not None:
            return node
        # 3. Default
        return default

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_log_source(self) -> LogSourceConfig:
        return LogSourceConfig(
            type=self._resolve("log_source.type", "LOG_SOURCE_TYPE", "mock"),
            folder_path=self._resolve("log_source.folder_path", "LOG_SOURCE_FOLDER_PATH", "mocks/logs"),
        )

    def _build_mock(self) -> MockConfig:
        return MockConfig(
            log_count=int(self._resolve("mock.log_count", "MOCK_LOG_COUNT", 50)),
            interval=float(self._resolve("mock.interval", "MOCK_LOG_INTERVAL", 1.0)),
            severities=self._resolve("mock.severities", "MOCK_LOG_SEVERITIES", ["info", "warn", "error", "critical"]),
            services=self._resolve("mock.services", "MOCK_LOG_SERVICES", [
                "auth-service", "payment-service", "gateway",
                "inventory-service", "user-api", "order-processor",
            ]),
        )

    def _build_watcher(self) -> WatcherConfig:
        return WatcherConfig(
            min_severity=str(self._resolve("watcher.min_severity", "WATCHER_MIN_SEVERITY", "medium")),
            dedup_ttl=float(self._resolve("watcher.dedup_ttl", "WATCHER_DEDUP_TTL", 300.0)),
            dedup_threshold=int(self._resolve("watcher.dedup_threshold", "WATCHER_DEDUP_THRESHOLD", 1)),
            context_before=int(self._resolve("watcher.context_before", "WATCHER_CONTEXT_BEFORE", 5)),
            context_after=int(self._resolve("watcher.context_after", "WATCHER_CONTEXT_AFTER", 3)),
        )

    def _build_predictor(self) -> PredictorConfig:
        return PredictorConfig(
            window_size=int(self._resolve("predictor.window_size", "PREDICTOR_WINDOW_SIZE", 200)),
        )

    def _build_metrics(self) -> MetricsConfig:
        source_type = str(self._resolve("metrics.source.type", "METRICS_SOURCE_TYPE", "mock"))
        folder_path = str(self._resolve("metrics.source.folder_path", "METRICS_FOLDER_PATH", "./demo_metrics"))
        cpu_thresh = float(self._resolve("metrics.thresholds.cpu_percent", "METRICS_CPU_THRESHOLD", 85.0))
        mem_thresh = float(self._resolve("metrics.thresholds.memory_percent", "METRICS_MEMORY_THRESHOLD", 90.0))
        interval = float(self._resolve("metrics.stream_interval_seconds", "METRICS_STREAM_INTERVAL", 5.0))

        pred_window = int(self._resolve('metrics.predictor_window_size', 'METRICS_PREDICTOR_WINDOW_SIZE', 100))
        scenarios = self._resolve('metrics.scenarios', 'METRICS_SCENARIOS', [])
        if isinstance(scenarios, str):
            scenarios = [s.strip() for s in scenarios.split(',') if s.strip()]

        return MetricsConfig(
            source=MetricSourceConfig(type=source_type, folder_path=folder_path),
            thresholds=MetricsThresholds(cpu_percent=cpu_thresh, memory_percent=mem_thresh),
            stream_interval_seconds=interval,
            predictor_window_size=pred_window,
            scenarios=list(scenarios),
        )

    def _build_llm(self) -> LlmConfig:
        provider_str = str(self._resolve("llm.provider", "LLM_PROVIDER", "llama_cpp"))
        try:
            provider = LlmProviderType(provider_str)
        except ValueError:
            provider = LlmProviderType.LLAMA_CPP

        return LlmConfig(
            provider=provider,
            llama_cpp=LlamaCppConfig(
                base_url=str(self._resolve("llm.llama_cpp.base_url", "LLAMA_CPP_BASE_URL", "http://localhost:8080/v1")),
                model_name=str(self._resolve("llm.llama_cpp.model_name", "LLAMA_CPP_MODEL_NAME", "./models/llama-model.gguf")),
            ),
            openai=OpenAiConfig(
                api_key=str(self._resolve("llm.openai.api_key", "OPENAI_API_KEY", "")),
                base_url=str(self._resolve("llm.openai.base_url", "OPENAI_BASE_URL", "https://api.openai.com/v1")),
                model_name=str(self._resolve("llm.openai.model_name", "OPENAI_MODEL_NAME", "gpt-4o")),
            ),
        )

    # ------------------------------------------------------------------
    # Backward-compatible flat attributes (for existing callers)
    # ------------------------------------------------------------------

    @property
    def llm_provider(self) -> LlmProviderType:
        """Alias for settings.llm.provider — keeps old code working."""
        if "llm_provider" in self._overrides:
            return self._overrides["llm_provider"]
        return self.llm.provider

    @llm_provider.setter
    def llm_provider(self, value: LlmProviderType) -> None:
        self._overrides["llm_provider"] = value

    @property
    def llama_cpp_base_url(self) -> str:
        return self.llm.llama_cpp.base_url

    @property
    def llama_cpp_model_name(self) -> str:
        return self.llm.llama_cpp.model_name

    @property
    def openai_api_key(self) -> str:
        return self.llm.openai.api_key

    @property
    def openai_base_url(self) -> str:
        return self.llm.openai.base_url

    @property
    def openai_model_name(self) -> str:
        return self.llm.openai.model_name

    @property
    def mock_log_count(self) -> int:
        return self.mock.log_count

    @property
    def mock_log_severities(self) -> list[str]:
        return self.mock.severities

    @property
    def mock_log_dir(self) -> str:
        return self.log_source.folder_path

    @property
    def mock_log_interval(self) -> float:
        return self.mock.interval

    @property
    def mock_log_services(self) -> list[str]:
        if "mock_log_services" in self._overrides:
            return self._overrides["mock_log_services"]
        return self.mock.services

    @mock_log_services.setter
    def mock_log_services(self, value: list[str]) -> None:
        self._overrides["mock_log_services"] = value
