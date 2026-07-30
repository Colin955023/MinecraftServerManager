"""
src/core/__init__.py
核心模組套件
提供 Minecraft 伺服器管理器的核心功能模組，包含伺服器管理、版本控制、載入器管理等
"""

from __future__ import annotations

from .. import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "AppException": (".exceptions", "AppException"),
    "ConfigurationError": (".exceptions", "ConfigurationError"),
    "LoaderManager": (".loader_manager", "LoaderManager"),
    "ModManager": (".mod_manager", "ModManager"),
    "ModPlatform": (".mod_manager", "ModPlatform"),
    "ServerManager": (".server_manager", "ServerManager"),
    "LocalModScanner": (".local_mod_scanner", "LocalModScanner"),
    "MinecraftVersionManager": (".version_manager", "MinecraftVersionManager"),
}
__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
