#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI 工具函數
提供常用的界面元件和工具函數，避免重複代碼
"""
# ====== 標準函式庫 ======
from typing import Optional, Callable
import tkinter as tk
import tkinter.messagebox
import queue
import threading
import time
# ====== 第三方函式庫 ======
import customtkinter as ctk
# ====== 專案內部模組 ======
from .path_utils import PathUtils
from .window_manager import WindowManager
from .logger import get_logger
from .font_manager import font_manager

logger = get_logger().bind(component="UIUtils")

# 設置 CustomTkinter 主題
ctk.set_appearance_mode("light")  # 固定使用淺色主題
ctk.set_default_color_theme("blue")  # 淺色藍色主題

# ====== 對話框創建工具類別 ======
class DialogUtils:
    """
    對話框創建工具類別
    Dialog creation utility class for modal windows and common dialogs
    """
    # 創建模態對話框的通用函數
    @staticmethod
    def create_modal_dialog(
        parent,
        title: str,
        size: tuple = None,
        resizable: bool = True,
        center: bool = True,
    ) -> ctk.CTkToplevel:
        """
        創建標準模態對話框，統一視窗屬性設定
        Create standard modal dialog with unified window properties setup

        Args:
            parent: 父視窗物件
            title (str): 對話框標題
            size (tuple): 視窗大小 (width, height)，None 表示自動計算
            resizable (bool): 是否可調整大小
            center (bool): 是否居中顯示

        Returns:
            CTkToplevel: 設定完成的對話框物件
        """
        dialog = ctk.CTkToplevel(parent)
        dialog.title(title)
        dialog.resizable(resizable, resizable)

        # 使用新的視窗管理器來設定對話框
        if size:
            WindowManager.setup_dialog_window(dialog, parent, size[0], size[1], center)
        else:
            WindowManager.setup_dialog_window(dialog, parent, center_on_parent=center)

        # 設定模態視窗屬性
        if parent:
            try:
                dialog.transient(parent)
                dialog.grab_set()
                dialog.focus_set()
            except Exception as e:
                logger.exception(f"設定模態視窗失敗: {e}")
        # 延遲綁定圖示
        IconUtils.set_window_icon(dialog, 250)

        return dialog

# ====== 圖示管理工具類別 ======
class IconUtils:
    """
    統一的圖示綁定工具類別
    Unified icon binding utility class for window icon management
    """
    # 設定視窗圖示（無置頂邏輯）
    @staticmethod
    def set_window_icon(window, delay_ms=200) -> None:
        """
        只設定視窗圖示，不執行任何置頂邏輯，適用於已手動設定 transient 的對話框
        Only set window icon without any positioning logic, suitable for dialogs with manual transient setup

        Args:
            window: 要設定圖示的視窗物件
            delay_ms (int): 延遲毫秒數，確保視窗完全初始化

        Returns:
            None
        """

        def _delayed_icon_bind():
            """延遲圖示綁定，確保視窗完全初始化"""
            try:
                # 檢查視窗是否仍然存在
                if not window.winfo_exists():
                    return

                # 避免重複設定造成閃爍/撕裂
                if getattr(window, "_msm_icon_set", False):
                    return

                # 使用統一的路徑工具
                icon_path = PathUtils.get_assets_path() / "icon.ico"
                if icon_path.exists():
                    window.iconbitmap(str(icon_path))
                    setattr(window, "_msm_icon_set", True)
                    # 只在 idle 時做一次輕量刷新，避免頻繁 update 導致閃爍
                    try:
                        window.after_idle(window.update_idletasks)
                    except Exception as e:
                        logger.exception(
                            f"after_idle(update_idletasks) 失敗: {e}"
                        )
                else:
                    logger.warning(f"圖示檔案不存在 - {icon_path}")
            except Exception as e:
                logger.exception(f"設定視窗圖示失敗 - {e}")

        # 延遲綁定圖示，確保視窗完全初始化完成
        try:
            if hasattr(window, "after") and hasattr(window, "winfo_exists"):
                # 使用更長的延遲確保視窗完全載入
                window.after(delay_ms, _delayed_icon_bind)
                # 額外的備用嘗試，以防第一次失敗
                window.after(delay_ms + 100, _delayed_icon_bind)
            else:
                _delayed_icon_bind()  # 立即執行作為備選
        except Exception as e:
            logger.warning(f"無法延遲執行圖示綁定: {e}")
            _delayed_icon_bind()  # 直接執行作為最後備選

# ====== UI 通用工具類別 ======
class UIUtils:
    """
    UI 工具類別：常用視窗、訊息框、檔案/資料夾選擇等功能
    UI utility class for common windows, message boxes, file/folder selection and other UI functions
    """
    # 統一設定視窗屬性
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
        """
        統一的視窗屬性設定函數，整合圖示綁定、視窗置中、模態設定三個功能
        Unified window properties setup function that integrates icon binding, window centering, and modal setup

        Args:
            window: 要設定的視窗物件
            parent: 父視窗物件，若為 None 則使用螢幕置中
            width (int): 視窗寬度，用於置中計算
            height (int): 視窗高度，用於置中計算
            bind_icon (bool): 是否綁定圖示
            center_on_parent (bool): 是否相對於父視窗置中，False 則螢幕置中
            make_modal (bool): 是否設為模態視窗（transient + grab_set）
            delay_ms (int): 圖示綁定延遲毫秒數，確保不被覆蓋

        Returns:
            None
        """
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
        """
        安全地更新 widget，檢查 widget 是否存在
        Safely update widget, checking if widget exists
        """
        try:
            if widget and widget.winfo_exists():
                update_func(widget, *args, **kwargs)
        except Exception as e:
            logger.exception(f"更新 widget 失敗: {e}")

    @staticmethod
    def safe_config_widget(widget, **config) -> None:
        """
        安全地配置 widget
        Safely configure widget
        """
        UIUtils.safe_update_widget(
            widget, lambda w, **cfg: w.configure(**cfg), **config
        )

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
        """在 Tk/CTk 主執行緒安全地輪詢並執行 UI 任務佇列。

        - 會自動 coalesce 成單一 after job，避免多重計時器造成撕裂/卡頓。
        - 每次 tick 限制最多執行 max_tasks_per_tick，避免 UI 長時間凍結。
        - 若佇列仍有積壓，會用較短的 busy_interval_ms 追趕。
        """

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
                logger.exception(
                    f"取消舊的 UI queue pump job 失敗（視窗可能已關閉）: {e}"
                )
            try:
                setattr(widget, job_attr, None)
            except Exception as e:
                logger.exception(
                    f"重設 UI queue pump job 欄位失敗（視窗可能已關閉）: {e}"
                )

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
                logger.exception(
                    f"排程下一次 UI queue pump 失敗（視窗可能正在銷毀）: {e}"
                )

        if not _alive():
            return

        _cancel_existing()
        _tick()

    @staticmethod
    def run_in_daemon_thread(
        task_func: Callable,
        *,
        ui_queue: Optional["queue.Queue"] = None,
        widget=None,
        on_error: Optional[Callable[[], None]] = None,
        error_log_prefix: str = "",
        component: str = "UIUtils",
    ) -> None:
        """在背景執行緒執行任務，必要時把 UI 回呼安全地排回主執行緒。

        - task_func：背景工作（請勿直接操作 Tk/CTk UI）。
        - ui_queue：若提供，會把 on_error 以 callable 的形式丟回 UI 佇列（需由主執行緒 pump）。
        - widget：若提供且有 `.after(...)`，會用 `widget.after(0, on_error)` 排回主執行緒。
        - 兩者都未提供時，會直接呼叫 on_error（最後備援）。
        """

        def _dispatch(cb: Optional[Callable[[], None]]) -> None:
            if cb is None:
                return
            if ui_queue is not None:
                try:
                    ui_queue.put(cb)
                    return
                except Exception as e:
                    logger.debug(f"ui_queue put 失敗: {e}", "UIUtils")
                    pass
            if widget is not None:
                try:
                    widget.after(0, cb)
                    return
                except Exception as e:
                    logger.debug(f"widget.after 失敗: {e}", "UIUtils")
                    pass
            try:
                cb()
            except Exception as e:
                logger.debug(f"直接執行 callback 失敗: {e}", "UIUtils")
                pass

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
        wraplength: Optional[int] = None,
        justify: str = "left",
        borderwidth: int = 0,
        relief: str = "flat",
        offset_x: int = 10,
        offset_y: int = 10,
        auto_hide_ms: Optional[int] = None,
    ) -> None:
        """綁定滑鼠移入/移出 tooltip（輕量、可重用）。

        - 以 tk.Toplevel + wm_overrideredirect(True) 實作，避免影響視窗焦點。
        - auto_hide_ms 可選：到期自動關閉（例如 5000ms）。
        """
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
                    pass
            try:
                setattr(widget, "_msm_tooltip", None)
            except Exception as e:
                logger.debug(f"重置 _msm_tooltip 屬性失敗: {e}", "UIUtils")
            job = getattr(widget, "_msm_tooltip_job", None)
            if job is not None:
                try:
                    widget.after_cancel(job)
                except Exception as e:
                    logger.debug(f"取消 tooltip job 失敗: {e}", "UIUtils")
                    pass
            try:
                setattr(widget, "_msm_tooltip_job", None)
            except Exception as e:
                logger.debug(f"重置 _msm_tooltip_job 屬性失敗: {e}", "UIUtils")

        def _show_tooltip(event) -> None:
            try:
                _destroy_tooltip()
                tip = tk.Toplevel(widget.winfo_toplevel())
                tip.wm_overrideredirect(True)
                tip.configure(bg=bg)
                tip.wm_geometry(f"+{event.x_root + offset_x}+{event.y_root + offset_y}")

                label_kwargs = {
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

                setattr(widget, "_msm_tooltip", tip)

                if auto_hide_ms:
                    try:
                        setattr(
                            widget,
                            "_msm_tooltip_job",
                            tip.after(auto_hide_ms, _destroy_tooltip),
                        )
                    except Exception as e:
                        logger.debug(f"設定 tooltip 自動隱藏失敗: {e}", "UIUtils")
                        pass
            except Exception as e:
                logger.exception(f"顯示 tooltip 失敗: {e}")

        def _hide_tooltip(_event=None) -> None:
            _destroy_tooltip()

        try:
            widget.bind("<Enter>", _show_tooltip)
            widget.bind("<Leave>", _hide_tooltip)
        except Exception as e:
            logger.exception(f"綁定 tooltip 事件失敗: {e}")

    # 顯示錯誤對話框
    @staticmethod
    def show_error(
        title: str = "錯誤",
        message: str = "發生未知錯誤",
        parent=None,
        topmost: bool = False,
    ) -> None:
        """
        顯示錯誤訊息對話框，使用 tk 並自動處理圖示和置中
        Display error message dialog using tk with automatic icon and centering handling

        Args:
            title (str): 對話框標題
            message (str): 錯誤訊息內容
            parent: 父視窗物件，None 則使用臨時根視窗

        Returns:
            None
        """
        # 任何顯示給使用者的錯誤，都同時寫入 log，方便追蹤
        logger.error(f"{title}: {message}", "UIUtils")

        try:
            # 如果沒有父視窗，創建臨時根視窗
            if parent is None:
                root = tk.Tk()
                root.withdraw()  # 隱藏主視窗

                if topmost:
                    root.attributes("-topmost", True)

                # 使用 setup_window_properties 統一處理視窗屬性
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

                tk.messagebox.showerror(title, message, parent=root)
                root.destroy()
            else:
                tk.messagebox.showerror(title, message, parent=parent)
        except Exception as e:
            logger.exception(f"顯示錯誤對話框失敗: {e}")
            logger.error(f"錯誤: {title} - {message}")

    # 顯示警告對話框
    @staticmethod
    def show_warning(
        title: str = "警告",
        message: str = "警告訊息",
        parent=None,
        topmost: bool = False,
    ) -> None:
        """
        顯示警告訊息對話框，使用 tk 並自動處理圖示和置中
        Display warning message dialog using tk with automatic icon and centering handling

        Args:
            title (str): 對話框標題
            message (str): 警告訊息內容
            parent: 父視窗物件，None 則使用臨時根視窗

        Returns:
            None
        """
        try:
            # 如果沒有父視窗，創建臨時根視窗
            if parent is None:
                root = tk.Tk()
                root.withdraw()  # 隱藏主視窗

                if topmost:
                    root.attributes("-topmost", True)

                # 使用 setup_window_properties 統一處理視窗屬性
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

                tk.messagebox.showwarning(title, message, parent=root)
                root.destroy()
            else:
                tk.messagebox.showwarning(title, message, parent=parent)
        except Exception as e:
            logger.exception(f"顯示警告對話框失敗: {e}")
            logger.warning(f"警告: {title} - {message}")

    # 顯示資訊對話框
    @staticmethod
    def show_info(
        title: str = "資訊",
        message: str = "資訊訊息",
        parent=None,
        topmost: bool = False,
    ) -> None:
        """
        顯示資訊對話框，使用 tk 並自動處理圖示和置中
        Display information dialog using tk with automatic icon and centering handling

        Args:
            title (str): 對話框標題
            message (str): 資訊訊息內容
            parent: 父視窗物件，None 則使用臨時根視窗

        Returns:
            None
        """
        try:
            # 如果沒有父視窗，創建臨時根視窗
            if parent is None:
                root = tk.Tk()
                root.withdraw()  # 隱藏主視窗

                if topmost:
                    root.attributes("-topmost", True)

                # 使用 setup_window_properties 統一處理視窗屬性
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

                tk.messagebox.showinfo(title, message, parent=root)
                root.destroy()
            else:
                tk.messagebox.showinfo(title, message, parent=parent)
        except Exception as e:
            logger.exception(f"顯示資訊對話框失敗: {e}")
            logger.warning(f"警告: {title} - {message}")

    # 顯示確認對話框（是/否/取消）
    @staticmethod
    def ask_yes_no_cancel(
        title: str = "確認",
        message: str = "請選擇操作",
        parent=None,
        show_cancel: bool = True,
        topmost: bool = False,
    ) -> Optional[bool]:
        """
        顯示確認對話框，支援是/否/取消選項，使用 tk 並呼叫 setup_window_properties
        Display confirmation dialog with Yes/No/Cancel options using tk and setup_window_properties

        Args:
            title (str): 對話框標題
            message (str): 顯示訊息
            parent: 父視窗物件
            show_cancel (bool): 是否顯示取消按鈕
            topmost (bool): 是否系統級置頂

        Returns:
            bool or None: True=點擊是, False=點擊否, None=點擊取消 (僅當 show_cancel=True 時)
        """
        try:
            # 如果沒有父視窗，創建臨時根視窗
            if parent is None:
                root = tk.Tk()
                root.withdraw()  # 隱藏主視窗

                if topmost:
                    root.attributes("-topmost", True)

                # 使用 setup_window_properties 統一處理視窗屬性
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
                    result = tk.messagebox.askyesnocancel(title, message, parent=root)
                else:
                    result = tk.messagebox.askyesno(title, message, parent=root)
                root.destroy()
                return result
            else:
                if show_cancel:
                    return tk.messagebox.askyesnocancel(title, message, parent=parent)
                else:
                    return tk.messagebox.askyesno(title, message, parent=parent)
        except Exception as e:
            logger.exception(f"顯示確認對話框失敗: {e}")
            logger.warning(f"確認: {title} - {message}")
            return False if not show_cancel else None

    @staticmethod
    def apply_unified_dropdown_styling(dropdown_widget) -> None:
        """
        統一下拉選單樣式
        Apply unified dropdown styling for light theme with mouse wheel support
        """
        try:
            # 固定淺色模式：白色背景黑字
            style_config = {
                "fg_color": ("#ffffff", "#ffffff"),  # 白色背景
                "button_color": ("#e5e7eb", "#e5e7eb"),  # 淺灰色按鈕
                "button_hover_color": ("#d1d5db", "#d1d5db"),  # 按鈕懸停
                "dropdown_fg_color": ("#ffffff", "#ffffff"),  # 下拉清單背景
                "dropdown_hover_color": ("#f3f4f6", "#f3f4f6"),  # 下拉清單懸停
                "dropdown_text_color": ("#1f2937", "#1f2937"),  # 下拉清單文字
                "text_color": ("#1f2937", "#1f2937"),  # 主文字顏色
            }

            # 應用樣式到下拉選單
            dropdown_widget.configure(**style_config)

            # 新增：滑鼠滾輪支援
            def on_mouse_wheel(event):
                """處理滑鼠滾輪事件"""
                try:
                    # 獲取當前值和選項列表
                    current_value = dropdown_widget.get()
                    values = dropdown_widget.cget("values")

                    if values and current_value in values:
                        current_index = values.index(current_value)

                        # 向上滾動 (event.delta > 0) 選擇上一個選項
                        # 向下滾動 (event.delta < 0) 選擇下一個選項
                        if event.delta > 0 and current_index > 0:
                            new_index = current_index - 1
                        elif event.delta < 0 and current_index < len(values) - 1:
                            new_index = current_index + 1
                        else:
                            return

                        # 設定新值
                        dropdown_widget.set(values[new_index])

                        # 如果有 command 回調，執行它
                        if (
                            hasattr(dropdown_widget, "_command")
                            and dropdown_widget._command
                        ):
                            dropdown_widget._command(values[new_index])

                except Exception as e:
                    logger.exception(f"滑鼠滾輪處理錯誤: {e}")

            # 綁定滑鼠滾輪事件
            dropdown_widget.bind("<MouseWheel>", on_mouse_wheel)

        except Exception as e:
            logger.exception(f"應用下拉選單樣式失敗: {e}")

    @staticmethod
    def create_styled_button(
        parent, text, command, button_type="secondary", **kwargs
    ) -> ctk.CTkButton:
        """
        建立統一樣式的按鈕
        建立具有統一樣式的按鈕，自動應用全域DPI縮放因子

        Args:
            parent: 父容器
            text: 按鈕文字
            command: 點擊事件
            button_type: 'primary', 'secondary', 'small', 'cancel'
            **kwargs: 其他按鈕參數（會覆蓋預設值）
        """
        # 從字體管理器獲取當前的DPI縮放因子
        scale_factor = font_manager.get_scale_factor()

        # 根據按鈕類型設定樣式
        if button_type == "primary":
            button_style = {
                "fg_color": ("#1f4e79", "#0f2a44"),  # 更深的藍色，提高對比
                "hover_color": ("#0f2a44", "#071925"),
                "text_color": ("#ffffff", "#ffffff"),  # 確保文字為白色
                "font": font_manager.get_font(
                    family="Microsoft JhengHei", size=18, weight="bold"
                ),
                "width": int(180 * scale_factor),
                "height": int(60 * scale_factor),
            }
        elif button_type == "secondary":
            button_style = {
                "fg_color": ("#2d3748", "#1a202c"),  # 深灰色背景
                "hover_color": ("#1a202c", "#0d1117"),
                "text_color": ("#ffffff", "#ffffff"),  # 白色文字
                "font": font_manager.get_font(family="Microsoft JhengHei", size=18),
                "width": int(120 * scale_factor),
                "height": int(42 * scale_factor),
            }
        elif button_type == "small":
            button_style = {
                "fg_color": ("#4a5568", "#2d3748"),  # 灰色背景
                "hover_color": ("#2d3748", "#1a202c"),
                "text_color": ("#ffffff", "#ffffff"),  # 白色文字確保對比
                "font": font_manager.get_font(family="Microsoft JhengHei", size=18),
                "width": int(80 * scale_factor),
                "height": int(30 * scale_factor),
            }
        elif button_type == "cancel":
            button_style = {
                "fg_color": ("#dc2626", "#991b1b"),  # 更深的紅色
                "hover_color": ("#991b1b", "#7f1d1d"),
                "text_color": ("#ffffff", "#ffffff"),  # 白色文字
                "font": font_manager.get_font(family="Microsoft JhengHei", size=18),
                "width": int(120 * scale_factor),
                "height": int(48 * scale_factor),
            }
        else:
            button_style = {}

        # 合併所有樣式
        final_style = {**button_style, **kwargs}

        return ctk.CTkButton(parent, text=text, command=command, **final_style)

class ProgressDialog:
    """
    進度條對話框
    Progress dialog with a progress bar and status label.
    """

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
        self.status_label = ctk.CTkLabel(
            content_frame, text="準備中...", font=font_manager.get_font(size=12)
        )
        self.status_label.pack(pady=(10, 15))

        # 進度條
        self.progress = ctk.CTkProgressBar(
            content_frame, width=410, height=20
        )  # 調整寬度以配合新的視窗大小
        self.progress.pack(pady=(0, 15))
        self.progress.set(0)

        # 百分比標籤
        self.percent_label = ctk.CTkLabel(
            content_frame, text="0%", font=font_manager.get_font(size=11)
        )
        self.percent_label.pack()

        # 取消按鈕（可選）
        if show_cancel:
            self.cancel_button = ctk.CTkButton(
                content_frame,
                text="取消",
                command=self.cancel,
                fg_color=("#ef4444", "#dc2626"),
                hover_color=("#dc2626", "#b91c1c"),
                font=font_manager.get_font(size=12),
                width=80,
                height=38,
            )
            self.cancel_button.pack(pady=(15, 0))

        self.cancelled = False
        self._last_ui_pump = 0.0

    def update_progress(self, percent, status_text) -> bool:
        """
        更新進度 (Thread-safe)
        Update the progress.
        """
        if self.cancelled:
            return False

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
            # 避免過於頻繁的 event loop pump 造成閃爍；仍保留可處理取消按鈕點擊的能力
            now = time.monotonic()
            if now - self._last_ui_pump >= 0.05:
                self._last_ui_pump = now
                self.dialog.update()
            else:
                self.dialog.update_idletasks()
        else:
            self.dialog.after(0, _update)

        return True

    def cancel(self) -> None:
        """
        取消操作
        Cancel the operation.
        """
        self.cancelled = True
        self.dialog.destroy()

    def close(self) -> None:
        """
        關閉對話框
        Close the dialog.
        """
        try:
            self.dialog.destroy()
        except Exception as e:
            logger.exception(f"關閉進度對話框失敗: {e}")
