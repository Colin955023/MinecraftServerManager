"""原生 Qt 進度對話框"""

from __future__ import annotations

from typing import Any

from PySide6 import QtWidgets
from PySide6.QtCore import Qt, Signal, Slot
from qfluentwidgets import ProgressBar, SubtitleLabel, TitleLabel

from src.ui import ModalMSFluentWindow
from src.utils import (
    Spacing,
    get_logger,
    is_qobject_alive,
)

logger = get_logger().bind(component="ProgressDialog")


class ProgressDialog(ModalMSFluentWindow):
    """顯示可取消的進度對話框"""

    progress_requested = Signal(float, str)

    def __init__(self, parent: Any, title: str = "進度", show_cancel: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.custom_title = TitleLabel(title, self.widget)
        self.custom_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(self.custom_title)

        self.viewLayout.setContentsMargins(Spacing.XL, Spacing.XL, Spacing.XL, Spacing.XL)
        self.viewLayout.setSpacing(Spacing.LARGE)

        self.status_label = SubtitleLabel("準備中...", self)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(60)
        self.viewLayout.addWidget(self.status_label)

        self.progress = ProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMinimumHeight(38)
        self.viewLayout.addWidget(self.progress)

        if show_cancel:
            self.yesButton.setText("取消")
            self.yesButton.clicked.connect(self.cancel)
            self.cancelButton.hide()
        else:
            self.yesButton.hide()
            self.cancelButton.hide()
            self.buttonGroup.hide()
            self.buttonLayout.setContentsMargins(0, 0, 0, 0)
            self.buttonGroup.setFixedSize(0, 0)

        self.cancelled = False
        self._last_percent: float = -1.0
        self._last_status = ""
        self.progress_requested.connect(self._apply_progress_update)

        self.setFixedSize(520, 290 if show_cancel else 230)

        self._center_on_parent(parent)

    def _center_on_parent(self, parent: Any) -> None:
        parent_window = parent.window() if parent is not None and hasattr(parent, "window") else parent
        screen = parent_window.screen() if parent_window is not None and hasattr(parent_window, "screen") else None
        if screen is None:
            screen = QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        self.move(
            geometry.center().x() - self.width() // 2,
            geometry.center().y() - self.height() // 2,
        )

    def update_progress(self, percent: float, status_text: str) -> bool:
        """
        更新進度百分比與狀態文字

        Args:
            percent: 進度百分比
            status_text: 要顯示的狀態文字

        Returns:
            成功排程或完成更新時回傳 True；已取消時回傳 False
        """
        if self.cancelled:
            return False
        if self._last_percent == percent and self._last_status == status_text:
            return True
        self._last_percent = percent
        self._last_status = status_text

        self.progress_requested.emit(percent, status_text)
        return True

    def cancel(self) -> None:
        """取消並關閉對話框"""
        self.cancelled = True
        self.close()

    @Slot(float, str)
    def _apply_progress_update(self, percent: float, status_text: str) -> None:
        if self.cancelled or not is_qobject_alive(self):
            return
        try:
            clamped = max(0.0, min(100.0, percent))
            self.progress.setValue(round(clamped))
            self.status_label.setText(status_text)
        except Exception as exc:
            logger.exception(f"更新進度 UI 失敗: {exc}")


__all__ = ["ProgressDialog"]
