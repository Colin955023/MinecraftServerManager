"""Tk/CustomTkinter 更新流程互動 adapter。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from ..utils import UIUtils
from ..utils.update_utils.update_checker import UpdateCheckerInteraction
from .task_utils import TaskUtils

_ResultT = TypeVar("_ResultT")


class TkUpdateCheckerInteraction(UpdateCheckerInteraction):
    """將更新流程需要的互動操作轉接到目前的 Tk UI 工具。"""

    def run_async(self, work: Callable[[], None]) -> None:
        """在既有 Tk 背景任務工具中執行更新工作。"""
        TaskUtils.run_async(work)

    def call_on_ui(self, parent: Any, callback: Callable[[], _ResultT]) -> _ResultT:
        """在 Tk UI 執行緒執行 callback。"""
        return TaskUtils.call_on_ui(parent, callback)

    def schedule_debounce(
        self, widget: Any, job_attr: str, delay_ms: int, callback: Callable[[], Any], *, owner: Any | None = None
    ) -> Any:
        """使用既有 Tk debounce helper 安排延遲工作。"""
        return UIUtils.schedule_debounce(widget, job_attr, delay_ms, callback, owner=owner)

    def ask_yes_no_cancel(self, title: str, message: str, **kwargs: Any) -> bool | None:
        """顯示確認對話框。"""
        return UIUtils.ask_yes_no_cancel(title, message, **kwargs)

    def show_info(self, title: str, message: str, **kwargs: Any) -> None:
        """顯示資訊對話框。"""
        UIUtils.show_info(title, message, **kwargs)

    def show_error(self, title: str, message: str, **kwargs: Any) -> None:
        """顯示錯誤對話框。"""
        UIUtils.show_error(title, message, **kwargs)

    def open_external(self, target: str) -> None:
        """透過既有 UI 工具開啟外部連結或路徑。"""
        UIUtils.open_external(target)
