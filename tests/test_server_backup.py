from __future__ import annotations

import datetime
import zipfile
from pathlib import Path
from types import SimpleNamespace

import src.core.server.server_backup as backup_module


class _FixedDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 8, 24, 13, 50, tzinfo=tz)


def _manager(server_dir: Path) -> backup_module.ServerBackupManager:
    crud = SimpleNamespace(servers={"TestServer": SimpleNamespace(path=str(server_dir))})
    return backup_module.ServerBackupManager(crud)


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

    backup_file = server_dir / "backups" / "TestServer_202608241350.zip"
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
