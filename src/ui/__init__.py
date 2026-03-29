"""使用者介面模組套件
提供 Minecraft 伺服器管理器的所有使用者介面元件和視窗
"""

from __future__ import annotations
from .. import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "MinecraftServerManager": (".main_window", "MinecraftServerManager"),
    "CreateServerFrame": (".create_server_frame", "CreateServerFrame"),
    "ManageServerFrame": (".manage_server_frame", "ManageServerFrame"),
    "ModManagementFrame": (".mod_management", "ModManagementFrame"),
    "ServerMonitorWindow": (".server_monitor_window", "ServerMonitorWindow"),
    "ServerPropertiesDialog": (".server_properties_dialog", "ServerPropertiesDialog"),
    "WindowPreferencesDialog": (".window_preferences_dialog", "WindowPreferencesDialog"),
    "CustomDropdown": (".custom_dropdown", "CustomDropdown"),
    "VirtualList": (".virtual_list", "VirtualList"),
    "search_mods_online": (".mod_search_service", "search_mods_online"),
    "get_mod_versions": (".mod_search_service", "get_mod_versions"),
    "get_recommended_mod_version": (".mod_search_service", "get_recommended_mod_version"),
    "analyze_mod_version_compatibility": (".mod_search_service", "analyze_mod_version_compatibility"),
    "analyze_local_mod_file_compatibility": (".mod_search_service", "analyze_local_mod_file_compatibility"),
    "build_required_dependency_install_plan": (".mod_search_service", "build_required_dependency_install_plan"),
    "build_local_mod_update_plan": (".mod_search_service", "build_local_mod_update_plan"),
    "serialize_online_dependency_install_plan": (".mod_search_service", "serialize_online_dependency_install_plan"),
    "deserialize_online_dependency_install_plan": (".mod_search_service", "deserialize_online_dependency_install_plan"),
    "validate_online_dependency_install_plan_payload": (
        ".mod_search_service",
        "validate_online_dependency_install_plan_payload",
    ),
    "migrate_online_dependency_install_plan_payload": (
        ".mod_search_service",
        "migrate_online_dependency_install_plan_payload",
    ),
    "normalize_mod_search_query": (".mod_search_service", "normalize_mod_search_query"),
    "resolve_modrinth_project_names": (".mod_search_service", "resolve_modrinth_project_names"),
    "OnlineModInfo": (".mod_search_service", "OnlineModInfo"),
    "OnlineModVersion": (".mod_search_service", "OnlineModVersion"),
    "OnlineModCompatibilityReport": (".mod_search_service", "OnlineModCompatibilityReport"),
    "OnlineDependencyInstallItem": (".mod_search_service", "OnlineDependencyInstallItem"),
    "OnlineDependencyInstallPlan": (".mod_search_service", "OnlineDependencyInstallPlan"),
    "LocalModUpdateCandidate": (".mod_search_service", "LocalModUpdateCandidate"),
    "LocalModUpdatePlan": (".mod_search_service", "LocalModUpdatePlan"),
    "enhance_local_mod": (".mod_search_service", "enhance_local_mod"),
}
__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
