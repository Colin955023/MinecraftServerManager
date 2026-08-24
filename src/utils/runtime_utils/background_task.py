"""
背景任務工具、取消標記與共享工作池

提供背景任務執行器（基於 QThreadPool）、協作式取消（CancellationToken），
以及專案共享工作池（原 worker_pool.py 合併至此）

規範：若任務支援取消，應接受名為 cancel_token 的參數並自行檢查其狀態
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import os
import threading
from collections.abc import Callable
from typing import Any

from PySide6 import QtCore

from src.utils import get_logger

logger = get_logger().bind(component="BackgroundTask")

DEFAULT_WORKER_COUNT = min(16, (os.cpu_count() or 4) + 4)
_shared_manager_lock = threading.Lock()


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


def _make_done_callback(
    callback: Callable[[Any], None],
    task_label: str = "Background task",
) -> Callable[[concurrent.futures.Future | asyncio.Future], None]:
    """建立統一的任務完成回呼包裝器"""

    def _on_done(future) -> None:
        try:
            result = future.result()
        except Exception as exc:
            logger.exception(f"{task_label} failed: {exc}")
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
    """簡單的背景任務執行器，支援取消 token 與回呼"""

    def __init__(self, max_workers: int = DEFAULT_WORKER_COUNT):
        self._pool = QtCore.QThreadPool()
        self._pool.setMaxThreadCount(max(1, int(max_workers)))

    def run(
        self,
        fn: Callable[..., Any],
        *args,
        callback: Callable[[Any], None] | None = None,
        cancel_token: CancellationToken | None = None,
        **kwargs,
    ) -> concurrent.futures.Future:
        """
        提交背景任務到 QThreadPool 執行

        Args:
            fn: 要執行的函式
            *args: 傳入函式的位置參數
            callback: 任務完成後的回呼，會在背景執行緒被呼叫
            cancel_token: 協作式取消標記
            **kwargs: 傳入函式的關鍵字參數

        Returns:
            提交到執行器後的 Future
        """
        if cancel_token is not None and "cancel_token" not in kwargs:
            kwargs["cancel_token"] = cancel_token
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        runnable = _QtRunnable(future, functools.partial(fn, *args, **kwargs))
        try:
            self._pool.start(runnable)
        except RuntimeError:
            logger.debug("QThreadPool 已銷毀，無法提交背景任務")
            future.set_exception(RuntimeError("QThreadPool has been deleted, cannot submit background task"))
            return future
        if callback:
            future.add_done_callback(_make_done_callback(callback))
        return future

    def shutdown(self, wait: bool = True, timeout_ms: int = 2000) -> None:
        """
        關閉 Qt 工作池，必要時等待既有任務完成

        Args:
            wait: 是否等待既有任務完成
            timeout_ms: 最大等待毫秒數，預設 2000ms
        """
        if wait:
            if not self._pool.waitForDone(timeout_ms):
                self._pool.clear()
        else:
            self._pool.clear()


class _QtRunnable(QtCore.QRunnable):
    """在 QThreadPool 中執行 Python callable，並同步完成 Future"""

    def __init__(self, future: concurrent.futures.Future[Any], call: Callable[[], Any]) -> None:
        super().__init__()
        self.future = future
        self.call = call
        self.setAutoDelete(True)

    def run(self) -> None:
        """執行背景工作中保存的 callable"""
        if not self.future.set_running_or_notify_cancel():
            return
        try:
            result = self.call()
        except Exception as exc:
            self.future.set_exception(exc)
            return
        self.future.set_result(result)


_shared_manager: BackgroundTaskManager | None = None


def get_shared_manager() -> BackgroundTaskManager:
    """
    取得全域共用的背景任務管理器（相容既有呼叫端，執行緒安全）

    Returns:
        全域共用的 BackgroundTaskManager 實例
    """
    global _shared_manager
    if _shared_manager is None:
        with _shared_manager_lock:
            if _shared_manager is None:
                _shared_manager = BackgroundTaskManager()
    return _shared_manager


def shutdown_shared_manager(wait: bool = True) -> None:
    """
    停止並釋放全域背景工作池，避免程式結束時仍有工作存取已關閉資源

    Args:
        wait: 是否等待既有任務完成
    """
    global _shared_manager
    with _shared_manager_lock:
        manager = _shared_manager
        _shared_manager = None
    if manager is not None:
        manager.shutdown(wait=wait)


def run_in_background(
    fn: Callable[..., Any], *args, callback: Callable[[Any], None] | None = None, **kwargs
) -> concurrent.futures.Future[Any] | None:
    """
    使用共享 BackgroundTaskManager 的便利函式

    若無法使用共享 manager，會同步完成一個 Future 以保持錯誤可觀測

    Args:
        fn: 要執行的函式
        *args: 傳入函式的位置參數
        callback: 任務完成後的回呼，會在背景執行緒被呼叫
        **kwargs: 傳入函式的關鍵字參數

    Returns:
        提交到執行器後的 Future，若無法使用共享 manager 則回傳 None
    """
    try:
        return get_shared_manager().run(fn, *args, callback=callback, **kwargs)
    except Exception as exc:
        logger.warning(f"Shared BackgroundTaskManager unavailable, running fallback Future synchronously: {exc}")
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        try:
            result = fn(*args, **kwargs)
        except Exception as e:
            future.set_exception(e)
            logger.exception(f"背景任務執行失敗: {e}")
            if callback:
                callback(None)
        else:
            future.set_result(result)
            if callback:
                callback(result)
        return future


__all__ = [
    "CancellationToken",
    "get_shared_manager",
    "run_in_background",
    "shutdown_shared_manager",
]
