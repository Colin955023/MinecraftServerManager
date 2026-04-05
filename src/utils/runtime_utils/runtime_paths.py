"""運行時路徑管理工具
提供應用程式運行時所需的路徑配置與管理功能。
"""

import os
import sys
from pathlib import Path


class RuntimePaths:
    """運行時路徑管理工具類"""

    @staticmethod
    def is_portable_mode() -> bool:
        """檢測是否為便攜模式（可執行檔旁有 .portable 標記檔或 .config 資料夾）"""
        exe_dir = RuntimePaths.get_exe_dir()
        portable_marker = exe_dir / ".portable"
        config_dir = exe_dir / ".config"
        return portable_marker.exists() or config_dir.exists()

    @staticmethod
    def _get_localappdata() -> Path:
        """取得 Windows 系統的本機應用程式資料目錄路徑"""
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Local")
        return Path(base)

    @staticmethod
    def get_portable_base_dir() -> Path:
        """取得便攜模式的基礎目錄（可執行檔所在目錄）"""
        return RuntimePaths.get_exe_dir()

    @staticmethod
    def get_exe_dir() -> Path:
        """取得當前執行檔或專案根目錄的基礎目錄。"""
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent
        return Path(__file__).resolve().parent.parent.parent

    @staticmethod
    def get_user_data_dir() -> Path:
        """取得應用程式的使用者資料存放目錄"""
        if RuntimePaths.is_portable_mode():
            return RuntimePaths.get_portable_base_dir() / ".config"
        return RuntimePaths._get_localappdata() / "Programs" / "MinecraftServerManager"

    @staticmethod
    def get_cache_dir() -> Path:
        """取得應用程式的快取檔案存放目錄"""
        return RuntimePaths.get_user_data_dir() / "Cache"

    @staticmethod
    def get_log_dir() -> Path:
        """取得應用程式的日誌存放目錄"""
        if RuntimePaths.is_portable_mode():
            return RuntimePaths.get_portable_base_dir() / ".log"
        return RuntimePaths._get_localappdata() / "Programs" / "MinecraftServerManager" / "log"

    @staticmethod
    def ensure_dir(p: Path) -> Path:
        """確保指定路徑的目錄存在，如果不存在則建立。

        Args:
            p: 要建立的目錄路徑。

        Returns:
            已確認存在的目錄路徑。
        """
        p.mkdir(parents=True, exist_ok=True)
        return p
