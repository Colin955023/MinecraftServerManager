"""背景任務工具與取消標記

提供一個簡單的背景任務執行器（基於 ThreadPoolExecutor）與協作式取消（CancellationToken），
供 UI 與 core 層在不阻塞主執行緒下執行長時間任務。

規範：若任務支援取消，應接受名為 `cancel_token` 的參數並自行檢查其狀態。
"""

from __future__ import annotations
import asyncio
import concurrent.futures
import functools
import inspect
import threading
from collections.abc import Callable
from typing import Any
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
    """簡易的取消標記，用於協作式取消（cooperative cancellation）。"""

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
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)

    def run(
        self,
        fn: Callable[..., Any],
        *args,
        callback: Callable[[Any], None] | None = None,
        cancel_token: CancellationToken | None = None,
        **kwargs,
    ) -> concurrent.futures.Future:
        """提交背景任務，完成後若提供 callback 會在背景執行緒呼叫 callback(result)。

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
        future = self._executor.submit(fn, *args, **kwargs)
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
        """以 coroutine 介面執行任務。

        Args:
            fn: 要執行的函式或 coroutine function。
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
            call = functools.partial(fn, *args, **kwargs)

            async def _run_in_executor():
                return await loop.run_in_executor(self._executor, call)

            task = loop.create_task(_run_in_executor())

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
        """關閉 executor，必要時等待既有任務完成。

        Args:
            wait: 是否等待既有任務完成。
        """

        self._executor.shutdown(wait=wait)


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
    會回退到在新的 daemon thread 中直接啟動函式以保持向後相容性。
    """
    try:
        return get_shared_manager().run(fn, *args, callback=callback, **kwargs)
    except Exception as exc:
        logger.warning(f"Shared BackgroundTaskManager unavailable, falling back to daemon thread: {exc}")

        def _fallback_runner() -> None:
            try:
                res = fn(*args, **kwargs)
            except Exception:
                logger.exception("Background fallback thread raised an exception")
                if callback:
                    try:
                        callback(None)
                    except Exception:
                        logger.exception("Background fallback callback raised an exception while handling failure")
                return
            if callback:
                try:
                    callback(res)
                except Exception:
                    logger.exception("Background fallback callback raised an exception")

        thread = threading.Thread(target=_fallback_runner, daemon=True)
        thread.start()
        return None


def run_async_in_background(
    fn: Callable[..., Any], *args, callback: Callable[[Any], None] | None = None, **kwargs
) -> concurrent.futures.Future[Any] | asyncio.Task[Any]:
    """若在 asyncio loop 中，使用共享 manager 的 run_async；否則回傳 concurrent.futures.Future。

    注意：呼叫者在 asyncio context 中應直接呼叫 `await get_shared_manager().run_async(...)`。
    此函式提供在不確定執行環境時的便利層級。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return get_shared_manager().run(fn, *args, callback=callback, **kwargs)
    # 已有 running loop，建立 task 並回傳 asyncio.Task
    return asyncio.ensure_future(get_shared_manager().run_async(fn, *args, callback=callback, **kwargs))
