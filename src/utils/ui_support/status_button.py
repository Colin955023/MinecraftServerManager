"""提供支援主題切換與狀態改變（如危險、成功）的按鈕元件"""

from typing import Any

from qfluentwidgets import PushButton, isDarkTheme, qconfig

from src.utils import Colors, resolve_color


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

        if self._status == "danger":
            bg_normal = resolve_color(Colors.BUTTON_DANGER)
            bg_hover = resolve_color(Colors.BUTTON_DANGER_HOVER)
            text_color = "black"
        elif self._status == "success":
            bg_normal = resolve_color(Colors.BUTTON_SUCCESS)
            bg_hover = resolve_color(Colors.BUTTON_SUCCESS_HOVER)
            text_color = "white"
        else:
            self.setStyleSheet("")
            return

        is_dark = isDarkTheme()
        bg_disabled = "rgba(255, 255, 255, 0.06)" if is_dark else "rgba(0, 0, 0, 0.03)"
        border_disabled = "rgba(255, 255, 255, 0.04)" if is_dark else "rgba(0, 0, 0, 0.05)"
        color_disabled = resolve_color(Colors.TEXT_MUTED)

        self.setStyleSheet(
            f"""
            StatusPushButton {{
                background-color: {bg_normal};
                color: {text_color};
                border: 1px solid rgba(0, 0, 0, 0.1);
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
