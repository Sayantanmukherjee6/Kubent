"""Tests that CLI commands use the log source factory correctly.

These tests verify that the CLI helper `_build_settings` and the
`create_log_source` factory work together as expected, matching
the behavior of CLI commands like `stream-logs`, `watch-logs`, and
`predict`.
"""

from pathlib import Path

import pytest

from src.config.settings import Settings
from src.core.log_sources.factory import create_log_source
from src.core.log_sources.folder_source import FolderLogSource
from src.core.log_sources.mock_file_source import MockFileLogSource


# Import the CLI helper directly for testing
from src.__main__ import _build_settings


class TestBuildSettingsHelper:
    """Tests for the _build_settings CLI helper function."""

    def test_no_overrides_returns_default_settings(self) -> None:
        """When no CLI flags are provided, settings should use defaults."""
        settings = _build_settings(source=None, log_dir=None)
        assert settings.log_source.type == "mock"

    def test_source_override_changes_type(self) -> None:
        """When --source is provided, log_source.type should be overridden."""
        settings = _build_settings(source="folder", log_dir=None)
        assert settings.log_source.type == "folder"

    def test_log_dir_override_changes_folder_path(self) -> None:
        """When --log-dir is provided, folder_path should be overridden."""
        settings = _build_settings(source=None, log_dir="/custom/path")
        assert settings.log_source.folder_path == "/custom/path"

    def test_both_overrides_applied(self) -> None:
        """Both --source and --log-dir should be applied together."""
        settings = _build_settings(source="folder", log_dir="/custom/logs")
        assert settings.log_source.type == "folder"
        assert settings.log_source.folder_path == "/custom/logs"

    def test_mock_source_override(self) -> None:
        """Explicitly setting source=mock should work."""
        settings = _build_settings(source="mock", log_dir=None)
        assert settings.log_source.type == "mock"


class TestCliFactoryIntegration:
    """Tests that CLI settings produce correct log sources via factory."""

    def test_default_settings_creates_mock_source(self, tmp_path: Path) -> None:
        """Default CLI (no flags) should create MockFileLogSource."""
        settings = _build_settings(source=None, log_dir=None)
        source = create_log_source(settings)
        assert isinstance(source, MockFileLogSource)

    def test_folder_source_flag_creates_folder_source(self, tmp_path: Path) -> None:
        """--source folder should create FolderLogSource."""
        settings = _build_settings(source="folder", log_dir=str(tmp_path))
        source = create_log_source(settings)
        assert isinstance(source, FolderLogSource)

    def test_mock_source_flag_creates_mock_source(self, tmp_path: Path) -> None:
        """--source mock should create MockFileLogSource."""
        settings = _build_settings(source="mock", log_dir=str(tmp_path))
        source = create_log_source(settings)
        assert isinstance(source, MockFileLogSource)

    def test_log_dir_is_passed_to_source(self, tmp_path: Path) -> None:
        """The log_dir override should be reflected in the source."""
        custom_dir = tmp_path / "custom_logs"
        custom_dir.mkdir(parents=True, exist_ok=True)

        settings = _build_settings(source="folder", log_dir=str(custom_dir))
        source = create_log_source(settings)

        assert isinstance(source, FolderLogSource)
        assert str(custom_dir) in source.name

    def test_folder_source_with_custom_dir(self, tmp_path: Path) -> None:
        """Folder source should use the custom directory from CLI."""
        custom_dir = tmp_path / "my_logs"
        custom_dir.mkdir(parents=True, exist_ok=True)

        settings = _build_settings(source="folder", log_dir=str(custom_dir))
        source = create_log_source(settings)

        assert isinstance(source, FolderLogSource)
        # Verify the source was created with the correct path
        assert source._folder_path == custom_dir


class TestFactoryWithSettingsOverrides:
    """Test that factory respects Settings overrides from CLI."""

    def test_settings_override_type_takes_precedence(self, tmp_path: Path) -> None:
        """When settings are built with source override, factory uses it."""
        settings = _build_settings(source="folder", log_dir=str(tmp_path))
        source = create_log_source(settings)
        assert isinstance(source, FolderLogSource)

    def test_settings_override_path_takes_precedence(self, tmp_path: Path) -> None:
        """When settings are built with log_dir override, factory uses it."""
        other_path = tmp_path / "other"
        other_path.mkdir(parents=True, exist_ok=True)

        settings = _build_settings(source="folder", log_dir=str(other_path))
        source = create_log_source(settings)

        assert isinstance(source, FolderLogSource)
        assert str(other_path) in source.name

    def test_factory_path_override_still_works(self, tmp_path: Path) -> None:
        """The factory folder_path arg can still override settings."""
        path_a = tmp_path / "a"
        path_b = tmp_path / "b"
        path_a.mkdir(parents=True, exist_ok=True)
        path_b.mkdir(parents=True, exist_ok=True)

        settings = _build_settings(source="folder", log_dir=str(path_a))
        # Pass explicit folder_path to factory (overrides settings)
        source = create_log_source(settings, folder_path=str(path_b))

        assert isinstance(source, FolderLogSource)
        assert str(path_b) in source.name


class TestBuildSettingsIsolation:
    """Test that _build_settings creates independent Settings instances."""

    def test_multiple_calls_are_independent(self, tmp_path: Path) -> None:
        """Each call to _build_settings should return a new Settings object."""
        settings_a = _build_settings(source="mock", log_dir=str(tmp_path / "a"))
        settings_b = _build_settings(source="folder", log_dir=str(tmp_path / "b"))

        assert settings_a.log_source.type == "mock"
        assert settings_b.log_source.type == "folder"
        assert settings_a is not settings_b

    def test_none_values_do_not_affect_defaults(self) -> None:
        """Passing None for source/log_dir should not change defaults."""
        settings = _build_settings(source=None, log_dir=None)
        # Type should remain the default "mock"
        assert settings.log_source.type == "mock"
        # Path should remain the default
        assert settings.log_source.folder_path == "mocks/logs"
