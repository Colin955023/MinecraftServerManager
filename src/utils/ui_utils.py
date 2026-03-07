#!/usr/bin/env python3
"""UI 工具函數
提供常用的界面元件和工具函數，避免重複程式碼
"""

import contextlib
import os
import queue
import threading
import time
import tkinter as tk
import webbrowser
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, scrolledtext
from typing import Any, Final

import customtkinter as ctk

from . import (
    FontManager,
    PathUtils,
    SubprocessUtils,
    WindowManager,
    get_logger,
)

logger = get_logger().bind(component="UIUtils")

ctk.set_appearance_mode("light")  # 固定使用淺色主題
ctk.set_default_color_theme("blue")  # 淺色藍色主題


# ====== UI 設計 Token 系統 ======
class FontSize:
    """字型大小常數"""

    # 文字大小
    TINY: Final[int] = 10  # 極小文字（小圖示、提示）
    SMALL: Final[int] = 11  # 小文字（下拉選單、次要資訊）
    NORMAL: Final[int] = 12  # 一般文字（說明文字、選項）
    SMALL_PLUS: Final[int] = 13  # 小一點的中等文字
    MEDIUM: Final[int] = 14  # 中等文字（次要標籤、輸入提示）
    NORMAL_PLUS: Final[int] = 15  # 稍大的一般文字
    INPUT: Final[int] = 16  # 輸入欄位（表單輸入）
    LARGE: Final[int] = 18  # 大文字（重要資訊、表格標題、按鈕）

    # 標題大小
    HEADING_SMALL: Final[int] = 20  # 小標題（區段標題）
    HEADING_MEDIUM: Final[int] = 21  # 中標題（主要區段）
    HEADING_SMALL_PLUS: Final[int] = 22  # 小標題加強
    HEADING_LARGE: Final[int] = 24  # 大標題（頁面副標題）
    HEADING_XLARGE: Final[int] = 27  # 超大標題（頁面主標題）

    # 特殊用途
    CONSOLE: Final[int] = 11  # 終端機輸出
    ICON: Final[int] = 21  # 圖示符號


class Colors:
    """顏色常數（支援 light/dark 模式）"""

    # 主要按鈕顏色（藍色系）
    BUTTON_PRIMARY: Final[tuple[str, str]] = ("#2563eb", "#1d4ed8")
    BUTTON_PRIMARY_HOVER: Final[tuple[str, str]] = ("#1d4ed8", "#1e40af")
    BUTTON_PRIMARY_ACTIVE: Final[tuple[str, str]] = ("#1d4ed8", "#1d4ed8")
    BUTTON_PRIMARY_ACTIVE_HOVER: Final[tuple[str, str]] = ("#1e40af", "#1e40af")
    BUTTON_INFO: Final[tuple[str, str]] = ("#3b82f6", "#2563eb")
    BUTTON_INFO_HOVER: Final[tuple[str, str]] = ("#2563eb", "#1d4ed8")
    BUTTON_SUCCESS: Final[tuple[str, str]] = ("#059669", "#047857")
    BUTTON_SUCCESS_HOVER: Final[tuple[str, str]] = ("#047857", "#065f46")
    BUTTON_SECONDARY: Final[tuple[str, str]] = ("#6b7280", "#4b5563")
    BUTTON_SECONDARY_HOVER: Final[tuple[str, str]] = ("#4b5563", "#374151")
    BUTTON_PURPLE: Final[tuple[str, str]] = ("#8b5cf6", "#7c3aed")
    BUTTON_PURPLE_HOVER: Final[tuple[str, str]] = ("#7c3aed", "#6d28d9")
    BUTTON_PURPLE_DARK: Final[tuple[str, str]] = ("#7c3aed", "#6d28d9")
    BUTTON_PURPLE_DARK_HOVER: Final[tuple[str, str]] = ("#6d28d9", "#5b21b6")

    # 警告按鈕顏色（橙色系）
    BUTTON_WARNING: Final[tuple[str, str]] = ("#f59e0b", "#d97706")
    BUTTON_WARNING_HOVER: Final[tuple[str, str]] = ("#d97706", "#b45309")

    # 危險按鈕顏色（紅色系）
    BUTTON_DANGER: Final[tuple[str, str]] = ("#dc2626", "#b91c1c")
    BUTTON_DANGER_HOVER: Final[tuple[str, str]] = ("#b91c1c", "#991b1b")

    # 文字顏色
    TEXT_PRIMARY: Final[tuple[str, str]] = ("#1f2937", "#1f2937")  # 主要文字
    TEXT_PRIMARY_CONTRAST: Final[tuple[str, str]] = ("#1f2937", "#e5e7eb")  # 高對比主要文字
    TEXT_HEADING: Final[tuple[str, str]] = ("#111827", "#f3f4f6")  # 標題文字
    TEXT_SECONDARY: Final[tuple[str, str]] = ("#6b7280", "#6b7280")  # 次要文字
    TEXT_MUTED: Final[tuple[str, str]] = ("#4b5563", "#9ca3af")  # 弱化提示文字
    TEXT_TERTIARY: Final[tuple[str, str]] = ("#a0aec0", "#a0aec0")  # 更淡的輔助文字
    TEXT_ON_LIGHT: Final[str] = "#000000"  # 淺色背景文字
    TEXT_ON_DARK: Final[str] = "#ffffff"  # 深色背景文字
    TEXT_LINK: Final[tuple[str, str]] = ("blue", "#4dabf7")  # 連結文字
    TEXT_SUCCESS: Final[tuple[str, str]] = ("green", "#10b981")  # 成功文字
    TEXT_ERROR: Final[tuple[str, str]] = ("#e53e3e", "#e53e3e")  # 錯誤文字
    TEXT_WARNING: Final[tuple[str, str]] = ("#b45309", "#d97706")  # 警示文字

    # 背景顏色
    BG_PRIMARY: Final[tuple[str, str]] = ("#ffffff", "#ffffff")  # 主要背景（白色）
    BG_SECONDARY: Final[tuple[str, str]] = ("#f3f4f6", "#f3f4f6")  # 次要背景
    BG_ALERT: Final[tuple[str, str]] = ("#fffbe6", "#2d2a1f")  # 提示/警告背景
    BG_CONSOLE: Final[str] = "#000000"  # 終端機背景
    BG_LISTBOX_LIGHT: Final[str] = "#f8fafc"  # 清單背景（淺色）
    BG_LISTBOX_DARK: Final[str] = "#2b2b2b"  # 清單背景（深色）
    BG_TOOLTIP: Final[str] = "#2b2b2b"  # 工具提示背景
    BG_ROW_SOFT_LIGHT: Final[str] = "#f1f5f9"  # 清單交錯背景（淺色柔和）
    BG_LISTBOX_ALT_LIGHT: Final[str] = "#e2e8f0"  # 清單交錯背景（淺色）
    BG_LISTBOX_ALT_DARK: Final[str] = "#363636"  # 清單交錯背景（深色）

    # 邊框顏色
    BORDER_LIGHT: Final[tuple[str, str]] = ("#d1d5db", "#d1d5db")  # 淺色邊框
    BORDER_MEDIUM: Final[tuple[str, str]] = ("#9ca3af", "#9ca3af")  # 中等邊框

    # 下拉選單顏色
    DROPDOWN_BG: Final[tuple[str, str]] = ("#ffffff", "#ffffff")
    DROPDOWN_HOVER: Final[tuple[str, str]] = ("#f3f4f6", "#f3f4f6")
    DROPDOWN_BUTTON: Final[tuple[str, str]] = ("#e5e7eb", "#e5e7eb")
    DROPDOWN_BUTTON_HOVER: Final[tuple[str, str]] = ("#d1d5db", "#d1d5db")

    # 特殊顏色
    CONSOLE_TEXT: Final[str] = "#00ff00"  # 終端機文字（綠色）
    SCROLLBAR_BUTTON: Final[tuple[str, str]] = ("#333333", "#333333")  # 滾動條按鈕
    SCROLLBAR_BUTTON_HOVER: Final[tuple[str, str]] = ("#555555", "#555555")  # 滾動條按鈕懸停
    SELECT_BG: Final[str] = "#1f538d"  # 選擇背景
    PROGRESS_ACCENT: Final[tuple[str, str]] = ("#22d3ee", "#4ade80")
    PROGRESS_TRACK: Final[tuple[str, str]] = ("#e5e7eb", "#374151")


