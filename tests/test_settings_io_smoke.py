from __future__ import annotations

import json

import pytest
import src.utils.runtime_utils.settings_manager as settings_module
from src.core import ConfigurationError


@pytest.mark.smoke
def test_settings_manager_read_write_roundtrip(tmp_path, monkeypatch) -> None:
    user_data_dir = tmp_path / "user_data"
    monkeypatch.setattr(
        settings_module.RuntimePaths,
        "get_user_data_dir",
        staticmethod(lambda: user_data_dir),
    )

    manager = settings_module.SettingsManager()
    expected_servers_root = str(tmp_path / "servers_root")
    manager.set_servers_root(expected_servers_root)
    manager.set_auto_update_enabled(False)
    manager.set_dpi_scaling(1.75)

    reloaded = settings_module.SettingsManager()
    assert reloaded.get_servers_root() == expected_servers_root
    assert reloaded.is_auto_update_enabled() is False
    assert reloaded.get_dpi_scaling() == pytest.approx(1.75)

    settings_path = user_data_dir / "user_settings.json"
    stored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert stored["servers_root"] == expected_servers_root
    assert stored["auto_update_enabled"] is False


@pytest.mark.smoke
def test_settings_manager_normalizes_servers_folder_and_validates_root(tmp_path, monkeypatch) -> None:
    user_data_dir = tmp_path / "user_data"
    monkeypatch.setattr(
        settings_module.RuntimePaths,
        "get_user_data_dir",
        staticmethod(lambda: user_data_dir),
    )

    manager = settings_module.SettingsManager()
    manager.set_servers_root(str(tmp_path / "workspace" / "servers"))

    assert manager.get_servers_root() == str((tmp_path / "workspace").resolve())
    validated_root = manager.get_validated_servers_root_path(create=True)
    assert validated_root == (tmp_path / "workspace" / "servers").resolve()
    assert validated_root.is_dir() is True


@pytest.mark.smoke
def test_settings_manager_set_servers_root_then_validate_creates_missing_servers_folder(tmp_path, monkeypatch) -> None:
    user_data_dir = tmp_path / "user_data"
    monkeypatch.setattr(
        settings_module.RuntimePaths,
        "get_user_data_dir",
        staticmethod(lambda: user_data_dir),
    )

    manager = settings_module.SettingsManager()
    manager.set_servers_root(str(tmp_path / "workspace"))
    validated_root = manager.get_validated_servers_root_path(create=True)

    assert validated_root == (tmp_path / "workspace" / "servers").resolve()
    assert manager.get_servers_root() == str((tmp_path / "workspace").resolve())
    assert validated_root.exists() is True
    assert validated_root.is_dir() is True


@pytest.mark.smoke
def test_settings_manager_validated_servers_root_requires_configuration(tmp_path, monkeypatch) -> None:
    user_data_dir = tmp_path / "user_data"
    monkeypatch.setattr(
        settings_module.RuntimePaths,
        "get_user_data_dir",
        staticmethod(lambda: user_data_dir),
    )

    manager = settings_module.SettingsManager()
    manager.set("servers_root", "")

    with pytest.raises(ConfigurationError, match="尚未設定伺服器主資料夾"):
        manager.get_validated_servers_root_path(create=False)


@pytest.mark.smoke
def test_settings_manager_validated_servers_root_create_true_builds_missing_servers_folder(
    tmp_path, monkeypatch
) -> None:
    user_data_dir = tmp_path / "user_data"
    monkeypatch.setattr(
        settings_module.RuntimePaths,
        "get_user_data_dir",
        staticmethod(lambda: user_data_dir),
    )

    manager = settings_module.SettingsManager()
    manager.set_servers_root(str(tmp_path / "workspace"))

    with pytest.raises(ConfigurationError, match="找不到伺服器資料夾"):
        manager.get_validated_servers_root_path(create=False)

    validated_root = manager.get_validated_servers_root_path(create=True)
    assert validated_root == (tmp_path / "workspace" / "servers").resolve()
    assert validated_root.exists() is True
    assert validated_root.is_dir() is True
