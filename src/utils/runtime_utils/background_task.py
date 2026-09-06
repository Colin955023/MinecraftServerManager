"""
背景工作工具、取消標記與共享工作池

提供背景工作執行器（基於 QThreadPool）、協作式取消（CancellationToken），
以及專案共享工作池（原 worker_pool.py 合併至此）

規範：若工作支援取消，應接受名為 cancel_token 的參數並自行檢查其狀態
"""

from __future__ import annotations

import concurrent.futures
import functools
import os
import threading
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

from PySide6 import QtCore

from src.utils import OperationCancelledError, get_logger

logger = get_logger().bind(component="BackgroundTask")

DEFAULT_WORKER_COUNT = min(16, (os.cpu_count() or 4) + 4)
_shared_manager_lock = threading.Lock()
_work_context = threading.local()


class CancellationToken:
    """簡易的取消標記，用於協作式取消"""

    def __init__(self):
        self._event = threading.Event()

    def cancel(self) -> None:
        """將取消標記設為已取消"""
        self._event.set()

    def is_cancelled(self) -> bool:
        """
        回傳目前是否已請求取消

        Returns:
            True 表示已請求取消，False 表示尚未請求取消
        """
        return self._event.is_set()

    def check(self) -> None:
        """在安全取消點中止工作"""
        if self.is_cancelled():
            raise OperationCancelledError("工作已取消")

    def wait(self, seconds: float) -> None:
        """
        等待可被取消標記喚醒的退避時間

        Args:
            seconds: 等待的秒數，若為負數則立即返回
        """
        if self._event.wait(max(0.0, seconds)):
            self.check()


def current_work_token() -> CancellationToken:
    """
    取得目前工作及其子工作的取消標記

    Returns:
        目前工作及其子工作的 CancellationToken 實例
    """
    token = getattr(_work_context, "token", None)
    return token if token is not None else CancellationToken()


@contextmanager
def work_cancellation(token: CancellationToken):
    """
    在目前執行緒內傳遞取消標記，離開時還原原有工作

    Args:
        token: 要傳遞的 CancellationToken 實例
    """
    previous = getattr(_work_context, "token", None)
    _work_context.token = token
    try:
        yield
    finally:
        _work_context.token = previous


def _make_done_callback(
    callback: Callable[[Any], None],
    task_label: str = "Background task",
) -> Callable[[concurrent.futures.Future[Any]], None]:
    """建立統一的工作完成回呼包裝器"""

    def _on_done(future) -> None:
        try:
            result = future.result()
        except Exception as e:
            logger.exception(f"{task_label} failed: {e}")
            try:
                callback(None)
            except Exception:
                logger.exception(f"{task_label} callback failed while handling exception")
            return
        try:
            callback(result)
        except Exception:
            logger.exception(f"{task_label} callback raised an exception")

    return _on_done


class BackgroundTaskManager:
    """簡單的背景工作執行器，支援取消 token 與回呼"""

    def __init__(self, max_workers: int = DEFAULT_WORKER_COUNT):
        self._pool = QtCore.QThreadPool()
        self._pool.setMaxThreadCount(max(1, int(max_workers)))
        self._lock = threading.RLock()
        self._futures: set[concurrent.futures.Future[Any]] = set()
        self._future_tokens: dict[concurrent.futures.Future[Any], CancellationToken] = {}
        self._closing = False

    def run(
        self,
        fn: Callable[..., Any],
        *args,
        callback: Callable[[Any], None] | None = None,
        cancel_token: CancellationToken | None = None,
        **kwargs,
    ) -> concurrent.futures.Future:
        """
        提交背景工作到 QThreadPool 執行

        Args:
            fn: 要執行的函式
            *args: 傳入函式的位置參數
            callback: 工作完成後的回呼，會在背景執行緒被呼叫
            cancel_token: 協作式取消標記
            **kwargs: 傳入函式的關鍵字參數

        Returns:
            提交到執行器後的 Future
        """
        if cancel_token is not None and "cancel_token" not in kwargs:
            kwargs["cancel_token"] = cancel_token
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        runnable = _QtRunnable(future, functools.partial(fn, *args, **kwargs), cancel_token or current_work_token())
        with self._lock:
            if self._closing:
                future.cancel()
                return future
            self._futures.add(future)
            self._future_tokens[future] = runnable.token
            future.add_done_callback(self._forget_future)
            self._pool.start(runnable)
        if callback:
            future.add_done_callback(_make_done_callback(callback))
        return future

    def _forget_future(self, future: concurrent.futures.Future[Any]) -> None:
        with self._lock:
            self._futures.discard(future)
            self._future_tokens.pop(future, None)

    def shutdown(self, wait: bool = True, timeout_ms: int = 2000) -> bool:
        """
        關閉 Qt 工作池，必要時等待既有工作完成

        Args:
            wait: 是否等待既有工作完成
            timeout_ms: 最大等待毫秒數，預設 2000ms

        Returns:
            工作池已完成關閉時回傳 True
        """
        with self._lock:
            self._closing = True
            for future in tuple(self._futures):
                token = self._future_tokens.get(future)
                if token is not None:
                    token.cancel()
                future.cancel()
            self._pool.clear()
        return self._pool.waitForDone(timeout_ms if wait else 0)


class _QtRunnable(QtCore.QRunnable):
    """在 QThreadPool 中執行 Python callable，並同步完成 Future"""

    def __init__(
        self, future: concurrent.futures.Future[Any], call: Callable[[], Any], token: CancellationToken
    ) -> None:
        super().__init__()
        self.future = future
        self.call = call
        self.token = token
        self.setAutoDelete(True)

    def run(self) -> None:
        """執行背景工作中保存的 callable"""
        if not self.future.set_running_or_notify_cancel():
            return
        try:
            with work_cancellation(self.token):
                self.token.check()
                result = self.call()
        except Exception as e:
            self.future.set_exception(e)
            return
        self.future.set_result(result)


_shared_manager: BackgroundTaskManager | None = None


def get_shared_manager() -> BackgroundTaskManager:
    """
    取得全域共用的背景工作管理器

    Returns:
        全域共用的 BackgroundTaskManager 實例
    """
    global _shared_manager
    if _shared_manager is None:
        with _shared_manager_lock:
            if _shared_manager is None:
                _shared_manager = BackgroundTaskManager()
    return _shared_manager


def shutdown_shared_manager(wait: bool = True) -> bool:
    """
    停止並釋放全域背景工作池，避免程式結束時仍有工作存取已關閉資源

    Args:
        wait: 是否等待既有工作完成

    Returns:
        工作池已完成關閉時回傳 True
    """
    global _shared_manager
    with _shared_manager_lock:
        manager = _shared_manager
    if manager is not None:
        if not manager.shutdown(wait=wait):
            return False
        with _shared_manager_lock:
            if _shared_manager is manager:
                _shared_manager = None
    return True


__all__ = [
    "CancellationToken",
    "current_work_token",
    "get_shared_manager",
    "shutdown_shared_manager",
    "work_cancellation",
]
