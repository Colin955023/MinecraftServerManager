"""
伺服器資源庫模組
負責伺服器狀態的持久化與檔案 I/O，處理 servers_config.json 與 server.properties 的讀寫與鎖管理。
"""

import contextlib
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from ...models import ServerConfig
from ...utils import PathUtils, atomic_write_json, get_logger, record_and_mark
from ...utils.server_utils.server_constants import DEFAULT_SERVER_PROPERTIES
from .server_properties import ServerPropertiesHelper

logger = get_logger().bind(component="ServerRepository")


class ServerRepository:
    """處理伺服器資料與配置的持久化層。"""

    def __init__(self, servers_root: str):
        if not servers_root:
            raise ValueError("ServerRepository 必須指定 servers_root 路徑，且不可為空。")
        self.servers_root = Path(servers_root).resolve()
        self.servers_root.mkdir(parents=True, exist_ok=True)
        self.config_file = self.servers_root / "servers_config.json"

        self.servers: dict[str, ServerConfig] = {}
        self._properties_cache: dict[str, Any] = {}

        self._config_lock = threading.Lock()
        self._properties_update_lock = threading.Lock()

        self.load_servers_config()
        if not self.config_file.exists():
            self.write_servers_config()

    def load_servers_config(self) -> None:
        """載入伺服器配置。"""
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
        將伺服器配置寫入 JSON 文件。

        Returns:
            bool: 是否成功寫入。
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

    @staticmethod
    def get_default_server_properties() -> dict[str, str]:
        """獲取預設的伺服器屬性。"""
        return dict(DEFAULT_SERVER_PROPERTIES)

    def load_server_properties(self, server_name: str) -> dict[str, str]:
        """
        載入指定伺服器的 server.properties 文件，並使用快取以提高效能。

        Args:
            server_name: 伺服器名稱。

        Returns:
            dict[str, str]: 伺服器屬性字典。
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

            with self._properties_update_lock:
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

    def update_server_properties(self, server_name: str, properties: dict[str, str]) -> bool:
        """
        更新指定伺服器的 server.properties 文件，並同步更新 servers_config.json。
        加入鎖機制確保多執行緒下讀取-修改-寫入週期的安全性。

        Args:
            server_name: 伺服器名稱。
            properties: 要更新的伺服器屬性字典。

        Returns:
            bool: 是否成功更新。
        """
        with self._properties_update_lock:
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
