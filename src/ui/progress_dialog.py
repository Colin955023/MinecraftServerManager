"""原生 Qt 進度對話框"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Qt, Signal, Slot
from qfluentwidgets import ProgressBar, SubtitleLabel, TitleLabel

from ..utils import (
    Spacing,
    get_logger,
    is_qobject_alive,
)
from . import ModalMSFluentWindow

logger = get_logger().bind(component="ProgressDialog")


class _ProgressDialogSignals(QObject):
    progress_requested = Signal(float, str)
    close_requested = Signal()


class ProgressDialog(ModalMSFluentWindow):
    """顯示可取消的進度對話框"""

    def __init__(self, parent: Any, title: str = "進度", show_cancel: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.custom_title = TitleLabel(title, self.widget)
        self.viewLayout.addWidget(self.custom_title)

        self.viewLayout.setContentsMargins(Spacing.XL, Spacing.XL, Spacing.XL, Spacing.XL)
        self.viewLayout.setSpacing(Spacing.LARGE_MINUS)

        self.status_label = SubtitleLabel("準備中...", self)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.viewLayout.addWidget(self.status_label)

        self.progress = ProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMinimumHeight(38)
        self.viewLayout.addWidget(self.progress)

        self.cancel_button = None
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
        self._signals = _ProgressDialogSignals(self)
        self._signals.progress_requested.connect(self._apply_progress_update)

        self.widget.setMinimumWidth(560)

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

        self._signals.progress_requested.emit(percent, status_text)
        return True

    def cancel(self) -> None:
        """取消並關閉對話框"""
        self.cancelled = True
        self.close()

    def close(self) -> None:
        """關閉對話框"""
        super().close()

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
