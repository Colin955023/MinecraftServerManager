"""
伺服器 CRUD 模組
處理伺服器的建立、刪除與匯入。
"""

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

from ...models import ServerConfig, ServerOperationResult
from ...utils import PathUtils, SystemUtils, get_logger, record_and_mark
from .. import ServerCommands, ServerDetectionUtils, ServerPropertiesHelper

if TYPE_CHECKING:
    from .server_repository import ServerRepository

logger = get_logger().bind(component="ServerCRUD")


class ServerCRUD:
    """處理伺服器的建立、匯入與刪除邏輯。"""

    def __init__(self, repository: ServerRepository):
        self.repository = repository

    def _success_result(self, message: str = "", *, server_name: str = "") -> ServerOperationResult:
        return ServerOperationResult(success=True, message=message, server_name=server_name)

    def _failure_result(self, title: str, message: str, *, server_name: str = "") -> ServerOperationResult:
        return ServerOperationResult(success=False, title=title, message=message, server_name=server_name)

    def create_server_result(
        self, config: ServerConfig, properties: dict[str, str] | None = None
    ) -> ServerOperationResult:
        """
        建立伺服器的結果。

        Args:
            config: 伺服器配置
            properties: 伺服器屬性

        Returns:
            ServerOperationResult: 建立結果
        """
        server_path: Path | None = None
        previous_config = self.repository.servers.get(config.name)
        added_server_entry = False
        created_server_dir = False
        try:
            server_path = (self.repository.servers_root / config.name).resolve()
            if not PathUtils.is_path_within(self.repository.servers_root, server_path, strict=False):
                raise ValueError(f"無效的伺服器名稱 (路徑遍歷偵測): {config.name}")
            if server_path.exists():
                raise FileExistsError(f"伺服器資料夾已存在: {server_path}")
            server_path.mkdir()
            created_server_dir = True
            config.path = str(server_path)
            need_detect = (
                not config.loader_type
                or config.loader_type == "unknown"
                or (not config.minecraft_version)
                or (config.minecraft_version == "unknown")
                or (
                    config.loader_type
                    and config.loader_type.lower() in ["forge", "fabric"]
                    and (not config.loader_version or config.loader_version == "unknown")
                )
            )
            if need_detect:
                try:
                    ServerDetectionUtils.detect_server_type(server_path, config)
                    if not config.loader_type or config.loader_type == "unknown":
                        raise Exception(
                            f"偵測失敗：loader_type 無法判斷，name={config.name}, path={config.path}, loader_type={config.loader_type}, minecraft_version={config.minecraft_version}, loader_version={config.loader_version}"
                        )
                    if not config.minecraft_version or config.minecraft_version == "unknown":
                        raise Exception(
                            f"偵測失敗：minecraft_version 無法判斷，name={config.name}, path={config.path}, loader_type={config.loader_type}, minecraft_version={config.minecraft_version}, loader_version={config.loader_version}"
                        )
                    if config.loader_type.lower() in ["forge", "fabric"] and (
                        not config.loader_version or config.loader_version == "unknown"
                    ):
                        raise Exception(
                            f"偵測失敗：loader_version 無法判斷，name={config.name}, path={config.path}, loader_type={config.loader_type}, minecraft_version={config.minecraft_version}, loader_version={config.loader_version}"
                        )
                except Exception as e:
                    logger.error(f"自動偵測伺服器類型失敗: {e}")
                    raise
            if not self._create_eula_file(server_path):
                raise RuntimeError(f"建立 EULA 檔案失敗: {server_path}")
            config.eula_accepted = True
            self._create_server_structure(Path(config.path), config.loader_type)
            properties_file = server_path / "server.properties"
            if properties is None:
                properties = self.repository.get_default_server_properties()
            properties = dict(properties)
            properties["motd"] = f"Minecraft 伺服器 - {config.name}"
            if not ServerPropertiesHelper.save_properties(properties_file, properties):
                raise RuntimeError(f"儲存 server.properties 失敗: {properties_file}")
            config.properties = properties
            if not self.create_launch_script(config):
                raise RuntimeError(f"建立啟動腳本失敗: {server_path}")
            self.repository.servers[config.name] = config
            added_server_entry = True
            if not self.repository.write_servers_config():
                raise RuntimeError(f"儲存伺服器設定失敗: {config.name}")
            return self._success_result(f"伺服器 {config.name} 已建立", server_name=config.name)
        except Exception as e:
            if added_server_entry:
                if previous_config is not None:
                    self.repository.servers[config.name] = previous_config
                else:
                    self.repository.servers.pop(config.name, None)
            try:
                if created_server_dir and server_path and server_path.exists():
                    PathUtils.delete_within(self.repository.servers_root, server_path)
            except Exception:
                logger.warning(f"建立失敗後清理伺服器資料夾失敗: {server_path}")
            try:
                killed = False
                if server_path and server_path.exists():
                    killed = SystemUtils.kill_java_processes_in_path(server_path)
                    if killed:
                        logger.warning(f"異常建立失敗，自動終止殘留 Java 進程於: {server_path}")
            except Exception as kill_exc:
                logger.error(f"自動終止殘留 Java 進程失敗: {kill_exc}")
            record_and_mark(
                e, marker_path=server_path, reason="建立伺服器失敗", details={"server": getattr(config, "name", None)}
            )
            return self._failure_result(
                "建立失敗",
                f"建立過程發生錯誤，已嘗試清理殘留 Java 進程。請檢查日誌與 .issues 目錄。\n錯誤: {e}",
                server_name=getattr(config, "name", ""),
            )

    def _create_eula_file(self, server_path: Path) -> bool:
        eula_content = "eula=true"
        return PathUtils.write_text_file(server_path / "eula.txt", eula_content)

    def _create_server_structure(self, path: Path, loader_type: str) -> None:
        if loader_type.lower() == "vanilla":
            directories = ["world", "logs"]
        elif loader_type.lower() in ["forge", "fabric"]:
            directories = ["world", "plugins", "mods", "config", "logs"]
        else:
            directories = ["world", "logs"]
            logger.warning(f"未知 loader_type: {loader_type}，使用預設目錄結構")
        for directory in directories:
            (path / directory).mkdir(exist_ok=True)

    def create_launch_script(self, config: ServerConfig, java_command_override: str | None = None) -> bool:
        """
        建立伺服器啟動腳本。

        Args:
            config: 伺服器配置
            java_command_override: 自訂 Java 命令

        Returns:
            bool: 是否成功建立
        """
        server_path = Path(config.path)
        if java_command_override:
            java_command_str = java_command_override.strip()
        else:
            java_cmd_list = ServerCommands.build_java_command(config, return_list=True)
            logger.debug(f"Java 命令列表: {java_cmd_list}")
            java_exe = java_cmd_list[0]
            if " " in java_exe and (not (java_exe.startswith('"') and java_exe.endswith('"'))):
                java_exe = f'"{java_exe}"'
            uses_args_file = len(java_cmd_list) >= 2 and java_cmd_list[1].startswith("@")
            if uses_args_file:
                args_spec = java_cmd_list[1]
                args_rel_path = args_spec[1:]
                args_path = server_path / args_rel_path
                if args_path.exists():
                    java_command_str = f"{java_exe} {args_spec} nogui"
                else:
                    logger.warning(f"參數檔案不存在: {args_path}")
                    java_command_str = f"{java_exe} {args_spec} nogui"
            else:
                cmd_parts = [java_exe]
                i = 1
                while i < len(java_cmd_list):
                    arg = java_cmd_list[i]
                    if arg == "-jar" and i + 1 < len(java_cmd_list):
                        cmd_parts.append(arg)
                        jar_spec = java_cmd_list[i + 1]
                        jar_path = server_path / jar_spec
                        if jar_path.exists():
                            cmd_parts.append(f'"{jar_path.resolve()}"')
                        else:
                            cmd_parts.append(f'"{jar_spec}"')
                        i += 2
                    else:
                        cmd_parts.append(arg)
                        i += 1
                java_command_str = " ".join(cmd_parts)
        bat_lines = [
            "@echo off",
            "chcp 65001 >nul",
            'cd /d "%~dp0"',
            "",
            java_command_str,
        ]
        bat_content = "\n".join(bat_lines)
        start_script_path = server_path / "start_server.bat"
        try:
            if start_script_path.exists():
                existing_bytes = start_script_path.read_bytes()
                existing_has_bom = existing_bytes.startswith(b"\xef\xbb\xbf")
                existing_content = existing_bytes.decode("utf-8-sig", errors="ignore")
                if existing_content == bat_content and not existing_has_bom:
                    logger.debug("啟動腳本內容未變更，跳過寫入")
                    return True
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(
                    e,
                    marker_path=start_script_path,
                    reason="compare_start_script_failed",
                    details={"server": getattr(config, "name", None)},
                )
            logger.debug(f"比較啟動腳本時發生錯誤 (將強制覆寫): {e}")
        return PathUtils.write_text_file(start_script_path, bat_content, encoding="utf-8", errors="replace")

    def delete_server_result(self, server_name: str) -> ServerOperationResult:
        """
        刪除伺服器的結果。

        Args:
            server_name: 伺服器名稱

        Returns:
            ServerOperationResult: 刪除結果
        """
        try:
            if server_name not in self.repository.servers:
                return self._failure_result("刪除失敗", f"找不到伺服器: {server_name}", server_name=server_name)
            config = self.repository.servers[server_name]
            server_path = Path(config.path).resolve(strict=False)
            if not PathUtils.is_path_within(self.repository.servers_root, server_path, strict=False):
                logger.error(f"拒絕刪除不在 servers_root 之下的路徑: {server_path}")
                return self._failure_result(
                    "刪除失敗",
                    f"拒絕刪除不在伺服器根目錄下的路徑: {server_path}",
                    server_name=server_name,
                )
            removed_config = self.repository.servers[server_name]
            del self.repository.servers[server_name]
            if not self.repository.write_servers_config():
                self.repository.servers[server_name] = removed_config
                return self._failure_result(
                    "刪除失敗", f"無法保存刪除後的伺服器配置: {server_name}", server_name=server_name
                )
            if not PathUtils.delete_within(self.repository.servers_root, server_path):
                self.repository.servers[server_name] = removed_config
                if not self.repository.write_servers_config():
                    logger.error(f"回滾刪除失敗時，無法恢復伺服器配置: {server_name}")
                return self._failure_result("刪除失敗", f"無法刪除伺服器資料夾: {server_path}", server_name=server_name)
            return self._success_result(f"伺服器 {server_name} 已刪除", server_name=server_name)
        except Exception as e:
            try:
                server_path = Path(getattr(self.repository.servers.get(server_name), "path", ""))
            except Exception:
                server_path = None
            record_and_mark(e, marker_path=server_path, reason="刪除伺服器失敗", details={"server": server_name})
            return self._failure_result("刪除失敗", f"無法刪除伺服器 {server_name}。錯誤: {e}", server_name=server_name)

    def _collect_imported_startup_scripts(self, server_path: Path) -> list[Path]:
        server_root = server_path.resolve(strict=False)
        managed_name = ServerCommands.MANAGED_STARTUP_SCRIPT_NAME.lower()
        scripts: list[Path] = []
        seen: set[Path] = set()

        def append_script(script_path: Path) -> None:
            resolved_path = script_path.resolve(strict=False)
            if resolved_path in seen or resolved_path.parent != server_root or not script_path.is_file():
                return
            scripts.append(script_path)
            seen.add(resolved_path)

        for script_name in ServerCommands.STARTUP_SCRIPT_CANDIDATES:
            if script_name.lower() == managed_name:
                continue
            append_script(server_path / script_name)

        for script_path in sorted(server_path.glob("*.bat")):
            if script_path.name.lower() == managed_name:
                continue
            resolved_path = script_path.resolve(strict=False)
            if resolved_path in seen:
                continue
            startup_command = ServerCommands.extract_startup_script_command(script_path)
            if startup_command.has_java_command:
                append_script(script_path)
        return scripts

    def _extract_imported_startup_command(self, config: ServerConfig, script_path: Path) -> str | None:
        startup_command = ServerCommands.extract_startup_script_command(script_path)
        if not startup_command.has_java_command:
            return None
        if startup_command.memory_max_mb is not None:
            config.memory_max_mb = startup_command.memory_max_mb
        if startup_command.memory_min_mb is not None:
            config.memory_min_mb = startup_command.memory_min_mb
        return ServerCommands.replace_startup_command_java_path(startup_command.command_line, config)

    def _delete_root_startup_script(self, server_path: Path, script_path: Path) -> bool:
        server_root = server_path.resolve(strict=False)
        resolved_path = script_path.resolve(strict=False)
        if resolved_path.parent != server_root or not script_path.is_file():
            return False
        script_path.unlink()
        return True

    def _prepare_imported_startup_scripts(self, config: ServerConfig) -> None:
        server_path = Path(config.path)
        managed_script = server_path / ServerCommands.MANAGED_STARTUP_SCRIPT_NAME
        try:
            imported_scripts = self._collect_imported_startup_scripts(server_path)
            setting_sources = imported_scripts or ([managed_script] if managed_script.is_file() else [])
            java_command_override = None
            command_source = ""
            for script_path in setting_sources:
                java_command_override = self._extract_imported_startup_command(config, script_path)
                if java_command_override:
                    command_source = script_path.name
                    break
            if command_source:
                logger.info(f"已從匯入啟動腳本保留啟動命令: {command_source}")

            removed_scripts: list[str] = []
            for script_path in [*imported_scripts, managed_script]:
                if not script_path.exists():
                    continue
                try:
                    if self._delete_root_startup_script(server_path, script_path):
                        removed_scripts.append(script_path.name)
                except Exception as exc:
                    logger.warning(f"無法刪除匯入啟動腳本 {script_path.name}: {exc}")
            if removed_scripts:
                logger.info("已移除匯入啟動腳本: " + ", ".join(removed_scripts))

            if not self.create_launch_script(config, java_command_override=java_command_override):
                raise RuntimeError(f"匯入伺服器啟動腳本建立失敗: {config.name}")
            logger.info(f"匯入伺服器已建立/更新標準啟動腳本 start_server.bat: {config.name}")
        except Exception as exc:
            logger.warning(f"匯入伺服器啟動腳本整理失敗，保留原始檔案: {exc}")
            raise

    def add_server(self, config: ServerConfig) -> bool:
        """
        將伺服器配置新增至管理器，並嘗試建立標準啟動腳本。

        Args:
            config: 伺服器配置

        Returns:
            bool: 是否成功添加
        """
        previous_config = self.repository.servers.get(config.name)
        try:
            self._prepare_imported_startup_scripts(config)
            self.repository.servers[config.name] = config
            if not self.repository.write_servers_config():
                raise RuntimeError(f"保存伺服器配置失敗: {config.name}")
            return True
        except Exception as e:
            if previous_config is not None:
                self.repository.servers[config.name] = previous_config
            else:
                self.repository.servers.pop(config.name, None)
            logger.exception(f"添加伺服器失敗: {e}")
            return False
