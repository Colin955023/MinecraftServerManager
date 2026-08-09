"""執行緒與 UI 任務調度工具"""

from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from typing import Any

from .. import get_logger, run_in_background
from ..ui_support.qt_runtime import QtCore, invoke_later, is_qobject_alive, run_on_ui_thread

logger = get_logger().bind(component="TaskUtils")


class TaskUtils:
    """
    集中處理 UI 執行緒切換、背景工作與 UI 佇列泵送"""

    @staticmethod
    def call_on_ui(parent: Any, func: Callable[[], Any], timeout: float | None = None) -> Any:
        """
        在 UI 執行緒執行函數，若目前不在主執行緒則排程並等待結果

        Args:
            parent: 可用來排程 UI 工作的元件
            func: 要在 UI 執行緒執行的函式
            timeout: 等待執行完成的秒數，None 表示一直等待

        Returns:
            函式執行結果
        """
        if parent is not None and not isinstance(parent, QtCore.QObject):
            raise TypeError("TaskUtils.call_on_ui 只支援原生 Qt QObject parent")
        if isinstance(parent, QtCore.QObject) and not is_qobject_alive(parent):
            raise RuntimeError("Qt parent 已被銷毀，無法排程 UI 任務")
        return run_on_ui_thread(func, timeout=timeout)

    @staticmethod
    def run_async(target: Callable[..., Any], *args: Any, **kwargs: Any) -> concurrent.futures.Future | None:
        """
        簡單的非同步執行封裝

        Args:
            target: 要執行的函式
            *args: 傳給 target 的位置參數
            **kwargs: 傳給 target 的關鍵字參數

        Returns:
            由背景執行器回傳的 Future；回退到 daemon thread 時回傳 None
        """
        try:
            return run_in_background(target, *args, **kwargs)
        except Exception as exc:
            future: concurrent.futures.Future[Any] = concurrent.futures.Future()
            future.set_exception(exc)
            logger.exception(f"背景任務提交失敗: {exc}")
            return future

    @staticmethod
    def run_background_task(
        task_func: Callable,
        *,
        widget=None,
        on_error: Callable[[], None] | None = None,
        error_log_prefix: str = "",
        component: str = "TaskUtils",
    ) -> None:
        """
        透過 Qt 背景工作池執行任務，失敗時可選擇回派 UI callback

        Args:
            task_func: 要執行的任務函式
            widget: 可選的 UI 元件
            on_error: 發生錯誤時要回派的 callback
            error_log_prefix: 錯誤日誌前綴
            component: 日誌 component 名稱
        """

        def _dispatch(cb: Callable[[], None] | None) -> None:
            if cb is None:
                return
            if widget is not None:
                try:
                    if isinstance(widget, QtCore.QObject):
                        invoke_later(0, cb, parent=widget)
                    return
                except Exception as exc:
                    logger.debug(f"Qt UI callback 排程失敗: {exc}")
            try:
                run_on_ui_thread(cb, timeout=5.0)
            except Exception as exc:
                logger.debug(f"Qt UI callback 回派失敗: {exc}")

        def _wrapper() -> None:
            try:
                task_func()
            except Exception as exc:
                prefix = error_log_prefix + ": " if error_log_prefix else ""
                get_logger().bind(component=component).exception(f"{prefix}{exc}")
                _dispatch(on_error)

        TaskUtils.run_async(_wrapper)


__all__ = ["TaskUtils"]
