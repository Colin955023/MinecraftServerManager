"""
輕量級單例基底類別
提供 __new__ 單例行為與 _initialized 預設欄位，供多個類別共用以避免重複程式碼
"""

from __future__ import annotations

import threading
from typing import ClassVar, cast


class Singleton:
    """提供 thread-safe 的單例基底。"""

    _instance: ClassVar[object | None] = None
    _initialized: ClassVar[bool] = False
    _instance_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        cls._instance = None
        cls._initialized = False
        cls._instance_lock = threading.Lock()
        original_init = cls.__init__

        def guarded_init(self, *args: object, **kwargs: object) -> None:
            with cls._instance_lock:
                if getattr(self, "_initialized", False):
                    return
                original_init(self, *args, **kwargs)
                self._initialized = True

        cls.__init__ = guarded_init  # type: ignore[assignment]

    def __new__(cls, *_args: object, **_kwargs: object) -> Singleton:
        with cls._instance_lock:
            if getattr(cls, "_instance", None) is None:
                cls._instance = super().__new__(cls)
        return cast("Singleton", cls._instance)
