#!/usr/bin/env python3
"""UI 工具函數
提供常用的界面元件和工具函數，避免重複程式碼
"""

import contextlib
import os
import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, scrolledtext
from typing import Any, Callable, Final

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

    # 警告按鈕顏色（橙色系）
    BUTTON_WARNING: Final[tuple[str, str]] = ("#f59e0b", "#d97706")
    BUTTON_WARNING_HOVER: Final[tuple[str, str]] = ("#d97706", "#b45309")

    # 危險按鈕顏色（紅色系）
    BUTTON_DANGER: Final[tuple[str, str]] = ("#dc2626", "#b91c1c")
    BUTTON_DANGER_HOVER: Final[tuple[str, str]] = ("#b91c1c", "#991b1b")

    # 文字顏色
    TEXT_PRIMARY: Final[tuple[str, str]] = ("#1f2937", "#1f2937")  # 主要文字
    TEXT_SECONDARY: Final[tuple[str, str]] = ("#6b7280", "#6b7280")  # 次要文字
    TEXT_LINK: Final[tuple[str, str]] = ("blue", "#4dabf7")  # 連結文字
    TEXT_SUCCESS: Final[tuple[str, str]] = ("green", "#10b981")  # 成功文字
    TEXT_ERROR: Final[tuple[str, str]] = ("#e53e3e", "#e53e3e")  # 錯誤文字

    # 背景顏色
    BG_PRIMARY: Final[tuple[str, str]] = ("#ffffff", "#ffffff")  # 主要背景（白色）
    BG_SECONDARY: Final[tuple[str, str]] = ("#f3f4f6", "#f3f4f6")  # 次要背景
    BG_CONSOLE: Final[str] = "#000000"  # 終端機背景
    BG_LISTBOX_LIGHT: Final[str] = "#f8fafc"  # 清單背景（淺色）
    BG_LISTBOX_DARK: Final[str] = "#2b2b2b"  # 清單背景（深色）

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
    SELECT_BG: Final[str] = "#1f538d"  # 選擇背景


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
    BUTTON_HEIGHT_SMALL: Final[int] = 28  # 小按鈕高度

    # 輸入欄位尺寸
    INPUT_HEIGHT: Final[int] = 32  # 標準輸入欄位高度
    INPUT_WIDTH: Final[int] = 300  # 標準輸入欄位寬度

    # 下拉選單尺寸
    DROPDOWN_HEIGHT: Final[int] = 30  # 下拉選單高度
    DROPDOWN_WIDTH: Final[int] = 280  # 下拉選單寬度
    DROPDOWN_MAX_HEIGHT: Final[int] = 200  # 下拉選單最大高度
    DROPDOWN_ITEM_HEIGHT: Final[int] = 30  # 下拉選單項目高度

    # 對話框尺寸
    DIALOG_SMALL_WIDTH: Final[int] = 400
    DIALOG_SMALL_HEIGHT: Final[int] = 200
    DIALOG_MEDIUM_WIDTH: Final[int] = 600
    DIALOG_MEDIUM_HEIGHT: Final[int] = 400
    DIALOG_LARGE_WIDTH: Final[int] = 800
    DIALOG_LARGE_HEIGHT: Final[int] = 600


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


# ====== UI 輔助類別 ======


class IconUtils:
    @staticmethod
    def set_window_icon(window, delay_ms=200) -> None:
        """只設定視窗圖示，不執行任何置頂邏輯，適用於已手動設定 transient 的對話框"""

        def _delayed_icon_bind():
            try:
                if not window.winfo_exists():
                    return

                # 避免重複設定造成閃爍/撕裂
                if getattr(window, "_msm_icon_set", False):
                    return

                icon_path = PathUtils.get_assets_path() / "icon.ico"
                if icon_path.exists():
                    window.iconbitmap(str(icon_path))
                    window._msm_icon_set = True
                    # 只在 idle 時做一次輕量刷新，避免頻繁 update 導致閃爍
                    try:
                        window.after_idle(window.update_idletasks)
                    except Exception as e:
                        logger.exception(f"after_idle(update_idletasks) 失敗: {e}")
                else:
                    logger.warning(f"圖示檔案不存在 - {icon_path}")
            except Exception as e:
                logger.exception(f"設定視窗圖示失敗 - {e}")

        try:
            if hasattr(window, "after") and hasattr(window, "winfo_exists"):
                window.after(delay_ms, _delayed_icon_bind)
                window.after(delay_ms + 100, _delayed_icon_bind)
            else:
                _delayed_icon_bind()  # 立即執行作為備選
        except Exception as e:
            logger.warning(f"無法延遲執行圖示綁定: {e}")
            _delayed_icon_bind()  # 直接執行作為最後備選


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

        def _show_tooltip(event) -> None:
            try:
                _destroy_tooltip()
                tip = tk.Toplevel(widget.winfo_toplevel())
                tip.wm_overrideredirect(True)
                tip.configure(bg=bg)
                tip.wm_geometry(f"+{event.x_root + offset_x}+{event.y_root + offset_y}")

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

            if hasattr(os, "startfile"):
                try:
                    os.startfile(target_str)  # nosec: B606
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
