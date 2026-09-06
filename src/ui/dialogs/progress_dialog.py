"""基於 Fluent 的現代化進度對話框"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import QApplication
from qfluentwidgets import ProgressBar, SubtitleLabel, TitleLabel

from src.models import ProgressEvent
from src.ui import (
    ModalMSFluentWindow,
    Spacing,
    is_qobject_alive,
)
from src.utils import get_logger

logger = get_logger().bind(component="ProgressDialog")


class ProgressDialog(ModalMSFluentWindow):
    """顯示可取消的進度對話框"""

    progress_requested = Signal(float, str)
    progress_event_requested = Signal(object)

    def __init__(self, parent: Any, title: str = "進度", show_cancel: bool = True) -> None:
        super().__init__(parent, is_modal=False)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        if hasattr(self, "titleBar"):
            if hasattr(self.titleBar, "minBtn"):
                self.titleBar.minBtn.hide()
            if hasattr(self.titleBar, "maxBtn"):
                self.titleBar.maxBtn.hide()

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
        self.progress.setMinimumHeight(19)
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
        self._last_determinate_percent: float | None = None
        self.progress_requested.connect(self._apply_progress_update)
        self.progress_event_requested.connect(self._apply_progress_event)

        self.setFixedSize(520, 290 if show_cancel else 230)

        self._center_on_parent(parent)

    def _center_on_parent(self, parent: Any) -> None:
        parent_window = parent.window() if parent is not None and hasattr(parent, "window") else parent
        screen = parent_window.screen() if parent_window is not None and hasattr(parent_window, "screen") else None
        if screen is None:
            screen = QApplication.primaryScreen()
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
        self.reject()

    def update_progress_event(self, event: ProgressEvent) -> bool:
        """
        更新結構化進度事件

        Args:
            event: 建立、下載或安裝階段的進度事件

        Returns:
            對話框仍可接受更新時回傳 True
        """
        if self.cancelled:
            return False
        self.progress_event_requested.emit(event)
        return True

    def closeEvent(self, event) -> None:
        """
        處理視窗關閉事件，確保在關閉時發送取消通知

        Args:
            event: 關閉事件物件
        """
        if not self.cancelled:
            self.cancelled = True
            self.rejected.emit()
        super().closeEvent(event)

    def _apply_determinate_percent(self, percent: float) -> None:
        """
        套用單調遞增的確定式進度
        """
        clamped = max(0.0, min(100.0, percent))
        if self._last_determinate_percent is not None:
            clamped = max(self._last_determinate_percent, clamped)
        self._last_determinate_percent = clamped
        self.progress.setRange(0, 100)
        self.progress.setValue(round(clamped))

    @Slot(float, str)
    def _apply_progress_update(self, percent: float, status_text: str) -> None:
        if self.cancelled or not is_qobject_alive(self):
            return
        try:
            self._apply_determinate_percent(percent)
            self.status_label.setText(status_text)
        except Exception as e:
            logger.exception(f"更新進度 UI 失敗: {e}")

    @Slot(object)
    def _apply_progress_event(self, event: ProgressEvent) -> None:
        if self.cancelled or not is_qobject_alive(self):
            return
        try:
            percent = event.overall_percent
            if percent is None:
                percent = event.phase_percent
            if percent is None:
                if self._last_determinate_percent is None:
                    self.progress.setRange(0, 0)
            else:
                self._apply_determinate_percent(percent)
            self.status_label.setText(event.message)
        except Exception as e:
            logger.exception(f"更新結構化進度 UI 失敗: {e}")


__all__ = ["ProgressDialog"]
