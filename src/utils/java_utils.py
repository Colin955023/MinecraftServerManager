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
import requests
import re
import subprocess
from typing import Optional
# ====== 專案內部模組 ======
from .http_utils import HTTPUtils
from .runtime_paths import get_cache_dir
from .ui_utils import UIUtils
from .log_utils import LogUtils
from src.core.version_manager import MinecraftVersionManager
from .java_downloader import install_java_with_winget

COMMON_JAVA_PATHS = [
    r"C:\\Program Files\\Java",
    r"C:\\Program Files (x86)\\Java",
    r"C:\\Program Files\\Microsoft"
]
# 只偵測 JAVA_HOME，Path 另外處理
ENV_VARS = ["JAVA_HOME"]

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
def get_required_java_major(mc_version: str) -> int:
    """
    根據 mc_version 決定所需 Java major 版本
    Determine required Java major version based on Minecraft version

    Args:
        mc_version (str): Minecraft 版本號

    Returns:
        int: 所需的 Java 主要版本號
    """
    if not isinstance(mc_version, str) or not mc_version:
        raise ValueError("mc_version 必須為非空字串")
    cache_path = get_cache_dir() / "mc_versions_cache.json"
    # 若快取不存在或內容為空，則自動建立快取
    if not cache_path.exists() or cache_path.stat().st_size == 0:
        try:
            vm = MinecraftVersionManager()
            vm.fetch_versions()
        except Exception as e:
            raise FileNotFoundError(f"找不到 {cache_path}，且自動建立快取失敗: {e}")
    # 再次檢查
    if not cache_path.exists() or cache_path.stat().st_size == 0:
        raise FileNotFoundError(f"找不到 {cache_path} 或檔案為空")
    with open(cache_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception as e:
            raise ValueError(f"無法解析 {cache_path} 內容: {e}")
    if isinstance(data, dict):
        data = [data]
    for v in data:
        if v.get("id") == mc_version and "url" in v:
            url = v["url"]
            ver_json = HTTPUtils.get_json(url, timeout=8)
            if ver_json:
                java_info = ver_json.get("javaVersion")
                if java_info and "majorVersion" in java_info:
                    return int(java_info["majorVersion"])
                java_info2 = ver_json.get("java_version")
                if java_info2 and "major" in java_info2:
                    return int(java_info2["major"])
                # 萬一格式不同，正則搜尋 major
                resp = requests.get(url, timeout=8)
                if resp.ok:
                    m = re.search(r'"major(?:Version)?"\s*:\s*(\d+)', resp.text)
                    if m:
                        return int(m.group(1))
            raise ValueError(f"找不到 majorVersion，url: {url}")
    raise ValueError(f"找不到對應 mc_version: {mc_version}")

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
    # 統一搜尋所有來源
    search_paths = set()
    # 常見路徑
    for base in COMMON_JAVA_PATHS:
        if os.path.exists(base):
            for d in os.listdir(base):
                subdir = os.path.join(base, d)
                if os.path.isdir(subdir):
                    search_paths.add(os.path.join(subdir, "bin"))
    # JAVA_HOME
    for var in ENV_VARS:
        val = os.environ.get(var)
        if val:
            for p in val.split(";"):
                search_paths.add(os.path.join(p, "bin"))
    # 使用者 Path
    for p in os.environ.get("PATH", "").split(";"):
        search_paths.add(p)
    # 搜尋所有目錄下的 javaw.exe
    for p in search_paths:
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
    LogUtils.info(f"找到 {len(result)} 個 Java 執行檔選擇：", "JavaUtils")
    for path, major in result:
        LogUtils.info(f"  {path} -> {major}", "JavaUtils")
    return result

# ====== Java 選擇和下載管理 ======
# 為指定版本選擇最佳 Java 路徑
def get_best_java_path(mc_version: str, required_major: Optional[int] = None, ask_download: bool = True) -> str:
    """
    為指定 Minecraft 版本選擇最合適的 javaw.exe 路徑，找不到時詢問自動下載
    Select the best javaw.exe path for the given Minecraft version and loader info, ask to auto-download if not found

    Args:
        mc_version (str): Minecraft 版本號
        required_major (int, optional): 需要的 Java 主要版本，若未指定則自動判斷
        ask_download (bool, optional): 是否詢問自動下載，預設為 True

    Returns:
        str or None: 最佳 Java 路徑，找不到時返回 None
    """
    required_major = required_major if required_major else get_required_java_major(mc_version)
    candidates = get_all_local_java_candidates()
    for path, major in candidates:
        if major == required_major:
            return path
    if ask_download:
        # 找不到則詢問是否自動下載
        vendor = "Oracle jre" if required_major == 8 else "Microsoft JDK"
        res = UIUtils.ask_yes_no_cancel(
            "Java 未找到",
            f"未找到合適的 Java {required_major}，是否自動下載安裝？\n\n選擇 [是] 會自動下載安裝 {vendor} ，選擇 [否] 請手動下載並指定 Java 路徑。",
            show_cancel=False,
            topmost=True,
        )
        if res:
            try:
                install_java_with_winget(required_major)
                # 重新搜尋
                candidates = get_all_local_java_candidates()
                for path, major in candidates:
                    if major == required_major:
                        UIUtils.show_info(
                            title=f"Java {required_major} 安裝成功",
                            message=f"Java {required_major} 已成功安裝並偵測到 javaw.exe。",
                            topmost=True,
                        )
                        return path
            except Exception as e:
                UIUtils.show_error(
                    "Java 下載失敗",
                    f"自動下載 Microsoft JDK {required_major} 失敗：{e}\n請手動安裝或指定 Java 路徑。",
                    topmost=True,
                )
        else:
            UIUtils.show_info(
                "請手動下載 Java",
                f"請手動安裝或指定 Java 路徑。\n建議安裝 Microsoft JDK、Adoptium、Azul、Oracle JDK 17/21 等。",
                topmost=True,
            )
    return None
