#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Java 下載工具模組
提供 Java 安裝包下載和管理功能，支援 Microsoft JDK 的自動下載與安裝
Java Download Utility Module
Provides functions to download and manage Java installations, supports Microsoft JDK automatic download and installation
"""
# ====== 標準函式庫 ======
import subprocess
# ====== 專案內部模組 ======
from .ui_utils import UIUtils

# 只負責安裝
def install_java_with_winget(major: int):
    def is_winget_available():
        try:
            subprocess.run(["winget", "--version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False
    if not is_winget_available():
        UIUtils.show_error("找不到 winget 工具", "請手動安裝 Java 或安裝 winget 工具。", topmost=True)
        raise Exception("找不到 winget，請手動安裝 Java 或安裝 winget 工具。")
    if major == 8:
        pkg = "Oracle.JavaRuntimeEnvironment"
    elif major in (11, 16, 17, 21):
        pkg = f"Microsoft.OpenJDK.{major}"
    else:
        UIUtils.show_error("不支援的 Java 主要版本", f"不支援的 Java 主要版本: {major}，請手動安裝。", topmost=True)
        raise Exception(f"不支援的 Java 主要版本: {major}，請手動安裝。")
    winget_cmd = f'start /wait cmd /c "winget install --accept-package-agreements --accept-source-agreements {pkg}"'
    try:
        subprocess.run(winget_cmd, shell=False, check=True)
    except Exception as e:
        UIUtils.show_error("winget 安裝失敗", f"執行 winget 失敗: {e}", topmost=True)
        raise
