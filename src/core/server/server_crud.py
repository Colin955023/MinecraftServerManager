"""
伺服器管理器

負責建立、管理與配置 Minecraft 伺服器
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from typing import Any, ClassVar

from src.models import ServerConfig, ServerOperationResult
from src.utils import (
    PathUtils,
    ServerCommands,
    ServerPropertiesHelper,
    atomic_write_json,
    get_logger,
)

logger = get_logger().bind(component="ServerManager")


class ServerCRUD:
    """負責建立、管理和配置 Minecraft 伺服器"""

    _shared_servers: ClassVar[dict[str, dict[str, ServerConfig]]] = {}
    _operation_locks_guard: ClassVar[threading.Lock] = threading.Lock()
    _operation_locks: ClassVar[dict[str, threading.RLock]] = {}

    STARTUP_CHECK_DELAY = 0.1
    OUTPUT_QUEUE_MAX_SIZE = 1000

    def __init__(self, servers_root: str | None = None):
        if not servers_root:
            raise ValueError("ServerManager 必須指定 servers_root 路徑，且不可為空請於 UI 層先處理")
        self.servers_root = Path(servers_root).resolve()
        self.servers_root.mkdir(parents=True, exist_ok=True)
        self.config_file = self.servers_root / "servers_config.json"

        key = str(self.servers_root)
        with self._operation_locks_guard:
            self.operation_lock = self._operation_locks.setdefault(key, threading.RLock())
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
        """建立成功結果"""
        return ServerOperationResult(success=True, message=message, server_name=server_name)

    @staticmethod
    def _failure_result(title: str, message: str, *, server_name: str = "") -> ServerOperationResult:
        """建立失敗結果"""
        return ServerOperationResult(success=False, title=title, message=message, server_name=server_name)

    def prepare_server_files(self, config: ServerConfig, properties: dict[str, str]) -> None:
        """在 transaction staging 目錄準備不含下載內容與啟動腳本的基礎檔案

        Args:
            config: 指向 staging 目錄的伺服器設定
            properties: 要寫入的 server.properties 內容
        """
        server_path = Path(config.path).resolve(strict=False)
        if not PathUtils.is_path_within(self.servers_root, server_path, strict=False):
            raise ValueError("伺服器 staging 路徑不在伺服器根目錄內")
        if not server_path.is_dir():
            raise FileNotFoundError("伺服器 staging 目錄不存在")
        if not self._create_eula_file(server_path):
            raise RuntimeError("建立 EULA 檔案失敗")
        config.eula_accepted = True
        self._create_server_structure(server_path, config.loader_type)
        normalized_properties = dict(properties)
        normalized_properties["motd"] = f"Minecraft 伺服器 - {config.name}"
        if not ServerPropertiesHelper.save_properties(server_path / "server.properties", normalized_properties):
            raise RuntimeError("儲存 server.properties 失敗")
        config.properties = normalized_properties

    def create_launch_script(self, config: ServerConfig, java_command_override: str | None = None) -> bool:
        """
        建立伺服器啟動腳本

        Args:
            config: 伺服器設定與啟動參數來源
            java_command_override: 匯入既有伺服器時保留的原始 Java 啟動命令

        Returns:
            啟動腳本寫入成功時回傳 True，失敗時回傳 False
        """
        server_path = Path(config.path)
        if java_command_override:
            java_command_str = java_command_override.strip()
        else:
            java_cmd_list = ServerCommands.build_java_command(config, return_list=True)
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
                        jar_path = Path(jar_spec) if Path(jar_spec).is_absolute() else (server_path / jar_spec)
                        if jar_path.exists():
                            try:
                                rel = jar_path.resolve().relative_to(server_path.resolve())
                                cmd_parts.append(f'"{rel.as_posix()}"')
                            except ValueError:
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
                    return True
        except Exception as e:
            logger.debug(f"比較啟動腳本時發生錯誤 (將強制覆寫): {e}")
        return PathUtils.write_text_file(start_script_path, bat_content, encoding="utf-8", errors="replace")

    def update_server_properties(self, server_name: str, properties: dict[str, str]) -> bool:
        """
        更新 server.properties，只覆蓋有變動的欄位，其餘欄位保留原值

        Args:
            server_name: 目標伺服器名稱
            properties: 要合併寫入的屬性

        Returns:
            成功時回傳 True，失敗時回傳 False
        """
        try:
            config = self.servers.get(server_name)
            if not config:
                logger.error(f"update_server_properties 找不到伺服器設定: {server_name}")
                return False
            server_path = getattr(config, "path", None) or getattr(config, "server_path", None)
            if not server_path:
                logger.error(f"找不到伺服器路徑，無法儲存 server.properties config={config}")
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
                f"server.properties 與 servers_config.json 已同步儲存: server={server_name}, changed_keys={changed_keys}"
            )
            return True
        except Exception as exc:
            logger.exception(f"更新 server.properties 失敗: {exc}")
            return False

    def delete_server_result(self, server_name: str) -> ServerOperationResult:
        """
        刪除伺服器

        Args:
            server_name: 要刪除的伺服器名稱

        Returns:
            刪除流程結果
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
                    "刪除失敗", f"無法儲存刪除後的伺服器設定: {server_name}", server_name=server_name
                )
            if not PathUtils.delete_within(self.servers_root, server_path):
                self.servers[server_name] = removed_config
                if not self.write_servers_config():
                    logger.error(f"回滾刪除失敗時，無法恢復伺服器設定: {server_name}")
                return self._failure_result("刪除失敗", f"無法刪除伺服器資料夾: {server_path}", server_name=server_name)
            return self._success_result(f"伺服器 {server_name} 已刪除", server_name=server_name)
        except Exception as e:
            logger.exception(f"刪除伺服器失敗: {e}")
            return self._failure_result("刪除失敗", f"無法刪除伺服器 {server_name} 錯誤: {e}", server_name=server_name)

    def load_servers_config(self) -> None:
        """載入伺服器設定"""
        with self._config_lock:
            try:
                data = PathUtils.load_json(self.config_file)
                if data is not None:
                    self.servers.clear()
                    valid_keys = {f.name for f in fields(ServerConfig)}
                    for name, config_data in data.items():
                        filtered_data = {k: v for k, v in config_data.items() if k in valid_keys}
                        self.servers[name] = ServerConfig(**filtered_data)
                else:
                    logger.warning("伺服器設定檔為空或無法解析")
            except Exception as exc:
                logger.exception(f"載入伺服器設定失敗: {exc}")

    def write_servers_config(self) -> bool:
        """
        實際執行儲存伺服器設定到 servers_config.json

        Returns:
            成功寫入時回傳 True，失敗時回傳 False
        """
        with self._config_lock:
            try:
                data: dict[str, dict[str, Any]] = {}
                for name, config in self.servers.items():
                    if is_dataclass(config) and not isinstance(config, type):
                        raw_dict = asdict(config)

                        def _remove_callables(d: Any) -> Any:
                            if isinstance(d, dict):
                                return {k: _remove_callables(v) for k, v in d.items() if not callable(v)}
                            if isinstance(d, list):
                                return [_remove_callables(v) for v in d if not callable(v)]
                            return d

                        data[name] = _remove_callables(raw_dict)
                    elif isinstance(config, dict):
                        data[name] = config
                    else:
                        logger.error(f"儲存伺服器設定失敗: 無法序列化類型 {type(config).__name__} ({name})")
                        return False
                if not atomic_write_json(self.config_file, data):
                    logger.error("儲存伺服器設定失敗: 無法寫入檔案")
                    return False
                logger.info("伺服器設定已儲存到 servers_config.json")
                return True
            except Exception as e:
                logger.exception(f"儲存伺服器設定失敗: {e}")
                return False

    def get_default_server_properties(self) -> dict[str, str]:
        """
        取得預設伺服器屬性

        Returns:
            預設的 server.properties 屬性字典
        """
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
        檢查伺服器是否已存在

        Args:
            name: 伺服器名稱

        Returns:
            若伺服器存在則回傳 True
        """
        return name in self.servers

    def load_server_properties(self, server_name: str) -> dict[str, str]:
        """
        載入伺服器的 server.properties 檔案內容（附帶快取機制）

        Args:
            server_name: 伺服器名稱

        Returns:
            讀取到的屬性字典；找不到或失敗時回傳空字典
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
            existing_properties = dict(getattr(config, "properties", {}) or {})
            if existing_properties != properties:
                config.properties = dict(properties)
                if not self.write_servers_config():
                    logger.warning(f"同步 server.properties 到 servers_config.json 失敗: server={server_name}")
            return properties
        except Exception as e:
            logger.exception(f"讀取 server.properties 失敗: {e}")
            return {}

    def get_server_log_file(self, server_name: str) -> Path | None:
        """
        取得伺服器日誌檔案路徑

        Args:
            server_name: 目標伺服器名稱

        Returns:
            找到的日誌檔案路徑；找不到時回傳 None
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
            return next((f for f in log_files if f.exists()), None)
        except Exception as e:
            logger.exception(f"取得伺服器日誌檔案失敗: {e}")
            return None

    def _create_eula_file(self, server_path: Path) -> bool:
        """建立並同意 EULA 檔案"""
        eula_content = "eula=true"
        return PathUtils.write_text_file(server_path / "eula.txt", eula_content)

    def _create_server_structure(self, path: Path, loader_type: str) -> None:
        """建立伺服器檔案結構"""
        if loader_type.lower() == "vanilla":
            directories = ["world", "logs"]
        elif loader_type.lower() in ["forge", "fabric", "quilt", "neoforge"]:
            directories = ["world", "plugins", "mods", "config", "logs"]
        else:
            directories = ["world", "logs"]
            logger.warning(f"未知 loader_type: {loader_type}，使用預設目錄結構")
        for directory in directories:
            (path / directory).mkdir(exist_ok=True)


__all__ = ["ServerCRUD"]
