"""
背景任務工具、取消標記與共享工作池

提供背景任務執行器（基於 QThreadPool）、協作式取消（CancellationToken），
以及專案共享工作池（原 worker_pool.py 合併至此）

規範：若任務支援取消，應接受名為 `cancel_token` 的參數並自行檢查其狀態
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import inspect
import os
from collections.abc import Callable
from typing import Any, TypeVar

from PySide6 import QtCore

from .. import get_logger

logger = get_logger().bind(component="BackgroundTask")

T = TypeVar("T")

DEFAULT_WORKER_COUNT = 4

__all__ = [
    "DEFAULT_WORKER_COUNT",
    "BackgroundTaskManager",
    "CancellationToken",
    "get_shared_manager",
    "get_shared_worker_pool",
    "resolve_worker_count",
    "run_in_background",
]


class CancellationToken:
    """簡易的取消標記，用於協作式取消"""

    def __init__(self):
        self._cancelled = False

    def cancel(self) -> None:
        """將取消標記設為已取消"""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        """
        回傳目前是否已請求取消

        Returns:
            True 表示已請求取消，False 表示尚未請求取消
        """
        return self._cancelled


def _make_done_callback(
    callback: Callable[[Any], None],
    task_label: str = "Background task",
) -> Callable[[concurrent.futures.Future | asyncio.Future], None]:
    """建立統一的任務完成回呼包裝器，消除 run() 與 run_async() 中的重複邏輯"""

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

    def __init__(self, max_workers: int = 4):
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

    async def run_async(
        self,
        fn: Callable[..., Any],
        *args,
        callback: Callable[[Any], None] | None = None,
        cancel_token: CancellationToken | None = None,
        **kwargs,
    ) -> asyncio.Task:
        """
        以協程介面執行任務

        Args:
            fn: 要執行的函式或協程函式
            *args: 傳入函式的位置參數
            callback: 任務完成後的回呼
            cancel_token: 協作式取消標記
            **kwargs: 傳入函式的關鍵字參數

        Returns:
            可由呼叫方 await 的 asyncio Task
        """
        if cancel_token is not None and "cancel_token" not in kwargs:
            kwargs["cancel_token"] = cancel_token
        loop = asyncio.get_running_loop()
        if inspect.iscoroutinefunction(fn):
            task = loop.create_task(fn(*args, **kwargs))
        else:
            future = self.run(fn, *args, callback=callback, cancel_token=cancel_token, **kwargs)

            async def _await_future():
                return await asyncio.wrap_future(future)

            task = loop.create_task(_await_future())
            callback = None

        if callback:
            task.add_done_callback(_make_done_callback(callback, task_label="Background async task"))
        return task

    def shutdown(self, wait: bool = True) -> None:
        """
        關閉 Qt 工作池，必要時等待既有任務完成

        Args:
            wait: 是否等待既有任務完成
        """
        if wait:
            self._pool.waitForDone()
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


# ── 共享 manager（輕量版，相容既有呼叫端）──────────────────────────

_shared_manager: BackgroundTaskManager | None = None


def get_shared_manager() -> BackgroundTaskManager:
    """
    取得全域共用的背景任務管理器（相容既有呼叫端）

    Returns:
        全域共用的 BackgroundTaskManager 實例
    """
    global _shared_manager
    if _shared_manager is None:
        _shared_manager = BackgroundTaskManager()
    return _shared_manager


def run_in_background(
    fn: Callable[..., Any], *args, callback: Callable[[Any], None] | None = None, **kwargs
) -> concurrent.futures.Future[Any] | None:
    """
    使用共享 BackgroundTaskManager 的便利函式

    若無法使用共享 manager，會同步完成一個 Future 以保持錯誤可觀測

    Args:
        fn: 要執行的函式
        callback: 任務完成後的回呼，會在背景執行緒被呼叫
        *args: 傳入函式的位置參數
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
        except Exception as run_exc:
            future.set_exception(run_exc)
            logger.exception("Background fallback raised an exception")
            if callback:
                callback(None)
        else:
            future.set_result(result)
            if callback:
                callback(result)
        return future


# ── 共享工作池（原 worker_pool.py，合併至此）──────────────────────

_worker_pool_lock = QtCore.QMutex()
_shared_worker_pool: BackgroundTaskManager | None = None


def resolve_worker_count(requested_workers: int | None = None) -> int:
    """
    解析實際可用的 worker 數量

    Args:
        requested_workers: 呼叫端要求的 worker 數；未提供時使用預設值

    Returns:
        介於 1 與 CPU 核心數 / 預設值之間的 worker 數
    """
    cpu_count = max(1, os.cpu_count() or DEFAULT_WORKER_COUNT)
    desired = DEFAULT_WORKER_COUNT if requested_workers is None else int(requested_workers)
    return max(1, min(desired, cpu_count))


def get_shared_worker_pool() -> BackgroundTaskManager:
    """
    取得全專案共享的受限工作池（執行緒安全，CPU 感知）

    Returns:
        共用的 BackgroundTaskManager 實例
    """
    global _shared_worker_pool
    if _shared_worker_pool is None:
        with QtCore.QMutexLocker(_worker_pool_lock):
            if _shared_worker_pool is None:
                _shared_worker_pool = BackgroundTaskManager(max_workers=resolve_worker_count())
    return _shared_worker_pool
