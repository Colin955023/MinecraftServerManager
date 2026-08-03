from __future__ import annotations

from src.core import ServerCRUD, ServerStartup
from src.models import ServerConfig
from src.utils import ServerPropertiesHelper, ServerPropertiesValidator


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


def test_server_manager_update_server_properties_persists_empty_values_and_updates_config(tmp_path) -> None:
    manager = ServerCRUD(str(tmp_path))
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


def test_official_boolean_server_properties_are_classified_as_checkbox_candidates(tmp_path) -> None:
    manager = ServerCRUD(str(tmp_path))
    defaults = manager.get_default_server_properties()
    boolean_keys = [key for key, value in defaults.items() if str(value).strip().lower() in {"true", "false"}]

    missing = [key for key in boolean_keys if not ServerPropertiesValidator.is_boolean_property(key)]

    assert missing == []
    assert ServerPropertiesValidator.is_boolean_property("enforce-whitelist") is True
    assert ServerPropertiesValidator.is_boolean_property("enforce-secure-profile") is True
    assert ServerPropertiesValidator.is_boolean_property("motd") is False


def test_current_java_server_defaults_and_validation_match_official_schema(tmp_path) -> None:
    manager = ServerCRUD(str(tmp_path))
    defaults = manager.get_default_server_properties()

    expected_keys = {
        "enable-code-of-conduct",
        "management-server-allowed-origins",
        "management-server-enabled",
        "management-server-host",
        "management-server-port",
        "management-server-secret",
        "management-server-tls-enabled",
        "management-server-tls-keystore",
        "management-server-tls-keystore-password",
        "status-heartbeat-interval",
    }
    obsolete_keys = {"allow-nether", "enable-command-block", "pvp", "spawn-monsters"}

    assert expected_keys.issubset(defaults.keys())
    assert obsolete_keys.isdisjoint(defaults.keys())
    assert defaults["management-server-port"] == "0"
    assert defaults["management-server-secret"] == ""
    assert defaults["management-server-tls-enabled"] == "true"

    assert ServerPropertiesValidator.is_boolean_property("enable-code-of-conduct") is True
    assert ServerPropertiesValidator.is_boolean_property("management-server-enabled") is True
    assert ServerPropertiesValidator.validate_property("management-server-port", "0")[0] is True
    assert ServerPropertiesValidator.validate_property("management-server-port", "65535")[0] is True
    assert ServerPropertiesValidator.validate_property("management-server-port", "65536")[0] is False
    assert ServerPropertiesValidator.validate_property("region-file-compression", "lz4")[0] is True
    assert ServerPropertiesValidator.validate_property("level-type", "minecraft:single_biome_surface")[0] is True
    assert ServerPropertiesValidator.validate_property("level-type", "single_biome_surface")[0] is True
    assert ServerPropertiesValidator.validate_property("level-type", "buffet")[0] is False
    assert ServerPropertiesValidator.validate_property("text-filtering-version", "1")[0] is True
    assert ServerPropertiesValidator.validate_property("text-filtering-version", "2")[0] is False
    assert ServerPropertiesValidator.validate_property("pause-when-empty-seconds", "-5")[0] is True


def test_load_server_properties_skips_config_write_when_properties_unchanged(tmp_path, monkeypatch) -> None:
    manager = ServerCRUD(str(tmp_path))
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


def test_server_manager_rejects_path_traversal_on_create_and_delete(tmp_path, monkeypatch) -> None:
    manager = ServerCRUD(str(tmp_path))

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


def test_server_manager_rolls_back_when_launch_script_write_fails(tmp_path, monkeypatch) -> None:
    manager = ServerCRUD(str(tmp_path))
    server_dir = tmp_path / "demo"
    config = ServerConfig(
        name="demo",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path="",
    )

    monkeypatch.setattr(manager, "create_launch_script", lambda *_args, **_kwargs: False)

    result = manager.create_server_result(config)

    assert result.failed is True
    assert config.name not in manager.servers
    assert not server_dir.exists()


def test_server_manager_rolls_back_when_servers_config_write_fails(tmp_path, monkeypatch) -> None:
    manager = ServerCRUD(str(tmp_path))
    server_dir = tmp_path / "demo"
    config = ServerConfig(
        name="demo",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path="",
    )

    monkeypatch.setattr(manager, "create_launch_script", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(manager, "write_servers_config", lambda: False)

    result = manager.create_server_result(config)

    assert result.failed is True
    assert config.name not in manager.servers
    assert not server_dir.exists()


def test_server_manager_rolls_back_when_add_server_write_fails(tmp_path, monkeypatch) -> None:
    manager = ServerCRUD(str(tmp_path))
    server_dir = tmp_path / "imported"
    server_dir.mkdir()
    config = ServerConfig(
        name="imported",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(server_dir),
    )

    monkeypatch.setattr(manager, "_prepare_imported_startup_scripts", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(manager, "write_servers_config", lambda: False)

    assert manager.add_server(config) is False
    assert config.name not in manager.servers


def test_server_manager_rolls_back_when_delete_server_write_fails(tmp_path, monkeypatch) -> None:
    manager = ServerCRUD(str(tmp_path))
    server_dir = tmp_path / "demo"
    server_dir.mkdir()
    config = ServerConfig(
        name="demo",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(server_dir),
    )
    manager.servers[config.name] = config

    monkeypatch.setattr(manager, "write_servers_config", lambda: False)

    assert manager.delete_server(config.name) is False
    assert manager.servers[config.name] == config
    assert server_dir.exists()


def test_server_manager_rejects_outside_path_on_start(tmp_path, monkeypatch) -> None:
    manager = ServerCRUD(str(tmp_path))
    startup = ServerStartup(str(tmp_path))
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
    monkeypatch.setattr(
        manager,
        "create_launch_script",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not create script")),
    )

    result = startup.start_server_result("escape")

    assert result.success is False
    assert result.title == "伺服器路徑無效"
    assert "必須位於伺服器資料夾內" in result.message
