"""進度對話框元件。

提供可取消的進度視窗，供長時間 UI 作業共用。
"""

from __future__ import annotations

import threading
from typing import Any

import customtkinter as ctk

from ..utils import Colors, Sizes, Spacing, get_logger
from . import DialogUtils, FontManager

logger = get_logger().bind(component="ProgressDialog")


class ProgressDialog:
    """顯示可取消的進度對話框。"""

    def __init__(self, parent: Any, title: str = "進度", show_cancel: bool = True) -> None:
        """建立進度對話框。"""
        self.dialog = DialogUtils.create_toplevel_dialog(
            parent,
            title,
            width=Sizes.INPUT_WIDTH,
            height=Sizes.DIALOG_SMALL_HEIGHT,
            resizable=False,
            bind_icon=True,
            center_on_parent=True,
            make_modal=True,
            delay_ms=250,
            autosize_to_content=True,
            min_width=300,
            min_height=120,
            reveal_after_setup=False,
        )
        content_frame = ctk.CTkFrame(self.dialog)
        content_frame.pack(fill="both", expand=True, padx=Spacing.LARGE, pady=Spacing.LARGE)
        self.status_label = ctk.CTkLabel(content_frame, text="準備中...", font=FontManager.get_font(size=12))
        self.status_label.pack(pady=(Spacing.SMALL_PLUS, Spacing.LARGE_MINUS))
        self.progress = ctk.CTkProgressBar(content_frame, width=350, height=Spacing.XL)
        self.progress.pack(pady=(0, Spacing.LARGE_MINUS))
        self.progress.set(0)
        self.percent_label = ctk.CTkLabel(content_frame, text="0%", font=FontManager.get_font(size=11))
        self.percent_label.pack()
        if show_cancel:
            self.cancel_button = ctk.CTkButton(
                content_frame,
                text="取消",
                command=self.cancel,
                fg_color=(Colors.TEXT_ERROR[0], Colors.BUTTON_DANGER[0]),
                hover_color=("#dc2626", Colors.BUTTON_DANGER_HOVER[1]),
                font=FontManager.get_font(size=12),
                width=Sizes.BUTTON_WIDTH_COMPACT,
                height=Sizes.BUTTON_HEIGHT_LARGE,
            )
            self.cancel_button.pack(pady=(Spacing.LARGE_MINUS, 0))
        self.cancelled = False
        self._last_ui_pump = 0.0
        self._pending_update = False
        self._last_percent: float = -1.0
        self._last_status = ""

    def update_progress(self, percent: float, status_text: str) -> bool:
        """更新進度百分比與狀態文字。

        Args:
            percent: 進度百分比。
            status_text: 要顯示的狀態文字。

        Returns:
            若對話框尚未取消則回傳 True，否則回傳 False。
        """
        if self.cancelled:
            return False
        current_percent = getattr(self, "_last_percent", -1)
        current_status = getattr(self, "_last_status", "")
        if current_percent == percent and current_status == status_text:
            return True
        self._last_percent = percent
        self._last_status = status_text

        def _update() -> None:
            if self.cancelled:
                return
            try:
                self.progress.set(percent / 100.0)
                self.status_label.configure(text=status_text)
                self.percent_label.configure(text=f"{percent:.1f}%")
            except Exception as exc:
                logger.exception(f"更新進度 UI 失敗: {exc}")

        if threading.current_thread() is threading.main_thread():
            _update()
            if not getattr(self, "_pending_update", False):
                self._pending_update = True
                self.dialog.after_idle(self._do_idle_update)
        else:
            self.dialog.after(0, _update)
        return True

    def _do_idle_update(self) -> None:
        """在 idle 時刷新控制項。"""
        try:
            if self.cancelled or not self.dialog.winfo_exists():
                return
            self.dialog.update_idletasks()
        except Exception as exc:
            logger.exception(f"進度對話框 idle 更新失敗: {exc}")
        finally:
            self._pending_update = False

    def cancel(self) -> None:
        """取消並關閉對話框。"""
        self.cancelled = True
        self.dialog.destroy()

    def close(self) -> None:
        """關閉對話框。"""
        try:
            self.dialog.destroy()
        except Exception as exc:
            logger.exception(f"關閉進度對話框失敗: {exc}")


__all__ = ["ProgressDialog"]
