"""專案統一使用的原生 Qt 下拉選單。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from ..utils import FontSize, Sizes
from ..utils.ui_support.qt_runtime import QtCore, QtGui, QtWidgets, ValueState
from . import FontManager
from .ui_config import NativeQtStyle


class CustomDropdown(QtWidgets.QComboBox):
    """淺色原生 Qt QComboBox。"""

    def __init__(
        self,
        parent,
        variable: ValueState | None = None,
        values: list[str] | None = None,
        command: Callable[[str], Any] | None = None,
        width: int = Sizes.DROPDOWN_WIDTH,
        height: int = Sizes.DROPDOWN_HEIGHT,
        font_size: int = FontSize.MEDIUM,
        state: str = "normal",
        max_contents_length: int = 24,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent)
        self.variable = variable or ValueState("")
        self.values = [str(value) for value in values or []]
        self.command = command
        self.font_size = int(font_size)
        self.max_contents_length = max(4, int(max_contents_length))
        self.setEditable(False)
        self.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.setFont(FontManager.get_font(size=self.font_size))
        self.setMinimumHeight(int(height))
        if width:
            self.setMinimumWidth(int(width))
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.setStyleSheet(NativeQtStyle.custom_dropdown)
        self._set_minimum_contents_length(self.values)
        self.addItems(self.values)
        initial_value = str(self.variable.get() or "")
        if initial_value:
            self.set(initial_value)
        elif self.values:
            self.variable.set(self.values[0])
            self.setCurrentIndex(0)
        self.currentTextChanged.connect(self._handle_changed)
        self.variable.changed.connect(self._sync_from_state)
        self.configure(state=state, **kwargs)

    def paintEvent(self, event) -> None:
        """
        自訂繪製下拉箭頭以確保在不同平台和樣式下都能保持一致的外觀。

        Args:
            event: Qt 的繪製事件。
        """
        super().paintEvent(event)
        if self.width() <= 0 or self.height() <= 0:
            return
        painter = QtGui.QPainter(self)
        try:
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            if self.isEnabled():
                arrow_color = self.palette().color(QtGui.QPalette.ColorRole.Text)
            else:
                arrow_color = self.palette().color(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.Text)
            painter.setBrush(arrow_color)
            arrow_width = max(8, int(self.height() * 0.36))
            arrow_height = max(5, int(self.height() * 0.2))
            center_x = self.width() - max(11, int(self.height() * 0.5))
            center_y = self.height() // 2 + 1
            arrow = QtGui.QPolygon(
                [
                    QtCore.QPoint(center_x - arrow_width // 2, center_y - arrow_height // 2),
                    QtCore.QPoint(center_x + arrow_width // 2, center_y - arrow_height // 2),
                    QtCore.QPoint(center_x, center_y + arrow_height // 2),
                ]
            )
            painter.drawPolygon(arrow)
        finally:
            painter.end()

    def _set_minimum_contents_length(self, values: list[Any]) -> None:
        longest = max((len(str(value)) for value in values), default=4)
        self.setMinimumContentsLength(max(4, min(longest, self.max_contents_length)))

    def _sync_from_state(self, value: object) -> None:
        text = str(value or "")
        if text and self.currentText() != text:
            self.set(text)

    def _handle_changed(self, value: str) -> None:
        if self.variable.get() != value:
            self.variable.set(value)
        if self.command is not None:
            self.command(value)

    def get(self) -> str:
        """取得目前選取值。

        Returns:
            目前選取的文字。
        """
        return self.currentText()

    def set(self, value: str) -> None:
        """設定目前選取值。

        Args:
            value: 要選取或加入的文字。
        """
        text = str(value)
        index = self.findText(text)
        if index < 0:
            self.addItem(text)
            self.values.append(text)
            self._set_minimum_contents_length(self.values)
            index = self.findText(text)
        self.setCurrentIndex(index)
        if self.variable.get() != text:
            self.variable.set(text)

    def configure(self, **kwargs: Any) -> None:
        """更新選單設定。

        Args:
            **kwargs: 支援 values、command、font_size、font、width、height、state。
        """
        if "values" in kwargs:
            self.values = [str(value) for value in kwargs.pop("values")]
            self.blockSignals(True)
            self.clear()
            self.addItems(self.values)
            self.blockSignals(False)
            self._set_minimum_contents_length(self.values)
            if self.values:
                target = str(self.variable.get() or self.values[0])
                self.set(target if target in self.values else self.values[0])
        if "command" in kwargs:
            self.command = kwargs.pop("command")
        if "font_size" in kwargs:
            self.font_size = int(kwargs.pop("font_size"))
            self.setFont(FontManager.get_font(size=self.font_size))
        if "font" in kwargs:
            self.setFont(kwargs.pop("font"))
        if "width" in kwargs:
            self.setMinimumWidth(int(kwargs.pop("width")))
        if "height" in kwargs:
            self.setMinimumHeight(int(kwargs.pop("height")))
        if "max_contents_length" in kwargs:
            self.max_contents_length = max(4, int(kwargs.pop("max_contents_length")))
            self._set_minimum_contents_length(self.values)
        if "state" in kwargs:
            state = str(kwargs.pop("state"))
            self.setEnabled(state not in {"disabled", "readonly_disabled"})
        kwargs.pop("dropdown_font_size", None)
        kwargs.pop("max_dropdown_height", None)
        kwargs.pop("max_visible_items", None)

    config = configure

    def attach(self, **kwargs: Any) -> None:
        """加入父容器的線性 Qt 版面。

        Args:
            **kwargs: 版面選項，例如 side、fill、expand、anchor。
        """
        parent = self.parentWidget()
        if parent is None:
            return
        side = str(kwargs.get("side", "") or "").lower()
        layout = parent.layout()
        if layout is None:
            layout = QtWidgets.QHBoxLayout(parent) if side in {"left", "right"} else QtWidgets.QVBoxLayout(parent)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)
        if kwargs.get("expand") or str(kwargs.get("fill", "")).lower() in {"x", "both"}:
            self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, self.sizePolicy().verticalPolicy())
        alignment = QtCore.Qt.AlignmentFlag(0)
        anchor = str(kwargs.get("anchor", "") or "").lower()
        if anchor in {"w", "left"}:
            alignment = QtCore.Qt.AlignmentFlag.AlignLeft
        elif anchor in {"e", "right"}:
            alignment = QtCore.Qt.AlignmentFlag.AlignRight
        cast(QtWidgets.QBoxLayout, layout).addWidget(self, 1 if kwargs.get("expand") else 0, alignment)

    def cget(self, key: str) -> Any:
        """取得設定值。

        Args:
            key: 要讀取的設定鍵。

        Returns:
            設定值；未知鍵回傳 None。
        """
        if key == "values":
            return self.values
        if key == "font_size":
            return self.font_size
        if key == "state":
            return "normal" if self.isEnabled() else "disabled"
        return None
