"""線上模組瀏覽 Presenter。"""

from __future__ import annotations

from typing import Any

from ...utils import Colors, CustomDropdown, FontManager, FontSize, Sizes, Spacing, TreeUtils
from ...utils.ui_support import qt_widgets as qt
from .constants import MOD_TOOL_BUTTON_STYLE
from .presenter_delegate_mixin import PresenterDelegateMixin


class OnlineBrowsePresenter(PresenterDelegateMixin):
    """封裝線上模組搜尋列、結果列表與瀏覽事件入口。"""

    def __init__(self, frame: Any):
        super().__init__(frame)

    def render_online_mods(self) -> None:
        """重新渲染目前線上搜尋結果。"""
        self.refresh_browse_list()

    def handle_search(self, _event=None) -> None:
        """
        觸發線上模組搜尋。

        Args:
            _event: 來自搜尋列的事件，預設為 None 以供程式內呼叫使用。
        """
        self.search_online_mods(_event)

    def create_browse_search(self) -> None:
        """建立線上搜尋區域。"""
        if not self.browse_tab:
            return
        search_frame = qt.Frame(self.browse_tab)
        search_frame.attach(fill="x", padx=Spacing.MEDIUM, pady=Spacing.MEDIUM)
        self.search_var = qt.TextState()
        self.browse_sort_var = qt.TextState(value="相關性")
        self.browse_sort_options = {
            "相關性": "relevance",
            "下載量": "downloads",
            "最新發布": "newest",
            "最近更新": "updated",
            "名稱": "name",
        }
        self.online_search_filter = qt.SearchFilter()
        search_entry = qt.SearchEntry(
            search_frame,
            textvariable=self.search_var,
            search_command=self.search_online_mods,
            filter_logic=self.online_search_filter,
            placeholder_text="請輸入關鍵字後搜尋，例如 sodium / lithium / worldedit",
            font=FontManager.get_font(size=FontSize.MEDIUM),
            width=Sizes.DIALOG_PROGRESS_WIDTH,
            height=Sizes.INPUT_HEIGHT,
        )
        search_entry.attach(side="left", padx=(Spacing.MEDIUM, Spacing.SMALL_PLUS), pady=Spacing.MEDIUM)
        sort_dropdown = CustomDropdown(
            search_frame,
            variable=self.browse_sort_var,
            values=list(self.browse_sort_options.keys()),
            command=self.on_online_browse_filters_changed,
            width=Sizes.DROPDOWN_FILTER_WIDTH,
            height=Sizes.INPUT_HEIGHT,
        )
        sort_dropdown.attach(side="left", padx=(0, Spacing.SMALL_PLUS), pady=Spacing.MEDIUM)
        search_button = qt.Button(
            search_frame,
            text="🔍 搜尋 Modrinth",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.search_online_mods,
            **MOD_TOOL_BUTTON_STYLE,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        search_button.attach(side="left", padx=(0, Spacing.SMALL_PLUS), pady=Spacing.MEDIUM)
        install_button = qt.Button(
            search_frame,
            text="➕ 加入安裝清單",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.install_online_mod,
            **MOD_TOOL_BUTTON_STYLE,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        install_button.attach(side="left", pady=Spacing.MEDIUM)
        self.online_queue_button = qt.Button(
            search_frame,
            text="🧺 安裝清單 (0)",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.show_online_install_queue,
            **MOD_TOOL_BUTTON_STYLE,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        self.online_queue_button.attach(side="left", padx=(Spacing.SMALL_PLUS, 0), pady=Spacing.MEDIUM)
        self.browse_filter_label = qt.Label(
            self.browse_tab,
            text="",
            font=FontManager.get_font(size=FontSize.SMALL_PLUS),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=Sizes.ONLINE_HINT_WRAP_LENGTH,
        )
        self.browse_filter_label.attach(fill="x", padx=Spacing.LARGE, pady=(0, Spacing.XS))
        self.browse_results_label = qt.Label(
            self.browse_tab,
            text="",
            font=FontManager.get_font(size=FontSize.SMALL_PLUS),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=Sizes.ONLINE_HINT_WRAP_LENGTH,
        )
        self.browse_results_label.attach(fill="x", padx=Spacing.LARGE, pady=(0, Spacing.TINY))
        self._refresh_online_filter_hint()
        self._refresh_online_results_summary()

    def create_browse_mod_list(self) -> None:
        """建立線上模組列表。"""
        if not self.browse_tab:
            return
        list_frame = qt.Frame(self.browse_tab)
        list_frame.attach(fill="both", expand=True, padx=Spacing.SMALL_PLUS, pady=(0, Spacing.SMALL_PLUS))
        tree_container = qt.Frame(list_frame)
        tree_container.attach(fill="both", expand=True, padx=Spacing.SMALL_PLUS, pady=Spacing.SMALL_PLUS)
        columns = ("name", "author", "downloads", "description", "platform", "environments")
        self.browse_tree = qt.Treeview(
            tree_container,
            columns=columns,
            show="headings",
            height=Sizes.TREEVIEW_VISIBLE_ROWS,
        )
        column_config = {
            "name": ("模組名稱", 110),
            "author": ("作者", 60),
            "downloads": ("下載數", 50),
            "description": ("描述", 230),
            "platform": ("平台", 45),
            "environments": ("支援環境", 75),
        }
        for col, (text, width) in column_config.items():
            self.browse_tree.heading(col, text=text, anchor="w")
            is_stretch = col == "description"
            self.browse_tree.column(
                col, width=width, minwidth=width if is_stretch else 30, anchor="w", stretch=is_stretch
            )
        v_scrollbar = qt.Scrollbar(tree_container, orient="vertical", command=self.browse_tree.yview)
        h_scrollbar = qt.Scrollbar(tree_container, orient="horizontal", command=self.browse_tree.xview)
        self.browse_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        self.browse_tree.attach_matrix(row=0, column=0, sticky="nsew")
        v_scrollbar.attach_matrix(row=0, column=1, sticky="ns")
        h_scrollbar.attach_matrix(row=1, column=0, sticky="ew")
        tree_container.set_grid_row_stretch(0, weight=1)
        tree_container.set_grid_column_stretch(0, weight=1)
        TreeUtils.bind_treeview_header_auto_fit(
            self.browse_tree,
            on_row_double_click=self.install_online_mod,
            heading_font=FontManager.get_font(size=FontSize.HEADING_SMALL, weight="bold"),
            body_font=FontManager.get_font(size=FontSize.INPUT),
            stretch_columns={"description"},
        )
        self.browse_tree.connect_event("mouse_right_press", self.show_browse_context_menu)


__all__ = ["OnlineBrowsePresenter"]
