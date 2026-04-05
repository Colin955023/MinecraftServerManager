"""視窗管理器模組
提供動態視窗大小調整、位置管理與 DPI 支援功能。
"""

import contextlib
import time
from typing import Any
from .. import SystemUtils
from .. import get_logger
from .. import get_settings_manager

logger = get_logger().bind(component="WindowManager")


class WindowManager:
    """Windows 專用視窗管理器類別，處理動態大小調整、位置管理和 DPI 縮放"""

    _last_debug_time: float = 0.0
    _last_invalid_size_log_time: float = 0.0
    _suppressed_invalid_size_logs: int = 0
    _min_tracked_width: int = 1000
    _min_tracked_height: int = 700

    @staticmethod
    def _log_invalid_main_window_size(width: int, height: int) -> None:
        """記錄未通過 `is_valid_main_window_size` 的主視窗尺寸。

        此方法僅負責節流記錄，避免視窗連續觸發 configure 事件時刷爆日誌。
        """
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
        """檢查主視窗尺寸是否為可持久化的有效值。

        判斷依據為 `_min_tracked_width` / `_min_tracked_height`，
        用來排除初始化與佈局過程中的暫態尺寸。
        """
        return width >= WindowManager._min_tracked_width and height >= WindowManager._min_tracked_height

    @staticmethod
    def get_screen_info(window=None) -> dict[str, Any]:
        """取得 Windows 系統的螢幕資訊，包含 DPI 縮放和工作區域。

        Args:
            window: 可選的視窗物件；未提供時改用系統指標。

        Returns:
            包含螢幕寬高、DPI、可用區域與中心點的資訊字典。
        """
        try:
            if window is None:
                SystemUtils.set_process_dpi_aware()
                screen_width = SystemUtils.get_system_metrics(0)
                screen_height = SystemUtils.get_system_metrics(1)
                if screen_width <= 0 or screen_height <= 0:
                    screen_width = 1920
                    screen_height = 1080
            else:
                screen_width = window.winfo_screenwidth()
                screen_height = window.winfo_screenheight()
            SystemUtils.set_process_dpi_aware()
            actual_width = SystemUtils.get_system_metrics(0)
            actual_height = SystemUtils.get_system_metrics(1)
            dpi_scale_x = actual_width / screen_width if screen_width > 0 else 1.0
            dpi_scale_y = actual_height / screen_height if screen_height > 0 else 1.0
            dpi_scaling = max(dpi_scale_x, dpi_scale_y)
            try:
                work_area_width = SystemUtils.get_system_metrics(16)
                work_area_height = SystemUtils.get_system_metrics(17)
                usable_width = min(work_area_width, int(screen_width * 0.95))
                usable_height = min(work_area_height, int(screen_height * 0.9))
            except Exception:
                usable_width = int(screen_width * 0.9)
                usable_height = int(screen_height * 0.85)
            return {
                "width": screen_width,
                "height": screen_height,
                "dpi_scaling": dpi_scaling,
                "usable_width": usable_width,
                "usable_height": usable_height,
                "center_x": screen_width // 2,
                "center_y": screen_height // 2,
            }
        except Exception as e:
            logger.exception(f"取得螢幕資訊失敗: {e}")
            return {
                "width": 1920,
                "height": 1080,
                "dpi_scaling": 1.0,
                "usable_width": 1750,
                "usable_height": 950,
                "center_x": 960,
                "center_y": 540,
            }

    @staticmethod
    def calculate_optimal_size(
        screen_info: dict[str, Any], min_width: int = 1000, min_height: int = 700
    ) -> tuple[int, int]:
        """根據螢幕大小計算最佳視窗尺寸。

        Args:
            screen_info: 螢幕資訊字典。
            min_width: 最小寬度。
            min_height: 最小高度。

        Returns:
            最佳視窗寬高。
        """
        settings = get_settings_manager()
        if settings.is_adaptive_sizing_enabled():
            if screen_info["width"] <= 1366:
                optimal_width = min(1200, screen_info["usable_width"])
                optimal_height = min(700, screen_info["usable_height"])
            elif screen_info["width"] <= 1920:
                optimal_width = min(1400, screen_info["usable_width"])
                optimal_height = min(900, screen_info["usable_height"])
            else:
                optimal_width = min(1600, screen_info["usable_width"])
                optimal_height = min(1000, screen_info["usable_height"])
        else:
            optimal_width = 1200
            optimal_height = 800
        dpi_scale = settings.get_dpi_scaling()
        optimal_width = int(optimal_width * dpi_scale)
        optimal_height = int(optimal_height * dpi_scale)
        optimal_width = max(min_width, optimal_width)
        optimal_height = max(min_height, optimal_height)
        optimal_width = min(optimal_width, screen_info["usable_width"])
        optimal_height = min(optimal_height, screen_info["usable_height"])
        return (optimal_width, optimal_height)

    @staticmethod
    def calculate_center_position(screen_info: dict[str, Any], width: int, height: int) -> tuple[int, int]:
        """計算視窗置中位置，考慮工作區域和多螢幕環境。

        Args:
            screen_info: 螢幕資訊字典。
            width: 視窗寬度。
            height: 視窗高度。

        Returns:
            置中後的 x 與 y 座標。
        """
        usable_height = screen_info.get("usable_height", screen_info["height"])
        x = max(0, (screen_info["width"] - width) // 2)
        y = max(0, (usable_height - height) // 2)
        x = min(x, screen_info["width"] - width)
        y = min(y, screen_info["height"] - height)
        x = max(0, x)
        y = max(0, y)
        return (x, y)

    @staticmethod
    def setup_main_window(window, force_defaults: bool = False) -> None:
        """設定主視窗的大小、位置和狀態。

        Args:
            window: 主要視窗。
            force_defaults: 是否強制使用預設大小與位置。
        """
        settings = get_settings_manager()
        screen_info = WindowManager.get_screen_info(window)
        window_settings = settings.get_main_window_settings()
        if force_defaults or not settings.is_remember_size_position_enabled():
            width, height = WindowManager.calculate_optimal_size(screen_info)
            x, y = WindowManager.calculate_center_position(screen_info, width, height)
        else:
            width = window_settings.get("width", 1200)
            height = window_settings.get("height", 800)
            x_setting = window_settings.get("x")
            y_setting = window_settings.get("y")
            if (
                x_setting is None
                or y_setting is None
                or x_setting < 0
                or (y_setting < 0)
                or (x_setting + width > screen_info["width"])
                or (y_setting + height > screen_info["height"])
            ):
                x, y = WindowManager.calculate_center_position(screen_info, width, height)
            else:
                x, y = x_setting, y_setting
        try:
            window.geometry(f"{width}x{height}+{x}+{y}")
            window.minsize(WindowManager._min_tracked_width, WindowManager._min_tracked_height)
            if window_settings.get("maximized", False) and settings.is_remember_size_position_enabled():
                from .ui_utils import UIUtils

                UIUtils.schedule_debounce(window, "_window_zoom_job", 100, lambda: window.state("zoomed"), owner=window)
            get_logger().bind(component="WindowState").debug(f"主視窗設定: {width}x{height}+{x}+{y}")
        except Exception as e:
            logger.exception(f"設定主視窗失敗: {e}")
            window.geometry("1200x800")
            window.minsize(WindowManager._min_tracked_width, WindowManager._min_tracked_height)

    @staticmethod
    def save_main_window_state(window) -> None:
        """儲存主視窗狀態。

        Args:
            window: 主要視窗。
        """
        settings = get_settings_manager()
        if not settings.is_remember_size_position_enabled():
            return
        try:
            window.update_idletasks()
            is_maximized = window.state() == "zoomed"
            if window.state() == "iconic":
                return
            if not is_maximized:
                width = window.winfo_width()
                height = window.winfo_height()
                x = window.winfo_x()
                y = window.winfo_y()
                if WindowManager.is_valid_main_window_size(width, height):
                    settings.set_main_window_settings(width, height, x, y, False)
                else:
                    WindowManager._log_invalid_main_window_size(width, height)
            else:
                current_settings = settings.get_main_window_settings()
                settings.set_main_window_settings(
                    current_settings.get("width", 1200),
                    current_settings.get("height", 800),
                    current_settings.get("x"),
                    current_settings.get("y"),
                    True,
                )
            current_time = time.time()
            if not hasattr(WindowManager, "_last_debug_time") or current_time - WindowManager._last_debug_time > 5:
                get_logger().bind(component="WindowState").debug("已儲存主視窗狀態")
                WindowManager._last_debug_time = current_time
        except Exception as e:
            logger.exception(f"儲存主視窗狀態失敗: {e}")

    @staticmethod
    def setup_dialog_window(
        window, parent=None, width: int | None = None, height: int | None = None, center_on_parent: bool = True
    ) -> None:
        """設定對話框視窗的大小和位置。

        Args:
            window: 對話框視窗。
            parent: 父視窗。
            width: 視窗寬度。
            height: 視窗高度。
            center_on_parent: 是否以父視窗為基準置中。
        """
        settings = get_settings_manager()
        screen_info = WindowManager.get_screen_info(window)
        if width is None or height is None:
            window.update_idletasks()
            width = width or window.winfo_reqwidth()
            height = height or window.winfo_reqheight()
        dpi_scale = settings.get_dpi_scaling()
        width = int(width * dpi_scale)
        height = int(height * dpi_scale)
        max_width = max(320, int(screen_info["usable_width"] - 32))
        max_height = max(240, int(screen_info["usable_height"] - 32))
        width = min(width, max_width)
        height = min(height, max_height)
        if center_on_parent and parent and settings.is_auto_center_enabled():
            try:
                parent.update_idletasks()
                parent_x = parent.winfo_x()
                parent_y = parent.winfo_y()
                parent_width = parent.winfo_width()
                parent_height = parent.winfo_height()
                x = parent_x + (parent_width - width) // 2
                y = parent_y + (parent_height - height) // 2
                x = max(0, min(x, screen_info["width"] - width))
                y = max(0, min(y, screen_info["height"] - height))
            except Exception:
                x, y = WindowManager.calculate_center_position(screen_info, width, height)
        else:
            x, y = WindowManager.calculate_center_position(screen_info, width, height)
        try:
            window.geometry(f"{width}x{height}+{x}+{y}")
            logger.debug(f"對話框設定: {width}x{height}+{x}+{y}")
        except Exception as e:
            logger.exception(f"設定對話框失敗: {e}")

    @staticmethod
    def bind_window_state_tracking(window) -> None:
        """綁定視窗狀態追蹤事件。

        Args:
            window: 要追蹤狀態的視窗。
        """
        from .ui_utils import UIUtils

        def on_configure(event):
            if event.widget == window:
                with contextlib.suppress(Exception):
                    if not window.winfo_viewable():
                        return
                UIUtils.schedule_debounce(
                    window, "_save_timer", 1000, lambda: WindowManager.save_main_window_state(window), owner=window
                )

        def on_state_change(_event):
            with contextlib.suppress(Exception):
                if not window.winfo_viewable():
                    return
            WindowManager.save_main_window_state(window)

        window.bind("<Configure>", on_configure)
        window.bind("<Map>", on_state_change)
        window.bind("<Unmap>", on_state_change)
