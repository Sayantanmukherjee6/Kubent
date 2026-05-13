"""Factory for creating metric source instances.

Returns a ``BaseMetricSource`` subclass based on the configured
``metrics.source.type`` in ``config/config.yaml`` (or the ``Settings`` object).

Supported types:
    - ``"mock"``  → ``MockMetricSource`` (default, generates synthetic metrics)
    - ``"folder"`` → ``FolderMetricSource``  (tails *.csv files in a directory)

Usage
-----

.. code-block:: python

    from src.config.settings import Settings
    from src.core.metrics.factory import create_metric_source

    settings = Settings()
    source = create_metric_source(settings)
    await source.start()
    async for sample in source.stream():
        print(sample.service_name, sample.cpu_usage)
    await source.stop()
"""

from src.config.settings import Settings
from src.core.metrics.base import BaseMetricSource
from src.core.metrics.folder_metric_source import FolderMetricSource
from src.core.metrics.mock_metric_source import MockMetricSource


def create_metric_source(settings: Settings, folder_path: str | None = None) -> BaseMetricSource:
    """Create a metric source based on the configured type.

    Args:
        settings: Application settings containing ``metrics.source.type`` and
                  ``metrics.source.folder_path``.
        folder_path: Optional override for the folder path (used by both
                     ``MockMetricSource`` and ``FolderMetricSource``).  When
                     ``None``, falls back to ``settings.metrics.source.folder_path``.

    Returns:
        A concrete ``BaseMetricSource`` instance.

    Raises:
        ValueError: If ``metrics.source.type`` is not recognized.
    """
    source_type = settings.metrics.source.type
    effective_path = folder_path or settings.metrics.source.folder_path

    if source_type == "mock":
        return MockMetricSource(settings)

    if source_type == "folder":
        return FolderMetricSource(settings, folder_path=effective_path)

    raise ValueError(
        f"Unknown metrics.source.type: {source_type!r}. "
        f"Supported types: 'mock', 'folder'."
    )
