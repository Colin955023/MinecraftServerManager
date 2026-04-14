from __future__ import annotations

import pytest
import src.core.server_manager as server_manager_module
from src.core import ServerManager
from src.models import ServerConfig
from src.utils import ServerPropertiesHelper


@pytest.mark.smoke
def test_load_properties_parses_escaped_delimiters(tmp_path) -> None:
    props_file = tmp_path / "server.properties"
    props_file.write_text(
        "# Minecraft server properties\nmotd=Hello\\: World\nresource-pack-prompt=\\=Welcome\nserver-ip=\\ 127.0.0.1\n",
        encoding="utf-8",
    )

    loaded = ServerPropertiesHelper.load_properties(props_file)
    assert loaded["motd"] == "Hello: World"
    assert loaded["resource-pack-prompt"] == "=Welcome"
    assert loaded["server-ip"] == " 127.0.0.1"


@pytest.mark.smoke
def test_save_properties_round_trip_preserves_values(tmp_path) -> None:
    props_file = tmp_path / "server.properties"
    original = {
        "motd": "Hello: Survival",
        "resource-pack-prompt": "=Please accept",
        "level-name": "我的世界",
    }

    ServerPropertiesHelper.save_properties(props_file, original)
    reloaded = ServerPropertiesHelper.load_properties(props_file)

    assert reloaded["motd"] == original["motd"]
    assert reloaded["resource-pack-prompt"] == original["resource-pack-prompt"]
    assert reloaded["level-name"] == original["level-name"]


@pytest.mark.smoke
def test_server_manager_update_server_properties_persists_empty_values_and_updates_config(tmp_path) -> None:
    manager = ServerManager(str(tmp_path))
    server_dir = tmp_path / "demo"
    server_dir.mkdir()

    manager.servers["demo"] = ServerConfig(
        name="demo",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(server_dir),
        properties={"motd": "Old MOTD", "server-ip": "127.0.0.1"},
    )

    props_file = server_dir / "server.properties"
    assert ServerPropertiesHelper.save_properties(props_file, {"motd": "Old MOTD", "server-ip": "127.0.0.1"})
    assert manager.load_server_properties("demo") == {"motd": "Old MOTD", "server-ip": "127.0.0.1"}

    assert manager.update_server_properties("demo", {"motd": "", "server-ip": ""}) is True

    reloaded = ServerPropertiesHelper.load_properties(props_file)
    assert reloaded["motd"] == ""
    assert reloaded["server-ip"] == ""
    assert manager.servers["demo"].properties == {"motd": "", "server-ip": ""}
    assert manager.load_server_properties("demo") == {"motd": "", "server-ip": ""}


@pytest.mark.smoke
def test_load_server_properties_skips_config_write_when_properties_unchanged(tmp_path, monkeypatch) -> None:
    manager = ServerManager(str(tmp_path))
    server_dir = tmp_path / "demo"
    server_dir.mkdir()

    props = {"motd": "Stable MOTD", "server-ip": "127.0.0.1"}
    manager.servers["demo"] = ServerConfig(
        name="demo",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(server_dir),
        properties=dict(props),
    )

    props_file = server_dir / "server.properties"
    assert ServerPropertiesHelper.save_properties(props_file, props)

    write_calls: list[str] = []

    def _track_write_servers_config() -> bool:
        write_calls.append("called")
        return True

    monkeypatch.setattr(manager, "write_servers_config", _track_write_servers_config)

    loaded_first = manager.load_server_properties("demo")
    loaded_second = manager.load_server_properties("demo")

    assert loaded_first == props
    assert loaded_second == props
    assert write_calls == []


@pytest.mark.smoke
def test_server_manager_rejects_path_traversal_on_create_and_delete(tmp_path, monkeypatch) -> None:
    manager = ServerManager(str(tmp_path))

    create_config = ServerConfig(
        name="../escape",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path="",
    )
    assert manager.create_server(create_config) is False
    assert "../escape" not in manager.servers

    outside_path = tmp_path.parents[0] / "escape"
    delete_config = ServerConfig(
        name="escape",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(outside_path),
    )
    manager.servers[delete_config.name] = delete_config

    write_calls: list[str] = []

    def _track_write_servers_config() -> bool:
        write_calls.append("called")
        return True

    monkeypatch.setattr(manager, "write_servers_config", _track_write_servers_config)

    assert manager.delete_server(delete_config.name) is False
    assert manager.servers[delete_config.name] == delete_config
    assert write_calls == []


@pytest.mark.smoke
def test_server_manager_rejects_outside_path_on_start(tmp_path, monkeypatch) -> None:
    manager = ServerManager(str(tmp_path))
    outside_path = tmp_path.parents[0] / "escape"
    outside_path.mkdir(parents=True, exist_ok=True)

    manager.servers["escape"] = ServerConfig(
        name="escape",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(outside_path),
    )

    error_calls: list[tuple[str, str]] = []

    def _track_error(title: str, message: str, _parent=None, **_kwargs) -> None:
        error_calls.append((title, message))

    monkeypatch.setattr(server_manager_module.UIUtils, "show_error", _track_error)
    monkeypatch.setattr(
        manager,
        "create_launch_script",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not create script")),
    )

    assert manager.start_server("escape") is False
    assert error_calls
    assert "必須位於伺服器資料夾內" in error_calls[0][1]
