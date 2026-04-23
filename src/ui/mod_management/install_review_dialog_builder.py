"""安裝與更新 Review 對話框建構器。"""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from ...utils import Colors, FontSize, Sizes, Spacing
from ..dialog_utils import DialogUtils
from ..font_manager import FontManager
from .models import LocalUpdateReviewEntry, PendingInstallReviewEntry
from .presenter_delegate_mixin import PresenterDelegateMixin


class InstallReviewDialogBuilder(PresenterDelegateMixin):
    """集中建立 Review 對話框的共用 UI 元件與單筆檢視。"""

    def __init__(self, frame: Any):
        super().__init__(frame)

    @staticmethod
    def create_review_summary_box(parent: Any, *, height: int) -> ctk.CTkTextbox:
        """
        建立 Review 右側/下方摘要文字框。

        Args:
            parent: 摘要框的父容器。
            height: 摘要框的高度（像素）。寬度會自動調整以填滿父容器。
        Returns:
            建立完成的 ctk.CTkTextbox 實例，已設定為唯讀模式。
        """
        summary_box = ctk.CTkTextbox(
            parent,
            height=FontManager.get_dpi_scaled_size(height),
            font=FontManager.get_font(size=FontSize.NORMAL_PLUS),
            wrap="word",
        )
        summary_box.pack(fill="x", padx=Spacing.MEDIUM, pady=(0, Spacing.MEDIUM))
        summary_box.configure(state="disabled")
        return summary_box

    def create_review_shared_ui(self, main_frame: ctk.CTkFrame, wraplength: int) -> tuple[ctk.CTkLabel, ctk.CTkFrame]:
        """
        建立 Review 對話框中重複使用的概覽標籤與樹狀視圖容器。

        Args:
            main_frame: 這些 UI 元件的父容器。
            wraplength: 概覽標籤的文字換行長度（像素）。
        Returns:
            包含概覽標籤與樹狀視圖容器的元組。
        """
        overview_label = ctk.CTkLabel(
            main_frame,
            text="",
            font=FontManager.get_font(size=FontSize.NORMAL),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=FontManager.get_dpi_scaled_size(wraplength),
        )
        overview_label.pack(fill="x", padx=Spacing.MEDIUM, pady=(0, Spacing.TINY))
        tree_container = ctk.CTkFrame(main_frame)
        tree_container.pack(fill="both", expand=True, padx=Spacing.MEDIUM, pady=(0, Spacing.MEDIUM))
        return overview_label, tree_container

    def build_review_dialog(self, review_entry: PendingInstallReviewEntry | LocalUpdateReviewEntry) -> Any:
        """
        建立單筆安裝或更新 review 的詳細檢視對話框。

        Args:
            review_entry: 包含待檢視的安裝或更新資訊的 review entry 實例。
        Returns:
            建立完成的對話框實例。
         Raises:
            TypeError: 當 review_entry 的類型不受支援時引發。
        """
        if isinstance(review_entry, PendingInstallReviewEntry):
            title = "安裝項目 Review"
            heading = "待安裝模組詳細資訊"
            body = self._format_pending_install_review_text(review_entry)
            project_page_url = self._resolve_pending_install_review_project_page_url(review_entry)
        elif isinstance(review_entry, LocalUpdateReviewEntry):
            title = "本地模組更新 Review"
            heading = "本地模組更新詳細資訊"
            body = self._format_local_update_review_text(review_entry)
            project_page_url = self._resolve_local_update_review_project_page_url(review_entry)
        else:
            raise TypeError(f"不支援的 review entry 類型: {type(review_entry).__name__}")
        dialog = DialogUtils.create_toplevel_dialog(
            self.parent,
            title,
            width=Sizes.DIALOG_MEDIUM_WIDTH,
            height=Sizes.DIALOG_MEDIUM_HEIGHT,
            make_modal=True,
            bind_icon=True,
            center_on_parent=True,
            delay_ms=150,
            min_width=FontManager.get_dpi_scaled_size(720),
            min_height=FontManager.get_dpi_scaled_size(560),
            native_window=True,
            use_transient_for_modal=False,
        )
        main_frame = ctk.CTkFrame(dialog)
        main_frame.pack(fill="both", expand=True, padx=Spacing.LARGE, pady=Spacing.LARGE)
        title_label = ctk.CTkLabel(
            main_frame,
            text=heading,
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
        )
        title_label.pack(anchor="w", padx=Spacing.MEDIUM, pady=(Spacing.MEDIUM, Spacing.SMALL))
        summary_box = ctk.CTkTextbox(
            main_frame,
            font=FontManager.get_font(size=FontSize.SMALL_PLUS),
            wrap="word",
        )
        summary_box.pack(fill="both", expand=True, padx=Spacing.MEDIUM, pady=(0, Spacing.MEDIUM))
        summary_box.insert("1.0", body)
        summary_box.configure(state="disabled")
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x", padx=Spacing.MEDIUM, pady=(0, Spacing.SMALL))
        project_button = ctk.CTkButton(
            button_frame,
            text="開啟專案頁面",
            font=FontManager.get_font(size=FontSize.LARGE),
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            command=lambda: self._open_project_page(project_page_url, dialog),
            state="normal" if project_page_url else "disabled",
        )
        project_button.pack(side="left")
        close_button = ctk.CTkButton(
            button_frame,
            text="關閉",
            font=FontManager.get_font(size=FontSize.LARGE),
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            command=dialog.destroy,
        )
        close_button.pack(side="right")
        DialogUtils.schedule_toplevel_layout_refresh(
            dialog,
            min_width=FontManager.get_dpi_scaled_size(720),
            min_height=FontManager.get_dpi_scaled_size(560),
            parent=self.parent,
        )
        return dialog


__all__ = ["InstallReviewDialogBuilder"]
