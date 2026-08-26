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
    "LocalModScanner": (".mods.local_mod_scanner", "LocalModScanner"),
    "MODRINTH_BATCH_HASH_LOOKUP_SIZE": (
        ".mods.mod_search_constants",
        "MODRINTH_BATCH_HASH_LOOKUP_SIZE",
    ),
    "MODRINTH_BATCH_PROJECT_LOOKUP_SIZE": (
        ".mods.mod_search_constants",
        "MODRINTH_BATCH_PROJECT_LOOKUP_SIZE",
    ),
    "MODRINTH_PROJECT_BATCH_TIMEOUT_SECONDS": (
        ".mods.mod_search_constants",
        "MODRINTH_PROJECT_BATCH_TIMEOUT_SECONDS",
    ),
    "MODRINTH_PROJECT_BATCH_URL": (".mods.mod_search_constants", "MODRINTH_PROJECT_BATCH_URL"),
    "MODRINTH_PROJECT_DETAIL_TIMEOUT_SECONDS": (
        ".mods.mod_search_constants",
        "MODRINTH_PROJECT_DETAIL_TIMEOUT_SECONDS",
    ),
    "MODRINTH_PROJECT_URL": (".mods.mod_search_constants", "MODRINTH_PROJECT_URL"),
    "MODRINTH_SEARCH_TIMEOUT_SECONDS": (
        ".mods.mod_search_constants",
        "MODRINTH_SEARCH_TIMEOUT_SECONDS",
    ),
    "MODRINTH_SEARCH_URL": (".mods.mod_search_constants", "MODRINTH_SEARCH_URL"),
    "MODRINTH_VERSION_DETAIL_TIMEOUT_SECONDS": (
        ".mods.mod_search_constants",
        "MODRINTH_VERSION_DETAIL_TIMEOUT_SECONDS",
    ),
    "MODRINTH_VERSION_DETAIL_URL_TEMPLATE": (
        ".mods.mod_search_constants",
        "MODRINTH_VERSION_DETAIL_URL_TEMPLATE",
    ),
    "MODRINTH_VERSION_FILES_TIMEOUT_SECONDS": (
        ".mods.mod_search_constants",
        "MODRINTH_VERSION_FILES_TIMEOUT_SECONDS",
    ),
    "MODRINTH_VERSION_FILES_UPDATE_URL": (
        ".mods.mod_search_constants",
        "MODRINTH_VERSION_FILES_UPDATE_URL",
    ),
    "MODRINTH_VERSION_FILES_URL": (
        ".mods.mod_search_constants",
        "MODRINTH_VERSION_FILES_URL",
    ),
    "MODRINTH_VERSION_TIMEOUT_SECONDS": (
        ".mods.mod_search_constants",
        "MODRINTH_VERSION_TIMEOUT_SECONDS",
    ),
    "MODRINTH_VERSION_URL_TEMPLATE": (
        ".mods.mod_search_constants",
        "MODRINTH_VERSION_URL_TEMPLATE",
    ),
    "ModFileInstaller": (".mods.mod_file_installer", "ModFileInstaller"),
    "ModIndexProviderIdentityStore": (".mods.provider_identity", "ModIndexProviderIdentityStore"),
    "ModManager": (".mods.mod_manager", "ModManager"),
    "ModPlanning": (".mods.dependency_planner_facade", "ModPlanning"),
    "ModPlanningProviderPort": (".mods.mod_planning_ports", "ModPlanningProviderPort"),
    "LoaderRulesPort": (".mods.mod_planning_ports", "LoaderRulesPort"),
    "ModrinthPlanningAdapter": (".mods.modrinth_planning_adapter", "ModrinthPlanningAdapter"),
    "LoaderManagerRulesAdapter": (".mods.modrinth_planning_adapter", "LoaderManagerRulesAdapter"),
    "ModrinthProviderAdapter": (".mods.modrinth_provider_adapter", "ModrinthProviderAdapter"),
    "ProviderCatalogPort": (".mods.provider_identity", "ProviderCatalogPort"),
    "ProviderIdentityService": (".mods.provider_identity", "ProviderIdentityService"),
    "ServerBackupManager": (".server.server_backup", "ServerBackupManager"),
    "ServerCRUD": (".server.server_crud", "ServerCRUD"),
    "ServerImportService": (".server.server_import", "ServerImportService"),
    "ServerInspector": (".server.server_inspector", "ServerInspector"),
    "ServerPropertiesStore": (".server.server_properties", "ServerPropertiesStore"),
    "ServerRuntime": (".server.server_runtime", "ServerRuntime"),
    "SUPPORTED_SORT_OPTIONS": (".mods.mod_search_constants", "SUPPORTED_SORT_OPTIONS"),
    "analyze_local_mod_file_compatibility": (
        ".mods.compatibility_analyzer",
        "analyze_local_mod_file_compatibility",
    ),
    "fetch_modrinth_project_name": (".mods.modrinth_service", "fetch_modrinth_project_name"),
    "get_mod_version_details": (".mods.modrinth_service", "get_mod_version_details"),
    "get_mod_versions": (".mods.modrinth_service", "get_mod_versions"),
    "get_modrinth_current_versions_by_hashes": (
        ".mods.modrinth_service",
        "get_modrinth_current_versions_by_hashes",
    ),
    "get_modrinth_latest_versions_by_hashes": (
        ".mods.modrinth_service",
        "get_modrinth_latest_versions_by_hashes",
    ),
    "get_modrinth_project_info": (".mods.modrinth_service", "get_modrinth_project_info"),
    "get_recommended_mod_version": (".mods.modrinth_service", "get_recommended_mod_version"),
    "mod_search_logger": (".mods.mod_search_constants", "logger"),
    "resolve_modrinth_project_names": (
        ".mods.modrinth_service",
        "resolve_modrinth_project_names",
    ),
    "search_mods_online": (".mods.modrinth_service", "search_mods_online"),
}
__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
