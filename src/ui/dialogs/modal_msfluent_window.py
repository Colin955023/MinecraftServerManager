"""基於 MSFluentWindow 的功能性彈出視窗基底類別"""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from PySide6.QtCore import QEventLoop, Qt, Signal
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, MSFluentWindow, PrimaryPushButton, PushButton, TitleLabel, qconfig

from src.utils import Colors, FontManager, FontSize, Sizes, center_window, get_icon_path, resolve_color


class ModalMSFluentWindow(MSFluentWindow):
    """
    自定義的彈出視窗基底類別，繼承自 MSFluentWindow 以提供完整的最大化/最小化按鈕，
    並實作類似 MessageBoxBase 的版面配置與 exec() 阻塞功能
    """

    accepted = Signal()
    rejected = Signal()

    def __init__(self, parent: Any = None, is_modal: bool = True, show_buttons: bool = True):
        widget_parent = parent if isinstance(parent, QWidget) else None
        super().__init__(widget_parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)
        self.setMicaEffectEnabled(False)
        self.setCustomBackgroundColor(*Colors.BG_PRIMARY)
        icon_path = get_icon_path()
        if icon_path:
            icon = QIcon(icon_path)
            self.setWindowIcon(icon)
            if hasattr(self, "titleBar") and hasattr(self.titleBar, "setIcon"):
                self.titleBar.setIcon(icon)
        if is_modal:
            self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(600, 450)

        self.widget = QWidget(self)
        self.widget.setObjectName("ModalMainWidget")
        self._apply_theme_styles()
        qconfig.themeChangedFinished.connect(self._apply_theme_styles)

        self.navigationInterface.hide()
        self.stackedWidget.addWidget(self.widget)
        self.stackedWidget.setCurrentWidget(self.widget)
        self.windowLayout = QVBoxLayout(self.widget)
        self.windowLayout.setContentsMargins(0, 0, 0, 0)
        self.windowLayout.setSpacing(0)

        self.viewLayout = QVBoxLayout()
        self.viewLayout.setContentsMargins(24, 24, 24, 24)
        self.viewLayout.setSpacing(12)
        self.windowLayout.addLayout(self.viewLayout, 1)

        self.buttonGroup = QFrame(self.widget)
        self.buttonGroup.setObjectName("buttonGroup")
        self.buttonLayout = QHBoxLayout(self.buttonGroup)
        self.buttonLayout.setContentsMargins(24, 12, 24, 24)
        self.buttonLayout.setSpacing(16)
        self.windowLayout.addWidget(self.buttonGroup)

        self.buttonLayout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.cancelButton = PushButton("取消", self.buttonGroup)
        self.yesButton = PrimaryPushButton("確定", self.buttonGroup)
        self.cancelButton.setMinimumSize(Sizes.DIALOG_BUTTON_WIDTH, Sizes.DIALOG_BUTTON_HEIGHT)
        self.yesButton.setMinimumSize(Sizes.DIALOG_BUTTON_WIDTH, Sizes.DIALOG_BUTTON_HEIGHT)
        btn_font = FontManager.get_font(size=FontSize.NORMAL_PLUS, weight="bold")
        self.cancelButton.setFont(btn_font)
        self.yesButton.setFont(btn_font)

        self.buttonLayout.addStretch(1)
        self.buttonLayout.addWidget(self.cancelButton)
        self.buttonLayout.addWidget(self.yesButton)
        self.buttonLayout.addStretch(1)

        if not show_buttons:
            self.buttonGroup.hide()

        self.cancelButton.clicked.connect(self.reject)
        self.yesButton.clicked.connect(self.accept)

        self._result = False
        self._loop: QEventLoop | None = None

    def _apply_theme_styles(self) -> None:
        """讓 modal 的外框、內容容器與 stacked widget 使用相同主題背景"""
        background = resolve_color(Colors.BG_PRIMARY)
        foreground = resolve_color(Colors.TEXT_PRIMARY)
        if hasattr(self, "widget"):
            self.widget.setStyleSheet(
                f"#ModalMainWidget {{ background-color: {background}; color: {foreground}; border: 0; }}"
            )
        stacked = getattr(self, "stackedWidget", getattr(self, "stacked_widget", None))
        if stacked is not None:
            stacked.setStyleSheet(
                f"QStackedWidget {{ background-color: {background}; border: 0; }}\n"
                f"QScrollArea {{ background-color: transparent; border: 0; }}\n"
                f"QScrollArea > QWidget > QWidget {{ background-color: transparent; }}"
            )

    def accept(self) -> None:
        """接受操作，設定結果為 True 並關閉視窗"""
        self._result = True
        self.accepted.emit()
        self.close()

    def reject(self) -> None:
        """拒絕操作，設定結果為 False 並關閉視窗"""
        self._result = False
        self.rejected.emit()
        self.close()

    def exec(self) -> bool:
        """
        顯示視窗並阻塞，直到使用者接受或拒絕操作返回結果為 True 或 False

        Returns:
            使用者操作結果，True 表示接受，False 表示拒絕
        """
        center_window(self, self.parentWidget())
        self.show()
        self._loop = QEventLoop()
        self.destroyed.connect(self._loop.quit)
        self._loop.exec()
        return self._result

    def closeEvent(self, e: QCloseEvent) -> None:
        """
        視窗關閉事件處理，確保在關閉時退出事件循環並解除主題信號連接

        Args:
            e: QCloseEvent 事件物件
        """
        with suppress(Exception):
            qconfig.themeChangedFinished.disconnect(self._apply_theme_styles)
        super().closeEvent(e)
        if hasattr(self, "_loop") and self._loop and self._loop.isRunning():
            self._loop.quit()


class MessageDialog(ModalMSFluentWindow):
    """
    基於 ModalMSFluentWindow 的精簡 Fluent 訊息與確認對話框
    標題與內容文字置中、隱藏最大/最小化按鈕，完全復用既有視窗機制
    """

    def __init__(
        self,
        title: str,
        message: str,
        parent: Any = None,
        *,
        question: bool = False,
        show_cancel: bool = True,
    ) -> None:
        super().__init__(parent, is_modal=True, show_buttons=True)
        self.setWindowTitle(title)
        self.setFixedSize(520, 260 if question else 230)

        if hasattr(self, "titleBar"):
            if hasattr(self.titleBar, "minBtn"):
                self.titleBar.minBtn.hide()
            if hasattr(self.titleBar, "maxBtn"):
                self.titleBar.maxBtn.hide()

        self.title_label = TitleLabel(title, self.widget)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(self.title_label)

        self.content_label = BodyLabel(message, self.widget)
        self.content_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_label.setWordWrap(True)
        self.content_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.viewLayout.addWidget(self.content_label, 1)

        if question:
            self.yesButton.setText("是")
            self.cancelButton.setText("取消" if show_cancel else "否")
        else:
            self.cancelButton.hide()
            self.yesButton.setText("確定")


__all__ = ["MessageDialog", "ModalMSFluentWindow"]
