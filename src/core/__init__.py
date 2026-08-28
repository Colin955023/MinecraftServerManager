"""
src/core/__init__.py
核心模組套件
提供 Minecraft 伺服器管理器的核心功能模組，包含伺服器管理、版本控制、載入器管理等
"""

from __future__ import annotations

from src import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "CreateServerJourney": (".server.server_creation", "CreateServerJourney"),
    "LoaderManager": (".loader_manager", "LoaderManager"),
    "LoaderManagerRulesAdapter": (".mods.modrinth_planning_adapter", "LoaderManagerRulesAdapter"),
    "ModManager": (".mods.mod_manager", "ModManager"),
    "ModPlanning": (".mods.dependency_planner_facade", "ModPlanning"),
    "ModrinthPlanningAdapter": (".mods.modrinth_planning_adapter", "ModrinthPlanningAdapter"),
    "ServerBackupManager": (".server.server_backup", "ServerBackupManager"),
    "ServerCRUD": (".server.server_crud", "ServerCRUD"),
    "ServerImportService": (".server.server_import", "ServerImportService"),
    "ServerInspector": (".server.server_inspector", "ServerInspector"),
    "ServerPropertiesStore": (".server.server_properties", "ServerPropertiesStore"),
    "ServerRuntime": (".server.server_runtime", "ServerRuntime"),
    "get_mod_versions": (".mods.modrinth_service", "get_mod_versions"),
    "get_modrinth_project_info": (".mods.modrinth_service", "get_modrinth_project_info"),
    "search_mods_online": (".mods.modrinth_service", "search_mods_online"),
}
__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
