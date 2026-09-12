"""原生 PySide6 runtime 工具"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import isValid as shiboken_is_valid

from src.utils import OperationCancelledError, RuntimePaths, current_work_token

_dispatcher: _UiDispatcher | None = None
_dispatcher_lock = threading.Lock()
_ui_closing = threading.Event()


def set_ui_closing(closing: bool) -> None:
    """
    切換退出狀態，讓背景執行緒停止等待 UI 回應

    Args:
        closing: True 表示 UI 正在關閉，False 表示 UI 尚未關閉
    """
    if closing:
        _ui_closing.set()
    else:
        _ui_closing.clear()


def _resolve_application_icon() -> QtGui.QIcon:
    """
    解析目前執行型態可用的應用程式圖示

    Nuitka 會把 PE icon 寫入執行檔資源，但自訂 Fluent title bar 不保證自動沿用
    Qt 頂層視窗仍需確保 QApplication.windowIcon 有效
    """
    if RuntimePaths.is_packaged():
        with suppress(OSError, RuntimeError):
            provider = QtWidgets.QFileIconProvider()
            icon = provider.icon(QtCore.QFileInfo(sys.executable))
            if not icon.isNull():
                return icon

    try:
        icon_path = Path(__file__).resolve().parents[3] / "assets" / "icon.ico"
        if icon_path.is_file():
            icon = QtGui.QIcon(str(icon_path))
            if not icon.isNull():
                return icon
    except OSError:
        pass
    return QtGui.QIcon()


def _apply_application_icon(app: QtWidgets.QApplication) -> None:
    """確保 Qt application 取得可供所有頂層視窗繼承的圖示"""
    if not app.windowIcon().isNull():
        return
    icon = _resolve_application_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)


def apply_window_icon(window: QtWidgets.QWidget) -> None:
    """
    將 application icon 套用到頂層視窗與 Fluent title bar

    Args:
        window: 要套用圖示的頂層視窗
    """
    app = ensure_application()
    icon = app.windowIcon()
    if icon.isNull():
        return
    try:
        window.setWindowIcon(icon)
    except RuntimeError:
        return
    title_bar = getattr(window, "titleBar", None)
    set_icon = getattr(title_bar, "setIcon", None)
    if callable(set_icon):
        with suppress(RuntimeError, TypeError):
            set_icon(icon)


def ensure_application() -> QtWidgets.QApplication:
    """
    取得或建立 QApplication

    Returns:
        目前行程可使用的 QApplication 實例
    """
    global _dispatcher
    app = QtWidgets.QApplication.instance()
    if not isinstance(app, QtWidgets.QApplication):
        app = QtWidgets.QApplication(sys.argv[:1])

    app.setAttribute(
        QtCore.Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings,
        True,
    )

    _apply_application_icon(app)

    if QtCore.QThread.currentThread() is app.thread() and (_dispatcher is None or not is_qobject_alive(_dispatcher)):
        with _dispatcher_lock:
            if _dispatcher is None or not is_qobject_alive(_dispatcher):
                _dispatcher = _UiDispatcher()

    return app


def is_qobject_alive(obj: Any) -> bool:
    """
    確認 QObject 尚未被 Qt 銷毀

    Args:
        obj: 要檢查的 QObject 或任意物件

    Returns:
        物件仍可安全存取時回傳 True
    """
    if obj is None:
        return False

    try:
        return bool(shiboken_is_valid(obj)) if isinstance(obj, QtCore.QObject) else True
    except RuntimeError, TypeError:
        return False


def invoke_later(delay_ms: int, callback: Callable[[], Any], *, parent: QtCore.QObject | None = None) -> QtCore.QTimer:
    """
    使用 QTimer 排程一次性 callback

    Args:
        delay_ms: 延遲毫秒數
        callback: 要執行的回呼
        parent: timer 的 Qt parent

    Returns:
        可取消的一次性 QTimer
    """
    app = ensure_application()
    if QtCore.QThread.currentThread() is not app.thread():
        timer = QtCore.QTimer()
        timer.setSingleShot(True)
        timer.moveToThread(app.thread())

        def _bg_run() -> None:
            try:
                if parent is not None and not is_qobject_alive(parent):
                    return
                callback()
            finally:
                if is_qobject_alive(timer):
                    timer.deleteLater()

        timer.timeout.connect(_bg_run)
        QtCore.QMetaObject.invokeMethod(
            timer, "start", QtCore.Qt.ConnectionType.QueuedConnection, QtCore.Q_ARG(int, max(0, int(delay_ms)))
        )
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
    """
    停止並釋放 QTimer

    Args:
        timer: 要取消的 QTimer 或相容物件
    """
    if not is_qobject_alive(timer):
        return
    try:
        timer.stop()
        timer.deleteLater()
    except RuntimeError:
        return


class _UiDispatcher(QtCore.QObject):
    dispatched = QtCore.Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.dispatched.connect(self._run, QtCore.Qt.ConnectionType.QueuedConnection)

    @QtCore.Slot(object)
    def _run(self, payload: object) -> None:
        func, done, result = cast(tuple[Callable[[], Any], QtCore.QSemaphore, dict[str, Any]], payload)
        try:
            if _ui_closing.is_set() or result.get("abandoned"):
                raise OperationCancelledError("視窗已關閉或工作已取消")
            result["value"] = func()
        except Exception as e:
            result["exc"] = e
        finally:
            done.release()


def run_on_ui_thread(func: Callable[[], Any], timeout: float | None = 30.0) -> Any:
    """
    在 Qt UI thread 執行 callable，必要時等待結果

    Args:
        func: 要在 UI thread 執行的 callable
        timeout: 從背景 thread 等待結果的秒數

    Returns:
        callable 的回傳值
    """
    if _ui_closing.is_set():
        raise OperationCancelledError("應用程式正在關閉")
    app = ensure_application()
    if QtCore.QThread.currentThread() is app.thread():
        return func()

    global _dispatcher
    if _dispatcher is None or not is_qobject_alive(_dispatcher):
        with _dispatcher_lock:
            if _dispatcher is None or not is_qobject_alive(_dispatcher):
                _dispatcher = _UiDispatcher()
                _dispatcher.moveToThread(app.thread())
    done = QtCore.QSemaphore(0)
    result: dict[str, Any] = {"value": None, "exc": None}
    _dispatcher.dispatched.emit((func, done, result))
    deadline = None if timeout is None else time.monotonic() + timeout
    token = current_work_token()
    try:
        while not done.tryAcquire(1, 50):
            token.check()
            if _ui_closing.is_set():
                raise OperationCancelledError("應用程式正在關閉")
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(f"UI 工作等待逾時 ({timeout} 秒)")
    except Exception:
        result["abandoned"] = True
        raise
    if result["exc"] is not None:
        raise result["exc"]
    return result["value"]


class ValueState(QtCore.QObject):
    """輕量 UI 狀態容器，透過 Qt signal 通知變更"""

    changed = QtCore.Signal(object)

    def __init__(self, value: Any = None, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._value = value

    def get(self) -> Any:
        """
        取得目前值

        Returns:
            目前儲存的狀態值
        """
        return self._value

    def set(self, value: Any) -> None:
        """
        設定值並送出變更通知

        Args:
            value: 新狀態值
        """
        if self._value == value:
            return
        self._value = value
        self.changed.emit(value)

    def trace_add(self, callback: Callable[[], Any]) -> None:
        """
        註冊狀態變更回呼

        Args:
            callback: 狀態變更時呼叫的回呼

        """

        def _run() -> None:
            callback()

        self.changed.connect(_run)


__all__ = [
    "ValueState",
    "apply_window_icon",
    "cancel_timer",
    "ensure_application",
    "invoke_later",
    "is_qobject_alive",
    "run_on_ui_thread",
]
