from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import src.core.server.server_properties as properties_module
from src.core import CreateServerJourney, ServerCRUD, ServerImportService, ServerPropertiesStore, ServerRuntime
from src.models import ServerConfig
from src.utils import PropertiesSchema


def _make_store(tmp_path: Path, content: str | bytes | None = None) -> tuple[ServerCRUD, ServerPropertiesStore, Path]:
    manager = ServerCRUD(str(tmp_path))
    server_dir = tmp_path / "demo"
    server_dir.mkdir(exist_ok=True)
    manager.servers["demo"] = ServerConfig(
        name="demo",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(server_dir),
    )
    properties_path = server_dir / "server.properties"
    if isinstance(content, bytes):
        properties_path.write_bytes(content)
    elif content is not None:
        properties_path.write_text(content, encoding="utf-8")
    return manager, ServerPropertiesStore(manager), properties_path


def test_store_parses_escaped_delimiters_and_preserves_unknown_keys(tmp_path: Path) -> None:
    _, store, _ = _make_store(
        tmp_path,
        "# Minecraft server properties\nmotd=Hello\\: World\ncustom-key=\\=Welcome\nserver-ip=\\ 127.0.0.1\n",
    )

    snapshot = store.read("demo")

    assert snapshot.status == "ok"
    assert snapshot.properties == {
        "motd": "Hello: World",
        "custom-key": "=Welcome",
        "server-ip": " 127.0.0.1",
    }


def test_store_round_trip_preserves_unicode_empty_and_unknown_values(tmp_path: Path) -> None:
    _, store, properties_path = _make_store(tmp_path)
    initial = store.read("demo")

    result = store.update(
        "demo",
        {"motd": "Hello: Survival", "custom-key": "我的世界", "server-ip": ""},
        expected_revision=initial.revision,
    )

    assert result.success
    assert store.read("demo").properties == {
        "motd": "Hello: Survival",
        "custom-key": "我的世界",
        "server-ip": "",
    }
    assert properties_path.is_file()


def test_store_rejects_revision_conflict_without_overwriting_external_change(tmp_path: Path) -> None:
    _, store, properties_path = _make_store(tmp_path, "motd=original\n")
    baseline = store.read("demo")
    properties_path.write_text("motd=external\n", encoding="utf-8")

    result = store.update("demo", {"motd": "dialog"}, expected_revision=baseline.revision)

    assert result.success is False
    assert result.error_kind == "conflict"
    assert properties_path.read_text(encoding="utf-8") == "motd=external\n"


def test_store_validation_and_atomic_write_failure_leave_original_file(tmp_path: Path, monkeypatch: Any) -> None:
    _, store, properties_path = _make_store(tmp_path, "server-port=25565\nmotd=stable\n")
    baseline = store.read("demo")

    invalid = store.update("demo", {"server-port": "70000"}, expected_revision=baseline.revision)
    assert invalid.error_kind == "invalid"
    assert properties_path.read_text(encoding="utf-8") == "server-port=25565\nmotd=stable\n"

    monkeypatch.setattr(properties_module, "atomic_write_text", lambda *_args, **_kwargs: False)
    failed = store.update("demo", {"motd": "changed"}, expected_revision=baseline.revision)
    assert failed.error_kind == "write_failed"
    assert properties_path.read_text(encoding="utf-8") == "server-port=25565\nmotd=stable\n"


def test_store_distinguishes_missing_empty_invalid_and_unreadable(tmp_path: Path, monkeypatch: Any) -> None:
    _, store, properties_path = _make_store(tmp_path)
    assert store.read("demo").status == "missing"

    properties_path.write_bytes(b"")
    assert store.read("demo").status == "empty"

    properties_path.write_bytes(b"\xff")
    assert store.read("demo").status == "invalid"

    original_read_bytes = Path.read_bytes

    def _deny(path: Path) -> bytes:
        if path == properties_path:
            raise PermissionError("denied")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", _deny)
    assert store.read("demo").status == "unreadable"


def test_read_and_update_never_write_servers_config_or_model_copy(tmp_path: Path, monkeypatch: Any) -> None:
    manager, store, _ = _make_store(tmp_path, "motd=stable\n")
    write_calls: list[str] = []

    def _track_write() -> bool:
        write_calls.append("called")
        return True

    monkeypatch.setattr(manager, "write_servers_config", _track_write)

    baseline = store.read("demo")
    result = store.update("demo", {"motd": "changed"}, expected_revision=baseline.revision)

    assert result.success
    assert write_calls == []
    assert not hasattr(manager.servers["demo"], "properties")


def test_legacy_json_properties_are_ignored_and_not_rewritten(tmp_path: Path) -> None:
    config_file = tmp_path / "servers_config.json"
    config_file.write_text(
        json.dumps(
            {
                "demo": {
                    "name": "demo",
                    "minecraft_version": "1.20.1",
                    "loader_type": "vanilla",
                    "loader_version": "",
                    "memory_max_mb": 2048,
                    "path": str(tmp_path / "demo"),
                    "properties": {"motd": "legacy"},
                }
            }
        ),
        encoding="utf-8",
    )

    manager = ServerCRUD(str(tmp_path))

    assert not hasattr(manager.servers["demo"], "properties")
    assert manager.write_servers_config()
    persisted = json.loads(config_file.read_text(encoding="utf-8"))
    assert "properties" not in persisted["demo"]


