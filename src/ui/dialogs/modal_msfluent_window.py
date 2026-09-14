"""基於 MSFluentWindow 的功能性彈出視窗基底類別"""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from PySide6.QtCore import QEventLoop, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, MSFluentWindow, PrimaryPushButton, PushButton, TitleLabel, qconfig

from src.ui import (
    Colors,
    FontManager,
    FontSize,
    Sizes,
    apply_window_icon,
    center_window,
    resolve_color,
    themed_surface_stylesheet,
)


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
        apply_window_icon(self)
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

        self.buttonGroup = QWidget(self.widget)
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
        if hasattr(self, "widget"):
            self.widget.setStyleSheet(themed_surface_stylesheet("ModalMainWidget"))
        stacked = getattr(self, "stackedWidget", getattr(self, "stacked_widget", None))
        if stacked is not None:
            stacked.setStyleSheet(f"background-color: {background}; border: 0;")

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
        loop = QEventLoop()
        self._loop = loop
        self.destroyed.connect(loop.quit)
        try:
            loop.exec()
        finally:
            self._loop = None
        return self._result

    def closeEvent(self, e: QCloseEvent) -> None:
        """
        視窗關閉事件處理，確保在關閉時退出事件迴圈並解除主題訊號連接

        Args:
            e: QCloseEvent 事件物件
        """
        with suppress(Exception):
            qconfig.themeChangedFinished.disconnect(self._apply_theme_styles)
        if hasattr(self, "_loop") and self._loop and self._loop.isRunning():
            self._loop.quit()
        super().closeEvent(e)


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
        self.content_label.setTextFormat(Qt.TextFormat.PlainText)
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


class DeleteServerDialog(ModalMSFluentWindow):
    """
    刪除伺服器確認對話框
    整合伺服器檔案刪除確認與外部備份清理選項
    """

    def __init__(
        self,
        server_name: str,
        backup_count: int,
        parent: Any = None,
    ) -> None:
        super().__init__(parent, is_modal=True, show_buttons=False)
        self.server_name = server_name
        self.backup_count = backup_count
        self.decision: str = "cancel"

        self.setWindowTitle("確認刪除伺服器")
        self.setFixedSize(540, 290 if backup_count > 0 else 240)

        if hasattr(self, "titleBar"):
            if hasattr(self.titleBar, "minBtn"):
                self.titleBar.minBtn.hide()
            if hasattr(self.titleBar, "maxBtn"):
                self.titleBar.maxBtn.hide()

        self.title_label = TitleLabel("🗑️ 確認刪除伺服器", self.widget)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(self.title_label)

        if backup_count > 0:
            msg = (
                f"確定要刪除伺服器「{server_name}」嗎？\n\n"
                "⚠️ 這將永久刪除伺服器檔案，無法復原！\n\n"
                f"偵測到此伺服器有 {backup_count} 個外部備份檔案，是否一併永久刪除？"
            )
        else:
            msg = f"確定要刪除伺服器「{server_name}」嗎？\n\n⚠️ 這將永久刪除伺服器檔案，無法復原！"

        self.content_label = BodyLabel(msg, self.widget)
        self.content_label.setTextFormat(Qt.TextFormat.PlainText)
        self.content_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_label.setWordWrap(True)
        self.content_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.viewLayout.addWidget(self.content_label, 1)

        custom_buttons = QWidget(self.widget)
        btn_layout = QHBoxLayout(custom_buttons)
        btn_layout.setContentsMargins(24, 8, 24, 20)
        btn_layout.setSpacing(12)
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn_font = FontManager.get_font(size=FontSize.NORMAL_PLUS, weight="bold")

        if backup_count > 0:
            self.cancel_btn = PushButton("取消", custom_buttons)
            self.no_btn = PushButton("否（只刪除伺服器）", custom_buttons)
            self.yes_btn = PrimaryPushButton("是（連備份一併刪除）", custom_buttons)

            for btn in (self.cancel_btn, self.no_btn, self.yes_btn):
                btn.setMinimumSize(Sizes.DIALOG_BUTTON_WIDTH, Sizes.DIALOG_BUTTON_HEIGHT)
                btn.setFont(btn_font)

            btn_layout.addStretch(1)
            btn_layout.addWidget(self.cancel_btn)
            btn_layout.addWidget(self.no_btn)
            btn_layout.addWidget(self.yes_btn)
            btn_layout.addStretch(1)

            self.cancel_btn.clicked.connect(self._choose_cancel)
            self.no_btn.clicked.connect(self._choose_server_only)
            self.yes_btn.clicked.connect(self._choose_all)
        else:
            self.cancel_btn = PushButton("取消", custom_buttons)
            self.confirm_btn = PrimaryPushButton("確定刪除", custom_buttons)

            for btn in (self.cancel_btn, self.confirm_btn):
                btn.setMinimumSize(Sizes.DIALOG_BUTTON_WIDTH, Sizes.DIALOG_BUTTON_HEIGHT)
                btn.setFont(btn_font)

            btn_layout.addStretch(1)
            btn_layout.addWidget(self.cancel_btn)
            btn_layout.addWidget(self.confirm_btn)
            btn_layout.addStretch(1)

            self.cancel_btn.clicked.connect(self._choose_cancel)
            self.confirm_btn.clicked.connect(self._choose_server_only)

        self.windowLayout.addWidget(custom_buttons)

    def _choose_all(self) -> None:
        self.decision = "all"
        self.accept()

    def _choose_server_only(self) -> None:
        self.decision = "server_only"
        self.accept()

    def _choose_cancel(self) -> None:
        self.decision = "cancel"
        self.reject()

    def exec_decision(self) -> str:
        """
        顯示視窗並回傳使用者選擇的刪除決策

        Returns:
            all 代表連備份一併刪除，server_only 代表只刪除伺服器，cancel 代表取消
        """
        self.exec()
        return self.decision


__all__ = ["DeleteServerDialog", "MessageDialog", "ModalMSFluentWindow"]
