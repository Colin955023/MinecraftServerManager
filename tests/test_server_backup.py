from __future__ import annotations

import datetime
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import src.core.server.server_backup as backup_module
from src.core.server.server_crud import ServerConfigChangeSet, ServerConfigRegistrySnapshot, ServerCRUD
from src.models import ServerConfig


class _FixedDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 8, 24, 13, 50, tzinfo=tz)


def _manager(server_dir: Path) -> backup_module.ServerBackupManager:
    backup_dir = server_dir.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    config = SimpleNamespace(name="TestServer", path=str(server_dir), backup_path=str(backup_dir), jvm_args=[])
    crud = SimpleNamespace(
        snapshot=lambda: ServerConfigRegistrySnapshot("test-revision", (("TestServer", config),)),
        servers_root=server_dir.parent,
        operation_lock=threading.RLock(),
    )
    runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        begin_maintenance=lambda _name: True,
        end_maintenance=lambda _name: None,
    )
    return backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, runtime))


def test_backup_is_committed_atomically_and_excludes_runtime_directories(tmp_path, monkeypatch) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "server.properties").write_text("motd=test\n", encoding="utf-8")
    world_dir = server_dir / "world"
    world_dir.mkdir()
    (world_dir / "level.dat").write_bytes(b"world-data")
    logs_dir = server_dir / "logs"
    logs_dir.mkdir()
    (logs_dir / "latest.log").write_text("ignored", encoding="utf-8")

    monkeypatch.setattr(backup_module.datetime, "datetime", _FixedDateTime)

    manager = _manager(server_dir)
    assert manager.backup_server("TestServer") is True

    backup_files = list((tmp_path / "backups").glob("TestServer_*.zip"))
    assert len(backup_files) == 1
    backup_file = backup_files[0]
    assert backup_file.is_file()
    assert not list((tmp_path / "backups").glob("*.tmp"))

    with zipfile.ZipFile(backup_file) as archive:
        assert set(archive.namelist()) == {"server.properties", "world/level.dat"}


def test_backup_failure_keeps_existing_final_backup_and_removes_temp_file(tmp_path, monkeypatch) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "server.properties").write_text("motd=test\n", encoding="utf-8")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "TestServer_202608241350.zip"
    backup_file.write_bytes(b"existing-backup")

    monkeypatch.setattr(backup_module.datetime, "datetime", _FixedDateTime)

    def fail_open_regular_file(*args, **kwargs):
        _ = args, kwargs
        raise OSError("simulated source read failure")

    monkeypatch.setattr(backup_module, "open_regular_file", fail_open_regular_file)

    manager = _manager(server_dir)
    assert manager.backup_server("TestServer") is False
    assert backup_file.read_bytes() == b"existing-backup"
    assert not list(backup_dir.glob("*.tmp"))


def test_backup_rejected_when_server_is_running(tmp_path: Path) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "server.properties").write_text("motd=test\n", encoding="utf-8")
    config = SimpleNamespace(
        name="TestServer", path=str(server_dir), backup_path=str(tmp_path / "backups"), jvm_args=[]
    )
    crud = SimpleNamespace(
        snapshot=lambda: ServerConfigRegistrySnapshot("test-revision", (("TestServer", config),)),
        servers_root=server_dir.parent,
        operation_lock=threading.RLock(),
    )
    runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=True),
        begin_maintenance=lambda _name: True,
        end_maintenance=lambda _name: None,
    )
    manager = backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, runtime))

    assert manager.backup_server("TestServer") is False
    assert not (tmp_path / "backups").exists()


def test_backup_requires_configured_external_directory(tmp_path: Path) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    config = SimpleNamespace(name="TestServer", path=str(server_dir), backup_path="", jvm_args=[])
    crud = SimpleNamespace(
        snapshot=lambda: ServerConfigRegistrySnapshot("test-revision", (("TestServer", config),)),
        servers_root=server_dir.parent,
        operation_lock=threading.RLock(),
    )
    runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        begin_maintenance=lambda _name: True,
        end_maintenance=lambda _name: None,
    )

    assert (
        backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, runtime)).backup_server(
            "TestServer"
        )
        is False
    )
    assert not (server_dir / "backups").exists()


