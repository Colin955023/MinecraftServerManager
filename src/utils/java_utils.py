#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在 Windows 上偵測與管理 Java 安裝的工具函式。
本模組提供從 Windows 常見安裝路徑與環境變數中尋找 Java 安裝的功能。
Utility functions for detecting and managing Java installations on Windows.
This module provides functions to find Java installations in the Windows registry,
common installation paths, and environment variables.
"""
# ====== 標準函式庫 ======
import json
import os
import re
import subprocess
# ====== 專案內部模組 ======
from . import java_downloader
from .http_utils import HTTPUtils
from .runtime_paths import get_cache_dir
from .ui_utils import UIUtils

COMMON_JAVA_PATHS = [
    r"C:\\Program Files\\Java",
    r"C:\\Program Files (x86)\\Java",
    r"C:\\Program Files\\Microsoft",
    r"C:\\Program Files\\Microsoft\\OpenJDK",
]
ENV_VARS = ["JAVA_HOME", "PRISMLAUNCHER_JAVA_PATHS"]

# ====== Java 版本檢測相關函數 ======
# 獲取 Java 版本號
def get_java_version(java_path: str) -> int:
    """
    取得指定 javaw.exe 的主要版本號
    Get the major version of the given javaw.exe
    
    Args:
        java_path (str): Java 執行檔的完整路徑
        
    Returns:
        int or None: Java 主要版本號，失敗時返回 None
    """
    try:
        out = subprocess.check_output([java_path, "-version"], stderr=subprocess.STDOUT, encoding="utf-8")
        m = re.search(r'version "([0-9]+)\.([0-9]+)', out)
        if m:
            major = int(m.group(1))
            if major == 1:
                # 1.x 代表 Java 8 及以前
                m2 = re.search(r'version "1\.([0-9]+)', out)
                if m2 and m2.group(1) == "8":
                    return 8
                return major
            return major
        m = re.search(r'version "1\.([0-9]+)', out)
        if m:
            if m.group(1) == "8":
                return 8
            return int(m.group(1))
    except Exception:
        pass
    return None

# 取得指定 Minecraft 版本所需的 Java 版本
def get_required_java_major(mc_version: str, loader_type: str = None, loader_version: str = None) -> int:
    """
    根據 mc_version、loader_type、loader_version 決定所需 Java major 版本
    Determine required Java major version based on Minecraft version and loader info
    
    Args:
        mc_version (str): Minecraft 版本號
        loader_type (str): 載入器類型（可選）
        loader_version (str): 載入器版本（可選）
        
    Returns:
        int: 所需的 Java 主要版本號
    """
    # 先查詢 LocalAppData Cache 中的 mc_versions_cache.json
    cache_path = get_cache_dir() / 'mc_versions_cache.json'
    if cache_path.exists():
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for v in data:
                if v.get('id') == mc_version and 'url' in v:
                    try:
                        ver_json = HTTPUtils.get_json(v['url'], timeout=8)
                        if ver_json:
                            java_info = ver_json.get('javaVersion') or ver_json.get('java_version')
                            if java_info:
                                major = java_info.get('majorVersion') or java_info.get('major')
                                if major:
                                    return int(major)
                    except Exception:
                        pass
        except Exception:
            pass
    v = tuple(int(x) for x in mc_version.split(".") if x.isdigit())
    if v <= (1, 16, 5):
        return 8
    if (1, 17, 0) <= v <= (1, 17, 9):
        return 16
    if (1, 18, 0) <= v <= (1, 20, 4):
        return 17
    if v >= (1, 20, 5):
        return 21
    return 17

# ====== Java 搜尋和檢測功能 ======
# 搜尋本機所有可用的 Java 安裝
def get_all_local_java_candidates() -> list:
    """
    返回所有可用的 javaw.exe 路徑及其主要版本
    Return all available javaw.exe paths and their major versions
    
    Args:
        None
        
    Returns:
        list: 格式為 (路徑, 主要版本) 的列表
    """
    candidates = []
    # 常見路徑
    for base in COMMON_JAVA_PATHS:
        if os.path.exists(base):
            for d in os.listdir(base):
                subdir = os.path.join(base, d)
                if os.path.isdir(subdir):
                    javaw = os.path.join(subdir, "bin", "javaw.exe")
                    if os.path.exists(javaw):
                        major = get_java_version(javaw)
                        if major:
                            candidates.append((os.path.normpath(javaw), major))
    # 環境變數
    for var in ENV_VARS:
        val = os.environ.get(var)
        if val:
            for p in val.split(";"):
                javaw = os.path.join(p, "bin", "javaw.exe")
                if os.path.exists(javaw):
                    major = get_java_version(javaw)
                    if major:
                        candidates.append((os.path.normpath(javaw), major))
    for p in os.environ.get("PATH", "").split(";"):
        javaw = os.path.join(p, "javaw.exe")
        if os.path.exists(javaw):
            major = get_java_version(javaw)
            if major:
                candidates.append((os.path.normpath(javaw), major))
    # 去重
    seen = set()
    result = []
    for path, major in candidates:
        if (path, major) not in seen:
            seen.add((path, major))
            result.append((path, major))
    # 按照 major 版本排序
    result.sort(key=lambda x: x[1])
    print(f"找到 {len(result)} 個 Java 執行檔候選：")
    for path, major in result:
        print(f"  {path} -> {major}")
    return result

# ====== Java 選擇和下載管理 ======
# 為指定版本選擇最佳 Java 路徑
def get_best_java_path(
    mc_version: str, loader_type: str = None, loader_version: str = None, ask_download: bool = True, parent=None
) -> str:
    """
    為指定 Minecraft 版本選擇最合適的 javaw.exe 路徑，找不到時詢問自動下載
    Select the best javaw.exe path for the given Minecraft version and loader info, ask to auto-download if not found
    
    Args:
        mc_version (str): Minecraft 版本號
        loader_type (str): 載入器類型（可選）
        loader_version (str): 載入器版本（可選）
        ask_download (bool): 找不到時是否詢問下載
        parent: 父視窗，用於顯示對話框（可選）
        
    Returns:
        str or None: 最佳 Java 路徑，找不到時返回 None
    """
    required_major = get_required_java_major(mc_version, loader_type, loader_version)
    candidates = get_all_local_java_candidates()
    # 先找完全符合 major
    for path, major in candidates:
        if major == required_major:
            return path
    # 再找大於需求的
    for path, major in candidates:
        if major > required_major:
            return path
    # 最後找小於需求的
    for path, major in candidates:
        if major < required_major:
            return path
    # 都沒有，詢問是否自動下載或手動下載
    if ask_download:
        res = UIUtils.ask_yes_no_cancel(
            "Java 未找到",
            f"未找到合適的 Java {required_major}，是否自動下載安裝？\n\n選擇 [是] 會自動下載安裝 Microsoft JDK，選擇 [否] 請手動下載並指定 Java 路徑。",
            show_cancel=False,
            parent=parent
        )
        if res:
            try:
                java_path = java_downloader.ensure_java_installed(required_major)
                if java_path:
                    return java_path
            except Exception as e:
                UIUtils.show_error(
                    "Java 下載失敗", f"自動下載 Microsoft JDK {required_major} 失敗：{e}\n請手動安裝或指定 Java 路徑。",
                    parent=parent
                )
        else:
            UIUtils.show_info(
                "請手動下載 Java",
                "請手動安裝或指定 Java 路徑。\n建議安裝 Microsoft JDK、Adoptium、Azul、Oracle JDK 17/21 等。",
                parent=parent
            )
    return None