class Spacing:
    """間距常數（像素）"""

    XS: Final[int] = 4  # 極小間距
    SMALL: Final[int] = 8  # 小間距
    MEDIUM: Final[int] = 12  # 中等間距
    LARGE: Final[int] = 16  # 大間距
    XL: Final[int] = 20  # 超大間距
    XXL: Final[int] = 24  # 特大間距


class Sizes:
    """尺寸常數"""

    # 按鈕尺寸
    BUTTON_HEIGHT: Final[int] = 36  # 標準按鈕高度
    BUTTON_HEIGHT_MEDIUM: Final[int] = 35  # 中等按鈕高度
    BUTTON_HEIGHT_LARGE: Final[int] = 40  # 大按鈕高度（主要表單動作）
    BUTTON_HEIGHT_SMALL: Final[int] = 28  # 小按鈕高度
    BUTTON_WIDTH_PRIMARY: Final[int] = 140  # 主要動作按鈕寬度
    BUTTON_WIDTH_SECONDARY: Final[int] = 120  # 次要動作按鈕寬度
    BUTTON_WIDTH_COMPACT: Final[int] = 80  # 緊湊按鈕寬度
    BUTTON_WIDTH_SMALL: Final[int] = 100  # 小型按鈕寬度
    BUTTON_HEIGHT_EXPORT: Final[int] = 25  # 匯出列小按鈕高度
    ICON_BUTTON: Final[int] = 20  # 小型圖示按鈕/標籤尺寸

    # 輸入欄位尺寸
    INPUT_HEIGHT: Final[int] = 32  # 標準輸入欄位高度
    INPUT_WIDTH: Final[int] = 300  # 標準輸入欄位寬度
    INPUT_FIELD_WIDTH_CHARS: Final[int] = 32  # 標準文字輸入欄寬度（字符數）
    SPINBOX_WIDTH_CHARS: Final[int] = 14  # Spinbox輸入欄寬度（字符數）
    WRAP_LENGTH_MEDIUM: Final[int] = 400  # 中型說明文字換行寬度
    WRAP_LENGTH_WIDE: Final[int] = 900  # 大型說明文字換行寬度

    # 下拉選單尺寸
    DROPDOWN_HEIGHT: Final[int] = 30  # 下拉選單高度
    DROPDOWN_WIDTH: Final[int] = 280  # 下拉選單寬度
    DROPDOWN_COMPACT_WIDTH: Final[int] = 200  # 緊湊型下拉選單寬度
    DROPDOWN_FILTER_WIDTH: Final[int] = 100  # 篩選下拉選單寬度
    DROPDOWN_MAX_HEIGHT: Final[int] = 200  # 下拉選單最大高度
    DROPDOWN_ITEM_HEIGHT: Final[int] = 30  # 下拉選單項目高度

    # 管理頁 Tree 欄寬
    SERVER_TREE_COL_NAME: Final[int] = 300
    SERVER_TREE_COL_VERSION: Final[int] = 75
    SERVER_TREE_COL_LOADER: Final[int] = 150
    SERVER_TREE_COL_STATUS: Final[int] = 110
    SERVER_TREE_COL_BACKUP: Final[int] = 110
    SERVER_TREE_COL_PATH: Final[int] = 200

    # 對話框尺寸
    DIALOG_SMALL_WIDTH: Final[int] = 400
    DIALOG_SMALL_HEIGHT: Final[int] = 200
    DIALOG_MEDIUM_WIDTH: Final[int] = 600
    DIALOG_MEDIUM_HEIGHT: Final[int] = 400
    DIALOG_LARGE_WIDTH: Final[int] = 800
    DIALOG_LARGE_HEIGHT: Final[int] = 600
    DIALOG_PREFERENCES_WIDTH: Final[int] = 500
    DIALOG_PREFERENCES_HEIGHT: Final[int] = 600
    DIALOG_FIRST_RUN_WIDTH: Final[int] = 480
    DIALOG_FIRST_RUN_HEIGHT: Final[int] = 250
    DIALOG_IMPORT_WIDTH: Final[int] = 450
    DIALOG_IMPORT_HEIGHT: Final[int] = 280
    DIALOG_ABOUT_WIDTH: Final[int] = 600
    DIALOG_ABOUT_HEIGHT: Final[int] = 650
    CONSOLE_PANEL_HEIGHT: Final[int] = 240
    PREVIEW_TEXTBOX_HEIGHT: Final[int] = 300
    TREEVIEW_VISIBLE_ROWS: Final[int] = 15
    APP_HEADER_HEIGHT: Final[int] = 60


