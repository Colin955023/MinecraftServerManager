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
    "ArchiveSecurityError": (".exceptions", "ArchiveSecurityError"),
    "JavaInstallError": (".exceptions", "JavaInstallError"),
    "LoaderManager": (".loader_manager", "LoaderManager"),
    "ModManager": (".mods.mod_manager", "ModManager"),
    "ServerCRUD": (".server.server_crud", "ServerCRUD"),
    "ServerStartup": (".server.server_startup", "ServerStartup"),
    "ServerBackupManager": (".server.server_backup", "ServerBackupManager"),
    "ServerInstance": (".server.server_instance", "ServerInstance"),
    "LocalModScanner": (".mods.local_mod_scanner", "LocalModScanner"),
}
__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
