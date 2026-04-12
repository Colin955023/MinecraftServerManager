"""Minecraft 伺服器管理器主程式
提供 Minecraft 伺服器的建立、管理和監控功能的主要入口點
Minecraft Server Manager Main Application
Main entry point for creating, managing and monitoring Minecraft servers
"""

import ctypes
import sys
import traceback
from contextlib import suppress
from pathlib import Path
import customtkinter as ctk

if __name__ == "__main__" and __package__ is None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.core import LoaderManager, MinecraftVersionManager
from src.ui import FontManager, MinecraftServerManager, ui_config
from src.utils import PathUtils, UIUtils, get_logger, get_settings_manager, record_and_mark

logger = get_logger().bind(component="Main")


def show_message(title, message, message_type="error"):
    """統一的訊息提示入口，提供 UI 與 logger fallback 機制"""
    try:
        if message_type == "error":
            UIUtils.show_error(title, message, topmost=True)
        elif message_type == "warning":
            UIUtils.show_warning(title, message, topmost=True)
        else:
            UIUtils.show_info(title, message, topmost=True)
        return True
    except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as ui_error:
        with suppress(Exception):
            log_message = f"{title}: {message}"
            if message_type == "error":
                logger.error(log_message)
            elif message_type == "warning":
                logger.warning(log_message)
            else:
                logger.info(log_message)
            logger.debug(f"UI 提示失敗，改用 logger。原因: {ui_error}")
        return False


def start_application():
    """初始化應用程式並啟動主視窗"""
    _initialize_managers()
    try:
        settings = get_settings_manager()
        if settings.get("auto_prune_markers_on_startup"):
            PathUtils.auto_prune_markers()
    except Exception as e:
        with suppress(Exception):
            record_and_mark(
                e,
                marker_path=PathUtils.get_project_root(),
                reason="auto_prune_markers failed",
                details={"context": "startup"},
            )
        get_logger().bind(component="Startup").exception("auto_prune_markers failed")
    _setup_ui_environment()
    _launch_main_window()


def _initialize_managers():
    """初始化全域管理器實例"""
    LoaderManager()
    MinecraftVersionManager()


def _setup_ui_environment():
    """設定 UI 環境和主題"""
    # 初始化 customtkinter 主題配置
    ui_config.initialize_ui_theme()

    settings = get_settings_manager()
    dpi_scaling = settings.get_dpi_scaling()
    FontManager.set_scale_factor(dpi_scaling)


def _launch_main_window():
    """建立並啟動主應用程式視窗"""
    root = ctk.CTk()
    MinecraftServerManager(root)
    root.mainloop()


def main():
    """應用程式入口點，處理啟動過程中的例外"""
    # 註冊 Mutex 供 Inno Setup 偵測應用程式程式執行狀態
    mutex_name = "MinecraftServerManagerMutex"
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW(None, False, mutex_name)
    except Exception as e:
        logger.debug(f"Failed to create mutex: {e}")

    try:
        start_application()
    except KeyboardInterrupt:
        show_message("程式中斷", "程式被使用者中斷\n感謝使用 Minecraft 伺服器管理器！", "info")
    except (RuntimeError, OSError, ValueError, TypeError, AttributeError):
        error_message = f"程式執行錯誤：\n\n{traceback.format_exc()}"
        show_message("執行錯誤", error_message, "error")
        sys.exit(1)


if __name__ == "__main__":
    main()
