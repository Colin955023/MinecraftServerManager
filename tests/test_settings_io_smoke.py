from __future__ import annotations

import copy
import json
import threading
import time
from typing import Any

import pytest
import src.utils.runtime_utils.settings_manager as settings_module
from src.core import ConfigurationError


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

    reloaded = settings_module.SettingsManager()
    assert reloaded.get_servers_root() == expected_servers_root
    assert reloaded.is_auto_update_enabled() is False

    settings_path = user_data_dir / "user_settings.json"
    stored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert stored["servers_root"] == expected_servers_root
    assert stored["auto_update_enabled"] is False


def test_window_preferences_defaults_enabled_and_persist_to_user_settings(tmp_path, monkeypatch) -> None:
    user_data_dir = tmp_path / "user_data"
    monkeypatch.setattr(
        settings_module.RuntimePaths,
        "get_user_data_dir",
        staticmethod(lambda: user_data_dir),
    )

    manager = settings_module.SettingsManager()
    assert manager.is_remember_size_position_enabled() is True
    assert manager.is_auto_center_enabled() is True
    assert manager.is_adaptive_sizing_enabled() is True
    assert manager.get_theme_mode() == "system"

    manager.set_remember_size_position(False)
    manager.set_auto_center(False)
    manager.set_adaptive_sizing(False)
    manager.set_theme_mode("dark")

    reloaded = settings_module.SettingsManager()
    assert reloaded.is_remember_size_position_enabled() is False
    assert reloaded.is_auto_center_enabled() is False
    assert reloaded.is_adaptive_sizing_enabled() is False
    assert reloaded.get_theme_mode() == "dark"

    settings_path = user_data_dir / "user_settings.json"
    stored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert stored["window_preferences"]["remember_size_position"] is False
    assert stored["window_preferences"]["auto_center"] is False
    assert stored["window_preferences"]["adaptive_sizing"] is False
    assert stored["window_preferences"]["theme_mode"] == "dark"
    assert "debug_settings" not in stored


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


def test_settings_manager_concurrent_window_pref_updates_preserve_snapshot_integrity(tmp_path, monkeypatch) -> None:
    user_data_dir = tmp_path / "user_data"
    monkeypatch.setattr(
        settings_module.RuntimePaths,
        "get_user_data_dir",
        staticmethod(lambda: user_data_dir),
    )

    manager = settings_module.SettingsManager()
    saved_snapshots: list[dict[str, Any]] = []
    save_lock = threading.Lock()

    def fake_save_settings(_self, settings) -> None:
        with save_lock:
            saved_snapshots.append(copy.deepcopy(settings))
        time.sleep(0.01)

    monkeypatch.setattr(settings_module.SettingsManager, "_save_settings", fake_save_settings)

    errors: list[BaseException] = []
    start = threading.Barrier(2)

    def _run(work) -> None:
        try:
            start.wait(timeout=5)
            work()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=_run, args=(lambda: manager.set_auto_center(False),)),
        threading.Thread(target=_run, args=(lambda: manager.set_theme_mode("dark"),)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not errors
    assert any(
        snapshot["window_preferences"]["auto_center"] is False
        and snapshot["window_preferences"]["theme_mode"] == "dark"
        for snapshot in saved_snapshots
    )
