"""
UI 狀態綁定與搜尋篩選工具
合併自 state_utils.py 與 search_utils.py
"""

from collections.abc import Callable
from typing import Any

from src.utils import ValueState


class Variable(ValueState):
    """
    通用變數狀態綁定
    支援當值改變時觸發註冊的回呼函式
    """

    def __init__(self, value: Any = None) -> None:
        super().__init__(value)
        self._callbacks: list[Callable[..., Any]] = []

    def set(self, value: Any) -> None:
        """
        設定目前值或顯示狀態

        Args:
            value: 要設定的新值
        """
        if self._value == value:
            return
        super().set(value)
        for callback in list(self._callbacks):
            callback()

    def trace_add(self, _mode: str, callback: Callable[..., Any]) -> str:
        """
        將回呼函式新增至監聽清單中

        Args:
            _mode: 監聽模式 (未使用)
            callback: 要註冊的回呼函式，當值改變時會被呼叫

        Returns:
            該回呼函式的唯一識別碼（ID）
        """
        self._callbacks.append(callback)
        return str(id(callback))

    def trace(self, mode: str, callback: Callable[..., Any]) -> str:
        """
        註冊變數變更監聽器

        Args:
            mode: 監聽模式
            callback: 要註冊的回呼函式，當值改變時會被呼叫

        Returns:
            該回呼函式的唯一識別碼（ID）
        """
        return self.trace_add(mode, callback)


class TextState(Variable):
    """字串狀態變數"""

    def __init__(self, value: str = "") -> None:
        super().__init__(value)


class BoolState(Variable):
    """布林狀態變數"""

    def __init__(self, value: bool = False) -> None:
        super().__init__(bool(value))


class FloatState(Variable):
    """浮點數狀態變數"""

    def __init__(self, value: float = 0.0) -> None:
        super().__init__(float(value))


__all__ = [
    "BoolState",
    "FloatState",
    "TextState",
    "Variable",
]
