"""背景任務工具與取消標記

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
    "run_async_in_background",
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
        """提交背景任務，完成後若提供 callback 會在背景執行緒呼叫。

        Args:
            fn: 要執行的函式。
            *args: 傳入函式的位置參數。
            callback: 任務完成後的回呼。
            cancel_token: 協作式取消標記。
            **kwargs: 傳入函式的關鍵字參數。

        Returns:
            提交到執行器後的 Future。
        """
        if cancel_token is not None and "cancel_token" not in kwargs:
            kwargs["cancel_token"] = cancel_token
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        runnable = _QtRunnable(future, functools.partial(fn, *args, **kwargs))
        self._pool.start(runnable)
        if callback:

            def _on_done(f: concurrent.futures.Future):
                try:
                    res = f.result()
                except Exception as e:
                    logger.exception("Background task failed: %s", e)
                    try:
                        callback(None)
                    except Exception:
                        logger.exception("Background task callback failed while handling exception")
                    return
                try:
                    callback(res)
                except Exception:
                    logger.exception("Background task callback raised an exception")

            future.add_done_callback(_on_done)
        return future

    async def run_async(
        self,
        fn: Callable[..., Any],
        *args,
        callback: Callable[[Any], None] | None = None,
        cancel_token: CancellationToken | None = None,
        **kwargs,
    ) -> asyncio.Task:
        """以協程介面執行任務。

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
            callback = None

        if callback:

            def _on_done(task_fut: asyncio.Future):
                try:
                    res = task_fut.result()
                except Exception as e:
                    logger.exception("Background async task failed: %s", e)
                    try:
                        callback(None)
                    except Exception:
                        logger.exception("Background async task callback failed while handling exception")
                    return
                try:
                    callback(res)
                except Exception:
                    logger.exception("Background async task callback raised an exception")

            task.add_done_callback(_on_done)
        return task

    def shutdown(self, wait: bool = True) -> None:
        """關閉 Qt 工作池，必要時等待既有任務完成。

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
    """取得全域共用的背景任務管理器。

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
    """使用共享 BackgroundTaskManager 的便利函式。

    若無法使用共享 manager（例：初始化失敗或其他稀有例外），
    會同步完成一個 Future 以保持錯誤可觀測。
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


def run_async_in_background(
    fn: Callable[..., Any], *args, callback: Callable[[Any], None] | None = None, **kwargs
) -> concurrent.futures.Future[Any] | asyncio.Task[Any]:
    """若在 asyncio loop 中，使用共享 manager 的 run_async；否則回傳 concurrent.futures.Future。

    注意：呼叫者在 asyncio 環境中應直接呼叫 `await get_shared_manager().run_async(...)`。
    此函式提供在不確定執行環境時的便利層級。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return get_shared_manager().run(fn, *args, callback=callback, **kwargs)
    # 已有 running loop，建立 task 並回傳 asyncio.Task
    return asyncio.ensure_future(get_shared_manager().run_async(fn, *args, callback=callback, **kwargs))
