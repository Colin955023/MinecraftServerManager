"""線上模組瀏覽 Presenter。"""

from __future__ import annotations

import tkinter
import tkinter.ttk as ttk
from typing import Any

import customtkinter as ctk

from ...utils import (
    Colors,
    FontSize,
    Sizes,
    Spacing,
)
from ..custom_dropdown import CustomDropdown
from ..font_manager import FontManager
from ..tree_utils import TreeUtils
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
        search_frame = ctk.CTkFrame(self.browse_tab)
        search_frame.pack(fill="x", padx=Spacing.MEDIUM, pady=Spacing.MEDIUM)
        self.search_var = tkinter.StringVar()
        self.browse_sort_var = tkinter.StringVar(value="相關性")
        self.browse_sort_options = {
            "相關性": "relevance",
            "下載量": "downloads",
            "最新發布": "newest",
            "最近更新": "updated",
            "名稱": "name",
        }
        search_entry = ctk.CTkEntry(
            search_frame,
            textvariable=self.search_var,
            placeholder_text="請輸入關鍵字後搜尋，例如 sodium / lithium / worldedit",
            font=FontManager.get_font(size=FontSize.MEDIUM),
            width=FontManager.get_dpi_scaled_size(320),
            height=Sizes.INPUT_HEIGHT,
        )
        search_entry.pack(side="left", padx=(Spacing.MEDIUM, Spacing.SMALL_PLUS), pady=Spacing.MEDIUM)
        search_entry.bind("<Return>", self.search_online_mods)
        sort_dropdown = CustomDropdown(
            search_frame,
            variable=self.browse_sort_var,
            values=list(self.browse_sort_options.keys()),
            command=self.on_online_browse_filters_changed,
            width=Sizes.DROPDOWN_FILTER_WIDTH,
            height=Sizes.INPUT_HEIGHT,
        )
        sort_dropdown.pack(side="left", padx=(0, Spacing.SMALL_PLUS), pady=Spacing.MEDIUM)
        search_button = ctk.CTkButton(
            search_frame,
            text="🔍 搜尋 Modrinth",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.search_online_mods,
            fg_color=Colors.BUTTON_PRIMARY,
            hover_color=Colors.BUTTON_PRIMARY_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        search_button.pack(side="left", padx=(0, Spacing.SMALL_PLUS), pady=Spacing.MEDIUM)
        install_button = ctk.CTkButton(
            search_frame,
            text="➕ 加入安裝清單",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.install_online_mod,
            fg_color=Colors.BUTTON_SUCCESS,
            hover_color=Colors.BUTTON_SUCCESS_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        install_button.pack(side="left", pady=Spacing.MEDIUM)
        self.online_queue_button = ctk.CTkButton(
            search_frame,
            text="🧺 安裝清單 (0)",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.show_online_install_queue,
            fg_color=Colors.BUTTON_WARNING,
            hover_color=Colors.BUTTON_WARNING_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        self.online_queue_button.pack(side="left", padx=(Spacing.SMALL_PLUS, 0), pady=Spacing.MEDIUM)
        self.browse_filter_label = ctk.CTkLabel(
            self.browse_tab,
            text="",
            font=FontManager.get_font(size=FontSize.SMALL_PLUS),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=FontManager.get_dpi_scaled_size(980),
        )
        self.browse_filter_label.pack(fill="x", padx=Spacing.LARGE, pady=(0, Spacing.XS))
        self.browse_results_label = ctk.CTkLabel(
            self.browse_tab,
            text="",
            font=FontManager.get_font(size=FontSize.SMALL_PLUS),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=FontManager.get_dpi_scaled_size(980),
        )
        self.browse_results_label.pack(fill="x", padx=Spacing.LARGE, pady=(0, Spacing.TINY))
        self._refresh_online_filter_hint()
        self._refresh_online_results_summary()

    def create_browse_mod_list(self) -> None:
        """建立線上模組列表。"""
        if not self.browse_tab:
            return
        list_frame = ctk.CTkFrame(self.browse_tab)
        list_frame.pack(fill="both", expand=True, padx=Spacing.SMALL_PLUS, pady=(0, Spacing.SMALL_PLUS))
        tree_container = ctk.CTkFrame(list_frame)
        tree_container.pack(fill="both", expand=True, padx=Spacing.SMALL_PLUS, pady=Spacing.SMALL_PLUS)
        style = ttk.Style()
        style.configure(
            "BrowseModList.Treeview",
            font=FontManager.get_font(size=FontSize.INPUT),
            rowheight=int(26 * FontManager.get_scale_factor()),
        )
        style.configure(
            "BrowseModList.Treeview.Heading", font=FontManager.get_font(size=FontSize.HEADING_SMALL, weight="bold")
        )
        columns = ("name", "author", "downloads", "description", "platform", "environments")
        self.browse_tree = ttk.Treeview(
            tree_container,
            columns=columns,
            show="headings",
            height=Sizes.TREEVIEW_VISIBLE_ROWS,
            style="BrowseModList.Treeview",
        )
        column_config = {
            "name": ("模組名稱", 220),
            "author": ("作者", 120),
            "downloads": ("下載數", 100),
            "description": ("描述", 460),
            "platform": ("平台", 90),
            "environments": ("支援環境", 150),
        }
        for col, (text, width) in column_config.items():
            self.browse_tree.heading(col, text=text, anchor="w")
            is_stretch = col == "environments"
            self.browse_tree.column(
                col, width=width, minwidth=width if is_stretch else 60, anchor="w", stretch=is_stretch
            )
        v_scrollbar = ttk.Scrollbar(tree_container, orient="vertical", command=self.browse_tree.yview)
        h_scrollbar = ttk.Scrollbar(tree_container, orient="horizontal", command=self.browse_tree.xview)
        self.browse_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        self.browse_tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)
        TreeUtils.bind_treeview_header_auto_fit(
            self.browse_tree,
            on_row_double_click=self.install_online_mod,
            heading_font=FontManager.get_font(size=FontSize.HEADING_SMALL, weight="bold"),
            body_font=FontManager.get_font(size=FontSize.INPUT),
            stretch_columns={"environments"},
        )
        self.browse_tree.bind("<Button-3>", self.show_browse_context_menu)


__all__ = ["OnlineBrowsePresenter"]
