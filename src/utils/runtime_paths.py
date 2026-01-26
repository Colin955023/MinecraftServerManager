#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
運行時路徑管理工具
提供應用程式運行時所需的路徑配置與管理功能
Runtime Path Management Utilities
Provides path configuration and management functions required during application runtime
"""
from pathlib import Path
import os

# ====== 系統路徑檢測 ======
def _get_localappdata() -> Path:
    """
    取得 Windows 系統的本機應用程式資料目錄路徑
    Get Windows system's local application data directory path

    Args:
        None

    Returns:
        Path: 本機應用程式資料目錄路徑
    """
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        # Fallback: %USERPROFILE%\AppData\Local
        base = str(Path.home() / "AppData" / "Local")
    return Path(base)

# ====== 應用程式專用路徑 ======
def get_user_data_dir() -> Path:
    """
    取得應用程式的使用者資料存放目錄
    Get application's user data storage directory (%LOCALAPPDATA%\\MinecraftServerManager)

    Args:
        None

    Returns:
        Path: 使用者資料目錄路徑
    """
    # 修改：將資料目錄移動到 %LOCALAPPDATA%\Programs\MinecraftServerManager
    return _get_localappdata() / "Programs" / "MinecraftServerManager"

def get_cache_dir() -> Path:
    """
    取得應用程式的快取檔案存放目錄
    Get application's cache file storage directory (%LOCALAPPDATA%\\MinecraftServerManager\\Cache)

    Args:
        None

    Returns:
        Path: 快取目錄路徑
    """
    return get_user_data_dir() / "Cache"

# ====== 目錄操作工具 ======
def ensure_dir(p: Path) -> Path:
    """
    確保指定路徑的目錄存在，如果不存在則建立
    Ensure the directory at specified path exists, create if it doesn't exist

    Args:
        p (Path): 要確保存在的目錄路徑

    Returns:
        Path: 已確保存在的目錄路徑
    """
    p.mkdir(parents=True, exist_ok=True)
    return p
