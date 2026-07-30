"""安裝與更新 Review 對話框建構器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models import LocalUpdateReviewEntry, PendingInstallReviewEntry
from ...utils import Colors, FontManager, FontSize, Sizes, Spacing, TreeUtils
from ...utils.ui_support import qt_widgets as qt
from .constants import MOD_MANAGEMENT_UI_SCALE
from .presenter_delegate_mixin import PresenterDelegateMixin


@dataclass(slots=True)
class ReviewDialogShell:
    """包含 Review 對話框中共用 UI 元件的容器。"""

    dialog: Any
    main_frame: qt.Frame
    subtitle: qt.Label
    overview_label: qt.Label
    tree_container: qt.Frame
    summary_box: qt.TextBox
    button_frame: qt.Frame


class InstallReviewDialogBuilder(PresenterDelegateMixin):
    """集中建立 Review 對話框的共用 UI 元件與單筆檢視。"""

    def __init__(self, frame: Any):
        super().__init__(frame)

    @staticmethod
    def _create_dialog_main_frame(dialog: Any) -> qt.Frame:
        """
        建立對話框的主要容器並設定邊距與填滿模式。

        Args:
            dialog: 對話框實例。
        Returns:
            設定完成的 qt.Frame 實例。
        """
        s = MOD_MANAGEMENT_UI_SCALE
        main_frame = qt.Frame(dialog)
        main_frame.attach(fill="both", expand=True, padx=int(Spacing.LARGE * s), pady=int(Spacing.LARGE * s))
        return main_frame

    @staticmethod
    def create_review_summary_box(parent: Any, *, height: int) -> qt.TextBox:
        """
        建立 Review 右側/下方摘要文字框。

        Args:
            parent: 摘要框的父容器。
            height: 摘要框的高度（像素）。寬度會自動調整以填滿父容器。
        Returns:
            建立完成的 qt.TextBox 實例，已設定為唯讀模式。
        """
        s = MOD_MANAGEMENT_UI_SCALE
        summary_box = qt.TextBox(
            parent,
            height=int(height * s),
            font=FontManager.get_font(size=int(FontSize.NORMAL_PLUS * s)),
            wrap="word",
        )
        summary_box.attach(fill="x", padx=int(Spacing.MEDIUM * s), pady=(0, int(Spacing.MEDIUM * s)))
        summary_box.setReadOnly(True)
        return summary_box

    def create_review_shared_ui(self, main_frame: qt.Frame, wraplength: int) -> tuple[qt.Label, qt.Frame]:
        """
        建立 Review 對話框中重複使用的概覽標籤與樹狀視圖容器。

        Args:
            main_frame: 這些 UI 元件的父容器。
            wraplength: 概覽標籤的文字換行長度（像素）。
        Returns:
            包含概覽標籤與樹狀視圖容器的元組。
        """
        s = MOD_MANAGEMENT_UI_SCALE
        overview_label = qt.Label(
            main_frame,
            text="",
            font=FontManager.get_font(size=int(FontSize.NORMAL * s)),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=int(wraplength * s),
        )
        overview_label.attach(fill="x", padx=int(Spacing.MEDIUM * s), pady=(0, int(Spacing.TINY * s)))
        tree_container = qt.Frame(main_frame)
        tree_container.attach(fill="both", expand=True, padx=int(Spacing.MEDIUM * s), pady=(0, int(Spacing.MEDIUM * s)))
        return overview_label, tree_container

    @staticmethod
    def _create_dialog_title(parent: Any, heading: str) -> qt.Label:
        s = MOD_MANAGEMENT_UI_SCALE
        title_label = qt.Label(
            parent,
            text=heading,
            font=FontManager.get_font(size=int(FontSize.HEADING_LARGE * s), weight="bold"),
        )
        title_label.attach(
            anchor="w", padx=int(Spacing.MEDIUM * s), pady=(int(Spacing.MEDIUM * s), int(Spacing.SMALL * s))
        )
        return title_label

    def create_review_dialog_shell(
        self,
        *,
        dialog_title: str,
        heading: str,
        subtitle_text: str,
        subtitle_wraplength: int,
        overview_wraplength: int,
        summary_height: int,
        width: int,
        height: int,
        min_width: int,
        min_height: int,
    ) -> ReviewDialogShell:
        """
        建立 Review 對話框的共用骨架。

        Args:
            dialog_title: 對話框的標題文字。
            heading: 對話框內部的主要標題文字。
            subtitle_text: 對話框內部的副標題文字。
            subtitle_wraplength: 副標題的文字換行長度（像素）。
            overview_wraplength: 概覽標籤的文字換行長度（像素）。
            summary_height: 摘要框的高度（像素）。
            width: 對話框的初始寬度（像素）。
            height: 對話框的初始高度（像素）。
            min_width: 對話框的最小寬度（像素）。
            min_height: 對話框的最小高度（像素）。
        Returns:
            包含對話框及其共用 UI 元件的 ReviewDialogShell 實例。
        """
        s = MOD_MANAGEMENT_UI_SCALE
        dialog = qt.PlainWindow(title=dialog_title)
        dialog.resize(int(width * s), int(height * s))
        dialog.setMinimumSize(int(min_width * s), int(min_height * s))
        main_frame = self._create_dialog_main_frame(dialog)
        self._create_dialog_title(main_frame, heading)
        subtitle = qt.Label(
            main_frame,
            text=subtitle_text,
            font=FontManager.get_font(size=int(FontSize.SMALL_PLUS * s)),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=int(subtitle_wraplength * s),
        )
        subtitle.attach(fill="x", padx=int(Spacing.MEDIUM * s), pady=(0, int(Spacing.TINY * s)))
        overview_label, tree_container = self.create_review_shared_ui(main_frame, overview_wraplength)
        summary_box = self.create_review_summary_box(main_frame, height=summary_height)
        button_frame = qt.Frame(main_frame, fg_color="transparent")
        button_frame.attach(fill="x", padx=int(Spacing.MEDIUM * s), pady=(0, int(Spacing.SMALL * s)))
        return ReviewDialogShell(
            dialog=dialog,
            main_frame=main_frame,
            subtitle=subtitle,
            overview_label=overview_label,
            tree_container=tree_container,
            summary_box=summary_box,
            button_frame=button_frame,
        )

    def create_review_tree(
        self,
        tree_container: qt.Frame,
        *,
        tree_heading: str,
        columns: tuple[str, ...],
        column_specs: list[tuple[str, str, int, int, bool, str]],
        tree_column_width: int,
        tree_column_minwidth: int,
        tree_column_stretch: bool,
        tree_row: int = 0,
        stretch_columns: set[str],
        include_tree_column: bool = True,
    ) -> qt.Treeview:
        """
        建立帶有自動欄寬調整與捲軸的 Review Treeview。

        Args:
            tree_container: Treeview 的父容器。
            tree_heading: Treeview 樹狀欄的標題文字。
            columns: Treeview 的欄位識別名稱元組（不包含樹狀欄）。
            column_specs: 包含每個欄位設定的列表，每個元素為 (column_name, text, width, minwidth, stretch, anchor)。
            tree_column_width: 樹狀欄的初始寬度（像素）。
            tree_column_minwidth: 樹狀欄的最小寬度（像素）。
            tree_column_stretch: 樹狀欄是否允許伸展以填滿剩餘空間。
            tree_row: 樹狀視圖在容器格線中的列號。
            stretch_columns: 允許伸展的欄位名稱集合。
            include_tree_column: 是否將樹狀欄包含在自動欄寬調整中。
        Returns:
            建立完成的 qt.Treeview 實例，已配置好自動欄寬調整與垂直捲軸。
        """
        s = MOD_MANAGEMENT_UI_SCALE
        tree = qt.Treeview(
            tree_container,
            columns=columns,
            show="tree headings",
            height=int(Spacing.MEDIUM * s),
        )
        tree.setRootIsDecorated(True)
        tree.setItemsExpandable(True)
        tree.heading("#0", text=tree_heading)
        tree.column(
            "#0",
            width=int(tree_column_width * s),
            minwidth=int(tree_column_minwidth * s),
            anchor="w",
            stretch=tree_column_stretch,
        )
        for column_name, text, width, minwidth, stretch, anchor in column_specs:
            tree.heading(column_name, text=text, anchor="w")
            tree.column(column_name, width=int(width * s), minwidth=int(minwidth * s), anchor=anchor, stretch=stretch)
        TreeUtils.bind_treeview_header_auto_fit(
            tree,
            include_tree_column=include_tree_column,
            heading_font=FontManager.get_font(size=int(FontSize.LARGE * s), weight="bold"),
            body_font=FontManager.get_font(size=int(FontSize.INPUT * s)),
            stretch_columns=stretch_columns,
        )
        scrollbar = qt.Scrollbar(tree_container, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.attach_matrix(row=tree_row, column=0, sticky="nsew")
        scrollbar.attach_matrix(row=tree_row, column=1, sticky="ns")
        tree_container.set_grid_row_stretch(tree_row, weight=1)
        tree_container.set_grid_column_stretch(0, weight=1)
        return tree

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
        s = MOD_MANAGEMENT_UI_SCALE
        if isinstance(review_entry, PendingInstallReviewEntry):
            title = "安裝項目 Review"
            heading = "待安裝模組詳細資訊"
            body = self._format_pending_install_review_text(review_entry)
            project_page_url = self._resolve_review_project_page_url(review_entry, mode="online")
        elif isinstance(review_entry, LocalUpdateReviewEntry):
            title = "本地模組更新 Review"
            heading = "本地模組更新詳細資訊"
            body = self._format_local_update_review_text(review_entry)
            project_page_url = self._resolve_review_project_page_url(review_entry, mode="local")
        else:
            raise TypeError(f"不支援的 review entry 類型: {type(review_entry).__name__}")
        dialog = qt.PlainWindow(title=title)
        dialog.resize(int(Sizes.DIALOG_MEDIUM_WIDTH * s), int(Sizes.DIALOG_MEDIUM_HEIGHT * s))
        dialog.setMinimumSize(
            int((Sizes.SERVER_PROPERTIES_DIALOG_WIDTH + Sizes.CONSOLE_PANEL_HEIGHT) * s),
            int((Sizes.SERVER_PROPERTIES_DIALOG_HEIGHT + Sizes.CONSOLE_PANEL_HEIGHT + Sizes.BUTTON_WIDTH_COMPACT) * s),
        )
        main_frame = self._create_dialog_main_frame(dialog)
        self._create_dialog_title(main_frame, heading)
        summary_box = qt.TextBox(
            main_frame,
            font=FontManager.get_font(size=int(FontSize.SMALL_PLUS * s)),
            wrap="word",
        )
        summary_box.attach(fill="both", expand=True, padx=int(Spacing.MEDIUM * s), pady=(0, int(Spacing.MEDIUM * s)))
        summary_box.insert("1.0", body)
        summary_box.setReadOnly(True)
        button_frame = qt.Frame(main_frame, fg_color="transparent")
        button_frame.attach(fill="x", padx=int(Spacing.MEDIUM * s), pady=(0, int(Spacing.SMALL * s)))
        project_button = qt.Button(
            button_frame,
            text="開啟專案頁面",
            font=FontManager.get_font(size=int(FontSize.LARGE * s)),
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            width=int(Sizes.BUTTON_WIDTH_COMPACT * s),
            command=lambda: self._open_project_page(project_page_url, dialog),
            state="normal" if project_page_url else "disabled",
        )
        project_button.attach(side="left")
        close_button = qt.Button(
            button_frame,
            text="關閉",
            font=FontManager.get_font(size=int(FontSize.LARGE * s)),
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            width=int(Sizes.BUTTON_WIDTH_COMPACT * s),
            command=dialog.destroy,
        )
        close_button.attach(side="right")
        return dialog


__all__ = ["InstallReviewDialogBuilder"]
