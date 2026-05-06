"""原生 PySide6 元件."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from PySide6 import QtCore, QtGui, QtWidgets

from .. import get_logger
from .qt_runtime import ValueState, is_qobject_alive

logger = get_logger().bind(component="QtWidgets")


END = "end"
NORMAL = "normal"
DISABLED = "disabled"
HORIZONTAL = "horizontal"
VERTICAL = "vertical"
LEFT = "left"
RIGHT = "right"
TOP = "top"
BOTTOM = "bottom"
BOTH = "both"
X = "x"
Y = "y"
INVALID_MODEL_INDEX = QtCore.QModelIndex()


def ensure_app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv[:1])
    return app


def is_dark_color_scheme() -> bool:
    """Return whether the active Qt palette/color scheme is dark."""
    app = cast(Any, QtWidgets.QApplication.instance())
    if app is None:
        return False
    with context_suppress():
        scheme = app.styleHints().colorScheme()
        if scheme == QtCore.Qt.ColorScheme.Dark:
            return True
        if scheme == QtCore.Qt.ColorScheme.Light:
            return False
    window_color = app.palette().color(QtGui.QPalette.ColorRole.Window)
    return window_color.lightness() < 128


def set_color_scheme(mode: str) -> None:
    """Set Qt color scheme hint: Light, Dark, or System/Auto."""
    app = ensure_app()
    normalized = str(mode or "System").strip().lower()
    scheme = QtCore.Qt.ColorScheme.Unknown
    if normalized == "dark":
        scheme = QtCore.Qt.ColorScheme.Dark
    elif normalized == "light":
        scheme = QtCore.Qt.ColorScheme.Light
    with context_suppress():
        app.styleHints().setColorScheme(scheme)


def is_alive(widget: Any) -> bool:
    """Return whether a wrapper or native Qt object is still usable."""
    if widget is None:
        return False
    checker = getattr(widget, "is_alive", None)
    if callable(checker):
        with context_suppress():
            return bool(checker())
    if isinstance(widget, QtCore.QObject):
        return is_qobject_alive(widget)
    return True


def _native_parent(parent: Any) -> Any:
    return getattr(parent, "_qt_widget", parent)


def _qt_class(name: str) -> Any:
    return getattr(QtWidgets, name)


def _is_qt_instance(widget: Any, *class_names: str) -> bool:
    return any(isinstance(widget, _qt_class(class_name)) for class_name in class_names)


def _style_selector(widget: Any) -> str:
    object_name = widget.objectName() if hasattr(widget, "objectName") else ""
    if not object_name and hasattr(widget, "setObjectName"):
        object_name = f"msm_{id(widget)}"
        widget.setObjectName(object_name)
    return f"#{object_name}" if object_name else widget.__class__.__name__


def _event_position(event: Any) -> tuple[int, int, int, int]:
    if event is None:
        return (0, 0, 0, 0)
    point = event.position() if hasattr(event, "position") else event.pos() if hasattr(event, "pos") else None
    global_point = (
        event.globalPosition()
        if hasattr(event, "globalPosition")
        else event.globalPos()
        if hasattr(event, "globalPos")
        else None
    )
    x = int(point.x()) if point is not None else 0
    y = int(point.y()) if point is not None else 0
    x_root = int(global_point.x()) if global_point is not None else x
    y_root = int(global_point.y()) if global_point is not None else y
    return (x, y, x_root, y_root)


def _color(value: Any) -> str:
    if isinstance(value, tuple):
        index = 1 if is_dark_color_scheme() and len(value) > 1 else 0
        return str(value[index])
    if value in (None, "transparent"):
        return "transparent"
    return str(value)


def _font(value: Any = None):
    if hasattr(value, "font"):
        value = value.font
    if isinstance(value, QtGui.QFont):
        return value
    family = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.GeneralFont).family()
    size = 12
    weight = QtGui.QFont.Weight.Normal
    underline = False
    if isinstance(value, tuple):
        if len(value) >= 1 and value[0]:
            family = str(value[0])
        if len(value) >= 2 and value[1]:
            size = int(value[1])
        if len(value) >= 3 and str(value[2]).lower() == "bold":
            weight = QtGui.QFont.Weight.Bold
    elif isinstance(value, dict):
        family = str(value.get("family", family))
        size = int(value.get("size", size))
        if str(value.get("weight", "")).lower() == "bold":
            weight = QtGui.QFont.Weight.Bold
        underline = bool(value.get("underline", False))
    font = QtGui.QFont(family, size)
    font.setWeight(weight)
    font.setUnderline(underline)
    return font


def _align(value: Any = None):
    if value in ("center",):
        return QtCore.Qt.AlignmentFlag.AlignCenter
    text = str(value or "")
    if any(token in text for token in ("n", "s", "e", "w")):
        flags = QtCore.Qt.AlignmentFlag(0)
        if "w" in text:
            flags |= QtCore.Qt.AlignmentFlag.AlignLeft
        if "e" in text:
            flags |= QtCore.Qt.AlignmentFlag.AlignRight
        if "n" in text:
            flags |= QtCore.Qt.AlignmentFlag.AlignTop
        if "s" in text:
            flags |= QtCore.Qt.AlignmentFlag.AlignBottom
        if flags:
            return flags
    if value in ("e", "right"):
        return QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
    if value in ("w", "left"):
        return QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
    return QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter


def _attach_layout_mode(kwargs: dict[str, Any]) -> str:
    side = str(kwargs.get("side", TOP)).lower()
    return "hbox" if side in (LEFT, RIGHT) else "vbox"


def _box_alignment(kwargs: dict[str, Any]):
    fill = str(kwargs.get("fill", "") or "").lower()
    if kwargs.get("expand", False) or fill in (X, Y, BOTH):
        return QtCore.Qt.AlignmentFlag(0)
    return _align(kwargs.get("anchor"))


def _padding_pair(value: Any) -> tuple[int, int]:
    if isinstance(value, (tuple, list)):
        if len(value) >= 2:
            return int(value[0] or 0), int(value[1] or 0)
        if len(value) == 1:
            return int(value[0] or 0), int(value[0] or 0)
    amount = int(value or 0)
    return amount, amount


def _apply_size_policy(widget: Any, kwargs: dict[str, Any]) -> None:
    if not hasattr(widget, "setSizePolicy"):
        return
    fill = str(kwargs.get("fill", "") or "").lower()
    expand = bool(kwargs.get("expand", False))
    horizontal = (
        QtWidgets.QSizePolicy.Policy.Expanding
        if expand or fill in (X, BOTH)
        else QtWidgets.QSizePolicy.Policy.Preferred
    )
    vertical = (
        QtWidgets.QSizePolicy.Policy.Expanding
        if expand or fill in (Y, BOTH)
        else QtWidgets.QSizePolicy.Policy.Preferred
    )
    widget.setSizePolicy(horizontal, vertical)


@dataclass(slots=True)
class Event:
    widget: Any
    x: int = 0
    y: int = 0
    x_root: int = 0
    y_root: int = 0
    width: int = 0
    height: int = 0
    delta: int = 0
    keysym: str = ""


class Variable(ValueState):
    def __init__(self, value: Any = None) -> None:
        super().__init__(value)
        self._callbacks: list[Callable[..., Any]] = []

    def set(self, value: Any) -> None:
        if self._value == value:
            return
        super().set(value)
        for callback in list(self._callbacks):
            callback()

    def trace_add(self, _mode: str, callback: Callable[..., Any]) -> str:
        self._callbacks.append(callback)
        return str(id(callback))

    def trace(self, mode: str, callback: Callable[..., Any]) -> str:
        return self.trace_add(mode, callback)


class TextState(Variable):
    def __init__(self, value: str = "") -> None:
        super().__init__(value)


class BoolState(Variable):
    def __init__(self, value: bool = False) -> None:
        super().__init__(bool(value))


class FloatState(Variable):
    def __init__(self, value: float = 0.0) -> None:
        super().__init__(float(value))


class Font:
    def __init__(self, font: Any = None, **kwargs: Any) -> None:
        if kwargs:
            font = kwargs
        self.font = _font(font)

    def measure(self, text: str) -> int:
        if self.font is None:
            return len(str(text)) * 6
        return QtGui.QFontMetrics(self.font).horizontalAdvance(str(text))


class WidgetMixin:
    _layout_mode: str | None

    def _init_native(self, parent: Any = None, **kwargs: Any) -> None:
        self._parent_ref = parent
        self.master = parent
        self._manager = ""
        self._layout_mode = None
        self._timer_refs: dict[str, Any] = {}
        self._event_handlers: dict[str, Callable[..., Any]] = {}
        self._connected_event_names: set[str] = set()
        self._options: dict[str, Any] = {}
        self._exists = True
        if parent is not None and hasattr(parent, "_children"):
            parent._children.append(self)
        self._children: list[Any] = []
        self.configure(**kwargs)

    def _ensure_layout(self, mode: str = "vbox"):
        existing = self.layout() if hasattr(self, "layout") else None
        if existing is not None:
            return existing
        if mode == "grid":
            layout: Any = QtWidgets.QGridLayout()
        elif mode == "hbox":
            layout = QtWidgets.QHBoxLayout()
        else:
            layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        cast(Any, self).setLayout(layout)
        self._layout_mode = mode
        return layout

    def _add_to_parent(self, parent: Any, **kwargs: Any) -> None:
        if parent is None:
            return
        mode = "grid" if "row" in kwargs or "column" in kwargs else _attach_layout_mode(kwargs)
        if hasattr(parent, "_ensure_layout"):
            layout = parent._ensure_layout(mode)
        else:
            layout = parent.layout() if hasattr(parent, "layout") else None
            if layout is None and hasattr(parent, "setLayout"):
                if mode == "grid":
                    layout = QtWidgets.QGridLayout()
                elif mode == "hbox":
                    layout = QtWidgets.QHBoxLayout()
                else:
                    layout = QtWidgets.QVBoxLayout()
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(6)
                parent.setLayout(layout)
        if layout is None:
            return
        _apply_size_policy(self, kwargs)
        if _is_qt_instance(layout, "QGridLayout"):
            row = int(kwargs.get("row", 0) or 0)
            col = int(kwargs.get("column", 0) or 0)
            rowspan = int(kwargs.get("rowspan", 1) or 1)
            colspan = int(kwargs.get("columnspan", 1) or 1)
            sticky = str(kwargs.get("sticky", "") or "")
            alignment = QtCore.Qt.AlignmentFlag(0) if any(c in sticky for c in "nsew") else _align(kwargs.get("anchor"))
            layout.addWidget(cast(Any, self), row, col, rowspan, colspan, alignment)
        else:
            alignment = _box_alignment(kwargs)
            stretch = 1 if kwargs.get("expand", False) else 0
            if _is_qt_instance(layout, "QBoxLayout"):
                layout.addWidget(cast(Any, self), stretch, alignment)

    def attach(self, **kwargs: Any) -> None:
        self._add_to_parent(getattr(self, "_parent_ref", None), **kwargs)
        self._manager = "box"

    def attach_matrix(self, **kwargs: Any) -> None:
        self._add_to_parent(getattr(self, "_parent_ref", None), **kwargs)
        self._manager = "matrix"

    def hide_from_layout(self) -> None:
        cast(Any, self).hide()
        self._manager = ""

    def _set_layout_resize_enabled(self, enabled: bool) -> None:
        self_widget = cast(Any, self)
        if enabled:
            previous_limits = getattr(self, "_layout_resize_previous_limits", None)
            if previous_limits is not None:
                min_size, max_size = previous_limits
                self_widget.setMinimumSize(min_size)
                self_widget.setMaximumSize(max_size)
                delattr(self, "_layout_resize_previous_limits")
            return

        if getattr(self, "_layout_resize_previous_limits", None) is None:
            self._layout_resize_previous_limits = (self_widget.minimumSize(), self_widget.maximumSize())

        requested_width = self._options.get("width")
        requested_height = self._options.get("height")
        if requested_width is not None and requested_height is not None:
            self_widget.setFixedSize(int(requested_width), int(requested_height))
            return
        if requested_width is not None:
            self_widget.setFixedWidth(int(requested_width))
            return
        if requested_height is not None:
            self_widget.setFixedHeight(int(requested_height))
            return

        width = max(1, int(self_widget.width() or self_widget.sizeHint().width()))
        height = max(1, int(self_widget.height() or self_widget.sizeHint().height()))
        self_widget.setFixedSize(width, height)

    def set_box_layout_propagation(self, flag: bool) -> None:
        self._set_layout_resize_enabled(bool(flag))

    def set_grid_layout_propagation(self, flag: bool) -> None:
        self._set_layout_resize_enabled(bool(flag))

    def set_grid_row_stretch(self, index: int, weight: int = 0) -> None:
        layout = self._ensure_layout("grid")
        if _is_qt_instance(layout, "QGridLayout"):
            layout.setRowStretch(int(index), int(weight))

    def set_grid_column_stretch(self, index: int, weight: int = 0) -> None:
        layout = self._ensure_layout("grid")
        if _is_qt_instance(layout, "QGridLayout"):
            layout.setColumnStretch(int(index), int(weight))

    def configure(self, **kwargs: Any) -> None:
        # 偵測並警告已被 Qt 介面移除的舊 kwargs，避免靜默丟棄造成開發者困惑
        legacy_keys = {
            "row",
            "column",
            "sticky",
            "padx",
            "pady",
            "ipadx",
            "ipady",
            "rowspan",
            "columnspan",
            "grid",
            "pack",
            "place",
        }
        ignored = set(kwargs.keys()) & legacy_keys
        if ignored:
            logger.warning(
                f"configure() 收到不再支援的舊參數並將被忽略: {', '.join(sorted(ignored))}. "
                "請改用 Qt API 或更新呼叫方以移除這些參數。"
            )
        self._options.update(kwargs)
        self_widget = cast(Any, self)
        if "text" in kwargs and hasattr(self, "setText"):
            self_widget.setText(str(kwargs["text"]))
        if "font" in kwargs and hasattr(self, "setFont"):
            self_widget.setFont(_font(kwargs["font"]))
        if "width" in kwargs and hasattr(self, "setFixedWidth"):
            with context_suppress():
                width = int(kwargs["width"])
                if _is_qt_instance(
                    self,
                    "QPushButton",
                    "QLineEdit",
                    "QComboBox",
                    "QTextEdit",
                    "QTreeView",
                    "QListWidget",
                ):
                    self_widget.setMinimumWidth(width)
                else:
                    self_widget.setFixedWidth(width)
        if "height" in kwargs and hasattr(self, "setFixedHeight"):
            with context_suppress():
                height = int(kwargs["height"])
                if _is_qt_instance(self, "QPushButton", "QLineEdit", "QComboBox"):
                    self_widget.setMinimumHeight(max(height, self_widget.sizeHint().height()))
                elif _is_qt_instance(self, "QTreeView") and height <= 80:
                    row_height = max(14, self_widget.fontMetrics().height() + 5)
                    header_height = max(16, self_widget.header().height())
                    self_widget.setMinimumHeight(header_height + row_height * max(1, height))
                elif _is_qt_instance(self, "QListWidget") and height <= 80:
                    row_height = max(13, self_widget.fontMetrics().height() + 4)
                    self_widget.setMinimumHeight(row_height * max(1, height) + 4)
                else:
                    self_widget.setFixedHeight(height)
        if "min_width" in kwargs and hasattr(self, "setMinimumWidth"):
            with context_suppress():
                self_widget.setMinimumWidth(int(kwargs["min_width"]))
        if "min_height" in kwargs and hasattr(self, "setMinimumHeight"):
            with context_suppress():
                self_widget.setMinimumHeight(int(kwargs["min_height"]))
        if "placeholder_text" in kwargs and hasattr(self, "setPlaceholderText"):
            self_widget.setPlaceholderText(str(kwargs["placeholder_text"]))
        if "cursor" in kwargs and hasattr(self, "setCursor"):
            cursor = str(kwargs["cursor"]).lower()
            if cursor in ("hand2", "hand", "pointinghandcursor"):
                self_widget.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        if "wraplength" in kwargs and hasattr(self, "setWordWrap"):
            with context_suppress():
                self_widget.setWordWrap(True)
                self_widget.setMaximumWidth(int(kwargs["wraplength"]))
        if "wrap" in kwargs and _is_qt_instance(self, "QTextEdit"):
            wrap = str(kwargs["wrap"]).lower()
            mode = (
                QtWidgets.QTextEdit.LineWrapMode.NoWrap
                if wrap == "none"
                else QtWidgets.QTextEdit.LineWrapMode.WidgetWidth
            )
            self_widget.setLineWrapMode(mode)
        if ("anchor" in kwargs or "justify" in kwargs) and hasattr(self, "setAlignment"):
            alignment_value = kwargs.get("anchor", kwargs.get("justify"))
            with context_suppress():
                self_widget.setAlignment(_align(alignment_value))
        if "state" in kwargs and hasattr(self, "setEnabled"):
            self_widget.setEnabled(str(kwargs["state"]) != DISABLED)
        style_parts: list[str] = []
        bg = kwargs.get("fg_color", kwargs.get("bg", kwargs.get("background")))
        fg = kwargs.get("text_color", kwargs.get("fg", kwargs.get("foreground")))
        border = kwargs.get("border_color")
        radius = kwargs.get("corner_radius", kwargs.get("border_radius"))
        hover = kwargs.get("hover_color", kwargs.get("button_hover_color"))
        style_requested = any(
            key in kwargs
            for key in (
                "fg_color",
                "bg",
                "background",
                "text_color",
                "fg",
                "foreground",
                "border_color",
                "corner_radius",
                "border_radius",
                "hover_color",
                "button_hover_color",
                "border_spacing",
                "padx",
                "pady",
                "width",
                "height",
            )
        )
        if bg is not None:
            style_parts.append(f"background-color: {_color(bg)};")
        if fg is not None:
            style_parts.append(f"color: {_color(fg)};")
        if border is not None:
            style_parts.append(f"border: 1px solid {_color(border)};")
        if radius is not None:
            style_parts.append(f"border-radius: {int(radius)}px;")
        if _is_qt_instance(self, "QPushButton") and style_requested:
            if border is None:
                style_parts.append("border: 0;")
            requested_width = int(kwargs.get("width", 0) or 0)
            requested_height = int(kwargs.get("height", 0) or 0)
            if requested_width <= 24 or requested_height <= 16:
                style_parts.append("padding: 2px 5px;")
            elif requested_width <= 45 or requested_height <= 18:
                style_parts.append("padding: 3px 6px;")
            else:
                style_parts.append("padding: 6px 10px;")
            if "border_spacing" in kwargs:
                spacing = int(kwargs["border_spacing"])
                style_parts.append(f"padding-left: {spacing}px; padding-right: {spacing}px;")
            elif "padx" in kwargs or "pady" in kwargs:
                padx = _padding_pair(kwargs.get("padx", 7))[0]
                pady = _padding_pair(kwargs.get("pady", 4))[0]
                style_parts.append(f"padding: {pady}px {padx}px;")
            if kwargs.get("anchor") in ("w", "left"):
                style_parts.append("text-align: left;")
        if _is_qt_instance(self, "QComboBox"):
            button_color = kwargs.get("button_color")
            if button_color is not None:
                style_parts.append(f"selection-background-color: {_color(button_color)};")
        if _is_qt_instance(self, "QFrame") and border is None and style_requested:
            style_parts.append("border: none;")
        if _is_qt_instance(self, "QLabel") and style_requested:
            style_parts.append("border: none; background: transparent;")
        if style_parts and hasattr(self, "setStyleSheet"):
            selector = _style_selector(self)
            stylesheet = f"{selector} {{ {' '.join(style_parts)} }}"
            if hover is not None and _is_qt_instance(self, "QPushButton"):
                stylesheet += f" {selector}:hover {{ background-color: {_color(hover)}; }}"
            self_widget.setStyleSheet(stylesheet)

    config = configure

    def cget(self, key: str) -> Any:
        return self._options.get(key)

    def connect_event(self, event_name: str, callback: Callable[..., Any], *, append: bool = False) -> str:
        if append and event_name in self._event_handlers:
            previous = self._event_handlers[event_name]

            def chained_callback(*args: Any, **kwargs: Any) -> Any:
                previous(*args, **kwargs)
                return callback(*args, **kwargs)

            self._event_handlers[event_name] = chained_callback
            self._install_event_hook(event_name)
            return str(id(chained_callback))
        self._event_handlers[event_name] = callback
        self._install_event_hook(event_name)
        return str(id(callback))

    def disconnect_event(self, event_name: str) -> None:
        self._event_handlers.pop(event_name, None)

    def _install_event_hook(self, event_name: str) -> None:
        if hasattr(self, "installEventFilter"):
            with context_suppress():
                cast(Any, self).installEventFilter(cast(Any, self))
        if hasattr(self, "viewport"):
            with context_suppress():
                cast(Any, self).viewport().installEventFilter(cast(Any, self))
        if hasattr(self, "header"):
            with context_suppress():
                cast(Any, self).header().installEventFilter(cast(Any, self))
        if event_name in self._connected_event_names:
            return
        if event_name == "selection_changed":
            if hasattr(self, "itemSelectionChanged"):
                cast(Any, self).itemSelectionChanged.connect(lambda: self._dispatch_event(event_name))
                self._connected_event_names.add(event_name)
                return
            if hasattr(self, "selectionModel"):
                selection_model = cast(Any, self).selectionModel()
                if selection_model is not None:
                    selection_model.selectionChanged.connect(lambda *_args: self._dispatch_event(event_name))
                    self._connected_event_names.add(event_name)

    def _event_from_qt(self, qt_event: Any = None) -> Event:
        x, y, x_root, y_root = _event_position(qt_event)
        delta = 0
        keysym = ""
        width = self.widget_width()
        height = self.widget_height()
        if qt_event is not None and hasattr(qt_event, "size"):
            event_size = qt_event.size()
            width = int(event_size.width())
            height = int(event_size.height())
        if qt_event is not None and hasattr(qt_event, "angleDelta"):
            delta = int(qt_event.angleDelta().y())
        if qt_event is not None and hasattr(qt_event, "key"):
            key_map = {
                QtCore.Qt.Key.Key_Return: "Return",
                QtCore.Qt.Key.Key_Enter: "Return",
                QtCore.Qt.Key.Key_Escape: "Escape",
                QtCore.Qt.Key.Key_Up: "Up",
                QtCore.Qt.Key.Key_Down: "Down",
            }
            keysym = key_map.get(qt_event.key(), "")
        return Event(
            widget=self,
            x=x,
            y=y,
            x_root=x_root,
            y_root=y_root,
            width=width,
            height=height,
            delta=delta,
            keysym=keysym,
        )

    def _dispatch_event(self, event_name: str, qt_event: Any = None) -> bool:
        callback = self._event_handlers.get(event_name)
        if callback is None:
            return False
        result = callback(self._event_from_qt(qt_event))
        return result == "break"

    def eventFilter(self, watched: Any, event: Any) -> bool:
        watched_self = watched is self
        with context_suppress():
            watched_self = watched_self or watched is cast(Any, self).viewport() or watched is cast(Any, self).header()
        if not watched_self:
            return False
        event_type = event.type()
        event_names: list[str] = []
        if event_type == QtCore.QEvent.Type.MouseButtonPress:
            button = event.button()
            if button == QtCore.Qt.MouseButton.LeftButton:
                event_names.append("mouse_left_press")
            elif button == QtCore.Qt.MouseButton.RightButton:
                event_names.append("mouse_right_press")
        elif event_type == QtCore.QEvent.Type.MouseButtonRelease:
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                event_names.append("mouse_left_release")
        elif event_type == QtCore.QEvent.Type.MouseButtonDblClick:
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                event_names.append("mouse_double_click")
        elif event_type == QtCore.QEvent.Type.KeyPress:
            key = event.key()
            key_event_names = {
                QtCore.Qt.Key.Key_Return: "return_pressed",
                QtCore.Qt.Key.Key_Enter: "return_pressed",
                QtCore.Qt.Key.Key_Escape: "escape_pressed",
                QtCore.Qt.Key.Key_Up: "key_up",
                QtCore.Qt.Key.Key_Down: "key_down",
            }
            if key in key_event_names:
                event_names.append(key_event_names[key])
        elif event_type == QtCore.QEvent.Type.Wheel:
            event_names.append("wheel")
        elif event_type == QtCore.QEvent.Type.Resize:
            event_names.append("resize")
        elif event_type == QtCore.QEvent.Type.Show:
            event_names.append("show")
        elif event_type == QtCore.QEvent.Type.Hide:
            event_names.append("hide")
        elif event_type == QtCore.QEvent.Type.FocusIn:
            event_names.append("focus_in")
        with context_suppress():
            self._dispatching_header_event = watched is cast(Any, self).header()
        handled = False
        try:
            for event_name in event_names:
                handled = self._dispatch_event(event_name, event) or handled
            return handled
        finally:
            with context_suppress():
                self._dispatching_header_event = False

    def schedule(self, delay_ms: int, callback: Callable[..., Any] | None = None) -> str:
        if callback is None:
            time.sleep(max(0, int(delay_ms)) / 1000)
            return ""
        job_id = f"job-{id(callback)}-{time.monotonic_ns()}"
        # QTimer 需 QObject 作 parent，若 self 不是 QObject 則傳 None
        parent_obj = self if hasattr(self, "thread") or hasattr(self, "metaObject") else None
        timer = QtCore.QTimer(cast(Any, parent_obj))
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        timer.timeout.connect(timer.deleteLater)
        timer.start(max(0, int(delay_ms)))
        self._timer_refs[job_id] = timer
        return job_id

    def schedule_idle(self, callback: Callable[..., Any]) -> str:
        return self.schedule(0, callback)

    def cancel_schedule(self, job_id: str) -> None:
        timer = self._timer_refs.pop(job_id, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def destroy(self, *_args, **_kwargs) -> None:
        self._exists = False
        widget = cast(Any, self)
        with context_suppress():
            widget._force_destroy = True
        if hasattr(widget, "close"):
            widget.close()
        elif hasattr(widget, "hide"):
            widget.hide()
        if hasattr(widget, "deleteLater"):
            widget.deleteLater()

    def is_alive(self) -> bool:
        if not bool(getattr(self, "_exists", True)):
            return False
        if isinstance(self, QtCore.QObject):
            return is_qobject_alive(self)
        return True

    def top_level_widget(self):
        widget = self
        while getattr(widget, "_parent_ref", None) is not None:
            widget = widget._parent_ref
        return widget

    def widget_width(self) -> int:
        return int(self.width()) if hasattr(self, "width") else 0

    def widget_height(self) -> int:
        return int(self.height()) if hasattr(self, "height") else 0

    def widget_x(self) -> int:
        return int(self.x()) if hasattr(self, "x") else 0

    def widget_y(self) -> int:
        return int(self.y()) if hasattr(self, "y") else 0

    def is_viewable(self) -> bool:
        return bool(self.isVisible()) if hasattr(self, "isVisible") else True

    def clipboard_clear(self) -> None:
        app = ensure_app()
        app.clipboard().clear()

    def clipboard_append(self, text: str) -> None:
        app = ensure_app()
        app.clipboard().setText(str(text))


class context_suppress:
    def __enter__(self):
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return True


class Frame(WidgetMixin, QtWidgets.QFrame):
    def __init__(self, parent: Any = None, **kwargs: Any) -> None:
        QtWidgets.QFrame.__init__(self, _native_parent(parent))
        self._init_native(parent, **kwargs)


class ScrollableFrame(WidgetMixin, QtWidgets.QScrollArea):
    def __init__(self, parent: Any = None, **kwargs: Any) -> None:
        QtWidgets.QScrollArea.__init__(self, _native_parent(parent))
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._content_widget = QtWidgets.QWidget()
        self._content_widget.setObjectName(f"msm_scroll_content_{id(self)}")
        self._content_widget.setStyleSheet(f"#{self._content_widget.objectName()} {{ background: transparent; }}")
        self.setWidget(self._content_widget)
        self._init_native(parent, **kwargs)

    def _ensure_layout(self, mode: str = "vbox"):
        existing = self._content_widget.layout()
        if existing is not None:
            return existing
        if mode == "grid":
            layout: Any = QtWidgets.QGridLayout()
        elif mode == "hbox":
            layout = QtWidgets.QHBoxLayout()
        else:
            layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._content_widget.setLayout(layout)
        self._layout_mode = mode
        return layout


class Label(WidgetMixin, QtWidgets.QLabel):
    def __init__(self, parent: Any = None, text: str = "", **kwargs: Any) -> None:
        QtWidgets.QLabel.__init__(self, str(text), _native_parent(parent))
        self._init_native(parent, text=text, **kwargs)
        if "wraplength" in kwargs:
            self.setWordWrap(True)
        self.setAlignment(_align(kwargs.get("anchor")))


class Button(WidgetMixin, QtWidgets.QPushButton):
    def __init__(self, parent: Any = None, text: str = "", command: Callable[..., Any] | None = None, **kwargs: Any):
        QtWidgets.QPushButton.__init__(self, str(text), _native_parent(parent))
        self._command = command
        if command is not None:
            self.clicked.connect(self._invoke_command)
        self._init_native(parent, text=text, **kwargs)

    def _invoke_command(self, *_args: Any) -> None:
        if self._command:
            self._command()

    def invoke(self) -> None:
        self._invoke_command()

    def configure(self, **kwargs: Any) -> None:
        command = kwargs.pop("command", None)
        if command is not None:
            with context_suppress():
                self.clicked.disconnect()
            self._command = command
            self.clicked.connect(self._invoke_command)
        super().configure(**kwargs)


class Entry(WidgetMixin, QtWidgets.QLineEdit):
    def __init__(self, parent: Any = None, textvariable: Variable | None = None, **kwargs: Any) -> None:
        QtWidgets.QLineEdit.__init__(self, _native_parent(parent))
        self._variable = textvariable
        if textvariable is not None:
            self.setText(str(textvariable.get()))
            self.textChanged.connect(textvariable.set)
            textvariable.trace_add("write", lambda *_: self.setText(str(textvariable.get())))
        self._init_native(parent, **kwargs)

    def get(self) -> str:
        return self.text()

    def insert(self, index: Any, text: str | None = None) -> None:
        insert_text = str(index if text is None else text)
        if index in (0, "0"):
            self.setText(insert_text + self.text())
        else:
            self.setText(self.text() + insert_text)

    def delete(self, _start: Any, _end: Any = None) -> None:
        self.clear()

    def select_range(self, start: int, end: Any) -> None:
        length = len(self.text()) if end == END else int(end) - int(start)
        self.setSelection(int(start), max(0, length))


class TextBox(WidgetMixin, QtWidgets.QTextEdit):
    def __init__(self, parent: Any = None, **kwargs: Any) -> None:
        QtWidgets.QTextEdit.__init__(self, _native_parent(parent))
        self._init_native(parent, **kwargs)

    def insert(self, index: Any, text: str) -> None:
        if index in (END, "end"):
            self.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        self.insertPlainText(str(text))

    def get(self, *_args: Any) -> str:
        return self.toPlainText()

    def delete(self, *_args: Any) -> None:
        self.clear()

    def see(self, *_args: Any) -> None:
        self.moveCursor(QtGui.QTextCursor.MoveOperation.End)

    def yview_scroll(self, number: int, _what: str = "units") -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + int(number) * bar.singleStep())

    def yview_moveto(self, fraction: float) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(int(float(fraction) * bar.maximum()))


class CheckBox(WidgetMixin, QtWidgets.QCheckBox):
    def __init__(self, parent: Any = None, text: str = "", variable: Variable | None = None, command=None, **kwargs):
        QtWidgets.QCheckBox.__init__(self, str(text), _native_parent(parent))
        self._variable = variable
        self._command = command
        if variable is not None:
            self.setChecked(bool(variable.get()))
            self.stateChanged.connect(lambda _state: variable.set(self.isChecked()))
            variable.trace_add("write", lambda *_: self._sync_from_variable())
        if command is not None:
            self.stateChanged.connect(lambda _state: command())
        self._init_native(parent, text=text, **kwargs)

    def _sync_from_variable(self) -> None:
        if self._variable is None:
            return
        checked = bool(self._variable.get())
        if self.isChecked() == checked:
            return
        blocker = QtCore.QSignalBlocker(self)
        try:
            self.setChecked(checked)
        finally:
            del blocker


class RadioButton(WidgetMixin, QtWidgets.QRadioButton):
    def __init__(
        self,
        parent: Any = None,
        text: str = "",
        variable: Variable | None = None,
        value: Any = None,
        command: Callable[..., Any] | None = None,
        **kwargs: Any,
    ) -> None:
        QtWidgets.QRadioButton.__init__(self, str(text), _native_parent(parent))
        self._variable = variable
        self._value = value
        self._command = command
        if variable is not None:
            self.setChecked(variable.get() == value)
            self.toggled.connect(lambda checked: variable.set(value) if checked else None)
        if command is not None:
            self.toggled.connect(lambda checked: command() if checked else None)
        self._init_native(parent, text=text, **kwargs)


class Slider(WidgetMixin, QtWidgets.QSlider):
    def __init__(
        self,
        parent: Any = None,
        from_: float = 0.0,
        to: float = 1.0,
        command=None,
        variable: Variable | None = None,
        **kwargs,
    ):
        QtWidgets.QSlider.__init__(self, QtCore.Qt.Orientation.Horizontal, _native_parent(parent))
        self._scale = 100
        self.setRange(int(from_ * self._scale), int(to * self._scale))
        self._command = command
        self._variable = variable
        if variable is not None:
            self.setValue(int(float(variable.get()) * self._scale))
            variable.trace_add("write", lambda *_: self._sync_from_variable())
        self.valueChanged.connect(self._on_value_changed)
        self._init_native(parent, **kwargs)

    def _sync_from_variable(self) -> None:
        if self._variable is None:
            return
        raw_value = int(float(self._variable.get()) * self._scale)
        if self.value() == raw_value:
            return
        blocker = QtCore.QSignalBlocker(self)
        try:
            self.setValue(raw_value)
        finally:
            del blocker

    def _on_value_changed(self, value: int) -> None:
        scaled_value = value / self._scale
        if self._variable is not None:
            self._variable.set(scaled_value)
        if self._command is not None:
            self._command(scaled_value)

    def set(self, value: float) -> None:
        self.setValue(int(float(value) * self._scale))

    def get(self) -> float:
        return self.value() / self._scale


class ProgressBar(WidgetMixin, QtWidgets.QProgressBar):
    def __init__(self, parent: Any = None, **kwargs: Any) -> None:
        QtWidgets.QProgressBar.__init__(self, _native_parent(parent))
        self.setRange(0, 100)
        self._init_native(parent, **kwargs)

    def set(self, value: float) -> None:
        self.setValue(int(float(value) * 100 if float(value) <= 1 else float(value)))

    def stop(self) -> None:
        return None


class OptionMenu(WidgetMixin, QtWidgets.QComboBox):
    def __init__(
        self,
        parent: Any = None,
        values: list[str] | None = None,
        variable: Variable | None = None,
        command=None,
        **kwargs,
    ):
        QtWidgets.QComboBox.__init__(self, _native_parent(parent))
        self._variable = variable
        self._command = command
        self.setEditable(False)
        self.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(4)
        self.addItems([str(v) for v in values or []])
        if variable is not None and variable.get():
            self.setCurrentText(str(variable.get()))
        self.currentTextChanged.connect(self._on_changed)
        self._init_native(parent, values=values or [], **kwargs)

    def _on_changed(self, value: str) -> None:
        if self._variable is not None:
            self._variable.set(value)
        if self._command is not None:
            self._command(value)

    def get(self) -> str:
        return self.currentText()

    def set(self, value: str) -> None:
        self.setCurrentText(str(value))

    def configure(self, **kwargs: Any) -> None:
        if "values" in kwargs:
            self.clear()
            values = [str(v) for v in kwargs["values"]]
            self.addItems(values)
            longest = max((len(v) for v in values), default=4)
            self.setMinimumContentsLength(min(max(longest, 4), 24))
        super().configure(**kwargs)


class _TreeRow:
    __slots__ = ("children", "item_id", "parent", "tag_styles", "tags", "values")

    def __init__(
        self,
        item_id: str,
        values: list[str] | tuple[str, ...] = (),
        tags: tuple[str, ...] = (),
        tag_styles: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.item_id = item_id
        self.values = [str(value) for value in values]
        self.tags = tuple(tags)
        self.tag_styles = tag_styles if tag_styles is not None else {}
        self.parent: _TreeRow | None = None
        self.children: list[_TreeRow] = []

    def text(self, column: int) -> str:
        return self.values[column] if 0 <= column < len(self.values) else ""

    def setText(self, column: int, value: Any) -> None:
        while len(self.values) <= column:
            self.values.append("")
        self.values[column] = str(value)

    def textAlignment(self, _column: int):
        return QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter

    def _style_color(self, name: str) -> str | None:
        color: str | None = None
        for tag in self.tags:
            color = self.tag_styles.get(str(tag), {}).get(name, color)
        return color

    def background(self, _column: int) -> QtGui.QBrush:
        color = self._style_color("background")
        return QtGui.QBrush(QtGui.QColor(color)) if color else QtGui.QBrush()

    def foreground(self, _column: int) -> QtGui.QBrush:
        color = self._style_color("foreground")
        return QtGui.QBrush(QtGui.QColor(color)) if color else QtGui.QBrush()


class _TreeModel(QtCore.QAbstractItemModel):
    def __init__(self, columns: list[str], tag_styles: dict[str, dict[str, str]], parent: Any = None) -> None:
        super().__init__(parent)
        self.columns = list(columns)
        self.tag_styles = tag_styles
        self.root = _TreeRow("", tag_styles=tag_styles)
        self.rows: dict[str, _TreeRow] = {}

    def _column_count(self) -> int:
        return max(1, len(self.columns))

    def _row_from_index(self, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex) -> _TreeRow:
        if index.isValid():
            row = index.internalPointer()
            if isinstance(row, _TreeRow):
                return row
        return self.root

    def _parent_index_for_row(self, row: _TreeRow) -> QtCore.QModelIndex:
        parent = row.parent
        if parent is None or parent is self.root:
            return QtCore.QModelIndex()
        grandparent = parent.parent or self.root
        return self.createIndex(grandparent.children.index(parent), 0, parent)

    def _index_for_row(self, row: _TreeRow, column: int = 0) -> QtCore.QModelIndex:
        parent = row.parent
        if parent is None:
            return QtCore.QModelIndex()
        return self.createIndex(parent.children.index(row), max(0, int(column)), row)

    def index(
        self,
        row: int,
        column: int,
        parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex = INVALID_MODEL_INDEX,
    ) -> QtCore.QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QtCore.QModelIndex()
        parent_row = self._row_from_index(parent)
        try:
            return self.createIndex(row, column, parent_row.children[row])
        except IndexError:
            return QtCore.QModelIndex()

    def parent(self, index: QtCore.QModelIndex) -> QtCore.QModelIndex:  # type: ignore[override]
        if not index.isValid():
            return QtCore.QModelIndex()
        row = self._row_from_index(index)
        parent_row = row.parent
        if parent_row is None or parent_row is self.root:
            return QtCore.QModelIndex()
        return self._index_for_row(parent_row)

    def rowCount(self, parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex = INVALID_MODEL_INDEX) -> int:
        if parent.isValid() and parent.column() > 0:
            return 0
        return len(self._row_from_index(parent).children)

    def columnCount(self, _parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex = INVALID_MODEL_INDEX) -> int:
        return self._column_count()

    def data(
        self,
        index: QtCore.QModelIndex | QtCore.QPersistentModelIndex,
        role: int = QtCore.Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid():
            return None
        row = self._row_from_index(index)
        column = index.column()
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return row.text(column)
        if role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            return row.textAlignment(column)
        if role == QtCore.Qt.ItemDataRole.BackgroundRole:
            color = row._style_color("background")
            return QtGui.QBrush(QtGui.QColor(color)) if color else None
        if role == QtCore.Qt.ItemDataRole.ForegroundRole:
            color = row._style_color("foreground")
            return QtGui.QBrush(QtGui.QColor(color)) if color else None
        return None

    def flags(self, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex) -> QtCore.Qt.ItemFlag:
        if not index.isValid():
            return QtCore.Qt.ItemFlag.NoItemFlags
        return QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable

    def headerData(
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: int = QtCore.Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == QtCore.Qt.Orientation.Horizontal and role == QtCore.Qt.ItemDataRole.DisplayRole:
            return self.columns[section] if 0 <= section < len(self.columns) else ""
        if orientation == QtCore.Qt.Orientation.Horizontal and role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            return QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        return None

    def setHeaderData(
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        value: Any,
        role: int = QtCore.Qt.ItemDataRole.EditRole,
    ) -> bool:
        if orientation != QtCore.Qt.Orientation.Horizontal or role not in {
            QtCore.Qt.ItemDataRole.EditRole,
            QtCore.Qt.ItemDataRole.DisplayRole,
        }:
            return False
        while len(self.columns) <= section:
            self.columns.append("")
        self.columns[section] = str(value)
        self.headerDataChanged.emit(orientation, section, section)
        return True

    def index_for_id(self, item_id: str, column: int = 0) -> QtCore.QModelIndex:
        row = self.rows.get(str(item_id))
        if row is None or row.parent is None:
            return QtCore.QModelIndex()
        return self._index_for_row(row, column)

    def _normalized_values(self, values: Any, text: str = "") -> list[str]:
        normalized = [str(value) for value in (values or ())]
        while len(normalized) < self._column_count():
            normalized.append("")
        if text:
            normalized[0] = str(text)
        return normalized[: self._column_count()]

    def insert_item(
        self,
        parent_id: str,
        index: Any,
        item_id: str,
        text: str = "",
        values: Any = (),
        tags: Any = (),
    ) -> str:
        if item_id in self.rows:
            self.remove_item(item_id)
        parent_row = self.rows.get(str(parent_id), self.root) if parent_id else self.root
        row_index = len(parent_row.children) if index in (END, "end") else max(0, int(index))
        row_index = min(row_index, len(parent_row.children))
        parent_index = QtCore.QModelIndex() if parent_row is self.root else self._index_for_row(parent_row)
        self.beginInsertRows(parent_index, row_index, row_index)
        row = _TreeRow(item_id, self._normalized_values(values, text), tuple(tags or ()), self.tag_styles)
        row.parent = parent_row
        parent_row.children.insert(row_index, row)
        self.rows[item_id] = row
        self.endInsertRows()
        return item_id

    def _remove_row_mapping(self, row: _TreeRow) -> None:
        for child in list(row.children):
            self._remove_row_mapping(child)
        self.rows.pop(row.item_id, None)

    def remove_item(self, item_id: str, *, detach: bool = False) -> None:
        row = self.rows.get(str(item_id))
        if row is None or row.parent is None:
            return
        parent_row = row.parent
        row_index = parent_row.children.index(row)
        parent_index = QtCore.QModelIndex() if parent_row is self.root else self._index_for_row(parent_row)
        self.beginRemoveRows(parent_index, row_index, row_index)
        parent_row.children.pop(row_index)
        row.parent = None
        self.endRemoveRows()
        if not detach:
            self._remove_row_mapping(row)

    def reattach_item(self, item_id: str, parent_id: str, index: int | str = 0) -> None:
        row = self.rows.get(str(item_id))
        if row is None:
            return
        if row.parent is not None:
            self.remove_item(item_id, detach=True)
        parent_row = self.rows.get(str(parent_id), self.root) if parent_id else self.root
        row_index = len(parent_row.children) if index == END else max(0, int(index))
        row_index = min(row_index, len(parent_row.children))
        parent_index = QtCore.QModelIndex() if parent_row is self.root else self._index_for_row(parent_row)
        self.beginInsertRows(parent_index, row_index, row_index)
        row.parent = parent_row
        parent_row.children.insert(row_index, row)
        self.endInsertRows()

    def move_item(self, item_id: str, parent_id: str = "", index: int = 0) -> None:
        if str(item_id) not in self.rows:
            return
        self.remove_item(str(item_id), detach=True)
        self.reattach_item(str(item_id), parent_id, index)

    def children_ids(self, parent_id: str | None = None) -> tuple[str, ...]:
        parent_row = self.rows.get(str(parent_id), self.root) if parent_id else self.root
        return tuple(row.item_id for row in parent_row.children)

    def parent_id(self, item_id: str) -> str:
        row = self.rows.get(str(item_id))
        if row is None or row.parent is None or row.parent is self.root:
            return ""
        return row.parent.item_id

    def set_values(self, item_id: str, values: Any) -> None:
        row = self.rows.get(str(item_id))
        if row is None:
            return
        row.values = self._normalized_values(values)
        index_left = self.index_for_id(item_id, 0)
        index_right = self.index_for_id(item_id, self._column_count() - 1)
        if index_left.isValid() and index_right.isValid():
            self.dataChanged.emit(index_left, index_right, [QtCore.Qt.ItemDataRole.DisplayRole])

    def set_cell(self, item_id: str, column: int, value: Any) -> None:
        row = self.rows.get(str(item_id))
        if row is None:
            return
        row.setText(column, value)
        index = self.index_for_id(item_id, column)
        if index.isValid():
            self.dataChanged.emit(index, index, [QtCore.Qt.ItemDataRole.DisplayRole])

    def set_tags(self, item_id: str, tags: Any) -> None:
        row = self.rows.get(str(item_id))
        if row is None:
            return
        row.tags = tuple(tags or ())
        self._emit_row_style_changed(item_id)

    def _emit_row_style_changed(self, item_id: str) -> None:
        index_left = self.index_for_id(item_id, 0)
        index_right = self.index_for_id(item_id, self._column_count() - 1)
        if index_left.isValid() and index_right.isValid():
            self.dataChanged.emit(
                index_left,
                index_right,
                [QtCore.Qt.ItemDataRole.BackgroundRole, QtCore.Qt.ItemDataRole.ForegroundRole],
            )

    def emit_style_changed(self, tag: str) -> None:
        for item_id, row in self.rows.items():
            if tag not in row.tags:
                continue
            self._emit_row_style_changed(item_id)


class Treeview(WidgetMixin, QtWidgets.QTreeView):
    def __init__(self, parent: Any = None, columns: list[str] | tuple[str, ...] = (), show: str = "", **kwargs):
        QtWidgets.QTreeView.__init__(self, _native_parent(parent))
        self._columns = list(columns)
        self._tags: dict[str, tuple[str, ...]] = {}
        self._tag_styles: dict[str, dict[str, str]] = {}
        self._model = _TreeModel([str(c) for c in self._columns] or [""], self._tag_styles, self)
        self._items = self._model.rows
        self.setModel(self._model)
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setUniformRowHeights(True)
        self.setAllColumnsShowFocus(True)
        self.setAlternatingRowColors(True)
        self.setItemsExpandable(True)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.setViewportMargins(0, 0, 0, 0)
        self.header().setMinimumSectionSize(0)
        self.header().setStretchLastSection(False)
        self.setHeaderHidden("headings" not in str(show).split())
        default_alignment = QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        self.header().setDefaultAlignment(default_alignment)
        self._apply_selectmode(str(kwargs.get("selectmode", "browse")))
        self._init_native(parent, columns=columns, show=show, **kwargs)
        self.apply_theme_style()

    def apply_theme_style(self) -> None:
        """Apply the current Qt theme colors directly to this native tree."""
        dark = is_dark_color_scheme()
        base = "#000000" if dark else "#ffffff"
        alternate = "#111827" if dark else "#f8fafc"
        text = "#ffffff" if dark else "#0f172a"
        border = "#4b5563" if dark else "#cbd5e1"
        header_bg = "#171717" if dark else "#f1f5f9"
        header_text = "#f8fafc" if dark else "#0f172a"
        selected = "#2563eb"
        self.setStyleSheet(
            "QTreeView {"
            f"background: {base}; color: {text}; alternate-background-color: {alternate};"
            f"border: 1px solid {border}; padding: 0px; margin: 0px;"
            "}"
            "QTreeView::item {"
            f"color: {text}; padding: 0px 2px 0px 0px; margin: 0px;"
            "}"
            f"QTreeView::item:selected {{ background: {selected}; color: #ffffff; }}"
            f"QTreeView::item:selected:!active {{ background: {selected}; color: #ffffff; }}"
            "QHeaderView::section {"
            f"background: {header_bg}; color: {header_text}; border: 1px solid {border};"
            "padding: 3px 4px 3px 0px; margin: 0px;"
            "}"
        )

    def _apply_selectmode(self, selectmode: str) -> None:
        mode = selectmode.lower()
        if mode in {"extended", "multiple"}:
            self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        elif mode in {"none", "disabled"}:
            self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        else:
            self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)

    def heading(self, column: str, text: str | None = None, command: Callable[..., Any] | None = None, **_kwargs):
        idx = self._column_index(column)
        if text == "text" and command is None:
            return self._model.headerData(idx, QtCore.Qt.Orientation.Horizontal)
        if text is not None:
            self._model.setHeaderData(idx, QtCore.Qt.Orientation.Horizontal, str(text))
        if command is not None:
            self.header().sectionClicked.connect(lambda clicked: command() if clicked == idx else None)
        return None

    def column(self, column: str | int, width: int | str | None = None, **_kwargs):
        idx = self._column_index(column)
        if isinstance(width, str):
            if width == "width":
                return self.columnWidth(idx)
            if width == "minwidth":
                return self.header().minimumSectionSize()
            if width == "stretch":
                return self.header().sectionResizeMode(idx) == QtWidgets.QHeaderView.ResizeMode.Stretch
            width = None
        if width is not None:
            self.setColumnWidth(idx, int(width))
        if "minwidth" in _kwargs and _kwargs["minwidth"] is not None:
            self.header().setMinimumSectionSize(
                min(self.header().minimumSectionSize(), max(0, int(_kwargs["minwidth"])))
            )
        if "stretch" in _kwargs:
            mode = (
                QtWidgets.QHeaderView.ResizeMode.Stretch
                if bool(_kwargs["stretch"])
                else QtWidgets.QHeaderView.ResizeMode.Interactive
            )
            self.header().setSectionResizeMode(idx, mode)
        return {"width": self.columnWidth(idx)}

    def configure(self, **kwargs: Any) -> None:
        display_columns = kwargs.pop("displaycolumns", None)
        super().configure(**kwargs)
        if display_columns is not None:
            display_set = {str(column) for column in display_columns}
            for column_name in self._columns:
                idx = self._column_index(column_name)
                self.setColumnHidden(idx, column_name not in display_set)

    def insert(
        self,
        parent: str,
        _index: Any,
        iid: str | None = None,
        text: str = "",
        values: Any = (),
        tags: Any = (),
        open: bool = False,
    ):
        item_id = str(iid or f"item-{len(self._items) + 1}")
        self._model.insert_item(parent, _index, item_id, text=text, values=values, tags=tags)
        self._tags[item_id] = tuple(tags or ())
        if open:
            index = self._model.index_for_id(item_id)
            if index.isValid():
                self.expand(index)
        return item_id

    def item(self, item: str, option: str | None = None, **kwargs: Any):
        node = self._items.get(str(item))
        if node is None:
            return {} if option is None else None
        if "values" in kwargs:
            self._model.set_values(str(item), kwargs["values"])
        if "tags" in kwargs:
            self._tags[str(item)] = tuple(kwargs["tags"])
            self._model.set_tags(str(item), kwargs["tags"])
        if "open" in kwargs:
            index = self._model.index_for_id(str(item))
            if index.isValid():
                self.expand(index) if kwargs["open"] else self.collapse(index)
        if "text" in kwargs:
            self._model.set_cell(str(item), 0, kwargs["text"])
        item_values = tuple(node.text(idx) for idx in range(self._model.columnCount()))
        payload: dict[str, Any] = {"text": node.text(0), "values": item_values, "tags": self._tags.get(str(item), ())}
        return payload.get(option) if option is not None else payload

    def delete(self, *items: str) -> None:
        for item_id in items:
            self._model.remove_item(str(item_id))
            self._tags.pop(str(item_id), None)

    def get_children(self, item: str | None = None) -> tuple[str, ...]:
        return self._model.children_ids(item)

    def parent(self, item: str | None = None):
        if item is None:
            return QtWidgets.QTreeView.parent(self)
        return self._model.parent_id(str(item))

    def exists(self, item: str) -> bool:
        return str(item) in self._items and self._model.index_for_id(str(item)).isValid()

    def selection(self) -> tuple[str, ...]:
        selection_model = self.selectionModel()
        if selection_model is None:
            return ()
        selected: list[str] = []
        for index in selection_model.selectedRows(0):
            node = index.internalPointer()
            if isinstance(node, _TreeRow):
                selected.append(node.item_id)
        return tuple(selected)

    def selection_set(self, *items: str | list[str] | tuple[str, ...]) -> None:
        ids = self._flatten_item_ids(items)
        self.clearSelection()
        selection_model = self.selectionModel()
        if selection_model is None:
            return
        first_index = QtCore.QModelIndex()
        for item_id in ids:
            index = self._model.index_for_id(str(item_id))
            if index.isValid():
                selection_model.select(
                    index,
                    QtCore.QItemSelectionModel.SelectionFlag.Select | QtCore.QItemSelectionModel.SelectionFlag.Rows,
                )
                if not first_index.isValid():
                    first_index = index
        if first_index.isValid():
            selection_model.setCurrentIndex(first_index, QtCore.QItemSelectionModel.SelectionFlag.NoUpdate)

    def selection_remove(self, *items: str | list[str] | tuple[str, ...]) -> None:
        ids = self._flatten_item_ids(items)
        selection_model = self.selectionModel()
        if selection_model is None:
            return
        for item_id in ids:
            index = self._model.index_for_id(str(item_id))
            if index.isValid():
                selection_model.select(
                    index,
                    QtCore.QItemSelectionModel.SelectionFlag.Deselect | QtCore.QItemSelectionModel.SelectionFlag.Rows,
                )

    @staticmethod
    def _flatten_item_ids(items: tuple[str | list[str] | tuple[str, ...], ...]) -> list[str]:
        if len(items) == 1 and not isinstance(items[0], str):
            return [str(item_id) for item_id in items[0]]
        return [str(item_id) for item_id in items]

    def focus(self, item: str | None = None):
        if item is None:
            node = self.currentIndex().internalPointer() if self.currentIndex().isValid() else None
            return node.item_id if isinstance(node, _TreeRow) else ""
        index = self._model.index_for_id(str(item))
        if index.isValid():
            self.setCurrentIndex(index)
        return item

    def set(self, item: str, column: str, value: Any = None):
        node = self._items.get(str(item))
        if node is None:
            return None
        idx = self._column_index(column)
        if value is None:
            return node.text(idx)
        self._model.set_cell(str(item), idx, value)
        return None

    def move(self, item: str, _parent: str = "", index: int = 0) -> None:  # type: ignore[override]
        self._model.move_item(str(item), str(_parent or ""), int(index))

    def index(self, item: str) -> int:
        node = self._items.get(str(item))
        if node is None or node.parent is None:
            return -1
        return node.parent.children.index(node)

    def detach(self, item: str) -> None:
        self._model.remove_item(str(item), detach=True)

    def reattach(self, item: str, parent: str, index: int | str = 0) -> None:
        self._model.reattach_item(str(item), str(parent or ""), index)

    def see(self, item: str) -> None:
        index = self._model.index_for_id(str(item))
        if index.isValid():
            self.scrollTo(index)

    def identify_row(self, y: int) -> str:
        index = self.indexAt(QtCore.QPoint(0, int(y)))
        node = index.internalPointer() if index.isValid() else None
        return node.item_id if isinstance(node, _TreeRow) else ""

    def identify_column(self, x: int) -> str:
        idx = self.columnAt(int(x))
        return f"#{idx + 1}" if idx >= 0 else ""

    def identify_region(self, _x: int, _y: int) -> str:
        if getattr(self, "_dispatching_header_event", False):
            return "heading"
        return "cell"

    def bbox(self, item: str, _column: str | None = None):
        index = self._model.index_for_id(str(item), self._column_index(_column or 0))
        if not index.isValid():
            return ()
        rect = self.visualRect(index)
        return (rect.x(), rect.y(), rect.width(), rect.height())

    def tag_configure(self, *args: Any, **kwargs: Any) -> None:
        if not args:
            return
        tag = str(args[0])
        style = self._tag_styles.setdefault(tag, {})
        for source, target in (
            ("background", "background"),
            ("bg", "background"),
            ("foreground", "foreground"),
            ("fg", "foreground"),
        ):
            if source in kwargs and kwargs[source] is not None:
                style[target] = _color(kwargs[source])
        for item_id, node in self._items.items():
            if tag in self._tags.get(item_id, ()):
                self._model.set_tags(item_id, node.tags)
        self._model.emit_style_changed(tag)

    def yview(self, *_args: Any) -> tuple[float, float]:
        bar = self.verticalScrollBar()
        maximum = max(1, bar.maximum())
        start = bar.value() / maximum
        page = bar.pageStep() / maximum
        return (start, min(1.0, start + page))

    def xview(self, *_args: Any) -> tuple[float, float]:
        bar = self.horizontalScrollBar()
        maximum = max(1, bar.maximum())
        start = bar.value() / maximum
        page = bar.pageStep() / maximum
        return (start, min(1.0, start + page))

    def yview_scroll(self, number: int, _what: str = "units") -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + int(number) * bar.singleStep())

    def yview_moveto(self, fraction: float) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(int(float(fraction) * bar.maximum()))

    def _column_index(self, column: str | int) -> int:
        if isinstance(column, int):
            return max(0, column)
        if isinstance(column, str) and column.startswith("#"):
            return max(0, int(column[1:]) - 1)
        if column in self._columns:
            return self._columns.index(column)
        return 0

    def _apply_item_tag_styles(self, item_id: str, node: _TreeRow) -> None:
        self._model.set_tags(item_id, node.tags)


class Scrollbar(WidgetMixin, QtWidgets.QScrollBar):
    def __init__(self, parent: Any = None, orient: str = VERTICAL, command: Any = None, **kwargs: Any) -> None:
        orientation = QtCore.Qt.Orientation.Horizontal if orient == HORIZONTAL else QtCore.Qt.Orientation.Vertical
        QtWidgets.QScrollBar.__init__(self, orientation, _native_parent(parent))
        self._command = command
        self._init_native(parent, orient=orient, **kwargs)
        self.setFixedSize(0, 0)
        self.hide()

    def set(self, first: float, _last: float | None = None) -> None:
        maximum = max(1, self.maximum())
        self.setValue(int(float(first) * maximum))

    def attach_matrix(self, **kwargs: Any) -> None:
        super().attach_matrix(**kwargs)
        self.hide()

    def attach(self, **kwargs: Any) -> None:
        super().attach(**kwargs)
        self.hide()


class Notebook(WidgetMixin, QtWidgets.QTabWidget):
    def __init__(self, parent: Any = None, **kwargs: Any) -> None:
        QtWidgets.QTabWidget.__init__(self, _native_parent(parent))
        self._init_native(parent, **kwargs)
        self.currentChanged.connect(lambda _idx: self._dispatch_event("tab_changed"))

    def add(self, child: Any, text: str = "") -> None:
        self.addTab(child, str(text))

    def select(self, tab_id: Any = None):
        if tab_id is None:
            return self.currentWidget()
        if isinstance(tab_id, int):
            self.setCurrentIndex(tab_id)
        else:
            self.setCurrentWidget(_native_parent(tab_id))
        return self.currentWidget()

    def tab(self, tab_id: Any, option: str | None = None, **kwargs: Any):
        widget = _native_parent(tab_id)
        idx = self.indexOf(widget) if not isinstance(tab_id, int) else tab_id
        if idx < 0:
            return None
        if "text" in kwargs:
            self.setTabText(idx, str(kwargs["text"]))
        if option == "text":
            return self.tabText(idx)
        return {"text": self.tabText(idx)}

    def index(self, tab_id: Any) -> int:
        if tab_id in (None, "current"):
            return self.currentIndex()
        if isinstance(tab_id, int):
            return tab_id
        return self.indexOf(_native_parent(tab_id))


class LabelFrame(WidgetMixin, QtWidgets.QGroupBox):
    def __init__(self, parent: Any = None, text: str = "", **kwargs: Any) -> None:
        QtWidgets.QGroupBox.__init__(self, str(text), _native_parent(parent))
        self._init_native(parent, text=text, **kwargs)


class Spinbox(Entry):
    pass


class Listbox(WidgetMixin, QtWidgets.QListWidget):
    def __init__(self, parent: Any = None, **kwargs: Any) -> None:
        QtWidgets.QListWidget.__init__(self, _native_parent(parent))
        self._init_native(parent, **kwargs)

    def insert(self, index: Any, *texts: str) -> None:
        insert_at_end = index in (END, "end")
        base_index = self.count() if insert_at_end else int(index)
        for offset, text in enumerate(texts):
            if insert_at_end:
                self.addItem(str(text))
            else:
                self.insertItem(base_index + offset, str(text))

    def delete(self, start: Any, end: Any = None) -> None:
        if start in (0, "0") and end in (END, "end"):
            self.clear()
            return
        self.takeItem(int(start))

    def curselection(self) -> tuple[int, ...]:
        return tuple(self.row(item) for item in self.selectedItems())

    def selection_clear(self, _start: Any, _end: Any = None) -> None:
        self.clearSelection()

    def selection_set(self, index: int) -> None:
        item = self.item(int(index))
        if item is not None:
            item.setSelected(True)
            self.setCurrentItem(item)

    def activate(self, index: int) -> None:
        item = self.item(int(index))
        if item is not None:
            self.setCurrentItem(item)

    def see(self, index: int) -> None:
        item = self.item(int(index))
        if item is not None:
            self.scrollToItem(item)

    def size(self) -> int:  # type: ignore[override]
        return self.count()

    def get(self, index: int) -> str:
        item = self.item(int(index))
        return item.text() if item is not None else ""

    def itemconfig(self, index: int, **kwargs: Any) -> None:
        item = self.item(int(index))
        if item is None:
            return
        if "bg" in kwargs:
            item.setBackground(QtGui.QBrush(QtGui.QColor(_color(kwargs["bg"]))))
        if "fg" in kwargs:
            item.setForeground(QtGui.QBrush(QtGui.QColor(_color(kwargs["fg"]))))

    def yview(self, *_args: Any) -> None:
        return None


class PopupMenu:
    def __init__(self, parent: Any = None, **_kwargs: Any) -> None:
        self._menu = QtWidgets.QMenu(_native_parent(parent))

    def grab_release(self) -> None:
        pass

    def add_command(self, label: str, command: Callable[..., Any] | None = None, **_kwargs: Any) -> None:
        action = self._menu.addAction(str(label))
        if command is not None:
            action.triggered.connect(command)

    def add_separator(self) -> None:
        self._menu.addSeparator()

    def popup_at(self, x: int, y: int) -> None:
        self._menu.popup(QtCore.QPoint(int(x), int(y)))


Widget = QtWidgets.QWidget


def _file_dialog_filters(filetypes: Any = None) -> str:
    return ";;".join(f"{label} ({pattern})" for label, pattern in filetypes or [])


def get_existing_directory(parent: Any = None, title: str = "", initialdir: str | None = None) -> str:
    """Open a native Qt directory picker and return the selected path."""
    return QtWidgets.QFileDialog.getExistingDirectory(_native_parent(parent), title, initialdir or "")


def get_open_file_name(
    parent: Any = None, title: str = "", filetypes: Any = None, initialdir: str | None = None
) -> str:
    """Open a native Qt file picker and return the selected path."""
    path, _selected = QtWidgets.QFileDialog.getOpenFileName(
        _native_parent(parent), title, initialdir or "", _file_dialog_filters(filetypes)
    )
    return path


def get_save_file_name(
    parent: Any = None,
    title: str = "",
    filetypes: Any = None,
    *,
    initialfile: str | None = None,
    defaultextension: str | None = None,
) -> str:
    """Open a native Qt save dialog and return the selected path."""
    initial = initialfile or ""
    path, _selected = QtWidgets.QFileDialog.getSaveFileName(
        _native_parent(parent), title, initial, _file_dialog_filters(filetypes)
    )
    if path and defaultextension and "." not in Path(path).name:
        path += str(defaultextension)
    return path
