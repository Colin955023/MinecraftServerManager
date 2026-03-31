"""
核心模組套件
提供 Minecraft 伺服器管理器的核心功能模組，包含伺服器管理、版本控制、載入器管理等
"""

from __future__ import annotations
from .. import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "ServerManager": (".server_manager", "ServerManager"),
    "ServerConfig": (".server_manager", "ServerConfig"),
    "LoaderManager": (".loader_manager", "LoaderManager"),
    "MinecraftVersionManager": (".version_manager", "MinecraftVersionManager"),
    "ModManager": (".mod_manager", "ModManager"),
    "ModStatus": (".mod_manager", "ModStatus"),
    "ModPlatform": (".mod_manager", "ModPlatform"),
    "AppException": (".exceptions", "AppException"),
    "ConfigurationError": (".exceptions", "ConfigurationError"),
    "NetworkOperationError": (".exceptions", "NetworkOperationError"),
    "MetadataResolutionError": (".exceptions", "MetadataResolutionError"),
    "ServerOperationError": (".exceptions", "ServerOperationError"),
}
__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
