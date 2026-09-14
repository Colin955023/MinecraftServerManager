from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import src.core.server.server_crud as crud_module
import src.core.server.server_properties as properties_module
from src.core import (
    CreateServerJourney,
    ServerConfigChangeSet,
    ServerCRUD,
    ServerImportService,
    ServerPropertiesStore,
    ServerRuntime,
)
from src.core.server.server_properties_codec import PropertiesSchema
from src.models import ServerConfig


def _make_store(tmp_path: Path, content: str | bytes | None = None) -> tuple[ServerCRUD, ServerPropertiesStore, Path]:
    manager = ServerCRUD(str(tmp_path))
    server_dir = tmp_path / "demo"
    server_dir.mkdir(exist_ok=True)
    _register(
        manager,
        ServerConfig(
            name="demo",
            minecraft_version="1.20.1",
            loader_type="vanilla",
            loader_version="",
            memory_max_mb=2048,
            path=str(server_dir),
        ),
    )
    properties_path = server_dir / "server.properties"
    if isinstance(content, bytes):
        properties_path.write_bytes(content)
    elif content is not None:
        properties_path.write_text(content, encoding="utf-8")
    return manager, ServerPropertiesStore(manager), properties_path


def _register(manager: ServerCRUD, *configs: ServerConfig) -> None:
    baseline = manager.snapshot()
    result = manager.commit(ServerConfigChangeSet(upserts=tuple(configs)), expected_revision=baseline.revision)
    assert result.success, result.message


def test_store_parses_escaped_delimiters_and_preserves_unknown_keys(tmp_path: Path) -> None:
    _, store, _ = _make_store(
        tmp_path,
        "# Minecraft server properties\nmotd=Hello\\: World\ncustom-key=\\=Welcome\nserver-ip=\\ 127.0.0.1\n",
    )

    snapshot = store.describe("demo")

    assert snapshot.status == "ok"
    assert snapshot.properties == {
        "motd": "Hello: World",
        "custom-key": "=Welcome",
        "server-ip": " 127.0.0.1",
    }


def test_store_round_trip_preserves_unicode_empty_and_unknown_values(tmp_path: Path) -> None:
    _, store, properties_path = _make_store(tmp_path)
    initial = store.describe("demo")

    result = store.commit(
        "demo",
        {"motd": "Hello: Survival", "custom-key": "我的世界", "server-ip": ""},
        expected_revision=initial.revision,
    )

    assert result.success
    assert store.describe("demo").properties == {
        "motd": "Hello: Survival",
        "custom-key": "我的世界",
        "server-ip": "",
    }
    assert properties_path.is_file()


def test_store_round_trip_escapes_properties_control_characters(tmp_path: Path) -> None:
    _, store, _ = _make_store(tmp_path)
    initial = store.describe("demo")
    value = " leading\\tab\tline\ncarriage\rform\x0c=:"

    result = store.commit("demo", {"motd": value}, expected_revision=initial.revision)

    assert result.success
    assert store.describe("demo").properties["motd"] == value


def test_store_rejects_revision_conflict_without_overwriting_external_change(tmp_path: Path) -> None:
    _, store, properties_path = _make_store(tmp_path, "motd=original\n")
    baseline = store.describe("demo")
    properties_path.write_text("motd=external\n", encoding="utf-8")

    result = store.commit("demo", {"motd": "dialog"}, expected_revision=baseline.revision)

    assert result.success is False
    assert result.error_kind == "conflict"
    assert properties_path.read_text(encoding="utf-8") == "motd=external\n"


def test_store_validation_and_atomic_write_failure_leave_original_file(tmp_path: Path, monkeypatch: Any) -> None:
    _, store, properties_path = _make_store(tmp_path, "server-port=25565\nmotd=stable\n")
    baseline = store.describe("demo")

    invalid = store.commit("demo", {"server-port": "70000"}, expected_revision=baseline.revision)
    assert invalid.error_kind == "invalid"
    assert properties_path.read_text(encoding="utf-8") == "server-port=25565\nmotd=stable\n"

    monkeypatch.setattr(properties_module, "atomic_write_text", lambda *_args, **_kwargs: False)
    failed = store.commit("demo", {"motd": "changed"}, expected_revision=baseline.revision)
    assert failed.error_kind == "write_failed"
    assert properties_path.read_text(encoding="utf-8") == "server-port=25565\nmotd=stable\n"


def test_store_distinguishes_missing_empty_invalid_and_unreadable(tmp_path: Path, monkeypatch: Any) -> None:
    _, store, properties_path = _make_store(tmp_path)
    assert store.describe("demo").status == "missing"

    properties_path.write_bytes(b"")
    assert store.describe("demo").status == "empty"

    properties_path.write_bytes(b"\xff")
    assert store.describe("demo").status == "invalid"

    monkeypatch.setattr(
        properties_module,
        "read_bytes_file",
        lambda path, **_kwargs: None if path == properties_path else b"",
    )
    assert store.describe("demo").status == "unreadable"


