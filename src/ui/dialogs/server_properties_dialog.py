"""
server.properties 設定對話框
提供視覺化的 server.properties 編輯介面
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any, ClassVar

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    LineEdit,
    Pivot,
    PopUpAniStackedWidget,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SpinBox,
    SubtitleLabel,
)

from src.core import ServerPropertiesStore
from src.models import ServerConfig
from src.ui import ModalMSFluentWindow
from src.utils import (
    Colors,
    PropertiesDocumentCodec,
    PropertiesSchema,
    ScrollableComboBox,
    Sizes,
    Spacing,
    TextState,
    UIUtils,
    get_logger,
    resolve_color,
)

logger = get_logger().bind(component="ServerPropertiesDialog")


class ServerPropertiesDialog(ModalMSFluentWindow):
    """server.properties 設定對話框"""

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

    def __init__(self, parent, server_config: ServerConfig, server_properties: ServerPropertiesStore):
        super().__init__(parent)
        self.server_config = server_config
        self.server_properties = server_properties
        self._default_properties: dict[str, str] = self._load_default_properties()
        self._snapshot = self.server_properties.read(self.server_config.name)
        current_properties = self._snapshot.properties if self._snapshot.readable else {}
        self._property_value_cache = {**self._default_properties, **current_properties}
        self._initial_values = dict(self._property_value_cache)

        self.setWindowTitle(f"🛠️ {self.server_config.name} - server.properties")
        self.title_label = SubtitleLabel(f"🛠️ {self.server_config.name} - server.properties", self.widget)
        self.viewLayout.addWidget(self.title_label)

        self.yesButton.hide()
        self.cancelButton.hide()

        self.property_vars: dict[str, Any] = {}
        self.setup_dialog()
        self.create_widgets()
        self.load_properties()

    def setup_dialog(self) -> None:
        """設定對話框的基礎尺寸與邊距"""
        self.widget.setMinimumSize(Sizes.SERVER_PROPERTIES_DIALOG_MIN_WIDTH, Sizes.SERVER_PROPERTIES_DIALOG_MIN_HEIGHT)
        self.viewLayout.setContentsMargins(Spacing.LARGE, Spacing.LARGE, Spacing.LARGE, Spacing.LARGE)

    def create_widgets(self) -> None:
        """建立對話框的所有 UI 元件，包含分頁導航、內容區域與底部操作按鈕"""
        self.pivot = Pivot(self)
        self.viewLayout.addWidget(self.pivot, 0, Qt.AlignmentFlag.AlignHCenter)
        self.stacked_widget = PopUpAniStackedWidget(self)
        self.viewLayout.addWidget(self.stacked_widget, 1)

        self.create_property_tabs()

        footer_layout = QHBoxLayout()
        self.viewLayout.addLayout(footer_layout)

        help_label = BodyLabel("💡 將滑鼠移到設定項目上可查看詳細說明", self)
        help_label.setStyleSheet(f"color: {resolve_color(Colors.TEXT_SECONDARY)};")
        footer_layout.addWidget(help_label)

        footer_layout.addStretch(1)

        btn_cancel = PushButton("❌ 取消", self.widget)
        btn_cancel.clicked.connect(self.reject)
        footer_layout.addWidget(btn_cancel)

        btn_reset = PushButton("🔄 重設", self.widget)
        btn_reset.clicked.connect(self.reset_properties)
        footer_layout.addWidget(btn_reset)

        btn_save = PrimaryPushButton("💾 儲存", self.widget)
        btn_save.clicked.connect(self.save_properties)
        footer_layout.addWidget(btn_save)

    def create_property_tabs(self) -> None:
        """根據屬性類別建立對應的分頁，並在每個分頁中生成屬性控制元件"""
        categories = PropertiesDocumentCodec.get_property_categories()
        categorized_keys: set[str] = set()
        for props in categories.values():
            categorized_keys.update(props)
        all_keys = set(self._property_value_cache)

        for category_name, properties in categories.items():
            visible_properties = [prop for prop in properties if prop in all_keys]
            if visible_properties:
                self._add_tab(category_name, visible_properties)

        uncategorized_keys = sorted(all_keys - categorized_keys)
        if uncategorized_keys:
            self._add_tab("其他", uncategorized_keys)

        if self.stacked_widget.count() > 0:
            self.stacked_widget.setCurrentIndex(0)

    def create_property_widget(self, parent, prop_name: str, var: TextState) -> QWidget:
        """
        根據屬性名稱與值，建立最適合的輸入元件

        Args:
            parent: 父元件
            prop_name: 屬性名稱
            var: 綁定的狀態變數

        Returns:
            建立好的輸入元件
        """
        if self._should_use_checkbox(prop_name, var.get()):
            widget = CheckBox("啟用", parent)

            normalized = var.get().strip().lower() in ("true", "1", "yes", "on")
            widget.setChecked(normalized)

            def _on_check_changed(checked):
                var.set("true" if checked else "false")

            widget.stateChanged.connect(lambda state: _on_check_changed(state == Qt.CheckState.Checked.value))

            def _on_var_changed(*_args):
                val = var.get().strip().lower() in ("true", "1", "yes", "on")
                if widget.isChecked() != val:
                    widget.setChecked(val)

            var.trace_add("write", _on_var_changed)

        elif prop_name in self.CHOICE_PROPS:
            widget = ScrollableComboBox(parent)
            items = list(self.CHOICE_PROPS[prop_name])
            widget.addItems(items)

            if var.get() in items:
                widget.setCurrentIndex(items.index(var.get()))

            def _on_combo_changed(idx):
                var.set(items[idx])

            widget.currentIndexChanged.connect(_on_combo_changed)

            def _on_var_changed(*_args):
                val = var.get()
                if val in items and widget.currentIndex() != items.index(val):
                    widget.setCurrentIndex(items.index(val))

            var.trace_add("write", _on_var_changed)

        elif prop_name in self.RANGE_PROPS:
            min_val, max_val = self.RANGE_PROPS[prop_name]
            widget = SpinBox(parent)
            widget.setRange(min_val, max_val)
            with suppress(ValueError):
                widget.setValue(int(var.get() or min_val))

            def _on_spin_changed(val):
                var.set(str(val))

            widget.valueChanged.connect(_on_spin_changed)

            def _on_var_changed(*_args):
                with suppress(ValueError):
                    val = int(var.get() or min_val)
                    if widget.value() != val:
                        widget.setValue(val)

            var.trace_add("write", _on_var_changed)

        else:
            widget = LineEdit(parent)
            widget.setMinimumWidth(Sizes.INPUT_WIDTH)
            widget.setText(var.get())

            def _on_text_changed(text):
                var.set(text)

            widget.textChanged.connect(_on_text_changed)

            def _on_var_changed(*_args):
                if widget.text() != var.get():
                    widget.setText(var.get())

            var.trace_add("write", _on_var_changed)

        return widget

    def load_properties(self) -> None:
        """從伺服器設定檔載入目前的屬性值並同步至 UI 變數"""
        for prop_name, value in self._property_value_cache.items():
            if prop_name in self.property_vars:
                self.property_vars[prop_name].set(value)

    def save_properties(self) -> None:
        """驗證目前所有屬性值，若通過則儲存至伺服器設定檔"""
        try:
            properties = self._collect_property_values()
            is_valid, errors = PropertiesSchema.validate_properties(properties)
            if not is_valid:
                error_message = "以下屬性值無效：\n\n" + "\n".join(errors)
                UIUtils.show_message("驗證失敗", error_message, self, message_level="error")
                return
            patch = {key: value for key, value in properties.items() if self._initial_values.get(key) != value}
            result = self.server_properties.update(
                self.server_config.name,
                patch,
                expected_revision=self._snapshot.revision,
            )
            if result.success:
                UIUtils.show_message(
                    "成功",
                    "伺服器屬性已儲存\n若伺服器正在執行，建議執行指令：/reload 或是重新啟動伺服器",
                    self,
                    message_level="info",
                )
                self.accept()
            else:
                title = "檔案已變更" if result.error_kind == "conflict" else "錯誤"
                UIUtils.show_message(title, result.message or "儲存伺服器屬性失敗", self, message_level="error")
        except Exception as e:
            UIUtils.show_message("錯誤", f"儲存時發生錯誤: {e}", self, message_level="error")

    def reset_properties(self) -> None:
        """將所有屬性值重設為預設值"""
        if UIUtils.ask_yes_no_cancel("確認", "確定要重設所有屬性為預設值嗎？", self, show_cancel=False):
            default_properties = PropertiesSchema.default_values()
            for prop_name, value in default_properties.items():
                value_str = str(value)
                self._property_value_cache[prop_name] = value_str
                if prop_name in self.property_vars:
                    self.property_vars[prop_name].set(value_str)

    def _load_default_properties(self) -> dict[str, str]:
        try:
            defaults = PropertiesSchema.default_values()
        except Exception as e:
            logger.exception(f"讀取預設 server.properties 失敗: {e}")
            return {}
        if not isinstance(defaults, dict):
            return {}
        return {str(key): "" if value is None else str(value) for key, value in defaults.items()}

    def _add_tab(self, tab_name: str, properties: list[str]) -> None:
        scroll_area = ScrollArea(self)
        scroll_area.setWidgetResizable(True)

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(Spacing.LARGE, Spacing.LARGE, Spacing.LARGE, Spacing.LARGE)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        for prop in properties:
            self._create_property_control(layout, prop, content_widget)

        scroll_area.setWidget(content_widget)

        self.stacked_widget.addWidget(scroll_area)
        self.pivot.addItem(tab_name, tab_name, lambda: self.stacked_widget.setCurrentWidget(scroll_area))

    def _is_boolean_string(self, value: Any) -> bool:
        normalized = str(value).strip().lower() if value is not None else ""
        return normalized in {"true", "false"}

    def _should_use_checkbox(self, prop_name: str, value: Any) -> bool:
        if PropertiesSchema.is_boolean_property(prop_name):
            return True
        if self._is_boolean_string(value):
            return True
        return self._is_boolean_string(self._default_properties.get(prop_name))

    def _get_or_create_property_var(self, prop_name: str) -> TextState:
        existing = self.property_vars.get(prop_name)
        if existing is not None:
            return existing
        var = TextState()
        cached_value = self._property_value_cache.get(prop_name)
        if cached_value is not None:
            var.set(cached_value)

        def _sync_cache(*_args) -> None:
            self._property_value_cache[prop_name] = var.get()

        var.trace_add("write", _sync_cache)
        self.property_vars[prop_name] = var
        return var

    def _create_property_control(self, layout: QVBoxLayout, prop_name: str, parent_widget: QWidget) -> None:
        prop_frame = QWidget(parent_widget)
        description = PropertiesDocumentCodec.get_property_descriptions().get(prop_name, f"未知屬性: {prop_name}")
        prop_frame.setToolTip(description)
        h_layout = QHBoxLayout(prop_frame)
        h_layout.setContentsMargins(0, 0, 0, 0)

        label = BodyLabel(f"{prop_name}:", prop_frame)
        label.setToolTip(description)
        h_layout.addWidget(label)

        var = self._get_or_create_property_var(prop_name)
        widget = self.create_property_widget(prop_frame, prop_name, var)
        widget.setToolTip(description)
        h_layout.addWidget(widget)
        h_layout.addStretch(1)

        layout.addWidget(prop_frame)

    def _collect_property_values(self) -> dict[str, str]:
        properties: dict[str, str] = {}
        for prop_name, value in self._property_value_cache.items():
            properties[prop_name] = "" if value is None else str(value)
        for prop_name, var in self.property_vars.items():
            value = var.get()
            properties[prop_name] = value
            self._property_value_cache[prop_name] = value
        return properties


__all__ = ["ServerPropertiesDialog"]
