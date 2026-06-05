"""原生 Qt 進度對話框。"""

from __future__ import annotations

from typing import Any

from ..utils import FontSize, Sizes, Spacing, get_logger
from ..utils.ui_support import qt_widgets as qt
from ..utils.ui_support.fluent import FluentPushButton
from ..utils.ui_support.qt_runtime import QtCore, QtWidgets, is_qobject_alive
from . import DialogUtils, FontManager
from .ui_config import NativeQtStyle

logger = get_logger().bind(component="ProgressDialog")


class _ProgressDialogSignals(QtCore.QObject):
    progress_requested = QtCore.Signal(float, str)
    close_requested = QtCore.Signal()


class ProgressDialog:
    """顯示可取消的進度對話框。"""

    def __init__(self, parent: Any, title: str = "進度", show_cancel: bool = True) -> None:
        self.dialog = DialogUtils.create_toplevel_dialog(
            parent,
            title,
            width=Sizes.DIALOG_PROGRESS_WIDTH,
            height=Sizes.DIALOG_PROGRESS_HEIGHT,
            bind_icon=True,
            center_on_parent=True,
            make_modal=True,
            min_width=560,
            min_height=240,
            reveal_after_setup=True,
        )
        self.dialog.setStyleSheet(NativeQtStyle.progress_dialog)

        layout = QtWidgets.QVBoxLayout(self.dialog)
        margin = Spacing.XL
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(Spacing.LARGE_MINUS)
        self.status_label = QtWidgets.QLabel("準備中...", self.dialog)
        self.status_label.setFont(FontManager.get_font(size=FontSize.LARGE, weight="bold"))
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress = qt.ProgressBar(self.dialog)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMinimumHeight(38)
        self.progress.setFont(FontManager.get_font(size=FontSize.NORMAL_PLUS, weight="bold"))
        self.progress.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)

        self.cancel_button: QtWidgets.QPushButton | None = None
        if show_cancel:
            try:
                self.cancel_button = FluentPushButton("取消", self.dialog)
            except TypeError:
                self.cancel_button = FluentPushButton(self.dialog)
                self.cancel_button.setText("取消")
            self.cancel_button.setFont(FontManager.get_font(size=FontSize.NORMAL))
            self.cancel_button.setMinimumSize(Sizes.BUTTON_WIDTH_COMPACT, Sizes.BUTTON_HEIGHT_LARGE)
            self.cancel_button.setStyleSheet(NativeQtStyle.create_button(kind="secondary"))
            self.cancel_button.clicked.connect(self.cancel)
            layout.addWidget(self.cancel_button, 0, QtCore.Qt.AlignmentFlag.AlignCenter)

        self.cancelled = False
        self._pending_update = False
        self._last_percent: float = -1.0
        self._last_status = ""
        self._signals = _ProgressDialogSignals(self.dialog)
        self._signals.progress_requested.connect(self._apply_progress_update)
        self._signals.close_requested.connect(self._close_dialog)

    def update_progress(self, percent: float, status_text: str) -> bool:
        """更新進度百分比與狀態文字。

        Args:
            percent: 進度百分比。
            status_text: 要顯示的狀態文字。

        Returns:
            成功排程或完成更新時回傳 True；已取消時回傳 False。
        """
        if self.cancelled:
            return False
        if self._last_percent == percent and self._last_status == status_text:
            return True
        self._last_percent = percent
        self._last_status = status_text

        self._signals.progress_requested.emit(float(percent), str(status_text))
        return True

    @QtCore.Slot(float, str)
    def _apply_progress_update(self, percent: float, status_text: str) -> None:
        if self.cancelled or not is_qobject_alive(self.dialog):
            return
        try:
            clamped = max(0.0, min(100.0, float(percent)))
            self.progress.setValue(round(clamped))
            self.status_label.setText(status_text)
        except Exception as exc:
            logger.exception(f"更新進度 UI 失敗: {exc}")

    def cancel(self) -> None:
        """取消並關閉對話框。"""
        self.cancelled = True
        self.close()

    def close(self) -> None:
        """關閉對話框。"""
        try:
            self._signals.close_requested.emit()
        except Exception as exc:
            logger.exception(f"關閉進度對話框失敗: {exc}")

    @QtCore.Slot()
    def _close_dialog(self) -> None:
        if is_qobject_alive(self.dialog):
            self.dialog.close()
            self.dialog.deleteLater()


__all__ = ["ProgressDialog"]
