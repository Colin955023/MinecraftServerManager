#!/usr/bin/env python3
"""視窗管理器模組
提供動態視窗大小調整、位置管理和 DPI視窗管理功能
Window Manager Module
Provides window management functionality for dynamic sizing, positioning, and DPI support
"""

import ctypes
import time
import tkinter as tk
from typing import Any

from . import get_logger, get_settings_manager

logger = get_logger().bind(component="WindowManager")


class WindowManager:
    """Windows 專用視窗管理器類別，處理動態大小調整、位置管理和 DPI 縮放
    Windows-specific window manager class for handling dynamic sizing, positioning, and DPI scaling
    """

    _last_debug_time: float = 0.0

    @staticmethod
    def get_screen_info(window=None) -> dict[str, Any]:
        """取得 Windows 系統的螢幕資訊，包含 DPI 縮放和工作區域
        Get Windows system screen information including DPI scaling and work area

        Args:
            window: 可選的視窗物件，用於取得螢幕資訊

        Returns:
            Dict[str, Any]: 包含螢幕寬高、DPI 縮放、可用區域等資訊的字典

        """
        try:
            if window is None:
                # 建立臨時視窗來取得螢幕資訊
                temp_root = tk.Tk()
                temp_root.withdraw()
                screen_width = temp_root.winfo_screenwidth()
                screen_height = temp_root.winfo_screenheight()
                temp_root.destroy()
            else:
                screen_width = window.winfo_screenwidth()
                screen_height = window.winfo_screenheight()

            # Windows DPI 縮放檢測和工作區域檢測
            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware()

            # 取得真實螢幕尺寸
            actual_width = user32.GetSystemMetrics(0)
            actual_height = user32.GetSystemMetrics(1)
            dpi_scale_x = actual_width / screen_width if screen_width > 0 else 1.0
            dpi_scale_y = actual_height / screen_height if screen_height > 0 else 1.0
            dpi_scaling = max(dpi_scale_x, dpi_scale_y)

            # 取得工作區域（排除工作列）
            try:
                # 獲取工作區域尺寸
                work_area_width = user32.GetSystemMetrics(16)  # SM_CXFULLSCREEN
                work_area_height = user32.GetSystemMetrics(17)  # SM_CYFULLSCREEN
                usable_width = min(work_area_width, int(screen_width * 0.95))
                usable_height = min(work_area_height, int(screen_height * 0.9))
            except Exception:
                # 備用方案
                usable_width = int(screen_width * 0.9)
                usable_height = int(screen_height * 0.85)  # 稍微保守一些

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
            # 回傳預設值
            return {
                "width": 1920,
                "height": 1080,
                "dpi_scaling": 1.0,
                "usable_width": 1750,  # 更保守的預設值
                "usable_height": 950,  # 考慮工作列
                "center_x": 960,
                "center_y": 540,
            }

    @staticmethod
    def calculate_optimal_size(
        screen_info: dict[str, Any],
        min_width: int = 1000,
        min_height: int = 700,
    ) -> tuple[int, int]:
        """根據螢幕大小計算最佳視窗尺寸
        Calculate optimal window size based on screen dimensions.
        """
        settings = get_settings_manager()

        # 如果啟用自適應調整
        if settings.is_adaptive_sizing_enabled():
            # 根據螢幕大小動態調整
            if screen_info["width"] <= 1366:  # 小螢幕 (1366x768)
                optimal_width = min(1200, screen_info["usable_width"])
                optimal_height = min(700, screen_info["usable_height"])
            elif screen_info["width"] <= 1920:  # 標準螢幕 (1920x1080)
                optimal_width = min(1400, screen_info["usable_width"])
                optimal_height = min(900, screen_info["usable_height"])
            else:  # 大螢幕 (2K/4K)
                optimal_width = min(1600, screen_info["usable_width"])
                optimal_height = min(1000, screen_info["usable_height"])
        else:
            # 使用預設尺寸
            optimal_width = 1200
            optimal_height = 800

        # 應用 DPI 縮放
        dpi_scale = settings.get_dpi_scaling()
        optimal_width = int(optimal_width * dpi_scale)
        optimal_height = int(optimal_height * dpi_scale)

        # 確保不小於最小尺寸
        optimal_width = max(min_width, optimal_width)
        optimal_height = max(min_height, optimal_height)

        # 確保不超過螢幕可用大小
        optimal_width = min(optimal_width, screen_info["usable_width"])
        optimal_height = min(optimal_height, screen_info["usable_height"])

        return optimal_width, optimal_height

    @staticmethod
    def calculate_center_position(screen_info: dict[str, Any], width: int, height: int) -> tuple[int, int]:
        """計算視窗置中位置，考慮工作區域和多螢幕環境
        Calculate centered window position, considering work area and multi-monitor environments.
        """
        # 取得螢幕可用區域（排除工作列等）
        usable_height = screen_info.get("usable_height", screen_info["height"])

        # 計算置中位置，但稍微偏上一些以獲得更好的視覺效果
        x = max(0, (screen_info["width"] - width) // 2)
        y = max(0, (usable_height - height) // 2)

        # 確保視窗不會超出螢幕邊界
        x = min(x, screen_info["width"] - width)
        y = min(y, screen_info["height"] - height)

        # 確保視窗不會有負座標
        x = max(0, x)
        y = max(0, y)

        return x, y

    @staticmethod
    def setup_main_window(window, force_defaults: bool = False) -> None:
        """設定主視窗的大小、位置和狀態
        Setup main window size, position, and state with preference persistence.
        """
        settings = get_settings_manager()
        screen_info = WindowManager.get_screen_info(window)

        # 取得視窗設定
        window_settings = settings.get_main_window_settings()

        if force_defaults or not settings.is_remember_size_position_enabled():
            # 使用動態計算的最佳尺寸
            width, height = WindowManager.calculate_optimal_size(screen_info)
            x, y = WindowManager.calculate_center_position(screen_info, width, height)
        else:
            # 使用儲存的設定
            width = window_settings.get("width", 1200)
            height = window_settings.get("height", 800)
            x = window_settings.get("x")
            y = window_settings.get("y")

            # 如果沒有儲存位置或位置超出螢幕範圍，重新計算置中位置
            if (
                x is None
                or y is None
                or x < 0
                or y < 0
                or x + width > screen_info["width"]
                or y + height > screen_info["height"]
            ):
                x, y = WindowManager.calculate_center_position(screen_info, width, height)

        # 設定視窗幾何
        try:
            window.geometry(f"{width}x{height}+{x}+{y}")
            window.minsize(1000, 700)  # 設定最小尺寸

            # 如果記錄為最大化狀態
            if window_settings.get("maximized", False) and settings.is_remember_size_position_enabled():
                window.after(100, lambda: window.state("zoomed"))

            get_logger().bind(component="WindowState").debug(f"主視窗設定: {width}x{height}+{x}+{y}")
        except Exception as e:
            logger.exception(f"設定主視窗失敗: {e}")
            # 備用設定
            window.geometry("1200x800")
            window.minsize(1000, 700)

    @staticmethod
    def save_main_window_state(window) -> None:
        """儲存主視窗狀態
        Save main window state to preferences.
        """
        settings = get_settings_manager()

        if not settings.is_remember_size_position_enabled():
            return

        try:
            # 檢查是否最大化
            is_maximized = window.state() == "zoomed"

            if not is_maximized:
                # 取得當前視窗大小和位置
                width = window.winfo_width()
                height = window.winfo_height()
                x = window.winfo_x()
                y = window.winfo_y()

                # 儲存設定
                settings.set_main_window_settings(width, height, x, y, False)
            else:
                # 如果是最大化狀態，只更新最大化標記
                current_settings = settings.get_main_window_settings()
                settings.set_main_window_settings(
                    current_settings.get("width", 1200),
                    current_settings.get("height", 800),
                    current_settings.get("x"),
                    current_settings.get("y"),
                    True,
                )

            # 減少除錯訊息頻率：只有在沒有最近記錄時才顯示
            current_time = time.time()
            if not hasattr(WindowManager, "_last_debug_time") or current_time - WindowManager._last_debug_time > 5:
                get_logger().bind(component="WindowState").debug("已儲存主視窗狀態")
                WindowManager._last_debug_time = current_time
        except Exception as e:
            logger.exception(f"儲存主視窗狀態失敗: {e}")

    @staticmethod
    def setup_dialog_window(
        window,
        parent=None,
        width: int | None = None,
        height: int | None = None,
        center_on_parent: bool = True,
    ) -> None:
        """設定對話框視窗的大小和位置
        Setup dialog window size and position with intelligent positioning.
        """
        settings = get_settings_manager()
        screen_info = WindowManager.get_screen_info(window)

        # 如果沒有指定尺寸，使用預設值
        if width is None or height is None:
            window.update_idletasks()
            width = width or window.winfo_reqwidth()
            height = height or window.winfo_reqheight()

        # 應用 DPI 縮放
        dpi_scale = settings.get_dpi_scaling()
        width = int(width * dpi_scale)
        height = int(height * dpi_scale)

        # 確保對話框不會太大
        max_width = int(screen_info["usable_width"] * 0.8)
        max_height = int(screen_info["usable_height"] * 0.8)
        width = min(width, max_width)
        height = min(height, max_height)

        # 計算位置
        if center_on_parent and parent and settings.is_auto_center_enabled():
            try:
                # 相對於父視窗置中
                parent.update_idletasks()
                parent_x = parent.winfo_x()
                parent_y = parent.winfo_y()
                parent_width = parent.winfo_width()
                parent_height = parent.winfo_height()

                x = parent_x + (parent_width - width) // 2
                y = parent_y + (parent_height - height) // 2

                # 確保對話框在螢幕範圍內
                x = max(0, min(x, screen_info["width"] - width))
                y = max(0, min(y, screen_info["height"] - height))
            except Exception:
                # 螢幕置中作為備用
                x, y = WindowManager.calculate_center_position(screen_info, width, height)
        else:
            # 螢幕置中
            x, y = WindowManager.calculate_center_position(screen_info, width, height)

        # 設定視窗幾何
        try:
            window.geometry(f"{width}x{height}+{x}+{y}")
            logger.debug(f"對話框設定: {width}x{height}+{x}+{y}")
        except Exception as e:
            logger.exception(f"設定對話框失敗: {e}")

    @staticmethod
    def bind_window_state_tracking(window) -> None:
        """綁定視窗狀態追蹤事件
        Bind window state tracking events for automatic saving.
        """

        def on_configure(event):
            # 只處理主視窗的配置事件
            if event.widget == window:
                # 延遲儲存狀態，避免頻繁寫入
                if hasattr(window, "_save_timer"):
                    window.after_cancel(window._save_timer)
                window._save_timer = window.after(1000, lambda: WindowManager.save_main_window_state(window))

        def on_state_change(_event):
            # 立即儲存狀態變更
            WindowManager.save_main_window_state(window)

        # 綁定事件
        window.bind("<Configure>", on_configure)
        window.bind("<Map>", on_state_change)
        window.bind("<Unmap>", on_state_change)
