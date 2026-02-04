#!/usr/bin/env python3
"""在 Windows 上偵測與管理 Java 安裝的工具函式。
本模組提供從 Windows 常見安裝路徑與環境變數中尋找 Java 安裝的功能。
Utility functions for detecting and managing Java installations on Windows.
This module provides functions to find Java installations in the Windows registry,
common installation paths, and environment variables.
"""

import json
import os
import re
import shutil
from pathlib import Path
from subprocess import STDOUT

from src.core import MinecraftVersionManager

from . import (
    HTTPUtils,
    PathUtils,
    UIUtils,
    get_cache_dir,
    get_logger,
    install_java_with_winget,
    run_checked,
)

logger = get_logger().bind(component="JavaUtils")

COMMON_JAVA_PATHS = [
    r"C:\\Program Files\\Java",
    r"C:\\Program Files (x86)\\Java",
    r"C:\\Program Files\\Microsoft",
]
# 只偵測 JAVA_HOME，Path 另外處理
ENV_VARS = ["JAVA_HOME"]


# ====== Java 版本檢測相關函數 ======
# 獲取 Java 版本號
def get_java_version(java_path: str) -> int | None:
    """取得指定 javaw.exe 的主要版本號
    Get the major version of the given javaw.exe

    Args:
        java_path (str): Java 執行檔的完整路徑

    Returns:
        int or None: Java 主要版本號，失敗時返回 None

    """
    try:
        res = run_checked([java_path, "-version"], capture_output=True, text=True, stderr=STDOUT, check=True)
        out = res.stdout or ""
        m = re.search(r'version "(\d+)\.(\d+)', out)
        if m:
            major = int(m.group(1))
            # Java 8 及以前版本格式為 "1.8"，需要取第二個數字
            if major == 1:
                return int(m.group(2))
            # Java 9+ 格式為 "9.x", "11.x" 等，直接取第一個數字
            return major

        # 備用模式：直接匹配 "version \"X" 格式
        m = re.search(r'version "(\d+)"', out)
        if m:
            return int(m.group(1))
    except Exception as e:
        logger.exception(f"取得 Java 版本失敗 {java_path}: {e}")
    return None


def _ensure_cache_exists(cache_path):
    """確保快取檔案存在且非空"""
    if not cache_path.exists() or cache_path.stat().st_size == 0:
        try:
            vm = MinecraftVersionManager()
            vm.fetch_versions()
        except Exception as e:
            raise FileNotFoundError(f"找不到 {cache_path}，且自動建立快取失敗: {e}") from e
        # 再次檢查
        if not cache_path.exists() or cache_path.stat().st_size == 0:
            raise FileNotFoundError(f"找不到 {cache_path} 或檔案為空")


# 取得指定 Minecraft 版本所需的 Java 版本
def get_required_java_major(mc_version: str) -> int:
    """根據 mc_version 決定所需 Java major 版本
    Determine required Java major version based on Minecraft version

    Args:
        mc_version (str): Minecraft 版本號

    Returns:
        int: 所需的 Java 主要版本號

    """
    if not isinstance(mc_version, str) or not mc_version:
        raise ValueError("mc_version 必須為非空字串")

    cache_path = get_cache_dir() / "mc_versions_cache.json"
    _ensure_cache_exists(cache_path)

    data = PathUtils.load_json(cache_path)
    if data is None:
        raise ValueError(f"無法解析 {cache_path} 內容")

    if isinstance(data, dict):
        data = [data]
    for v in data:
        if v.get("id") == mc_version and "url" in v:
            url = v["url"]
            ver_json = HTTPUtils.get_json(url, timeout=8)
            if ver_json:
                # 優先檢查 javaVersion 結構
                java_info = ver_json.get("javaVersion")
                if java_info and "majorVersion" in java_info:
                    return int(java_info["majorVersion"])
                java_info2 = ver_json.get("java_version")
                if java_info2 and "major" in java_info2:
                    return int(java_info2["major"])
                json_str = json.dumps(ver_json)
                m = re.search(r'"major(?:Version)?"\s*:\s*(\d+)', json_str)
                if m:
                    return int(m.group(1))
            raise ValueError(f"找不到 majorVersion，url: {url}")
    raise ValueError(f"找不到對應 mc_version: {mc_version}")


