"""線上模組瀏覽 Presenter"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QVBoxLayout
from qfluentwidgets import BodyLabel, PushButton, SearchLineEdit, TreeWidget

from ....utils import (
    Colors,
    FontManager,
    FontSize,
    ScrollableComboBox,
    SearchFilter,
    Sizes,
    Spacing,
    TextState,
    resolve_color,
)
from .presenter_delegate_mixin import PresenterDelegateMixin


class OnlineBrowsePresenter(PresenterDelegateMixin):
    """封裝線上模組搜尋列、結果列表與瀏覽事件入口"""

    def __init__(self, frame: Any):
        super().__init__(frame)

    def render_online_mods(self) -> None:
        """重新渲染目前線上搜尋結果"""
        self.refresh_browse_list()

    def handle_search(self, event=None) -> None:
        """
        觸發線上模組搜尋

        Args:
            event: 來自搜尋列的事件，預設為 None 以供程式內呼叫使用
        """
        if hasattr(self.frame, "search_online_mods"):
            self.frame.search_online_mods(event)

    def create_browse_search(self) -> None:
        """建立線上搜尋區域"""
        if not self.browse_tab:
            return

        search_frame = QFrame(self.browse_tab)
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(Spacing.MEDIUM, Spacing.MEDIUM, Spacing.MEDIUM, Spacing.MEDIUM)
        search_layout.setSpacing(Spacing.SMALL_PLUS)

        if self.browse_tab.layout() is not None:
            self.browse_tab.layout().addWidget(search_frame)

        self.frame.search_var = TextState()
        self.frame.browse_sort_var = TextState(value="相關性")
        self.frame.browse_sort_options = {
            "相關性": "relevance",
            "下載量": "downloads",
            "最新發布": "newest",
            "最近更新": "updated",
            "名稱": "name",
        }
        self.frame.online_search_filter = SearchFilter()

        search_entry = SearchLineEdit(search_frame)
        search_entry.setPlaceholderText("請輸入關鍵字後搜尋，例如 sodium / lithium / worldedit")
        search_entry.setFont(FontManager.get_font(size=FontSize.MEDIUM))
        search_entry.setMinimumSize(Sizes.DIALOG_PROGRESS_WIDTH, Sizes.INPUT_HEIGHT)
        search_entry.textChanged.connect(self.frame.search_var.set)
        search_entry.returnPressed.connect(self.handle_search)
        search_layout.addWidget(search_entry)

        sort_dropdown = ScrollableComboBox(search_frame)
        sort_dropdown.addItems(list(self.frame.browse_sort_options.keys()))
        sort_dropdown.setCurrentText(self.frame.browse_sort_var.get())
        sort_dropdown.currentTextChanged.connect(self.frame.browse_sort_var.set)
        sort_dropdown.currentTextChanged.connect(self.on_online_browse_filters_changed)
        sort_dropdown.setMinimumSize(Sizes.DROPDOWN_FILTER_WIDTH, Sizes.INPUT_HEIGHT)
        search_layout.addWidget(sort_dropdown)

        search_button = PushButton("🔍 搜尋 Modrinth", search_frame)
        search_button.setFont(FontManager.get_font(size=FontSize.LARGE, weight="bold"))
        search_button.clicked.connect(self.handle_search)
        search_button.setMinimumSize(Sizes.BUTTON_WIDTH_COMPACT, Sizes.BUTTON_HEIGHT)
        search_layout.addWidget(search_button)

        install_button = PushButton("➕ 加入安裝清單", search_frame)
        install_button.setFont(FontManager.get_font(size=FontSize.LARGE, weight="bold"))
        install_button.clicked.connect(self.install_online_mod)
        install_button.setMinimumSize(Sizes.BUTTON_WIDTH_COMPACT, Sizes.BUTTON_HEIGHT)
        search_layout.addWidget(install_button)

        self.online_queue_button = PushButton("🧺 安裝清單 (0)", search_frame)
        self.online_queue_button.setFont(FontManager.get_font(size=FontSize.LARGE, weight="bold"))
        self.online_queue_button.clicked.connect(self.show_online_install_queue)
        self.online_queue_button.setMinimumSize(Sizes.BUTTON_WIDTH_COMPACT, Sizes.BUTTON_HEIGHT)
        search_layout.addWidget(self.online_queue_button)

        self.browse_filter_label = BodyLabel("", self.browse_tab)
        font_small = FontManager.get_font(size=FontSize.SMALL_PLUS)
        self.browse_filter_label.setFont(font_small)
        self.browse_filter_label.setStyleSheet(f"color: {resolve_color(Colors.TEXT_SECONDARY)};")
        self.browse_filter_label.setWordWrap(True)
        if self.browse_tab.layout() is not None:
            self.browse_tab.layout().addWidget(self.browse_filter_label)

        self.browse_results_label = BodyLabel("", self.browse_tab)
        self.browse_results_label.setFont(font_small)
        self.browse_results_label.setStyleSheet(f"color: {resolve_color(Colors.TEXT_SECONDARY)};")
        self.browse_results_label.setWordWrap(True)
        if self.browse_tab.layout() is not None:
            self.browse_tab.layout().addWidget(self.browse_results_label)

        self._refresh_online_filter_hint()
        self._refresh_online_results_summary()

    def create_browse_mod_list(self) -> None:
        """建立線上模組列表"""
        if not self.browse_tab:
            return

        list_frame = QFrame(self.browse_tab)
        if self.browse_tab.layout() is not None:
            self.browse_tab.layout().addWidget(list_frame, stretch=1)

        list_layout = QVBoxLayout(list_frame)
        list_layout.setContentsMargins(Spacing.SMALL_PLUS, 0, Spacing.SMALL_PLUS, Spacing.SMALL_PLUS)

        tree_container = QFrame(list_frame)
        list_layout.addWidget(tree_container, stretch=1)

        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(Spacing.SMALL_PLUS, Spacing.SMALL_PLUS, Spacing.SMALL_PLUS, Spacing.SMALL_PLUS)

        columns = ("name", "author", "downloads", "description", "platform", "environments")
        self.browse_tree = TreeWidget(tree_container)
        self.browse_tree.setColumnCount(len(columns))

        column_config = {
            "name": ("模組名稱", 110),
            "author": ("作者", 60),
            "downloads": ("下載數", 50),
            "description": ("描述", 230),
            "platform": ("平台", 45),
            "environments": ("支援環境", 75),
        }

        self.browse_tree.setHeaderLabels([v[0] for v in column_config.values()])
        self.browse_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.browse_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        for idx, col in enumerate(columns):
            self.browse_tree.header().resizeSection(idx, column_config[col][1])

        self.browse_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.browse_tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        tree_layout.addWidget(self.browse_tree, stretch=1)

        self.browse_tree.doubleClicked.connect(self.install_online_mod)
        self.browse_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.browse_tree.customContextMenuRequested.connect(self.show_browse_context_menu)

    def install_online_mod(self, event=None) -> None:
        """
        安裝選中的線上模組

        Args:
            event: 事件物件，預設為 None 以供程式內呼叫使用
        """
        if hasattr(self.frame, "install_online_mod"):
            self.frame.install_online_mod(event)

    def show_online_install_queue(self, event=None) -> None:
        """
        顯示線上模組安裝佇列

        Args:
            event: 事件物件，預設為 None 以供程式內呼叫使用
        """
        if hasattr(self.frame, "show_online_install_queue"):
            self.frame.show_online_install_queue(event)

    def on_online_browse_filters_changed(self, value) -> None:
        """
        線上瀏覽篩選條件變更時觸發重新查詢

        Args:
            value: 新的篩選條件值
        """
        if hasattr(self.frame, "on_online_browse_filters_changed"):
            self.frame.on_online_browse_filters_changed(value)

    def show_browse_context_menu(self, event) -> None:
        """
        顯示線上瀏覽的右鍵選單

        Args:
            event: 事件物件，預設為 None 以供程式內呼叫使用
        """
        if hasattr(self.frame, "show_browse_context_menu"):
            self.frame.show_browse_context_menu(event)


__all__ = ["OnlineBrowsePresenter"]
