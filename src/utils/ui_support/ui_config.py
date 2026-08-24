"""
UI 應用程式設定

此模組負責 PySide6 全域設定與主題設定
所有 GUI 元件建立前應先導入此模組以套用主題
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from PySide6 import QtGui
from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QWidget
from qfluentwidgets import ComboBox, MSFluentWindow, Theme, isDarkTheme, setTheme, setThemeColor

from src.utils import Colors, Sizes, ensure_application, is_qobject_alive

_CENTERING_FILTER: QObject | None = None


def resolve_color(color: Any, *, dark: bool | None = None) -> str:
    """
    解析專案色彩設定為 Qt stylesheet 可用色碼

    Args:
        color: 單一色碼或 (light, dark) 色碼 tuple
        dark: 是否使用深色主題；未指定時由 qfluentwidgets 判斷

    Returns:
        Qt stylesheet 可接受的色彩字串
    """
    if dark is None:
        dark = isDarkTheme()
    if isinstance(color, tuple):
        return str(color[1 if dark and len(color) > 1 else 0])
    return str(color)


class _TableHeaderScrollFilter(QObject):
    """確保表格/樹狀列表的垂直滾動條起始於表頭正下方，不突出版頭"""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        res = super().eventFilter(watched, event)
        if (
            event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest)
            and isinstance(watched, QWidget)
            and hasattr(watched, "header")
        ):
            header = watched.header()
            header_h = header.height() if header and header.isVisible() else 0
            delegate = getattr(watched, "scrollDelagate", None)
            vbar = getattr(delegate, "vScrollBar", None) if delegate else None
            if vbar is not None and is_qobject_alive(vbar):
                vbar.move(watched.width() - 13, header_h + 1)
                vbar.resize(12, max(0, watched.height() - header_h - 2))
        return res


_TABLE_HEADER_SCROLL_FILTER = _TableHeaderScrollFilter()


def apply_table_header_style(table: Any) -> None:
    """
    套用所有列表共用的表頭背景、文字與分隔線樣式，並重設平面列表縮排與裝飾空間

    Args:
        table: 欲套用樣式的 QTreeWidget 或 QTableWidget 實例
    """
    if table is None:
        return
    if hasattr(table, "setRootIsDecorated"):
        table.setRootIsDecorated(False)
    if hasattr(table, "setIndentation"):
        table.setIndentation(0)
    if not hasattr(table, "header"):
        return
    header = table.header()
    bg_listbox = resolve_color((Colors.BG_LISTBOX_LIGHT, Colors.BG_LISTBOX_DARK))
    text_primary = resolve_color(Colors.TEXT_PRIMARY)
    border_color = resolve_color(Colors.TABLE_HEADER_BORDER)
    stylesheet = (
        "QHeaderView {"
        " background-color: transparent;"
        " border: none;"
        "}"
        "QHeaderView::section {"
        f" background-color: {bg_listbox};"
        f" color: {text_primary};"
        f" border: {Sizes.TABLE_HEADER_BORDER_WIDTH}px solid {border_color};"
        " padding: 4px 6px;"
        "}"
    )
    if header.styleSheet() != stylesheet:
        header.setStyleSheet(stylesheet)
    if isinstance(table, QObject) and not bool(table.property("_msm_header_scroll_filtered")):
        table.installEventFilter(_TABLE_HEADER_SCROLL_FILTER)
        table.setProperty("_msm_header_scroll_filtered", True)


def center_window(window: QWidget, parent: QWidget | None = None) -> None:
    """
    將彈出視窗置中於父視窗所在螢幕

    Args:
        window: 要置中的視窗
        parent: 父視窗，若未指定則使用 window.parentWidget()
    """
    if window is None:
        return
    try:
        window.adjustSize()
        raw_anchor = parent or window.parentWidget()
        anchor = raw_anchor.window() if raw_anchor is not None and hasattr(raw_anchor, "window") else raw_anchor
        screen = anchor.screen() if anchor is not None else window.screen()
        if screen is None:
            screen = ensure_application().primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        margin = 24
        max_width = max(1, area.width() - margin * 2)
        max_height = max(1, area.height() - margin * 2)
        if window.width() > max_width or window.height() > max_height:
            window.resize(min(window.width(), max_width), min(window.height(), max_height))
        target_center = anchor.frameGeometry().center() if anchor is not None else area.center()
        frame = window.frameGeometry()
        x = target_center.x() - frame.width() // 2
        y = target_center.y() - frame.height() // 2
        x = max(area.left() + margin, min(x, area.right() - frame.width() - margin + 1))
        y = max(area.top() + margin, min(y, area.bottom() - frame.height() - margin + 1))
        window.move(x, y)
    except AttributeError, RuntimeError:
        return


class _DialogCenteringFilter(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.Show
            and isinstance(watched, QWidget)
            and watched.isWindow()
            and isinstance(watched, MSFluentWindow)
            and not bool(watched.property("_primary_window"))
        ):
            center_window(watched, watched.parentWidget())
        return super().eventFilter(watched, event)


def _preferred_ui_font(point_size: int = 12) -> QtGui.QFont:
    candidates = ("Microsoft JhengHei UI", "Microsoft JhengHei", "Noto Sans CJK TC")
    try:
        families = set(QtGui.QFontDatabase.families())
        family = next((candidate for candidate in candidates if candidate in families), "")
        font = (
            QtGui.QFont(family, point_size)
            if family
            else QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.GeneralFont)
        )
        font.setPointSize(point_size)
        return font
    except Exception:
        return QtGui.QFont("Arial", point_size)


def initialize_ui_theme(mode: str = "light") -> None:
    """
    初始化 UI 主題設定

    應在應用程式啟動時（建構主視窗前）呼叫一次
    設定全域外觀模式與色彩主題

    Args:
        mode: 主題模式，可為 light 或 dark
    """
    global _CENTERING_FILTER
    app = ensure_application()
    if _CENTERING_FILTER is None:
        centering_filter = _DialogCenteringFilter(app)
        _CENTERING_FILTER = centering_filter
        app.installEventFilter(centering_filter)

    normalized = str(mode or "system").strip().lower()
    if normalized == "dark":
        setTheme(Theme.DARK)
    elif normalized == "light":
        setTheme(Theme.LIGHT)
    else:
        setTheme(Theme.AUTO)

    setThemeColor("#2563eb")

    ui_font = _preferred_ui_font(12)
    app.setFont(ui_font)

    _patch_combobox_wheel_event()
    _patch_navigation_push_button_paint_event()


def _patch_combobox_wheel_event():
    def _combo_wheel_event(self, event: QWheelEvent):
        if not self.hasFocus():
            event.ignore()
            return
        delta = event.angleDelta().y()
        if delta > 0:
            if self.currentIndex() > 0:
                self.setCurrentIndex(self.currentIndex() - 1)
        elif delta < 0 and self.currentIndex() < self.count() - 1:
            self.setCurrentIndex(self.currentIndex() + 1)
        event.accept()

    if not hasattr(ComboBox, "_original_wheel_event"):
        ComboBox._original_wheel_event = ComboBox.wheelEvent
        ComboBox.wheelEvent = _combo_wheel_event


def _patch_navigation_push_button_paint_event():
    """修補 NavigationPushButton 的繪製事件，確保動畫流暢且防止收合時文字重疊撕裂"""
    with suppress(Exception):
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QColor, QPainter
        from qfluentwidgets.common.color import autoFallbackThemeColor
        from qfluentwidgets.common.config import isDarkTheme
        from qfluentwidgets.common.icon import drawIcon
        from qfluentwidgets.components.navigation.navigation_widget import NavigationPushButton

        def _patched_paint_event(self, _e):
            painter = QPainter(self)
            painter.setRenderHints(
                QPainter.RenderHint.Antialiasing
                | QPainter.RenderHint.TextAntialiasing
                | QPainter.RenderHint.SmoothPixmapTransform
            )
            painter.setPen(Qt.PenStyle.NoPen)

            if self.isPressed:
                painter.setOpacity(0.7)
            if not self.isEnabled():
                painter.setOpacity(0.4)

            c = 255 if isDarkTheme() else 0
            m = self._margins()
            pl, pr = m.left(), m.right()

            if self._canDrawIndicator():
                painter.setBrush(QColor(c, c, c, 6 if self.isEnter else 10))
                painter.drawRoundedRect(self.rect(), 5, 5)

                painter.setBrush(autoFallbackThemeColor(self.lightIndicatorColor, self.darkIndicatorColor))
                painter.drawRoundedRect(self.indicatorRect(), 1.5, 1.5)
            elif (self.isEnter or self.isAboutSelected) and self.isEnabled():
                painter.setBrush(QColor(c, c, c, 6 if self.isAboutSelected else 10))
                painter.drawRoundedRect(self.rect(), 5, 5)

            drawIcon(self._icon, painter, QRectF(11.5 + pl, 10, 16, 16))

            if self.isCompacted or self.width() <= 48:
                return

            painter.setFont(self.font())
            painter.setPen(self.textColor())

            has_icon = bool(getattr(self, "_icon", None)) or not self.icon().isNull()
            left = 44 + pl if has_icon else pl + 16
            text_width = float(self.width() - 13 - left - pr)
            if text_width > 10:
                painter.drawText(
                    QRectF(left, 0, text_width, float(self.height())),
                    Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
                    self.text(),
                )

        if not hasattr(NavigationPushButton, "_original_paint_event"):
            NavigationPushButton._original_paint_event = NavigationPushButton.paintEvent
            NavigationPushButton.paintEvent = _patched_paint_event


__all__ = [
    "apply_table_header_style",
    "center_window",
    "initialize_ui_theme",
    "resolve_color",
]
