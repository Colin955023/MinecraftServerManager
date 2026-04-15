"""輕量虛擬清單元件（以 Tk Listbox 實作）。"""

from __future__ import annotations

import tkinter
import tkinter.font as tkfont
import tkinter.ttk as ttk
from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from ..utils import Colors, FontSize
from . import FontManager, TreeUtils


def _resolve_token_color(color: str | tuple[str, str]) -> str:
    """將 light/dark token 解析為 tkinter 可用顏色字串。"""
    if isinstance(color, tuple):
        return color[1] if ctk.get_appearance_mode() == "Dark" else color[0]
    return color


def _normalize_tk_font(font) -> Any:
    """將 CTkFont 正規化為 Tk 可穩定套用的格式。"""
    if font is None:
        return None
    if hasattr(font, "cget"):
        try:
            family = font.cget("family")
            size = int(font.cget("size"))
            weight = font.cget("weight")
            slant = font.cget("slant")
            underline = bool(font.cget("underline"))
            overstrike = bool(font.cget("overstrike"))
            return tkfont.Font(
                family=family, size=size, weight=weight, slant=slant, underline=underline, overstrike=overstrike
            )
        except Exception:
            return font
    return font


class VirtualList(tkinter.Frame):
    """以 Listbox 提供大量項目清單顯示，避免建立大量 row widgets。"""

    def __init__(
        self,
        parent,
        *,
        items: list[str] | tuple[str, ...] | None = None,
        on_select: Callable[[str, int], Any] | None = None,
        height_rows: int = 8,
        show_scrollbar: bool = True,
        font=None,
        bg: str | tuple[str, str] = Colors.DROPDOWN_BG,
        fg: str | tuple[str, str] = Colors.TEXT_PRIMARY,
        select_bg: str | tuple[str, str] = Colors.BUTTON_PRIMARY,
        select_fg: str | tuple[str, str] = Colors.BG_PRIMARY,
    ):
        resolved_bg = _resolve_token_color(bg)
        resolved_fg = _resolve_token_color(fg)
        resolved_select_bg = _resolve_token_color(select_bg)
        resolved_select_fg = _resolve_token_color(select_fg)
        super().__init__(parent, bg=resolved_bg, highlightthickness=0, bd=0)
        self._on_select = on_select
        self._all_items: list[str] = list(items or [])
        self._items: list[str] = []
        self._filter_query = ""
        self._filter_case_sensitive = False
        self._sort_key: Callable[[str], Any] | None = None
        self._sort_reverse = False
        self.listbox = tkinter.Listbox(
            self,
            activestyle="none",
            exportselection=False,
            selectmode="browse",
            height=max(1, int(height_rows)),
            highlightthickness=0,
            bd=0,
            bg=resolved_bg,
            fg=resolved_fg,
            selectbackground=resolved_select_bg,
            selectforeground=resolved_select_fg,
        )
        if font is None:
            font = FontManager.get_font(size=FontSize.MEDIUM)
        self.listbox.configure(font=_normalize_tk_font(font))
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=self.scrollbar.set)
        if show_scrollbar:
            self.listbox.pack(side="left", fill="both", expand=True)
            self.scrollbar.pack(side="right", fill="y")
        else:
            self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_listbox_select)
        self._rebuild_view(preserve_selection=False)

    def _render_items(self) -> None:
        self.listbox.delete(0, "end")
        if self._items:
            self.listbox.insert("end", *self._items)
        TreeUtils.apply_listbox_alternating_rows(self.listbox, item_count=len(self._items))

    def _rebuild_view(self, *, preserve_selection: bool) -> None:
        previous_value = self.get_selected_value() if preserve_selection else None
        items = list(self._all_items)
        query = self._filter_query
        if query:
            if self._filter_case_sensitive:
                items = [item for item in items if query in item]
            else:
                folded_query = query.lower()
                items = [item for item in items if folded_query in item.lower()]
        if self._sort_key is not None:
            with_key = self._sort_key
            items.sort(key=with_key, reverse=self._sort_reverse)
        self._items = items
        self._render_items()
        if previous_value and previous_value in self._items:
            self.select_index(self._items.index(previous_value), ensure_visible=True, notify=False)

    def _on_listbox_select(self, _event=None) -> None:
        if not self._on_select:
            return
        idx = self.get_selected_index()
        if idx is None:
            return
        value = self._items[idx]
        self._on_select(value, idx)

    def set_items(self, items: list[str] | tuple[str, ...], *, preserve_selection: bool = True) -> None:
        """設定清單資料並可選擇保留目前選取項目。"""

        self._all_items = list(items)
        self._rebuild_view(preserve_selection=preserve_selection)

    def set_filter(self, query: str | None, *, case_sensitive: bool = False, preserve_selection: bool = True) -> None:
        """設定包含式篩選條件。"""
        self._filter_query = (query or "").strip()
        self._filter_case_sensitive = bool(case_sensitive)
        self._rebuild_view(preserve_selection=preserve_selection)

    def clear_filter(self, *, preserve_selection: bool = True) -> None:
        """清除目前篩選條件。"""
        self._filter_query = ""
        self._rebuild_view(preserve_selection=preserve_selection)

    def set_sort(
        self, key: Callable[[str], Any] | None = None, *, reverse: bool = False, preserve_selection: bool = True
    ) -> None:
        """設定排序方式。`key=None` 表示維持原順序。"""
        self._sort_key = key
        self._sort_reverse = bool(reverse)
        self._rebuild_view(preserve_selection=preserve_selection)

    def clear_sort(self, *, preserve_selection: bool = True) -> None:
        """清除排序設定，回復資料原始順序。"""
        self._sort_key = None
        self._sort_reverse = False
        self._rebuild_view(preserve_selection=preserve_selection)

    def get_selected_index(self) -> int | None:
        """取得目前選取項目的索引。"""

        selection = self.listbox.curselection()
        if not selection:
            return None
        return int(selection[0])

    def get_selected_value(self) -> str | None:
        """取得目前選取項目的值。"""

        idx = self.get_selected_index()
        if idx is None:
            return None
        if idx < 0 or idx >= len(self._items):
            return None
        return self._items[idx]

    def select_index(self, index: int, *, ensure_visible: bool = True, notify: bool = False) -> None:
        """選取指定索引的項目。

        Args:
            index: 要選取的索引。
            ensure_visible: 是否捲動到可見範圍。
            notify: 是否觸發選取 callback。
        """

        if index < 0 or index >= len(self._items):
            return
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        if ensure_visible:
            self.listbox.see(index)
        if notify and self._on_select:
            self._on_select(self._items[index], index)

    def move_selection(self, offset: int, *, ensure_visible: bool = True, notify: bool = False) -> None:
        """將目前選取項目向上/向下位移。"""
        if not self._items:
            return
        current = self.get_selected_index()
        if current is None:
            current = 0
        target = max(0, min(len(self._items) - 1, current + int(offset)))
        self.select_index(target, ensure_visible=ensure_visible, notify=notify)

    def set_font(self, font) -> None:
        """動態更新清單字型。"""
        self.listbox.configure(font=_normalize_tk_font(font))

    def set_font_size(self, size: int, *, family: str | None = None, weight: str = "normal") -> None:
        """以 token 字體管理器動態更新字級（含 DPI 縮放）。"""
        self.set_font(FontManager.get_font(family=family, size=size, weight=weight))

    def clear(self) -> None:
        """清空清單內容與目前資料。"""

        self._all_items = []
        self._items = []
        self.listbox.delete(0, "end")
        TreeUtils.apply_listbox_alternating_rows(self.listbox, item_count=0)

    @property
    def item_count(self) -> int:
        return len(self._items)

    def total_count(self) -> int:
        """取得原始資料總數。"""

        return len(self._all_items)
