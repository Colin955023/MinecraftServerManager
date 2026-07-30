"""原生 PySide6 元件與 qfluentwidgets 整合。"""

from __future__ import annotations

import contextlib
import re
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from PySide6 import QtCore, QtGui, QtWidgets
from qfluentwidgets import (
    BodyLabel,
    TabWidget,
    Theme,
    isDarkTheme,
    setCustomStyleSheet,
    setFontFamilies,
    setTheme,
    setThemeColor,
)
from qfluentwidgets import (
    CheckBox as FluentCheckBox,
)
from qfluentwidgets import (
    ComboBox as FluentComboBox,
)
from qfluentwidgets import (
    Dialog as FluentDialog,
)
from qfluentwidgets import (
    HyperlinkLabel as FluentHyperlinkLabel,
)
from qfluentwidgets import (
    LineEdit as FluentLineEdit,
)
from qfluentwidgets import (
    MessageBox as FluentMessageBox,
)
from qfluentwidgets import (
    ProgressBar as FluentProgressBarWidget,
)
from qfluentwidgets import (
    PushButton as FluentPushButton,
)
from qfluentwidgets import (
    RadioButton as FluentRadioButton,
)
from qfluentwidgets import (
    ScrollArea as FluentScrollArea,
)
from qfluentwidgets import (
    SearchLineEdit as FluentSearchLineEdit,
)
from qfluentwidgets import (
    Slider as FluentSlider,
)
from qfluentwidgets import (
    SpinBox as FluentSpinBox,
)
from qfluentwidgets import (
    SubtitleLabel as FluentSubtitleLabel,
)
from qfluentwidgets import (
    TextEdit as FluentTextEdit,
)

from .. import get_logger
from .qt_runtime import ValueState, is_qobject_alive
from .ui_tokens import Colors, FluentTokens

logger = get_logger().bind(component="QtWidgets")

__all__ = [
    "BOTH",
    "BOTTOM",
    "DISABLED",
    "END",
    "HORIZONTAL",
    "INVALID_MODEL_INDEX",
    "LEFT",
    "NORMAL",
    "RIGHT",
    "TOP",
    "VERTICAL",
    "Button",
    "CheckBox",
    "ComboBox",
    "Dialog",
    "Entry",
    "Frame",
    "Label",
    "LineEdit",
    "MessageBox",
    "Notebook",
    "PlainWindow",
    "ProgressBar",
    "PushButton",
    "RadioButton",
    "ScrollableFrame",
    "Scrollbar",
    "SearchFilter",
    "SearchLineEdit",
    "Slider",
    "Spinbox",
    "TextBox",
    "Theme",
    "Treeview",
    "X",
    "Y",
    "apply_fluent_theme",
    "ensure_app",
    "get_existing_directory",
    "get_open_file_name",
    "get_save_file_name",
    "setTheme",
    "setThemeColor",
]

# Tkinter 相容常數
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
_QAbstractItemModel: Any = QtCore.QAbstractItemModel


@dataclass(slots=True)
class SearchFilter:
    """搜尋元件共用的文字篩選器。"""

    case_sensitive: bool = False
    normalize_whitespace: bool = True
    require_all_terms: bool = True

    def normalize(self, value: Any) -> str:
        """
        正規化搜尋文字。

        Args:
            value: 要轉成搜尋字串的任意值。

        Returns:
            正規化後的搜尋字串。
        """
        text = str(value or "").strip()
        if self.normalize_whitespace:
            text = re.sub(r"\s+", " ", text)
        return text if self.case_sensitive else text.lower()

    def matches(self, candidate: Any, query: Any) -> bool:
        """
        判斷候選文字是否符合查詢字串。

        Args:
            candidate: 被比對的候選值；可為字串、序列或 dict。
            query: 使用者輸入的查詢值。

        Returns:
            候選值符合查詢時回傳 True。
        """
        normalized_query = self.normalize(query)
        if not normalized_query:
            return True
        candidate_text = " ".join(self.normalize(value) for value in self._candidate_values(candidate))
        if not candidate_text:
            return False
        if not self.require_all_terms:
            return normalized_query in candidate_text
        return all(term in candidate_text for term in normalized_query.split())

    def matches_any(self, candidates: Any, query: Any) -> bool:
        """
        判斷多個候選欄位是否符合查詢。

        Args:
            candidates: 字串、序列或 dict 候選欄位。
            query: 使用者輸入的搜尋字串。

        Returns:
            任一候選欄位符合查詢時回傳 True。
        """
        return self.matches(candidates, query)

    def _candidate_values(self, candidate: Any) -> list[Any]:
        if isinstance(candidate, Mapping):
            return list(candidate.values())
        if isinstance(candidate, (list, tuple, set, frozenset)):
            return list(candidate)
        return [candidate]


def apply_fluent_theme(*, dark: bool, accent_color: str | None = None) -> None:
    """
    在 qfluentwidgets 可用時套用 Fluent 主題。

    Args:
        dark: 是否套用深色主題。
        accent_color: Fluent accent 色碼；未提供時使用專案主要按鈕色。
    """
    try:
        setTheme(Theme.DARK if dark else Theme.LIGHT)
        if setThemeColor is not None:
            setThemeColor(accent_color or Colors.BUTTON_PRIMARY[0])
        # 設定 qfluentwidgets 使用與專案一致的字型家族，避免 fallback 時出現 -1 point size 警告
        if setFontFamilies is not None:
            setFontFamilies(["Microsoft JhengHei UI", "Microsoft JhengHei", "Noto Sans CJK TC", "Segoe UI"])
    except Exception:
        return


def ensure_app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv[:1])
    return app


def is_dark_color_scheme() -> bool:
    """是否使用深色主題。"""
    app = cast(Any, QtWidgets.QApplication.instance())
    if app is None:
        return False
    with contextlib.suppress(Exception):
        scheme = app.styleHints().colorScheme()
        if scheme == QtCore.Qt.ColorScheme.Dark:
            return True
        if scheme == QtCore.Qt.ColorScheme.Light:
            return False
    window_color = app.palette().color(QtGui.QPalette.ColorRole.Window)
    return window_color.lightness() < 128


def native_parent(parent: Any) -> Any:
    """對話框/訊息框專用：parent 為 None 時備援尋找 activeWindow，確保彈出視窗可置中與遮罩定位。"""
    raw_parent = getattr(parent, "_qt_widget", parent)
    if raw_parent is not None and isinstance(raw_parent, QtCore.QObject) and not is_qobject_alive(raw_parent):
        raw_parent = None

    if raw_parent is None:
        app = cast(Any, QtWidgets.QApplication.instance())
        if app is not None:
            active = app.activeWindow()
            if active is not None and is_qobject_alive(active):
                raw_parent = active
            else:
                for widget in app.topLevelWidgets():
                    if (
                        widget.isVisible()
                        and is_qobject_alive(widget)
                        and not widget.windowFlags() & (QtCore.Qt.WindowType.ToolTip | QtCore.Qt.WindowType.Popup)
                    ):
                        raw_parent = widget
                        break
    return raw_parent


def _native_parent_simple(parent: Any) -> Any:
    """普通靜態元件專用：僅取原生 QWidget，不進行 activeWindow 備援綁定，避免生命週期過度連結與 Qt parent 變更警告。"""
    raw_parent = getattr(parent, "_qt_widget", parent)
    if raw_parent is not None and isinstance(raw_parent, QtCore.QObject) and not is_qobject_alive(raw_parent):
        return None
    return raw_parent


def _qt_class(name: str) -> Any:
    return getattr(QtWidgets, name)


def _is_qt_instance(widget: Any, *class_names: str) -> bool:
    return any(isinstance(widget, _qt_class(class_name)) for class_name in class_names)


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
    if isinstance(value, str) and hasattr(FluentTokens, value.upper()):
        return FluentTokens.qss_value(getattr(FluentTokens, value.upper()))
    if isinstance(value, tuple):
        index = 1 if is_dark_color_scheme() and len(value) > 1 else 0
        return _color(value[index])
    if value in (None, "transparent"):
        return "transparent"
    return str(value)


