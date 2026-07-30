"""
src/core/__init__.py
核心模組套件
提供 Minecraft 伺服器管理器的核心功能模組，包含伺服器管理、版本控制、載入器管理等
"""

from __future__ import annotations

from .. import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "resolve_platform_info_from_cache": (".mods.mod_provider_resolver", "resolve_platform_info_from_cache"),
    "ModProviderResolver": (".mods.mod_provider_resolver", "ModProviderResolver"),
    "ModFileInstaller": (".mods.mod_file_installer", "ModFileInstaller"),
    "LocalModScanner": (".mods.local_mod_scanner", "LocalModScanner"),
    "AppException": (".exceptions", "AppException"),
    "ConfigurationError": (".exceptions", "ConfigurationError"),
    "JavaManager": (".system.java_manager", "JavaManager"),
    "ILoaderAdapter": (".loaders.loader_adapter", "ILoaderAdapter"),
    "FabricAdapter": (".loaders.loader_fabric", "FabricAdapter"),
    "ForgeAdapter": (".loaders.loader_forge", "ForgeAdapter"),
    "NeoForgeAdapter": (".loaders.loader_neoforge", "NeoForgeAdapter"),
    "QuiltAdapter": (".loaders.loader_quilt", "QuiltAdapter"),
    "LoaderManager": (".loaders.loader_manager", "LoaderManager"),
    "ModManager": (".mods.mod_manager", "ModManager"),
    "ServerDetectionUtils": (".server.server_detection", "ServerDetectionUtils"),
    "ServerInstance": (".server.server_instance", "ServerInstance"),
    "ServerRepository": (".server.server_repository", "ServerRepository"),
    "ServerCRUD": (".server.server_crud", "ServerCRUD"),
    "ServerStartup": (".server.server_startup", "ServerStartup"),
    "ServerBackup": (".server.server_backup", "ServerBackup"),
    "ServerPropertiesHelper": (".server.server_properties", "ServerPropertiesHelper"),
    "ServerPropertiesValidator": (".server.server_properties", "ServerPropertiesValidator"),
    "JvmOptionPolicy": (".server.server_jvm", "JvmOptionPolicy"),
    "ServerCommands": (".server.server_runtime", "ServerCommands"),
    "ServerOperations": (".server.server_runtime", "ServerOperations"),
    "MinecraftVersionManager": (".system.version_manager", "MinecraftVersionManager"),
    "UpdateManager": (".system.update_manager", "UpdateManager"),
    "VersionReviewEngine": (".mods.mod_review_engine", "VersionReviewEngine"),
    "resolve_dependency_reference": (".mods.mod_dependency_resolver", "resolve_dependency_reference"),
    "LocalProviderEnsureResult": (".mods.mod_provider_metadata", "LocalProviderEnsureResult"),
    "ProviderMetadataRecord": (".mods.mod_provider_metadata", "ProviderMetadataRecord"),
    "apply_provider_metadata": (".mods.mod_provider_metadata", "apply_provider_metadata"),
    "ensure_local_mod_provider_record": (".mods.mod_provider_metadata", "ensure_local_mod_provider_record"),
    "resolve_modrinth_provider_record": (".mods.mod_provider_metadata", "resolve_modrinth_provider_record"),
    "derive_provider_lifecycle_state": (".mods.mod_provider_metadata", "derive_provider_lifecycle_state"),
    "PROVIDER_REVALIDATION_BATCH_MAX_PER_RUN": (
        ".mods.mod_provider_metadata",
        "PROVIDER_REVALIDATION_BATCH_MAX_PER_RUN",
    ),
    "cache_provider_metadata_record": (".mods.mod_provider_metadata", "cache_provider_metadata_record"),
    "is_cached_provider_metadata_fresh": (".mods.mod_provider_metadata", "is_cached_provider_metadata_fresh"),
    "is_provider_revalidation_retry_due": (".mods.mod_provider_metadata", "is_provider_revalidation_retry_due"),
    "PROVIDER_LIFECYCLE_STALE": (".mods.mod_provider_metadata", "PROVIDER_LIFECYCLE_STALE"),
    "fetch_modrinth_project_detail": (".mods.mod_provider_metadata", "fetch_modrinth_project_detail"),
    "register_provider_revalidation_success": (".mods.mod_provider_metadata", "register_provider_revalidation_success"),
    "PROVIDER_LIFECYCLE_INVALIDATED": (".mods.mod_provider_metadata", "PROVIDER_LIFECYCLE_INVALIDATED"),
    "should_attempt_provider_revalidation": (".mods.mod_provider_metadata", "should_attempt_provider_revalidation"),
    "PROVIDER_LIFECYCLE_RETRYING": (".mods.mod_provider_metadata", "PROVIDER_LIFECYCLE_RETRYING"),
    "PROVIDER_LIFECYCLE_FRESH": (".mods.mod_provider_metadata", "PROVIDER_LIFECYCLE_FRESH"),
    "PROVIDER_LIFECYCLE_MISSING": (".mods.mod_provider_metadata", "PROVIDER_LIFECYCLE_MISSING"),
    "MODRINTH_REQUEST_THROTTLE_SECONDS": (".online_mods.constants", "MODRINTH_REQUEST_THROTTLE_SECONDS"),
    "MODRINTH_RETRY_BACKOFF_BASE_SECONDS": (".online_mods.constants", "MODRINTH_RETRY_BACKOFF_BASE_SECONDS"),
    "MODRINTH_RETRY_BACKOFF_MAX_SECONDS": (".online_mods.constants", "MODRINTH_RETRY_BACKOFF_MAX_SECONDS"),
    "analyze_local_mod_file_compatibility": (
        ".online_mods.compatibility_analyzer",
        "analyze_local_mod_file_compatibility",
    ),
    "analyze_mod_version_compatibility": (".online_mods.compatibility_analyzer", "analyze_mod_version_compatibility"),
    "build_local_mod_update_plan": (".online_mods.dependency_planner", "build_local_mod_update_plan"),
    "build_required_dependency_install_plan": (
        ".online_mods.dependency_planner",
        "build_required_dependency_install_plan",
    ),
    "enhance_local_mod": (".online_mods.modrinth_service", "enhance_local_mod"),
    "get_mod_versions": (".online_mods.modrinth_service", "get_mod_versions"),
    "get_recommended_mod_version": (".online_mods.modrinth_service", "get_recommended_mod_version"),
    "resolve_modrinth_project_names": (".online_mods.modrinth_service", "resolve_modrinth_project_names"),
    "search_mods_online": (".online_mods.modrinth_service", "search_mods_online"),
    "get_mod_version_details": (".online_mods.modrinth_service", "get_mod_version_details"),
    "get_modrinth_current_versions_by_hashes": (
        ".online_mods.modrinth_service",
        "get_modrinth_current_versions_by_hashes",
    ),
    "get_modrinth_latest_versions_by_hashes": (
        ".online_mods.modrinth_service",
        "get_modrinth_latest_versions_by_hashes",
    ),
    "resolve_local_mod_project_info": (".online_mods.modrinth_service", "resolve_local_mod_project_info"),
}
__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
