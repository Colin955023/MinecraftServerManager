"""原生 PySide6 runtime 工具。"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any, cast

from PySide6 import QtCore, QtGui, QtWidgets

shiboken_is_valid: Callable[[Any], bool] | None

try:
    from shiboken6 import isValid as shiboken_is_valid
except ImportError:
    shiboken_is_valid = None

_dispatcher: _UiDispatcher | None = None


def ensure_application() -> QtWidgets.QApplication:
    """取得或建立 QApplication。

    Returns:
        目前行程可使用的 QApplication 實例。
    """
    app = QtWidgets.QApplication.instance()
    if not isinstance(app, QtWidgets.QApplication):
        app = QtWidgets.QApplication(sys.argv[:1])
    return app


def is_qobject_alive(obj: Any) -> bool:
    """確認 QObject 尚未被 Qt 銷毀。

    Args:
        obj: 要檢查的 QObject 或任意物件。

    Returns:
        物件仍可安全存取時回傳 True。
    """
    if obj is None:
        return False

    # 優先調用 shiboken 檢查 C++ 記憶體狀態以確保穩定。
    # 若環境限制無法導入，則透過存取屬性誘發 RuntimeError 作為相容替代方案。
    if shiboken_is_valid is not None:
        try:
            return bool(shiboken_is_valid(obj))
        except Exception:
            return False
    try:
        if isinstance(obj, QtCore.QObject):
            obj.objectName()
        return True
    except RuntimeError:
        return False


def invoke_later(delay_ms: int, callback: Callable[[], Any], *, parent: QtCore.QObject | None = None) -> QtCore.QTimer:
    """使用 QTimer 排程一次性 callback。

    Args:
        delay_ms: 延遲毫秒數。
        callback: 要執行的回呼。
        parent: timer 的 Qt parent。

    Returns:
        可取消的一次性 QTimer。
    """
    app = ensure_application()
    if QtCore.QThread.currentThread() is not app.thread():
        try:
            return cast(
                QtCore.QTimer,
                run_on_ui_thread(lambda: invoke_later(delay_ms, callback, parent=parent), timeout=5.0),
            )
        except Exception:
            timer = QtCore.QTimer()
            timer.setSingleShot(True)
            return timer
    timer_parent = parent if is_qobject_alive(parent) else None
    timer = QtCore.QTimer(timer_parent)
    timer.setSingleShot(True)

    def _run() -> None:
        try:
            callback()
        finally:
            if is_qobject_alive(timer):
                timer.deleteLater()

    timer.timeout.connect(_run)
    timer.start(max(0, int(delay_ms)))
    return timer


def cancel_timer(timer: Any) -> None:
    """停止並釋放 QTimer。

    Args:
        timer: 要取消的 QTimer 或相容物件。
    """
    if not is_qobject_alive(timer):
        return
    try:
        timer.stop()
        timer.deleteLater()
    except RuntimeError:
        return


class _OpenUrlClickFilter(QtCore.QObject):
    """把滑鼠點擊轉成開啟外部網址的 Qt event filter。"""

    def __init__(self, url: str, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._url = str(url)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        """攔截 Qt 事件並依目前元件狀態處理。"""
        if event.type() == QtCore.QEvent.Type.MouseButtonRelease:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(self._url))
            return True
        return super().eventFilter(watched, event)


def install_open_url_click(widget: QtWidgets.QWidget, url: str) -> None:
    """讓 widget 被點擊時開啟指定外部網址。

    Args:
        widget: 要安裝點擊處理器的 Qt widget。
        url: 點擊後要開啟的外部網址。
    """

    click_filter = _OpenUrlClickFilter(url, widget)
    widget.installEventFilter(click_filter)
    cast(Any, widget)._msm_open_url_click_filter = click_filter


class _UiDispatcher(QtCore.QObject):
    dispatched = QtCore.Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.dispatched.connect(self._run, QtCore.Qt.ConnectionType.QueuedConnection)

    @QtCore.Slot(object)
    def _run(self, payload: object) -> None:
        func, done, result = cast(tuple[Callable[[], Any], QtCore.QSemaphore, dict[str, Any]], payload)
        try:
            result["value"] = func()
        except Exception as exc:
            result["exc"] = exc
        finally:
            done.release()


def run_on_ui_thread(func: Callable[[], Any], timeout: float | None = None) -> Any:
    """在 Qt UI thread 執行 callable，必要時等待結果。

    Args:
        func: 要在 UI thread 執行的 callable。
        timeout: 從背景 thread 等待結果的秒數。

    Returns:
        callable 的回傳值。
    """
    app = ensure_application()
    if QtCore.QThread.currentThread() is app.thread():
        return func()

    global _dispatcher
    if _dispatcher is None or not is_qobject_alive(_dispatcher):
        _dispatcher = _UiDispatcher()
        _dispatcher.moveToThread(app.thread())
    done = QtCore.QSemaphore(0)
    result: dict[str, Any] = {"value": None, "exc": None}
    _dispatcher.dispatched.emit((func, done, result))
    if timeout is None:
        done.acquire()
    elif not done.tryAcquire(1, max(0, int(timeout * 1000))):
        raise TimeoutError(f"UI 任務等待逾時 ({timeout}秒)")
    if result["exc"] is not None:
        raise result["exc"]
    return result["value"]


class ValueState(QtCore.QObject):
    """輕量 UI 狀態容器，透過 Qt signal 通知變更。"""

    changed = QtCore.Signal(object)

    def __init__(self, value: Any = None, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._value = value

    def get(self) -> Any:
        """取得目前值。

        Returns:
            目前保存的狀態值。
        """
        return self._value

    def set(self, value: Any) -> None:
        """設定值並發送變更通知。

        Args:
            value: 新狀態值。
        """
        if self._value == value:
            return
        self._value = value
        self.changed.emit(value)

    def trace_add(self, _mode: str, callback: Callable[..., Any]) -> str:
        """相容既有狀態監聽呼叫點。

        Args:
            _mode: 既有 trace 模式參數，Qt 版忽略。
            callback: 狀態變更時呼叫的回呼。

        Returns:
            監聽器識別字串。
        """

        def _run(_value: Any) -> None:
            callback()

        self.changed.connect(_run)
        return str(id(callback))


def set_window_title(window: QtWidgets.QWidget, title: str) -> None:
    """設定 QWidget / QMainWindow 標題。"""
    if is_qobject_alive(window):
        window.setWindowTitle(title)


def show_window(window: QtWidgets.QWidget, *, raise_window: bool = True) -> None:
    """顯示視窗並選擇性帶到前景。

    Args:
        window: 要顯示的視窗。
        raise_window: 是否將視窗帶到前景。
    """
    if not is_qobject_alive(window):
        return
    window.show()
    if raise_window:
        window.raise_()
        window.activateWindow()


def set_modal(dialog: QtWidgets.QDialog, parent: QtWidgets.QWidget | None = None) -> None:
    """套用 Qt dialog modality。"""
    if parent is not None and is_qobject_alive(parent):
        dialog.setParent(parent, dialog.windowFlags())
    dialog.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
    dialog.setModal(True)


def set_topmost(window: QtWidgets.QWidget, enabled: bool) -> None:
    """設定視窗置頂旗標。"""
    if not is_qobject_alive(window):
        return
    was_visible = window.isVisible()
    window.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, bool(enabled))
    if was_visible:
        window.show()


__all__ = [
    "QtCore",
    "QtGui",
    "QtWidgets",
    "ValueState",
    "cancel_timer",
    "ensure_application",
    "install_open_url_click",
    "invoke_later",
    "is_qobject_alive",
    "run_on_ui_thread",
    "set_modal",
    "set_topmost",
    "set_window_title",
    "show_window",
]