def _font(value: Any = None, *, size_token: str | None = None, weight_token: str | None = None):
    if hasattr(value, "font"):
        value = value.font
    if isinstance(value, QtGui.QFont):
        font = value
    else:
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

    if size_token and hasattr(FluentTokens, size_token.upper()):
        font.setPointSize(getattr(FluentTokens, size_token.upper()))
    if weight_token and hasattr(FluentTokens, weight_token.upper()):
        weight_val = getattr(FluentTokens, weight_token.upper())
        font.setWeight(weight_val)

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


def _apply_fluent_style(
    widget: QtWidgets.QWidget, light_qss: str = "", dark_qss: str = "", *, preserve_native: bool = True
) -> None:
    """
    在保留 Fluent 原生樣式的前提下疊加自訂樣式

    Args:
        preserve_native: True 時使用 setCustomStyleSheet（疊加），
                         False 時使用 setStyleSheet（完全覆寫）
    """
    if preserve_native:
        setCustomStyleSheet(widget, light_qss, dark_qss)
    else:
        widget.setStyleSheet(light_qss if not isDarkTheme() else dark_qss)


def _build_qss(
    *,
    bg: Any = None,
    fg: Any = None,
    border: Any = None,
    radius: Any = None,
    padding: tuple[int, int] = (0, 0),
    hover_bg: Any = None,
    pressed_bg: Any = None,
    focus_border: Any = None,
) -> tuple[str, str]:
    """
    建構亮/暗雙主題 QSS，自動解析 Token
    回傳: (light_qss, dark_qss)
    """

    def resolve(v):
        return _color(v) if v is not None else None

    light_parts = []
    dark_parts = []

    # 基礎屬性
    for prop, light_val, dark_val in [
        ("background-color", resolve(bg), resolve(bg)),
        ("color", resolve(fg), resolve(fg)),
        (
            "border",
            f"1px solid {resolve(border)}" if border else "none",
            f"1px solid {resolve(border)}" if border else "none",
        ),
        ("border-radius", f"{int(radius)}px" if radius else "0", f"{int(radius)}px" if radius else "0"),
        ("padding", f"{padding[1]}px {padding[0]}px", f"{padding[1]}px {padding[0]}px"),
    ]:
        if light_val:
            light_parts.append(f"{prop}: {light_val};")
        if dark_val:
            dark_parts.append(f"{prop}: {dark_val};")

    # 狀態樣式
    states = []
    if hover_bg:
        states.append(f":hover {{ background-color: {resolve(hover_bg)}; }}")
    if pressed_bg:
        states.append(f":pressed {{ background-color: {resolve(pressed_bg)}; }}")
    if focus_border:
        states.append(f":focus {{ border: 1px solid {resolve(focus_border)}; }}")

    light_qss = " ".join(light_parts + states)
    dark_qss = " ".join(dark_parts + states)

    return light_qss, dark_qss


def _apply_size_policy(widget: Any, kwargs: dict[str, Any]) -> None:
    if not hasattr(widget, "setSizePolicy"):
        return
    fill = str(kwargs.get("fill", "") or "").lower()
    expand = bool(kwargs.get("expand", False))
    sticky = str(kwargs.get("sticky", "") or "").lower()
    has_n_s = "n" in sticky and "s" in sticky
    has_e_w = "e" in sticky and "w" in sticky

    horizontal = (
        QtWidgets.QSizePolicy.Policy.Expanding
        if expand or fill in (X, BOTH) or has_e_w
        else QtWidgets.QSizePolicy.Policy.Preferred
    )
    vertical = (
        QtWidgets.QSizePolicy.Policy.Expanding
        if expand or fill in (Y, BOTH) or has_n_s
        else QtWidgets.QSizePolicy.Policy.Preferred
    )
    widget.setSizePolicy(horizontal, vertical)


class context_suppress:
    def __enter__(self):
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return True


