"""
輕量級單例基底類別
提供 __new__ 單例行為與 _initialized 預設欄位，供多個類別共用以避免重複程式碼
"""

from __future__ import annotations

from typing import ClassVar, cast


class Singleton:
    _instance: ClassVar[object | None] = None
    _initialized: ClassVar[bool] = False

    def __new__(cls, *_args: object, **_kwargs: object) -> Singleton:
        if getattr(cls, "_instance", None) is None:
            cls._instance = super().__new__(cls)
        return cast("Singleton", cls._instance)
