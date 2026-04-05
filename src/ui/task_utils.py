"""執行緒與 UI 任務調度工具。"""

from __future__ import annotations

import concurrent.futures
import contextlib
import queue
import threading
from collections.abc import Callable
from typing import Any

from ..utils import get_logger, run_in_background

logger = get_logger().bind(component="TaskUtils")


class TaskUtils:
    """集中處理 UI 執行緒切換、背景工作與 UI 佇列泵送。"""

    @staticmethod
    def call_on_ui(parent: Any, func: Callable[[], Any], timeout: float | None = None) -> Any:
        """在 UI 執行緒執行函數，若目前不在主執行緒則排程並等待結果。

        Args:
            parent: 可用來排程 after 的 UI 元件。
            func: 要在 UI 執行緒執行的函式。
            timeout: 等待執行完成的秒數，None 表示一直等待。

        Returns:
            函式執行結果。
        """
        try:
            if (
                parent is not None
                and hasattr(parent, "after")
                and hasattr(parent, "winfo_exists")
                and parent.winfo_exists()
            ):
                if threading.current_thread() is threading.main_thread():
                    return func()
                result: dict[str, Any] = {"value": None, "exc": None, "cancelled": False}
                done = threading.Event()
                after_id = None

                def _runner() -> None:
                    if result["cancelled"]:
                        done.set()
                        return
                    try:
                        result["value"] = func()
                    except Exception as exc:
                        result["exc"] = exc
                    finally:
                        done.set()

                try:
                    after_id = parent.after(0, _runner)
                    if timeout is None:
                        done.wait()
                    elif not done.wait(timeout=timeout):
                        result["cancelled"] = True
                        if after_id is not None:
                            with contextlib.suppress(Exception):
                                parent.after_cancel(after_id)
                        logger.warning(f"UI 任務等待逾時 ({timeout}秒)")
                        if not parent.winfo_exists():
                            logger.debug("視窗已關閉")
                        raise TimeoutError(f"UI 任務等待逾時 ({timeout}秒)")
                except TimeoutError:
                    raise
                except (AttributeError, RuntimeError) as exc:
                    result["cancelled"] = True
                    logger.debug(f"排程 UI 任務時發生暫時性例外 (可能視窗已關閉): {exc}")
                    return func()
                except Exception:
                    result["cancelled"] = True
                    logger.exception("排程 UI 任務時發生例外，回退到直接呼叫")
                    return func()
                if isinstance(result["exc"], Exception):
                    raise result["exc"]
                return result["value"]
        except TimeoutError:
            raise
        except Exception as exc:
            logger.debug(f"UI 排程執行失敗，回退至直接呼叫: {exc}")
        return func()

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
            if widget and widget.winfo_exists():
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
            widget: 提供 after / winfo_exists 的 UI 元件。
            task_queue: 要處理的任務佇列。
            interval_ms: 佇列空閒時的輪詢間隔。
            busy_interval_ms: 佇列繁忙時的輪詢間隔。
            max_tasks_per_tick: 每次輪詢最多執行的任務數。
            job_attr: 儲存 after job id 的屬性名稱。
        """

        def _alive() -> bool:
            try:
                return bool(widget) and widget.winfo_exists()
            except Exception:
                return False

        def _cancel_existing() -> None:
            try:
                job_id = getattr(widget, job_attr, None)
                if job_id:
                    widget.after_cancel(job_id)
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
                setattr(widget, job_attr, widget.after(next_delay, _tick))
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
        except Exception:
            threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True).start()
            return None

    @staticmethod
    def run_in_daemon_thread(
        task_func: Callable,
        *,
        ui_queue: queue.Queue | None = None,
        widget=None,
        on_error: Callable[[], None] | None = None,
        error_log_prefix: str = "",
        component: str = "TaskUtils",
    ) -> None:
        """在背景 daemon thread 執行任務，失敗時可選擇回派 UI callback。

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
                    widget.after(0, cb)
                    return
                except Exception as exc:
                    logger.debug(f"widget.after 失敗: {exc}")
            try:
                cb()
            except Exception as exc:
                logger.debug(f"直接執行 callback 失敗: {exc}")

        def _wrapper() -> None:
            try:
                task_func()
            except Exception as exc:
                prefix = error_log_prefix + ": " if error_log_prefix else ""
                get_logger().bind(component=component).exception(f"{prefix}{exc}")
                _dispatch(on_error)

        threading.Thread(target=_wrapper, daemon=True).start()


__all__ = ["TaskUtils"]