def test_store_rejects_oversized_properties_file(tmp_path: Path) -> None:
    _, store, properties_path = _make_store(tmp_path)
    properties_path.write_bytes(b"x" * (properties_module.SAFE_TEXT_FILE_MAX_BYTES + 1))

    snapshot = store.describe("demo")

    assert snapshot.status == "unreadable"
    assert "大小上限" in snapshot.message


def test_describe_and_commit_do_not_mutate_registry_model(tmp_path: Path) -> None:
    manager, store, _ = _make_store(tmp_path, "motd=stable\n")

    baseline = store.describe("demo")
    result = store.commit("demo", {"motd": "changed"}, expected_revision=baseline.revision)

    assert result.success
    assert not hasattr(manager.snapshot().get("demo"), "properties")


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

    assert not hasattr(manager.snapshot().get("demo"), "properties")
    config = manager.snapshot().get("demo")
    assert config is not None
    baseline = manager.snapshot()
    assert manager.commit(ServerConfigChangeSet(upserts=(config,)), expected_revision=baseline.revision).success
    persisted = json.loads(config_file.read_text(encoding="utf-8"))
    assert "properties" not in persisted["demo"]


def test_registry_snapshot_rejects_paths_outside_servers_root(tmp_path: Path) -> None:
    servers_root = tmp_path / "servers"
    outside_path = tmp_path / "outside"
    outside_path.mkdir()
    (servers_root).mkdir()
    (servers_root / "servers_config.json").write_text(
        json.dumps(
            {
                "escape": {
                    "name": "escape",
                    "minecraft_version": "1.21.1",
                    "loader_type": "vanilla",
                    "loader_version": "",
                    "memory_max_mb": 2048,
                    "path": str(outside_path),
                }
            }
        ),
        encoding="utf-8",
    )

    manager = ServerCRUD(str(servers_root))

    assert "escape" not in manager.snapshot()


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
    assert PropertiesSchema.validate_properties({"management-server-port": "65535"})[0]
    assert not PropertiesSchema.validate_properties({"management-server-port": "65536"})[0]
    assert PropertiesSchema.validate_properties({"level-type": "minecraft:single_biome_surface"})[0]
    assert not PropertiesSchema.validate_properties({"level-type": "buffet"})[0]


def test_server_manager_rejects_path_traversal_on_create_and_delete(tmp_path: Path) -> None:
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
    with pytest.raises(ValueError, match="路徑片段"):
        CreateServerJourney(manager, _PlanOnlyLoader()).plan(create_config)
    assert "../escape" not in manager.snapshot()

    outside_path = tmp_path.parents[0] / "escape"
    delete_config = ServerConfig(
        name="escape",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(outside_path),
    )
    result = manager.commit(
        ServerConfigChangeSet(upserts=(delete_config,)),
        expected_revision=manager.snapshot().revision,
    )
    assert result.success is False

    stopped_runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        prepare_maintenance=lambda _name, _path: True,
    )
    assert manager.delete_server_result(delete_config.name, server_runtime=stopped_runtime).success is False
    assert manager.snapshot().get(delete_config.name) is None


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
    monkeypatch.setattr(crud_module, "atomic_write_json", lambda *_args, **_kwargs: False)

    result = service.execute(inspection)

    assert result.status == "failed"
    assert "imported" not in manager.snapshot()
    assert not (servers_root / "imported").exists()
    assert (source / "server.jar").is_file()


def test_server_manager_rolls_back_when_delete_server_write_fails(tmp_path: Path, monkeypatch: Any) -> None:
    manager = ServerCRUD(str(tmp_path))
    server_dir = tmp_path / "demo"
    server_dir.mkdir()
    (server_dir / "world.dat").write_bytes(b"world")
    config = ServerConfig("demo", "1.20.1", "vanilla", "", 2048, path=str(server_dir))
    _register(manager, config)
    monkeypatch.setattr(crud_module, "atomic_write_json", lambda *_args, **_kwargs: False)

    stopped_runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        prepare_maintenance=lambda _name, _path: True,
    )
    assert manager.delete_server_result(config.name, server_runtime=stopped_runtime).success is False
    assert manager.snapshot().get(config.name) == config
    assert server_dir.exists()
    assert (server_dir / "world.dat").read_bytes() == b"world"
    assert not list(tmp_path.glob(".msm-delete-*"))


def test_server_manager_delete_registry_commit_failure_restores_directory_without_marker(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    manager = ServerCRUD(str(tmp_path))
    server_dir = tmp_path / "demo"
    server_dir.mkdir()
    (server_dir / "world.dat").write_bytes(b"world")
    config = ServerConfig("demo", "1.20.1", "vanilla", "", 2048, path=str(server_dir))
    _register(manager, config)
    real_atomic_write_json = crud_module.atomic_write_json

    def _fail_registry_write(path: Path, data: Any, *args: Any, **kwargs: Any) -> bool:
        if Path(path).name == "servers_config.json":
            return False
        return real_atomic_write_json(path, data, *args, **kwargs)

    monkeypatch.setattr(crud_module, "atomic_write_json", _fail_registry_write)
    stopped_runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        prepare_maintenance=lambda _name, _path: True,
    )

    result = manager.delete_server_result(config.name, server_runtime=stopped_runtime)

    assert result.success is False
    assert manager.snapshot().get(config.name) == config
    assert server_dir.is_dir()
    assert (server_dir / "world.dat").read_bytes() == b"world"
    assert not (server_dir / ".msm-delete.json").exists()
    assert not list(tmp_path.glob(".msm-delete-*"))


