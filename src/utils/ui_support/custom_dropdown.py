"""專案統一使用的 Fluent 下拉選單。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from .. import FontManager, FontSize, QtCore, QtWidgets, Sizes
from .qt_widgets import ComboBox as FluentComboBoxBase


class CustomDropdown(FluentComboBoxBase):
    """Fluent ComboBox 包裝器，提供專案統一 API。"""

    def __init__(
        self,
        parent,
        variable: Any | None = None,
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
        self.variable = variable
        self.values = [str(value) for value in values or []]
        self.command = command
        self.font_size = int(font_size)
        self.max_contents_length = max(4, int(max_contents_length))
        self.setFont(FontManager.get_font(size=self.font_size))
        self.setMinimumHeight(int(height))
        if width:
            self.setMinimumWidth(int(width))
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
        self.addItems(self.values)
        initial_value = str(self.variable.get() if self.variable and hasattr(self.variable, "get") else "")
        if initial_value:
            self.set(initial_value)
        elif self.values:
            if self.variable and hasattr(self.variable, "set"):
                self.variable.set(self.values[0])
            self.setCurrentIndex(0)
        self.currentTextChanged.connect(self._handle_changed)
        if self.variable and hasattr(self.variable, "changed"):
            self.variable.changed.connect(self._sync_from_state)
        self.configure(state=state, **kwargs)
        # 安裝滾輪事件攔截，使下拉選單展開時可用滾輪切換選項
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.installEventFilter(self)

    def eventFilter(self, watched: Any, event: Any) -> bool:
        """
        攔截滾輪事件，在下拉清單展開時切換選項而非捲動頁面。

        Args:
            watched: 事件來源物件。
            event: Qt 事件物件。

        Returns:
            True 表示事件已被處理，False 表示事件未被處理。
        """
        if watched is self and event.type() == QtCore.QEvent.Type.Wheel:
            popup_view = getattr(self, "view", None)
            if popup_view is not None and callable(popup_view):
                popup_view = popup_view()
            if popup_view is not None and popup_view.isVisible():
                delta = event.angleDelta().y()
                current = self.currentIndex()
                count = self.count()
                if delta > 0 and current > 0:
                    self.setCurrentIndex(current - 1)
                elif delta < 0 and current < count - 1:
                    self.setCurrentIndex(current + 1)
            return True
        return super().eventFilter(watched, event)

    def _sync_from_state(self, value: object) -> None:
        text = str(value or "")
        if text and self.currentText() != text:
            self.set(text)

    def _handle_changed(self, value: str) -> None:
        if (
            self.variable
            and hasattr(self.variable, "get")
            and self.variable.get() != value
            and hasattr(self.variable, "set")
        ):
            self.variable.set(value)
        if self.command is not None:
            self.command(value)

    def get(self) -> str:
        """
        取得目前選取值。

        Returns:
            目前選取的文字。
        """
        return self.currentText()

    def set(self, value: str) -> None:
        """
        設定目前選取值。

        Args:
            value: 要選取或加入的文字。
        """
        text = str(value)
        index = self.findText(text)
        if index < 0:
            self.addItem(text)
            self.values.append(text)
            index = self.findText(text)
        self.setCurrentIndex(index)
        if (
            self.variable
            and hasattr(self.variable, "get")
            and self.variable.get() != text
            and hasattr(self.variable, "set")
        ):
            self.variable.set(text)

    def configure(self, **kwargs: Any) -> None:
        """
        更新選單設定。

        Args:
            **kwargs: 支援 values、command、font_size、font、width、height、state。
        """
        if "values" in kwargs:
            self.values = [str(value) for value in kwargs.pop("values")]
            self.blockSignals(True)
            self.clear()
            self.addItems(self.values)
            self.blockSignals(False)
            if self.values:
                target = str(self.variable.get() if self.variable and hasattr(self.variable, "get") else self.values[0])
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
        if "state" in kwargs:
            state = str(kwargs.pop("state"))
            self.setEnabled(state not in {"disabled", "readonly_disabled"})
        kwargs.pop("dropdown_font_size", None)
        kwargs.pop("max_dropdown_height", None)
        kwargs.pop("max_visible_items", None)

    config = configure

    def attach(self, **kwargs: Any) -> None:
        """
        加入父容器的線性 Qt 版面。

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
        """
        取得設定值。

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
