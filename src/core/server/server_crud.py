"""
伺服器管理器

負責建立、管理與設定 Minecraft 伺服器的核心邏輯。
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from typing import Any, ClassVar

from src.core import ServerRuntime
from src.models import ServerConfig, ServerOperationResult
from src.utils import (
    ServerCommands,
    atomic_write_json,
    atomic_write_text,
    delete_within,
    get_logger,
    is_path_within,
    read_json,
)

logger = get_logger().bind(component="ServerManager")


class ServerCRUD:
    """伺服器管理類別，負責建立、管理和設定 Minecraft 伺服器"""

    _shared_servers: ClassVar[dict[str, dict[str, ServerConfig]]] = {}
    _operation_locks_guard: ClassVar[threading.Lock] = threading.Lock()
    _operation_locks: ClassVar[dict[str, threading.RLock]] = {}

    STARTUP_CHECK_DELAY = 0.1

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
        self.load_servers_config()
        if not self.config_file.exists():
            self.write_servers_config()

    def prepare_server_files(self, config: ServerConfig) -> None:
        """在 transaction staging 目錄準備 EULA 與基礎資料夾

        Args:
            config: 指向 staging 目錄的伺服器設定
        """
        server_path = Path(config.path).resolve(strict=False)
        if not is_path_within(self.servers_root, server_path, strict=False):
            raise ValueError("伺服器 staging 路徑不在伺服器根目錄內")
        if not server_path.is_dir():
            raise FileNotFoundError("伺服器 staging 目錄不存在")
        if not self._create_eula_file(server_path):
            raise RuntimeError("建立 EULA 檔案失敗")
        self._create_server_structure(server_path, config.loader_type)

    def create_launch_script(
        self,
        config: ServerConfig,
        java_command_override: str | None = None,
        *,
        launch_target: str | None = None,
    ) -> bool:
        """
        建立伺服器啟動腳本

        Args:
            config: 伺服器設定與啟動參數來源
            java_command_override: 匯入既有伺服器時保留的原始 Java 啟動命令
            launch_target: 已由 ServerInspector 驗證的 JAR 或 args 啟動目標

        Returns:
            啟動腳本寫入成功時回傳 True，失敗時回傳 False
        """
        server_path = Path(config.path)
        if java_command_override:
            java_command_str = java_command_override.strip()
        else:
            resolved_target = launch_target
            if resolved_target and Path(resolved_target).suffix.lower() in {".bat", ".cmd", ".sh", ".ps1"}:
                resolved_target = None
            if not resolved_target and server_path.is_dir():
                from src.core import ServerInspector

                detected = ServerInspector.find_main_jar(server_path, config.loader_type, config)
                if detected and detected.lower() != "@user_jvm_args.txt":
                    resolved_target = detected
            command_result = ServerCommands.build_java_command(
                config,
                return_list=False,
                launch_target=resolved_target,
            )
            java_command_str = str(command_result).strip()
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
        return atomic_write_text(start_script_path, bat_content, encoding="utf-8", errors="replace")

    def delete_server_result(self, server_name: str, *, server_runtime: ServerRuntime) -> ServerOperationResult:
        """
        刪除伺服器

        Args:
            server_name: 要刪除的伺服器名稱

        Returns:
            刪除流程結果
        """
        tombstone_path: Path | None = None
        server_path: Path | None = None
        removed_config: ServerConfig | None = None
        config_committed = False
        maintenance_acquired = False
        begin_maintenance = getattr(server_runtime, "begin_maintenance", None)
        if callable(begin_maintenance):
            maintenance_acquired = bool(begin_maintenance(server_name))
            if not maintenance_acquired:
                return ServerOperationResult(
                    success=False,
                    title="無法刪除",
                    message=f"伺服器 {server_name} 正在執行或進行其他維護操作",
                    server_name=server_name,
                )
        try:
            with self.operation_lock:
                if server_name not in self.servers:
                    return ServerOperationResult(
                        success=False,
                        title="刪除失敗",
                        message=f"找不到伺服器: {server_name}",
                        server_name=server_name,
                    )
                if server_runtime.observe(server_name).is_running:
                    return ServerOperationResult(
                        success=False,
                        title="無法刪除",
                        message=f"伺服器 {server_name} 正在執行中，請先停止伺服器",
                        server_name=server_name,
                    )

                config = self.servers[server_name]
                server_path = Path(config.path).resolve(strict=False)
                if not is_path_within(self.servers_root, server_path, strict=False):
                    logger.error(f"拒絕刪除不在 servers_root 之下的路徑: {server_path}")
                    return ServerOperationResult(
                        success=False,
                        title="刪除失敗",
                        message=f"拒絕刪除不在伺服器根目錄下的路徑: {server_path}",
                        server_name=server_name,
                    )

                if server_path.exists():
                    tombstone_path = self.servers_root / f".msm-delete-{uuid.uuid4().hex}"
                    server_path.replace(tombstone_path)

                removed_config = self.servers.pop(server_name)
                if not self.write_servers_config():
                    self.servers[server_name] = removed_config
                    if tombstone_path is not None:
                        tombstone_path.replace(server_path)
                        tombstone_path = None
                    return ServerOperationResult(
                        success=False,
                        title="刪除失敗",
                        message=f"無法儲存刪除後的伺服器設定: {server_name}",
                        server_name=server_name,
                    )
                config_committed = True

                if tombstone_path is not None:
                    if not delete_within(self.servers_root, tombstone_path):
                        logger.warning(f"伺服器已移除，但暫存刪除目錄無法清理: {tombstone_path}")
                    tombstone_path = None
                return ServerOperationResult(
                    success=True,
                    message=f"伺服器 {server_name} 已刪除",
                    server_name=server_name,
                )
        except Exception as e:
            error_message = str(e)
            if (
                tombstone_path is not None
                and server_path is not None
                and tombstone_path.exists()
                and not server_path.exists()
            ):
                try:
                    tombstone_path.replace(server_path)
                except OSError as e:
                    logger.exception(f"刪除失敗後無法復原伺服器目錄: {e}")
            if not config_committed and removed_config is not None and server_name not in self.servers:
                self.servers[server_name] = removed_config
                if not self.write_servers_config():
                    logger.error(f"刪除失敗後無法恢復伺服器設定: {server_name}")
            logger.exception(f"刪除伺服器失敗: {error_message}")
            return ServerOperationResult(
                success=False,
                title="刪除失敗",
                message=f"無法刪除伺服器 {server_name} 錯誤: {error_message}",
                server_name=server_name,
            )
        finally:
            if maintenance_acquired:
                end_maintenance = getattr(server_runtime, "end_maintenance", None)
                if callable(end_maintenance):
                    end_maintenance(server_name)

    def load_servers_config(self) -> None:
        """載入伺服器設定"""
        with self.operation_lock:
            try:
                data = read_json(self.config_file)
                if data is not None:
                    valid_keys = {f.name for f in fields(ServerConfig)}
                    new_servers: dict[str, ServerConfig] = {}
                    for name, config_data in data.items():
                        filtered_data = {k: v for k, v in config_data.items() if k in valid_keys}
                        new_servers[name] = ServerConfig(**filtered_data)
                    self.servers.clear()
                    self.servers.update(new_servers)
                else:
                    logger.warning("伺服器設定檔為空或無法解析")
            except Exception as e:
                logger.exception(f"載入伺服器設定失敗: {e}")

    def write_servers_config(self) -> bool:
        """
        實際執行儲存伺服器設定到 servers_config.json

        Returns:
            成功寫入時回傳 True，失敗時回傳 False
        """
        with self.operation_lock:
            try:
                data: dict[str, dict[str, Any]] = {}
                for name, config in list(self.servers.items()):
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
        return atomic_write_text(server_path / "eula.txt", eula_content)

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
