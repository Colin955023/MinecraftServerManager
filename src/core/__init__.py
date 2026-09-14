"""
src/core/__init__.py
核心模組套件
提供 Minecraft 伺服器管理器的核心功能模組，包含伺服器管理、版本控制、載入器管理等
"""

from __future__ import annotations

from src import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "CreateServerJourney": (".server.server_creation", "CreateServerJourney"),
    "LoaderManager": (".loader.loader_manager", "LoaderManager"),
    "ModManager": (".mods.mod_manager", "ModManager"),
    "ModPlanning": (".mods.dependency_planner_facade", "ModPlanning"),
    "deserialize_online_dependency_install_plan": (
        ".mods.dependency_plan_serializer",
        "deserialize_online_dependency_install_plan",
    ),
    "serialize_online_dependency_install_plan": (
        ".mods.dependency_plan_serializer",
        "serialize_online_dependency_install_plan",
    ),
    "validate_online_dependency_install_plan_payload": (
        ".mods.dependency_plan_serializer",
        "validate_online_dependency_install_plan_payload",
    ),
    "LoaderManagerRulesAdapter": (".mods.mod_planning_ports", "LoaderManagerRulesAdapter"),
    "ModrinthHttpAdapter": (".mods.modrinth_http", "ModrinthHttpAdapter"),
    "ServerBackupManager": (".server.server_backup", "ServerBackupManager"),
    "ServerCRUD": (".server.server_crud", "ServerCRUD"),
    "ServerConfigChangeSet": (".server.server_crud", "ServerConfigChangeSet"),
    "ServerImportService": (".server.server_import", "ServerImportService"),
    "ServerInspector": (".server.server_inspector", "ServerInspector"),
    "ServerPropertiesStore": (".server.server_properties", "ServerPropertiesStore"),
    "ServerPropertiesMigrationService": (".server.server_properties_migration", "ServerPropertiesMigrationService"),
    "ServerRuntime": (".server.server_runtime", "ServerRuntime"),
}
__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
