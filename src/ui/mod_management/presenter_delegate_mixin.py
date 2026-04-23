"""
Presenter 委派共用 Mixin。
"""

from typing import Any


class PresenterDelegateMixin:
    """提供 Presenter 委派共用邏輯，讓 Presenter 可以專注於事件處理與狀態管理。"""

    def __init__(self, frame: Any):
        object.__setattr__(self, "frame", frame)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "frame"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "frame":
            object.__setattr__(self, name, value)
            return
        setattr(object.__getattribute__(self, "frame"), name, value)
