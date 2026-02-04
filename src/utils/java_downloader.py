#!/usr/bin/env python3
"""Java 下載工具模組
提供 Java 安裝包下載和管理功能，支援 Microsoft JDK 的自動下載與安裝
Java Download Utility Module
Provides functions to download and manage Java installations, supports Microsoft JDK automatic download and installation
"""

from . import (
    PathUtils,
    SubprocessUtils,
    UIUtils,
    get_logger,
)

logger = get_logger().bind(component="JavaDownloader")


class JavaDownloader:
    """Java 下載管理類別 (Static Class)"""

    @staticmethod
    def _is_winget_available():
        winget_path = PathUtils.find_executable("winget")
        if not winget_path:
            return False
        try:
            SubprocessUtils.run_checked(
                [winget_path, "--version"], check=True, stdout=SubprocessUtils.DEVNULL, stderr=SubprocessUtils.DEVNULL
            )
            return True
        except Exception:
            return False

    @staticmethod
    def install_java_with_winget(major: int):
        if not JavaDownloader._is_winget_available():
            UIUtils.show_error("找不到 winget 工具", "請手動安裝 Java 或安裝 winget 工具。", topmost=True)
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
            SubprocessUtils.run_checked(winget_cmd, check=True)
        except SubprocessUtils.CalledProcessError as e:
            logger.exception(f"winget 安裝失敗: {e}")
            UIUtils.show_error("winget 安裝失敗", f"winget 執行失敗，請檢查錯誤訊息：\n{e}", topmost=True)
            raise Exception(f"執行 winget 失敗: {e}") from e
        except Exception as e:
            logger.exception(f"winget 執行異常: {e}")
            UIUtils.show_error("winget 執行異常", f"執行 winget 發生例外：{e}", topmost=True)
            raise
