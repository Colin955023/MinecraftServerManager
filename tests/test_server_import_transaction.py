from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

import src.core.server.server_import as server_import_module
from src.core import ServerConfigChangeSet, ServerCRUD, ServerImportService
from src.models import ServerConfig


def _write_server(path: Path, *, script: str = "java -Xms1G -Xmx2G -jar server.jar\n") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "server.jar").write_bytes(b"not-a-real-jar")
    (path / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    (path / "start.bat").write_text(script, encoding="utf-8")


def _register(manager: ServerCRUD, *configs: ServerConfig) -> None:
    baseline = manager.snapshot()
    result = manager.commit(ServerConfigChangeSet(upserts=tuple(configs)), expected_revision=baseline.revision)
    assert result.success, result.message


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
    assert result.config == manager.snapshot().get("managed")
    assert Path(result.config.path) == root / "managed"
    assert (root / "managed" / "start_server.bat").is_file()
    assert (source / "start.bat").read_bytes() == original_script
    assert not list(root.glob(".msm-import-*.staging"))


def test_external_directory_import_rejects_same_metadata_jar_swap(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "external"
    _write_server(source)
    original_jar = source / "server.jar"
    original_bytes = original_jar.read_bytes()
    original_stat = original_jar.stat()
    root = tmp_path / "servers"
    service = ServerImportService(ServerCRUD(str(root)))
    inspection = service.inspect(source, "managed")
    original_copy_dir = server_import_module.copy_dir

    def tampering_copy_dir(source_path: Path, destination: Path, **kwargs) -> bool:
        replacement = b"x" * len(original_bytes)
        original_jar.write_bytes(replacement)
        os.utime(original_jar, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        return original_copy_dir(source_path, destination, **kwargs)

    monkeypatch.setattr(server_import_module, "copy_dir", tampering_copy_dir)
    result = service.execute(inspection)

    assert result.completed is False
    assert result.status == "failed"
    assert not (root / "managed").exists()
    assert original_jar.read_bytes() == b"x" * len(original_bytes)


def test_external_directory_import_rejects_same_metadata_nested_jar_swap(tmp_path: Path) -> None:
    source = tmp_path / "external"
    _write_server(source)
    nested_jar = source / "libraries" / "example" / "library.jar"
    nested_jar.parent.mkdir(parents=True)
    original_bytes = b"trusted-library"
    nested_jar.write_bytes(original_bytes)
    original_stat = nested_jar.stat()
    root = tmp_path / "servers"
    service = ServerImportService(ServerCRUD(str(root)))
    inspection = service.inspect(source, "managed")

    nested_jar.write_bytes(b"x" * len(original_bytes))
    os.utime(nested_jar, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    result = service.execute(inspection)

    assert result.completed is False
    assert result.status == "failed"
    assert not (root / "managed").exists()


def test_import_replaces_unsafe_startup_command_with_managed_safe_command(tmp_path: Path) -> None:
    source = tmp_path / "external"
    _write_server(source, script="java -Xmx2G -jar server.jar & whoami\n")
    root = tmp_path / "servers"
    service = ServerImportService(ServerCRUD(str(root)))

    inspection = service.inspect(source, "managed")
    result = service.execute(inspection)

    assert result.completed
    generated = (root / "managed" / "start_server.bat").read_text(encoding="utf-8-sig")
    assert "whoami" not in generated
    assert "&" not in generated


def test_import_rejects_source_junction_before_resolving_target(tmp_path: Path, make_junction) -> None:
    source = tmp_path / "external"
    _write_server(source)
    root = tmp_path / "servers"
    root.mkdir()
    link = root / "linked-server"
    make_junction(link, source)
    service = ServerImportService(ServerCRUD(str(root)))

    with pytest.raises(ValueError, match="符號連結"):
        service.inspect(link, "linked-server")


def test_discover_skips_root_child_junction(tmp_path: Path, make_junction) -> None:
    source = tmp_path / "external"
    _write_server(source)
    root = tmp_path / "servers"
    root.mkdir()
    link = root / "linked-server"
    make_junction(link, source)
    service = ServerImportService(ServerCRUD(str(root)))

    report = service.discover()
    assert report.candidates == ()
    assert report.issues == ()


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


def test_zip_import_accepts_loader_script_without_root_jar(tmp_path: Path) -> None:
    archive = tmp_path / "neoforge.zip"
    with zipfile.ZipFile(archive, "w") as payload:
        payload.writestr("run.bat", "java @user_jvm_args.txt @libraries/net/neoforged/neoforge/21.1.0/win_args.txt\n")
        payload.writestr("user_jvm_args.txt", "-Xmx2G\n")
        payload.writestr("libraries/net/neoforged/neoforge/21.1.0/win_args.txt", "-cp libraries\n")
        payload.writestr("eula.txt", "eula=true\n")

    inspection = ServerImportService(ServerCRUD(str(tmp_path / "servers"))).inspect(archive, "neoforge")

    assert inspection.committable is True
    assert inspection.server.launch_target.kind == "script"


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

    _register(
        manager,
        ServerConfig(
            name="config_only",
            minecraft_version="1.20.1",
            loader_type="vanilla",
            loader_version="",
            memory_max_mb=1024,
            path=str(root / "config_only"),
        ),
    )
    insp_config = service.inspect(source, "config_only")
    assert insp_config.conflict_type == "config"
    assert insp_config.committable is False

    (root / "both_exist").mkdir(parents=True)
    _register(
        manager,
        ServerConfig(
            name="both_exist",
            minecraft_version="1.20.1",
            loader_type="vanilla",
            loader_version="",
            memory_max_mb=1024,
            path=str(root / "both_exist"),
        ),
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
    _register(manager, previous)
    service = ServerImportService(manager)
    inspection = service.inspect_registered("existing")
    monkeypatch.setattr(manager, "_persist_registry_locked", lambda *_args: False)

    result = service.execute(inspection)

    assert result.status == "failed"
    assert result.cleanup_complete is True
    assert manager.snapshot().get("existing") == previous
    assert managed.read_bytes() == b"original-managed-script"
    assert not (server_path / ".msm-server-import.json").exists()
    assert not (server_path / ".msm-start-server.backup").exists()


def test_in_place_migration_restores_properties_when_cancelled(tmp_path: Path) -> None:
    root = tmp_path / "servers"
    server_path = root / "existing"
    _write_server(server_path)
    props_file = server_path / "server.properties"
    original = "gamemode=1\n"
    props_file.write_text(original, encoding="utf-8")
    service = ServerImportService(ServerCRUD(str(root)))
    inspection = service.inspect(server_path, "existing")
    checks = iter((False, True))

    result = service.execute(inspection, apply_properties_migration=True, cancel_check=lambda: next(checks))

    assert result.status == "cancelled"
    assert result.cleanup_complete is True
    assert props_file.read_text(encoding="utf-8") == original
    assert not (server_path / "server.properties.backup").exists()


def test_batch_reports_completed_and_skipped_items_independently(tmp_path: Path) -> None:
    root = tmp_path / "servers"
    first = root / "first"
    second = root / "second"
    _write_server(first)
    _write_server(second)
    manager = ServerCRUD(str(root))
    _register(
        manager,
        ServerConfig(
            name="second",
            minecraft_version="unknown",
            loader_type="vanilla",
            loader_version="unknown",
            memory_max_mb=2048,
            path=str(second),
        ),
    )
    service = ServerImportService(manager)
    new_candidate = service.inspect(first, "first")
    conflict = service.inspect(second, "second")

    batch = service.execute_batch((new_candidate, conflict))

    assert batch.completed_count == 1
    assert batch.skipped_count == 1
    assert batch.failed_count == 0
    assert "first" in manager.snapshot()


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
    _register(manager, previous)
    service = ServerImportService(manager)
    inspection = service.inspect_registered("existing")
    (server_path / service._BACKUP_NAME).write_bytes(b"old-script")
    managed.write_bytes(b"new-script")
    service._write_marker(server_path, inspection, "prepared")

    ServerImportService(manager)

    assert managed.read_bytes() == b"old-script"
    assert not (server_path / service._MARKER_NAME).exists()
    assert not (server_path / service._BACKUP_NAME).exists()


def test_orphan_recovery_preserves_unregistered_in_place_server(tmp_path: Path) -> None:
    root = tmp_path / "servers"
    server_path = root / "existing"
    _write_server(server_path)
    manager = ServerCRUD(str(root))
    service = ServerImportService(manager)
    inspection = service.inspect(server_path, "existing")
    managed = server_path / "start_server.bat"
    service._write_marker(server_path, inspection, "script_preparing")
    managed.write_bytes(b"transaction-generated-script")

    ServerImportService(ServerCRUD(str(root)))

    assert (server_path / "server.jar").is_file()
    assert (server_path / "eula.txt").is_file()
    assert not managed.exists()
    assert not (server_path / service._MARKER_NAME).exists()


def test_orphan_recovery_removes_unregistered_moved_import(tmp_path: Path) -> None:
    root = tmp_path / "servers"
    source = tmp_path / "external"
    _write_server(source)
    manager = ServerCRUD(str(root))
    service = ServerImportService(manager)
    inspection = service.inspect(source, "copied")
    candidate = root / "copied"
    _write_server(candidate)
    service._write_marker(candidate, inspection, "moved")

    ServerImportService(ServerCRUD(str(root)))

    assert not candidate.exists()


def test_discover_counts_existing_registered_servers_separately_from_new_candidates(tmp_path: Path) -> None:
    root = tmp_path / "servers"
    root.mkdir()
    manager = ServerCRUD(str(root))

    managed_path = root / "managed"
    new_path = root / "new-server"
    _write_server(managed_path)
    _write_server(new_path)
    _register(
        manager,
        ServerConfig(
            name="managed",
            minecraft_version="1.20.1",
            loader_type="vanilla",
            loader_version="",
            memory_max_mb=2048,
            path=str(managed_path),
        ),
    )

    report = ServerImportService(manager).discover()

    assert report.managed_count == 1
    assert [candidate.name for candidate in report.candidates] == ["new-server"]
    assert report.issues == ()


def test_server_import_with_properties_migration(tmp_path: Path) -> None:
    source = tmp_path / "legacy_external"
    _write_server(source)
    props_file = source / "server.properties"
    props_file.write_text("gamemode=1\ntexture-pack=custom.zip\n", encoding="utf-8")

    root = tmp_path / "servers"
    manager = ServerCRUD(str(root))
    service = ServerImportService(manager)

    inspection = service.inspect(source, "migrated")
    result = service.execute(inspection, apply_properties_migration=True)

    assert result.completed is True
    target_server = root / "migrated"
    target_props = target_server / "server.properties"
    target_backup = target_server / "server.properties.backup"

    assert target_props.is_file()
    assert target_backup.is_file()

    content = target_props.read_text(encoding="utf-8")
    assert "gamemode=creative" in content
    assert "resource-pack=custom.zip" in content
    assert "texture-pack" not in content

    backup_content = target_backup.read_text(encoding="utf-8")
    assert "gamemode=1" in backup_content
    assert "texture-pack=custom.zip" in backup_content

    source_props = props_file.read_text(encoding="utf-8")
    assert "gamemode=1" in source_props


def test_redetect_preserves_configured_backup_path(tmp_path: Path) -> None:
    root = tmp_path / "servers"
    server_dir = root / "demo"
    _write_server(server_dir)
    manager = ServerCRUD(str(root))
    initial_config = ServerConfig(
        name="demo",
        path=str(server_dir),
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        memory_min_mb=1024,
        jvm_args=["-Dcustom=true"],
        backup_path=str(tmp_path / "custom_backups"),
    )
    _register(manager, initial_config)
    service = ServerImportService(manager)

    inspection = service.inspect(server_dir, "demo", mode="redetect")
    result = service.execute(inspection)

    assert result.completed is True
    assert result.config is not None
    assert result.config.backup_path == str(tmp_path / "custom_backups")
    assert result.config.jvm_args == ["-Dcustom=true"]
    committed = manager.snapshot().get("demo")
    assert committed is not None
    assert committed.backup_path == str(tmp_path / "custom_backups")
