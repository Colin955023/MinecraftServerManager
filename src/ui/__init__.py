"""
src/ui/__init__.py
使用者介面模組套件
提供 Minecraft 伺服器管理器的所有使用者介面元件和視窗
"""

from __future__ import annotations

from .. import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "ModManagementRuntimeBase": (".mods.mod_management.online_mod_queue", "ModManagementRuntimeBase"),
    "AboutPreferencesFrame": (".about_preferences_frame", "AboutPreferencesFrame"),
    "CreateServerFrame": (".create_server_frame", "CreateServerFrame"),
    "ModalMSFluentWindow": (".modal_msfluent_window", "ModalMSFluentWindow"),
    "MainWindow": (".main_window", "MainWindow"),
    "run_application": (".main_window", "run_application"),
    "ManageServerFrame": (".manage_server_frame", "ManageServerFrame"),
    "RestoreBackupDialog": (".restore_backup_dialog", "RestoreBackupDialog"),
    "InstallReviewDialogBuilder": (".mods.mod_management.install_review_dialog_builder", "InstallReviewDialogBuilder"),
    "LocalModListPresenter": (".mods.mod_management.local_mod_list_presenter", "LocalModListPresenter"),
    "LocalTreeVirtualizationState": (
        ".mods.mod_management.local_tree_virtualization_state",
        "LocalTreeVirtualizationState",
    ),
    "ModManagementFrame": (".mods.mod_management.frame", "ModManagementFrame"),
    "OnlineBrowsePresenter": (".mods.mod_management.online_browse_presenter", "OnlineBrowsePresenter"),
    "MODRINTH_REQUEST_THROTTLE_SECONDS": (
        ".mods.mod_search_service.constants",
        "MODRINTH_REQUEST_THROTTLE_SECONDS",
    ),
    "MODRINTH_RETRY_BACKOFF_BASE_SECONDS": (
        ".mods.mod_search_service.constants",
        "MODRINTH_RETRY_BACKOFF_BASE_SECONDS",
    ),
    "MODRINTH_RETRY_BACKOFF_MAX_SECONDS": (
        ".mods.mod_search_service.constants",
        "MODRINTH_RETRY_BACKOFF_MAX_SECONDS",
    ),
    "analyze_local_mod_file_compatibility": (
        ".mods.mod_search_service.compatibility_analyzer",
        "analyze_local_mod_file_compatibility",
    ),
    "analyze_mod_version_compatibility": (
        ".mods.mod_search_service.compatibility_analyzer",
        "analyze_mod_version_compatibility",
    ),
    "build_local_mod_update_plan": (
        ".mods.mod_search_service.dependency_planner_facade",
        "build_local_mod_update_plan",
    ),
    "DependencyPlanningService": (
        ".mods.mod_search_service.dependency_planner_facade",
        "DependencyPlanningService",
    ),
    "build_required_dependency_install_plan": (
        ".mods.mod_search_service.dependency_planner_facade",
        "build_required_dependency_install_plan",
    ),
    "enhance_local_mod": (".mods.mod_search_service.modrinth_service", "enhance_local_mod"),
    "get_mod_versions": (".mods.mod_search_service.modrinth_service", "get_mod_versions"),
    "get_recommended_mod_version": (".mods.mod_search_service.modrinth_service", "get_recommended_mod_version"),
    "resolve_modrinth_project_names": (
        ".mods.mod_search_service.modrinth_service",
        "resolve_modrinth_project_names",
    ),
    "search_mods_online": (".mods.mod_search_service.modrinth_service", "search_mods_online"),
    "get_mod_version_details": (".mods.mod_search_service.modrinth_service", "get_mod_version_details"),
    "ProgressDialog": (".progress_dialog", "ProgressDialog"),
    "get_modrinth_current_versions_by_hashes": (
        ".mod_search_service.modrinth_service",
        "get_modrinth_current_versions_by_hashes",
    ),
    "get_modrinth_latest_versions_by_hashes": (
        ".mod_search_service.modrinth_service",
        "get_modrinth_latest_versions_by_hashes",
    ),
    "get_modrinth_project_info": (".mod_search_service.modrinth_service", "get_modrinth_project_info"),
    "ServerMonitorWindow": (".server_monitor_window", "ServerMonitorWindow"),
    "ServerPropertiesDialog": (".server_properties_dialog", "ServerPropertiesDialog"),
    "resolve_local_mod_project_info": (".mod_search_service.modrinth_service", "resolve_local_mod_project_info"),
    "TaskCoordinator": (".task_coordinator", "TaskCoordinator"),
    "PageRouter": (".page_router", "PageRouter"),
    "ManageServerService": (".manage_server_service", "ManageServerService"),
    "ServerRefreshContext": (".manage_server_service", "ServerRefreshContext"),
    "ServerRefreshExecutionPlan": (".manage_server_service", "ServerRefreshExecutionPlan"),
    "ServerRefreshPayload": (".manage_server_service", "ServerRefreshPayload"),
    "ServerTreeDiffPreparation": (".manage_server_service", "ServerTreeDiffPreparation"),
}
__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