class Variable(ValueState):
    def __init__(self, value: Any = None) -> None:
        super().__init__(value)
        self._callbacks: list[Callable[..., Any]] = []

    def set(self, value: Any) -> None:
        """設定目前值或顯示狀態。"""
        if self._value == value:
            return
        super().set(value)
        for callback in list(self._callbacks):
            callback()


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
        """估算指定文字在目前字型下的寬度。"""
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
            if mode == "grid" and not isinstance(existing, QtWidgets.QGridLayout) and existing.count() == 0:
                margins = existing.contentsMargins()
                spacing = existing.spacing()
                QtWidgets.QWidget().setLayout(existing)
                grid: Any = QtWidgets.QGridLayout()
                grid.setContentsMargins(margins)
                grid.setSpacing(spacing)
                cast(Any, self).setLayout(grid)
                self._layout_mode = mode
                return grid
            return existing
        padding = getattr(self, "_padding", None)
        layout: Any
        if mode == "grid":
            layout = QtWidgets.QGridLayout()
        elif mode == "hbox":
            layout = QtWidgets.QHBoxLayout()
        else:
            layout = QtWidgets.QVBoxLayout()
        if padding is not None:
            layout.setContentsMargins(padding, padding + 10, padding, padding)
        else:
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
            existing_layout: Any = None
            with contextlib.suppress(AttributeError, RuntimeError):
                existing_layout = parent.layout()
            if existing_layout is not None:
                if (
                    mode == "grid"
                    and not isinstance(existing_layout, QtWidgets.QGridLayout)
                    and existing_layout.count() == 0
                ):
                    margins = existing_layout.contentsMargins()
                    spacing = existing_layout.spacing()
                    QtWidgets.QWidget().setLayout(existing_layout)
                    layout = QtWidgets.QGridLayout()
                    layout.setContentsMargins(margins)
                    layout.setSpacing(spacing)
                    parent.setLayout(layout)
                else:
                    layout = existing_layout
            elif hasattr(parent, "setLayout"):
                if mode == "grid":
                    layout = QtWidgets.QGridLayout()
                elif mode == "hbox":
                    layout = QtWidgets.QHBoxLayout()
                else:
                    layout = QtWidgets.QVBoxLayout()
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(6)
                try:
                    if parent.layout() is None:
                        parent.setLayout(layout)
                    else:
                        layout = parent.layout()
                except AttributeError, RuntimeError:
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
        """將元件加入父層布局並套用布局參數。"""
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
                with contextlib.suppress(AttributeError):
                    delattr(self, "_layout_resize_previous_limits")
            if hasattr(self_widget, "setUpdatesEnabled"):
                self_widget.setUpdatesEnabled(True)
            return

        if getattr(self, "_layout_resize_previous_limits", None) is None:
            self._layout_resize_previous_limits = (self_widget.minimumSize(), self_widget.maximumSize())

        if hasattr(self_widget, "setUpdatesEnabled"):
            self_widget.setUpdatesEnabled(False)

    def _apply_fluent_style_config(self, kwargs: dict[str, Any]) -> None:
        """使用疊加模式套用樣式，保留 Fluent 原生外觀"""
        widget = cast(Any, self)

        # 解析參數
        bg = kwargs.get("fg_color", kwargs.get("bg", kwargs.get("background")))
        fg = kwargs.get("text_color", kwargs.get("fg", kwargs.get("foreground")))
        border = kwargs.get("border_color")
        radius = kwargs.get("corner_radius", kwargs.get("border_radius"))
        hover = kwargs.get("hover_color", kwargs.get("button_hover_color"))
        pressed = kwargs.get("pressed_color")
        focus = kwargs.get("focus_color")

        # Padding 處理
        padx = _padding_pair(kwargs.get("padx", kwargs.get("padding", (0, 0))))[0]
        pady = _padding_pair(kwargs.get("pady", kwargs.get("padding", (0, 0))))[1]

        # 決定是否保留原生樣式
        preserve_native = not kwargs.get("_override_native_style", False)

        # 特定元件的預設樣式增強
        extra_qss = ""
        if _is_qt_instance(self, "QPushButton"):
            # 按鈕預設保留 Fluent 圓角、動畫等
            if radius is None:
                radius = FluentTokens.BORDER_RADIUS_MD
            if border is None:
                extra_qss = "border: none;"
        elif _is_qt_instance(self, "QLineEdit") or _is_qt_instance(self, "QComboBox"):
            if radius is None:
                radius = FluentTokens.BORDER_RADIUS_SM

        light_qss, dark_qss = _build_qss(
            bg=bg,
            fg=fg,
            border=border,
            radius=radius,
            padding=(padx, pady),
            hover_bg=hover,
            pressed_bg=pressed,
            focus_border=focus,
        )

        # 合併額外 QSS
        if extra_qss:
            light_qss = extra_qss + " " + light_qss
            dark_qss = extra_qss + " " + dark_qss

        _apply_fluent_style(widget, light_qss, dark_qss, preserve_native=preserve_native)

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
        """更新元件設定並套用到實際 Qt widget。"""
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

        # 尺寸處理 - 支援 Token
        size_props = {
            "width": "setFixedWidth",
            "height": "setFixedHeight",
            "min_width": "setMinimumWidth",
            "min_height": "setMinimumHeight",
        }
        for prop, setter in size_props.items():
            if prop in kwargs and hasattr(self_widget, setter):
                val = kwargs[prop]
                if (
                    prop == "height"
                    and _is_qt_instance(self_widget, "QAbstractItemView")
                    and isinstance(val, (int, float))
                    and val <= 100
                ):
                    continue
                if isinstance(val, str) and hasattr(FluentTokens, val.upper()):
                    val = getattr(FluentTokens, val.upper())
                with context_suppress():
                    getattr(self_widget, setter)(int(val))

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

        # 樣式處理 - 使用新疊加模式
        style_keys = {
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
            "pressed_color",
            "focus_color",
            "padding",
            "padx",
            "pady",
            "progress_color",
        }
        if any(k in kwargs for k in style_keys):
            self._apply_fluent_style_config(kwargs)
            self._last_style_kwargs = kwargs

    config = configure

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

    def _event_from_qt(self, qt_event: Any = None) -> Any:
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
        return type(
            "Event",
            (),
            {
                "widget": self,
                "x": x,
                "y": y,
                "x_root": x_root,
                "y_root": y_root,
                "width": width,
                "height": height,
                "delta": delta,
                "keysym": keysym,
            },
        )()

    def _dispatch_event(self, event_name: str, qt_event: Any = None) -> bool:
        callback = self._event_handlers.get(event_name)
        if callback is None:
            logger.debug(
                f"_dispatch_event: no handler for '{event_name}', available={list(self._event_handlers.keys())}",
                "WidgetMixin",
            )
            return False
        logger.debug(f"_dispatch_event: calling handler for '{event_name}'", "WidgetMixin")
        result = callback(self._event_from_qt(qt_event))
        return result == "break"

    def eventFilter(self, watched: Any, event: Any) -> bool:
        """攔截 Qt 事件並依目前元件狀態處理。"""
        watched_self = watched is self
        with context_suppress():
            is_header = watched is cast(Any, self).header()
            self._dispatching_header_event = is_header
            watched_self = watched_self or watched is cast(Any, self).viewport() or is_header
        if not watched_self:
            return False
        event_type = event.type()
        event_names: list[str] = []
        if event_type == QtCore.QEvent.Type.MouseButtonPress:
            button = event.button()
            if button == QtCore.Qt.MouseButton.LeftButton:
                event_names.append("mouse_left_press")
        elif event_type == QtCore.QEvent.Type.MouseButtonRelease:
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                event_names.append("mouse_left_release")
        elif event_type == QtCore.QEvent.Type.MouseButtonDblClick:
            logger.debug(f"eventFilter MouseButtonDblClick: button={event.button()}", "WidgetMixin")
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                event_names.append("mouse_double_click")
        elif event_type == QtCore.QEvent.Type.ContextMenu:
            event_names.append("mouse_right_press")
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
        """建立延遲執行的 Qt 計時器工作。"""
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
        """銷毀元件並清理底層 Qt 資源。"""
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

    def _on_theme_changed(self) -> None:
        """主題切換時自動重新套用樣式"""
        if hasattr(self, "_last_style_kwargs") and self._last_style_kwargs:
            self.configure(**self._last_style_kwargs)

    def clipboard_clear(self) -> None:
        app = ensure_app()
        app.clipboard().clear()

    def clipboard_append(self, text: str) -> None:
        app = ensure_app()
        app.clipboard().setText(str(text))


# =============================================================================
# Fluent 原生元件包裝器
# =============================================================================


class PlainWindow(WidgetMixin, QtWidgets.QWidget):
    """無側邊欄的純內容視窗，用於對話框與彈出視窗。"""

    def __init__(self, parent: Any = None, title: str = "", resizable: bool = True, **kwargs: Any) -> None:
        flags = (
            QtCore.Qt.WindowType.Window
            | QtCore.Qt.WindowType.WindowCloseButtonHint
            | QtCore.Qt.WindowType.WindowTitleHint
        )
        if resizable:
            flags |= QtCore.Qt.WindowType.WindowMinMaxButtonsHint
        QtWidgets.QWidget.__init__(self, _native_parent_simple(parent), flags)
        self.setWindowTitle(title)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._close_event_handler: Callable[..., Any] | None = None
        self._init_native(parent, **kwargs)

    def set_close_event_handler(self, handler: Callable[..., Any]) -> None:
        """設定關閉事件處理器，於視窗關閉時呼叫。"""
        self._close_event_handler = handler

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._close_event_handler is not None:
            self._close_event_handler(event)
        super().closeEvent(event)

    def accept(self) -> None:
        self._modal_result = True
        self.close()

    def reject(self) -> None:
        self._modal_result = False
        self.close()

    def destroy(self, *_args, **_kwargs) -> None:
        self._exists = False
        with context_suppress():
            self.close()
        with context_suppress():
            self.deleteLater()


class Frame(WidgetMixin, QtWidgets.QFrame):
    def __init__(self, parent: Any = None, **kwargs: Any) -> None:
        QtWidgets.QFrame.__init__(self, _native_parent_simple(parent))
        self._init_native(parent, **kwargs)


class ScrollableFrame(WidgetMixin, FluentScrollArea):
    def __init__(self, parent: Any = None, **kwargs: Any) -> None:
        FluentScrollArea.__init__(self, _native_parent_simple(parent))
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


class Label(WidgetMixin, BodyLabel):
    def __init__(self, parent: Any = None, text: str = "", **kwargs: Any) -> None:
        BodyLabel.__init__(self, _native_parent_simple(parent))
        self.setText(str(text))
        self._init_native(parent, text=str(text), **kwargs)
        if "wraplength" in kwargs:
            self.setWordWrap(True)
        self.setAlignment(_align(kwargs.get("anchor")))


class SubtitleLabel(WidgetMixin, FluentSubtitleLabel):
    def __init__(self, parent: Any = None, text: str = "", **kwargs: Any) -> None:
        FluentSubtitleLabel.__init__(self, _native_parent_simple(parent))
        self.setText(str(text))
        self._init_native(parent, text=str(text), **kwargs)


class HyperlinkLabel(WidgetMixin, FluentHyperlinkLabel):
    def __init__(self, parent: Any = None, text: str = "", url: str = "", **kwargs: Any) -> None:
        FluentHyperlinkLabel.__init__(self, _native_parent_simple(parent))
        self.setUrl(url)
        self.setText(str(text))
        self._init_native(parent, text=str(text), **kwargs)


def _apply_button_command(button: Any, kwargs: dict[str, Any]) -> None:
    """共用邏輯：從 configure kwargs 中提取 command 並重新綁定。"""
    command = kwargs.pop("command", None)
    if command is not None:
        with context_suppress():
            button.clicked.disconnect()
        button._command = command
        button.clicked.connect(button._invoke_command)


