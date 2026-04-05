"""
資料模型套件
提供 Minecraft 伺服器管理器的資料模型定義與相關類別。
"""

from __future__ import annotations

from .. import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "ModrinthVersionLookupResult": (".models", "ModrinthVersionLookupResult"),
    "LoaderVersion": (".models", "LoaderVersion"),
    "OnlineModVersion": (".models", "OnlineModVersion"),
    "ResolvedDependencyReference": (".models", "ResolvedDependencyReference"),
    "ServerConfig": (".models", "ServerConfig"),
}

__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
