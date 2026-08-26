from __future__ import annotations

from pathlib import Path

import pytest

import src.utils.server_utils.server_runtime_utils as runtime_utils_module
from src.core import ServerCRUD, ServerImportService, ServerInspector
from src.models import ServerConfig, ServerInspectionIntent
from src.utils import JvmOptionPolicy, ServerCommands


def test_jvm_policy_recommends_g1gc_for_memory_above_4gb() -> None:
    args = JvmOptionPolicy.recommend_gc_args(memory_max_mb=4097)
    assert "-XX:+UseG1GC" in args
    assert "-XX:+ParallelRefProcEnabled" in args


def test_jvm_policy_recommends_zgc_for_java_21() -> None:
    args = JvmOptionPolicy.recommend_gc_args(
        memory_max_mb=2048,
        java_major=21,
    )
    assert "-XX:+UseZGC" in args
    assert "-XX:+ZGenerational" in args


def test_jvm_policy_keeps_existing_gc_option() -> None:
    assert (
        JvmOptionPolicy.recommend_gc_args(
            memory_max_mb=8192,
            java_major=21,
            existing_args=["-XX:+UseShenandoahGC"],
        )
        == []
    )


def test_build_java_command_includes_recommended_gc(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    server_jar = tmp_path / "server.jar"
    server_jar.write_bytes(b"jar")
    config = ServerConfig(
        name="alpha",
        minecraft_version="1.21.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=8192,
        path=str(tmp_path),
    )

    monkeypatch.setattr(
        runtime_utils_module.JavaUtils, "get_best_java_path", staticmethod(lambda *_args, **_kwargs: None)
    )

    command = ServerCommands.build_java_command(config, return_list=True)

    assert command[:2] == ["java", "-XX:+UseG1GC"]
    assert "-Xmx8192M" in command


def test_build_java_command_uses_version_specific_full_java_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    server_jar = tmp_path / "server.jar"
    server_jar.write_bytes(b"jar")
    javaw = tmp_path / "jdk 21" / "bin" / "javaw.exe"
    javaw.parent.mkdir(parents=True)
    javaw.write_bytes(b"")
    calls: list[tuple[str, int | None, bool]] = []
    config = ServerConfig(
        name="alpha",
        minecraft_version="1.21.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(tmp_path),
    )

    def _get_best_java_path(mc_version: str, required_major=None, ask_download=True, **_kwargs) -> str:
        calls.append((mc_version, required_major, ask_download))
        return str(javaw)

    monkeypatch.setattr(runtime_utils_module.JavaUtils, "get_best_java_path", staticmethod(_get_best_java_path))

    command = ServerCommands.build_java_command(config, return_list=True)

    assert command[0] == str(javaw.with_name("java.exe"))
    assert calls == [("1.21.1", None, False)]


def test_build_java_command_uses_args_file_for_neoforge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = ServerConfig(
        name="neo",
        minecraft_version="1.21.1",
        loader_type="neoforge",
        loader_version="26.1.2.36-beta",
        memory_min_mb=1024,
        memory_max_mb=2048,
        path=str(tmp_path),
    )

    monkeypatch.setattr(
        runtime_utils_module.JavaUtils, "get_best_java_path", staticmethod(lambda *_args, **_kwargs: None)
    )
    target = "@libraries/net/neoforged/neoforge/26.1.2.36-beta/win_args.txt"
    command = ServerCommands.build_java_command(config, return_list=True, launch_target=target)

    assert command[0] == "java"
    assert "@libraries/net/neoforged/neoforge/26.1.2.36-beta/win_args.txt" in command
    assert command[-1] == "nogui"


def test_repair_startup_script_rewrites_bare_java_to_full_versioned_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script_path = tmp_path / "start.bat"
    script_path.write_text(
        "@echo off\njava -Xmx2G -jar server.jar\ncall java @user_jvm_args.txt %*\necho java -jar server.jar\n",
        encoding="utf-8",
    )
    javaw = tmp_path / "jdk 21" / "bin" / "javaw.exe"
    javaw.parent.mkdir(parents=True)
    javaw.write_bytes(b"")
    config = ServerConfig(
        name="alpha",
        minecraft_version="1.21.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(tmp_path),
    )
    monkeypatch.setattr(
        runtime_utils_module.JavaUtils,
        "get_best_java_path",
        staticmethod(lambda *_args, **_kwargs: str(javaw)),
    )

    assert ServerCommands.repair_startup_script_java_command(script_path, config) is True

    repaired = script_path.read_text(encoding="utf-8-sig")
    quoted_java = f'"{javaw.with_name("java.exe")}"'
    assert f"{quoted_java} -Xmx2G -jar server.jar" in repaired
    assert f"call {quoted_java} @user_jvm_args.txt %*" in repaired
    assert "echo java -jar server.jar" in repaired


def test_repair_startup_script_removes_bom_from_already_versioned_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    javaw = tmp_path / "jdk 21" / "bin" / "javaw.exe"
    javaw.parent.mkdir(parents=True)
    javaw.write_bytes(b"")
    script_path = tmp_path / "start.bat"
    script_path.write_text(f'\ufeff"{javaw.with_name("java.exe")}" -Xmx20G -jar server.jar\n', encoding="utf-8")
    config = ServerConfig(
        name="alpha",
        minecraft_version="1.21.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=20480,
        path=str(tmp_path),
    )
    monkeypatch.setattr(
        runtime_utils_module.JavaUtils,
        "get_best_java_path",
        staticmethod(lambda *_args, **_kwargs: str(javaw)),
    )

    assert ServerCommands.repair_startup_script_java_command(script_path, config) is True

    repaired_bytes = script_path.read_bytes()
    assert not repaired_bytes.startswith(b"\xef\xbb\xbf")
    assert repaired_bytes.decode("utf-8").startswith(f'"{javaw.with_name("java.exe")}"')


def test_extract_startup_script_command_reads_first_java_command_and_memory(tmp_path: Path) -> None:
    script_path = tmp_path / "start.bat"
    script_path.write_text(
        "echo java -jar ignored.jar\ncall java -XX:+UseG1GC --add-opens java.base/java.lang=ALL-UNNAMED -Xms512M -Xmx4G -jar server.jar\n",
        encoding="utf-8",
    )

    startup_command = ServerCommands.extract_startup_script_command(script_path)

    assert startup_command.has_java_command is True
    assert startup_command.command_line == (
        "call java -XX:+UseG1GC --add-opens java.base/java.lang=ALL-UNNAMED -Xms512M -Xmx4G -jar server.jar"
    )
    assert startup_command.memory_min_mb == 512
    assert startup_command.memory_max_mb == 4096


def test_replace_startup_command_java_path_replaces_existing_java_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old_java = tmp_path / "old jdk" / "bin" / "java.exe"
    new_javaw = tmp_path / "new jdk" / "bin" / "javaw.exe"
    old_java.parent.mkdir(parents=True)
    new_javaw.parent.mkdir(parents=True)
    old_java.write_bytes(b"")
    new_javaw.write_bytes(b"")
    config = ServerConfig(
        name="imported",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(tmp_path),
    )
    monkeypatch.setattr(
        runtime_utils_module.JavaUtils,
        "get_best_java_path",
        staticmethod(lambda *_args, **_kwargs: str(new_javaw)),
    )

    migrated = ServerCommands.replace_startup_command_java_path(f'"{old_java}" -Xmx2G -jar server.jar', config)

    assert migrated == f'"{new_javaw.with_name("java.exe")}" -Xmx2G -jar server.jar'


def test_import_service_builds_managed_startup_script_and_removes_old_script(tmp_path: Path) -> None:
    servers_root = tmp_path / "servers"
    server_path = servers_root / "imported"
    server_path.mkdir(parents=True)
    (server_path / "server.jar").write_bytes(b"jar")
    script_path = server_path / "start.bat"
    script_path.write_text("java -XX:+UseG1GC -Dfoo=bar -Xms1G -Xmx20G -jar server.jar\n", encoding="utf-8")
    manager = ServerCRUD(str(servers_root))
    service = ServerImportService(manager)
    inspection = service.inspect(server_path, "imported")
    result = service.execute(inspection)

    assert result.completed is True
    assert result.config is not None
    assert not script_path.exists()
    assert result.config.memory_min_mb == 1024
    assert result.config.memory_max_mb == 20480
    assert result.config.jvm_args == []
    generated_script = server_path / "start_server.bat"
    generated_content = generated_script.read_text(encoding="utf-8-sig")
    assert generated_script.exists()
    assert 'cd /d "%~dp0"' in generated_content
    assert "echo Minecraft" not in generated_content
    assert "正在啟動" not in generated_content
    assert "模組載入器" not in generated_content
    assert "記憶體配置" not in generated_content
    assert "java -XX:+UseG1GC -Dfoo=bar -Xms1G -Xmx20G -jar server.jar nogui" in generated_content


def test_find_startup_script_prefers_generated_script_over_imported_leftover(tmp_path: Path) -> None:
    (tmp_path / "start.bat").write_text("java -Xmx20G -jar fabric-server-launch.jar\n", encoding="utf-8")
    (tmp_path / "start_server.bat").write_text("java -Xmx2G -jar server.jar\n", encoding="utf-8")

    inspection = ServerInspector().inspect(tmp_path, ServerInspectionIntent("launch"))

    assert inspection.launch_target.value == "start_server.bat"


def test_import_inspection_reads_memory_without_rewriting_scripts(tmp_path: Path) -> None:
    servers_root = tmp_path / "servers"
    source = tmp_path / "source"
    source.mkdir()
    (source / "server.jar").write_bytes(b"jar")
    script = source / "start.bat"
    original = "java -Xmx20G -jar server.jar\npause\n"
    script.write_text(original, encoding="utf-8")

    inspection = ServerImportService(ServerCRUD(str(servers_root))).inspect(source, "imported")

    assert inspection.server.memory_max_mb == 20480
    assert script.read_text(encoding="utf-8") == original


def test_create_launch_script_rewrites_existing_bom_script_without_bom(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    server_path = tmp_path / "server"
    server_path.mkdir()
    (server_path / "server.jar").write_bytes(b"jar")
    config = ServerConfig(
        name="server",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(server_path),
    )
    monkeypatch.setattr(
        runtime_utils_module.JavaUtils,
        "get_best_java_path",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    manager = ServerCRUD(str(tmp_path))
    script_path = server_path / "start_server.bat"

    manager.create_launch_script(config)
    script_content = script_path.read_text(encoding="utf-8")
    script_path.write_bytes(b"\xef\xbb\xbf" + script_content.encode("utf-8"))
    manager.create_launch_script(config)

    assert not script_path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_startup_command_parser_is_read_only(tmp_path: Path) -> None:
    script_path = tmp_path / "start_server.bat"
    script_path.write_text("@echo off\njava -Xmx2G -Xms1G -jar server.jar\npause\n", encoding="utf-8")

    original = script_path.read_bytes()
    command = ServerCommands.extract_startup_script_command(script_path)

    assert command.memory_max_mb == 2048
    assert command.memory_min_mb == 1024
    assert script_path.read_bytes() == original


def test_startup_command_parser_accepts_bom_without_rewriting(tmp_path: Path) -> None:
    script_path = tmp_path / "start.bat"
    script_path.write_text("\ufeffjava -Xmx20G -jar fabric-server-launch.jar\n", encoding="utf-8")
    original = script_path.read_bytes()
    command = ServerCommands.extract_startup_script_command(script_path)

    assert command.memory_max_mb == 20480
    assert script_path.read_bytes() == original
