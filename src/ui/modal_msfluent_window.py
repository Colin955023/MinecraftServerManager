"""基於 MSFluentWindow 的功能性彈出視窗基底類別"""

from typing import Any

from PySide6.QtCore import QEventLoop, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import MSFluentWindow, PrimaryPushButton, PushButton


class ModalMSFluentWindow(MSFluentWindow):
    """
    自定義的彈出視窗基底類別，繼承自 MSFluentWindow 以提供完整的最大化/最小化按鈕，
    並實作類似 MessageBoxBase 的版面配置與 `.exec()` 阻塞功能
    """

    accepted = Signal()
    rejected = Signal()

    def __init__(self, parent: Any = None, is_modal: bool = True, show_buttons: bool = True):
        super().__init__(parent)
        if is_modal:
            self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(600, 450)

        # 主要容器
        self.widget = QWidget(self)
        self.widget.setObjectName("ModalMainWidget")

        self.navigationInterface.hide()
        self.addSubInterface(self.widget, "icon", "title")

        # 主要佈局
        self.windowLayout = QVBoxLayout(self.widget)
        self.windowLayout.setContentsMargins(0, 0, 0, 0)
        self.windowLayout.setSpacing(0)

        # 內容視圖佈局 (等同於 MessageBoxBase.viewLayout)
        self.viewLayout = QVBoxLayout()
        self.viewLayout.setContentsMargins(24, 24, 24, 24)
        self.viewLayout.setSpacing(12)
        self.windowLayout.addLayout(self.viewLayout, 1)

        # 底部按鈕區
        self.buttonGroup = QFrame(self.widget)
        self.buttonGroup.setObjectName("buttonGroup")
        self.buttonLayout = QHBoxLayout(self.buttonGroup)
        self.buttonLayout.setContentsMargins(24, 12, 24, 24)
        self.buttonLayout.setSpacing(12)
        self.windowLayout.addWidget(self.buttonGroup)

        self.buttonLayout.addStretch(1)

        # 預設按鈕 (等同於 MessageBoxBase.cancelButton / yesButton)
        self.cancelButton = PushButton("取消", self.buttonGroup)
        self.yesButton = PrimaryPushButton("確定", self.buttonGroup)

        self.buttonLayout.addWidget(self.cancelButton)
        self.buttonLayout.addWidget(self.yesButton)

        if not show_buttons:
            self.buttonGroup.hide()

        self.cancelButton.clicked.connect(self.reject)
        self.yesButton.clicked.connect(self.accept)

        self._result = False
        self._loop: QEventLoop | None = None

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
            bool: 使用者操作結果，True 表示接受，False 表示拒絕
        """
        self.show()
        self._loop = QEventLoop()
        self.destroyed.connect(self._loop.quit)
        self._loop.exec()
        return self._result

    def closeEvent(self, e: QCloseEvent) -> None:
        """
        視窗關閉事件處理，確保在關閉時退出事件循環

        Args:
            e: QCloseEvent 事件對象
        """
        super().closeEvent(e)
        if hasattr(self, "_loop") and self._loop and self._loop.isRunning():
            self._loop.quit()
