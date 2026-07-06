"""視窗圖示工具。"""

from __future__ import annotations

import contextlib

from ..utils import PathUtils, get_logger
from ..utils.ui_support.qt_runtime import QtCore, QtGui, QtWidgets, invoke_later, is_qobject_alive

logger = get_logger().bind(component="IconUtils")


class IconUtils:
    """集中處理視窗圖示的延遲綁定與重試。"""

    @staticmethod
    def set_window_icon(window, delay_ms=200) -> None:
        """設定視窗 icon，並在不同生命週期時機補設，避免被 Qt/系統主題覆寫。

        Args:
            window: 要設定圖示的視窗。
            delay_ms: 延遲重試的毫秒數。
        """
        icon_path = PathUtils.get_assets_path() / "icon.ico"
        if not icon_path.exists():
            logger.warning(f"圖示檔案不存在 - {icon_path}")
            return
        icon_str = str(icon_path)
        icon = QtGui.QIcon(icon_str)

        def _apply_icon() -> None:
            try:
                if not is_qobject_alive(window):
                    return
                window.setWindowIcon(icon)
                app = QtWidgets.QApplication.instance()
                if isinstance(app, QtWidgets.QApplication):
                    app.setWindowIcon(icon)
                window._msm_icon_set = True
                window.update()
            except (Exception, AttributeError, RuntimeError) as e:
                logger.warning(f"設定視窗圖示暫時性錯誤: {e}")

        def _on_window_state_change(_event=None) -> bool:
            invoke_later(0, _apply_icon, parent=window if isinstance(window, QtCore.QObject) else None)
            return False

        try:
            for retry_delay in (0, delay_ms, delay_ms + 120, delay_ms + 500):
                invoke_later(retry_delay, _apply_icon, parent=window if isinstance(window, QtCore.QObject) else None)
            if not getattr(window, "_msm_icon_event_bound", False):
                with contextlib.suppress(Exception):
                    window._msm_icon_event_filter = _IconRefreshFilter(window, _on_window_state_change)
                    window.installEventFilter(window._msm_icon_event_filter)
                window._msm_icon_event_bound = True
        except Exception as e:
            logger.warning(f"無法延遲執行圖示綁定: {e}")
            _apply_icon()


class _IconRefreshFilter(QtCore.QObject):
    """在視窗顯示或聚焦時補設 icon。"""

    def __init__(self, window, callback) -> None:
        super().__init__(window)
        self._callback = callback

    def eventFilter(self, watched, event) -> bool:
        """攔截 Qt 事件並依目前元件狀態處理。"""
        if event.type() in {QtCore.QEvent.Type.Show, QtCore.QEvent.Type.WindowActivate}:
            self._callback(event)
        return super().eventFilter(watched, event)


__all__ = ["IconUtils"]
