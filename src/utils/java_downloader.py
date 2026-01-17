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
from .log_utils import LogUtils

# 只負責安裝
def install_java_with_winget(major: int):
    def is_winget_available():
        try:
            subprocess.run(
                ["winget", "--version"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            return False

    if not is_winget_available():
        UIUtils.show_error(
            "找不到 winget 工具", "請手動安裝 Java 或安裝 winget 工具。", topmost=True
        )
        raise Exception("找不到 winget，請手動安裝 Java 或安裝 winget 工具。")
    if major == 8:
        pkg = "Oracle.JavaRuntimeEnvironment"
    elif major in (11, 16, 17, 21):
        pkg = f"Microsoft.OpenJDK.{major}"
    else:
        UIUtils.show_error(
            "不支援的 Java 主要版本",
            f"不支援的 Java 主要版本: {major}，請手動安裝。",
            topmost=True,
        )
        raise Exception(f"不支援的 Java 主要版本: {major}，請手動安裝。")
    winget_cmd = [
        "winget",
        "install",
        "--accept-package-agreements",
        "--accept-source-agreements",
        pkg,
    ]
    try:
        # 直接在主程式同步執行 winget，安裝過程會在主程式 console 顯示
        subprocess.run(winget_cmd, shell=False, check=True)
    except subprocess.CalledProcessError as e:
        LogUtils.error_exc(f"winget 安裝失敗: {e}", "JavaDownloader", e)
        UIUtils.show_error(
            "winget 安裝失敗", f"winget 執行失敗，請檢查錯誤訊息：\n{e}", topmost=True
        )
        raise Exception(f"執行 winget 失敗: {e}")
    except Exception as e:
        LogUtils.error_exc(f"winget 執行異常: {e}", "JavaDownloader", e)
        UIUtils.show_error(
            "winget 執行異常", f"執行 winget 發生例外：{e}", topmost=True
        )
        raise
