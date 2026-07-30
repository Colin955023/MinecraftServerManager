"""進度對話框。"""

from __future__ import annotations

from typing import Any

from qfluentwidgets import MessageBoxBase, ProgressBar, SubtitleLabel

from ..utils import (
    get_logger,
    is_qobject_alive,
    run_on_ui_thread,
)
from ..utils.ui_support import qt_widgets as qt

logger = get_logger().bind(component="ProgressDialog")


class FluentProgressDialog(MessageBoxBase):
    """基於 qfluentwidgets 的 Fluent 風格進度對話框。"""

    def __init__(self, parent: Any = None, title: str = "進度", show_cancel: bool = True):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(title, self)

        # 建立 Fluent 進度條
        self.progressBar = ProgressBar(self)
        self.progressBar.setMinimum(0)
        self.progressBar.setMaximum(100)
        self.progressBar.setValue(0)
        self.progressBar.setFixedHeight(4)  # 細線進度條

        # 狀態標籤
        self.statusLabel = SubtitleLabel("準備中...", self)
        self.statusLabel.setWordWrap(True)
        # 設定較小的字體
        font = self.statusLabel.font()
        font.setPixelSize(14)
        font.setWeight(qt.QtGui.QFont.Weight.Normal)
        self.statusLabel.setFont(font)

        # 加入 layout
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.progressBar)
        self.viewLayout.addWidget(self.statusLabel)

        # 設定按鈕
        self.yesButton.hide()  # 隱藏確定按鈕

        if show_cancel:
            self.cancelButton.setText("取消")
        else:
            self.cancelButton.hide()

        self.widget.setMinimumWidth(360)


class ProgressDialog:
    """顯示可取消的進度對話框。"""

    def __init__(self, _parent: Any = None, title: str = "進度", show_cancel: bool = True) -> None:
        p = qt.native_parent(_parent)
        self.dialog = FluentProgressDialog(p, title, show_cancel)
        self.cancelled = False
        self._last_percent: float = -1.0
        self._last_status = ""

        if show_cancel:
            self.dialog.cancelButton.clicked.disconnect()
            self.dialog.cancelButton.clicked.connect(self.cancel)

        self.dialog.show()

    def update_progress(self, percent: float, status_text: str) -> bool:
        """
        更新進度百分比與狀態文字。

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

        def _do_update():
            try:
                if is_qobject_alive(self.dialog):
                    clamped = max(0.0, min(100.0, float(percent)))
                    self.dialog.progressBar.setValue(round(clamped))
                    self.dialog.statusLabel.setText(status_text)
            except Exception as exc:
                logger.exception(f"更新進度 UI 失敗: {exc}")

        try:
            run_on_ui_thread(_do_update)
        except Exception as exc:
            logger.exception(f"排程更新進度 UI 失敗: {exc}")
        return True

    def cancel(self) -> None:
        """取消並關閉對話框。"""
        self.cancelled = True
        self.close()

    def close(self) -> None:
        """關閉對話框。"""

        def _do_close():
            try:
                if is_qobject_alive(self.dialog):
                    self.dialog.close()
                    self.dialog.deleteLater()
            except Exception as exc:
                logger.exception(f"關閉進度對話框失敗: {exc}")

        try:
            run_on_ui_thread(_do_close)
        except Exception as exc:
            logger.exception(f"排程關閉進度對話框失敗: {exc}")


__all__ = ["ProgressDialog"]
