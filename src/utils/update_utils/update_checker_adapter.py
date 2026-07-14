"""Qt 更新流程互動 adapter。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from .. import TaskUtils, UIUtils, UpdateCheckerInteraction

_ResultT = TypeVar("_ResultT")


class QtUpdateCheckerInteraction(UpdateCheckerInteraction):
    """將更新流程需要的互動操作轉接到目前的 Qt UI 工具。"""

    def run_async(self, work: Callable[[], None]) -> None:
        """在既有 Qt 背景任務工具中執行更新工作。"""
        TaskUtils.run_async(work)

    def call_on_ui(self, parent: Any, callback: Callable[[], _ResultT]) -> _ResultT:
        """
        在 Qt UI 執行緒執行 callback。

        Args:
            parent: 用於排程的 UI parent。
            callback: 要執行的函式。

        Returns:
            callback 的回傳值。
        """
        return TaskUtils.call_on_ui(parent, callback)

    def schedule_debounce(
        self, widget: Any, job_attr: str, delay_ms: int, callback: Callable[[], Any], *, owner: Any | None = None
    ) -> Any:
        """
        使用既有 Qt debounce helper 安排延遲工作。

        Args:
            widget: 排程所在 widget。
            job_attr: 儲存 debounce job id 的屬性名稱。
            delay_ms: 延遲毫秒數。
            callback: 到期後執行的函式。
            owner: 可選的 job holder。

        Returns:
            建立的 job id，或底層 helper 的回傳值。
        """
        return UIUtils.schedule_debounce(widget, job_attr, delay_ms, callback, owner=owner)

    def ask_yes_no_cancel(self, title: str, message: str, **kwargs: Any) -> bool | None:
        """
        顯示確認對話框。

        Args:
            title: 對話框標題。
            message: 對話框訊息。
            **kwargs: 轉交給 UIUtils 的選項。

        Returns:
            使用者選擇；取消或無法判斷時回傳 None。
        """
        return UIUtils.ask_yes_no_cancel(title, message, **kwargs)

    def show_info(self, title: str, message: str, **kwargs: Any) -> None:
        """
        顯示資訊對話框。

        Args:
            title: 對話框標題。
            message: 對話框訊息。
            **kwargs: 轉交給 UIUtils 的選項。
        """
        UIUtils.show_info(title, message, **kwargs)

    def show_error(self, title: str, message: str, **kwargs: Any) -> None:
        """
        顯示錯誤對話框。

        Args:
            title: 對話框標題。
            message: 對話框訊息。
            **kwargs: 轉交給 UIUtils 的選項。
        """
        UIUtils.show_error(title, message, **kwargs)

    def open_external(self, target: str) -> None:
        """
        透過既有 UI 工具開啟外部連結或路徑。

        Args:
            target: 要開啟的 URL 或檔案路徑。
        """
        UIUtils.open_external(target)
