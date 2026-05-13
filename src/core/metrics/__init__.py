"""Metric source modules for the Kubernetes Agent.

Public API
----------

- ``BaseMetricSource`` — abstract base class all sources implement
- ``MetricSample`` — single metric sample with metadata
- ``MockMetricSource`` — generates and streams synthetic K8s metrics
- ``FolderMetricSource`` — tails ``*.csv`` files in a shared directory
- ``create_metric_source`` — factory that returns the configured source type

Example
-------

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

from src.core.metrics.base import BaseMetricSource
from src.core.metrics.folder_metric_source import FolderMetricSource
from src.core.metrics.factory import create_metric_source
from src.core.metrics.mock_metric_source import MockMetricSource
from src.core.metrics.models import MetricSample

__all__ = [
    "BaseMetricSource",
    "MetricSample",
    "MockMetricSource",
    "FolderMetricSource",
    "create_metric_source",
]
