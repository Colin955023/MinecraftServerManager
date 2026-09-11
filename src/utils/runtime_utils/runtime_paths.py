"""
執行時路徑管理工具
提供應用程式執行時所需的路徑設定與管理功能
"""

from __future__ import annotations

import os
import re
from pathlib import Path


class RuntimePaths:
    """執行時路徑管理工具類別"""

    @staticmethod
    def is_packaged() -> bool:
        """檢測是否為打包執行環境"""
        return "__compiled__" in globals()

    @staticmethod
    def is_development_environment() -> bool:
        """回傳目前是否為非打包的開發環境"""
        return not RuntimePaths.is_packaged()

    @staticmethod
    def _get_localappdata() -> Path:
        """取得 Windows 系統的本地應用程式資料目錄路徑"""
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Local")
        return Path(base)

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
    def get_version_cache_dir() -> Path:
        """
        取得版本列表快取檔案存放目錄

        Returns:
            已建立且經安全驗證的版本快取目錄
        """
        from src.utils import resolve_stable_directory

        return resolve_stable_directory(RuntimePaths.get_cache_dir() / "versions", create=True)

    @staticmethod
    def get_installer_cache_dir() -> Path:
        """
        取得模組安裝器檔案存放目錄

        Returns:
            已建立且經安全驗證的安裝器快取目錄
        """
        from src.utils import resolve_stable_directory

        return resolve_stable_directory(RuntimePaths.get_cache_dir() / "installers", create=True)

    @staticmethod
    def get_log_dir() -> Path:
        """取得應用程式的日誌存放目錄"""
        return RuntimePaths.get_user_data_dir() / "Logs"

    @staticmethod
    def cleanup_old_onefile_caches(current_version: str) -> None:
        """
        程式成功啟動後清理可辨識且不再使用的 onefile 版本目錄

        Args:
            current_version: 當前程式版本號
        """
        if not RuntimePaths.is_packaged():
            return
        from src.utils import delete_within, list_bounded_directory

        root = RuntimePaths.get_user_data_dir()
        current_name = str(current_version or "").strip()
        if not current_name or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._-]*", current_name):
            return
        try:
            entries = list_bounded_directory(root)
        except OSError:
            return
        for entry in entries:
            if (
                not entry.is_dir()
                or entry.name == current_name
                or entry.name.startswith(f"{current_name}.")
                or entry.name.startswith(f"{current_name}-")
            ):
                continue
            if not re.fullmatch(r"\d+(?:\.\d+){1,4}(?:[-._][0-9A-Za-z.-]+)?", entry.name):
                continue
            delete_within(root, entry)


__all__ = ["RuntimePaths"]
