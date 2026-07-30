"""模組操作的共用輔助函式。"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


def notify_mod_list_changed(on_mod_list_changed: Callable | None) -> None:
    """
    在主執行緒中觸發模組列表變更通知。

    Args:
        on_mod_list_changed: 變更通知的回呼函式。
    """

    if on_mod_list_changed and threading.current_thread() is threading.main_thread():
        on_mod_list_changed()


def is_operation_cancelled(cancel_check: Callable[[], bool] | None, logger: Any) -> bool:
    """
    安全地檢查目前作業是否被取消。

    Args:
        cancel_check: 檢查是否取消的回呼函式。
        logger: 用於記錄錯誤的日誌物件。

    Returns:
        若作業應取消則回傳 True，否則回傳 False。
    """

    if cancel_check is None:
        return False
    try:
        return bool(cancel_check())
    except Exception as exc:
        logger.exception(f"取消檢查回呼失敗: {exc}")
        return False
