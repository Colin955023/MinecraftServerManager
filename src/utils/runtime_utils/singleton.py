"""輕量級單例（Singleton）基底類別。"""

from __future__ import annotations

import threading
from typing import ClassVar


class SingletonMeta(type):
    """執行緒安全的 Singleton metaclass。"""

    _instances: ClassVar[dict[type, object]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __call__(cls, *args: object, **kwargs: object) -> object:
        # 快速路徑：實例多半已存在，先不搶鎖檢查一次，避免每次呼叫都有鎖競爭。
        instance = cls._instances.get(cls)
        if instance is None:
            with cls._lock:
                instance = cls._instances.get(cls)
                if instance is None:
                    instance = super().__call__(*args, **kwargs)
                    cls._instances[cls] = instance
        return instance


class Singleton(metaclass=SingletonMeta):
    """繼承此類別即可獲得執行緒安全的單例行為，子類別無需額外處理。"""
