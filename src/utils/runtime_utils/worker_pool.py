"""
受限背景工作池工具。

集中管理檔案 I/O、壓縮與雜湊等高成本工作的共享 Qt 工作池，避免各模組自行建立執行緒。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
from collections.abc import Callable
from typing import Any, TypeVar

from PySide6 import QtCore

from .background_task import BackgroundTaskManager

T = TypeVar("T")

DEFAULT_WORKER_COUNT = 4
_worker_pool_lock = QtCore.QMutex()
_shared_worker_pool: BackgroundTaskManager | None = None


def resolve_worker_count(requested_workers: int | None = None) -> int:
    """
    解析實際可用的 worker 數量。

    Args:
        requested_workers: 呼叫端要求的 worker 數；未提供時使用預設值。

    Returns:
        介於 1 與 CPU 核心數 / 預設值之間的 worker 數。
    """

    cpu_count = max(1, os.cpu_count() or DEFAULT_WORKER_COUNT)
    desired = DEFAULT_WORKER_COUNT if requested_workers is None else int(requested_workers)
    return max(1, min(desired, cpu_count))


def get_shared_worker_pool() -> BackgroundTaskManager:
    """
    取得全專案共享的受限工作池。

    Returns:
        共用的 `BackgroundTaskManager` 實例。
    """

    global _shared_worker_pool
    if _shared_worker_pool is None:
        with QtCore.QMutexLocker(_worker_pool_lock):
            if _shared_worker_pool is None:
                _shared_worker_pool = BackgroundTaskManager(max_workers=resolve_worker_count())
    return _shared_worker_pool


def submit_to_worker_pool[T](fn: Callable[..., T], *args: Any, **kwargs: Any) -> concurrent.futures.Future[T]:
    """
    將同步函式提交至共享工作池。

    Args:
        fn: 要執行的同步函式。
        *args: 位置參數。
        **kwargs: 關鍵字參數。

    Returns:
        已提交的 Future。
    """

    return get_shared_worker_pool().run(fn, *args, **kwargs)


async def run_blocking_io[T](fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    在共享工作池中執行阻塞 I/O 或高成本工作。

    Args:
        fn: 要執行的同步函式。
        *args: 位置參數。
        **kwargs: 關鍵字參數。

    Returns:
        函式執行結果。
    """

    return await asyncio.wrap_future(submit_to_worker_pool(fn, *args, **kwargs))


def shutdown_shared_worker_pool(*, wait: bool = True) -> None:
    """
    關閉共享工作池，主要供測試或應用程式結束流程使用。

    Args:
        wait: 是否等待既有任務完成。
    """

    global _shared_worker_pool
    with QtCore.QMutexLocker(_worker_pool_lock):
        pool = _shared_worker_pool
        _shared_worker_pool = None
    if pool is not None:
        pool.shutdown(wait=wait)


__all__ = [
    "DEFAULT_WORKER_COUNT",
    "get_shared_worker_pool",
    "resolve_worker_count",
    "run_blocking_io",
    "shutdown_shared_worker_pool",
    "submit_to_worker_pool",
]
