#!/usr/bin/env python3
"""server.properties 設定對話框
提供視覺化的 server.properties 編輯介面
"""

import tkinter as tk
import traceback
from tkinter import ttk
from typing import ClassVar

import customtkinter as ctk

from ..core import ServerConfig, ServerManager
from ..utils import (
    Colors,
    FontManager,
    FontSize,
    ServerPropertiesHelper,
    ServerPropertiesValidator,
    Sizes,
    UIUtils,
    get_button_style,
    get_logger,
)
from . import CustomDropdown

logger = get_logger().bind(component="ServerPropertiesDialog")


class ServerPropertiesDialog:
    """
    server.properties 設定對話框
    提供視覺化的 server.properties 編輯介面
    """

    BOOLEAN_PROPS: tuple[str, ...] = (
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
        "prevent-proxy-connections",
        "hide-online-players",
        "force-gamemode",
        "broadcast-console-to-ops",
        "broadcast-rcon-to-ops",
        "enable-query",
        "enable-status",
        "log-ips",
        "require-resource-pack",
        "enable-code-of-conduct",
        "accepts-transfers",
        "sync-chunk-writes",
        "management-server-enabled",
        "management-server-tls-enabled",
    )

    CHOICE_PROPS: ClassVar[dict[str, tuple[str, ...]]] = {
        "gamemode": ("survival", "creative", "adventure", "spectator"),
        "difficulty": ("peaceful", "easy", "normal", "hard"),
        "level-type": (
            "minecraft:normal",
            "minecraft:flat",
            "minecraft:large_biomes",
            "minecraft:amplified",
        ),
        "region-file-compression": ("deflate", "lz4", "none"),
    }

    RANGE_PROPS: ClassVar[dict[str, tuple[int, int]]] = {
        "server-port": (1, 65534),
        "max-players": (1, 1000),
        "spawn-protection": (0, 100),
        "view-distance": (3, 32),
        "simulation-distance": (3, 32),
        "op-permission-level": (1, 4),
        "function-permission-level": (1, 4),
        "rcon.port": (1, 65534),
        "query.port": (1, 65534),
        "entity-broadcast-range-percentage": (10, 1000),
        "network-compression-threshold": (-1, 10000),
        "max-tick-time": (1000, 600000),
        "rate-limit": (0, 1000),
        "player-idle-timeout": (0, 1440),
    }

    def __init__(self, parent, server_config: ServerConfig, server_manager: ServerManager):
        self.parent = parent
        self.server_config = server_config
        self.server_manager = server_manager
        self.properties_helper = ServerPropertiesHelper()
        self.result = None

        # 建立對話框
        self.dialog = tk.Toplevel(parent)
        self.dialog.withdraw()  # 先隱藏

        # 設定對話框
        self.setup_dialog()

        # 屬性值
        self.property_vars: dict[str, tk.StringVar] = {}
        self.property_widgets: dict[str, tk.Widget] = {}
        self._property_bool_vars: dict[str, tk.BooleanVar] = {}
        self._property_bool_bound: set[str] = set()
        self._property_value_cache: dict[str, str] = {}
        self._tab_content_frames: dict[str, ttk.Frame] = {}
        self._tab_canvases: dict[str, tk.Canvas] = {}
        self._tab_properties: dict[str, tuple[str, ...]] = {}
        self._tab_scroll_regions: dict[str, tuple[int, int, int, int]] = {}
        self._tab_render_positions: dict[str, int] = {}
        self._tab_rendering: set[str] = set()
        self._tab_render_job_attrs: dict[str, str] = {}
        self._materialized_tabs: set[str] = set()

        # 建立介面
        self.create_widgets()
        self.load_properties()

        # 統一設定視窗屬性：綁定圖示、螢幕置中、設為模態視窗
        UIUtils.setup_window_properties(
            window=self.dialog,
            parent=self.parent,
            width=int(800 * FontManager.get_scale_factor()),
            height=int(600 * FontManager.get_scale_factor()),
            bind_icon=True,
            center_on_parent=True,
            make_modal=True,
            delay_ms=250,
        )
        self.dialog.deiconify()  # 顯示

        # 顯示對話框
        self.show_dialog()

    def setup_dialog(self) -> None:
        """設定對話框"""
        self.dialog.title(f"伺服器設定 - {self.server_config.name}")
        min_width = int(1000 * FontManager.get_scale_factor())  # 1000 * DPI
        min_height = int(600 * FontManager.get_scale_factor())  # 600 * DPI
        self.dialog.minsize(min_width, min_height)
        self.dialog.resizable(True, True)

        # 應用主題背景顏色
        try:
            self.dialog.configure(bg=Colors.BG_PRIMARY[0])  # 淺色背景
        except Exception as e:
            logger.error(f"應用對話框主題失敗: {e}\n{traceback.format_exc()}")

    def create_widgets(self) -> None:
        """建立介面元件"""
        # 主框架
        main_frame = ttk.Frame(self.dialog)
        UIUtils.pack_main_frame(main_frame)

        # 標題
        title_label = ttk.Label(
            main_frame,
            text=f"🛠️ {self.server_config.name} - server.properties",
            font=FontManager.get_font("Microsoft JhengHei", FontSize.HEADING_MEDIUM, "bold"),
        )
        title_label.pack(pady=(0, FontManager.get_dpi_scaled_size(15)))
        style = ttk.Style()
        style.configure(
            "ServerProps.TNotebook.Tab",
            font=FontManager.get_font("Microsoft JhengHei", FontSize.INPUT, "bold"),
        )

        self.notebook = ttk.Notebook(main_frame, style="ServerProps.TNotebook")
        self.notebook.pack(fill="both", expand=True, pady=(0, FontManager.get_dpi_scaled_size(15)))

        self.create_property_tabs()

        # 按鈕框架
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x")

        # 按鈕
        button_width = int(100 * FontManager.get_scale_factor())
        button_height = int(32 * FontManager.get_scale_factor())
        button_font_size = int(18 * FontManager.get_scale_factor())

        ctk.CTkButton(
            button_frame,
            text="💾 儲存",
            command=self.save_properties,
            width=button_width,
            height=button_height,
            font=FontManager.get_font(family="Microsoft JhengHei", size=button_font_size, weight="bold"),
            **get_button_style("primary"),
        ).pack(side="right", padx=(FontManager.get_dpi_scaled_size(8), 0))

        ctk.CTkButton(
            button_frame,
            text="🔄 重設",
            command=self.reset_properties,
            width=button_width,
            height=button_height,
            font=FontManager.get_font(family="Microsoft JhengHei", size=button_font_size, weight="bold"),
            **get_button_style("warning"),
        ).pack(side="right", padx=(FontManager.get_dpi_scaled_size(8), 0))

        ctk.CTkButton(
            button_frame,
            text="❌ 取消",
            command=self.dialog.destroy,
            width=button_width,
            height=button_height,
            font=FontManager.get_font(family="Microsoft JhengHei", size=button_font_size, weight="bold"),
            **get_button_style("danger"),
        ).pack(side="right", padx=(FontManager.get_dpi_scaled_size(8), 0))

        # 說明標籤
        help_label = ctk.CTkLabel(
            button_frame,
            text="💡 將滑鼠移到設定項目上可查看詳細說明",
            font=FontManager.get_font(size=FontSize.INPUT),
            text_color=("gray60", "gray50"),
        )
        help_label.pack(side="left")

        # 官方說明連結
        link_label = ctk.CTkLabel(
            button_frame,
            text="【官方設定說明】",
            font=FontManager.get_font(size=FontSize.INPUT, underline=True),
            text_color=Colors.TEXT_LINK,
            cursor="hand2",
        )
        link_label.pack(side="left", padx=(5, 0))
        link_label.bind("<Button-1>", lambda _: UIUtils.open_external("https://zh.minecraft.wiki/w/Server.properties"))

    def _apply_scrollregion(self, canvas: tk.Canvas) -> None:
        """更新分頁 canvas 的捲動區域。"""
        try:
            if not canvas.winfo_exists():
                return
            bbox = canvas.bbox("all")
            if not bbox:
                return
            x0, y0, x1, y1 = bbox
            height = max(y1 - y0, canvas.winfo_height())
            region: tuple[int, int, int, int] = (x0, y0, x1, y0 + height)
            canvas_key = str(canvas)
            last_region = self._tab_scroll_regions.get(canvas_key)
            if region != last_region:
                canvas.configure(scrollregion=region)
                self._tab_scroll_regions[canvas_key] = region
        except Exception:
            return

    def _schedule_scrollregion_update(self, canvas: tk.Canvas) -> None:
        """合併排程 scrollregion 更新，避免連續重算。"""
        try:
            UIUtils.schedule_coalesced_idle(
                canvas,
                "_server_props_scroll_job",
                lambda c=canvas: self._apply_scrollregion(c),
            )
        except Exception as e:
            logger.exception(f"排程 scrollregion 更新失敗: {e}")

    def _compute_property_render_batch_size(self, total_props: int) -> int:
        """計算屬性控制項分段建構的批次大小。"""
        scale = max(1.0, float(FontManager.get_scale_factor()))
        base_batch = 16 if total_props <= 80 else 12
        return max(6, int(base_batch / scale))

    def _get_tab_render_job_attr(self, tab_name: str) -> str:
        """取得 tab 專用 render job attr 名稱。"""
        job_attr = self._tab_render_job_attrs.get(tab_name)
        if job_attr is not None:
            return job_attr
        job_attr = f"_server_props_render_job_{len(self._tab_render_job_attrs)}"
        self._tab_render_job_attrs[tab_name] = job_attr
        return job_attr

    def _schedule_tab_render_batch(self, tab_name: str) -> None:
        """排程下一批控制項建構。"""
        canvas = self._tab_canvases.get(tab_name)
        host_widget = canvas if canvas is not None else self.dialog
        UIUtils.schedule_debounce(
            host_widget,
            self._get_tab_render_job_attr(tab_name),
            1,
            lambda name=tab_name: self._render_tab_batch(name),
            owner=self,
        )

    def _render_tab_batch(self, tab_name: str) -> None:
        """分段建立單一分頁的控制項，降低單次 UI 阻塞時間。"""
        if tab_name in self._materialized_tabs:
            return

        content_frame = self._tab_content_frames.get(tab_name)
        properties = self._tab_properties.get(tab_name, ())
        if content_frame is None:
            self._tab_rendering.discard(tab_name)
            return
        try:
            if not content_frame.winfo_exists():
                self._tab_rendering.discard(tab_name)
                return
        except Exception:
            self._tab_rendering.discard(tab_name)
            return

        total_props = len(properties)
        if total_props <= 0:
            self._materialized_tabs.add(tab_name)
            self._tab_rendering.discard(tab_name)
            return

        start_index = self._tab_render_positions.get(tab_name, 0)
        if start_index >= total_props:
            self._materialized_tabs.add(tab_name)
            self._tab_rendering.discard(tab_name)
            return

        batch_size = self._compute_property_render_batch_size(total_props)
        end_index = min(total_props, start_index + batch_size)

        self.create_property_controls(content_frame, properties[start_index:end_index])
        self._tab_render_positions[tab_name] = end_index

        canvas = self._tab_canvases.get(tab_name)
        if canvas is not None:
            self._schedule_scrollregion_update(canvas)

        if end_index < total_props:
            self._schedule_tab_render_batch(tab_name)
            return

        self._materialized_tabs.add(tab_name)
        self._tab_rendering.discard(tab_name)

    def _cancel_tab_render_jobs(self) -> None:
        """取消所有分頁批次建構工作。"""
        for tab_name, job_attr in self._tab_render_job_attrs.items():
            canvas = self._tab_canvases.get(tab_name)
            host_widget = canvas if canvas is not None else self.dialog
            UIUtils.cancel_scheduled_job(host_widget, job_attr, owner=self)

    def _materialize_tab(self, tab_name: str) -> None:
        """延遲建立分頁內容，減少對話框初次開啟成本。"""
        if tab_name in self._materialized_tabs:
            return
        if tab_name in self._tab_rendering:
            return

        content_frame = self._tab_content_frames.get(tab_name)
        if content_frame is None:
            return

        self._tab_rendering.add(tab_name)
        self._tab_render_positions.setdefault(tab_name, 0)
        self._schedule_tab_render_batch(tab_name)

    def _on_tab_changed(self, _event=None) -> None:
        """切換分頁時才建立該頁控制項。"""
        try:
            tab_id = self.notebook.select()
            if not tab_id:
                return
            tab_name = str(self.notebook.tab(tab_id, "text") or "")
            if tab_name:
                self._materialize_tab(tab_name)
        except Exception as e:
            logger.exception(f"處理分頁切換失敗: {e}")

    def create_property_tabs(self) -> None:
        """建立屬性分頁，並自動補充未分類屬性到「其他」分頁。"""

        self._cancel_tab_render_jobs()
        self._tab_content_frames.clear()
        self._tab_canvases.clear()
        self._tab_properties.clear()
        self._tab_scroll_regions.clear()
        self._tab_render_positions.clear()
        self._tab_rendering.clear()
        self._tab_render_job_attrs.clear()
        self._materialized_tabs.clear()

        def _add_scrollable_tab(tab_name: str, properties: list[str] | tuple[str, ...]) -> None:
            tab_frame = ttk.Frame(self.notebook)
            self.notebook.add(tab_frame, text=tab_name)

            canvas = tk.Canvas(tab_frame, highlightthickness=0, bd=0)
            scrollbar = ttk.Scrollbar(tab_frame, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas)

            window_item = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

            def _request_scrollregion_update(_event=None, target_canvas=canvas) -> None:
                self._schedule_scrollregion_update(target_canvas)

            scrollable_frame.bind("<Configure>", _request_scrollregion_update)

            def _on_canvas_configure(event, target_canvas=canvas, target_window_item=window_item) -> None:
                try:
                    target_canvas.itemconfigure(target_window_item, width=max(1, int(event.width)))
                except Exception:
                    return
                self._schedule_scrollregion_update(target_canvas)

            canvas.bind("<Configure>", _on_canvas_configure)
            canvas.configure(yscrollcommand=scrollbar.set)
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            def _on_mousewheel(event, target_canvas=canvas):
                delta = int(getattr(event, "delta", 0))
                if delta == 0:
                    return
                units = int(-delta / 120)
                if units == 0:
                    units = -1 if delta > 0 else 1
                target_canvas.yview_scroll(units, "units")

            canvas.bind("<MouseWheel>", _on_mousewheel)
            scrollable_frame.bind("<MouseWheel>", _on_mousewheel)

            self._tab_content_frames[tab_name] = scrollable_frame
            self._tab_canvases[tab_name] = canvas
            self._tab_properties[tab_name] = tuple(properties)

            self._schedule_scrollregion_update(canvas)

        categories = self.properties_helper.get_property_categories()
        categorized_keys: set[str] = set()
        for props in categories.values():
            categorized_keys.update(props)

        all_properties = dict(self.server_config.properties or {})
        if hasattr(self.server_manager, "get_default_server_properties"):
            try:
                defaults = self.server_manager.get_default_server_properties()
                all_properties = {**defaults, **all_properties}
            except Exception as e:
                logger.exception(f"讀取預設 server.properties 失敗: {e}")

        all_keys = set(all_properties.keys())
        uncategorized_keys = sorted(all_keys - categorized_keys)

        for category_name, properties in categories.items():
            _add_scrollable_tab(category_name, properties)

        if uncategorized_keys:
            _add_scrollable_tab("其他", uncategorized_keys)

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed, add="+")
        self._on_tab_changed()

    def _get_or_create_property_var(self, prop_name: str) -> tk.StringVar:
        """取得或建立屬性對應的 StringVar，並同步到 cache。"""
        existing = self.property_vars.get(prop_name)
        if existing is not None:
            return existing

        var = tk.StringVar()
        cached_value = self._property_value_cache.get(prop_name)
        if cached_value is not None:
            var.set(cached_value)

        def _sync_cache(*_args) -> None:
            self._property_value_cache[prop_name] = var.get()

        var.trace_add("write", _sync_cache)
        self.property_vars[prop_name] = var
        return var

    def _create_property_control(self, parent, prop_name: str, before=None) -> ttk.Frame:
        """建立單一屬性控制項列。"""
        prop_frame = ttk.Frame(parent)
        pack_kwargs = {
            "fill": "x",
            "padx": FontManager.get_dpi_scaled_size(15),
            "pady": FontManager.get_dpi_scaled_size(8),
        }
        if before is not None:
            prop_frame.pack(before=before, **pack_kwargs)
        else:
            prop_frame.pack(**pack_kwargs)

        label = ttk.Label(
            prop_frame,
            text=f"{prop_name}:",
            font=FontManager.get_font("Microsoft JhengHei", FontSize.HEADING_SMALL, "bold"),
            cursor="hand2",
        )
        label.pack(anchor="w")

        def copy_name(_event, name=prop_name):
            self.dialog.clipboard_clear()
            self.dialog.clipboard_append(name)
            self.dialog.update_idletasks()

        label.bind("<Button-1>", copy_name)

        var = self._get_or_create_property_var(prop_name)
        widget = self.create_property_widget(prop_frame, prop_name, var)
        self.property_widgets[prop_name] = widget
        self.create_tooltip(widget, prop_name)
        return prop_frame

    def create_property_controls(self, parent, properties: tuple[str, ...] | list[str]) -> None:
        """批次建立屬性控制項（相容保留）。"""
        for prop_name in properties:
            self._create_property_control(parent, prop_name)

    def create_property_widget(self, parent, prop_name: str, var: tk.StringVar) -> tk.Widget:
        """根據屬性類型建立控制項"""
        if prop_name in self.BOOLEAN_PROPS:
            # 布林值
            bool_var = self._property_bool_vars.get(prop_name)
            if bool_var is None:
                bool_var = tk.BooleanVar()
                self._property_bool_vars[prop_name] = bool_var

            normalized = var.get().strip().lower() in ("true", "1", "yes", "on")
            if bool_var.get() != normalized:
                bool_var.set(normalized)

            if prop_name not in self._property_bool_bound:
                UIUtils.bind_bool_string_var(bool_var, var)
                self._property_bool_bound.add(prop_name)

            widget = ctk.CTkCheckBox(
                parent,
                variable=bool_var,
                text="啟用",
                font=FontManager.get_font(size=FontSize.INPUT),
                width=FontManager.get_dpi_scaled_size(180),
                height=FontManager.get_dpi_scaled_size(36),
            )
            widget.pack(anchor="w", pady=FontManager.get_dpi_scaled_size(3))

        elif prop_name in self.CHOICE_PROPS:
            # 選項（與建立伺服器頁面一致：CustomDropdown + VirtualList）
            widget = CustomDropdown(
                parent,
                variable=var,
                values=list(self.CHOICE_PROPS[prop_name]),
                width=Sizes.DROPDOWN_WIDTH,
                font_size=FontSize.MEDIUM,
                dropdown_font_size=FontSize.MEDIUM,
                state="readonly",
            )
            widget.pack(anchor="w", pady=FontManager.get_dpi_scaled_size(3))

        elif prop_name in self.RANGE_PROPS:
            # 數字範圍
            min_val, max_val = self.RANGE_PROPS[prop_name]
            widget = tk.Spinbox(
                parent,
                textvariable=var,
                from_=min_val,
                to=max_val,
                width=Sizes.SPINBOX_WIDTH_CHARS,
                font=FontManager.get_font("Microsoft JhengHei", FontSize.INPUT),
            )
            widget.pack(anchor="w")

        else:
            # 一般文字
            widget = ttk.Entry(
                parent,
                textvariable=var,
                font=FontManager.get_font("Microsoft JhengHei", FontSize.INPUT),
                width=Sizes.INPUT_FIELD_WIDTH_CHARS,
            )
            widget.pack(anchor="w")

        return widget

    def create_tooltip(self, widget, prop_name: str) -> None:
        """建立工具提示"""
        description = self.properties_helper.get_property_description(prop_name)
        UIUtils.bind_tooltip(
            widget,
            description,
            bg="lightyellow",
            fg="black",
            font=FontManager.get_font("Microsoft JhengHei", FontSize.INPUT),
            padx=8,
            pady=4,
            wraplength=FontManager.get_dpi_scaled_size(600),
            justify="left",
            borderwidth=1,
            relief="solid",
            offset_x=10,
            offset_y=10,
            show_delay_ms=300,
            auto_hide_ms=5000,
        )

    def load_properties(self) -> None:
        """載入屬性值"""
        # 首先嘗試從檔案載入現有屬性
        current_properties = self.server_manager.load_server_properties(self.server_config.name)
        # 如果沒有找到檔案，使用配置中的屬性
        if not current_properties:
            current_properties = dict(self.server_config.properties or {})
        # 獲取預設屬性
        default_properties = self.server_manager.get_default_server_properties()
        # 合併屬性（現有優先）
        all_properties = {**default_properties, **current_properties}
        self._property_value_cache = {prop: str(value) for prop, value in all_properties.items()}
        # 設定到控制項
        for prop_name, value in self._property_value_cache.items():
            if prop_name in self.property_vars:
                self.property_vars[prop_name].set(value)

    def _collect_property_values(self) -> dict[str, str]:
        """收集所有屬性值（含尚未建構的分頁）。"""
        properties: dict[str, str] = {}
        for prop_name, value in self._property_value_cache.items():
            cleaned = str(value).strip()
            if cleaned:
                properties[prop_name] = cleaned

        for prop_name, var in self.property_vars.items():
            value = var.get().strip()
            if value:
                properties[prop_name] = value
                self._property_value_cache[prop_name] = value
            else:
                properties.pop(prop_name, None)
                self._property_value_cache.pop(prop_name, None)

        return properties

    def save_properties(self) -> None:
        """儲存屬性"""
        try:
            properties = self._collect_property_values()

            # 驗證屬性值
            is_valid, errors = ServerPropertiesValidator.validate_properties(properties)
            if not is_valid:
                error_message = "以下屬性值無效：\n\n" + "\n".join(errors)
                UIUtils.show_error("驗證失敗", error_message, self.dialog)
                return

            # 更新伺服器屬性
            success = self.server_manager.update_server_properties(self.server_config.name, properties)

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
            logger.error(f"儲存時發生錯誤: {e}\n{traceback.format_exc()}")
            UIUtils.show_error("錯誤", f"儲存時發生錯誤: {e}", self.dialog)

    def show_dialog(self) -> None:
        """顯示對話框"""
        self.dialog.focus_set()
        self.dialog.wait_window()

    def reset_properties(self) -> None:
        """重設所有屬性為預設值"""
        if UIUtils.ask_yes_no_cancel("確認", "確定要重設所有屬性為預設值嗎？", self.dialog, show_cancel=False):
            default_properties = self.server_manager.get_default_server_properties()
            for prop_name, value in default_properties.items():
                value_str = str(value)
                self._property_value_cache[prop_name] = value_str
                if prop_name in self.property_vars:
                    self.property_vars[prop_name].set(value_str)
