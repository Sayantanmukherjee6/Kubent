"""Log source modules for the Kubernetes Agent.

Public API
----------

- ``BaseLogSource`` — abstract base class all sources implement
- ``LogLine`` — single log line with metadata
- ``MockFileLogSource`` — generates and streams synthetic K8s logs
- ``FolderLogSource`` — tails ``*.log`` files in a shared directory
- ``create_log_source`` — factory that returns the configured source type

Example
-------

.. code-block:: python

    from src.config.settings import Settings
    from src.core.log_sources.factory import create_log_source

    settings = Settings()
    source = create_log_source(settings)
    await source.start()
    async for line in source.stream():
        print(line.text)
    await source.stop()
"""

from src.core.log_sources.base import BaseLogSource, LogLine
from src.core.log_sources.folder_source import FolderLogSource
from src.core.log_sources.factory import create_log_source
from src.core.log_sources.mock_file_source import MockFileLogSource

__all__ = [
    "BaseLogSource",
    "LogLine",
    "MockFileLogSource",
    "FolderLogSource",
    "create_log_source",
]
