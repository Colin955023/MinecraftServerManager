"""安裝與更新 Review 對話框建構器"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, SubtitleLabel, TextEdit, TreeWidget

from src.ui import ModalMSFluentWindow
from src.utils import apply_table_header_style


class ReviewDialog(ModalMSFluentWindow):
    """
    安裝/更新 Review 的對話框視窗
    繼承自 ModalMSFluentWindow，提供標題、副標題、概覽文字、樹狀列表與總結文字框
    """

    def __init__(self, parent=None, dialog_title="", heading="", subtitle_text="", min_width=800, min_height=600):
        super().__init__(parent)
        self.setWindowTitle(dialog_title)
        self.titleLabel = SubtitleLabel(heading, self.widget)
        self.subtitleLabel = BodyLabel(subtitle_text, self.widget)
        self.subtitleLabel.setWordWrap(True)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.subtitleLabel)

        self.overview_label = BodyLabel("")
        self.overview_label.setWordWrap(True)
        self.viewLayout.addWidget(self.overview_label)

        self.tree_container = QWidget()
        self.tree_layout = QVBoxLayout(self.tree_container)
        self.tree_layout.setContentsMargins(0, 0, 0, 0)
        self.viewLayout.addWidget(self.tree_container, 1)

        self.summary_box = TextEdit()
        self.summary_box.setReadOnly(True)
        self.viewLayout.addWidget(self.summary_box)

        self.button_frame = QWidget(self.widget)
        self.button_layout = QHBoxLayout(self.button_frame)
        self.button_layout.setContentsMargins(0, 0, 0, 0)
        self.viewLayout.addWidget(self.button_frame)

        self.widget.setMinimumSize(min_width, min_height)
        self.setMinimumSize(min_width, min_height)
        self.resize(min_width, min_height)

        self.yesButton.hide()
        self.cancelButton.hide()


@dataclass(slots=True)
class ReviewDialogShell:
    """包含 Review 對話框中共用 UI 元件的容器"""

    dialog: ReviewDialog
    main_frame: QWidget
    subtitle: BodyLabel
    overview_label: BodyLabel
    tree_container: QWidget
    summary_box: TextEdit
    button_frame: QWidget


class InstallReviewDialogBuilder:
    """集中建立 Review 對話框的共用 UI 元件與單筆檢視"""

    def __init__(self, parent: Any):
        self._parent = parent

    def create_review_dialog_shell(
        self,
        *,
        dialog_title: str,
        heading: str,
        subtitle_text: str,
        summary_height: int,
        min_width: int,
        min_height: int,
    ) -> ReviewDialogShell:
        """
        建立 Review 對話框的基礎外殼，包含對話框實例及其內部關鍵元件

        Args:
            dialog_title: 對話框標題
            heading: 對話框標題
            subtitle_text: 副標題文字
            summary_height: 總結文字框的高度
            min_width: 對話框的最小寬度
            min_height: 對話框的最小高度

        Returns:
            包含對話框與其 UI 元件的容器物件
        """
        dialog = ReviewDialog(self._parent, dialog_title, heading, subtitle_text, min_width, min_height)
        dialog.summary_box.setFixedHeight(summary_height)

        return ReviewDialogShell(
            dialog=dialog,
            main_frame=dialog.viewLayout.parentWidget(),
            subtitle=dialog.subtitleLabel,
            overview_label=dialog.overview_label,
            tree_container=dialog.tree_container,
            summary_box=dialog.summary_box,
            button_frame=dialog.button_frame,
        )

    def create_review_tree(
        self,
        tree_container: QWidget,
        *,
        tree_heading: str,
        column_specs: list[tuple[str, str, int, int, bool, str]],
        tree_column_width: int,
        stretch_columns: set[str],
    ) -> TreeWidget:
        """
        建立並配置 Review 用的樹狀列表，包含欄位寬度與伸縮設定

        Args:
            tree_container: 樹狀列表的容器
            tree_heading: 樹狀列表的標題
            column_specs: 欄位規格的列表，每個元素包含欄位名稱、顯示文字、寬度、最小寬度、是否伸縮與對齊方式
            tree_column_width: 樹狀列表的主要欄位寬度
            stretch_columns: 需要伸縮的欄位名稱集合

        Returns:
            配置完成的樹狀列表元件
        """
        tree = TreeWidget()
        headers = [tree_heading] + [text for _, text, _, _, _, _ in column_specs]
        tree.setHeaderLabels(headers)
        apply_table_header_style(tree)
        tree.setRootIsDecorated(True)
        tree.setIndentation(20)

        header = tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        tree.setColumnWidth(0, tree_column_width)

        for i, (column_name, _text, width, _minwidth, stretch, _anchor) in enumerate(column_specs, start=1):
            tree.setColumnWidth(i, width)
            if stretch or column_name in stretch_columns:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)

        layout = tree_container.layout()
        if layout:
            layout.addWidget(tree)
        return tree


__all__ = ["InstallReviewDialogBuilder"]