def _invoke_button_command(button: Any) -> None:
    """共用邏輯：執行按鈕綁定的 command。"""
    cmd = getattr(button, "_command", None)
    if cmd:
        cmd()


class Button(WidgetMixin, FluentPushButton):
    def __init__(
        self,
        parent: Any = None,
        text: str = "",
        command: Callable[..., Any] | None = None,
        **kwargs: Any,
    ):
        FluentPushButton.__init__(self, _native_parent_simple(parent))
        self.setText(str(text))
        self._command = command
        if command is not None:
            self.clicked.connect(self._invoke_command)
        self._init_native(parent, text=text, **kwargs)

    def _invoke_command(self, *_args: Any) -> None:
        _invoke_button_command(self)

    def configure(self, **kwargs: Any) -> None:
        """更新元件設定並套用到實際 Qt widget。"""
        _apply_button_command(self, kwargs)
        if "width" in kwargs:
            kwargs["min_width"] = kwargs.pop("width")
        super().configure(**kwargs)

    def set_accent(self, accent: bool = True) -> None:
        """一鍵切換強調色樣式"""
        if accent:
            self.configure(
                fg_color=FluentTokens.PRIMARY,
                text_color="#ffffff",
                hover_color=FluentTokens.HOVER,
                pressed_color=FluentTokens.PRESSED,
                corner_radius=FluentTokens.BORDER_RADIUS_MD,
            )
        else:
            self.configure(
                fg_color=FluentTokens.SURFACE,
                text_color=FluentTokens.TEXT_PRIMARY,
                border_color=FluentTokens.BORDER,
                hover_color=FluentTokens.HOVER,
                corner_radius=FluentTokens.BORDER_RADIUS_MD,
            )


class Entry(WidgetMixin, FluentLineEdit):
    def __init__(
        self,
        parent: Any = None,
        **kwargs: Any,
    ):
        FluentLineEdit.__init__(self, _native_parent_simple(parent))
        self._init_native(parent, **kwargs)

    def insert(self, index: Any, text: str | None = None) -> None:
        """插入項目或文字內容。"""
        insert_text = str(index if text is None else text)
        if index in (0, "0"):
            self.setText(insert_text + self.text())
        else:
            self.setText(self.text() + insert_text)

    def select_range(self, start: int, end: Any) -> None:
        length = len(self.text()) if end == END else int(end) - int(start)
        self.setSelection(int(start), max(0, length))

    def set_error_state(self, is_error: bool) -> None:
        """輸入框錯誤狀態"""
        if is_error:
            self.configure(
                border_color="#dc2626",  # 紅色
                focus_color="#dc2626",
            )
        else:
            self.configure(
                border_color=FluentTokens.BORDER,
                focus_color=FluentTokens.PRIMARY,
            )


class SearchEntry(WidgetMixin, FluentSearchLineEdit):
    """SearchLineEdit 包裝器，支援專案狀態綁定與過濾邏輯。"""

    def __init__(
        self,
        parent: Any = None,
        textvariable: Variable | None = None,
        search_command: Callable[..., Any] | None = None,
        filter_logic: SearchFilter | None = None,
        **kwargs: Any,
    ):
        FluentSearchLineEdit.__init__(self, _native_parent_simple(parent))
        self._variable = textvariable
        self._search_command = search_command
        self.filter_logic = filter_logic or SearchFilter()
        if hasattr(self, "setClearButtonEnabled"):
            with context_suppress():
                self.setClearButtonEnabled(True)
        if textvariable is not None:
            self.setText(str(textvariable.get()))
            self.textChanged.connect(textvariable.set)
            textvariable.trace_add("write", lambda *_: self._sync_from_variable())
        with context_suppress():
            self.searchSignal.connect(self._on_search_signal)
        with context_suppress():
            self.clearSignal.connect(self._on_clear_signal)
        if hasattr(self, "returnPressed"):
            self.returnPressed.connect(self._on_search_signal)
        self._init_native(parent, **kwargs)

    def _sync_from_variable(self) -> None:
        if self._variable is None:
            return
        value = str(self._variable.get())
        if self.text() != value:
            self.setText(value)

    def _on_search_signal(self, *_args: Any) -> None:
        if self._search_command is not None:
            self._search_command()
        self._dispatch_event("search")

    def _on_clear_signal(self, *_args: Any) -> None:
        if self._variable is not None:
            self._variable.set("")
        self._dispatch_event("clear")

    def filter_text(self) -> str:
        return self.filter_logic.normalize(self.text())

    def matches(self, candidate: Any) -> bool:
        """檢查目前輸入是否符合搜尋條件。"""
        return self.filter_logic.matches(candidate, self.text())


class TextBox(WidgetMixin, FluentTextEdit):
    def __init__(self, parent: Any = None, **kwargs: Any) -> None:
        FluentTextEdit.__init__(self, _native_parent_simple(parent))
        self._init_native(parent, **kwargs)

    def insert(self, index: Any, text: str) -> None:
        """插入項目或文字內容。"""
        if index in (END, "end"):
            self.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        self.insertPlainText(str(text))

    def see(self, *_args: Any) -> None:
        """捲動到指定位置或項目。"""
        self.moveCursor(QtGui.QTextCursor.MoveOperation.End)

    def yview_scroll(self, number: int, _what: str = "units") -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + int(number) * bar.singleStep())

    def yview_moveto(self, fraction: float) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(int(float(fraction) * bar.maximum()))


class CheckBox(WidgetMixin, FluentCheckBox):
    def __init__(
        self,
        parent: Any = None,
        text: str = "",
        variable: Variable | None = None,
        command=None,
        **kwargs,
    ):
        FluentCheckBox.__init__(self, _native_parent_simple(parent))
        self.setText(str(text))
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
        was_blocked = self.blockSignals(True)
        try:
            self.setChecked(checked)
        finally:
            self.blockSignals(was_blocked)


class RadioButton(WidgetMixin, FluentRadioButton):
    def __init__(
        self,
        parent: Any = None,
        text: str = "",
        variable: Variable | None = None,
        value: Any = None,
        command: Callable[..., Any] | None = None,
        **kwargs: Any,
    ):
        FluentRadioButton.__init__(self, _native_parent_simple(parent))
        self.setText(str(text))
        self._variable = variable
        self._value = value
        self._command = command
        if variable is not None:
            self.setChecked(variable.get() == value)
            self.toggled.connect(lambda checked: variable.set(value) if checked else None)
        if command is not None:
            self.toggled.connect(lambda checked: command() if checked else None)
        self._init_native(parent, text=text, **kwargs)


class Slider(WidgetMixin, FluentSlider):
    def __init__(
        self,
        parent: Any = None,
        from_: float = 0.0,
        to: float = 1.0,
        command=None,
        variable: Variable | None = None,
        **kwargs,
    ):
        FluentSlider.__init__(self, _native_parent_simple(parent))
        self._scale = 100
        self.setOrientation(QtCore.Qt.Orientation.Horizontal)
        self.setRange(int(from_ * self._scale), int(to * self._scale))
        self._command = command
        self._variable = variable
        if variable is not None:
            self.setValue(int(float(variable.get()) * self._scale))
            self.valueChanged.connect(lambda v: variable.set(v / self._scale))
            variable.trace_add("write", lambda *_: self._sync_from_variable())
        if command is not None:
            self.valueChanged.connect(lambda _v: command())
        self._init_native(parent, **kwargs)

    def _sync_from_variable(self) -> None:
        if self._variable is None:
            return
        value = int(float(self._variable.get()) * self._scale)
        if self.value() == value:
            return
        was_blocked = self.blockSignals(True)
        try:
            self.setValue(value)
        finally:
            self.blockSignals(was_blocked)

    def set(self, value: float) -> None:
        """設定滑桿值。"""
        self.setValue(int(value * self._scale))


