"""Factory for creating log source instances.

Returns a ``BaseLogSource`` subclass based on the configured
``log_source.type`` in ``config/config.yaml`` (or the ``Settings`` object).

Supported types:
    - ``"mock"``  → ``MockFileLogSource`` (default, generates synthetic logs)
    - ``"folder"`` → ``FolderLogSource``  (tails *.log files in a directory)

Usage
-----

.. code-block:: python

    from src.config.settings import Settings
    from src.core.log_sources.factory import create_log_source

    settings = Settings()
    source = create_log_source(settings)
    await source.start()
    async for log_line in source.stream():
        print(log_line.text)
    await source.stop()
"""

from src.config.settings import Settings
from src.core.log_sources.base import BaseLogSource
from src.core.log_sources.folder_source import FolderLogSource
from src.core.log_sources.mock_file_source import MockFileLogSource


def create_log_source(settings: Settings, folder_path: str | None = None) -> BaseLogSource:
    """Create a log source based on the configured type.

    Args:
        settings: Application settings containing ``log_source.type`` and
                  ``log_source.folder_path``.
        folder_path: Optional override for the folder path (used by both
                     ``MockFileLogSource`` and ``FolderLogSource``).  When
                     ``None``, falls back to ``settings.log_source.folder_path``.

    Returns:
        A concrete ``BaseLogSource`` instance.

    Raises:
        ValueError: If ``settings.log_source.type`` is not recognized.
    """
    source_type = settings.log_source.type
    effective_path = folder_path or settings.log_source.folder_path

    if source_type == "mock":
        return MockFileLogSource(settings, log_dir=effective_path)

    if source_type == "folder":
        return FolderLogSource(settings, folder_path=effective_path)

    raise ValueError(
        f"Unknown log_source.type: {source_type!r}. "
        f"Supported types: 'mock', 'folder'."
    )