def test_external_backup_directory_is_persisted_in_server_config(tmp_path: Path) -> None:
    server_dir = tmp_path / "TestServer"
    server_dir.mkdir()
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    crud = ServerCRUD(str(tmp_path))
    config = ServerConfig(
        "TestServer", "1.21.1", "vanilla", "", 2048, path=str(server_dir), backup_path=str(backup_dir)
    )
    baseline = crud.snapshot()

    assert crud.commit(ServerConfigChangeSet(upserts=(config,)), expected_revision=baseline.revision).success
    saved_config = ServerCRUD(str(tmp_path)).snapshot().get("TestServer")
    assert saved_config is not None
    assert saved_config.backup_path == str(backup_dir)


def test_delete_backups_only_removes_managed_files(tmp_path: Path) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    managed_backup = backup_dir / "TestServer_20260824135000000000-deadbeef.zip"
    managed_backup.write_bytes(b"backup")
    other_backup = backup_dir / "OtherServer_20260824135000000000-deadbeef.zip"
    other_backup.write_bytes(b"other")

    assert _manager(server_dir).delete_backups("TestServer", backup_dir) is True
    assert not managed_backup.exists()
    assert other_backup.is_file()


def test_backup_rejects_directory_inside_server(tmp_path: Path) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    backup_dir = server_dir / "backup"
    config = SimpleNamespace(name="TestServer", path=str(server_dir), backup_path=str(backup_dir), jvm_args=[])
    crud = SimpleNamespace(
        snapshot=lambda: ServerConfigRegistrySnapshot("test-revision", (("TestServer", config),)),
        servers_root=server_dir.parent,
        operation_lock=threading.RLock(),
    )
    runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        begin_maintenance=lambda _name: True,
        end_maintenance=lambda _name: None,
    )

    assert (
        backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, runtime)).backup_server(
            "TestServer"
        )
        is False
    )
    assert not backup_dir.exists()


def test_backup_rejects_junction_source(tmp_path: Path, make_junction) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    make_junction(server_dir / "linked", outside)

    assert _manager(server_dir).backup_server("TestServer") is False
    assert not list((tmp_path / "backups").glob("*.zip"))


def test_backup_rejects_junction_backup_directory(tmp_path: Path, make_junction) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    outside_dir = tmp_path / "outside-backups"
    outside_dir.mkdir()
    backup_dir = tmp_path / "backups"
    make_junction(backup_dir, outside_dir)

    config = SimpleNamespace(name="TestServer", path=str(server_dir), backup_path=str(backup_dir), jvm_args=[])
    crud = SimpleNamespace(
        snapshot=lambda: ServerConfigRegistrySnapshot("test-revision", (("TestServer", config),)),
        servers_root=server_dir.parent,
        operation_lock=threading.RLock(),
    )
    runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        begin_maintenance=lambda _name: True,
        end_maintenance=lambda _name: None,
    )

    assert (
        backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, runtime)).backup_server(
            "TestServer"
        )
        is False
    )
    assert not list(outside_dir.glob("*.zip"))


def test_backup_names_are_unique_and_listed_for_literal_server_name(tmp_path: Path, monkeypatch) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "server.properties").write_text("motd=test\n", encoding="utf-8")
    server_name = "[Forge] 1.21"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    config = SimpleNamespace(name=server_name, path=str(server_dir), backup_path=str(backup_dir), jvm_args=[])
    crud = SimpleNamespace(
        snapshot=lambda: ServerConfigRegistrySnapshot("test-revision", ((server_name, config),)),
        servers_root=server_dir.parent,
        operation_lock=threading.RLock(),
    )
    runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        begin_maintenance=lambda _name: True,
        end_maintenance=lambda _name: None,
    )
    manager = backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, runtime))
    monkeypatch.setattr(backup_module.datetime, "datetime", _FixedDateTime)

    assert manager.backup_server(server_name) is True
    assert manager.backup_server(server_name) is True

    backups = manager.list_backups(server_name)
    assert len(backups) == 2
    assert len({backup["filename"] for backup in backups}) == 2


