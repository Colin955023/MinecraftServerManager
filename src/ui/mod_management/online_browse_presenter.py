"""線上模組瀏覽 Presenter。"""

from __future__ import annotations

from typing import Any

from ...utils import Colors, CustomDropdown, FontManager, FontSize, QtCore, QtGui, Sizes, Spacing, TreeUtils
from ...utils.ui_support import qt_widgets as qt
from .constants import MOD_MANAGEMENT_UI_SCALE
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
        s = MOD_MANAGEMENT_UI_SCALE
        if not self.browse_tab:
            return
        search_frame = qt.Frame(self.browse_tab)
        search_frame.attach(fill="x", padx=int(Spacing.MEDIUM * s), pady=int(Spacing.MEDIUM * s))
        self.search_var = None if not hasattr(qt, "TextState") else qt.TextState()
        self.browse_sort_var = "相關性" if not hasattr(qt, "TextState") else qt.TextState(value="相關性")
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
            font=FontManager.get_font(size=int(FontSize.MEDIUM * s)),
            width=int(Sizes.DIALOG_PROGRESS_WIDTH * s),
            height=int(Sizes.INPUT_HEIGHT * s),
        )
        search_entry.attach(
            side="left", padx=(int(Spacing.MEDIUM * s), int(Spacing.SMALL_PLUS * s)), pady=int(Spacing.MEDIUM * s)
        )
        sort_dropdown = CustomDropdown(
            search_frame,
            variable=self.browse_sort_var,
            values=list(self.browse_sort_options.keys()),
            command=self.on_online_browse_filters_changed,
            width=int(90 * s),
            height=int(Sizes.DROPDOWN_HEIGHT * s),
            font_size=max(8, int(FontSize.MEDIUM * s)),
        )
        sort_dropdown.attach(side="left", padx=(0, int(Spacing.SMALL_PLUS * s)), pady=int(Spacing.MEDIUM * s))
        search_button = qt.Button(
            search_frame,
            text="🔍 搜尋 Modrinth",
            font=FontManager.get_font(size=int(FontSize.LARGE * s), weight="bold"),
            command=self.search_online_mods,
            width=Sizes.DETECT_BUTTON_WIDTH,
            height=int(Sizes.BUTTON_HEIGHT * s),
        )
        search_button.configure(
            fg_color=Colors.BUTTON_LIGHT,
            hover_color=Colors.BUTTON_LIGHT_HOVER,
            text_color=Colors.TEXT_ON_LIGHT,
            border_color=Colors.BORDER_LIGHT,
        )
        search_button.attach(side="left", padx=(0, int(Spacing.SMALL_PLUS * s)), pady=int(Spacing.MEDIUM * s))
        install_button = qt.Button(
            search_frame,
            text="➕ 加入安裝清單",
            font=FontManager.get_font(size=int(FontSize.LARGE * s), weight="bold"),
            command=self.install_online_mod,
            width=Sizes.DETECT_BUTTON_WIDTH,
            height=int(Sizes.BUTTON_HEIGHT * s),
        )
        install_button.configure(
            fg_color=Colors.BUTTON_LIGHT,
            hover_color=Colors.BUTTON_LIGHT_HOVER,
            text_color=Colors.TEXT_ON_LIGHT,
            border_color=Colors.BORDER_LIGHT,
        )
        install_button.attach(side="left", pady=int(Spacing.MEDIUM * s))
        self.online_queue_button = qt.Button(
            search_frame,
            text="🧺 安裝清單 (0)",
            font=FontManager.get_font(size=int(FontSize.LARGE * s), weight="bold"),
            command=self.show_online_install_queue,
            width=Sizes.DETECT_BUTTON_WIDTH,
            height=int(Sizes.BUTTON_HEIGHT * s),
        )
        self.online_queue_button.configure(
            fg_color=Colors.BUTTON_LIGHT,
            hover_color=Colors.BUTTON_LIGHT_HOVER,
            text_color=Colors.TEXT_ON_LIGHT,
            border_color=Colors.BORDER_LIGHT,
        )
        self.online_queue_button.attach(
            side="left", padx=(int(Spacing.SMALL_PLUS * s), 0), pady=int(Spacing.MEDIUM * s)
        )
        self.browse_filter_label = qt.Label(
            self.browse_tab,
            text="",
            font=FontManager.get_font(size=int(FontSize.SMALL_PLUS * s)),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=int(Sizes.ONLINE_HINT_WRAP_LENGTH * s),
        )
        self.browse_filter_label.attach(fill="x", padx=int(Spacing.LARGE * s), pady=(0, int(Spacing.XS * s)))
        self.browse_results_label = qt.Label(
            self.browse_tab,
            text="",
            font=FontManager.get_font(size=int(FontSize.SMALL_PLUS * s)),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=int(Sizes.ONLINE_HINT_WRAP_LENGTH * s),
        )
        self.browse_results_label.attach(fill="x", padx=int(Spacing.LARGE * s), pady=(0, int(Spacing.TINY * s)))
        self._refresh_online_filter_hint()
        self._refresh_online_results_summary()

    def create_browse_mod_list(self) -> None:
        """建立線上模組列表。"""
        s = MOD_MANAGEMENT_UI_SCALE
        if not self.browse_tab:
            return
        list_frame = qt.Frame(self.browse_tab)
        list_frame.attach(
            fill="both", expand=True, padx=int(Spacing.SMALL_PLUS * s), pady=(0, int(Spacing.SMALL_PLUS * s))
        )
        tree_container = qt.Frame(list_frame)
        tree_container.attach(
            fill="both", expand=True, padx=int(Spacing.SMALL_PLUS * s), pady=int(Spacing.SMALL_PLUS * s)
        )
        columns = ("name", "author", "downloads", "platform", "environments", "description")
        self.browse_tree = qt.Treeview(
            tree_container,
            columns=columns,
            show="headings",
            height=Sizes.TREEVIEW_VISIBLE_ROWS,
        )
        column_config = {
            "name": ("模組名稱", 110),
            "author": ("作者", 60),
            "downloads": ("下載數", 55),
            "platform": ("平台", 50),
            "environments": ("支援環境", 80),
            "description": ("描述", 230),
        }
        header_font = FontManager.get_font(size=int(FontSize.NORMAL * s), weight="bold")
        header_fm = QtGui.QFontMetrics(header_font) if header_font else None
        for col, (text, width) in column_config.items():
            self.browse_tree.heading(col, text=text, anchor="w")
            is_stretch = col == "description"
            min_width = (
                width if is_stretch else max(30, (header_fm.horizontalAdvance(text) + 20) if header_fm else width)
            )
            self.browse_tree.column(col, width=width, minwidth=min_width, anchor="w", stretch=is_stretch)
        # 使用內建捲軸，僅在內容超出時顯示
        self.browse_tree.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.browse_tree.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.browse_tree.attach(fill="both", expand=True)
        TreeUtils.bind_treeview_header_auto_fit(
            self.browse_tree,
            on_row_double_click=self.install_online_mod,
            heading_font=FontManager.get_font(size=FontSize.HEADING_SMALL, weight="bold"),
            body_font=FontManager.get_font(size=FontSize.INPUT),
            stretch_columns={"description"},
        )
        self.browse_tree.connect_event("mouse_right_press", self.show_browse_context_menu)


__all__ = ["OnlineBrowsePresenter"]
