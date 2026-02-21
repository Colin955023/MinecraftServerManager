from __future__ import annotations

import json

import pytest
from src.utils import settings_manager as settings_module


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