def test_restore_backup_rejected_when_server_is_running(tmp_path: Path) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "server.properties").write_text("motd=old\n", encoding="utf-8")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "test_backup.zip"
    with zipfile.ZipFile(backup_file, "w") as zf:
        zf.writestr("server.properties", "motd=restored\n")

    config = SimpleNamespace(name="TestServer", path=str(server_dir), backup_path=str(backup_dir), jvm_args=[])
    crud = SimpleNamespace(
        snapshot=lambda: ServerConfigRegistrySnapshot("test-revision", (("TestServer", config),)),
        servers_root=server_dir.parent,
        operation_lock=threading.RLock(),
    )
    running_runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=True),
        begin_maintenance=lambda _name: True,
        end_maintenance=lambda _name: None,
    )
    manager = backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, running_runtime))

    assert manager.restore_backup("TestServer", str(backup_file)) is False
    assert (server_dir / "server.properties").read_text(encoding="utf-8") == "motd=old\n"


def test_restore_backup_succeeds_when_server_not_running(tmp_path: Path) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "server.properties").write_text("motd=old\n", encoding="utf-8")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "test_backup.zip"
    with zipfile.ZipFile(backup_file, "w") as zf:
        zf.writestr("server.properties", "motd=restored\n")

    config = SimpleNamespace(name="TestServer", path=str(server_dir), backup_path=str(backup_dir), jvm_args=[])
    crud = SimpleNamespace(
        snapshot=lambda: ServerConfigRegistrySnapshot("test-revision", (("TestServer", config),)),
        servers_root=server_dir.parent,
        operation_lock=threading.RLock(),
    )
    stopped_runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        begin_maintenance=lambda _name: True,
        end_maintenance=lambda _name: None,
    )
    manager = backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, stopped_runtime))

    assert manager.restore_backup("TestServer", str(backup_file)) is True
    assert (server_dir / "server.properties").read_text(encoding="utf-8") == "motd=restored\n"


def test_restore_failure_leaves_live_server_unchanged(tmp_path: Path, monkeypatch) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    original = server_dir / "server.properties"
    original.write_text("motd=old\n", encoding="utf-8")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "TestServer_20260824135000000000-deadbeef.zip"
    with zipfile.ZipFile(backup_file, "w") as zf:
        zf.writestr("server.properties", "motd=restored\n")

    def fail_after_first_write(_backup_file, destination, *_args, **_kwargs) -> None:
        (destination / "server.properties").write_text("motd=partial\n", encoding="utf-8")
        raise OSError("simulated extraction failure")

    monkeypatch.setattr(backup_module, "safe_extract_zip", fail_after_first_write)
    config = SimpleNamespace(name="TestServer", path=str(server_dir), backup_path=str(backup_dir), jvm_args=[])
    crud = SimpleNamespace(
        snapshot=lambda: ServerConfigRegistrySnapshot("test-revision", (("TestServer", config),)),
        servers_root=server_dir.parent,
        operation_lock=threading.RLock(),
    )
    runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        begin_maintenance=lambda _name: True,
        end_maintenance=lambda _name: None,
    )
    manager = backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, runtime))

    assert manager.restore_backup("TestServer", str(backup_file)) is False
    assert original.read_text(encoding="utf-8") == "motd=old\n"
    assert backup_file.is_file()
    assert not list(tmp_path.glob(".server.restore-*"))


def test_restore_commit_failure_rolls_back_live_server(tmp_path: Path, monkeypatch) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    original = server_dir / "server.properties"
    original.write_text("motd=old\n", encoding="utf-8")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "TestServer_20260824135000000000-deadbeef.zip"
    with zipfile.ZipFile(backup_file, "w") as zf:
        zf.writestr("server.properties", "motd=restored\n")

    original_replace = Path.replace

    def fail_prepared_commit(path: Path, target: Path) -> Path:
        if path.name.startswith(".server.restore-") and not path.name.startswith(".server.restore-rollback-"):
            raise OSError("simulated commit failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_prepared_commit)
    config = SimpleNamespace(name="TestServer", path=str(server_dir), backup_path=str(backup_dir), jvm_args=[])
    crud = SimpleNamespace(
        snapshot=lambda: ServerConfigRegistrySnapshot("test-revision", (("TestServer", config),)),
        servers_root=server_dir.parent,
        operation_lock=threading.RLock(),
    )
    runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        begin_maintenance=lambda _name: True,
        end_maintenance=lambda _name: None,
    )
    manager = backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, runtime))

    assert manager.restore_backup("TestServer", str(backup_file)) is False
    assert original.read_text(encoding="utf-8") == "motd=old\n"
    assert backup_file.is_file()
    assert not list(tmp_path.glob(".server.restore-*"))