def get_button_style(button_type: str = "primary") -> dict[str, tuple[str, str]]:
    """取得按鈕樣式配置

    Args:
        button_type: 按鈕類型 ("primary", "warning", "danger")

    Returns:
        包含 fg_color 和 hover_color 的字典
    """
    styles = {
        "primary": {
            "fg_color": Colors.BUTTON_PRIMARY,
            "hover_color": Colors.BUTTON_PRIMARY_HOVER,
        },
        "warning": {
            "fg_color": Colors.BUTTON_WARNING,
            "hover_color": Colors.BUTTON_WARNING_HOVER,
        },
        "danger": {
            "fg_color": Colors.BUTTON_DANGER,
            "hover_color": Colors.BUTTON_DANGER_HOVER,
        },
    }
    return styles.get(button_type, styles["primary"])


def get_dropdown_style() -> dict[str, tuple[str, str]]:
    """取得下拉選單樣式配置

    Returns:
        包含所有下拉選單顏色的字典
    """
    return {
        "fg_color": Colors.DROPDOWN_BG,
        "button_color": Colors.DROPDOWN_BUTTON,
        "button_hover_color": Colors.DROPDOWN_BUTTON_HOVER,
        "dropdown_fg_color": Colors.DROPDOWN_BG,
        "dropdown_hover_color": Colors.DROPDOWN_HOVER,
        "dropdown_text_color": Colors.TEXT_PRIMARY,
        "text_color": Colors.TEXT_PRIMARY,
    }


