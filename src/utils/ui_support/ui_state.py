"""
UI 狀態綁定工具

統一使用 QtRuntime 的 ValueState；typed state 只保留預設值與輸入正規化
"""

from src.utils import ValueState


class TextState(ValueState):
    """字串狀態變數"""

    def __init__(self, value: str = "") -> None:
        super().__init__(value)


class BoolState(ValueState):
    """布林狀態變數"""

    def __init__(self, value: bool = False) -> None:
        super().__init__(bool(value))


class FloatState(ValueState):
    """浮點數狀態變數"""

    def __init__(self, value: float = 0.0) -> None:
        super().__init__(float(value))


__all__ = [
    "BoolState",
    "FloatState",
    "TextState",
]