class ProgressBar(WidgetMixin, FluentProgressBarWidget):
    def __init__(self, parent: Any = None, **kwargs: Any) -> None:
        FluentProgressBarWidget.__init__(self, _native_parent_simple(parent))
        self._init_native(parent, **kwargs)
        self.setTextVisible(True)
        self.setFormat("%p%")
        self.setVal(0)

    def value(self) -> int:
        """回傳目前進度值（取自 _val 並轉為 int，避免 float 顯示為 25.0%）。"""
        val = getattr(self, "_val", None)
        if val is not None:
            return int(val)
        return super().value()

    def text(self) -> str:
        """回傳進度文字，確保值為 0 時仍顯示 0%。"""
        return f"{self.value()}%"

    def set(self, value: float) -> None:
        """設定進度值 (0.0 - 1.0)，同步 Qt 原生進度狀態以維持 valueChanged 訊號。"""
        val_int = int(value * 100)
        self.setVal(val_int)
        super().setValue(val_int)

    def setRange(self, min_val: int, max_val: int) -> None:
        self.setMinimum(min_val)
        self.setMaximum(max_val)

    def setValue(self, value: int) -> None:
        self.setVal(value)
        super().setValue(value)

    def start(self) -> None:
        """啟動不定進度模式"""
        self.setRange(0, 0)

    def stop(self) -> None:
        """停止不定進度模式"""
        self.setRange(0, 100)


class ComboBox(WidgetMixin, FluentComboBox):
    def __init__(
        self,
        parent: Any = None,
        values: list[str] | None = None,
        variable: Variable | None = None,
        command: Callable[..., Any] | None = None,
        **kwargs: Any,
    ):
        FluentComboBox.__init__(self, _native_parent_simple(parent))
        self._variable = variable
        self._command = command
        if values:
            self.addItems(values)
        if variable is not None:
            self.setCurrentText(str(variable.get()))
            self.currentTextChanged.connect(variable.set)
            variable.trace_add("write", lambda *_: self._sync_from_variable())
        if command is not None:
            self.currentTextChanged.connect(lambda _: command())
        self._init_native(parent, **kwargs)

    def _sync_from_variable(self) -> None:
        if self._variable is None:
            return
        value = str(self._variable.get())
        if self.currentText() == value:
            return
        was_blocked = self.blockSignals(True)
        try:
            index = self.findText(value)
            if index >= 0:
                self.setCurrentIndex(index)
        finally:
            self.blockSignals(was_blocked)

    def configure(self, **kwargs: Any) -> None:
        values = kwargs.pop("values", None)
        if values is not None:
            self.clear()
            self.addItems(values)
        state = kwargs.pop("state", None)
        if state is not None:
            self.setEnabled(str(state) != DISABLED)
        super().configure(**kwargs)

    def set(self, value: str) -> None:
        index = self.findText(value)
        if index >= 0:
            self.setCurrentIndex(index)