def compute_adaptive_pool_limit(
    *,
    current: int,
    min_size: int,
    cap_size: int,
    step: int,
    pool_len: int,
    hit_rate: float,
    low_hit_threshold: float = 35.0,
    high_hit_threshold: float = 90.0,
    idle_divisor: int = 4,
) -> int:
    """依命中率與池使用狀態，回傳建議的 recycle pool 上限。"""
    current = max(1, int(current))
    min_size = max(1, int(min_size))
    cap_size = max(min_size, int(cap_size))
    step = max(1, int(step))
    pool_len = max(0, int(pool_len))
    idle_divisor = max(1, int(idle_divisor))

    new_size = current
    if hit_rate < low_hit_threshold and current < cap_size:
        new_size = min(cap_size, current + step)
    elif hit_rate > high_hit_threshold and pool_len < max(1, current // idle_divisor) and current > min_size:
        new_size = max(min_size, current - step)
    return new_size


def compute_exponential_moving_average(
    *,
    previous: float | None,
    current: float,
    alpha: float = 0.35,
) -> float:
    """計算 EMA（Exponential Moving Average）並限制 alpha 於 [0, 1]。"""
    clamped_alpha = max(0.0, min(1.0, float(alpha)))
    current_value = float(current)
    if previous is None:
        return current_value
    return (clamped_alpha * current_value) + ((1.0 - clamped_alpha) * float(previous))


# ====== UI 輔助類別 ======


class IconUtils:
    @staticmethod
    def set_window_icon(window, delay_ms=200) -> None:
        """設定視窗 icon，並在不同生命週期時機補設，避免被 CTk/系統主題覆寫。

        為何需要多段延遲：
        - `after(0)`: 先在事件迴圈下一拍立即套用，覆蓋最早期的預設圖示。
        - `after(delay_ms)`: 覆寫 CTk 完成初始版面/主題套用後可能發生的 icon 重設。
        - `after(delay_ms + 120)`: 捕捉部分環境第二波視窗狀態變更（例如 map/focus 連動）。
        - `after(delay_ms + 500)`: 作為延後保險補設，處理較慢的視窗管理器或 DPI/主題更新。

        另外在 `<Map>` 與 `<FocusIn>` 事件上補綁 `_apply_icon`，確保視窗再次顯示或取得焦點時，
        若圖示被外部機制覆寫，仍可補設為應用程式圖示。
        """

        icon_path = PathUtils.get_assets_path() / "icon.ico"
        if not icon_path.exists():
            logger.warning(f"圖示檔案不存在 - {icon_path}")
            return

        icon_str = str(icon_path)

        def _apply_icon() -> None:
            try:
                if not window.winfo_exists():
                    return
                # 先設成 default，讓後續新視窗也繼承同圖示
                try:
                    window.iconbitmap(default=icon_str)
                except tk.TclError as e:
                    logger.debug(f"無法設定預設視窗圖示，將略過此步驟 - {e}")
                # 再設當前視窗 icon
                window.iconbitmap(icon_str)
                window._msm_icon_set = True
                with contextlib.suppress(Exception):
                    window.after_idle(window.update_idletasks)
            except Exception as e:
                logger.exception(f"設定視窗圖示失敗 - {e}")

        def _on_window_state_change(_event=None) -> None:
            # 視窗 map/focus 時再補設一次，避免 icon 被主題系統覆寫
            with contextlib.suppress(Exception):
                window.after_idle(_apply_icon)

        try:
            if hasattr(window, "after") and hasattr(window, "winfo_exists"):
                # 分段補綁：覆寫不同時機點的 icon 重設。
                # 0ms: 下一拍立即套用（最早可行時機）
                with contextlib.suppress(Exception):
                    window.after(0, _apply_icon)
                # delay_ms: CTk 初始化完成後再補設一次
                with contextlib.suppress(Exception):
                    window.after(delay_ms, _apply_icon)
                # delay_ms + 120ms: 補捉次級狀態切換
                with contextlib.suppress(Exception):
                    window.after(delay_ms + 120, _apply_icon)
                # delay_ms + 500ms: 慢速環境的保險補設
                with contextlib.suppress(Exception):
                    window.after(delay_ms + 500, _apply_icon)

                # 只綁一次事件，避免重複 bind
                if not getattr(window, "_msm_icon_event_bound", False):
                    with contextlib.suppress(Exception):
                        window.bind("<Map>", _on_window_state_change, add="+")
                    with contextlib.suppress(Exception):
                        window.bind("<FocusIn>", _on_window_state_change, add="+")
                    window._msm_icon_event_bound = True
            else:
                _apply_icon()
        except Exception as e:
            logger.warning(f"無法延遲執行圖示綁定: {e}")
            _apply_icon()


class UIUtils:
    @staticmethod
    def pack_main_frame(frame, padx: int | None = None, pady: int | None = None) -> None:
        """統一的主框架布局方法"""
        if padx is None:
            padx = FontManager.get_dpi_scaled_size(15)
        if pady is None:
            pady = FontManager.get_dpi_scaled_size(15)

        frame.pack(
            fill="both",
            expand=True,
            padx=padx,
            pady=pady,
        )

    @staticmethod
    def call_on_ui(parent: Any, func: Callable[[], Any], timeout: float | None = None) -> Any:
        """在 UI 執行緒執行函數 (若當前非 UI 執行緒則排程執行並等待結果)

        Args:
            parent: 父視窗物件
            func: 要執行的函數
            timeout: 等待逾時秒數 (None = 不限時，等待直到完成)

        Returns:
            func 的回傳值
        """
        try:
            if (
                parent is not None
                and hasattr(parent, "after")
                and hasattr(parent, "winfo_exists")
                and parent.winfo_exists()
            ):
                if threading.current_thread() is threading.main_thread():
                    return func()

                result: dict[str, Any] = {"value": None, "exc": None, "cancelled": False}
                done = threading.Event()
                after_id = None

                def _runner():
                    # 檢查是否已被取消（執行前）
                    if result["cancelled"]:
                        done.set()
                        return
                    try:
                        result["value"] = func()
                    except Exception as e:
                        result["exc"] = e
                    finally:
                        done.set()

                try:
                    after_id = parent.after(0, _runner)

                    # 根據是否有設定 timeout 分別處理等待邏輯
                    if timeout is None:
                        # 無限等待直到任務完成
                        done.wait()
                    else:
                        # 設定了逾時秒數：等待並檢查是否超時
                        if not done.wait(timeout=timeout):
                            # Timeout 發生：設定 cancelled 旗標並嘗試取消排程
                            result["cancelled"] = True
                            if after_id is not None:
                                with contextlib.suppress(Exception):
                                    # 可能已經執行完畢或正在執行中
                                    parent.after_cancel(after_id)

                            # 明確設定逾時：拋出例外
                            logger.warning(f"UI 任務等待逾時 ({timeout}秒)")
                            if not parent.winfo_exists():
                                logger.debug("視窗已關閉")
                            raise TimeoutError(f"UI 任務等待逾時 ({timeout}秒)")
                except TimeoutError:
                    raise  # 重新拋出 TimeoutError 不回退
                except Exception as e:
                    result["cancelled"] = True
                    logger.debug(f"排程 UI 任務時發生例外 (可能視窗已關閉): {e}")
                    # 回退到直接呼叫
                    return func()

                if isinstance(result["exc"], Exception):
                    raise result["exc"]
                return result["value"]
        except TimeoutError:
            raise  # 重新拋出 TimeoutError 不回退
        except Exception as e:
            logger.debug(f"UI 排程執行失敗，回退至直接呼叫: {e}")
        return func()

    @staticmethod
    def setup_window_properties(
        window,
        parent=None,
        width=None,
        height=None,
        bind_icon=True,
        center_on_parent=True,
        make_modal=True,
        delay_ms=200,
    ) -> None:
        """統一的視窗屬性設定函數，整合圖示綁定、視窗置中、模態設定三個功能"""
        # 設定視窗大小與置中，統一呼叫 WindowManager 的 setup_dialog_window
        WindowManager.setup_dialog_window(
            window,
            parent=parent,
            width=width,
            height=height,
            center_on_parent=center_on_parent,
        )
        # 設定模態視窗屬性
        if make_modal and parent:
            try:
                window.transient(parent)
                window.grab_set()
                window.focus_set()
            except Exception as e:
                logger.exception(f"設定模態視窗失敗: {e}")

        # 延遲綁定圖示，確保不會被覆蓋，使用更長的延遲
        if bind_icon:
            IconUtils.set_window_icon(window, delay_ms)

    @staticmethod
    def create_toplevel_dialog(
        parent,
        title: str,
        *,
        width: int | None = None,
        height: int | None = None,
        resizable: bool = True,
        bind_icon: bool = True,
        center_on_parent: bool = True,
        make_modal: bool = True,
        delay_ms: int = 200,
    ) -> ctk.CTkToplevel:
        """建立並套用專案一致的 dialog 視窗屬性。"""
        dialog = ctk.CTkToplevel(parent)
        dialog.title(title)
        dialog.resizable(resizable, resizable)

        UIUtils.setup_window_properties(
            window=dialog,
            parent=parent,
            width=width,
            height=height,
            bind_icon=bind_icon,
            center_on_parent=center_on_parent,
            make_modal=make_modal,
            delay_ms=delay_ms,
        )
        return dialog

    @staticmethod
    def safe_update_widget(widget, update_func: Callable, *args, **kwargs) -> None:
        """安全地更新 widget，檢查 widget 是否存在"""
        try:
            if widget and widget.winfo_exists():
                update_func(widget, *args, **kwargs)
        except Exception as e:
            logger.exception(f"更新 widget 失敗: {e}")

    @staticmethod
    def start_ui_queue_pump(
        widget,
        task_queue: "queue.Queue",
        *,
        interval_ms: int = 100,
        busy_interval_ms: int = 25,
        max_tasks_per_tick: int = 100,
        job_attr: str = "_ui_queue_pump_job",
    ) -> None:
        def _alive() -> bool:
            try:
                return bool(widget) and widget.winfo_exists()
            except Exception:
                return False

        def _cancel_existing() -> None:
            try:
                job_id = getattr(widget, job_attr, None)
                if job_id:
                    widget.after_cancel(job_id)
            except Exception as e:
                logger.debug(f"取消舊的 UI queue pump job 失敗（視窗可能已關閉）: {e}")
            try:
                setattr(widget, job_attr, None)
            except Exception as e:
                logger.debug(f"重設 UI queue pump job 欄位失敗（視窗可能已關閉）: {e}")

        def _tick() -> None:
            if not _alive():
                return

            processed = 0
            while processed < max_tasks_per_tick:
                try:
                    task = task_queue.get_nowait()
                except queue.Empty:
                    break

                try:
                    task()
                except Exception as e:
                    logger.exception(f"UI 任務執行失敗: {e}")
                processed += 1

            if not _alive():
                return

            # 如果還有積壓，縮短下一次間隔；否則用一般間隔
            try:
                has_backlog = not task_queue.empty()
            except Exception:
                has_backlog = False

            next_delay = busy_interval_ms if has_backlog else interval_ms
            try:
                setattr(widget, job_attr, widget.after(next_delay, _tick))
            except Exception as e:
                # 視窗可能正在銷毀，忽略
                logger.exception(f"排程下一次 UI queue pump 失敗（視窗可能正在銷毀）: {e}")

        if not _alive():
            return

        _cancel_existing()
        _tick()

    @staticmethod
    def cancel_scheduled_job(widget, job_attr: str, *, owner: Any | None = None) -> None:
        """取消指定的 after/after_idle 排程工作。"""
        holder = owner if owner is not None else widget
        job_id = getattr(holder, job_attr, None)
        if not job_id:
            setattr(holder, job_attr, None)
            return
        try:
            if widget and hasattr(widget, "after_cancel"):
                widget.after_cancel(job_id)
        except Exception as e:
            logger.debug(f"取消排程失敗 {job_attr}={job_id}: {e}")
        finally:
            setattr(holder, job_attr, None)

    @staticmethod
    def schedule_debounce(
        widget,
        job_attr: str,
        delay_ms: int,
        callback: Callable[[], Any],
        *,
        owner: Any | None = None,
    ) -> str | None:
        """以 debounce 方式排程：新的呼叫會覆蓋尚未執行的舊工作。"""
        holder = owner if owner is not None else widget
        if not widget or not hasattr(widget, "after"):
            return None

        try:
            if hasattr(widget, "winfo_exists") and not widget.winfo_exists():
                setattr(holder, job_attr, None)
                return None
        except Exception:
            return None

        UIUtils.cancel_scheduled_job(widget, job_attr, owner=holder)

        def _runner() -> None:
            setattr(holder, job_attr, None)
            try:
                callback()
            except Exception as e:
                logger.exception(f"執行 debounce callback 失敗 {job_attr}: {e}")

        try:
            job_id = widget.after(max(0, int(delay_ms)), _runner)
            setattr(holder, job_attr, job_id)
            return job_id
        except Exception as e:
            logger.debug(f"建立 debounce 排程失敗 {job_attr}: {e}")
            setattr(holder, job_attr, None)
            return None

    @staticmethod
    def schedule_coalesced_idle(
        widget,
        job_attr: str,
        callback: Callable[[], Any],
        *,
        owner: Any | None = None,
    ) -> str | None:
        """合併多次請求為單次 after_idle 執行。"""
        holder = owner if owner is not None else widget
        if getattr(holder, job_attr, None):
            return getattr(holder, job_attr, None)
        if not widget or not hasattr(widget, "after_idle"):
            return None

        try:
            if hasattr(widget, "winfo_exists") and not widget.winfo_exists():
                setattr(holder, job_attr, None)
                return None
        except Exception:
            return None

        def _runner() -> None:
            setattr(holder, job_attr, None)
            try:
                callback()
            except Exception as e:
                logger.exception(f"執行 idle callback 失敗 {job_attr}: {e}")

        try:
            job_id = widget.after_idle(_runner)
            setattr(holder, job_attr, job_id)
            return job_id
        except Exception as e:
            logger.debug(f"建立 idle 合併排程失敗 {job_attr}: {e}")
            setattr(holder, job_attr, None)
            return None

    @staticmethod
    def schedule_throttle(
        widget,
        job_attr: str,
        interval_ms: int,
        callback: Callable[[], Any],
        *,
        owner: Any | None = None,
        trailing: bool = True,
        last_run_attr: str | None = None,
    ) -> bool:
        """節流排程：限制 callback 執行頻率，必要時保留尾端一次執行。"""
        holder = owner if owner is not None else widget
        if not widget:
            return False

        interval_ms = max(1, int(interval_ms))
        if last_run_attr is None:
            last_run_attr = f"{job_attr}_last_run_ms"

        try:
            if hasattr(widget, "winfo_exists") and not widget.winfo_exists():
                return False
        except Exception:
            return False

        now_ms = int(time.monotonic() * 1000)
        last_run_ms = int(getattr(holder, last_run_attr, 0) or 0)
        elapsed = now_ms - last_run_ms

        def _run_now() -> None:
            setattr(holder, last_run_attr, int(time.monotonic() * 1000))
            try:
                callback()
            except Exception as e:
                logger.exception(f"執行 throttle callback 失敗 {job_attr}: {e}")

        if elapsed >= interval_ms:
            UIUtils.cancel_scheduled_job(widget, job_attr, owner=holder)
            _run_now()
            return True

        if trailing and not getattr(holder, job_attr, None):
            remaining = max(1, interval_ms - elapsed)

            def _runner() -> None:
                setattr(holder, job_attr, None)
                _run_now()

            try:
                setattr(holder, job_attr, widget.after(remaining, _runner))
            except Exception as e:
                logger.debug(f"建立 throttle 排程失敗 {job_attr}: {e}")
                setattr(holder, job_attr, None)
                return False

        return False

    @staticmethod
    def run_async(target: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """簡單的非同步執行封裝，適用於不需要回傳值的任務"""
        threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True).start()

    @staticmethod
    def run_in_daemon_thread(
        task_func: Callable,
        *,
        ui_queue: "queue.Queue | None" = None,
        widget=None,
        on_error: Callable[[], None] | None = None,
        error_log_prefix: str = "",
        component: str = "UIUtils",
    ) -> None:
        def _dispatch(cb: Callable[[], None] | None) -> None:
            if cb is None:
                return
            if ui_queue is not None:
                try:
                    ui_queue.put(cb)
                    return
                except Exception as e:
                    logger.debug(f"ui_queue put 失敗: {e}")
            if widget is not None:
                try:
                    widget.after(0, cb)
                    return
                except Exception as e:
                    logger.debug(f"widget.after 失敗: {e}")
            try:
                cb()
            except Exception as e:
                logger.debug(f"直接執行 callback 失敗: {e}")

        def _wrapper() -> None:
            try:
                task_func()
            except Exception as e:
                prefix = (error_log_prefix + ": ") if error_log_prefix else ""
                get_logger().bind(component=component).exception(f"{prefix}{e}")
                _dispatch(on_error)

        threading.Thread(target=_wrapper, daemon=True).start()

    @staticmethod
    def bind_tooltip(
        widget,
        text: str,
        *,
        bg: str = "#2b2b2b",
        fg: str = "white",
        font=None,
        padx: int = 8,
        pady: int = 4,
        wraplength: int | None = None,
        justify: str = "left",
        borderwidth: int = 0,
        relief: str = "flat",
        offset_x: int = 10,
        offset_y: int = 10,
        show_delay_ms: int = 0,
        auto_hide_ms: int | None = None,
    ) -> None:
        if not widget:
            return

        def _destroy_tooltip() -> None:
            tip = getattr(widget, "_msm_tooltip", None)
            if tip is not None:
                try:
                    if tip.winfo_exists():
                        tip.destroy()
                except Exception as e:
                    logger.debug(f"銷毀 tooltip 失敗: {e}", "UIUtils")
            try:
                widget._msm_tooltip = None
            except Exception as e:
                logger.debug(f"重置 _msm_tooltip 屬性失敗: {e}", "UIUtils")
            job = getattr(widget, "_msm_tooltip_job", None)
            if job is not None:
                try:
                    widget.after_cancel(job)
                except Exception as e:
                    logger.debug(f"取消 tooltip job 失敗: {e}", "UIUtils")
            try:
                widget._msm_tooltip_job = None
            except Exception as e:
                logger.debug(f"重置 _msm_tooltip_job 屬性失敗: {e}", "UIUtils")
            show_job = getattr(widget, "_msm_tooltip_show_job", None)
            if show_job is not None:
                try:
                    widget.after_cancel(show_job)
                except Exception as e:
                    logger.debug(f"取消 tooltip show job 失敗: {e}", "UIUtils")
            try:
                widget._msm_tooltip_show_job = None
            except Exception as e:
                logger.debug(f"重置 _msm_tooltip_show_job 屬性失敗: {e}", "UIUtils")

        def _show_tooltip_at(x_root: int, y_root: int) -> None:
            try:
                _destroy_tooltip()
                tip = tk.Toplevel(widget.winfo_toplevel())
                tip.wm_overrideredirect(True)
                tip.configure(bg=bg)
                tip.wm_geometry(f"+{x_root + offset_x}+{y_root + offset_y}")

                label_kwargs: dict[str, Any] = {
                    "text": text or "",
                    "bg": bg,
                    "fg": fg,
                    "padx": padx,
                    "pady": pady,
                    "borderwidth": borderwidth,
                    "relief": relief,
                }
                if font is not None:
                    label_kwargs["font"] = font
                if wraplength is not None:
                    label_kwargs["wraplength"] = wraplength
                if justify is not None:
                    label_kwargs["justify"] = justify

                tk.Label(tip, **label_kwargs).pack()

                widget._msm_tooltip = tip

                if auto_hide_ms:
                    try:
                        widget._msm_tooltip_job = tip.after(auto_hide_ms, _destroy_tooltip)
                    except Exception as e:
                        logger.debug(f"設定 tooltip 自動隱藏失敗: {e}", "UIUtils")
            except Exception as e:
                logger.exception(f"顯示 tooltip 失敗: {e}")

        def _show_tooltip(event) -> None:
            x_root = int(getattr(event, "x_root", 0))
            y_root = int(getattr(event, "y_root", 0))
            delay = max(0, int(show_delay_ms))
            if delay <= 0:
                _show_tooltip_at(x_root, y_root)
                return

            _destroy_tooltip()

            def _delayed_show() -> None:
                with contextlib.suppress(Exception):
                    widget._msm_tooltip_show_job = None
                _show_tooltip_at(x_root, y_root)

            try:
                widget._msm_tooltip_show_job = widget.after(delay, _delayed_show)
            except Exception as e:
                logger.debug(f"設定 tooltip 延遲顯示失敗: {e}", "UIUtils")
                _show_tooltip_at(x_root, y_root)

        def _hide_tooltip(_event=None) -> None:
            _destroy_tooltip()

        try:
            widget.bind("<Enter>", _show_tooltip)
            widget.bind("<Leave>", _hide_tooltip)
        except Exception as e:
            logger.exception(f"綁定 tooltip 事件失敗: {e}")

    @staticmethod
    def _show_messagebox(
        message_func: Callable,
        title: str,
        message: str,
        parent=None,
        topmost: bool = False,
        log_level: str = "error",
    ) -> None:
        """統一的訊息對話框顯示方法"""
        # 記錄訊息
        log_msg = f"{title}: {message}"
        if log_level == "error":
            logger.error(log_msg)
        elif log_level == "warning":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        try:
            if parent is None:
                root = tk.Tk()
                root.withdraw()  # 隱藏主視窗

                if topmost:
                    root.attributes("-topmost", True)

                UIUtils.setup_window_properties(
                    root,
                    parent=None,
                    width=300,
                    height=150,
                    bind_icon=True,
                    center_on_parent=True,  # 螢幕置中
                    make_modal=True,
                    delay_ms=50,
                )

                message_func(title, message, parent=root)
                root.destroy()
            else:
                message_func(title, message, parent=parent)
        except Exception as e:
            logger.exception(f"顯示訊息對話框失敗: {e}")
            if log_level == "error":
                logger.error(f"錯誤: {title} - {message}")
            elif log_level == "warning":
                logger.warning(f"警告: {title} - {message}")

    @staticmethod
    def show_error(
        title: str = "錯誤",
        message: str = "發生未知錯誤",
        parent=None,
        topmost: bool = False,
    ) -> None:
        """顯示錯誤訊息對話框，使用 tk 並自動處理圖示和置中"""
        UIUtils._show_messagebox(messagebox.showerror, title, message, parent, topmost, "error")

    @staticmethod
    def show_manual_restart_dialog(parent, details: str | None) -> None:
        """顯示需要手動重啟的對話框，並提供複製診斷按鈕。"""
        try:
            dlg = UIUtils.create_toplevel_dialog(parent, "需要手動重啟", width=560, height=360, make_modal=True)

            tk.Label(dlg, text="設定已變更，但需要手動重新啟動應用程式。", anchor="w").pack(
                fill="x", padx=12, pady=(12, 6)
            )
            txt = scrolledtext.ScrolledText(dlg, wrap="word", height=12)
            txt.pack(fill="both", expand=True, padx=12, pady=(0, 8))
            txt.insert("1.0", details or "")
            txt.configure(state="disabled")

            def _copy():
                try:
                    dlg.clipboard_clear()
                    dlg.clipboard_append(details or "")
                except Exception as e:
                    logger.debug("copy to clipboard failed: %s", e)

            btn_frame = tk.Frame(dlg)
            btn_frame.pack(fill="x", padx=12, pady=(0, 12))
            from tkinter import Button as _Button

            _Button(btn_frame, text="複製診斷", command=_copy).pack(side="left")
            _Button(btn_frame, text="我會手動重啟", command=dlg.destroy).pack(side="right")
        except Exception:
            UIUtils.show_info("需要手動重啟", f"設定已變更，但自動重啟失敗。\n\n診斷：\n{details}", parent=parent)

    @staticmethod
    def show_warning(
        title: str = "警告",
        message: str = "警告訊息",
        parent=None,
        topmost: bool = False,
    ) -> None:
        """顯示警告訊息對話框，使用 tk 並自動處理圖示和置中"""
        UIUtils._show_messagebox(messagebox.showwarning, title, message, parent, topmost, "warning")

    @staticmethod
    def show_info(
        title: str = "資訊",
        message: str = "資訊訊息",
        parent=None,
        topmost: bool = False,
    ) -> None:
        """顯示資訊對話框，使用 tk 並自動處理圖示和置中"""
        UIUtils._show_messagebox(messagebox.showinfo, title, message, parent, topmost, "info")

    @staticmethod
    def reveal_in_explorer(target) -> None:
        """在檔案總管中顯示"""
        target_path = Path(target)
        try:
            if target_path.exists():
                target_path = target_path.resolve()
            target_str = str(target_path)
            explorer = PathUtils.find_executable("explorer") or str(
                Path(os.environ.get("WINDIR", "C:\\Windows")) / "explorer.exe"
            )
            try:
                SubprocessUtils.run_checked([explorer, f"/select,{target_str}"], check=False)
                return
            except Exception as e:
                logger.debug(f"使用 explorer /select 失敗: {e}")

            folder_path = target_path if target_path.is_dir() else target_path.parent
            UIUtils.open_external(str(folder_path))

        except Exception as e:
            logger.exception(f"在檔案總管中顯示失敗: {e}")

    @staticmethod
    def open_external(target) -> None:
        """使用系統預設程式開啟。"""
        try:
            target_str = str(target)
            if target_str.startswith(("http://", "https://")):
                webbrowser.open(target_str)
                return

            try:
                target_path = Path(target_str)
                if target_path.exists():
                    target_str = str(target_path.resolve())
                elif not target_str.startswith("http"):
                    logger.error(f"開啟外部資源失敗：路徑不存在 - {target_str}")
                    return
            except Exception as e:
                logger.debug(f"檢查路徑存在性時發生例外: {e}")

            try:
                startfile = getattr(os, "startfile", None)
                if callable(startfile):
                    startfile(target_str)  # nosec: B606
                    return
            except Exception as e:
                logger.debug(f"os.startfile 失敗，嘗試 subprocess: {e}")
            try:
                explorer = PathUtils.find_executable("explorer") or str(
                    Path(os.environ.get("WINDIR", "C:\\Windows")) / "explorer.exe"
                )
                try:
                    SubprocessUtils.run_checked([explorer, target_str], check=True)
                    return
                except Exception as e:
                    logger.debug(f"使用 explorer 開啟失敗: {e}")
            except Exception as e:
                logger.exception(f"透過系統開啟外部資源失敗: {target_str} - {e}")
        except Exception as e:
            logger.exception(f"開啟外部資源失敗: {e}")

    @staticmethod
    def ask_yes_no_cancel(
        title: str = "確認",
        message: str = "請選擇操作",
        parent=None,
        show_cancel: bool = True,
        topmost: bool = False,
    ) -> bool | None:
        """顯示確認對話框，支援是/否/取消選項，使用 tk 並呼叫 setup_window_properties"""
        try:
            if parent is None:
                root = tk.Tk()
                root.withdraw()  # 隱藏主視窗

                if topmost:
                    root.attributes("-topmost", True)

                UIUtils.setup_window_properties(
                    root,
                    parent=None,
                    width=300,
                    height=150,
                    bind_icon=True,
                    center_on_parent=True,  # 螢幕置中
                    make_modal=False,
                    delay_ms=50,
                )

                if show_cancel:
                    result = messagebox.askyesnocancel(title, message, parent=root)
                else:
                    result = messagebox.askyesno(title, message, parent=root)
                root.destroy()
                return result
            if show_cancel:
                return messagebox.askyesnocancel(title, message, parent=parent)
            return messagebox.askyesno(title, message, parent=parent)
        except Exception as e:
            logger.exception(f"顯示確認對話框失敗: {e}")
            return False if not show_cancel else None

    @staticmethod
    def apply_unified_dropdown_styling(dropdown_widget) -> None:
        """套用統一的下拉選單樣式"""
        style_config = get_dropdown_style()
        dropdown_widget.configure(**style_config)

        def on_mouse_wheel(event):
            try:
                current_value = dropdown_widget.get()
                values = dropdown_widget.cget("values")

                if values and current_value in values:
                    current_index = values.index(current_value)

                    if event.delta > 0 and current_index > 0:
                        new_index = current_index - 1
                    elif event.delta < 0 and current_index < len(values) - 1:
                        new_index = current_index + 1
                    else:
                        return

                    dropdown_widget.set(values[new_index])

                    if hasattr(dropdown_widget, "_command") and dropdown_widget._command:
                        dropdown_widget._command(values[new_index])

            except Exception as e:
                logger.exception(f"滑鼠滾輪處理錯誤: {e}")

        dropdown_widget.bind("<MouseWheel>", on_mouse_wheel)

    @staticmethod
    def bind_bool_string_var(bool_var, string_var) -> None:
        """建立 BooleanVar 與 StringVar 的雙向綁定（用於 server.properties 等場景）

        Args:
            bool_var: tkinter.BooleanVar 布林變數
            string_var: tkinter.StringVar 字串變數（"true"/"false"）
        """

        # 使用閉包內的旗標避免 trace 互相觸發造成遞迴
        in_sync = False

        def update_string_var(*_args):
            """當布林變數改變時，更新字串變數"""
            nonlocal in_sync
            if in_sync:
                return
            in_sync = True
            try:
                new_value = "true" if bool_var.get() else "false"
                # 僅在值實際變更時才更新，避免多餘 trace
                if string_var.get() != new_value:
                    string_var.set(new_value)
            finally:
                in_sync = False

        def update_bool_var(*_args):
            """當字串變數改變時，更新布林變數"""
            nonlocal in_sync
            if in_sync:
                return
            in_sync = True
            try:
                # 規範化為標準布林字串（確保 server.properties 一致性）
                current = string_var.get().strip().lower()
                # 容錯：將常見的真值映射為 "true"，其餘一律為 "false"
                if current in ("true", "1", "yes", "on"):
                    normalized = "true"
                    new_bool = True
                else:
                    normalized = "false"
                    new_bool = False

                # 更新字串為規範值
                if string_var.get() != normalized:
                    string_var.set(normalized)
                # 同步布林值
                if bool_var.get() != new_bool:
                    bool_var.set(new_bool)
            finally:
                in_sync = False

        bool_var.trace_add("write", update_string_var)
        string_var.trace_add("write", update_bool_var)

    @staticmethod
    def create_styled_button(parent, text, command, button_type="secondary", **kwargs) -> ctk.CTkButton:
        """建立統一樣式的按鈕"""
        scale_factor = FontManager.get_scale_factor()

        # 根據按鈕類型設定樣式
        if button_type == "primary":
            button_style = {
                "fg_color": ("#1f4e79", "#0f2a44"),  # 更深的藍色，提高對比
                "hover_color": ("#0f2a44", "#071925"),
                "text_color": ("#ffffff", "#ffffff"),  # 確保文字為白色
                "font": FontManager.get_font(family="Microsoft JhengHei", size=18, weight="bold"),
                "width": int(180 * scale_factor),
                "height": int(60 * scale_factor),
            }
        elif button_type == "secondary":
            button_style = {
                "fg_color": ("#2d3748", "#1a202c"),  # 深灰色背景
                "hover_color": ("#1a202c", "#0d1117"),
                "text_color": ("#ffffff", "#ffffff"),  # 白色文字
                "font": FontManager.get_font(family="Microsoft JhengHei", size=18),
                "width": int(120 * scale_factor),
                "height": int(42 * scale_factor),
            }
        elif button_type == "small":
            button_style = {
                "fg_color": ("#4a5568", "#2d3748"),  # 灰色背景
                "hover_color": ("#2d3748", "#1a202c"),
                "text_color": ("#ffffff", "#ffffff"),  # 白色文字確保對比
                "font": FontManager.get_font(family="Microsoft JhengHei", size=18),
                "width": int(80 * scale_factor),
                "height": int(30 * scale_factor),
            }
        elif button_type == "cancel":
            button_style = {
                "fg_color": ("#dc2626", "#991b1b"),  # 更深的紅色
                "hover_color": ("#991b1b", "#7f1d1d"),
                "text_color": ("#ffffff", "#ffffff"),  # 白色文字
                "font": FontManager.get_font(family="Microsoft JhengHei", size=18),
                "width": int(120 * scale_factor),
                "height": int(48 * scale_factor),
            }
        else:
            button_style = {}

        # 合併所有樣式
        final_style = {**button_style, **kwargs}

        return ctk.CTkButton(parent, text=text, command=command, **final_style)


class ProgressDialog:
    def __init__(self, parent, title="進度", show_cancel=True):
        self.dialog = ctk.CTkToplevel(parent)
        self.dialog.title(title)
        self.dialog.resizable(False, False)

        # 使用新的視窗管理器設定對話框
        WindowManager.setup_dialog_window(self.dialog, parent, 450, 200, True)

        # 設定模態視窗屬性
        if parent:
            try:
                self.dialog.transient(parent)
                self.dialog.grab_set()
                self.dialog.focus_set()
            except Exception as e:
                logger.exception(f"設定模態視窗失敗: {e}")

        # 延遲綁定圖示
        IconUtils.set_window_icon(self.dialog, 250)

        # 內容框架
        content_frame = ctk.CTkFrame(self.dialog)
        content_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 狀態標籤
        self.status_label = ctk.CTkLabel(content_frame, text="準備中...", font=FontManager.get_font(size=12))
        self.status_label.pack(pady=(10, 15))

        # 進度條
        self.progress = ctk.CTkProgressBar(content_frame, width=410, height=20)  # 調整寬度以配合新的視窗大小
        self.progress.pack(pady=(0, 15))
        self.progress.set(0)

        # 百分比標籤
        self.percent_label = ctk.CTkLabel(content_frame, text="0%", font=FontManager.get_font(size=11))
        self.percent_label.pack()

        # 取消按鈕（可選）
        if show_cancel:
            self.cancel_button = ctk.CTkButton(
                content_frame,
                text="取消",
                command=self.cancel,
                fg_color=("#ef4444", "#dc2626"),
                hover_color=("#dc2626", "#b91c1c"),
                font=FontManager.get_font(size=12),
                width=80,
                height=38,
            )
            self.cancel_button.pack(pady=(15, 0))

        self.cancelled = False
        self._last_ui_pump = 0.0
        self._pending_update = False
        self._last_percent = -1
        self._last_status = ""

    def update_progress(self, percent, status_text) -> bool:
        if self.cancelled:
            return False

        # 避免重複更新相同值
        current_percent = getattr(self, "_last_percent", -1)
        current_status = getattr(self, "_last_status", "")

        if current_percent == percent and current_status == status_text:
            return True  # 值未變，跳過更新

        self._last_percent = percent
        self._last_status = status_text

        def _update():
            if self.cancelled:
                return
            try:
                self.progress.set(percent / 100.0)  # CustomTkinter 使用 0-1 範圍
                self.status_label.configure(text=status_text)
                self.percent_label.configure(text=f"{percent:.1f}%")
            except Exception as e:
                logger.exception(f"更新進度 UI 失敗: {e}")

        # 確保在主線程執行
        if threading.current_thread() is threading.main_thread():
            _update()
            if not getattr(self, "_pending_update", False):
                self._pending_update = True
                self.dialog.after_idle(self._do_idle_update)
        else:
            self.dialog.after(0, _update)

        return True

    def _do_idle_update(self) -> None:
        """在 idle 時執行完整更新，批次處理widget變更"""
        try:
            if self.cancelled or not self.dialog.winfo_exists():
                return
            self.dialog.update_idletasks()
        except Exception as e:
            logger.exception(f"進度對話框 idle 更新失敗: {e}")
        finally:
            self._pending_update = False

    def cancel(self) -> None:
        self.cancelled = True
        self.dialog.destroy()

    def close(self) -> None:
        try:
            self.dialog.destroy()
        except Exception as e:
            logger.exception(f"關閉進度對話框失敗: {e}")
