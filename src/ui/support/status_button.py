"""提供支援主題切換與狀態改變（如危險、成功）的按鈕元件"""

from typing import Any

from qfluentwidgets import PushButton, isDarkTheme, qconfig

from .ui_config import resolve_color
from .ui_tokens import Colors


class StatusPushButton(PushButton):
    """客製化的按鈕元件，支援設定為不同狀態 (如 danger, success)"""

    def __init__(self, text: str = "", parent: Any = None):
        super().__init__(parent=parent)
        self.setText(text)
        self._status = "normal"
        qconfig.themeChangedFinished.connect(self._on_theme_changed)

    def set_status(self, status: str) -> None:
        """
        設定按鈕狀態

        Args:
            status: "normal", "danger", "success"
        """
        self._status = status
        self._apply_status_style()

    def _on_theme_changed(self) -> None:
        """主題切換時重新套用自定義樣式"""
        self._apply_status_style()

    def _apply_status_style(self) -> None:
        """根據目前狀態套用對應的 QSS 樣式表"""
        if self._status == "normal":
            self.setStyleSheet("")
            return

        is_dark = isDarkTheme()
        if self._status == "danger":
            bg_normal = resolve_color(Colors.BUTTON_DANGER, dark=is_dark)
            bg_hover = resolve_color(Colors.BUTTON_DANGER_HOVER, dark=is_dark)
            text_color = "black"
            bg_disabled = "rgba(220, 38, 38, 0.45)" if not is_dark else "rgba(185, 28, 28, 0.45)"
            color_disabled = "rgba(0, 0, 0, 0.5)" if not is_dark else "rgba(255, 255, 255, 0.5)"
            border_normal = "rgba(0, 0, 0, 0.1)" if not is_dark else "rgba(255, 255, 255, 0.15)"
            border_disabled = "rgba(220, 38, 38, 0.3)"
        elif self._status == "success":
            bg_normal = resolve_color(Colors.BUTTON_SUCCESS, dark=is_dark)
            bg_hover = resolve_color(Colors.BUTTON_SUCCESS_HOVER, dark=is_dark)
            text_color = "white"
            bg_disabled = "rgba(5, 150, 105, 0.45)" if not is_dark else "rgba(4, 120, 87, 0.45)"
            color_disabled = "rgba(0, 0, 0, 0.5)" if not is_dark else "rgba(255, 255, 255, 0.5)"
            border_normal = "rgba(0, 0, 0, 0.1)" if not is_dark else "rgba(255, 255, 255, 0.15)"
            border_disabled = "rgba(5, 150, 105, 0.3)"
        else:
            self.setStyleSheet("")
            return

        self.setStyleSheet(
            f"""
            StatusPushButton {{
                background-color: {bg_normal};
                color: {text_color};
                border: 1px solid {border_normal};
                border-radius: 5px;
                padding: 5px 10px;
            }}
            StatusPushButton:hover {{
                background-color: {bg_hover};
                color: {text_color};
            }}
            StatusPushButton:pressed {{
                background-color: {bg_normal};
                color: {text_color};
            }}
            StatusPushButton:disabled {{
                background-color: {bg_disabled};
                color: {color_disabled};
                border: 1px solid {border_disabled};
            }}
            """
        )


__all__ = ["StatusPushButton"]
