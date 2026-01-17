#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.properties 設定對話框
提供視覺化的 server.properties 編輯介面
"""
# ====== 標準函式庫 ======
from tkinter import ttk
import tkinter as tk
import traceback
from typing import Dict
import customtkinter as ctk
# ====== 專案內部模組 ======
from ..utils import ServerPropertiesHelper
from ..core import ServerConfig, ServerManager
from ..utils import font_manager, get_dpi_scaled_size, get_font
from ..utils import UIUtils, LogUtils

class ServerPropertiesDialog:
    """
    server.properties 設定對話框
    Server Properties Dialog
    提供視覺化的 server.properties 編輯介面
    (Provides a visual interface for editing server.properties)
    """

    def __init__(
        self, parent, server_config: ServerConfig, server_manager: ServerManager
    ):
        self.parent = parent
        self.server_config = server_config
        self.server_manager = server_manager
        self.properties_helper = ServerPropertiesHelper()
        self.result = None

        # 建立對話框
        self.dialog = tk.Toplevel(parent)

        # 設定對話框
        self.setup_dialog()

        # 屬性值
        self.property_vars: Dict[str, tk.StringVar] = {}
        self.property_widgets: Dict[str, ttk.Widget] = {}

        # 建立介面
        self.create_widgets()
        self.load_properties()

        # 統一設定視窗屬性：綁定圖示、螢幕置中、設為模態視窗
        UIUtils.setup_window_properties(
            window=self.dialog,
            parent=self.parent,
            width=int(1200 * font_manager.get_scale_factor()),
            height=int(900 * font_manager.get_scale_factor()),
            bind_icon=True,
            center_on_parent=True,  # 使用螢幕置中
            make_modal=True,
            delay_ms=250,  # 使用稍長延遲確保圖示綁定成功
        )

        # 顯示對話框
        self.show_dialog()

    def setup_dialog(self) -> None:
        """
        設定對話框
        """
        self.dialog.title(f"伺服器設定 - {self.server_config.name}")
        # 移除固定大小設定，讓視窗根據內容動態調整
        # 只設定最小尺寸
        min_width = int(1200 * font_manager.get_scale_factor())  # 1200 * DPI
        min_height = int(900 * font_manager.get_scale_factor())  # 900 * DPI
        self.dialog.minsize(min_width, min_height)
        self.dialog.resizable(True, True)

        # 應用主題背景顏色
        try:
            self.dialog.configure(bg="#ffffff")  # 淺色背景
        except Exception as e:
            LogUtils.error(
                f"應用對話框主題失敗: {e}\n{traceback.format_exc()}",
                "ServerPropertiesDialog",
            )

    def create_widgets(self) -> None:
        """
        建立介面元件
        Create the interface widgets
        """

        # 主框架
        main_frame = ttk.Frame(self.dialog)
        main_frame.pack(
            fill="both",
            expand=True,
            padx=get_dpi_scaled_size(15),
            pady=get_dpi_scaled_size(15),
        )

        # 標題
        title_label = ttk.Label(
            main_frame,
            text=f"🛠️ {self.server_config.name} - server.properties",
            font=get_font("Microsoft JhengHei", 21, "bold"),  # 21px
        )
        title_label.pack(pady=(0, get_dpi_scaled_size(15)))

        # 建立筆記本 (分頁)
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill="both", expand=True, pady=(0, get_dpi_scaled_size(15)))

        # 建立各個分頁
        self.create_property_tabs()

        # 按鈕框架
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x")

        # 按鈕
        button_width = int(100 * font_manager.get_scale_factor())
        button_height = int(32 * font_manager.get_scale_factor())
        button_font_size = int(18 * font_manager.get_scale_factor())

        ctk.CTkButton(
            button_frame,
            text="💾 儲存",
            command=self.save_properties,
            width=button_width,
            height=button_height,
            font=ctk.CTkFont(
                family="Microsoft JhengHei", size=button_font_size, weight="bold"
            ),
            fg_color=("#2563eb", "#1d4ed8"),
            hover_color=("#1d4ed8", "#1e40af"),
        ).pack(side="right", padx=(get_dpi_scaled_size(8), 0))

        ctk.CTkButton(
            button_frame,
            text="🔄 重設",
            command=self.reset_properties,
            width=button_width,
            height=button_height,
            font=ctk.CTkFont(
                family="Microsoft JhengHei", size=button_font_size, weight="bold"
            ),
            fg_color=("#f59e0b", "#d97706"),
            hover_color=("#d97706", "#b45309"),
        ).pack(side="right", padx=(get_dpi_scaled_size(8), 0))

        ctk.CTkButton(
            button_frame,
            text="❌ 取消",
            command=self.dialog.destroy,
            width=button_width,
            height=button_height,
            font=ctk.CTkFont(
                family="Microsoft JhengHei", size=button_font_size, weight="bold"
            ),
            fg_color=("#dc2626", "#b91c1c"),
            hover_color=("#b91c1c", "#991b1b"),
        ).pack(side="right", padx=(0, get_dpi_scaled_size(15)))

        # 說明標籤
        help_label = ctk.CTkLabel(
            button_frame,
            text="💡 將滑鼠移到設定項目上可查看詳細說明",
            font=get_font(size=14),
            text_color=("gray60", "gray50"),
        )
        help_label.pack(side="left")

    def create_property_tabs(self) -> None:
        """
        建立屬性分頁，並自動補充未分類屬性到「其他」分頁
        Create the property tabs and automatically add uncategorized properties to the "Other" tab
        """

        def _add_scrollable_tab(tab_name: str, properties) -> None:
            tab_frame = ttk.Frame(self.notebook)
            self.notebook.add(tab_frame, text=tab_name)

            canvas = tk.Canvas(tab_frame)
            scrollbar = ttk.Scrollbar(
                tab_frame, orient="vertical", command=canvas.yview
            )
            scrollable_frame = ttk.Frame(canvas)

            state = {"job": None, "last": None}

            def _apply_scrollregion() -> None:
                state["job"] = None
                try:
                    if not canvas.winfo_exists():
                        return
                    bbox = canvas.bbox("all")
                    if not bbox:
                        return
                    x0, y0, x1, y1 = bbox
                    height = max(y1 - y0, canvas.winfo_height())
                    region = (x0, y0, x1, y0 + height)
                    if region != state["last"]:
                        canvas.configure(scrollregion=region)
                        state["last"] = region
                except Exception:
                    return

            def _schedule_scrollregion_update(event=None) -> None:
                try:
                    if state["job"] is not None:
                        canvas.after_cancel(state["job"])
                    state["job"] = canvas.after_idle(_apply_scrollregion)
                except Exception as e:
                    LogUtils.error_exc(
                        f"排程 scrollregion 更新失敗: {e}", "ServerPropertiesDialog", e
                    )

            scrollable_frame.bind("<Configure>", _schedule_scrollregion_update)

            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)

            self.create_property_controls(scrollable_frame, properties)

            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            def _on_mousewheel(event, canvas=canvas):
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

            canvas.bind("<MouseWheel>", _on_mousewheel)

            # 初次排版完成後再更新一次 scrollregion
            _schedule_scrollregion_update()
        categories = self.properties_helper.get_property_categories()
        # 收集所有已分類的 key
        categorized_keys = set()
        for props in categories.values():
            categorized_keys.update(props)

        # 取得所有實際存在的屬性（合併 default + current）
        # 這裡直接用 server_config.properties，若要更完整可合併 default_properties
        all_properties = dict(self.server_config.properties or {})
        # 若 server_manager 有 default，合併進來
        if hasattr(self.server_manager, "get_default_server_properties"):
            try:
                defaults = self.server_manager.get_default_server_properties()
                all_properties = {**defaults, **all_properties}
            except Exception as e:
                LogUtils.error_exc(
                    f"讀取預設 server.properties 失敗: {e}", "ServerPropertiesDialog", e
                )

        all_keys = set(all_properties.keys())
        # 找出未分類的 key
        uncategorized_keys = sorted(list(all_keys - categorized_keys))

        # 先建立分類分頁
        for category_name, properties in categories.items():
            _add_scrollable_tab(category_name, properties)

        # 若有未分類屬性，建立「其他」分頁
        if uncategorized_keys:
            _add_scrollable_tab("其他", uncategorized_keys)

    def create_property_controls(self, parent, properties) -> None:
        """
        建立屬性控制項
        Create the property controls for the given properties
        """

        for i, prop_name in enumerate(properties):
            # 建立框架
            prop_frame = ttk.Frame(parent)
            prop_frame.pack(
                fill="x", padx=get_dpi_scaled_size(15), pady=get_dpi_scaled_size(8)
            )

            # 屬性標籤
            label = ttk.Label(
                prop_frame,
                text=f"{prop_name}:",
                font=get_font("Microsoft JhengHei", 14, "bold"),  # 14 * DPI
            )
            label.pack(anchor="w")

            # 根據屬性類型建立控制項
            var = tk.StringVar()
            self.property_vars[prop_name] = var

            widget = self.create_property_widget(prop_frame, prop_name, var)
            self.property_widgets[prop_name] = widget

            # 添加工具提示
            self.create_tooltip(widget, prop_name)

    def create_property_widget(
        self, parent, prop_name: str, var: tk.StringVar
    ) -> ttk.Widget:
        """
        根據屬性類型建立控制項
        Create the appropriate widget for the property type
        """
        # 布林值屬性
        boolean_props = [
            "hardcore",
            "pvp",
            "online-mode",
            "white-list",
            "generate-structures",
            "spawn-monsters",
            "allow-flight",
            "allow-nether",
            "enable-command-block",
            "use-native-transport",
            "enable-jmx-monitoring",
            "enable-rcon",
            "debug",
            "prevent-proxy-connections",
            "hide-online-players",
            "force-gamemode",
            "broadcast-console-to-ops",
            "broadcast-rcon-to-ops",
            "enable-query",
            "enable-status",
            "log-ips",
            "require-resource-pack",
        ]

        # 選項屬性
        choice_props = {
            "gamemode": ["survival", "creative", "adventure", "spectator"],
            "difficulty": ["peaceful", "easy", "normal", "hard"],
            "level-type": [
                "minecraft:normal",
                "minecraft:flat",
                "minecraft:large_biomes",
                "minecraft:amplified",
            ],
        }

        # 數字範圍屬性
        range_props = {
            "server-port": (1, 65535),
            "max-players": (1, 1000),
            "spawn-protection": (0, 100),
            "view-distance": (3, 32),
            "simulation-distance": (3, 32),
            "op-permission-level": (1, 4),
            "function-permission-level": (1, 4),
            "rcon.port": (1, 65535),
            "query.port": (1, 65535),
            "entity-broadcast-range-percentage": (10, 1000),
            "network-compression-threshold": (-1, 10000),
            "max-tick-time": (1000, 600000),
            "rate-limit": (0, 1000),
            "player-idle-timeout": (0, 1440),
        }

        if prop_name in boolean_props:
            # 布林值
            bool_var = tk.BooleanVar()
            widget = ctk.CTkCheckBox(
                parent,
                variable=bool_var,
                text="啟用",
                font=get_font(size=12),  # 統一字體
                width=get_dpi_scaled_size(180),
                height=get_dpi_scaled_size(36),
            )
            widget.pack(anchor="w", pady=get_dpi_scaled_size(3))

            # 連接到字串變數
            def update_string_var(*args, bv=bool_var, sv=var):
                sv.set("true" if bv.get() else "false")

            def update_bool_var(*args, bv=bool_var, sv=var):
                bv.set(sv.get().lower() == "true")

            bool_var.trace_add("write", update_string_var)
            var.trace_add("write", update_bool_var)

        elif prop_name in choice_props:
            # 選項
            widget = ctk.CTkOptionMenu(
                parent,
                variable=var,
                values=choice_props[prop_name],
                font=get_font(size=11),
                dropdown_font=get_font(size=11),
                width=get_dpi_scaled_size(300),
            )
            widget.pack(fill="x", pady=get_dpi_scaled_size(3))

            # 套用統一下拉選單樣式
            try:
                UIUtils.apply_unified_dropdown_styling(widget)
            except Exception as e:
                LogUtils.error(
                    f"套用下拉選單樣式失敗: {e}\n{traceback.format_exc()}",
                    "ServerPropertiesDialog",
                )

        elif prop_name in range_props:
            # 數字範圍
            min_val, max_val = range_props[prop_name]
            widget = tk.Spinbox(
                parent,
                textvariable=var,
                from_=min_val,
                to=max_val,
                width=get_dpi_scaled_size(30),  # 放大寬度
                font=get_font("Microsoft JhengHei", 15),
            )
            widget.pack(anchor="w")

        else:
            # 一般文字
            widget = ttk.Entry(
                parent,
                textvariable=var,
                font=get_font("Microsoft JhengHei", 15),
            )
            widget.pack(fill="x")

        return widget

    def create_tooltip(self, widget, prop_name: str) -> None:
        """
        建立工具提示
        Create a tooltip for the given widget
        """
        description = self.properties_helper.get_property_description(prop_name)
        UIUtils.bind_tooltip(
            widget,
            description,
            bg="lightyellow",
            fg="black",
            font=get_font("Microsoft JhengHei", 14),
            padx=8,
            pady=4,
            wraplength=get_dpi_scaled_size(600),
            justify="left",
            borderwidth=1,
            relief="solid",
            offset_x=10,
            offset_y=10,
            auto_hide_ms=5000,
        )

    def load_properties(self) -> None:
        """
        載入屬性值
        Load the property values from the server configuration or file
        """
        # 首先嘗試從檔案載入現有屬性
        current_properties = self.server_manager.load_server_properties(
            self.server_config.name
        )
        # 如果沒有找到檔案，使用配置中的屬性
        if not current_properties:
            current_properties = dict(self.server_config.properties or {})
        # 獲取預設屬性
        default_properties = self.server_manager.get_default_server_properties()
        # 合併屬性（現有優先）
        all_properties = {**default_properties, **current_properties}
        # 設定到控制項
        for prop_name, value in all_properties.items():
            if prop_name in self.property_vars:
                self.property_vars[prop_name].set(str(value))

    def save_properties(self) -> None:
        """
        儲存屬性
        Save the properties to the server configuration or file
        """
        try:
            # 收集所有屬性值
            properties = {}
            for prop_name, var in self.property_vars.items():
                value = var.get().strip()
                if value:  # 只儲存非空值
                    properties[prop_name] = value

            # 更新伺服器屬性
            success = self.server_manager.update_server_properties(
                self.server_config.name, properties
            )

            if success:
                UIUtils.show_info(
                    "成功",
                    "伺服器屬性已儲存\n若伺服器正在運行建議執行指令：/reload或是重新運行伺服器",
                    self.dialog,
                )
                self.dialog.destroy()
            else:
                UIUtils.show_error("錯誤", "儲存伺服器屬性失敗", self.dialog)

        except Exception as e:
            LogUtils.error(
                f"儲存時發生錯誤: {e}\n{traceback.format_exc()}",
                "ServerPropertiesDialog",
            )
            UIUtils.show_error("錯誤", f"儲存時發生錯誤: {e}", self.dialog)

    def show_dialog(self) -> None:
        """
        顯示對話框
        """
        self.dialog.focus_set()
        self.dialog.wait_window()

    def reset_properties(self) -> None:
        """
        重設所有屬性為預設值
        Reset all properties to default values
        """
        if UIUtils.ask_yes_no_cancel(
            "確認", "確定要重設所有屬性為預設值嗎？", self.dialog, show_cancel=False
        ):
            default_properties = self.server_manager.get_default_server_properties()
            for prop_name, value in default_properties.items():
                if prop_name in self.property_vars:
                    self.property_vars[prop_name].set(str(value))