def test_restore_replaces_snapshot_and_preserves_excluded_directories(tmp_path: Path, monkeypatch) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "stale.txt").write_text("stale", encoding="utf-8")
    logs_dir = server_dir / "logs"
    logs_dir.mkdir()
    (logs_dir / "latest.log").write_text("keep", encoding="utf-8")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "TestServer_20260824135000000000-deadbeef.zip"
    with zipfile.ZipFile(backup_file, "w") as zf:
        zf.writestr("server.properties", "motd=restored\n")
        zf.writestr("logs/injected.log", "discard")

    config = SimpleNamespace(name="TestServer", path=str(server_dir), backup_path=str(backup_dir), jvm_args=[])
    crud = SimpleNamespace(
        snapshot=lambda: ServerConfigRegistrySnapshot("test-revision", (("TestServer", config),)),
        servers_root=server_dir.parent,
        operation_lock=threading.RLock(),
    )
    runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        begin_maintenance=lambda _name: True,
        end_maintenance=lambda _name: None,
    )
    manager = backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, runtime))
    errors: list[str] = []
    monkeypatch.setattr(backup_module.logger, "error", errors.append)

    assert manager.restore_backup("TestServer", str(backup_file)) is True
    assert (server_dir / "server.properties").read_text(encoding="utf-8") == "motd=restored\n"
    assert not (server_dir / "stale.txt").exists()
    assert (server_dir / "logs" / "latest.log").read_text(encoding="utf-8") == "keep"
    assert not (server_dir / "logs" / "injected.log").exists()
    assert backup_file.is_file()
    assert errors == []


def test_managed_backup_restore_keeps_hard_archive_limits(tmp_path: Path, monkeypatch) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "TestServer_20260824135000000000-deadbeef.zip"
    with zipfile.ZipFile(backup_file, "w") as zf:
        zf.writestr("server.properties", "motd=restored\n")
        zf.writestr("world/level.dat", b"world-data")
    captured: dict[str, Any] = {}

    def capture_policy(_backup_file, destination, *_args, **kwargs) -> None:
        captured.update(kwargs)
        (destination / "server.properties").write_text("motd=restored\n", encoding="utf-8")

    monkeypatch.setattr(backup_module, "safe_extract_zip", capture_policy)
    config = SimpleNamespace(name="TestServer", path=str(server_dir), backup_path=str(backup_dir), jvm_args=[])
    crud = SimpleNamespace(
        snapshot=lambda: ServerConfigRegistrySnapshot("test-revision", (("TestServer", config),)),
        servers_root=server_dir.parent,
        operation_lock=threading.RLock(),
    )
    runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        begin_maintenance=lambda _name: True,
        end_maintenance=lambda _name: None,
    )
    manager = backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, runtime))

    assert manager.restore_backup("TestServer", str(backup_file)) is True
    assert callable(captured["progress_callback"])
    assert captured["max_members"] == backup_module._BACKUP_MAX_MEMBERS
    assert captured["max_total_uncompressed_bytes"] == backup_module._BACKUP_MAX_TOTAL_BYTES
    assert captured["max_member_uncompressed_bytes"] == backup_module._BACKUP_MAX_MEMBER_BYTES
    assert captured["max_compression_ratio"] == backup_module._BACKUP_MAX_COMPRESSION_RATIO


