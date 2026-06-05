"""server.properties 設定對話框
提供視覺化的 server.properties 編輯介面
"""

import traceback
from typing import Any, ClassVar

from ..core import ServerConfig, ServerManager
from ..utils import (
    Colors,
    FontSize,
    ServerPropertiesHelper,
    ServerPropertiesValidator,
    Sizes,
    Spacing,
    UIUtils,
    get_button_style,
    get_logger,
)
from ..utils.ui_support import qt_widgets as qt
from . import CustomDropdown, DialogUtils, FontManager
from .ui_config import NativeQtStyle

logger = get_logger().bind(component="ServerPropertiesDialog")


class ServerPropertiesDialog:
    """
    server.properties 設定對話框
    提供視覺化的 server.properties 編輯介面
    """

    CHOICE_PROPS: ClassVar[dict[str, tuple[str, ...]]] = {
        "gamemode": ("survival", "creative", "adventure", "spectator"),
        "difficulty": ("peaceful", "easy", "normal", "hard"),
        "level-type": (
            "minecraft:normal",
            "minecraft:flat",
            "minecraft:large_biomes",
            "minecraft:amplified",
            "minecraft:single_biome_surface",
        ),
        "region-file-compression": ("deflate", "lz4", "none"),
    }
    RANGE_PROPS: ClassVar[dict[str, tuple[int, int]]] = {
        "server-port": (1, 65534),
        "max-players": (0, 2147483647),
        "max-world-size": (1, 29999984),
        "spawn-protection": (0, 2147483647),
        "view-distance": (3, 32),
        "simulation-distance": (3, 32),
        "op-permission-level": (0, 4),
        "function-permission-level": (1, 4),
        "rcon.port": (1, 65534),
        "query.port": (1, 65534),
        "entity-broadcast-range-percentage": (10, 1000),
        "network-compression-threshold": (-1, 2147483647),
        "max-tick-time": (-1, 2147483647),
        "rate-limit": (0, 2147483647),
        "player-idle-timeout": (0, 2147483647),
        "pause-when-empty-seconds": (-2147483648, 2147483647),
        "max-chained-neighbor-updates": (-2147483648, 2147483647),
        "management-server-port": (0, 65535),
        "status-heartbeat-interval": (0, 2147483647),
        "text-filtering-version": (0, 1),
    }

    def __init__(self, parent, server_config: ServerConfig, server_manager: ServerManager):
        self.parent = parent
        self.server_config = server_config
        self.server_manager = server_manager
        self.properties_helper = ServerPropertiesHelper()
        self._default_properties: dict[str, str] = self._load_default_properties()
        self.result = None
        self.dialog = DialogUtils.create_toplevel_dialog(
            parent,
            f"伺服器設定 - {server_config.name}",
            width=Sizes.SERVER_PROPERTIES_DIALOG_WIDTH,
            height=Sizes.SERVER_PROPERTIES_DIALOG_HEIGHT,
            center_on_parent=True,
            make_modal=True,
            delay_ms=250,
        )
        self.setup_dialog()
        self.property_vars: dict[str, Any] = {}
        self.property_widgets: dict[str, Any] = {}
        self._property_bool_vars: dict[str, Any] = {}
        self._property_bool_bound: set[str] = set()
        self._property_value_cache: dict[str, str] = {}
        self._tab_content_frames: dict[str, Any] = {}
        self._tab_canvases: dict[str, Any] = {}
        self._tab_properties: dict[str, tuple[str, ...]] = {}
        self._tab_render_positions: dict[str, int] = {}
        self._tab_rendering: set[str] = set()
        self._tab_render_job_attrs: dict[str, str] = {}
        self._materialized_tabs: set[str] = set()
        self.create_widgets()
        self.load_properties()
        self.show_dialog()

    def _load_default_properties(self) -> dict[str, str]:
        """載入伺服器預設設定，供欄位型別與重設流程共用。"""
        if not hasattr(self.server_manager, "get_default_server_properties"):
            return {}
        try:
            defaults = self.server_manager.get_default_server_properties()
        except Exception as e:
            logger.exception(f"讀取預設 server.properties 失敗: {e}")
            return {}
        if not isinstance(defaults, dict):
            return {}
        return {str(key): "" if value is None else str(value) for key, value in defaults.items()}

    def setup_dialog(self) -> None:
        """設定對話框"""
        self.dialog.setWindowTitle(f"伺服器設定 - {self.server_config.name}")
        min_width = Sizes.SERVER_PROPERTIES_DIALOG_MIN_WIDTH
        min_height = Sizes.SERVER_PROPERTIES_DIALOG_MIN_HEIGHT
        self.dialog.setMinimumSize(min_width, min_height)
        try:
            self.dialog.setStyleSheet(NativeQtStyle.server_properties_dialog)
        except Exception as e:
            logger.error(f"應用對話框主題失敗: {e}\n{traceback.format_exc()}")

    def create_widgets(self) -> None:
        """建立介面元件"""
        main_frame = qt.Frame(self.dialog)
        UIUtils.pack_main_frame(main_frame)
        title_label = qt.Label(
            main_frame,
            text=f"🛠️ {self.server_config.name} - server.properties",
            font=FontManager.get_font("Microsoft JhengHei", FontSize.HEADING_MEDIUM, "bold"),
        )
        title_label.setObjectName("ServerPropertiesTitle")
        title_label.attach(pady=(0, Spacing.LARGE))
        self.notebook = qt.Notebook(main_frame, style="ServerProps.TNotebook")
        self.notebook.attach(fill="both", expand=True, pady=(0, Spacing.LARGE))
        self.create_property_tabs()
        footer_frame = qt.Frame(main_frame, fg_color="transparent")
        footer_frame.attach(fill="x")
        info_frame = qt.Frame(footer_frame, fg_color="transparent")
        info_frame.attach(side="left")
        button_frame = qt.Frame(footer_frame, fg_color="transparent")
        button_frame.attach(side="right")
        button_width = Sizes.BUTTON_WIDTH_SMALL
        button_height = 24
        button_font_size = FontSize.LARGE
        help_label = qt.Label(
            info_frame,
            text="💡 將滑鼠移到設定項目上可查看詳細說明",
            font=FontManager.get_font(size=FontSize.INPUT),
            text_color=Colors.TEXT_SECONDARY,
        )
        help_label.attach(side="left")
        link_label = qt.Label(
            info_frame,
            text="【官方設定說明】",
            font=FontManager.get_font(size=FontSize.INPUT, underline=True),
            text_color=Colors.TEXT_LINK,
            cursor="hand2",
        )
        link_label.attach(side="left", padx=(Spacing.TINY, 0))
        link_label.connect_event(
            "mouse_left_press", lambda _: UIUtils.open_external("https://zh.minecraft.wiki/w/Server.properties")
        )

        button_specs = [
            ("❌ 取消", self.dialog.destroy, get_button_style("danger")),
            ("🔄 重設", self.reset_properties, get_button_style("warning")),
            ("💾 儲存", self.save_properties, get_button_style("primary")),
        ]
        button_gap = max(1, Spacing.XS - 1)
        for index, (text, command, style_config) in enumerate(button_specs):
            padding = (0, 0) if index == len(button_specs) - 1 else (0, button_gap)
            qt.Button(
                button_frame,
                text=text,
                command=command,
                width=button_width,
                height=button_height,
                font=FontManager.get_font(family="Microsoft JhengHei", size=button_font_size, weight="bold"),
                **style_config,
            ).attach(side="left", padx=padding)

    def _compute_property_render_batch_size(self, total_props: int) -> int:
        """計算屬性控制項分段建構的批次大小。"""
        return 16 if total_props <= 80 else 12

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
            if not content_frame.is_alive():
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
        self._tab_render_positions.clear()
        self._tab_rendering.clear()
        self._tab_render_job_attrs.clear()
        self._materialized_tabs.clear()

        def _add_scrollable_tab(tab_name: str, properties: list[str] | tuple[str, ...]) -> None:
            tab_frame = qt.Frame(self.notebook)
            self.notebook.add(tab_frame, text=tab_name)
            scroll_area = qt.ScrollableFrame(tab_frame)
            scroll_area.attach(fill="both", expand=True)
            layout = scroll_area._ensure_layout("vbox")
            layout.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignTop | qt.QtCore.Qt.AlignmentFlag.AlignLeft)
            self._tab_content_frames[tab_name] = scroll_area
            self._tab_canvases[tab_name] = scroll_area
            self._tab_properties[tab_name] = tuple(properties)

        categories = self.properties_helper.get_property_categories()
        categorized_keys: set[str] = set()
        for props in categories.values():
            categorized_keys.update(props)
        all_properties = dict(self._default_properties)
        all_properties.update(self.server_config.properties or {})
        all_keys = set(all_properties.keys())
        for category_name, properties in categories.items():
            visible_properties = [prop for prop in properties if prop in all_keys]
            if visible_properties:
                _add_scrollable_tab(category_name, visible_properties)
        uncategorized_keys = sorted(all_keys - categorized_keys)
        if uncategorized_keys:
            _add_scrollable_tab("其他", uncategorized_keys)
        self.notebook.connect_event("tab_changed", self._on_tab_changed, append=True)
        self._on_tab_changed()

    @staticmethod
    def _is_boolean_string(value: Any) -> bool:
        normalized = str(value).strip().lower() if value is not None else ""
        return normalized in {"true", "false"}

    def _should_use_checkbox(self, prop_name: str, value: Any) -> bool:
        if ServerPropertiesValidator.is_boolean_property(prop_name):
            return True
        if self._is_boolean_string(value):
            return True
        return self._is_boolean_string(self._default_properties.get(prop_name))

    def _get_or_create_property_var(self, prop_name: str) -> Any:
        """取得或建立屬性對應的 TextState，並同步到 cache。"""
        existing = self.property_vars.get(prop_name)
        if existing is not None:
            return existing
        var = qt.TextState()
        cached_value = self._property_value_cache.get(prop_name)
        if cached_value is not None:
            var.set(cached_value)

        def _sync_cache(*_args) -> None:
            self._property_value_cache[prop_name] = var.get()

        var.trace_add("write", _sync_cache)
        self.property_vars[prop_name] = var
        return var

    def _create_property_control(self, parent, prop_name: str, before=None) -> Any:
        """建立單一屬性控制項列。"""
        prop_frame = qt.Frame(parent)
        pack_kwargs = {
            "fill": "x",
            "padx": Spacing.LARGE,
            "pady": 6,
        }
        if before is not None:
            prop_frame.attach(before=before, **pack_kwargs)
        else:
            prop_frame.attach(**pack_kwargs)
        prop_frame.setSizePolicy(
            qt.QtWidgets.QSizePolicy.Policy.Expanding,
            qt.QtWidgets.QSizePolicy.Policy.Maximum,
        )
        label = qt.Label(
            prop_frame,
            text=f"{prop_name}:",
            font=FontManager.get_font("Microsoft JhengHei", FontSize.HEADING_SMALL, "bold"),
            cursor="hand2",
        )
        label.attach(anchor="w")

        def copy_name(_event, name=prop_name):
            app = qt.ensure_app()
            if app is not None:
                try:
                    app.clipboard().setText(name)
                    app.processEvents()
                except Exception as e:
                    logger.exception(f"複製屬性名稱失敗: {e}")

        label.connect_event("mouse_left_press", copy_name)
        var = self._get_or_create_property_var(prop_name)
        widget = self.create_property_widget(prop_frame, prop_name, var)
        self.property_widgets[prop_name] = widget
        self.create_tooltip(prop_frame, prop_name)
        self.create_tooltip(label, prop_name)
        self.create_tooltip(widget, prop_name)
        return prop_frame

    def create_property_controls(self, parent, properties: tuple[str, ...] | list[str]) -> None:
        """批次建立屬性控制項（相容保留）。

        Args:
            parent: 父容器。
            properties: 要建立控制項的屬性名稱列表。
        """
        for prop_name in properties:
            self._create_property_control(parent, prop_name)

    def create_property_widget(self, parent, prop_name: str, var: Any) -> Any:
        """根據屬性類型建立控制項。

        Args:
            parent: 父容器。
            prop_name: 屬性名稱。
            var: 綁定的字串變數。

        Returns:
            建立完成的 widget。
        """
        widget: Any
        if self._should_use_checkbox(prop_name, var.get()):
            bool_var = self._property_bool_vars.get(prop_name)
            if bool_var is None:
                bool_var = qt.BoolState()
                self._property_bool_vars[prop_name] = bool_var
            normalized = var.get().strip().lower() in ("true", "1", "yes", "on")
            if bool_var.get() != normalized:
                bool_var.set(normalized)
            if prop_name not in self._property_bool_bound:
                UIUtils.sync_bool_string_state(bool_var, var)
                self._property_bool_bound.add(prop_name)
            widget = qt.CheckBox(
                parent,
                variable=bool_var,
                text="啟用",
                font=FontManager.get_font(size=FontSize.INPUT),
                width=Sizes.SERVER_PROPERTY_BOOL_WIDTH,
                height=Sizes.SERVER_PROPERTY_BOOL_HEIGHT,
            )
            widget.attach(anchor="w", pady=Spacing.TINY)
        elif prop_name in self.CHOICE_PROPS:
            widget = CustomDropdown(
                parent,
                variable=var,
                values=list(self.CHOICE_PROPS[prop_name]),
                width=Sizes.DROPDOWN_WIDTH,
                font_size=FontSize.MEDIUM,
                dropdown_font_size=FontSize.MEDIUM,
                state="readonly",
            )
            widget.attach(anchor="w", pady=Spacing.TINY)
        elif prop_name in self.RANGE_PROPS:
            min_val, max_val = self.RANGE_PROPS[prop_name]
            widget = qt.Spinbox(
                parent,
                textvariable=var,
                from_=min_val,
                to=max_val,
                width=Sizes.SPINBOX_WIDTH_CHARS,
                font=FontManager.get_font("Microsoft JhengHei", FontSize.INPUT),
                fg_color=Colors.BG_PRIMARY,
                border_color=Colors.BORDER_LIGHT,
                corner_radius=Sizes.INPUT_CORNER_RADIUS,
            )
            widget.attach(anchor="w")
        else:
            widget = qt.Entry(
                parent,
                textvariable=var,
                font=FontManager.get_font("Microsoft JhengHei", FontSize.INPUT),
                width=Sizes.SERVER_PROPERTY_TEXT_INPUT_WIDTH,
                fg_color=Colors.BG_PRIMARY,
                border_color=Colors.BORDER_LIGHT,
                corner_radius=Sizes.INPUT_CORNER_RADIUS,
            )
            widget.attach(anchor="w")
        return widget

    def create_tooltip(self, widget, prop_name: str) -> None:
        """建立工具提示。

        Args:
            widget: 要綁定提示的元件。
            prop_name: 屬性名稱。
        """
        description = self.properties_helper.get_property_description(prop_name)
        UIUtils.attach_tooltip(
            widget,
            description,
            bg="lightyellow",
            fg="black",
            font=FontManager.get_font("Microsoft JhengHei", FontSize.INPUT),
            padx=Spacing.SMALL,
            pady=Spacing.XS,
            wraplength=Sizes.SERVER_PROPERTIES_DIALOG_WIDTH,
            justify="left",
            borderwidth=2,
            relief="solid",
            offset_x=10,
            offset_y=10,
            show_delay_ms=300,
            auto_hide_ms=5000,
        )

    def load_properties(self) -> None:
        """載入屬性值"""
        current_properties = self.server_manager.load_server_properties(self.server_config.name)
        if not current_properties:
            current_properties = dict(self.server_config.properties or {})
        default_properties = self.server_manager.get_default_server_properties()
        all_properties = {**default_properties, **current_properties}
        self._property_value_cache = {prop: str(value) for prop, value in all_properties.items()}
        for prop_name, value in self._property_value_cache.items():
            if prop_name in self.property_vars:
                self.property_vars[prop_name].set(value)

    def _collect_property_values(self) -> dict[str, str]:
        """收集所有屬性值（含尚未建構的分頁）。"""
        properties: dict[str, str] = {}
        for prop_name, value in self._property_value_cache.items():
            properties[prop_name] = "" if value is None else str(value)
        for prop_name, var in self.property_vars.items():
            value = var.get()
            properties[prop_name] = value
            self._property_value_cache[prop_name] = value
        logger.debug(
            f"收集 server.properties 表單值完成: server={self.server_config.name}, property_count={len(properties)}"
        )
        return properties

    def save_properties(self) -> None:
        """儲存屬性"""
        try:
            properties = self._collect_property_values()
            is_valid, errors = ServerPropertiesValidator.validate_properties(properties)
            if not is_valid:
                error_message = "以下屬性值無效：\n\n" + "\n".join(errors)
                UIUtils.show_error("驗證失敗", error_message, self.dialog)
                return
            logger.info(f"開始儲存 server.properties 對話框內容: server={self.server_config.name}")
            success = self.server_manager.update_server_properties(self.server_config.name, properties)
            if success:
                UIUtils.show_info(
                    "成功", "伺服器屬性已儲存\n若伺服器正在運行建議執行指令：/reload或是重新運行伺服器", self.dialog
                )
                self.dialog.destroy()
            else:
                UIUtils.show_error("錯誤", "儲存伺服器屬性失敗", self.dialog)
        except Exception as e:
            logger.error(f"儲存時發生錯誤: {e}\n{traceback.format_exc()}")
            UIUtils.show_error("錯誤", f"儲存時發生錯誤: {e}", self.dialog)

    def show_dialog(self) -> None:
        """顯示對話框"""
        self.dialog.setFocus()
        self.dialog.activateWindow()
        self.dialog.exec()

    def reset_properties(self) -> None:
        """重設所有屬性為預設值"""
        if UIUtils.ask_yes_no_cancel("確認", "確定要重設所有屬性為預設值嗎？", self.dialog, show_cancel=False):
            default_properties = self.server_manager.get_default_server_properties()
            for prop_name, value in default_properties.items():
                value_str = str(value)
                self._property_value_cache[prop_name] = value_str
                if prop_name in self.property_vars:
                    self.property_vars[prop_name].set(value_str)
