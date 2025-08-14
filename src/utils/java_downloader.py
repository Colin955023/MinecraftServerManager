#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Java 下載工具模組
提供 Java 安裝包下載和管理功能，支援 Microsoft JDK 的自動下載與安裝
Java Download Utility Module
Provides functions to download and manage Java installations, supports Microsoft JDK automatic download and installation
"""
# ====== 標準函式庫 ======
from pathlib import Path
import os
import zipfile
# ====== 專案內部模組 ======
from .http_utils import HTTPUtils
from .log_utils import LogUtils

# Microsoft JDK 主要版本下載 URL（自動指向最新 LTS 次要版本）
MS_JDK_URL_TEMPLATE = "https://aka.ms/download-jdk/microsoft-jdk-{major}-windows-x64.zip"

# ====== URL 生成工具 ======
# 取得 Microsoft JDK 下載連結
def get_latest_ms_jdk_url(major: int) -> str:
    """
    取得 Microsoft JDK 最新 LTS 主要版本的 Windows x64 zip 下載連結
    Get Microsoft JDK latest LTS major version Windows x64 zip download URL
    
    Args:
        major (int): Java 主要版本號
        
    Returns:
        str: 下載連結 URL
    """
    return MS_JDK_URL_TEMPLATE.format(major=major)

# ====== Java 下載與安裝 ======
# 下載並解壓 JDK
def download_and_extract_jdk(major: int, target_dir: str) -> str:
    """
    下載並解壓 Microsoft JDK 到指定目錄
    Download and extract Microsoft JDK to target directory
    
    Args:
        major (int): Java 主要版本號
        target_dir (str): 目標目錄路徑
        
    Returns:
        str: javaw.exe 的完整路徑
    """
    url = get_latest_ms_jdk_url(major)
    LogUtils.debug(f"下載 Microsoft JDK {major}：{url}", "JavaDownloader")
    local_zip = os.path.join(target_dir, f"jdk{major}.zip")

    # 使用統一的 HTTP 工具下載文件
    success = HTTPUtils.download_file(url, local_zip, timeout=60)
    if not success:
        raise Exception(f"下載 JDK 失敗: {url}")

    # 解壓
    with zipfile.ZipFile(local_zip, 'r') as zip_ref:
        zip_ref.extractall(target_dir)
    os.remove(local_zip)
    # 尋找 javaw.exe
    for root, dirs, files in os.walk(target_dir):
        if "javaw.exe" in files:
            return os.path.join(root, "javaw.exe")
    raise Exception("解壓後找不到 javaw.exe")

# 確保 Java 已安裝
def ensure_java_installed(major: int, base_dir: str = r"C:\\Program Files\\Microsoft") -> str:
    """
    確保指定版本的 Java 已安裝，若無則自動下載安裝
    Ensure specified Java version is installed, auto-download if not found
    
    Args:
        major (int): Java 主要版本號
        base_dir (str): 基礎安裝目錄
        
    Returns:
        str: javaw.exe 的完整路徑
    """
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    # winget 標準路徑: C:\Program Files\Microsoft\jdk-<major>
    for d in base.iterdir():
        if d.is_dir() and d.name.startswith(f"jdk-{major}"):
            javaw = d / "bin" / "javaw.exe"
            if javaw.exists():
                return str(javaw)
    # 沒有就下載
    jdk_dir = base / f"jdk-{major}"
    jdk_dir.mkdir(exist_ok=True)
    return download_and_extract_jdk(major, str(jdk_dir))
