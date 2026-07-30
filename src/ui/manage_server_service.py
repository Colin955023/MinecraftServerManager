"""
管理伺服器服務模組
負責伺服器偵測、JAR 檔存在性與狀態描述計算。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..core import ServerDetectionUtils
from ..models import ServerConfig
from ..utils import get_logger

logger = get_logger().bind(component="ManageServerService")


class ManageServerService:
    """管理伺服器服務類別。"""

    @staticmethod
    def detect_servers_in_path(path: str, repository: Any, server_crud: Any) -> int:
        """
        掃描並偵測路徑下的所有伺服器。

        Args:
            path: 要偵測的資料夾路徑。
            repository: ServerRepository 實例。
            server_crud: ServerCRUD 實例。

        Returns:
            成功偵測或更新的伺服器數量。
        """
        count = 0
        path_obj = Path(path)
        if not path_obj.exists():
            return 0

        for item_path_obj in path_obj.iterdir():
            if item_path_obj.is_dir():
                item = item_path_obj.name
                item_path = str(item_path_obj)
                if ServerDetectionUtils.is_valid_server_folder(item_path_obj):
                    if item in repository.servers:
                        config = repository.servers[item]
                        config.path = str(item_path)
                    else:
                        config = ServerConfig(
                            name=item,
                            minecraft_version="Unknown",
                            loader_type="Unknown",
                            loader_version="Unknown",
                            memory_max_mb=2048,
                            path=item_path,
                        )
                    ServerDetectionUtils.detect_server_type(item_path_obj, config)
                    if item in repository.servers:
                        server_crud._prepare_imported_startup_scripts(config)
                        repository.write_servers_config()
                        count += 1
                    elif server_crud.add_server(config):
                        count += 1
        return count

    @staticmethod
    def check_server_jar_exists(server_path: str, loader_type: str = "vanilla") -> bool:
        """
        檢查伺服器 JAR 檔案是否存在。

        Args:
            server_path: 伺服器路徑。
            loader_type: 載入器類型。

        Returns:
            如果 JAR 檔案存在，返回 True；否則返回 False。
        """
        try:
            server_path_obj = Path(server_path)
            result = ServerDetectionUtils.find_main_jar(server_path_obj, loader_type or "vanilla")
            if result.startswith("@"):
                args_file_path = result[1:]
                return (server_path_obj / args_file_path).exists()
            jar_path = server_path_obj / result
            return jar_path.exists()
        except Exception as e:
            logger.debug(f"檢查 JAR 檔案存在失敗: {e}")
            return (Path(server_path) / "server.jar").exists()

    @classmethod
    def get_server_status_text(
        cls,
        name: str,
        config: ServerConfig,
        server_startup: Any,
        jar_search_cache: dict[str, Any],
        cache_timeout: int = 60,
    ) -> str:
        """
        獲取伺服器狀態顯示文字。

        Args:
            name: 伺服器名稱。
            config: 伺服器設定。
            server_startup: ServerStartup 實例。
            jar_search_cache: 搜尋快取字典。
            cache_timeout: 快取過期時間（秒）。

        Returns:
            伺服器狀態顯示文字。
        """
        is_running = server_startup.is_server_running(name)
        if is_running:
            return "🟢 運行中"

        current_time = time.time()
        cache_key = config.path
        if cache_key in jar_search_cache:
            cached_result, cache_time = jar_search_cache[cache_key]
            if current_time - cache_time < cache_timeout:
                server_jar_exists = cached_result
            else:
                server_jar_exists = cls.check_server_jar_exists(config.path, config.loader_type)
                jar_search_cache[cache_key] = (server_jar_exists, current_time)
        else:
            server_jar_exists = cls.check_server_jar_exists(config.path, config.loader_type)
            jar_search_cache[cache_key] = (server_jar_exists, current_time)

        eula_exists = (Path(config.path) / "eula.txt").exists()
        eula_accepted = getattr(config, "eula_accepted", False)
        if server_jar_exists and eula_exists and eula_accepted:
            return "✅ 已就緒"
        if server_jar_exists and eula_exists and (not eula_accepted):
            return "⚠️ 需要接受 EULA"
        if server_jar_exists:
            return "❌ 缺少 EULA"

        missing = ServerDetectionUtils.get_missing_server_files(Path(config.path))
        if missing:
            return f"❌ 未就緒 (缺少: {', '.join(missing)})"
        return "❌ 未就緒"