def test_current_defaults_and_schema_are_complete() -> None:
    defaults = PropertiesSchema.default_values()
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

    assert expected_keys.issubset(defaults)
    assert obsolete_keys.isdisjoint(defaults)
    assert all(
        PropertiesSchema.is_boolean_property(key) for key, value in defaults.items() if value in {"true", "false"}
    )
    assert PropertiesSchema.validate_properties({"management-server-port": "65535"})[0]
    assert not PropertiesSchema.validate_properties({"management-server-port": "65536"})[0]
    assert PropertiesSchema.validate_properties({"level-type": "minecraft:single_biome_surface"})[0]
    assert not PropertiesSchema.validate_properties({"level-type": "buffet"})[0]


def test_server_manager_rejects_path_traversal_on_create_and_delete(tmp_path: Path, monkeypatch: Any) -> None:
    manager = ServerCRUD(str(tmp_path))

    class _PlanOnlyLoader:
        @staticmethod
        def resolve_installer_artifact(*_args: Any) -> None:
            return None

    create_config = ServerConfig(
        name="../escape",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path="",
    )
    with pytest.raises(ValueError, match="路徑遍歷"):
        CreateServerJourney(manager, _PlanOnlyLoader()).plan(create_config)
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

    def _track_write() -> bool:
        write_calls.append("called")
        return True

    monkeypatch.setattr(manager, "write_servers_config", _track_write)

    stopped_runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=False))
    assert manager.delete_server_result(delete_config.name, server_runtime=stopped_runtime).success is False
    assert manager.servers[delete_config.name] == delete_config
    assert write_calls == []


def test_server_import_rolls_back_files_and_registration_when_config_write_fails(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    servers_root = tmp_path / "servers"
    source = tmp_path / "source"
    source.mkdir()
    (source / "server.jar").write_bytes(b"jar")
    manager = ServerCRUD(str(servers_root))
    service = ServerImportService(manager)
    inspection = service.inspect(source, "imported")
    monkeypatch.setattr(manager, "write_servers_config", lambda: False)

    result = service.execute(inspection)

    assert result.status == "failed"
    assert "imported" not in manager.servers
    assert not (servers_root / "imported").exists()
    assert (source / "server.jar").is_file()


def test_server_manager_rolls_back_when_delete_server_write_fails(tmp_path: Path, monkeypatch: Any) -> None:
    manager = ServerCRUD(str(tmp_path))
    server_dir = tmp_path / "demo"
    server_dir.mkdir()
    (server_dir / "world.dat").write_bytes(b"world")
    config = ServerConfig("demo", "1.20.1", "vanilla", "", 2048, path=str(server_dir))
    manager.servers[config.name] = config
    monkeypatch.setattr(manager, "write_servers_config", lambda: False)

    stopped_runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=False))
    assert manager.delete_server_result(config.name, server_runtime=stopped_runtime).success is False
    assert manager.servers[config.name] == config
    assert server_dir.exists()
    assert (server_dir / "world.dat").read_bytes() == b"world"
    assert not list(tmp_path.glob(".msm-delete-*"))


def test_server_manager_rejects_running_server_delete_without_mutation(tmp_path: Path) -> None:
    manager = ServerCRUD(str(tmp_path))
    server_dir = tmp_path / "demo"
    server_dir.mkdir()
    (server_dir / "world.dat").write_bytes(b"world")
    config = ServerConfig("demo", "1.20.1", "vanilla", "", 2048, path=str(server_dir))
    manager.servers[config.name] = config
    assert manager.write_servers_config()
    running_runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=True))

    result = manager.delete_server_result(config.name, server_runtime=running_runtime)

    assert result.success is False
    assert manager.servers[config.name] == config
    assert (server_dir / "world.dat").read_bytes() == b"world"


def test_server_delete_commits_before_best_effort_tombstone_cleanup(tmp_path: Path, monkeypatch: Any) -> None:
    manager = ServerCRUD(str(tmp_path))
    server_dir = tmp_path / "demo"
    server_dir.mkdir()
    (server_dir / "world.dat").write_bytes(b"world")
    config = ServerConfig("demo", "1.20.1", "vanilla", "", 2048, path=str(server_dir))
    manager.servers[config.name] = config
    assert manager.write_servers_config()
    stopped_runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=False))
    monkeypatch.setattr("src.core.server.server_crud.delete_within", lambda *_args: False)

    result = manager.delete_server_result(config.name, server_runtime=stopped_runtime)

    assert result.success is True
    assert config.name not in manager.servers
    assert not server_dir.exists()
    tombstones = list(tmp_path.glob(".msm-delete-*"))
    assert len(tombstones) == 1
    assert (tombstones[0] / "world.dat").read_bytes() == b"world"


def test_server_runtime_rejects_outside_path_on_start(tmp_path: Path, monkeypatch: Any) -> None:
    manager = ServerCRUD(str(tmp_path))
    runtime = ServerRuntime(manager)
    outside_path = tmp_path.parents[0] / "escape"
    outside_path.mkdir(parents=True, exist_ok=True)
    manager.servers["escape"] = ServerConfig("escape", "1.20.1", "vanilla", "", 2048, path=str(outside_path))
    monkeypatch.setattr(
        manager,
        "create_launch_script",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not create script")),
    )

    result = runtime.start("escape")

    assert result.failed
    assert result.title == "伺服器路徑無效"