def test_server_manager_recovers_uncommitted_delete_tombstone_on_restart(tmp_path: Path) -> None:
    manager = ServerCRUD(str(tmp_path))
    server_dir = tmp_path / "demo"
    server_dir.mkdir()
    (server_dir / "world.dat").write_bytes(b"world")
    config = ServerConfig("demo", "1.20.1", "vanilla", "", 2048, path=str(server_dir))
    _register(manager, config)

    tombstone = tmp_path / ".msm-delete-recovery"
    server_dir.replace(tombstone)
    (tombstone / ".msm-delete.json").write_text(
        json.dumps({"schema_version": 1, "server_name": "demo"}),
        encoding="utf-8",
    )

    reloaded = ServerCRUD(str(tmp_path))

    assert reloaded.snapshot().get("demo") is not None
    assert server_dir.is_dir()
    assert (server_dir / "world.dat").read_bytes() == b"world"
    assert not (server_dir / ".msm-delete.json").exists()
    assert not tombstone.exists()


def test_server_manager_schedules_committed_delete_tombstone_cleanup_on_restart(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    manager = ServerCRUD(str(tmp_path))
    server_dir = tmp_path / "demo"
    server_dir.mkdir()
    (server_dir / "world.dat").write_bytes(b"world")
    config = ServerConfig("demo", "1.20.1", "vanilla", "", 2048, path=str(server_dir))
    _register(manager, config)

    tombstone = tmp_path / ".msm-delete-committed"
    server_dir.replace(tombstone)
    (tombstone / ".msm-delete.json").write_text(
        json.dumps({"schema_version": 1, "server_name": "demo"}),
        encoding="utf-8",
    )
    removal = manager.commit(
        ServerConfigChangeSet(removals=("demo",)),
        expected_revision=manager.snapshot().revision,
    )
    assert removal.success is True

    scheduled: list[Path] = []

    def schedule_cleanup(_: ServerCRUD, path: Path) -> bool:
        scheduled.append(path)
        return True

    monkeypatch.setattr(
        ServerCRUD,
        "_schedule_delete_cleanup",
        schedule_cleanup,
    )

    reloaded = ServerCRUD(str(tmp_path))

    assert reloaded.snapshot().get("demo") is None
    assert scheduled == [tombstone]
    assert tombstone.is_dir()


def test_server_manager_rejects_running_server_delete_without_mutation(tmp_path: Path) -> None:
    manager = ServerCRUD(str(tmp_path))
    server_dir = tmp_path / "demo"
    server_dir.mkdir()
    (server_dir / "world.dat").write_bytes(b"world")
    config = ServerConfig("demo", "1.20.1", "vanilla", "", 2048, path=str(server_dir))
    _register(manager, config)
    running_runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=True))

    result = manager.delete_server_result(config.name, server_runtime=running_runtime)

    assert result.success is False
    assert manager.snapshot().get(config.name) == config
    assert (server_dir / "world.dat").read_bytes() == b"world"


def test_server_delete_commits_before_best_effort_tombstone_cleanup(tmp_path: Path, monkeypatch: Any) -> None:
    manager = ServerCRUD(str(tmp_path))
    server_dir = tmp_path / "demo"
    server_dir.mkdir()
    (server_dir / "world.dat").write_bytes(b"world")
    config = ServerConfig("demo", "1.20.1", "vanilla", "", 2048, path=str(server_dir))
    _register(manager, config)
    stopped_runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        prepare_maintenance=lambda _name, _path: True,
    )
    scheduled: list[Path] = []

    def schedule_cleanup(path: Path) -> bool:
        scheduled.append(path)
        return True

    monkeypatch.setattr(manager, "_schedule_delete_cleanup", schedule_cleanup)

    result = manager.delete_server_result(config.name, server_runtime=stopped_runtime)

    assert result.success is True
    assert config.name not in manager.snapshot()
    assert not server_dir.exists()
    assert len(scheduled) == 1
    assert scheduled[0].name.startswith(".msm-delete-")
    assert (scheduled[0] / "world.dat").read_bytes() == b"world"


def test_server_runtime_rejects_outside_path_on_start(tmp_path: Path, monkeypatch: Any) -> None:
    manager = ServerCRUD(str(tmp_path))
    runtime = ServerRuntime(manager)
    outside_path = tmp_path.parents[0] / "escape"
    outside_path.mkdir(parents=True, exist_ok=True)
    result = manager.commit(
        ServerConfigChangeSet(
            upserts=(ServerConfig("escape", "1.20.1", "vanilla", "", 2048, path=str(outside_path)),),
        ),
        expected_revision=manager.snapshot().revision,
    )
    assert result.success is False
    monkeypatch.setattr(
        manager,
        "create_launch_script",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not create script")),
    )

    result = runtime.start("escape")

    assert result.failed
    assert result.title == "伺服器未找到"
