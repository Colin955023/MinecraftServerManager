"""
伺服器管理器

負責建立、管理與配置 Minecraft 伺服器。
"""

import contextlib
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, ClassVar

from ...models import ServerConfig, ServerOperationResult
from ...utils import (
    PathUtils,
    ServerCommands,
    ServerDetectionUtils,
    ServerPropertiesHelper,
    SystemUtils,
    atomic_write_json,
    get_logger,
    record_and_mark,
)

logger = get_logger().bind(component="ServerManager")


class ServerCRUD:
    """負責建立、管理和配置 Minecraft 伺服器"""

    _shared_servers: ClassVar[dict[str, dict[str, ServerConfig]]] = {}

    STARTUP_CHECK_DELAY = 0.1
    STOP_CHECK_INTERVAL = 0.1
    STOP_TIMEOUT_SECONDS = 5
    OUTPUT_QUEUE_MAX_SIZE = 1000

    def __init__(self, servers_root: str | None = None):
        if not servers_root:
            raise ValueError("ServerManager 必須指定 servers_root 路徑，且不可為空。請於 UI 層先處理。")
        self.servers_root = Path(servers_root).resolve()
        self.servers_root.mkdir(parents=True, exist_ok=True)
        self.config_file = self.servers_root / "servers_config.json"
        # 若有其他 ServerCRUD 已針對相同 servers_root 建立過，重用其 servers 字典
        key = str(self.servers_root)
        if key in ServerCRUD._shared_servers:
            self.servers = ServerCRUD._shared_servers[key]
        else:
            self.servers = {}
            ServerCRUD._shared_servers[key] = self.servers
        self.running_servers: dict[str, Any] = {}
        self._properties_cache: dict[str, Any] = {}
        self._config_lock = threading.Lock()
        self.load_servers_config()
        if not self.config_file.exists():
            self.write_servers_config()

    @staticmethod
    def _success_result(message: str = "", *, server_name: str = "") -> ServerOperationResult:
        """建立成功結果。"""
        return ServerOperationResult(success=True, message=message, server_name=server_name)

    @staticmethod
    def _failure_result(title: str, message: str, *, server_name: str = "") -> ServerOperationResult:
        """建立失敗結果。"""
        return ServerOperationResult(success=False, title=title, message=message, server_name=server_name)

    def create_server_result(
        self, config: ServerConfig, properties: dict[str, str] | None = None
    ) -> ServerOperationResult:
        """
        建立新伺服器並初始化設定。

        Args:
            config: 要建立的伺服器設定。
            properties: 要寫入 server.properties 的初始屬性。

        Returns:
            建立流程結果，供 UI 或呼叫端決定後續呈現。
        """
        server_path: Path | None = None
        previous_config = self.servers.get(config.name)
        added_server_entry = False
        created_server_dir = False
        try:
            server_path = (self.servers_root / config.name).resolve()
            if not PathUtils.is_path_within(self.servers_root, server_path, strict=False):
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
                properties = self.get_default_server_properties()
            properties = dict(properties)
            properties["motd"] = f"Minecraft 伺服器 - {config.name}"
            if not ServerPropertiesHelper.save_properties(properties_file, properties):
                raise RuntimeError(f"儲存 server.properties 失敗: {properties_file}")
            config.properties = properties
            if not self.create_launch_script(config):
                raise RuntimeError(f"建立啟動腳本失敗: {server_path}")
            self.servers[config.name] = config
            added_server_entry = True
            if not self.write_servers_config():
                raise RuntimeError(f"儲存伺服器設定失敗: {config.name}")
            return self._success_result(f"伺服器 {config.name} 已建立", server_name=config.name)
        except Exception as e:
            if added_server_entry:
                if previous_config is not None:
                    self.servers[config.name] = previous_config
                else:
                    self.servers.pop(config.name, None)
            try:
                if created_server_dir and server_path and server_path.exists():
                    PathUtils.delete_within(self.servers_root, server_path)
            except Exception:
                logger.warning(f"建立失敗後清理伺服器資料夾失敗: {server_path}")
            # 嘗試終止殘留 Java 進程
            try:
                killed = False
                if server_path and server_path.exists():
                    # 掃描該資料夾下的 java 進程
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

    def create_server(self, config: ServerConfig, properties: dict[str, str] | None = None) -> bool:
        """
        建立新伺服器並初始化設定。

        Args:
            config: 要建立的伺服器設定。
            properties: 建立後要額外寫入的 `server.properties` 內容。

        Returns:
            建立成功時回傳 True，否則回傳 False。
        """

        return self.create_server_result(config, properties).success

    def _create_eula_file(self, server_path: Path) -> bool:
        """建立並同意 EULA 檔案。"""
        eula_content = "eula=true"
        return PathUtils.write_text_file(server_path / "eula.txt", eula_content)

    def _create_server_structure(self, path: Path, loader_type: str) -> None:
        """建立伺服器檔案結構"""
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
            config: 伺服器設定與啟動參數來源。
            java_command_override: 匯入既有伺服器時保留的原始 Java 啟動命令。

        Returns:
            啟動腳本寫入成功時回傳 True，失敗時回傳 False。
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

    def update_server_properties(self, server_name: str, properties: dict[str, str]) -> bool:
        """
        更新 server.properties，只覆蓋有變動的欄位，其餘欄位保留原值。

        Args:
            server_name: 目標伺服器名稱。
            properties: 要合併寫入的屬性。

        Returns:
            成功時回傳 True，失敗時回傳 False。
        """
        try:
            config = self.servers.get(server_name)
            if not config:
                logger.error(f"update_server_properties 找不到伺服器設定: {server_name}")
                return False
            server_path = getattr(config, "path", None) or getattr(config, "server_path", None)
            if not server_path:
                logger.error(f"找不到伺服器路徑，無法儲存 server.properties。config={config}")
                return False
            properties_path = Path(server_path) / "server.properties"
            original = ServerPropertiesHelper.load_properties(properties_path)
            merged = {**original, **properties}
            changed_keys = sorted((key for key, value in merged.items() if original.get(key) != value))
            logger.info(
                f"準備儲存 server.properties: server={server_name}, path={properties_path}, changed_keys={len(changed_keys)}"
            )
            if not ServerPropertiesHelper.save_properties(properties_path, merged):
                logger.error(f"儲存 server.properties 失敗: server={server_name}, path={properties_path}")
                return False
            try:
                mtime = properties_path.stat().st_mtime
            except OSError:
                mtime = time.time()
            self._properties_cache[server_name] = (mtime, dict(merged))
            config.properties = merged
            if not self.write_servers_config():
                logger.error(f"儲存 servers_config.json 失敗: server={server_name}")
                return False
            logger.info(
                f"server.properties 與 servers_config.json 已同步保存: server={server_name}, changed_keys={changed_keys}"
            )
            return True
        except Exception as e:
            try:
                properties_path = Path(getattr(self.servers.get(server_name), "path", "")) / "server.properties"
            except Exception:
                properties_path = None
            record_and_mark(
                e,
                marker_path=properties_path,
                reason="update_server_properties 儲存失敗",
                details={"server": server_name},
            )
            return False

    def delete_server_result(self, server_name: str) -> ServerOperationResult:
        """
        刪除伺服器。

        Args:
            server_name: 要刪除的伺服器名稱。

        Returns:
            刪除流程結果。
        """
        try:
            if server_name not in self.servers:
                return self._failure_result("刪除失敗", f"找不到伺服器: {server_name}", server_name=server_name)
            config = self.servers[server_name]
            server_path = Path(config.path).resolve(strict=False)
            if not PathUtils.is_path_within(self.servers_root, server_path, strict=False):
                logger.error(f"拒絕刪除不在 servers_root 之下的路徑: {server_path}")
                return self._failure_result(
                    "刪除失敗",
                    f"拒絕刪除不在伺服器根目錄下的路徑: {server_path}",
                    server_name=server_name,
                )
            removed_config = self.servers[server_name]
            del self.servers[server_name]
            if not self.write_servers_config():
                self.servers[server_name] = removed_config
                return self._failure_result(
                    "刪除失敗", f"無法保存刪除後的伺服器配置: {server_name}", server_name=server_name
                )
            if not PathUtils.delete_within(self.servers_root, server_path):
                self.servers[server_name] = removed_config
                if not self.write_servers_config():
                    logger.error(f"回滾刪除失敗時，無法恢復伺服器配置: {server_name}")
                return self._failure_result("刪除失敗", f"無法刪除伺服器資料夾: {server_path}", server_name=server_name)
            return self._success_result(f"伺服器 {server_name} 已刪除", server_name=server_name)
        except Exception as e:
            try:
                server_path = Path(getattr(self.servers.get(server_name), "path", ""))
            except Exception:
                server_path = None
            record_and_mark(e, marker_path=server_path, reason="刪除伺服器失敗", details={"server": server_name})
            return self._failure_result("刪除失敗", f"無法刪除伺服器 {server_name}。錯誤: {e}", server_name=server_name)

    def delete_server(self, server_name: str) -> bool:
        """
        刪除伺服器。

        Args:
            server_name: 要刪除的伺服器名稱。

        Returns:
            刪除成功時回傳 True，否則回傳 False。
        """

        return self.delete_server_result(server_name).success

    def load_servers_config(self) -> None:
        """載入伺服器配置"""
        with self._config_lock:
            try:
                data = PathUtils.load_json(self.config_file)
                if data is not None:
                    self.servers.clear()
                    for name, config_data in data.items():
                        self.servers[name] = ServerConfig(**config_data)
                else:
                    logger.warning("伺服器配置文件為空或無法解析")
            except Exception as e:
                with contextlib.suppress(Exception):
                    record_and_mark(e, marker_path=self.config_file, reason="load_servers_config_failed")

    def write_servers_config(self) -> bool:
        """
        實際執行保存伺服器配置到 servers_config.json。

        Returns:
            成功寫入時回傳 True，失敗時回傳 False。
        """
        with self._config_lock:
            try:
                data: dict[str, dict[str, Any]] = {}
                for name, config in self.servers.items():
                    if is_dataclass(config) and not isinstance(config, type):
                        data[name] = asdict(config)
                    elif isinstance(config, dict):
                        data[name] = config
                    else:
                        logger.error(f"保存伺服器配置失敗: 無法序列化類型 {type(config).__name__} ({name})")
                        return False
                logger.debug(f"寫入 servers_config.json: path={self.config_file}, server_count={len(data)}")
                if not atomic_write_json(self.config_file, data):
                    logger.error("保存伺服器配置失敗: 無法寫入文件")
                    return False
                logger.info("伺服器配置已保存到 servers_config.json")
                return True
            except Exception as e:
                with contextlib.suppress(Exception):
                    record_and_mark(e, marker_path=self.config_file, reason="write_servers_config_failed")
                logger.exception(f"保存伺服器配置失敗: {e}")
                return False

    def get_default_server_properties(self) -> dict[str, str]:
        """獲取預設伺服器屬性"""
        return {
            "accepts-transfers": "false",
            "allow-flight": "false",
            "broadcast-console-to-ops": "true",
            "broadcast-rcon-to-ops": "true",
            "bug-report-link": "",
            "difficulty": "easy",
            "enable-code-of-conduct": "false",
            "enable-jmx-monitoring": "false",
            "enable-query": "false",
            "enable-rcon": "false",
            "enable-status": "true",
            "enforce-secure-profile": "true",
            "enforce-whitelist": "false",
            "entity-broadcast-range-percentage": "100",
            "force-gamemode": "false",
            "function-permission-level": "2",
            "gamemode": "survival",
            "generate-structures": "true",
            "generator-settings": "{}",
            "hardcore": "false",
            "hide-online-players": "false",
            "initial-disabled-packs": "",
            "initial-enabled-packs": "vanilla",
            "level-name": "world",
            "level-seed": "",
            "level-type": "minecraft:normal",
            "log-ips": "true",
            "management-server-allowed-origins": "",
            "management-server-enabled": "false",
            "management-server-host": "localhost",
            "management-server-port": "0",
            "management-server-secret": "",
            "management-server-tls-enabled": "true",
            "management-server-tls-keystore": "",
            "management-server-tls-keystore-password": "",
            "max-chained-neighbor-updates": "1000000",
            "max-players": "20",
            "max-tick-time": "60000",
            "max-world-size": "29999984",
            "motd": "A Minecraft Server",
            "network-compression-threshold": "256",
            "online-mode": "true",
            "op-permission-level": "4",
            "pause-when-empty-seconds": "60",
            "player-idle-timeout": "0",
            "prevent-proxy-connections": "false",
            "query.port": "25565",
            "rate-limit": "0",
            "rcon.password": "",
            "rcon.port": "25575",
            "region-file-compression": "deflate",
            "require-resource-pack": "false",
            "resource-pack": "",
            "resource-pack-id": "",
            "resource-pack-prompt": "",
            "resource-pack-sha1": "",
            "server-ip": "",
            "server-port": "25565",
            "simulation-distance": "10",
            "spawn-protection": "16",
            "status-heartbeat-interval": "0",
            "sync-chunk-writes": "true",
            "text-filtering-config": "",
            "text-filtering-version": "0",
            "use-native-transport": "true",
            "view-distance": "10",
            "white-list": "false",
        }

    def server_exists(self, name: str) -> bool:
        """
        檢查伺服器是否已存在。

        Args:
            name: 伺服器名稱。

        Returns:
            若伺服器存在則回傳 True。
        """
        return name in self.servers

    @staticmethod
    def _collect_imported_startup_scripts(server_path: Path) -> list[Path]:
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

    @staticmethod
    def _extract_imported_startup_command(config: ServerConfig, script_path: Path) -> str | None:
        startup_command = ServerCommands.extract_startup_script_command(script_path)
        if not startup_command.has_java_command:
            return None
        if startup_command.memory_max_mb is not None:
            config.memory_max_mb = startup_command.memory_max_mb
        if startup_command.memory_min_mb is not None:
            config.memory_min_mb = startup_command.memory_min_mb
        return ServerCommands.replace_startup_command_java_path(startup_command.command_line, config)

    @staticmethod
    def _delete_root_startup_script(server_path: Path, script_path: Path) -> bool:
        server_root = server_path.resolve(strict=False)
        resolved_path = script_path.resolve(strict=False)
        if resolved_path.parent != server_root or not script_path.is_file():
            return False
        script_path.unlink()
        return True

    def _prepare_imported_startup_scripts(self, config: ServerConfig) -> None:
        """匯入伺服器時轉移原始腳本設定，並只留下程式管理的標準啟動腳本。"""
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
        添加伺服器配置（用於匯入）。

        Args:
            config: 要加入的伺服器設定。

        Returns:
            成功寫入設定時回傳 True，失敗時回傳 False。
        """
        previous_config = self.servers.get(config.name)
        try:
            self._prepare_imported_startup_scripts(config)
            self.servers[config.name] = config
            if not self.write_servers_config():
                raise RuntimeError(f"保存伺服器配置失敗: {config.name}")
            return True
        except Exception as e:
            if previous_config is not None:
                self.servers[config.name] = previous_config
            else:
                self.servers.pop(config.name, None)
            logger.exception(f"添加伺服器失敗: {e}")
            return False

    def load_server_properties(self, server_name: str) -> dict[str, str]:
        """
        載入伺服器的 server.properties 檔案內容（附帶快取機制）。

        Args:
            server_name: 伺服器名稱。

        Returns:
            讀取到的屬性字典；找不到或失敗時回傳空字典。
        """
        try:
            if server_name not in self.servers:
                return {}
            config = self.servers[server_name]
            server_path = Path(config.path)
            properties_file = server_path / "server.properties"
            if not properties_file.exists():
                return {}
            try:
                mtime = properties_file.stat().st_mtime
            except OSError:
                return {}
            cached_mtime, cached_props = self._properties_cache.get(server_name, (0, None))
            if cached_props is not None and mtime == cached_mtime:
                return cached_props
            properties = ServerPropertiesHelper.load_properties(properties_file)
            self._properties_cache[server_name] = (mtime, properties)
            logger.debug(
                f"重新載入 server.properties: server={server_name}, path={properties_file}, property_count={len(properties)}"
            )
            existing_properties = dict(getattr(config, "properties", {}) or {})
            if existing_properties != properties:
                config.properties = dict(properties)
                if not self.write_servers_config():
                    logger.warning(f"同步 server.properties 到 servers_config.json 失敗: server={server_name}")
            return properties
        except Exception as e:
            logger.exception(f"讀取 server.properties 失敗: {e}")
            return {}

    def invalidate_server_properties_cache(self, server_name: str | None = None) -> None:
        """
        清除 server.properties 快取。

        傳入 server_name 時僅清除單一伺服器，否則清除全部。

        Args:
            server_name: 要清除快取的伺服器名稱；為 None 時清除全部。
        """
        if server_name is None:
            self._properties_cache.clear()
            return
        self._properties_cache.pop(server_name, None)

    def get_server_log_file(self, server_name: str) -> Path | None:
        """
        獲取伺服器日誌檔案路徑。

        Args:
            server_name: 目標伺服器名稱。

        Returns:
            找到的日誌檔案路徑；找不到時回傳 None。
        """
        try:
            if server_name not in self.servers:
                return None
            server_config = self.servers[server_name]
            server_path = Path(server_config.path)
            log_files = [
                server_path / "logs" / "latest.log",
                server_path / "server.log",
                server_path / "logs" / "server.log",
            ]
            for log_file in log_files:
                if log_file.exists():
                    return log_file
            return None
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(e, reason="get_server_log_file_failed", details={"server": server_name})
            logger.exception(f"獲取伺服器日誌檔案失敗: {e}")
            return None
