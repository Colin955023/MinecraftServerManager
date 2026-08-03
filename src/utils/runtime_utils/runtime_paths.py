"""
運行時路徑管理工具
提供應用程式運行時所需的路徑配置與管理功能。
"""

import os
import sys
from pathlib import Path


class RuntimePaths:
    """運行時路徑管理工具類"""

    @staticmethod
    def is_packaged() -> bool:
        """檢測是否為打包執行環境。"""
        is_compiled_app = "__compiled__" in globals()
        return bool(
            getattr(sys, "frozen", False)
            or hasattr(sys, "_MEIPASS")
            or is_compiled_app
            or getattr(sys, "__compiled__", False)
        )

    @staticmethod
    def is_development_environment() -> bool:
        """回傳目前是否為非打包的開發環境。"""
        return not RuntimePaths.is_packaged()

    @staticmethod
    def _get_localappdata() -> Path:
        """取得 Windows 系統的本機應用程式資料目錄路徑"""
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Local")
        return Path(base)

    @staticmethod
    def get_exe_dir() -> Path:
        """
        取得當前執行檔或專案根目錄的基礎目錄。

        Returns:
            執行環境對應的基礎目錄 Path。
        """
        if RuntimePaths.is_packaged():
            executable = getattr(sys, "executable", "")
            if executable:
                try:
                    return Path(executable).resolve().parents[0]
                except OSError:
                    return Path(executable).parents[0]
        try:
            from ..core_utils.path_utils import PathUtils

            return PathUtils.get_project_root()
        except Exception:
            current_file = Path(__file__).resolve()
            for parent in current_file.parents:
                if (parent / "pyproject.toml").exists():
                    return parent
            return current_file.parents[3]

    @staticmethod
    def get_user_data_dir() -> Path:
        """取得應用程式的使用者資料存放目錄"""
        override = os.environ.get("MSM_USER_DATA_DIR")
        if override:
            return Path(override)
        return RuntimePaths._get_localappdata() / "Programs" / "MinecraftServerManager"

    @staticmethod
    def get_cache_dir() -> Path:
        """取得應用程式的快取檔案存放目錄"""
        return RuntimePaths.get_user_data_dir() / "Cache"

    @staticmethod
    def get_log_dir() -> Path:
        """取得應用程式的日誌存放目錄"""
        return RuntimePaths.get_user_data_dir() / "Logs"

    @staticmethod
    def ensure_dir(p: Path) -> Path:
        """
        確保指定路徑的目錄存在，如果不存在則建立。

        Args:
            p: 要建立的目錄路徑。

        Returns:
            已確認存在的目錄路徑。
        """
        p.mkdir(parents=True, exist_ok=True)
        return p
