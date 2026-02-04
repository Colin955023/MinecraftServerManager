#!/usr/bin/env python3
"""Minecraft 伺服器管理器主程式
提供 Minecraft 伺服器的建立、管理和監控功能的主要入口點
Minecraft Server Manager Main Application
Main entry point for creating, managing and monitoring Minecraft servers
"""

import sys
import traceback
from contextlib import suppress
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

import customtkinter as ctk

from src.core import LoaderManager, MinecraftVersionManager
from src.ui import MinecraftServerManager
from src.utils import FontManager, UIUtils, get_logger, get_settings_manager

# 初始化 logger
logger = get_logger().bind(component="Main")


# ====== 訊息顯示工具 ======
def show_message(title, message, message_type="error"):
    """顯示訊息對話框；若 GUI 顯示失敗則退回主控台輸出。"""
    try:
        if message_type == "error":
            UIUtils.show_error(title, message, topmost=True)
        else:
            UIUtils.show_info(title, message, topmost=True)
        return True
    except Exception as ui_error:
        # 退回到 logger 輸出
        with suppress(Exception):
            log_message = f"{title}: {message}"
            if message_type == "error":
                logger.error(log_message)
            else:
                logger.info(log_message)
            logger.debug(f"UI 提示失敗，改用 logger。原因: {ui_error}")
        return False


# ====== 應用程式啟動 ======
def start_application():
    """啟動主應用程式，初始化管理器並設定 UI 環境。"""
    _initialize_managers()
    _setup_ui_environment()
    _launch_main_window()


def _initialize_managers():
    """初始化管理器"""
    LoaderManager()
    MinecraftVersionManager()


def _setup_ui_environment():
    """設定 UI 環境"""
    ctk.set_appearance_mode("light")

    settings = get_settings_manager()
    dpi_scaling = settings.get_dpi_scaling()
    FontManager.set_scale_factor(dpi_scaling)


def _launch_main_window():
    """啟動主視窗"""
    root = ctk.CTk()
    MinecraftServerManager(root)
    root.mainloop()


def main():
    """主程式入口點，負責整體流程控制（單一頂層錯誤處理）。"""
    try:
        start_application()
    except KeyboardInterrupt:
        show_message("程式中斷", "程式被使用者中斷\n感謝使用 Minecraft 伺服器管理器！", "info")
    except Exception:
        error_message = f"程式執行錯誤：\n\n{traceback.format_exc()}"
        show_message("執行錯誤", error_message, "error")
        sys.exit(1)


if __name__ == "__main__":
    main()