def test_managed_backup_name_does_not_bypass_hard_total_limit(tmp_path: Path, monkeypatch) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    original = server_dir / "server.properties"
    original.write_text("motd=old\n", encoding="utf-8")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "TestServer_20260824135000000000-deadbeef.zip"
    with zipfile.ZipFile(backup_file, "w") as zf:
        zf.writestr("server.properties", "motd=restored\n")

    config = SimpleNamespace(name="TestServer", path=str(server_dir), backup_path=str(backup_dir), jvm_args=[])
    crud = SimpleNamespace(
        snapshot=lambda: ServerConfigRegistrySnapshot("test-revision", (("TestServer", config),)),
        servers_root=server_dir.parent,
        operation_lock=threading.RLock(),
    )
    runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        begin_maintenance=lambda _name: True,
        end_maintenance=lambda _name: None,
    )
    manager = backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, runtime))
    monkeypatch.setattr(
        manager,
        "_archive_declared_sizes",
        lambda _path: (backup_module._BACKUP_MAX_TOTAL_BYTES + 1, 1, 1),
    )
    monkeypatch.setattr(
        backup_module,
        "safe_extract_zip",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不應解壓超限備份")),
    )

    assert manager.restore_backup("TestServer", str(backup_file)) is False
    assert original.read_text(encoding="utf-8") == "motd=old\n"


def test_backup_dir_rejects_servers_root(tmp_path: Path) -> None:
    """
    驗證外部備份路徑若設為 servers_root 會被安全拒絕
    """
    servers_root = tmp_path / "servers"
    servers_root.mkdir()
    server_dir = servers_root / "TestServer"
    server_dir.mkdir()
    (server_dir / "server.properties").write_text("motd=test\n", encoding="utf-8")

    config_root = SimpleNamespace(name="TestServer", path=str(server_dir), backup_path=str(servers_root), jvm_args=[])
    crud_root = SimpleNamespace(
        snapshot=lambda: ServerConfigRegistrySnapshot("test-revision", (("TestServer", config_root),)),
        servers_root=servers_root,
        operation_lock=threading.RLock(),
    )
    runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        begin_maintenance=lambda _name: True,
        end_maintenance=lambda _name: None,
    )
    manager = backup_module.ServerBackupManager(cast(Any, crud_root), server_runtime=cast(Any, runtime))

    with pytest.raises(OSError, match="備份目錄不得為伺服器根目錄"):
        manager._get_backup_dir(cast(Any, config_root))
    assert manager.backup_server("TestServer") is False


def test_restore_uses_backup_archive_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "server.properties").write_text("motd=old\n", encoding="utf-8")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "test_backup.zip"
    with zipfile.ZipFile(backup_file, "w") as zf:
        zf.writestr("server.properties", "motd=restored\n")

    config = SimpleNamespace(name="TestServer", path=str(server_dir), backup_path=str(backup_dir), jvm_args=[])
    crud = SimpleNamespace(
        snapshot=lambda: ServerConfigRegistrySnapshot("test-revision", (("TestServer", config),)),
        servers_root=server_dir.parent,
        operation_lock=threading.RLock(),
    )
    runtime = SimpleNamespace(
        observe=lambda _name: SimpleNamespace(is_running=False),
        begin_maintenance=lambda _name: True,
        end_maintenance=lambda _name: None,
    )
    manager = backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, runtime))
    archive_limits: list[int | None] = []
    extract_limits: list[int | None] = []
    original_open = backup_module.open_bounded_zip
    original_extract = backup_module.safe_extract_zip

    def _open(*args: Any, **kwargs: Any) -> Any:
        archive_limits.append(kwargs.get("max_archive_bytes"))
        return original_open(*args, **kwargs)

    def _extract(*args: Any, **kwargs: Any) -> None:
        extract_limits.append(kwargs.get("max_archive_bytes"))
        original_extract(*args, **kwargs)

    monkeypatch.setattr(backup_module, "open_bounded_zip", _open)
    monkeypatch.setattr(backup_module, "safe_extract_zip", _extract)

    assert manager.restore_backup("TestServer", str(backup_file)) is True
    assert archive_limits == [backup_module._BACKUP_MAX_TOTAL_BYTES]
    assert extract_limits == [backup_module._BACKUP_MAX_TOTAL_BYTES]
