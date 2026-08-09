"""安裝與更新 Review 對話框建構器"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtWidgets import QFrame, QHBoxLayout, QHeaderView, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, PrimaryPushButton, PushButton, SubtitleLabel, TextEdit, TreeWidget

from ....models import LocalUpdateReviewEntry, PendingInstallReviewEntry
from ... import ModalMSFluentWindow
from .presenter_delegate_mixin import PresenterDelegateMixin


def _build_modrinth_project_page_url(identifier: str) -> str:
    clean_id = str(identifier or "").strip()
    if not clean_id:
        return ""
    if clean_id.startswith(("local:", "file:")):
        return ""
    return f"https://modrinth.com/project/{clean_id}"


def _resolve_project_page_url_from_candidates(
    url_candidates: tuple[str, ...], identifier_candidates: tuple[str, ...]
) -> str:
    for raw_url in url_candidates:
        clean_url = str(raw_url or "").strip()
        if clean_url:
            return clean_url
    for raw_identifier in identifier_candidates:
        project_page_url = _build_modrinth_project_page_url(str(raw_identifier or "").strip())
        if project_page_url:
            return project_page_url
    return ""


def _resolve_pending_install_review_project_page_url(review_entry: PendingInstallReviewEntry) -> str:
    pending = getattr(review_entry, "pending", None)
    if pending is None:
        return ""
    return _resolve_project_page_url_from_candidates(
        url_candidates=(getattr(pending, "homepage_url", ""), getattr(pending, "source_url", "")),
        identifier_candidates=(getattr(pending, "project_id", ""),),
    )


def _resolve_local_update_review_project_page_url(review_entry: LocalUpdateReviewEntry) -> str:
    candidate = getattr(review_entry, "candidate", None)
    if candidate is None:
        return ""
    local_mod = getattr(candidate, "local_mod", None)
    return _resolve_project_page_url_from_candidates(
        url_candidates=(),
        identifier_candidates=(
            getattr(local_mod, "platform_slug", ""),
            getattr(candidate, "project_id", ""),
            getattr(local_mod, "platform_id", ""),
        ),
    )


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

        self.tree_container = QFrame()
        self.tree_layout = QVBoxLayout(self.tree_container)
        self.tree_layout.setContentsMargins(0, 0, 0, 0)
        self.viewLayout.addWidget(self.tree_container, 1)

        self.summary_box = TextEdit()
        self.summary_box.setReadOnly(True)
        self.viewLayout.addWidget(self.summary_box)

        self.button_frame = QFrame(self.widget)
        self.button_layout = QHBoxLayout(self.button_frame)
        self.button_layout.setContentsMargins(0, 0, 0, 0)
        self.viewLayout.addWidget(self.button_frame)

        self.widget.setMinimumSize(min_width, min_height)

        self.yesButton.hide()
        self.cancelButton.hide()


@dataclass(slots=True)
class ReviewDialogShell:
    """包含 Review 對話框中共用 UI 元件的容器"""

    dialog: ReviewDialog
    main_frame: QWidget
    subtitle: BodyLabel
    overview_label: BodyLabel
    tree_container: QFrame
    summary_box: TextEdit
    button_frame: QFrame


class InstallReviewDialogBuilder(PresenterDelegateMixin):
    """集中建立 Review 對話框的共用 UI 元件與單筆檢視"""

    def __init__(self, frame: Any):
        super().__init__(frame)

    @staticmethod
    def create_review_summary_box(parent: Any, *, height: int) -> TextEdit:
        """
        建立一個唯讀的總結文字框

        Args:
            parent: 父元件
            height: 文字框的高度

        Returns:
            TextEdit: 建立好的唯讀文字框
        """
        summary_box = TextEdit(parent)
        summary_box.setReadOnly(True)
        summary_box.setFixedHeight(height)
        return summary_box

    def create_review_shared_ui(self) -> tuple[BodyLabel, QFrame]:
        """
        建立 Review 對話框中共用的 UI 元件（概覽標籤與樹狀容器）

        Returns:
            tuple[BodyLabel, QFrame]: 包含概覽標籤與樹狀容器的元組
        """
        overview_label = BodyLabel("")
        overview_label.setWordWrap(True)

        tree_container = QFrame()
        return overview_label, tree_container

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
            ReviewDialogShell: 包含對話框與其 UI 元件的容器物件
        """
        dialog = ReviewDialog(self.parent, dialog_title, heading, subtitle_text, min_width, min_height)
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
        tree_container: QFrame,
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
            TreeWidget: 配置完成的樹狀列表元件
        """
        tree = TreeWidget()
        headers = [tree_heading] + [text for _, text, _, _, _, _ in column_specs]
        tree.setHeaderLabels(headers)

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

    def build_review_dialog(self, review_entry: PendingInstallReviewEntry | LocalUpdateReviewEntry) -> Any:
        """
        根據提供的 Review 項目（安裝或更新）構建完整的 Review 對話框

        Args:
            review_entry: 待審核的安裝或更新項目

        Returns:
            Any: 構建完成的 ReviewDialog 實例
        """
        if isinstance(review_entry, PendingInstallReviewEntry):
            title = "安裝項目 Review"
            heading = "待安裝模組詳細資訊"
            body = self._format_pending_install_review_text(review_entry)
            project_page_url = _resolve_pending_install_review_project_page_url(review_entry)
        elif isinstance(review_entry, LocalUpdateReviewEntry):
            title = "本地模組更新 Review"
            heading = "本地模組更新詳細資訊"
            body = self._format_local_update_review_text(review_entry)
            project_page_url = _resolve_local_update_review_project_page_url(review_entry)
        else:
            raise TypeError(f"不支援的 review entry 類型: {type(review_entry).__name__}")

        dialog = ReviewDialog(self.parent, title, heading, "")

        dialog.summary_box.setPlainText(body)

        if project_page_url:
            project_button = PushButton("開啟專案頁面")
            project_button.clicked.connect(lambda: self._open_project_page(project_page_url, dialog))
            dialog.button_layout.addWidget(project_button)

        close_button = PrimaryPushButton("關閉")
        close_button.clicked.connect(dialog.accept)
        dialog.button_layout.addWidget(close_button)
        dialog.button_layout.addStretch(1)

        return dialog


__all__ = ["InstallReviewDialogBuilder"]
