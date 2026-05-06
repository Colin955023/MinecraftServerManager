"""原生 Qt 視窗大小、位置與狀態管理。"""

from __future__ import annotations

import time
from typing import Any, cast

from .. import get_logger, get_settings_manager
from .qt_runtime import QtCore, QtGui, QtWidgets, ensure_application, is_qobject_alive

logger = get_logger().bind(component="WindowManager")


class WindowManager:
    """Windows / Qt 視窗管理器。"""

    _last_debug_time: float = 0.0
    _last_invalid_size_log_time: float = 0.0
    _suppressed_invalid_size_logs: int = 0
    _min_tracked_width: int = 900
    _min_tracked_height: int = 600

    @staticmethod
    def _log_invalid_main_window_size(width: int, height: int) -> None:
        now = time.time()
        if now - WindowManager._last_invalid_size_log_time < 2.0:
            WindowManager._suppressed_invalid_size_logs += 1
            return
        logger_instance = get_logger().bind(component="WindowState")
        if WindowManager._suppressed_invalid_size_logs > 0:
            logger_instance.debug(f"已省略 {WindowManager._suppressed_invalid_size_logs} 筆無效主視窗尺寸訊息")
            WindowManager._suppressed_invalid_size_logs = 0
        logger_instance.debug(f"略過儲存無效主視窗尺寸: {width}x{height}")
        WindowManager._last_invalid_size_log_time = now

    @staticmethod
    def is_valid_main_window_size(width: int, height: int) -> bool:
        """檢查主視窗尺寸是否可持久化。"""
        return width >= WindowManager._min_tracked_width and height >= WindowManager._min_tracked_height

    @staticmethod
    def _screen_for_window(window: QtWidgets.QWidget | None = None) -> QtGui.QScreen | None:
        if window is not None and is_qobject_alive(window):
            screen = window.screen()
            if screen is not None:
                return screen
        app = QtWidgets.QApplication.instance()
        return app.primaryScreen() if isinstance(app, QtWidgets.QApplication) else None

    @staticmethod
    def get_screen_info(window: QtWidgets.QWidget | None = None) -> dict[str, Any]:
        """取得螢幕資訊，優先使用 Qt screen。

        Args:
            window: 用來解析所在螢幕的視窗。

        Returns:
            螢幕尺寸、可用區域與中心點。
        """
        try:
            screen = WindowManager._screen_for_window(window)
            if screen is not None:
                geometry = screen.geometry()
                available = screen.availableGeometry()
                return {
                    "width": geometry.width(),
                    "height": geometry.height(),
                    "usable_width": available.width(),
                    "usable_height": available.height(),
                    "center_x": available.center().x(),
                    "center_y": available.center().y(),
                    "available_x": available.x(),
                    "available_y": available.y(),
                }

            return {
                "width": 1920,
                "height": 1080,
                "usable_width": 1750,
                "usable_height": 950,
                "center_x": 960,
                "center_y": 540,
                "available_x": 0,
                "available_y": 0,
            }
        except Exception as e:
            logger.exception(f"取得螢幕資訊失敗: {e}")
            return {
                "width": 1920,
                "height": 1080,
                "usable_width": 1750,
                "usable_height": 950,
                "center_x": 960,
                "center_y": 540,
                "available_x": 0,
                "available_y": 0,
            }

    @staticmethod
    def calculate_optimal_size(
        screen_info: dict[str, Any], min_width: int = 900, min_height: int = 600
    ) -> tuple[int, int]:
        """根據螢幕大小計算最佳視窗尺寸。

        Args:
            screen_info: `get_screen_info` 回傳的螢幕資訊。
            min_width: 最小視窗寬度。
            min_height: 最小視窗高度。

        Returns:
            建議的視窗寬高。
        """
        settings = get_settings_manager()
        if settings.is_adaptive_sizing_enabled():
            if screen_info["width"] <= 1366:
                optimal_width = min(960, screen_info["usable_width"])
                optimal_height = min(620, screen_info["usable_height"])
            elif screen_info["width"] <= 1920:
                optimal_width = min(1350, screen_info["usable_width"])
                optimal_height = min(820, screen_info["usable_height"])
            else:
                optimal_width = min(1500, screen_info["usable_width"])
                optimal_height = min(920, screen_info["usable_height"])
        else:
            optimal_width = 1350
            optimal_height = 820
        optimal_width = max(min_width, int(optimal_width))
        optimal_height = max(min_height, int(optimal_height))
        return (min(optimal_width, screen_info["usable_width"]), min(optimal_height, screen_info["usable_height"]))

    @staticmethod
    def calculate_center_position(screen_info: dict[str, Any], width: int, height: int) -> tuple[int, int]:
        """計算視窗置中位置。

        Args:
            screen_info: `get_screen_info` 回傳的螢幕資訊。
            width: 視窗寬度。
            height: 視窗高度。

        Returns:
            視窗左上角座標。
        """
        available_x = int(screen_info.get("available_x", 0))
        available_y = int(screen_info.get("available_y", 0))
        usable_width = int(screen_info.get("usable_width", screen_info["width"]))
        usable_height = int(screen_info.get("usable_height", screen_info["height"]))
        x = available_x + max(0, (usable_width - width) // 2)
        y = available_y + max(0, (usable_height - height) // 2)
        return (x, y)

    @staticmethod
    def setup_main_window(window: QtWidgets.QWidget, force_defaults: bool = False) -> None:
        """設定主視窗大小、位置與最小尺寸。

        Args:
            window: 主視窗。
            force_defaults: 是否忽略保存的視窗狀態。
        """
        settings = get_settings_manager()
        screen_info = WindowManager.get_screen_info(window)
        window_settings = settings.get_main_window_settings()
        if force_defaults or not settings.is_remember_size_position_enabled():
            width, height = WindowManager.calculate_optimal_size(screen_info)
            x, y = WindowManager.calculate_center_position(screen_info, width, height)
        else:
            width = int(window_settings.get("width", 1350))
            height = int(window_settings.get("height", 820))
            if not WindowManager.is_valid_main_window_size(width, height):
                width, height = WindowManager.calculate_optimal_size(screen_info)
                x, y = WindowManager.calculate_center_position(screen_info, width, height)
            else:
                x_setting = window_settings.get("x")
                y_setting = window_settings.get("y")
                if (
                    x_setting is None
                    or y_setting is None
                    or int(x_setting) < 0
                    or int(y_setting) < 0
                    or int(x_setting) + width > screen_info["width"]
                    or int(y_setting) + height > screen_info["height"]
                ):
                    x, y = WindowManager.calculate_center_position(screen_info, width, height)
                else:
                    x, y = int(x_setting), int(y_setting)
        try:
            window.setMinimumSize(WindowManager._min_tracked_width, WindowManager._min_tracked_height)
            window.resize(width, height)
            window.move(x, y)
            if window_settings.get("maximized", False) and settings.is_remember_size_position_enabled():
                from .ui_utils import UIUtils

                UIUtils.schedule_debounce(window, "_window_zoom_job", 100, window.showMaximized, owner=window)
            get_logger().bind(component="WindowState").debug(f"主視窗設定: {width}x{height}+{x}+{y}")
        except Exception as e:
            logger.exception(f"設定主視窗失敗: {e}")
            window.resize(1350, 820)
            window.setMinimumSize(WindowManager._min_tracked_width, WindowManager._min_tracked_height)

    @staticmethod
    def save_main_window_state(window: QtWidgets.QWidget) -> None:
        """儲存主視窗狀態。

        Args:
            window: 要保存狀態的主視窗。
        """
        settings = get_settings_manager()

        if not is_qobject_alive(window):
            logger.debug("視窗物件無效或已被釋放，無法保存視窗狀態。")
            return

        if not settings.is_remember_size_position_enabled():
            return

        try:
            if window.isMinimized():
                return
            is_maximized = window.isMaximized()
            if not is_maximized:
                geometry = window.geometry()
                width = geometry.width()
                height = geometry.height()
                x = geometry.x()
                y = geometry.y()
                if WindowManager.is_valid_main_window_size(width, height):
                    settings.set_main_window_settings(width, height, x, y, False)
                else:
                    WindowManager._log_invalid_main_window_size(width, height)
            else:
                current_settings = settings.get_main_window_settings()
                settings.set_main_window_settings(
                    current_settings.get("width", 1350),
                    current_settings.get("height", 820),
                    current_settings.get("x"),
                    current_settings.get("y"),
                    True,
                )
            current_time = time.time()
            if current_time - WindowManager._last_debug_time > 5:
                get_logger().bind(component="WindowState").debug("已儲存主視窗狀態")
                WindowManager._last_debug_time = current_time
        except Exception as e:
            logger.exception(f"儲存主視窗狀態失敗: {e}")

    @staticmethod
    def setup_dialog_window(
        window: QtWidgets.QWidget,
        parent: QtWidgets.QWidget | None = None,
        width: int | None = None,
        height: int | None = None,
        center_on_parent: bool = True,
    ) -> None:
        """設定 dialog 大小與位置。

        Args:
            window: 要設定的對話框視窗。
            parent: 父視窗。
            width: 目標寬度；未指定時使用 sizeHint。
            height: 目標高度；未指定時使用 sizeHint。
            center_on_parent: 是否優先置中於父視窗。
        """
        settings = get_settings_manager()
        screen_info = WindowManager.get_screen_info(window)
        if width is None or height is None:
            hint = window.sizeHint()
            width = width or max(hint.width(), 1)
            height = height or max(hint.height(), 1)
        width = min(max(1, int(width)), max(160, int(screen_info["usable_width"] - 16)))
        height = min(max(1, int(height)), max(120, int(screen_info["usable_height"] - 16)))
        if center_on_parent and parent is not None and is_qobject_alive(parent) and settings.is_auto_center_enabled():
            parent_geometry = parent.frameGeometry()
            x = parent_geometry.x() + (parent_geometry.width() - width) // 2
            y = parent_geometry.y() + (parent_geometry.height() - height) // 2
        else:
            x, y = WindowManager.calculate_center_position(screen_info, width, height)
        try:
            window.resize(width, height)
            window.move(max(0, x), max(0, y))
            logger.debug(f"對話框設定: {width}x{height}+{x}+{y}")
        except Exception as e:
            logger.exception(f"設定對話框失敗: {e}")

    @staticmethod
    def bind_window_state_tracking(window: QtWidgets.QWidget) -> None:
        """綁定 Qt 視窗狀態追蹤事件。

        Args:
            window: 要追蹤移動、縮放與顯示事件的視窗。
        """
        if not is_qobject_alive(window):
            return
        ensure_application()
        tracker = _WindowStateTracker(window)
        window.installEventFilter(tracker)
        window_any = cast(Any, window)
        window_any._msm_window_state_tracker = tracker


class _WindowStateTracker(QtCore.QObject):
    """以 Qt event filter 儲存主視窗狀態。"""

    def __init__(self, window: QtWidgets.QWidget) -> None:
        super().__init__(window)
        self._window = window

    def eventFilter(self, watched, event) -> bool:
        if event.type() in {
            QtCore.QEvent.Type.Resize,
            QtCore.QEvent.Type.Move,
            QtCore.QEvent.Type.WindowStateChange,
            QtCore.QEvent.Type.Show,
        }:
            from .ui_utils import UIUtils

            UIUtils.schedule_debounce(
                self._window,
                "_save_timer",
                1000,
                lambda: WindowManager.save_main_window_state(self._window),
                owner=self,
            )
        return super().eventFilter(watched, event)
