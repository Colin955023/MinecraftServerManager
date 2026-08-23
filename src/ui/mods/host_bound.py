"""將 ops 實例的屬性存取委派到 ModManagementFrame host"""

from __future__ import annotations

from typing import Any


class HostBound:
    """ops 類別基底：讀寫都落到 host，方法仍綁在 ops 上"""

    __slots__ = ("_host",)

    def __init__(self, host: Any) -> None:
        object.__setattr__(self, "_host", host)

    def __getattribute__(self, name: str) -> Any:
        if name == "_host" or (name.startswith("__") and name.endswith("__")):
            return object.__getattribute__(self, name)
        host = object.__getattribute__(self, "_host")
        if hasattr(host, "__dict__") and name in host.__dict__:
            return host.__dict__[name]
        return object.__getattribute__(self, name)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_host"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_host":
            object.__setattr__(self, name, value)
            return
        setattr(object.__getattribute__(self, "_host"), name, value)


__all__ = ["HostBound"]
