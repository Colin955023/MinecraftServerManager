"""對話框與視窗生命週期工具。"""

from __future__ import annotations

import contextlib
import tkinter
import tkinter.messagebox as messagebox
import tkinter.scrolledtext as scrolledtext
from typing import Any

import customtkinter as ctk

from ..utils import Colors, Sizes, Spacing, WindowManager, get_logger
from . import FontManager, IconUtils

logger = get_logger().bind(component="DialogUtils")


class DialogUtils:
    """集中管理對話框建立、置中、縮放與顯示流程。"""

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
        topmost: bool = False,
        autosize_to_content: bool = False,
        min_width: int | None = None,
        min_height: int | None = None,
        max_width: int | None = None,
        max_height: int | None = None,
        start_maximized: bool = False,
        use_transient_for_modal: bool = True,
        reveal_after_setup: bool = True,
        enforce_max_size_limits: bool = False,
    ) -> None:
        """統一的視窗屬性設定函數，整合圖示綁定、視窗置中、模態設定三個功能。

        Args:
            window: 要設定的視窗。
            parent: 父視窗。
            width: 初始寬度。
            height: 初始高度。
            其他參數: 控制圖示、模態、最大尺寸與顯示行為。
        """
        WindowManager.setup_dialog_window(
            window, parent=parent, width=width, height=height, center_on_parent=center_on_parent
        )
        scaled_min_width = FontManager.get_dpi_scaled_size(int(min_width)) if min_width else 0
        scaled_min_height = FontManager.get_dpi_scaled_size(int(min_height)) if min_height else 0
        scaled_max_width = FontManager.get_dpi_scaled_size(int(max_width)) if max_width else 0
        scaled_max_height = FontManager.get_dpi_scaled_size(int(max_height)) if max_height else 0
        if scaled_min_width or scaled_min_height:
            try:
                window.minsize(max(1, scaled_min_width), max(1, scaled_min_height))
            except Exception as e:
                logger.debug(f"設定對話框最小尺寸失敗: {e}", "DialogUtils")
        if enforce_max_size_limits and (scaled_max_width or scaled_max_height):
            try:
                max_width_value = max(1, scaled_max_width or window.winfo_screenwidth())
                max_height_value = max(1, scaled_max_height or window.winfo_screenheight())
                window.maxsize(max_width_value, max_height_value)
            except Exception as e:
                logger.debug(f"設定對話框最大尺寸失敗: {e}", "DialogUtils")

        def finalize_dialog_visibility() -> None:
            if make_modal and parent:
                try:
                    if use_transient_for_modal:
                        window.transient(parent)
                    window.grab_set()
                    window.focus_set()
                except Exception as e:
                    logger.exception(f"設定模態視窗失敗: {e}")
            if topmost:
                try:
                    window.attributes("-topmost", True)
                except Exception as e:
                    logger.debug(f"設定視窗置頂失敗: {e}", "DialogUtils")
            if reveal_after_setup:
                try:
                    window.deiconify()
                    window.lift()
                    window.update_idletasks()
                except Exception as e:
                    logger.debug(f"顯示對話框失敗: {e}", "DialogUtils")

        if bind_icon:
            IconUtils.set_window_icon(window, delay_ms)
        if autosize_to_content:
            try:
                window.after_idle(
                    lambda: DialogUtils.autosize_toplevel_to_content(
                        window,
                        min_width=int(min_width or width or 0),
                        min_height=int(min_height or height or 0),
                        max_width=max_width,
                        max_height=max_height,
                        parent=parent,
                    )
                )
            except Exception as e:
                logger.debug(f"排程自動調整視窗大小失敗: {e}", "DialogUtils")
        if start_maximized:
            try:
                window.after(max(0, int(delay_ms)), lambda: DialogUtils.maximize_window(window))
            except Exception as e:
                logger.debug(f"排程視窗最大化失敗: {e}", "DialogUtils")
        try:
            window.after_idle(finalize_dialog_visibility)
        except Exception as e:
            logger.debug(f"排程顯示對話框失敗: {e}", "DialogUtils")
            finalize_dialog_visibility()

    @staticmethod
    def maximize_window(window) -> None:
        """將對話框最大化，並兼容不同視窗管理器的行為。

        Args:
            window: 要最大化的視窗。
        """

        if not window:
            return
        with contextlib.suppress(Exception):
            window.maxsize(window.winfo_screenwidth(), window.winfo_screenheight())
        try:
            if hasattr(window, "state"):
                window.state("zoomed")
                return
        except Exception as e:
            logger.debug(f"使用 state('zoomed') 最大化失敗: {e}", "DialogUtils")
        try:
            window.attributes("-zoomed", True)
        except Exception as e:
            logger.debug(f"使用 -zoomed 最大化失敗: {e}", "DialogUtils")

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
        topmost: bool = False,
        autosize_to_content: bool = False,
        min_width: int | None = None,
        min_height: int | None = None,
        max_width: int | None = None,
        max_height: int | None = None,
        start_maximized: bool = False,
        native_window: bool = False,
        use_transient_for_modal: bool = True,
        reveal_after_setup: bool = True,
        enforce_max_size_limits: bool = False,
    ) -> tkinter.Toplevel | ctk.CTkToplevel:
        """建立並套用專案一致的 dialog 視窗屬性。

        Args:
            parent: 父視窗。
            title: 視窗標題。
            其他參數: 控制尺寸、模態、圖示與顯示行為。

        Returns:
            建立好的對話框視窗物件。
        """
        dialog = tkinter.Toplevel(parent) if native_window else ctk.CTkToplevel(parent)
        if reveal_after_setup:
            try:
                dialog.withdraw()
            except Exception as e:
                logger.debug(f"建立對話框時預先隱藏失敗: {e}", "DialogUtils")
        dialog.title(title)
        dialog.resizable(resizable, resizable)
        DialogUtils.setup_window_properties(
            window=dialog,
            parent=parent,
            width=width,
            height=height,
            bind_icon=bind_icon,
            center_on_parent=center_on_parent,
            make_modal=make_modal,
            delay_ms=delay_ms,
            topmost=topmost,
            autosize_to_content=autosize_to_content,
            min_width=min_width,
            min_height=min_height,
            max_width=max_width,
            max_height=max_height,
            start_maximized=start_maximized,
            use_transient_for_modal=use_transient_for_modal,
            reveal_after_setup=reveal_after_setup,
            enforce_max_size_limits=enforce_max_size_limits,
        )
        return dialog

    @staticmethod
    def schedule_toplevel_layout_refresh(
        dialog,
        *,
        min_width: int = 0,
        min_height: int = 0,
        max_width: int | None = None,
        max_height: int | None = None,
        parent=None,
        delays_ms: tuple[int, ...] = (0, 120),
        preserve_current_size: bool = True,
    ) -> None:
        """在內容建構完成後重新整理對話框尺寸，降低初次開啟時被裁切的機率。

        Args:
            dialog: 要重新整理的對話框。
            min_width: 最小寬度。
            min_height: 最小高度。
            max_width: 最大寬度。
            max_height: 最大高度。
            parent: 父視窗。
            delays_ms: 要排程的延遲時間序列。
            preserve_current_size: 是否保留目前大小。
        """
        if not dialog:
            return
        for delay_ms in delays_ms:
            try:
                dialog.after(
                    max(0, int(delay_ms)),
                    lambda: DialogUtils.autosize_toplevel_to_content(
                        dialog,
                        min_width=min_width,
                        min_height=min_height,
                        max_width=max_width,
                        max_height=max_height,
                        parent=parent,
                        preserve_current_size=preserve_current_size,
                    ),
                )
            except Exception as e:
                logger.debug(f"排程對話框尺寸刷新失敗: {e}", "DialogUtils")
                break

    @staticmethod
    def autosize_toplevel_to_content(
        dialog,
        *,
        min_width: int = 0,
        min_height: int = 0,
        max_width: int | None = None,
        max_height: int | None = None,
        parent=None,
        preserve_current_size: bool = True,
    ) -> None:
        """依內容實際需求調整對話框大小，避免初次開啟時過小。

        Args:
            dialog: 要調整大小的對話框。
            min_width: 最小寬度。
            min_height: 最小高度。
            max_width: 最大寬度。
            max_height: 最大高度。
            parent: 父視窗。
            preserve_current_size: 是否保留目前大小。
        """
        if not dialog:
            return
        try:
            dialog.update_idletasks()
            requested_width = int(dialog.winfo_reqwidth())
            requested_height = int(dialog.winfo_reqheight())
            current_width = int(dialog.winfo_width())
            current_height = int(dialog.winfo_height())
            target_width = max(int(min_width), requested_width)
            target_height = max(int(min_height), requested_height)
            if preserve_current_size:
                if current_width > 1:
                    target_width = max(target_width, current_width)
                if current_height > 1:
                    target_height = max(target_height, current_height)
            if max_width is not None:
                target_width = min(target_width, int(max_width))
            if max_height is not None:
                target_height = min(target_height, int(max_height))
            logger.debug(
                f"依內容調整對話框大小: req={requested_width}x{requested_height}, current={current_width}x{current_height}, target={target_width}x{target_height}",
                "DialogUtils",
            )
            WindowManager.setup_dialog_window(
                dialog, parent=parent, width=target_width, height=target_height, center_on_parent=True
            )
        except Exception as e:
            logger.debug(f"依內容調整對話框大小失敗: {e}", "DialogUtils")

    @staticmethod
    def _show_messagebox(
        message_func,
        title: str,
        message: str,
        parent=None,
        topmost: bool = False,
        log_level: str = "error",
    ) -> None:
        """統一的訊息對話框顯示方法。"""
        log_msg = f"{title}: {message}"
        if log_level == "error":
            logger.error(log_msg)
        elif log_level == "warning":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)
        try:
            if parent is None:
                root = tkinter.Tk()
                root.withdraw()
                if topmost:
                    root.attributes("-topmost", True)
                DialogUtils.setup_window_properties(
                    root,
                    parent=None,
                    width=Sizes.INPUT_WIDTH,
                    height=Sizes.SERVER_TREE_COL_LOADER,
                    bind_icon=True,
                    center_on_parent=True,
                    make_modal=True,
                    delay_ms=50,
                    reveal_after_setup=False,
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
    def show_error(title: str = "錯誤", message: str = "發生未知錯誤", parent=None, topmost: bool = False) -> None:
        """顯示錯誤訊息對話框。

        Args:
            title: 對話框標題。
            message: 要顯示的訊息。
            parent: 父視窗。
            topmost: 是否置頂。
        """
        DialogUtils._show_messagebox(messagebox.showerror, title, message, parent, topmost, "error")

    @staticmethod
    def show_warning(title: str = "警告", message: str = "警告訊息", parent=None, topmost: bool = False) -> None:
        """顯示警告訊息對話框。

        Args:
            title: 對話框標題。
            message: 要顯示的訊息。
            parent: 父視窗。
            topmost: 是否置頂。
        """
        DialogUtils._show_messagebox(messagebox.showwarning, title, message, parent, topmost, "warning")

    @staticmethod
    def show_info(title: str = "資訊", message: str = "資訊訊息", parent=None, topmost: bool = False) -> None:
        """顯示資訊對話框。

        Args:
            title: 對話框標題。
            message: 要顯示的訊息。
            parent: 父視窗。
            topmost: 是否置頂。
        """
        DialogUtils._show_messagebox(messagebox.showinfo, title, message, parent, topmost, "info")

    @staticmethod
    def ask_yes_no_cancel(
        title: str = "確認", message: str = "請選擇操作", parent=None, show_cancel: bool = True, topmost: bool = False
    ) -> bool | None:
        """顯示確認對話框，支援是/否/取消選項。

        Args:
            title: 對話框標題。
            message: 要顯示的訊息。
            parent: 父視窗。
            show_cancel: 是否顯示取消按鈕。
            topmost: 是否置頂。

        Returns:
            使用者選擇結果；是/否 對應 True/False，取消時回傳 None。
        """
        try:
            if parent is None:
                root = tkinter.Tk()
                root.withdraw()
                if topmost:
                    root.attributes("-topmost", True)
                DialogUtils.setup_window_properties(
                    root,
                    parent=None,
                    width=Sizes.INPUT_WIDTH,
                    height=Sizes.SERVER_TREE_COL_LOADER,
                    bind_icon=True,
                    center_on_parent=True,
                    make_modal=False,
                    delay_ms=50,
                    reveal_after_setup=False,
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
    def create_tooltip_window(
        parent,
        text: str,
        *,
        bg: str = Colors.BG_LISTBOX_DARK,
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
        x_root: int = 0,
        y_root: int = 0,
    ):
        """建立 tooltip 彈出視窗。

        Args:
            parent: 觸發 tooltip 的元件。
            text: 要顯示的文字。
            其他參數: 控制外觀與位置偏移。

        Returns:
            建立好的 tooltip 視窗，若無法建立則回傳 None。
        """
        owner = parent.winfo_toplevel() if parent is not None and hasattr(parent, "winfo_toplevel") else parent
        if owner is None:
            return None
        tip = tkinter.Toplevel(owner)
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
        tkinter.Label(tip, **label_kwargs).pack()
        return tip

    @staticmethod
    def show_manual_restart_dialog(parent, details: str | None) -> None:
        """顯示需要手動重啟的對話框，並提供複製診斷按鈕。

        Args:
            parent: 父視窗。
            details: 要顯示的診斷內容。
        """
        try:
            dialog = DialogUtils.create_toplevel_dialog(
                parent,
                "需要手動重啟",
                width=Sizes.DIALOG_MEDIUM_WIDTH,
                height=Sizes.DIALOG_SMALL_HEIGHT,
                make_modal=True,
            )
            tkinter.Label(dialog, text="設定已變更，但需要手動重新啟動應用程式。", anchor="w").pack(
                fill="x", padx=Spacing.MEDIUM, pady=(Spacing.MEDIUM, Spacing.TINY)
            )
            text_box = scrolledtext.ScrolledText(dialog, wrap="word", height=Spacing.MEDIUM)
            text_box.pack(fill="both", expand=True, padx=Spacing.MEDIUM, pady=(0, Spacing.SMALL))
            text_box.insert("1.0", details or "")
            text_box.configure(state="disabled")

            def _copy() -> None:
                try:
                    dialog.clipboard_clear()
                    dialog.clipboard_append(details or "")
                except Exception as exc:
                    logger.debug(f"複製診斷內容失敗: {exc}")

            button_frame = tkinter.Frame(dialog)
            button_frame.pack(fill="x", padx=Spacing.MEDIUM, pady=(0, Spacing.MEDIUM))
            tkinter.Button(button_frame, text="複製診斷", command=_copy).pack(side="left")
            tkinter.Button(button_frame, text="我會手動重啟", command=dialog.destroy).pack(side="right")
        except Exception:
            DialogUtils.show_info("需要手動重啟", f"設定已變更，但自動重啟失敗。\n\n診斷：\n{details}", parent=parent)


__all__ = ["DialogUtils"]
