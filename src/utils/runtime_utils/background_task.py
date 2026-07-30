"""
背景任務工具與取消標記

提供一個簡單的背景任務執行器（基於 QThreadPool）與協作式取消（CancellationToken），
供 UI 與 core 層在不阻塞主執行緒下執行長時間任務。

規範：若任務支援取消，應接受名為 `cancel_token` 的參數並自行檢查其狀態。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import inspect
from collections.abc import Callable
from typing import Any

from PySide6 import QtCore

from .. import get_logger

logger = get_logger().bind(component="BackgroundTask")

__all__ = [
    "BackgroundTaskManager",
    "CancellationToken",
    "get_shared_manager",
    "run_in_background",
]


class CancellationToken:
    """簡易的取消標記，用於協作式取消。"""

    def __init__(self):
        self._cancelled = False

    def cancel(self) -> None:
        """將取消標記設為已取消。"""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        """回傳目前是否已請求取消。"""
        return self._cancelled


def _make_done_callback(
    callback: Callable[[Any], None],
    task_label: str = "Background task",
) -> Callable[[concurrent.futures.Future | asyncio.Future], None]:
    """
    建立統一的任務完成回呼包裝器，消除 run() 與 run_async() 中的重複邏輯。

    Args:
        callback: 任務完成後要執行的使用者回呼。
        task_label: 用於日誌的任務名稱。

    Returns:
        可直接傳入 future.add_done_callback 的包裝函式。
    """

    def _on_done(future) -> None:
        try:
            result = future.result()
        except Exception as exc:
            logger.exception(f"{task_label} failed: %s", exc)
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
        self._max_workers = max(1, int(max_workers))
        self._pool = self._create_pool()

    def _create_pool(self) -> QtCore.QThreadPool:
        """建立新的 QThreadPool 實例。"""
        pool = QtCore.QThreadPool()
        pool.setMaxThreadCount(self._max_workers)
        return pool

    def _ensure_pool_alive(self) -> QtCore.QThreadPool:
        """確保 QThreadPool 仍然有效；若 C++ 物件已被銷毀則重新建立。"""
        try:
            _ = self._pool.maxThreadCount()
        except RuntimeError:
            self._pool = self._create_pool()
        return self._pool

    def run(
        self,
        fn: Callable[..., Any],
        *args,
        callback: Callable[[Any], None] | None = None,
        cancel_token: CancellationToken | None = None,
        **kwargs,
    ) -> concurrent.futures.Future:
        """
        提交背景任務到 QThreadPool 執行。

        Args:
            fn: 要執行的函式。
            *args: 傳入函式的位置參數。
            callback: 任務完成後的回呼，會在背景執行緒被呼叫。
            cancel_token: 協作式取消標記。
            **kwargs: 傳入函式的關鍵字參數。

        Returns:
            提交到執行器後的 Future。
        """
        if cancel_token is not None and "cancel_token" not in kwargs:
            kwargs["cancel_token"] = cancel_token
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        runnable = _QtRunnable(future, functools.partial(fn, *args, **kwargs))
        self._ensure_pool_alive().start(runnable)
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
        以協程介面執行任務。

        Args:
            fn: 要執行的函式或協程函式。
            *args: 傳入函式的位置參數。
            callback: 任務完成後的回呼。
            cancel_token: 協作式取消標記。
            **kwargs: 傳入函式的關鍵字參數。

        Returns:
            可由呼叫方 await 的 asyncio Task。
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
            callback = None  # 已由 run() 的 future.add_done_callback 負責

        if callback:
            task.add_done_callback(_make_done_callback(callback, task_label="Background async task"))
        return task

    def shutdown(self, wait: bool = True) -> None:
        """
        關閉 Qt 工作池，必要時等待既有任務完成。

        Args:
            wait: 是否等待既有任務完成。
        """
        if wait:
            self._pool.waitForDone()
        else:
            self._pool.clear()


class _QtRunnable(QtCore.QRunnable):
    """在 QThreadPool 中執行 Python callable，並同步完成 Future。"""

    def __init__(self, future: concurrent.futures.Future[Any], call: Callable[[], Any]) -> None:
        super().__init__()
        self.future = future
        self.call = call
        self.setAutoDelete(True)

    def run(self) -> None:
        """執行背景工作中保存的 callable。"""
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
    取得全域共用的背景任務管理器。

    Returns:
        全域共用的 BackgroundTaskManager 實例。
    """

    global _shared_manager
    if _shared_manager is None:
        _shared_manager = BackgroundTaskManager()
    return _shared_manager


def run_in_background(
    fn: Callable[..., Any], *args, callback: Callable[[Any], None] | None = None, **kwargs
) -> concurrent.futures.Future[Any] | None:
    """
    使用共享 BackgroundTaskManager 的便利函式。

    若無法使用共享 manager，會同步完成一個 Future 以保持錯誤可觀測。
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