class Treeview(WidgetMixin, QtWidgets.QTreeView):
    def __init__(
        self,
        parent: Any = None,
        columns: list[str] | tuple[str, ...] | None = None,
        show: str = "headings",
        selectmode: str = "browse",
        **kwargs: Any,
    ):
        QtWidgets.QTreeView.__init__(self, _native_parent_simple(parent))
        self._columns: list[str] = list(columns) if columns else []
        self._show = show
        self._model = QtGui.QStandardItemModel()
        self._items: dict[str, QtGui.QStandardItem] = {}
        self._item_rows: dict[str, list[QtGui.QStandardItem]] = {}
        self._item_tags: dict[str, tuple] = {}
        self._tag_styles: dict[str, dict[str, str]] = {}
        self._detached: dict[str, list[QtGui.QStandardItem]] = {}
        self._detached_tags: dict[str, tuple] = {}
        self.setModel(self._model)
        if columns:
            self._model.setHorizontalHeaderLabels(columns)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self._apply_selectmode(selectmode)
        self.setAlternatingRowColors(True)
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.header().setStretchLastSection(True)
        self.header().setSectionsClickable(True)
        self._init_native(parent, **kwargs)

    # ── 內部輔助 ──────────────────────────────────────────────

    def _apply_selectmode(self, mode: str) -> None:
        mode_map = {
            "browse": QtWidgets.QAbstractItemView.SelectionMode.SingleSelection,
            "extended": QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection,
            "single": QtWidgets.QAbstractItemView.SelectionMode.SingleSelection,
            "multiple": QtWidgets.QAbstractItemView.SelectionMode.MultiSelection,
            "none": QtWidgets.QAbstractItemView.SelectionMode.NoSelection,
        }
        self.setSelectionMode(mode_map.get(mode, QtWidgets.QAbstractItemView.SelectionMode.SingleSelection))

    def _row_of(self, item_id: str) -> int:
        """回傳 item_id 對應的 model row，若已 detach 則回傳 -1。"""
        if item_id in self._items:
            return self._items[item_id].row()
        return -1

    def _find_iid_by_row(self, row: int) -> str | None:
        for iid, item in self._items.items():
            if item.row() == row:
                return iid
        return None

    # ── 欄位與標題 ────────────────────────────────────────────

    def heading(self, column: str, option: str | None = None, **kwargs: Any) -> Any:
        """讀取或設定欄位標題。heading(col, 'text') 回傳標題文字；heading(col, text=...) 設定標題。"""
        col_index = self._columns.index(column) if column in self._columns else 0
        if option == "text":
            data = self._model.headerData(col_index, QtCore.Qt.Orientation.Horizontal)
            return str(data) if data else ""
        if "text" in kwargs:
            self._model.setHeaderData(col_index, QtCore.Qt.Orientation.Horizontal, kwargs["text"])
        return None

    def column(self, column: str, option: str | None = None, **kwargs: Any) -> Any:
        """讀取或設定欄位屬性。column(col, 'width') 回傳寬度；column(col, width=...) 設定寬度。"""
        col_index = self._columns.index(column) if column in self._columns else 0
        if option == "width":
            return self.columnWidth(col_index)
        if option == "minwidth":
            return self.header().minimumSectionSize()
        if option == "stretch":
            return self.header().sectionResizeMode(col_index) == QtWidgets.QHeaderView.ResizeMode.Stretch
        if "width" in kwargs:
            self.setColumnWidth(col_index, int(kwargs["width"]))
        if "minwidth" in kwargs:
            self.header().setMinimumSectionSize(int(kwargs["minwidth"]))
        if "stretch" in kwargs:
            self.header().setSectionResizeMode(
                col_index,
                QtWidgets.QHeaderView.ResizeMode.Stretch
                if kwargs["stretch"]
                else QtWidgets.QHeaderView.ResizeMode.Interactive,
            )
        return None

    def identify_column(self, x: int) -> str:
        """依 x 座標回傳欄位識別字串（如 '#0' 或欄位名稱）。"""
        col = self.columnAt(x)
        if col < 0:
            return "#0"
        if col < len(self._columns):
            return self._columns[col]
        return f"#{col}"

    def identify_row(self, y: int, x: int | None = None) -> str:
        """依 y (以及選擇性的 x) 座標回傳該列的 item ID。"""
        px = 10 if x is None else x
        index = self.indexAt(QtCore.QPoint(px, y))
        if not index.isValid():
            # 嘗試向右偏移一些避免滾動條/Margin干擾
            index = self.indexAt(QtCore.QPoint(50, y))
            if not index.isValid():
                return ""
        row = index.row()
        iid = self._find_iid_by_row(row)
        return iid if iid else str(row)

    def identify_region(self, x: int, y: int) -> str:
        """依座標回傳區域類型（'heading'/'cell'/'nothing'等）。"""
        if getattr(self, "_dispatching_header_event", False):
            return "heading"
        index = self.indexAt(QtCore.QPoint(x, y))
        if not index.isValid():
            return "nothing"
        return "cell"

    # ── 標籤樣式 ──────────────────────────────────────────────

    def tag_configure(self, tag: str, **kwargs: Any) -> None:
        """設定標籤樣式（背景、前景色等）。"""
        self._tag_styles[tag] = kwargs

    def _apply_tag_styles(self, items: list, tags: tuple) -> None:
        for tag in tags:
            style = self._tag_styles.get(tag, {})
            if "background" in style:
                bg = QtGui.QColor(style["background"])
                for item in items:
                    item.setBackground(bg)
            if "foreground" in style:
                fg = QtGui.QColor(style["foreground"])
                for item in items:
                    item.setForeground(fg)

    # ── 插入與刪除 ────────────────────────────────────────────

    def insert(
        self,
        iid: str | None = None,
        values: tuple = (),
        tags: tuple = (),
    ) -> str:
        row = self._model.rowCount()
        items = [QtGui.QStandardItem(str(v)) for v in values]
        for item in items:
            item.setEditable(False)
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        if tags:
            self._apply_tag_styles(items, tags)
        self._model.appendRow(items)
        item_id = iid if iid else str(row)
        self._items[item_id] = items[0]
        self._item_rows[item_id] = items
        if tags:
            self._item_tags[item_id] = tags
        return item_id

    def exists(self, item_id: str) -> bool:
        """檢查 item 是否存在。"""
        return item_id in self._items or item_id in self._detached

    def detach(self, *item_ids: str) -> None:
        """暫時從樹中隱藏 item。"""
        rows_to_remove: list[int] = []
        for item_id in item_ids:
            if item_id in self._items:
                row = self._items[item_id].row()
                if row >= 0:
                    rows_to_remove.append(row)
                self._detached[item_id] = self._item_rows.pop(item_id, [])
                self._detached_tags[item_id] = self._item_tags.pop(item_id, ())
                del self._items[item_id]
        for row in sorted(rows_to_remove, reverse=True):
            self._model.takeRow(row)

    def reattach(self, item_id: str) -> None:
        """重新顯示之前 detach 的 item。"""
        if item_id not in self._detached:
            return
        items = self._detached.pop(item_id)
        tags = self._detached_tags.pop(item_id, ())
        self._model.appendRow(items)
        self._items[item_id] = items[0]
        self._item_rows[item_id] = items
        if tags:
            self._item_tags[item_id] = tags

    def move_item(self, item_id: str, index: int) -> None:
        """移動 item 到指定位置。"""
        if item_id not in self._items:
            return
        row = self._items[item_id].row()
        if row < 0:
            return
        items = self._model.takeRow(row)
        if items:
            target = min(index, self._model.rowCount())
            self._model.insertRow(target, items)

    def index(self, item_id: str) -> int:
        """回傳 item 的列索引。"""
        if item_id in self._items:
            return self._items[item_id].row()
        return -1

    # ── 取值與設值 ────────────────────────────────────────────

    def item(
        self,
        item_id: str,
        option: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        讀取或更新 item 屬性。

        讀取模式：item(id, "values") → tuple / item(id, "tags") → tuple / item(id, "text") → str
        寫入模式：item(id, values=..., tags=..., open=...)
        無參數：item(id) → {"values": tuple(...), "tags": tuple(...), "text": str}
        """
        if item_id not in self._items:
            return "" if option else {}

        row = self._items[item_id].row()
        if row < 0:
            return "" if option else {}

        # 寫入模式
        if kwargs:
            if "values" in kwargs:
                new_vals = kwargs["values"]
                for col, val in enumerate(new_vals):
                    if col < self._model.columnCount():
                        self._model.setData(self._model.index(row, col), str(val))
            if "tags" in kwargs:
                new_tags = kwargs["tags"]
                if new_tags:
                    row_items = self._item_rows.get(item_id, [])
                    if row_items:
                        self._apply_tag_styles(row_items, new_tags)
            return None

        # 讀取模式 — 指定 option
        if option == "values":
            vals = []
            for col in range(self._model.columnCount()):
                vals.append(self._model.data(self._model.index(row, col)))
            return tuple(vals)
        if option == "tags":
            return self._item_tags.get(item_id, ())
        if option == "text":
            return str(self._model.data(self._model.index(row, 0)) or "")

        # 讀取模式 — 無 option，回傳完整 dict
        vals = []
        for col in range(self._model.columnCount()):
            vals.append(self._model.data(self._model.index(row, col)))
        return {"values": tuple(vals), "tags": (), "text": str(vals[0]) if vals else ""}

    def get_children(self, parent: str = "") -> list[str]:
        if parent:
            return []
        return [str(i) for i in range(self._model.rowCount())]

    def parent_item(self, _item_id: str = "") -> str:
        """回傳父項目 ID（扁平模型永遠回傳空字串）。"""
        return ""

    # ── 選取 ──────────────────────────────────────────────────

    def selection(self) -> list[str]:
        """回傳目前選取的項目 ID 清單（有序）。"""
        selected: list[str] = []
        for index in self.selectionModel().selectedRows():
            row = index.row()
            iid = self._find_iid_by_row(row)
            if iid:
                selected.append(iid)
        return selected

    def selection_set(self, *item_ids: str) -> None:
        self.selectionModel().clearSelection()
        for item_id in item_ids:
            if item_id in self._items:
                row = self._items[item_id].row()
                if row >= 0:
                    index = self._model.index(row, 0)
                    self.selectionModel().select(
                        index,
                        QtCore.QItemSelectionModel.SelectionFlag.Select | QtCore.QItemSelectionModel.SelectionFlag.Rows,
                    )

    def selection_remove(self, *item_ids: str) -> None:
        """取消選取指定 item。"""
        for item_id in item_ids:
            if item_id in self._items:
                row = self._items[item_id].row()
                if row >= 0:
                    index = self._model.index(row, 0)
                    self.selectionModel().select(
                        index,
                        QtCore.QItemSelectionModel.SelectionFlag.Deselect
                        | QtCore.QItemSelectionModel.SelectionFlag.Rows,
                    )

    def see(self, item_id: str) -> None:
        if item_id in self._items:
            row = self._items[item_id].row()
            if row >= 0:
                self.scrollTo(self._model.index(row, 0))

    # ── 捲動 ──────────────────────────────────────────────────

    def yview(self, *args: Any) -> Any:
        """垂直捲動（供 Scrollbar command 使用）。"""
        if args:
            self.verticalScrollBar().setValue(int(args[0]))
            return None
        return self.verticalScrollBar().value()

    def xview(self, *args: Any) -> Any:
        """水平捲動（供 Scrollbar command 使用）。"""
        if args:
            self.horizontalScrollBar().setValue(int(args[0]))
            return None
        return self.horizontalScrollBar().value()

    def yview_scroll(self, number: int, what: str) -> None:
        """滑鼠滾輪捲動。"""
        bar = self.verticalScrollBar()
        if what == "units":
            bar.setValue(bar.value() - number * bar.singleStep())
        elif what == "pages":
            bar.setValue(bar.value() - number * bar.pageStep())

    def connect_event(self, event_name: str, callback: Callable[..., Any], *, append: bool = False) -> str:
        if event_name == "selection_changed":
            self.selectionModel().selectionChanged.connect(lambda *_args: callback(None))
            return "selection_changed"
        return super().connect_event(event_name, callback, append=append)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        """覆寫雙擊事件，確保自訂事件系統能正確攔截。"""
        logger.debug(f"Treeview mouseDoubleClickEvent called, handlers={list(self._event_handlers.keys())}", "Treeview")
        pos = event.pos()
        adjusted_event = type(
            "AdjustedEvent",
            (),
            {
                "x": pos.x(),
                "y": pos.y(),
                "x_root": event.globalPosition().x() if hasattr(event, "globalPosition") else event.globalPos().x(),
                "y_root": event.globalPosition().y() if hasattr(event, "globalPosition") else event.globalPos().y(),
                "widget": self,
                "width": self.width(),
                "height": self.height(),
                "delta": 0,
                "keysym": "",
            },
        )()
        callback = self._event_handlers.get("mouse_double_click")
        if callback is not None:
            logger.debug(
                f"Treeview mouseDoubleClickEvent: callback={callback.__name__ if hasattr(callback, '__name__') else callback}",
                "Treeview",
            )
            result = callback(adjusted_event)
            if result == "break":
                return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        """覆寫右鍵事件，轉換為自訂 mouse_right_press 事件。"""
        pos = event.pos()
        simulated = type(
            "Event",
            (),
            {
                "widget": self,
                "x": pos.x(),
                "y": pos.y(),
                "x_root": event.globalPos().x() if hasattr(event, "globalPos") else pos.x(),
                "y_root": event.globalPos().y() if hasattr(event, "globalPos") else pos.y(),
                "width": self.width(),
                "height": self.height(),
                "delta": 0,
                "keysym": "",
            },
        )()
        callback = self._event_handlers.get("mouse_right_press")
        if callback is not None:
            result = callback(simulated)
            if result == "break":
                return
        super().contextMenuEvent(event)

    def configure(self, **kwargs: Any) -> None:
        """更新元件設定，支援 Treeview 特有的 yscrollcommand/xscrollcommand/displaycolumns。"""
        if "height" in kwargs:
            val = kwargs.pop("height")
            if isinstance(val, (int, float)) and val > 100:
                self.setMinimumHeight(int(val))
        if "yscrollcommand" in kwargs:
            cmd = kwargs.pop("yscrollcommand")
            if cmd:
                self._link_scroll_bar(self.verticalScrollBar(), cmd, self.yview)
        if "xscrollcommand" in kwargs:
            cmd = kwargs.pop("xscrollcommand")
            if cmd:
                self._link_scroll_bar(self.horizontalScrollBar(), cmd, self.xview)
        if "displaycolumns" in kwargs:
            columns = kwargs.pop("displaycolumns")
            for col in range(self._model.columnCount()):
                col_name = self._columns[col] if col < len(self._columns) else ""
                is_visible = False
                if (isinstance(columns, str) and columns == "all") or col in columns or col_name in columns:
                    is_visible = True
                self.setColumnHidden(col, not is_visible)
        super().configure(**kwargs)

    @staticmethod
    def _link_scroll_bar(
        source_bar: QtWidgets.QScrollBar,
        cmd: Callable[..., Any],
        view_method: Callable[..., Any],
    ) -> None:
        """雙向同步 Qt 捲軸與 Tkinter 風格 Scrollbar。"""
        maximum = source_bar.maximum()
        source_bar.valueChanged.connect(
            lambda value: cmd(value / maximum, (value + source_bar.pageStep()) / maximum) if maximum > 0 else None
        )
        if hasattr(cmd, "__self__") and isinstance(cmd.__self__, QtWidgets.QScrollBar):
            cmd.__self__.valueChanged.connect(lambda value: view_method(value))

    def apply_theme_style(self) -> None:
        """套用主題樣式"""

    def delete(self, *items: str) -> None:
        """刪除項目"""
        for item_id in items:
            if hasattr(self, "_model") and hasattr(self._model, "remove_item"):
                self._model.remove_item(str(item_id))
            if hasattr(self, "_tags"):
                self._tags.pop(str(item_id), None)


class Notebook(WidgetMixin, TabWidget):
    def __init__(self, parent: Any = None, **kwargs: Any) -> None:
        TabWidget.__init__(self, _native_parent_simple(parent))
        self._init_native(parent, **kwargs)

    def add(self, child: Any, **kwargs: Any) -> None:
        text = kwargs.get("text", "")
        self.addTab(child, text)

    def select(self, tab_id: Any = None) -> Any:
        """選取或查詢目前 tab。無參數時回傳目前 tab 的文字標籤。"""
        if tab_id is None:
            idx = self.currentIndex()
            return self.tabText(idx) if idx >= 0 else ""
        if isinstance(tab_id, int):
            self.setCurrentIndex(tab_id)
        elif isinstance(tab_id, str):
            for i in range(self.count()):
                if self.tabText(i) == tab_id:
                    self.setCurrentIndex(i)
                    break
        return None

    def index(self, tab_id: str) -> int:
        for i in range(self.count()):
            if self.tabText(i) == tab_id:
                return i
        return 0

    def tab(self, tab_id: str, option: str) -> Any:
        if option == "text":
            for i in range(self.count()):
                if self.tabText(i) == tab_id:
                    return self.tabText(i)
        return ""

    def connect_event(self, event_name: str, callback: Callable[..., Any], *, append: bool = False) -> str:
        if event_name == "tab_changed":
            self.currentChanged.connect(lambda _: callback())
            return "tab_changed"
        return super().connect_event(event_name, callback, append=append)


class Scrollbar(WidgetMixin, QtWidgets.QScrollBar):
    def __init__(
        self, parent: Any = None, orient: str = VERTICAL, command: Callable[..., Any] | None = None, **kwargs: Any
    ):
        orientation = QtCore.Qt.Orientation.Vertical if orient == VERTICAL else QtCore.Qt.Orientation.Horizontal
        QtWidgets.QScrollBar.__init__(self, orientation, _native_parent_simple(parent))
        self._command = command
        if command is not None:
            self.valueChanged.connect(command)
        self._init_native(parent, **kwargs)

    def set(self, first: float, _last: float) -> None:
        """Tkinter 相容的 set 方法：由可捲動元件呼叫以更新捲軸位置。"""
        # first, last 為 0.0~1.0 的比例
        maximum = self.maximum()
        if maximum <= 0:
            return
        value = int(first * maximum)
        self.setValue(value)


class Spinbox(WidgetMixin, FluentSpinBox):
    def __init__(
        self,
        parent: Any = None,
        from_: int = 0,
        to: int = 100,
        textvariable: Variable | None = None,
        **kwargs: Any,
    ):
        FluentSpinBox.__init__(self, _native_parent_simple(parent))
        self.setRange(from_, to)
        self._variable = textvariable
        if textvariable is not None:
            self.setValue(int(textvariable.get()))
            self.valueChanged.connect(lambda v: textvariable.set(v))
            textvariable.trace_add("write", lambda *_: self._sync_from_variable())
        self._init_native(parent, **kwargs)

    def _sync_from_variable(self) -> None:
        if self._variable is None:
            return
        value = int(self._variable.get())
        if self.value() == value:
            return
        was_blocked = self.blockSignals(True)
        try:
            self.setValue(value)
        finally:
            self.blockSignals(was_blocked)


# =============================================================================
# 對話框與訊息框
# =============================================================================


class Dialog:
    """對話框基類"""

    def __init__(self, parent: Any = None, title: str = "", content: Any = None):
        self._dummy_parent: QtWidgets.QWidget | None = None
        p = native_parent(parent)
        if p is None:
            self._dummy_parent = QtWidgets.QWidget()
            screen = QtWidgets.QApplication.primaryScreen()
            if screen:
                self._dummy_parent.setGeometry(screen.geometry())
            else:
                self._dummy_parent.setGeometry(0, 0, 800, 600)
            p = self._dummy_parent
        else:
            self._dummy_parent = None
        self._dialog = FluentDialog(title, str(content) if content is not None else "", p)
        self._dialog.setWindowTitle(title)
        self._dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._parent = parent

    def destroy(self) -> None:
        self._dialog.deleteLater()
        if self._dummy_parent is not None:
            self._dummy_parent.deleteLater()
            self._dummy_parent = None

    def configure(self, **kwargs: Any) -> None:
        if "fg_color" in kwargs:
            self._dialog.setStyleSheet(f"background-color: {_color(kwargs['fg_color'])};")


class MessageBox:
    """訊息框包裝器"""

    @staticmethod
    def show_info(title: str, content: str, parent: Any = None) -> None:
        p = native_parent(parent)
        if p is None:
            QtWidgets.QMessageBox.information(None, title, content)
        else:
            dialog = FluentMessageBox(title, content, p)
            dialog.yesButton.setText("確定")
            dialog.cancelButton.setText("取消")
            dialog.cancelButton.hide()
            dialog.exec()

    @staticmethod
    def show_warning(title: str, content: str, parent: Any = None) -> None:
        p = native_parent(parent)
        if p is None:
            QtWidgets.QMessageBox.warning(None, title, content)
        else:
            dialog = FluentMessageBox(title, content, p)
            dialog.yesButton.setText("確定")
            dialog.cancelButton.setText("取消")
            dialog.cancelButton.hide()
            dialog.exec()

    @staticmethod
    def show_error(title: str, content: str, parent: Any = None) -> None:
        p = native_parent(parent)
        if p is None:
            QtWidgets.QMessageBox.critical(None, title, content)
        else:
            dialog = FluentMessageBox(title, content, p)
            dialog.yesButton.setText("確定")
            dialog.cancelButton.setText("取消")
            dialog.cancelButton.hide()
            dialog.exec()

    @staticmethod
    def ask_yes_no(title: str, content: str, parent: Any = None) -> bool:
        p = native_parent(parent)
        if p is None:
            return (
                QtWidgets.QMessageBox.question(
                    None,
                    title,
                    content,
                    QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                )
                == QtWidgets.QMessageBox.StandardButton.Yes
            )
        dialog = FluentMessageBox(title, content, p)
        dialog.yesButton.setText("是")
        dialog.cancelButton.setText("否")
        return dialog.exec() == 1

    @staticmethod
    def ask_yes_no_cancel(title: str, content: str, parent: Any = None, show_cancel: bool = True) -> bool | None:
        p = native_parent(parent)
        if p is None or show_cancel:
            buttons = QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
            if show_cancel:
                buttons |= QtWidgets.QMessageBox.StandardButton.Cancel

            msg_box = QtWidgets.QMessageBox(p)
            msg_box.setWindowTitle(title)
            msg_box.setText(content)
            msg_box.setStandardButtons(buttons)
            msg_box.button(QtWidgets.QMessageBox.StandardButton.Yes).setText("是")
            msg_box.button(QtWidgets.QMessageBox.StandardButton.No).setText("否")
            if show_cancel:
                msg_box.button(QtWidgets.QMessageBox.StandardButton.Cancel).setText("取消")

            result = msg_box.exec()
            if result == QtWidgets.QMessageBox.StandardButton.Yes:
                return True
            if result == QtWidgets.QMessageBox.StandardButton.No:
                return False
            return None

        dialog = FluentMessageBox(title, content, p)
        dialog.yesButton.setText("是")
        dialog.cancelButton.setText("否")
        result = dialog.exec()
        if result == 1:
            return True
        if result == 0:
            return False
        return None


# =============================================================================
# 檔案對話框
# =============================================================================


def get_open_file_name(
    parent: Any = None,
    title: str = "開啟檔案",
    filetypes: list[tuple[str, str]] | str | None = None,
    initialdir: str | None = None,
) -> str | None:
    """開啟檔案選擇對話框"""
    if isinstance(filetypes, str):
        filter_str = filetypes
    else:
        filter_str = ";;".join([f"{desc} ({pattern})" for desc, pattern in (filetypes or [("所有檔案", "*")])])
    file_path, _ = QtWidgets.QFileDialog.getOpenFileName(native_parent(parent), title, initialdir or "", filter_str)
    return file_path if file_path else None


def get_save_file_name(
    parent: Any = None,
    title: str = "儲存檔案",
    defaultextension: str = "",
    filetypes: list[tuple[str, str]] | None = None,
    initialdir: str | None = None,
) -> str | None:
    """儲存檔案對話框"""
    filter_str = ";;".join([f"{desc} ({pattern})" for desc, pattern in (filetypes or [("所有檔案", "*")])])
    file_path, _ = QtWidgets.QFileDialog.getSaveFileName(native_parent(parent), title, initialdir or "", filter_str)
    if file_path and defaultextension and not file_path.endswith(defaultextension):
        file_path += defaultextension
    return file_path if file_path else None


def get_existing_directory(
    parent: Any = None,
    title: str = "選擇資料夾",
    initialdir: str | None = None,
) -> str | None:
    """選擇資料夾對話框"""
    dir_path = QtWidgets.QFileDialog.getExistingDirectory(
        native_parent(parent), title, initialdir or "", QtWidgets.QFileDialog.Option.ShowDirsOnly
    )
    return dir_path if dir_path else None


LineEdit = Entry
PushButton = Button
SearchLineEdit = SearchEntry
SearchFilter = SearchFilter
Theme = Theme
apply_fluent_theme = apply_fluent_theme
setTheme = setTheme
setThemeColor = setThemeColor


# =============================================================================
# LabelFrame — 帶標題的群組框
# =============================================================================


class LabelFrame(WidgetMixin, QtWidgets.QGroupBox):
    def __init__(self, parent: Any = None, text: str = "", padding: int = 5, **kwargs: Any):
        QtWidgets.QGroupBox.__init__(self, _native_parent_simple(parent))
        self.setTitle(text)
        self._padding = padding
        self._init_native(parent, **kwargs)

    def configure(self, **kwargs: Any) -> None:
        if "text" in kwargs:
            self.setTitle(str(kwargs.pop("text")))
        if "padding" in kwargs:
            padding = int(kwargs.pop("padding"))
            self._padding = padding
            lay = self.layout()
            if lay is not None:
                lay.setContentsMargins(padding, padding + 10, padding, padding)
        super().configure(**kwargs)


# =============================================================================
# PopupMenu — 右鍵彈出選單
# =============================================================================


class PopupMenu(QtWidgets.QMenu):
    def __init__(self, parent: Any = None, _tearoff: int = 0, font: Any = None):
        QtWidgets.QMenu.__init__(self, _native_parent_simple(parent))
        if font is not None:
            self.setFont(font)

        # 調整 QMenu 樣式以解決文字被裁切的問題並設定內距
        self.setStyleSheet("""
            QMenu {
                padding: 4px;
                border: 1px solid rgba(128, 128, 128, 0.2);
                border-radius: 6px;
                background-color: palette(window);
            }
            QMenu::item {
                padding: 6px 24px 6px 12px;
                border-radius: 4px;
                margin: 2px;
            }
            QMenu::item:selected {
                background-color: rgba(128, 128, 128, 0.1);
            }
        """)
        self._commands: dict[str, Callable[..., Any]] = {}

    def add_command(self, *, label: str, command: Callable[..., Any]) -> None:
        action = self.addAction(label)
        action.triggered.connect(lambda _checked=False: command())
        self._commands[label] = command

    def popup_at(self, x: int, y: int) -> None:
        parent = self.parent()
        pos = parent.mapToGlobal(QtCore.QPoint(x, y)) if isinstance(parent, QtWidgets.QWidget) else QtCore.QPoint(x, y)
        self.exec(pos)


# =============================================================================
# Listbox — 清單元件
# =============================================================================


class Listbox(WidgetMixin, QtWidgets.QListWidget):
    def __init__(self, parent: Any = None, selectmode: str = "browse", **kwargs: Any):
        QtWidgets.QListWidget.__init__(self, _native_parent_simple(parent))
        self._apply_selectmode(selectmode)
        self._init_native(parent, **kwargs)

    def _apply_selectmode(self, mode: str) -> None:
        mode_map = {
            "browse": QtWidgets.QAbstractItemView.SelectionMode.SingleSelection,
            "extended": QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection,
            "single": QtWidgets.QAbstractItemView.SelectionMode.SingleSelection,
            "multiple": QtWidgets.QAbstractItemView.SelectionMode.MultiSelection,
        }
        self.setSelectionMode(mode_map.get(mode, QtWidgets.QAbstractItemView.SelectionMode.SingleSelection))

    def insert(self, _index: str | int = "end", *values: str) -> None:
        for value in values:
            self.addItem(value)

    def selection(self) -> list[int]:
        """回傳選取項目的索引清單。"""
        return [index.row() for index in self.selectedIndexes()]

    def see(self, index: int) -> None:
        item = self.item(index)
        if item:
            self.scrollToItem(item)

    def yview_scroll(self, number: int, what: str) -> None:
        bar = self.verticalScrollBar()
        if what == "units":
            bar.setValue(bar.value() - number * bar.singleStep())
        elif what == "pages":
            bar.setValue(bar.value() - number * bar.pageStep())
