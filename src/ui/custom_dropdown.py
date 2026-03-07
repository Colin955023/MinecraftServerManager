#!/usr/bin/env python3
"""自定義下拉選單元件模組
使用 button 和 listbox 實現下拉選單功能，支援滾輪選擇、滾動條等功能
Custom Dropdown Component Module
Implements dropdown functionality using button and listbox with wheel selection and scrollbar support
"""

import tkinter as tk
import traceback
from collections.abc import Callable

import customtkinter as ctk

from ..utils import Colors, FontManager, FontSize, Sizes, UIUtils, get_logger
from . import VirtualList

logger = get_logger().bind(component="CustomDropdown")


class CustomDropdown(ctk.CTkFrame):
    """自定義下拉選單元件類別，使用 button 和 listbox 實現下拉選單功能"""

    # ====== 初始化與設定 ======
    def __init__(
        self,
        parent,
        variable: tk.StringVar | None = None,
        values: list[str] | None = None,
        command: Callable | None = None,
        width: int = Sizes.DROPDOWN_WIDTH,
        height: int = Sizes.DROPDOWN_HEIGHT,
        max_dropdown_height: int = Sizes.DROPDOWN_MAX_HEIGHT,
        max_visible_items: int = 8,
        font_size: int = FontSize.MEDIUM,
        dropdown_font_size: int | None = None,
        state: str = "normal",
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self.variable = variable or tk.StringVar()
        self.values = values or []
        self.command = command
        self.width = width
        self.height = height
        self.max_dropdown_height = max_dropdown_height
        self.max_visible_items = max_visible_items
        self.font_size = int(font_size)
        self.dropdown_font_size = int(dropdown_font_size) if dropdown_font_size is not None else int(font_size)
        self.state = state

        # 下拉狀態
        self.is_dropdown_open = False
        self.dropdown_window = None
        self.dropdown_list: VirtualList | None = None
        self._global_click_bind_id: str | None = None
        self._global_click_toplevel = None

        # 建立 UI 元件
        self._create_widgets()

        # 綁定變數變更事件
        self.variable.trace_add("write", self._on_variable_changed)

        # 綁定滑鼠滾輪事件
        self._bind_mouse_wheel()

    def _create_widgets(self) -> None:
        """建立介面元件"""
        # 主按鈕
        self.button = ctk.CTkButton(
            self,
            text=self.variable.get() or "請選擇...",
            width=self.width,
            height=self.height,
            command=self._toggle_dropdown,
            anchor="w",
            font=FontManager.get_font(size=self.font_size),
            fg_color=Colors.DROPDOWN_BG,
            text_color=Colors.TEXT_PRIMARY,
            border_width=1,
            border_color=Colors.BORDER_LIGHT,
            hover_color=Colors.DROPDOWN_HOVER,
        )
        self.button.pack(fill="x")

        # 下拉箭頭標籤（覆蓋在按鈕右側）
        self.arrow_label = ctk.CTkLabel(
            self.button,
            text="▼",
            font=FontManager.get_font(size=FontSize.TINY),
            text_color=Colors.TEXT_SECONDARY,
            width=Sizes.ICON_BUTTON,
            height=Sizes.ICON_BUTTON,
        )
        self.arrow_label.place(relx=1.0, rely=0.5, anchor="e", x=-10)

        # 箭頭標籤接收點擊事件
        self.arrow_label.bind("<Button-1>", self._on_button_click)

    def _on_button_click(self, _event=None) -> None:
        """按鈕點擊事件"""
        if self.state != "disabled":
            self._toggle_dropdown()

    def _toggle_dropdown(self) -> None:
        """切換下拉選單狀態"""
        if self.state == "disabled":
            return

        if self.is_dropdown_open:
            self._close_dropdown()
        else:
            self._open_dropdown()

    def _open_dropdown(self) -> None:
        """打開下拉選單"""
        if self.is_dropdown_open or self.state == "disabled":
            return

        self.is_dropdown_open = True
        self.arrow_label.configure(text="▲")

        # 建立下拉視窗
        window = ctk.CTkToplevel(self)
        self.dropdown_window = window
        window.withdraw()  # 先隱藏
        window.overrideredirect(True)  # 移除視窗裝飾

        # Safe transient call
        top = self.winfo_toplevel()
        if top.winfo_exists():
            window.transient(top)

        # 計算位置
        try:
            # 嘗試獲取 CustomTkinter 內部的縮放因子
            scale = self.button._get_widget_scaling()
        except AttributeError:
            try:
                scale = ctk.ScalingTracker.get_widget_scaling(self.button)
            except Exception:
                scale = FontManager.get_scale_factor()

        button_x = self.button.winfo_rootx()
        button_y = self.button.winfo_rooty()
        button_height = self.button.winfo_height()
        button_width = self.button.winfo_width()  # 獲取按鈕實際寬度

        # 轉換為邏輯寬度
        logical_button_width = int(button_width / scale)

        # 計算下拉清單高度
        item_height = Sizes.DROPDOWN_ITEM_HEIGHT
        total_items = len(self.values)
        visible_items = max(1, min(total_items, self.max_visible_items))

        # 計算需要的總高度
        needed_height = visible_items * item_height
        if total_items > self.max_visible_items:
            needed_height += 10  # 額外空間給 padding

        dropdown_height = min(needed_height, self.max_dropdown_height)

        # 設定視窗位置和大小 - 寬度與按鈕一致
        window.geometry(f"{logical_button_width}x{dropdown_height}+{button_x}+{button_y + button_height}")

        # 以 VirtualList（Listbox）渲染選項，避免每個項目建立一個按鈕 widget。
        bg_color = Colors.DROPDOWN_BG[0] if isinstance(Colors.DROPDOWN_BG, tuple) else Colors.DROPDOWN_BG
        container = tk.Frame(window, bg=bg_color, bd=0, highlightthickness=0)
        container.pack(fill="both", expand=True, padx=0, pady=0)

        def _on_list_select(value: str, _index: int) -> None:
            self._select_option(value)

        self.dropdown_list = VirtualList(
            container,
            items=self.values,
            on_select=_on_list_select,
            height_rows=max(1, visible_items),
            show_scrollbar=total_items > self.max_visible_items,
            font=FontManager.get_font(size=self.dropdown_font_size),
            bg=Colors.DROPDOWN_BG,
            fg=Colors.TEXT_PRIMARY,
            select_bg=Colors.BUTTON_PRIMARY,
            select_fg=Colors.BG_PRIMARY,
        )
        self.dropdown_list.pack(fill="both", expand=True)

        current_value = self.variable.get()
        if current_value in self.values:
            self.dropdown_list.select_index(self.values.index(current_value), ensure_visible=True, notify=False)

        # 綁定事件來關閉下拉選單
        window.bind("<Escape>", lambda _e: self._close_dropdown())

        # 顯示視窗
        window.deiconify()
        window.focus_set()

        # 延遲綁定全域點擊和焦點事件，避免立即觸發關閉
        UIUtils.schedule_debounce(self, "_dropdown_bind_job", 150, self._delayed_bind_events, owner=self)

    def _delayed_bind_events(self) -> None:
        """延遲綁定事件，避免立即觸發關閉"""
        if self.dropdown_window and self.is_dropdown_open:
            self._bind_global_click()

    def _close_dropdown(self, _event=None) -> None:
        """關閉下拉選單"""
        UIUtils.cancel_scheduled_job(self, "_dropdown_bind_job", owner=self)
        UIUtils.cancel_scheduled_job(self, "_dropdown_close_job", owner=self)

        if not self.is_dropdown_open:
            return

        self.is_dropdown_open = False
        self.arrow_label.configure(text="▼")

        if self.dropdown_window:
            self.dropdown_window.destroy()
            self.dropdown_window = None

        self.dropdown_list = None
        self._unbind_global_click()

    def _select_option(self, value: str) -> None:
        """選擇選項"""
        self.variable.set(value)
        self.button.configure(text=value)

        # 執行回調
        if self.command:
            try:
                self.command(value)
            except Exception as e:
                logger.error(f"下拉選單回調錯誤: {e}\n{traceback.format_exc()}")
                UIUtils.show_error("錯誤", f"下拉選單回調錯誤: {e}", self.winfo_toplevel())

        # 關閉下拉選單 - 稍微延遲以確保點擊效果可見
        UIUtils.schedule_debounce(self, "_dropdown_close_job", 150, self._close_dropdown, owner=self)

    def _on_variable_changed(self, *_args) -> None:
        """變數變更事件"""
        new_value = self.variable.get()
        self.button.configure(text=new_value or "請選擇...")

    def _bind_mouse_wheel(self) -> None:
        """綁定滑鼠滾輪事件"""

        def on_mouse_wheel(event):
            if self.state == "disabled" or not self.values:
                return

            current_value = self.variable.get()
            if current_value not in self.values:
                return

            current_index = self.values.index(current_value)

            # 向上滾動選擇上一個，向下滾動選擇下一個
            if event.delta > 0 and current_index > 0:
                new_index = current_index - 1
            elif event.delta < 0 and current_index < len(self.values) - 1:
                new_index = current_index + 1
            else:
                return

            new_value = self.values[new_index]
            self.variable.set(new_value)

            if self.command:
                try:
                    self.command(new_value)
                except Exception as e:
                    logger.bind(component="").error(
                        f"滾輪事件回調錯誤: {e}\n{traceback.format_exc()}",
                        "CustomDropdown",
                    )
                    UIUtils.show_error("錯誤", f"滾輪事件回調錯誤: {e}", self.winfo_toplevel())

        self.button.bind("<MouseWheel>", on_mouse_wheel)

    def _bind_global_click(self) -> None:
        """綁定全域點擊事件"""

        def on_global_click(event):
            # 檢查點擊是否在下拉選單外部
            if not self.dropdown_window or not self.is_dropdown_open:
                return

            try:
                # 獲取點擊位置
                x, y = event.x_root, event.y_root

                # 檢查是否點擊在下拉選單或按鈕上
                dropdown_x = self.dropdown_window.winfo_rootx()
                dropdown_y = self.dropdown_window.winfo_rooty()
                dropdown_width = self.dropdown_window.winfo_width()
                dropdown_height = self.dropdown_window.winfo_height()

                button_x = self.button.winfo_rootx()
                button_y = self.button.winfo_rooty()
                button_width = self.button.winfo_width()
                button_height = self.button.winfo_height()

                # 檢查點擊是否在下拉選單內
                in_dropdown = (
                    dropdown_x <= x <= dropdown_x + dropdown_width and dropdown_y <= y <= dropdown_y + dropdown_height
                )

                # 檢查點擊是否在按鈕內
                in_button = button_x <= x <= button_x + button_width and button_y <= y <= button_y + button_height

                # 如果點擊在下拉選單或按鈕外部，關閉下拉選單
                if not (in_dropdown or in_button):
                    self._close_dropdown()
            except Exception as e:
                logger.exception(f"全域點擊處理失敗: {e}")

        # 綁定到頂層視窗
        self._unbind_global_click()
        toplevel = self.winfo_toplevel()
        bind_id = toplevel.bind("<Button-1>", on_global_click, add=True)
        self._global_click_bind_id = bind_id
        self._global_click_toplevel = toplevel

    def _unbind_global_click(self) -> None:
        """移除全域點擊綁定"""
        bind_id = self._global_click_bind_id
        toplevel = self._global_click_toplevel
        self._global_click_bind_id = None
        self._global_click_toplevel = None
        if not bind_id or toplevel is None:
            return
        try:
            if toplevel.winfo_exists():
                toplevel.unbind("<Button-1>", bind_id)
        except Exception as e:
            logger.exception(f"移除全域點擊綁定失敗: {e}")

    # 公共方法，模擬 CTkComboBox/CTkOptionMenu 的介面
    def get(self) -> str:
        """獲取當前值"""
        return self.variable.get()

    def set(self, value: str) -> None:
        """設定當前值"""
        self.variable.set(value)

    def configure(self, **kwargs) -> None:
        """配置元件"""
        if "values" in kwargs:
            self.values = kwargs.pop("values")

        if "state" in kwargs:
            self.state = kwargs.pop("state")
            if self.state == "disabled":
                self.button.configure(state="disabled")
                if self.is_dropdown_open:
                    self._close_dropdown()
            else:
                self.button.configure(state="normal")

        if "command" in kwargs:
            self.command = kwargs.pop("command")

        if "font_size" in kwargs:
            self.font_size = int(kwargs.pop("font_size"))
            self.button.configure(font=FontManager.get_font(size=self.font_size))
            if self.dropdown_list:
                self.dropdown_list.set_font_size(self.font_size)

        if "dropdown_font_size" in kwargs:
            self.dropdown_font_size = int(kwargs.pop("dropdown_font_size"))
            if self.dropdown_list:
                self.dropdown_list.set_font_size(self.dropdown_font_size)

        # 將其他參數傳遞給父類
        if kwargs:
            super().configure(**kwargs)

    def cget(self, key: str) -> str | list[str] | int:
        """獲取配置值"""
        if key == "values":
            return self.values
        if key == "state":
            return self.state
        if key == "font_size":
            return self.font_size
        if key == "dropdown_font_size":
            return self.dropdown_font_size
        return super().cget(key)

    def destroy(self) -> None:
        """銷毀元件"""
        UIUtils.cancel_scheduled_job(self, "_dropdown_bind_job", owner=self)
        UIUtils.cancel_scheduled_job(self, "_dropdown_close_job", owner=self)
        self._unbind_global_click()
        if self.is_dropdown_open:
            self._close_dropdown()
        super().destroy()
