#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定義下拉選單元件模組
使用 button 和 listbox 實現下拉選單功能，支援滾輪選擇、滾動條等功能
Custom Dropdown Component Module
Implements dropdown functionality using button and listbox with wheel selection and scrollbar support
"""
# ====== 標準函式庫 ======
from typing import Callable, List
import traceback
import tkinter as tk
import customtkinter as ctk
# ====== 專案內部模組 ======
from ..utils import font_manager, get_font
from ..utils import UIUtils, LogUtils

class CustomDropdown(ctk.CTkFrame):
    """
    自定義下拉選單元件類別，使用 button 和 listbox 實現下拉選單功能
    Custom dropdown component class implementing dropdown functionality using button and listbox
    """
    # ====== 初始化與設定 ======
    # 初始化下拉選單元件
    def __init__(
        self,
        parent,
        variable: tk.StringVar = None,
        values: List[str] = None,
        command: Callable = None,
        width: int = 280,
        height: int = 30,
        max_dropdown_height: int = 200,
        max_visible_items: int = 8,
        state: str = "normal",
        **kwargs,
    ):
        """
        初始化自定義下拉選單元件
        Initialize custom dropdown component

        Args:
            parent: 父容器物件
            variable (tk.StringVar): 關聯的 StringVar 變數
            values (List[str]): 選項列表
            command (Callable): 選擇回調函數
            width (int): 下拉選單寬度
            height (int): 按鈕高度
            max_dropdown_height (int): 下拉清單最大高度
            max_visible_items (int): 最大可見項目數量
            state (str): 元件狀態

        Returns:
            None
        """
        super().__init__(parent, fg_color="transparent", **kwargs)

        self.variable = variable or tk.StringVar()
        self.values = values or []
        self.command = command
        self.width = width
        self.height = height
        self.max_dropdown_height = max_dropdown_height
        self.max_visible_items = max_visible_items
        self.state = state

        # 下拉狀態
        self.is_dropdown_open = False
        self.dropdown_window = None

        # 建立 UI 元件
        self._create_widgets()

        # 綁定變數變更事件
        self.variable.trace_add("write", self._on_variable_changed)

        # 綁定滑鼠滾輪事件
        self._bind_mouse_wheel()

    def _create_widgets(self) -> None:
        """
        建立介面元件
        Create interface widgets
        """
        # 主按鈕
        self.button = ctk.CTkButton(
            self,
            text=self.variable.get() or "請選擇...",
            width=self.width,
            height=self.height,
            command=self._toggle_dropdown,
            anchor="w",
            font=get_font(size=11),
            fg_color=("#ffffff", "#ffffff"),  # 白色背景
            text_color=("#1f2937", "#1f2937"),  # 深色文字
            border_width=1,
            border_color=("#d1d5db", "#d1d5db"),  # 淺灰色邊框
            hover_color=("#f3f4f6", "#f3f4f6"),  # 懸停時稍微變暗
        )
        self.button.pack(fill="x")

        # 下拉箭頭標籤（覆蓋在按鈕右側）
        self.arrow_label = ctk.CTkLabel(
            self.button,
            text="▼",
            font=get_font(size=10),
            text_color=("#6b7280", "#6b7280"),  # 灰色箭頭
            width=20,
            height=20,
        )
        self.arrow_label.place(relx=1.0, rely=0.5, anchor="e", x=-10)

        # 箭頭標籤接收點擊事件
        self.arrow_label.bind("<Button-1>", self._on_button_click)

    def _on_button_click(self, event=None) -> None:
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
        self.dropdown_window = ctk.CTkToplevel(self)
        self.dropdown_window.withdraw()  # 先隱藏
        self.dropdown_window.overrideredirect(True)  # 移除視窗裝飾
        self.dropdown_window.transient(self.winfo_toplevel())

        # 計算位置
        try:
            # 嘗試獲取 CustomTkinter 內部的縮放因子
            scale = self.button._get_widget_scaling()
        except AttributeError:
            try:
                scale = ctk.ScalingTracker.get_widget_scaling(self.button)
            except Exception:
                scale = font_manager.get_scale_factor()

        button_x = self.button.winfo_rootx()
        button_y = self.button.winfo_rooty()
        button_height = self.button.winfo_height()
        button_width = self.button.winfo_width()  # 獲取按鈕實際寬度
        
        # 轉換為邏輯寬度
        logical_button_width = int(button_width / scale)

        # 計算下拉清單高度
        item_height = 30  # 增加項目高度以容納較大字體
        total_items = len(self.values)
        visible_items = min(total_items, self.max_visible_items)
        
        # 計算需要的總高度
        needed_height = visible_items * item_height
        if total_items > self.max_visible_items:
            needed_height += 10 # 額外空間給 padding
            
        dropdown_height = min(needed_height, self.max_dropdown_height)

        # 設定視窗位置和大小 - 寬度與按鈕一致
        self.dropdown_window.geometry(f"{logical_button_width}x{dropdown_height}+{button_x}+{button_y + button_height}")

        # 建立滾動框架
        if total_items > self.max_visible_items:
            # 需要滾動條
            self.scroll_frame = ctk.CTkScrollableFrame(
                self.dropdown_window,
                width=logical_button_width, # 寬度與視窗一致
                height=dropdown_height,
                fg_color=("#ffffff", "#ffffff"),
                scrollbar_button_color=("#d1d5db", "#d1d5db"),
                scrollbar_button_hover_color=("#9ca3af", "#9ca3af"),
            )
            self.scroll_frame.pack(fill="both", expand=True, padx=0, pady=0)
            container = self.scroll_frame
        else:
            # 不需要滾動條
            container = ctk.CTkFrame(self.dropdown_window, fg_color=("#ffffff", "#ffffff"), corner_radius=0)
            container.pack(fill="both", expand=True, padx=0, pady=0)

        # 建立選項按鈕
        self.option_buttons = []
        current_value = self.variable.get()

        # 優化：預先建立字體物件和樣式設定，避免在迴圈中重複計算
        font_obj = get_font(size=14)
        btn_width = logical_button_width - 20 if total_items > self.max_visible_items else logical_button_width
        
        # 樣式常數
        SELECTED_FG = ("#3b82f6", "#2563eb")
        NORMAL_FG = "transparent"
        SELECTED_TEXT = ("#ffffff", "#ffffff")
        NORMAL_TEXT = ("#1f2937", "#1f2937")
        SELECTED_HOVER = ("#2563eb", "#1d4ed8")
        NORMAL_HOVER = ("#60a5fa", "#3b82f6")

        # 分批載入設定
        # 第一批載入數量：可見項目 + 緩衝區，確保打開時立即填滿視窗
        INITIAL_BATCH_SIZE = self.max_visible_items + 5
        # 後續批次載入數量
        BATCH_SIZE = 20
        # 批次載入間隔 (ms)
        BATCH_INTERVAL = 5

        def create_option_button(value):
            """建立單個選項按鈕"""
            is_selected = value == current_value
            
            option_btn = ctk.CTkButton(
                container,
                text=value,
                width=btn_width,
                height=item_height,
                command=lambda v=value: self._select_option(v),
                anchor="w",
                font=font_obj,
                fg_color=SELECTED_FG if is_selected else NORMAL_FG,
                text_color=SELECTED_TEXT if is_selected else NORMAL_TEXT,
                hover_color=NORMAL_HOVER if not is_selected else SELECTED_HOVER,
                border_width=0,
                corner_radius=0
            )
            option_btn.pack(fill="x", pady=0)
            self.option_buttons.append(option_btn)

        def load_batch(start_index):
            """分批載入選項"""
            # 如果下拉選單已關閉，停止載入
            if not self.is_dropdown_open or not self.dropdown_window:
                return

            end_index = min(start_index + BATCH_SIZE, len(self.values))
            
            # 批量建立按鈕
            for i in range(start_index, end_index):
                create_option_button(self.values[i])
            
            # 如果還有剩餘項目，安排下一次載入
            if end_index < len(self.values):
                self.after(BATCH_INTERVAL, lambda: load_batch(end_index))

        # 立即載入第一批
        first_batch_end = min(INITIAL_BATCH_SIZE, len(self.values))
        for i in range(first_batch_end):
            create_option_button(self.values[i])

        # 綁定事件來關閉下拉選單
        self.dropdown_window.bind("<Escape>", lambda e: self._close_dropdown())

        # 顯示視窗
        self.dropdown_window.deiconify()
        self.dropdown_window.focus_set()
        
        # 開始載入剩餘項目
        if first_batch_end < len(self.values):
            self.after(BATCH_INTERVAL, lambda: load_batch(first_batch_end))

        # 延遲綁定全域點擊和焦點事件，避免立即觸發關閉
        self.after(150, self._delayed_bind_events)

    def _delayed_bind_events(self) -> None:
        """
        延遲綁定事件，避免立即觸發關閉
        delay binding events to avoid immediate closure
        """
        if self.dropdown_window and self.is_dropdown_open:
            self._bind_global_click()

    def _close_dropdown(self, event=None) -> None:
        """關閉下拉選單"""
        if not self.is_dropdown_open:
            return

        self.is_dropdown_open = False
        self.arrow_label.configure(text="▼")

        if self.dropdown_window:
            self.dropdown_window.destroy()
            self.dropdown_window = None

        self.option_buttons = []
        self._unbind_global_click()

    def _select_option(self, value: str) -> None:
        """
        選擇選項
        Select an option

        Args:
            value (str):選擇的值
        """
        self.variable.set(value)
        self.button.configure(text=value)

        # 更新選項按鈕樣式
        for btn in self.option_buttons:
            if btn.cget("text") == value:
                btn.configure(fg_color=("#3b82f6", "#2563eb"), text_color=("#ffffff", "#ffffff"))
            else:
                btn.configure(fg_color="transparent", text_color=("#1f2937", "#1f2937"))

        # 執行回調
        if self.command:
            try:
                self.command(value)
            except Exception as e:
                LogUtils.error(f"下拉選單回調錯誤: {e}\n{traceback.format_exc()}", "CustomDropdown")
                UIUtils.show_error("錯誤", f"下拉選單回調錯誤: {e}", self.winfo_toplevel())

        # 關閉下拉選單 - 稍微延遲以確保點擊效果可見
        self.after(150, self._close_dropdown)

    def _on_variable_changed(self, *args) -> None:
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
                    LogUtils.error(f"滾輪事件回調錯誤: {e}\n{traceback.format_exc()}", "CustomDropdown")
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
                LogUtils.error_exc(f"全域點擊處理失敗: {e}", "CustomDropdown", e)

        # 綁定到頂層視窗
        toplevel = self.winfo_toplevel()
        toplevel.bind("<Button-1>", on_global_click, add=True)
        self._global_click_binding = on_global_click

    def _unbind_global_click(self) -> None:
        """移除全域點擊綁定"""
        if hasattr(self, "_global_click_binding"):
            try:
                toplevel = self.winfo_toplevel()
                toplevel.unbind("<Button-1>")
            except Exception as e:
                LogUtils.error_exc(f"移除全域點擊綁定失敗: {e}", "CustomDropdown", e)

    # 公共方法，模擬 CTkComboBox/CTkOptionMenu 的介面
    def get(self) -> str:
        """獲取當前值"""
        return self.variable.get()

    def set(self, value: str) -> None:
        """
        設定當前值
        Set the current value

        Args:
            value (str):當前選擇的值
        """
        self.variable.set(value)

    def configure(self, **kwargs) -> None:
        """
        配置元件
        Configure the widget

        Args:
            **kwargs: 配置參數
        """
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

        # 將其他參數傳遞給父類
        if kwargs:
            super().configure(**kwargs)

    def cget(self, key: str) -> str:
        """
        獲取配置值
        Get the configuration value

        Args:
            key (str): 配置值
        """
        if key == "values":
            return self.values
        elif key == "state":
            return self.state
        else:
            return super().cget(key)

    def destroy(self) -> None:
        """
        銷毀元件
        Destroy the widget
        """
        if self.is_dropdown_open:
            self._close_dropdown()
        super().destroy()
