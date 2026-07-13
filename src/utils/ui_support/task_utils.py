"""執行緒與 UI 任務調度工具。"""

from __future__ import annotations

import concurrent.futures
import queue
from collections.abc import Callable
from typing import Any

from .. import get_logger, run_in_background
from ..ui_support.qt_runtime import QtCore, cancel_timer, invoke_later, is_qobject_alive, run_on_ui_thread

logger = get_logger().bind(component="TaskUtils")


class TaskUtils:
    """集中處理 UI 執行緒切換、背景工作與 UI 佇列泵送。"""

    @staticmethod
    def call_on_ui(parent: Any, func: Callable[[], Any], timeout: float | None = None) -> Any:
        """在 UI 執行緒執行函數，若目前不在主執行緒則排程並等待結果。

        Args:
            parent: 可用來排程 UI 工作的元件。
            func: 要在 UI 執行緒執行的函式。
            timeout: 等待執行完成的秒數，None 表示一直等待。

        Returns:
            函式執行結果。
        """
        if parent is not None and not isinstance(parent, QtCore.QObject):
            raise TypeError("TaskUtils.call_on_ui 只支援原生 Qt QObject parent")
        if isinstance(parent, QtCore.QObject) and not is_qobject_alive(parent):
            raise RuntimeError("Qt parent 已被銷毀，無法排程 UI 任務")
        return run_on_ui_thread(func, timeout=timeout)

    @staticmethod
    def safe_update_widget(widget, update_func: Callable, *args, **kwargs) -> None:
        """安全地更新 widget，先確認 widget 仍然存在。

        Args:
            widget: 要更新的元件。
            update_func: 實際執行更新的函式。
            *args: 傳給 update_func 的位置參數。
            **kwargs: 傳給 update_func 的關鍵字參數。
        """
        try:
            if widget is None:
                return
            if not isinstance(widget, QtCore.QObject):
                raise TypeError("TaskUtils.safe_update_widget 只支援原生 Qt QObject")
            if is_qobject_alive(widget):
                update_func(widget, *args, **kwargs)
        except Exception as exc:
            logger.exception(f"更新 widget 失敗: {exc}")

    @staticmethod
    def start_ui_queue_pump(
        widget,
        task_queue: queue.Queue,
        *,
        interval_ms: int = 100,
        busy_interval_ms: int = 25,
        max_tasks_per_tick: int = 100,
        job_attr: str = "_ui_queue_pump_job",
    ) -> None:
        """啟動 UI queue pump，將背景執行緒送入的任務分批送到主執行緒。

        Args:
            widget: 原生 Qt QObject UI 元件。
            task_queue: 要處理的任務佇列。
            interval_ms: 佇列空閒時的輪詢間隔。
            busy_interval_ms: 佇列繁忙時的輪詢間隔。
            max_tasks_per_tick: 每次輪詢最多執行的任務數。
            job_attr: 儲存 scheduled job id 的屬性名稱。
        """
        if not isinstance(widget, QtCore.QObject):
            raise TypeError("TaskUtils.start_ui_queue_pump 只支援原生 Qt QObject widget")

        def _alive() -> bool:
            return isinstance(widget, QtCore.QObject) and is_qobject_alive(widget)

        def _cancel_existing() -> None:
            try:
                job_id = getattr(widget, job_attr, None)
                if isinstance(job_id, QtCore.QTimer):
                    cancel_timer(job_id)
            except Exception as exc:
                logger.debug(f"取消舊的 UI queue pump job 失敗（視窗可能已關閉）: {exc}")
            try:
                setattr(widget, job_attr, None)
            except Exception as exc:
                logger.debug(f"重設 UI queue pump job 欄位失敗（視窗可能已關閉）: {exc}")

        def _tick() -> None:
            if not _alive():
                return
            processed = 0
            while processed < max_tasks_per_tick:
                try:
                    task = task_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    task()
                except Exception as exc:
                    logger.exception(f"UI 任務執行失敗: {exc}")
                processed += 1
            if not _alive():
                return
            try:
                has_backlog = not task_queue.empty()
            except Exception:
                has_backlog = False
            next_delay = busy_interval_ms if has_backlog else interval_ms
            try:
                setattr(widget, job_attr, invoke_later(next_delay, _tick, parent=widget))
            except Exception as exc:
                logger.exception(f"排程下一次 UI queue pump 失敗（視窗可能正在銷毀）: {exc}")

        if not _alive():
            return
        _cancel_existing()
        _tick()

    @staticmethod
    def run_async(target: Callable[..., Any], *args: Any, **kwargs: Any) -> concurrent.futures.Future | None:
        """簡單的非同步執行封裝。

        Args:
            target: 要執行的函式。
            *args: 傳給 target 的位置參數。
            **kwargs: 傳給 target 的關鍵字參數。

        Returns:
            由背景執行器回傳的 Future；回退到 daemon thread 時回傳 None。
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
        ui_queue: queue.Queue | None = None,
        widget=None,
        on_error: Callable[[], None] | None = None,
        error_log_prefix: str = "",
        component: str = "TaskUtils",
    ) -> None:
        """透過 Qt 背景工作池執行任務，失敗時可選擇回派 UI callback。

        Args:
            task_func: 要執行的任務函式。
            ui_queue: 可選的 UI 佇列。
            widget: 可選的 UI 元件。
            on_error: 發生錯誤時要回派的 callback。
            error_log_prefix: 錯誤日誌前綴。
            component: 日誌 component 名稱。
        """

        def _dispatch(cb: Callable[[], None] | None) -> None:
            if cb is None:
                return
            if ui_queue is not None:
                try:
                    ui_queue.put(cb)
                    return
                except Exception as exc:
                    logger.debug(f"ui_queue put 失敗: {exc}")
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
