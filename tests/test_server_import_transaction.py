from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from src.core import ServerCRUD, ServerImportService
from src.models import ServerConfig


def _write_server(path: Path, *, script: str = "java -Xms1G -Xmx2G -jar server.jar\n") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "server.jar").write_bytes(b"not-a-real-jar")
    (path / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    (path / "start.bat").write_text(script, encoding="utf-8")


def test_external_directory_import_is_managed_copy_and_source_is_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "external"
    _write_server(source)
    original_script = (source / "start.bat").read_bytes()
    root = tmp_path / "servers"
    manager = ServerCRUD(str(root))
    service = ServerImportService(manager)

    inspection = service.inspect(source, "managed")
    result = service.execute(inspection)

    assert inspection.source_kind == "directory"
    assert result.completed
    assert result.config is manager.servers["managed"]
    assert Path(result.config.path) == root / "managed"
    assert (root / "managed" / "start_server.bat").is_file()
    assert (source / "start.bat").read_bytes() == original_script
    assert not list(root.glob(".msm-import-*.staging"))


def test_zip_import_flattens_single_wrapper_without_modifying_archive(tmp_path: Path) -> None:
    archive = tmp_path / "wrapped.zip"
    with zipfile.ZipFile(archive, "w") as payload:
        payload.writestr("wrapper/fabric-server-mc.1.21.1-loader.0.16.0.jar", b"jar")
        payload.writestr("wrapper/eula.txt", "eula=true\n")
        payload.writestr("wrapper/start.bat", "java -Xms1G -Xmx4G -jar fabric-server-mc.1.21.1-loader.0.16.0.jar\n")
    original_archive = archive.read_bytes()
    root = tmp_path / "servers"
    service = ServerImportService(ServerCRUD(str(root)))

    inspection = service.inspect(archive, "zip-server")
    assert inspection.source_kind == "archive"
    assert inspection.server.loader_type == "fabric"
    assert inspection.server.minecraft_version == "1.21.1"
    assert inspection.server.loader_version == "0.16.0"
    assert inspection.server.memory_max_mb == 4096
    assert inspection.server.eula_state == "accepted"
    assert inspection.committable is True
    assert inspection.conflict_type == "none"

    result = service.execute(inspection)

    assert result.completed
    assert (root / "zip-server" / "fabric-server-mc.1.21.1-loader.0.16.0.jar").is_file()
    assert not (root / "zip-server" / "wrapper").exists()
    assert archive.read_bytes() == original_archive


def test_conflict_type_distinguishes_disk_config_and_both(tmp_path: Path) -> None:
    root = tmp_path / "servers"
    manager = ServerCRUD(str(root))
    service = ServerImportService(manager)

    source = tmp_path / "source"
    _write_server(source)

    (root / "disk_only").mkdir(parents=True)
    insp_disk = service.inspect(source, "disk_only")
    assert insp_disk.conflict_type == "disk"
    assert insp_disk.committable is False

    manager.servers["config_only"] = ServerConfig(
        name="config_only",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=1024,
        path=str(root / "non_existent_folder"),
    )
    insp_config = service.inspect(source, "config_only")
    assert insp_config.conflict_type == "config"
    assert insp_config.committable is False

    (root / "both_exist").mkdir(parents=True)
    manager.servers["both_exist"] = ServerConfig(
        name="both_exist",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=1024,
        path=str(root / "both_exist"),
    )
    insp_both = service.inspect(source, "both_exist")
    assert insp_both.conflict_type == "both"
    assert insp_both.committable is False

    insp_none = service.inspect(source, "clean_new")
    assert insp_none.conflict_type == "none"
    assert insp_none.committable is True


def test_import_cancellation_during_execution_cleans_staging(tmp_path: Path) -> None:
    source = tmp_path / "external"
    _write_server(source)
    root = tmp_path / "servers"
    service = ServerImportService(ServerCRUD(str(root)))
    inspection = service.inspect(source, "cancelled_import")

    result = service.execute(inspection, cancel_check=lambda: True)

    assert result.status == "cancelled"
    assert result.cleanup_complete is True
    assert not (root / "cancelled_import").exists()
    assert not list(root.glob(".msm-import-*.staging"))


@pytest.mark.parametrize("name", ["../escape", "child/name", "child\\name", "bad:name", "trailing."])
def test_import_rejects_unsafe_name_before_writing(tmp_path: Path, name: str) -> None:
    source = tmp_path / "source"
    _write_server(source)
    root = tmp_path / "servers"
    service = ServerImportService(ServerCRUD(str(root)))

    with pytest.raises(ValueError):
        service.inspect(source, name)

    assert list(root.iterdir()) == [root / "servers_config.json"]


def test_in_place_redetect_restores_config_and_managed_script_when_persistence_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "servers"
    server_path = root / "existing"
    _write_server(server_path, script="java -Xmx4G -jar server.jar\n")
    managed = server_path / "start_server.bat"
    managed.write_bytes(b"original-managed-script")
    manager = ServerCRUD(str(root))
    previous = ServerConfig(
        name="existing",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=1024,
        path=str(server_path),
    )
    manager.servers["existing"] = previous
    assert manager.write_servers_config()
    service = ServerImportService(manager)
    inspection = service.inspect_registered("existing")
    monkeypatch.setattr(manager, "write_servers_config", lambda: False)

    result = service.execute(inspection)

    assert result.status == "failed"
    assert result.cleanup_complete is False
    assert manager.servers["existing"] is previous
    assert managed.read_bytes() == b"original-managed-script"
    assert not (server_path / ".msm-server-import.json").exists()
    assert not (server_path / ".msm-start-server.backup").exists()


def test_batch_reports_completed_and_skipped_items_independently(tmp_path: Path) -> None:
    root = tmp_path / "servers"
    first = root / "first"
    second = root / "second"
    _write_server(first)
    _write_server(second)
    manager = ServerCRUD(str(root))
    manager.servers["second"] = ServerConfig(
        name="second",
        minecraft_version="unknown",
        loader_type="vanilla",
        loader_version="unknown",
        memory_max_mb=2048,
        path=str(second),
    )
    assert manager.write_servers_config()
    service = ServerImportService(manager)
    new_candidate = service.inspect(first, "first")
    conflict = service.inspect(second, "second")

    batch = service.execute_batch((new_candidate, conflict))

    assert batch.completed_count == 1
    assert batch.skipped_count == 1
    assert batch.failed_count == 0
    assert "first" in manager.servers


def test_orphan_recovery_restores_script_when_redetect_config_was_not_committed(tmp_path: Path) -> None:
    root = tmp_path / "servers"
    server_path = root / "existing"
    _write_server(server_path, script="java -Xmx4G -jar server.jar\n")
    managed = server_path / "start_server.bat"
    managed.write_bytes(b"old-script")
    manager = ServerCRUD(str(root))
    previous = ServerConfig(
        name="existing",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=1024,
        path=str(server_path),
    )
    manager.servers["existing"] = previous
    assert manager.write_servers_config()
    service = ServerImportService(manager)
    inspection = service.inspect_registered("existing")
    (server_path / service._BACKUP_NAME).write_bytes(b"old-script")
    managed.write_bytes(b"new-script")
    service._write_marker(server_path, inspection, "prepared")

    ServerImportService(manager)

    assert managed.read_bytes() == b"old-script"
    assert not (server_path / service._MARKER_NAME).exists()
    assert not (server_path / service._BACKUP_NAME).exists()