# ====== Java 搜尋和檢測功能 ======
# 搜尋本機所有可用的 Java 安裝
def get_all_local_java_candidates() -> list:
    """返回所有可用的 javaw.exe 路徑及其主要版本
    Return all available javaw.exe paths and their major versions

    Args:
        None

    Returns:
        list: 格式為 (路徑, 主要版本) 的列表

    """
    search_paths = set()

    # 1.常見路徑搜尋
    for base_str in COMMON_JAVA_PATHS:
        base = Path(base_str)
        if base.exists():
            for subdir in base.iterdir():
                if subdir.is_dir():
                    search_paths.add(str(subdir / "bin"))

    # 2.JAVA_HOME 環境變數
    for var in ENV_VARS:
        val = os.environ.get(var)
        if val:
            for p in val.split(";"):
                java_bin = Path(p) / "bin"
                search_paths.add(str(java_bin))

    # 3.PATH 環境變數中的 Java 路徑（優化：只掃描 PATH 而非所有環境變數）
    try:
        path_env = os.environ.get("PATH", "")
        if path_env:
            for path_str in path_env.split(os.pathsep):
                if "java" in path_str.lower():
                    path = Path(path_str)
                    # 判斷是否已經在 bin 目錄
                    javaw_path = path / "javaw.exe" if path.name == "bin" else path / "bin" / "javaw.exe"
                    if javaw_path.is_file():
                        search_paths.add(str(javaw_path.parent))
    except Exception as e:
        logger.exception(f"PATH 環境變數尋找 java 失敗：{e}")

    # 4.where javaw 檢查
    candidates: list[tuple[str, int]] = []
    try:
        where_path = shutil.which("where")
        if not where_path:
            return candidates

        result = run_checked([where_path, "javaw"], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            for java_path_str in (result.stdout or "").strip().splitlines():
                java_path = Path(java_path_str)
                if java_path.name.lower() == "javaw.exe":
                    major = get_java_version(str(java_path))
                    if major:
                        candidates.append((str(java_path.resolve()), major))
    except Exception as e:
        logger.exception(f"搜尋 Java 失敗: {e}")

    # 5.搜尋所有目錄下的 javaw.exe
    for p_str in search_paths:
        search_path_obj = Path(p_str)
        javaw_exe = search_path_obj / "javaw.exe"
        if javaw_exe.exists():
            major = get_java_version(str(javaw_exe))
            if major:
                candidates.append((str(javaw_exe.resolve()), major))

    # 去重並按版本排序
    seen = set()
    final_results = []
    for c_path, c_major in candidates:
        if (c_path, c_major) not in seen:
            seen.add((c_path, c_major))
            final_results.append((c_path, c_major))

    final_results.sort(key=lambda x: x[1])
    logger.debug(f"找到 {len(final_results)} 個 Java 執行檔選擇：")
    for r_path, r_major in final_results:
        logger.debug(f"  {r_path} -> {r_major}")
    return final_results


# ====== Java 選擇和下載管理 ======
# 為指定版本選擇最佳 Java 路徑
def get_best_java_path(mc_version: str, required_major: int | None = None, ask_download: bool = True) -> str | None:
    """為指定 Minecraft 版本選擇最合適的 javaw.exe 路徑，找不到時詢問自動下載
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
                logger.exception(f"自動下載 Microsoft JDK {required_major} 失敗：{e}")
                UIUtils.show_error(
                    "Java 下載失敗",
                    f"自動下載 Microsoft JDK {required_major} 失敗：{e}\n請手動安裝或指定 Java 路徑。",
                    topmost=True,
                )
        else:
            UIUtils.show_info(
                "請手動下載 Java",
                "請手動安裝或指定 Java 路徑。\n建議安裝 Microsoft JDK、Adoptium、Azul、Oracle JDK 17/21 等。",
                topmost=True,
            )
    return None
