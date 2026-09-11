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
from qfluentwidgets import ComboBox, Theme, isDarkTheme, setTheme, setThemeColor

from .qt_runtime import ensure_application, is_qobject_alive
from .ui_tokens import Colors, Sizes

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


def themed_surface_stylesheet(object_name: str) -> str:
    """
    建立內容面板共用的主題感知文字、背景與邊框樣式

    Args:
        object_name: 套用樣式的根 QWidget objectName

    Returns:
        可直接套用到根 QWidget 的 Qt stylesheet
    """
    background = resolve_color(Colors.BG_PRIMARY)
    foreground = resolve_color(Colors.TEXT_PRIMARY)
    secondary = resolve_color(Colors.TEXT_SECONDARY)
    border = resolve_color(Colors.BORDER)
    return (
        f"#{object_name} {{ background-color: {background}; color: {foreground}; border: 0; }}"
        f"#{object_name} QLabel {{ color: {foreground}; background-color: transparent; }}"
        f"#{object_name} CaptionLabel {{ color: {secondary}; background-color: transparent; }}"
        f"#{object_name} CardWidget {{ background-color: transparent; border: 1px solid {border};"
        " border-radius: 8px; }}"
    )


class _TableHeaderScrollFilter(QObject):
    """確保表格/樹狀列表的垂直捲軸起始於表頭正下方，不突出版頭"""

    def __init__(self, table: QWidget | None = None):
        super().__init__(table)
        self.table = table

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        res = super().eventFilter(watched, event)
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest):
            target = self.table if self.table is not None else watched
            if isinstance(target, QWidget):
                self.adjust_scrollbar(target)
        return res

    @staticmethod
    def adjust_scrollbar(table: QWidget) -> None:
        if not is_qobject_alive(table):
            return
        delegate = getattr(table, "scrollDelagate", None)
        vbar = getattr(delegate, "vScrollBar", None) if delegate else None
        if vbar is None or not is_qobject_alive(vbar):
            return
        vp_fn = getattr(table, "viewport", None)
        viewport = vp_fn() if callable(vp_fn) else None
        if viewport and viewport.isVisible():
            vp_geo = viewport.geometry()
            if vp_geo.isValid() and vp_geo.height() > 0:
                vbar.move(table.width() - 13, vp_geo.top() + 1)
                vbar.resize(12, max(0, vp_geo.height() - 2))
                return
        hdr_fn = getattr(table, "header", None)
        header = hdr_fn() if callable(hdr_fn) else None
        header_h = (header.height() or header.sizeHint().height() or 32) if header and not header.isHidden() else 0
        vbar.move(table.width() - 13, header_h + 1)
        vbar.resize(12, max(0, table.height() - header_h - 2))


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
    if isinstance(table, QWidget) and not bool(table.property("_msm_header_scroll_filtered")):
        flt = _TableHeaderScrollFilter(table)
        table.installEventFilter(flt)
        table.setProperty("_msm_header_scroll_filtered", True)
        table.setProperty("_msm_header_scroll_filter", flt)
        if hasattr(table, "header") and table.header():
            table.header().installEventFilter(flt)
        if hasattr(table, "viewport") and table.viewport():
            table.viewport().installEventFilter(flt)

    delegate = getattr(table, "scrollDelagate", None)
    vbar = getattr(delegate, "vScrollBar", None) if delegate else None
    if vbar is not None and not bool(vbar.property("_msm_header_pos_patched")):

        def _make_adjust_pos(scroll_bar, parent_table):
            def _adjust(size):
                vp_fn = getattr(parent_table, "viewport", None)
                viewport = vp_fn() if callable(vp_fn) else None
                if viewport and viewport.isVisible():
                    vp_geo = viewport.geometry()
                    if vp_geo.isValid() and vp_geo.height() > 0:
                        scroll_bar.move(size.width() - 13, vp_geo.top() + 1)
                        scroll_bar.resize(12, max(0, vp_geo.height() - 2))
                        return
                hdr_fn = getattr(parent_table, "header", None)
                hdr = hdr_fn() if callable(hdr_fn) else None
                hdr_h = (hdr.height() or hdr.sizeHint().height() or 32) if hdr and not hdr.isHidden() else 0
                scroll_bar.resize(12, max(0, size.height() - hdr_h - 2))
                scroll_bar.move(size.width() - 13, hdr_h + 1)

            return _adjust

        vbar._adjustPos = _make_adjust_pos(vbar, table)
        vbar.setProperty("_msm_header_pos_patched", True)
        hdr = table.header() if hasattr(table, "header") else None
        hdr_h = (hdr.height() or hdr.sizeHint().height() or 32) if hdr and not hdr.isHidden() else 0
        vbar.move(table.width() - 13, hdr_h + 1)
        vbar.resize(12, max(0, table.height() - hdr_h - 2))


def center_window(window: QWidget, parent: QWidget | None = None) -> None:
    """
    將彈出視窗置中於父視窗所在螢幕

    Args:
        window: 要置中的視窗
        parent: 父視窗，若未指定則使用 window.parentWidget()
    """
    if window is None or window.isMaximized() or window.isFullScreen():
        return
    try:
        window.adjustSize()
        raw_anchor = parent or window.parentWidget()
        if raw_anchor is not None:
            win_attr = getattr(raw_anchor, "window", None)
            anchor = win_attr() if callable(win_attr) else raw_anchor
        else:
            anchor = None
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
            and not bool(watched.property("_centered"))
            and not bool(watched.property("_primary_window"))
        ):
            from src.ui import ModalMSFluentWindow

            if isinstance(watched, ModalMSFluentWindow):
                watched.setProperty("_centered", True)
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

        def _patched_paint_event(self, event):
            painter = QPainter(self)
            painter.setClipRect(event.rect())
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
    "themed_surface_stylesheet",
]
