"""線上模組瀏覽 Presenter"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, PushButton, SearchLineEdit, TreeWidget, isDarkTheme

from src.utils import (
    Colors,
    FontManager,
    FontSize,
    ScrollableComboBox,
    Sizes,
    Spacing,
    TextState,
    apply_table_header_style,
    resolve_color,
)

if TYPE_CHECKING:
    from .frame import ModManagementFrame


@dataclass(slots=True)
class SearchFilter:
    """Presenter 共用的搜尋文字正規化與比對政策"""

    case_sensitive: bool = False
    normalize_whitespace: bool = True
    require_all_terms: bool = True

    def normalize(self, value: Any) -> str:
        """正規化搜尋文字

        Args:
            value: 待正規化的任意值

        Returns:
            套用空白與大小寫規則後的搜尋文字
        """
        text = str(value or "").strip()
        if self.normalize_whitespace:
            text = re.sub(r"\s+", " ", text)
        return text if self.case_sensitive else text.lower()

    def matches(self, candidate: Any, query: Any) -> bool:
        """判斷候選內容是否符合查詢

        Args:
            candidate: 被比對的字串、序列或 mapping
            query: 使用者輸入的查詢值

        Returns:
            候選內容符合目前比對政策時為 True
        """
        normalized_query = self.normalize(query)
        if not normalized_query:
            return True
        candidate_text = " ".join(self.normalize(value) for value in self._candidate_values(candidate))
        if not candidate_text:
            return False
        if not self.require_all_terms:
            return normalized_query in candidate_text
        return all(term in candidate_text for term in normalized_query.split())

    @staticmethod
    def _candidate_values(candidate: Any) -> list[Any]:
        if isinstance(candidate, Mapping):
            return list(candidate.values())
        if isinstance(candidate, (list, tuple, set, frozenset)):
            return list(candidate)
        return [candidate]


class OnlineBrowsePresenter:
    """封裝線上模組搜尋列、結果列表與瀏覽事件入口"""

    def __init__(self, controller: ModManagementFrame):
        self.controller = controller
        self.search_var = TextState()
        self.browse_sort_var = TextState(value="相關性")
        self.browse_sort_options: dict[str, str] = {}
        self.online_search_filter = SearchFilter()
        self.browse_search_entry: SearchLineEdit
        self.online_queue_button: PushButton
        self.browse_filter_label: BodyLabel
        self.browse_results_label: BodyLabel
        self.browse_tree: TreeWidget

    def create_browse_search(self) -> None:
        """建立線上搜尋區域"""
        browse_tab = self.controller.browse_tab
        if browse_tab is None:
            return

        search_frame = QWidget(browse_tab)
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(Spacing.MEDIUM, Spacing.MEDIUM, Spacing.MEDIUM, Spacing.MEDIUM)
        search_layout.setSpacing(Spacing.SMALL_PLUS)

        tab_layout = browse_tab.layout()
        if tab_layout is not None:
            tab_layout.addWidget(search_frame)

        self.search_var = TextState()
        self.browse_sort_var = TextState(value="相關性")
        self.browse_sort_options = {
            "相關性": "relevance",
            "下載量": "downloads",
            "最新發布": "newest",
            "最近更新": "updated",
            "名稱": "name",
        }
        self.online_search_filter = SearchFilter()

        search_entry = SearchLineEdit(search_frame)
        search_entry.setPlaceholderText("請輸入關鍵字後搜尋，例如 sodium / lithium / worldedit")
        search_entry.setFont(FontManager.get_font(size=FontSize.MEDIUM))
        search_entry.setMinimumSize(Sizes.DIALOG_PROGRESS_WIDTH, Sizes.INPUT_HEIGHT)
        search_entry.textChanged.connect(self.search_var.set)
        self.browse_search_entry = search_entry
        search_entry.returnPressed.connect(self.controller.queue_ops.search_online_mods)
        search_layout.addWidget(search_entry)

        sort_dropdown = ScrollableComboBox(search_frame)
        sort_dropdown.addItems(list(self.browse_sort_options.keys()))
        sort_dropdown.setCurrentText(self.browse_sort_var.get())
        sort_dropdown.currentTextChanged.connect(self.browse_sort_var.set)
        sort_dropdown.currentTextChanged.connect(self.controller.queue_ops.on_online_browse_filters_changed)
        sort_dropdown.setMinimumSize(Sizes.DROPDOWN_FILTER_WIDTH, Sizes.INPUT_HEIGHT)
        search_layout.addWidget(sort_dropdown)

        search_button = PushButton("🔍 搜尋 Modrinth", search_frame)
        search_button.setFont(FontManager.get_font(size=FontSize.LARGE, weight="bold"))
        search_button.clicked.connect(self.controller.queue_ops.search_online_mods)
        search_button.setMinimumSize(Sizes.BUTTON_WIDTH_COMPACT, Sizes.BUTTON_HEIGHT)
        search_layout.addWidget(search_button)

        install_button = PushButton("➕ 加入安裝清單", search_frame)
        install_button.setFont(FontManager.get_font(size=FontSize.LARGE, weight="bold"))
        install_button.clicked.connect(self.controller.queue_ops.install_online_mod)
        install_button.setMinimumSize(Sizes.BUTTON_WIDTH_COMPACT, Sizes.BUTTON_HEIGHT)
        search_layout.addWidget(install_button)

        self.online_queue_button = PushButton("🧺 安裝清單 (0)", search_frame)
        self.online_queue_button.setFont(FontManager.get_font(size=FontSize.LARGE, weight="bold"))
        self.online_queue_button.clicked.connect(self.controller.review_ops.show_online_install_queue)
        self.online_queue_button.setMinimumSize(Sizes.BUTTON_WIDTH_COMPACT, Sizes.BUTTON_HEIGHT)
        search_layout.addWidget(self.online_queue_button)

        self.browse_filter_label = BodyLabel("", browse_tab)
        font_small = FontManager.get_font(size=FontSize.SMALL_PLUS)
        self.browse_filter_label.setFont(font_small)
        self.browse_filter_label.setStyleSheet(f"color: {resolve_color(Colors.TEXT_SECONDARY)};")
        self.browse_filter_label.setWordWrap(True)
        if tab_layout is not None:
            tab_layout.addWidget(self.browse_filter_label)

        self.browse_results_label = BodyLabel("", browse_tab)
        self.browse_results_label.setFont(font_small)
        self.browse_results_label.setStyleSheet(f"color: {resolve_color(Colors.TEXT_SECONDARY)};")
        self.browse_results_label.setWordWrap(True)
        if tab_layout is not None:
            tab_layout.addWidget(self.browse_results_label)

        self.controller.queue_ops._refresh_online_filter_hint()
        self.controller.queue_ops._refresh_online_results_summary()

    def create_browse_mod_list(self) -> None:
        """建立線上模組列表"""
        browse_tab = self.controller.browse_tab
        if browse_tab is None:
            return

        list_frame = QWidget(browse_tab)
        tab_layout = browse_tab.layout()
        if tab_layout is not None:
            tab_layout.addWidget(list_frame)

        list_layout = QVBoxLayout(list_frame)
        list_layout.setContentsMargins(Spacing.SMALL_PLUS, 0, Spacing.SMALL_PLUS, Spacing.SMALL_PLUS)

        tree_container = QWidget(list_frame)
        list_layout.addWidget(tree_container, stretch=1)

        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(Spacing.SMALL_PLUS, Spacing.SMALL_PLUS, Spacing.SMALL_PLUS, Spacing.SMALL_PLUS)

        columns = ("name", "author", "downloads", "platform", "environments", "description")
        self.browse_tree = TreeWidget(tree_container)
        tree = self.browse_tree
        tree.setColumnCount(len(columns))

        column_config = {
            "name": ("模組名稱", 110),
            "author": ("作者", 60),
            "downloads": ("下載數", 50),
            "platform": ("平台", 45),
            "environments": ("支援環境", 75),
            "description": ("描述", 230),
        }

        tree.setHeaderLabels([v[0] for v in column_config.values()])
        apply_table_header_style(tree)
        tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        for idx, col in enumerate(columns):
            tree.header().resizeSection(idx, column_config[col][1])

        tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        tree.header().setSectionResizeMode(len(columns) - 1, QHeaderView.ResizeMode.Stretch)
        tree.header().setStretchLastSection(True)

        tree_layout.addWidget(tree, stretch=1)

        tree.doubleClicked.connect(lambda _index: self.controller.queue_ops.install_online_mod())
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(self.controller.queue_ops.show_browse_context_menu)

    def apply_browse_tree_theme(self) -> None:
        """套用主題樣式至線上瀏覽清單"""
        tree = self.browse_tree
        if not tree:
            return
        is_dark = isDarkTheme()
        bg_color = resolve_color((Colors.BG_CARD_LIGHT, Colors.BG_CARD_DARK), dark=is_dark)
        border_color = resolve_color(Colors.BORDER, dark=is_dark)
        primary_color = resolve_color(Colors.TEXT_PRIMARY, dark=is_dark)
        tree.setStyleSheet(
            f"TreeWidget {{ background-color: {bg_color}; color: {primary_color}; border: 1px solid {border_color}; border-radius: 6px; }}"
        )


__all__ = ["OnlineBrowsePresenter"]
