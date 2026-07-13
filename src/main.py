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
from typing import Any, cast

if __name__ == "__main__" and __package__ is None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.core import LoaderManager, MinecraftVersionManager
from src.ui import MinecraftServerManager
from src.utils import (
    PathUtils,
    QtCore,
    QtWidgets,
    UIUtils,
    ensure_application,
    get_logger,
    get_settings_manager,
    initialize_ui_theme,
    record_and_mark,
)

logger = get_logger().bind(component="Main")


def _install_global_exception_logging() -> None:
    """Log uncaught Qt slot exceptions that happen after app.exec() starts."""
    previous_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_traceback):
        logger.error(
            "未處理例外",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        previous_hook(exc_type, exc_value, exc_traceback)

    sys.excepthook = _hook


def _install_qt_warning_filter() -> None:
    """Suppress a known harmless Qt stylesheet parse warning emitted by combo-box subclasses."""

    def _handler(_mode, _context, message):
        msg_str = str(message or "")
        if msg_str == "Could not parse application stylesheet":
            logger.debug(f"已抑制 Qt 樣式表警告: {msg_str}")
            return
        stderr = sys.__stderr__
        if stderr is not None:
            stderr.write(f"{message}\n")

    QtCore.qInstallMessageHandler(_handler)


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
    _install_global_exception_logging()
    _install_qt_warning_filter()
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
    settings = get_settings_manager()
    initialize_ui_theme(settings.get_theme_mode())


def _launch_main_window():
    """建立並啟動主應用程式視窗"""
    app = ensure_application()
    root = _ApplicationRoot()
    manager = MinecraftServerManager(root)
    root_any = cast(Any, root)
    root_any._msm_manager = manager
    root.show()
    app.exec()


class _ApplicationRoot(QtWidgets.QWidget):
    """主應用程式根視窗。"""

    def closeEvent(self, event) -> None:
        """處理 Qt 視窗關閉事件。"""
        manager = getattr(self, "_msm_manager", None)
        if manager is None or getattr(self, "_msm_closing", False):
            event.accept()
            return
        event.ignore()
        manager.on_closing()


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
    except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as _:
        error_message = f"程式執行錯誤：\n\n{traceback.format_exc()}"
        show_message("執行錯誤", error_message, "error")
        sys.exit(1)


if __name__ == "__main__":
    main()
