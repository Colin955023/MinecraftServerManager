from __future__ import annotations

import datetime
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import src.core.server.server_backup as backup_module


class _FixedDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 8, 24, 13, 50, tzinfo=tz)


def _manager(server_dir: Path) -> backup_module.ServerBackupManager:
    crud = SimpleNamespace(servers={"TestServer": SimpleNamespace(path=str(server_dir))})
    runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=False))
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

    backup_files = list((server_dir / "backups").glob("TestServer_*.zip"))
    assert len(backup_files) == 1
    backup_file = backup_files[0]
    assert backup_file.is_file()
    assert not list((server_dir / "backups").glob("*.tmp"))

    with zipfile.ZipFile(backup_file) as archive:
        assert set(archive.namelist()) == {"server.properties", "world/level.dat"}


def test_backup_failure_keeps_existing_final_backup_and_removes_temp_file(tmp_path, monkeypatch) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "server.properties").write_text("motd=test\n", encoding="utf-8")
    backup_dir = server_dir / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "TestServer_202608241350.zip"
    backup_file.write_bytes(b"existing-backup")

    monkeypatch.setattr(backup_module.datetime, "datetime", _FixedDateTime)

    def fail_write(self, filename, arcname=None, compress_type=None, compresslevel=None):
        _ = filename, arcname, compress_type, compresslevel, self
        raise OSError("simulated source read failure")

    monkeypatch.setattr(backup_module.zipfile.ZipFile, "write", fail_write)

    manager = _manager(server_dir)
    assert manager.backup_server("TestServer") is False
    assert backup_file.read_bytes() == b"existing-backup"
    assert not list(backup_dir.glob("*.tmp"))


def test_backup_rejected_when_server_is_running(tmp_path: Path) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "server.properties").write_text("motd=test\n", encoding="utf-8")
    crud = SimpleNamespace(servers={"TestServer": SimpleNamespace(path=str(server_dir))})
    runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=True))
    manager = backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, runtime))

    assert manager.backup_server("TestServer") is False
    assert not (server_dir / "backups").exists()


def test_backup_names_are_unique_and_listed_for_literal_server_name(tmp_path: Path, monkeypatch) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "server.properties").write_text("motd=test\n", encoding="utf-8")
    server_name = "[Forge] 1.21"
    crud = SimpleNamespace(servers={server_name: SimpleNamespace(name=server_name, path=str(server_dir))})
    runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=False))
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
    backup_dir = server_dir / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "test_backup.zip"
    with zipfile.ZipFile(backup_file, "w") as zf:
        zf.writestr("server.properties", "motd=restored\n")

    crud = SimpleNamespace(servers={"TestServer": SimpleNamespace(path=str(server_dir))})
    running_runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=True))
    manager = backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, running_runtime))

    assert manager.restore_backup("TestServer", str(backup_file)) is False
    assert (server_dir / "server.properties").read_text(encoding="utf-8") == "motd=old\n"


def test_restore_backup_succeeds_when_server_not_running(tmp_path: Path) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "server.properties").write_text("motd=old\n", encoding="utf-8")
    backup_dir = server_dir / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "test_backup.zip"
    with zipfile.ZipFile(backup_file, "w") as zf:
        zf.writestr("server.properties", "motd=restored\n")

    crud = SimpleNamespace(servers={"TestServer": SimpleNamespace(path=str(server_dir))})
    stopped_runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=False))
    manager = backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, stopped_runtime))

    assert manager.restore_backup("TestServer", str(backup_file)) is True
    assert (server_dir / "server.properties").read_text(encoding="utf-8") == "motd=restored\n"


def test_restore_failure_leaves_live_server_unchanged(tmp_path: Path, monkeypatch) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    original = server_dir / "server.properties"
    original.write_text("motd=old\n", encoding="utf-8")
    backup_dir = server_dir / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "TestServer_20260824135000000000-deadbeef.zip"
    with zipfile.ZipFile(backup_file, "w") as zf:
        zf.writestr("server.properties", "motd=restored\n")

    def fail_after_first_write(_backup_file, destination, *_args, **_kwargs) -> None:
        (destination / "server.properties").write_text("motd=partial\n", encoding="utf-8")
        raise OSError("simulated extraction failure")

    monkeypatch.setattr(backup_module, "safe_extract_zip", fail_after_first_write)
    crud = SimpleNamespace(servers={"TestServer": SimpleNamespace(name="TestServer", path=str(server_dir))})
    runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=False))
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
    backup_dir = server_dir / "backups"
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
    crud = SimpleNamespace(servers={"TestServer": SimpleNamespace(name="TestServer", path=str(server_dir))})
    runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=False))
    manager = backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, runtime))

    assert manager.restore_backup("TestServer", str(backup_file)) is False
    assert original.read_text(encoding="utf-8") == "motd=old\n"
    assert backup_file.is_file()
    assert not list(tmp_path.glob(".server.restore-*"))


def test_restore_replaces_snapshot_and_preserves_excluded_directories(tmp_path: Path) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    (server_dir / "stale.txt").write_text("stale", encoding="utf-8")
    logs_dir = server_dir / "logs"
    logs_dir.mkdir()
    (logs_dir / "latest.log").write_text("keep", encoding="utf-8")
    backup_dir = server_dir / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "TestServer_20260824135000000000-deadbeef.zip"
    with zipfile.ZipFile(backup_file, "w") as zf:
        zf.writestr("server.properties", "motd=restored\n")
        zf.writestr("logs/injected.log", "discard")

    crud = SimpleNamespace(servers={"TestServer": SimpleNamespace(name="TestServer", path=str(server_dir))})
    runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=False))
    manager = backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, runtime))

    assert manager.restore_backup("TestServer", str(backup_file)) is True
    assert (server_dir / "server.properties").read_text(encoding="utf-8") == "motd=restored\n"
    assert not (server_dir / "stale.txt").exists()
    assert (server_dir / "logs" / "latest.log").read_text(encoding="utf-8") == "keep"
    assert not (server_dir / "logs" / "injected.log").exists()
    assert backup_file.is_file()


def test_managed_backup_restore_uses_managed_archive_policy(tmp_path: Path, monkeypatch) -> None:
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    backup_dir = server_dir / "backups"
    backup_dir.mkdir()
    backup_file = backup_dir / "TestServer_20260824135000000000-deadbeef.zip"
    with zipfile.ZipFile(backup_file, "w") as zf:
        zf.writestr("server.properties", "motd=restored\n")
    captured: dict[str, Any] = {}

    def capture_policy(_backup_file, destination, *_args, **kwargs) -> None:
        captured.update(kwargs)
        (destination / "server.properties").write_text("motd=restored\n", encoding="utf-8")

    monkeypatch.setattr(backup_module, "safe_extract_zip", capture_policy)
    crud = SimpleNamespace(servers={"TestServer": SimpleNamespace(name="TestServer", path=str(server_dir))})
    runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=False))
    manager = backup_module.ServerBackupManager(cast(Any, crud), server_runtime=cast(Any, runtime))

    assert manager.restore_backup("TestServer", str(backup_file)) is True
    with zipfile.ZipFile(backup_file, "r") as archive:
        required_bytes = sum(max(0, int(member.file_size)) for member in archive.infolist())
    assert captured["max_total_uncompressed_bytes"] == required_bytes
    assert captured["max_member_uncompressed_bytes"] == required_bytes
    assert "max_compression_ratio" not in captured
