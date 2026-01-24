#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minecraft 伺服器管理器主程式
提供 Minecraft 伺服器的建立、管理和監控功能的主要入口點
Minecraft Server Manager Main Application
Main entry point for creating, managing and monitoring Minecraft servers
"""

# ====== 標準函式庫 ======
import sys
import traceback
from pathlib import Path

# 讓 `python src/main.py` 與打包工具在入口檔位於 src/ 時仍可解析 `import src.*`
# 注意：標準執行方式仍建議使用 `python -m src.main`
if __name__ == "__main__" and __package__ is None:
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


# ====== 第三方套件 ======
import customtkinter as ctk

# ====== 專案內部模組 ======
from src.core import LoaderManager, MinecraftVersionManager
from src.ui import MinecraftServerManager
from src.utils import UIUtils, get_settings_manager, set_ui_scale_factor
from src.utils.logger import get_logger

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
    except Exception:
        # 退回到 logger 輸出
        try:
            if message_type == "error":
                logger.error(f"{title}: {message}")
            else:
                logger.info(f"{title}: {message}")
        except Exception:
            pass
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
    set_ui_scale_factor(dpi_scaling)


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
        show_message(
            "程式中斷", "程式被使用者中斷\n感謝使用 Minecraft 伺服器管理器！", "info"
        )
    except Exception:
        error_message = f"程式執行錯誤：\n\n{traceback.format_exc()}"
        show_message("執行錯誤", error_message, "error")
        sys.exit(1)


if __name__ == "__main__":
    main()
