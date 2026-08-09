"""
UI 應用程式配置

此模組負責 PySide6 全域配置與主題設定
所有 GUI 組件建立前應先導入此模組以套用主題
"""

from typing import Any

from PySide6.QtGui import QWheelEvent
from qfluentwidgets import ComboBox, Theme, isDarkTheme, setTheme, setThemeColor

from ..ui_support.qt_runtime import QtGui, ensure_application


def resolve_color(color: Any, *, dark: bool | None = None) -> str:
    """
    解析專案色彩設定為 Qt stylesheet 可用色碼

    Args:
        color: 單一色碼或 `(light, dark)` 色碼 tuple
        dark: 是否使用深色主題；未指定時由 qfluentwidgets 判斷

    Returns:
        Qt stylesheet 可接受的色彩字串
    """
    if dark is None:
        dark = isDarkTheme()
    if isinstance(color, tuple):
        return str(color[1 if dark and len(color) > 1 else 0])
    return str(color)


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
    初始化 UI 主題配置

    應在應用程式啟動時（組建主視窗前）呼叫一次
    設定全域外觀模式與色彩主題

    Args:
        mode: 主題模式，可為 `light` 或 `dark`
    """
    app = ensure_application()

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


__all__ = ["initialize_ui_theme", "resolve_color"]
