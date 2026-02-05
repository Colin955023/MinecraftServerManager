#!/usr/bin/env python3
"""運行時路徑管理工具
提供應用程式運行時所需的路徑配置與管理功能
Runtime Path Management Utilities
Provides path configuration and management functions required during application runtime
"""

import os
import sys
from pathlib import Path


class RuntimePaths:
    """運行時路徑管理工具類"""

    # ====== 便攜模式檢測 ======
    @staticmethod
    def is_portable_mode() -> bool:
        """檢測是否為便攜模式（可執行檔旁有 .portable 標記檔或 .config 資料夾）"""
        exe_dir = RuntimePaths.get_exe_dir()

        # 檢查是否存在 .portable 標記檔或 .config 資料夾
        portable_marker = exe_dir / ".portable"
        config_dir = exe_dir / ".config"

        return portable_marker.exists() or config_dir.exists()

    # ====== 系統路徑檢測 ======
    @staticmethod
    def _get_localappdata() -> Path:
        """取得 Windows 系統的本機應用程式資料目錄路徑"""
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            # Fallback: %USERPROFILE%\AppData\Local
            base = str(Path.home() / "AppData" / "Local")
        return Path(base)

    @staticmethod
    def _get_portable_base_dir() -> Path:
        """取得便攜模式的基礎目錄（可執行檔所在目錄）"""
        return RuntimePaths.get_exe_dir()

    @staticmethod
    def get_exe_dir() -> Path:
        """取得當前執行檔或專案根目錄的基礎目錄。"""
        if getattr(sys, "frozen", False):
            # 打包後的可執行檔
            return Path(sys.executable).parent
        # 開發模式，使用專案根目錄
        return Path(__file__).resolve().parent.parent.parent

    # ====== 應用程式專用路徑 ======
    @staticmethod
    def get_user_data_dir() -> Path:
        """取得應用程式的使用者資料存放目錄"""
        if RuntimePaths.is_portable_mode():
            # 便攜模式：使用相對於可執行檔的 .config 資料夾
            return RuntimePaths._get_portable_base_dir() / ".config"
        # 安裝模式：使用 %LOCALAPPDATA%\Programs\MinecraftServerManager
        return RuntimePaths._get_localappdata() / "Programs" / "MinecraftServerManager"

    @staticmethod
    def get_cache_dir() -> Path:
        """取得應用程式的快取檔案存放目錄"""
        return RuntimePaths.get_user_data_dir() / "Cache"

    # ====== 目錄操作工具 ======
    @staticmethod
    def ensure_dir(p: Path) -> Path:
        """確保指定路徑的目錄存在，如果不存在則建立"""
        p.mkdir(parents=True, exist_ok=True)
        return p
