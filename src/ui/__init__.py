"""
src/ui/__init__.py
使用者介面模組套件
提供 Minecraft 伺服器管理器的所有使用者介面元件和視窗
"""

from __future__ import annotations

from src import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "AboutPreferencesFrame": (".core_frames.about_preferences_frame", "AboutPreferencesFrame"),
    "CreateServerFrame": (".core_frames.create_server_frame", "CreateServerFrame"),
    "InstallReviewDialogBuilder": (".mods.install_review_dialog_builder", "InstallReviewDialogBuilder"),
    "JvmArgsDialog": (".dialogs.jvm_args_dialog", "JvmArgsDialog"),
    "LocalModListPresenter": (".mods.local_mod_list_presenter", "LocalModListPresenter"),
    "LocalReviewSession": (".mods.review_workflow", "LocalReviewSession"),
    "MainWindow": (".core_frames.main_window", "MainWindow"),
    "ManageServerFrame": (".core_frames.manage_server_frame", "ManageServerFrame"),
    "ManageServerService": (".services.manage_server_service", "ManageServerService"),
    "MessageDialog": (".dialogs.modal_msfluent_window", "MessageDialog"),
    "MODRINTH_PROJECT_PAGE_BASE_URL": (".mods.constants", "MODRINTH_PROJECT_PAGE_BASE_URL"),
    "ModManagementFrame": (".mods.frame", "ModManagementFrame"),
    "ModManagementInstallExecutor": (".mods.install_executor", "ModManagementInstallExecutor"),
    "ModManagementQueueOps": (".mods.online_mod_queue", "ModManagementQueueOps"),
    "ModManagementReviewOps": (".mods.review", "ModManagementReviewOps"),
    "ModListRow": (".mods.mod_management_session", "ModListRow"),
    "ModOperationScope": (".mods.mod_management_session", "ModOperationScope"),
    "ModManagementSession": (".mods.mod_management_session", "ModManagementSession"),
    "ModManagementTreeSyncOps": (".mods.tree_sync", "ModManagementTreeSyncOps"),
    "ModReviewWorkflow": (".mods.review_workflow", "ModReviewWorkflow"),
    "ModalMSFluentWindow": (".dialogs.modal_msfluent_window", "ModalMSFluentWindow"),
    "OnlineBrowsePresenter": (".mods.online_browse_presenter", "OnlineBrowsePresenter"),
    "OnlineBrowseRequest": (".mods.mod_management_session", "OnlineBrowseRequest"),
    "OnlineReviewSession": (".mods.review_workflow", "OnlineReviewSession"),
    "PageRouter": (".core_frames.page_router", "PageRouter"),
    "ProgressDialog": (".dialogs.progress_dialog", "ProgressDialog"),
    "RestoreBackupDialog": (".dialogs.restore_backup_dialog", "RestoreBackupDialog"),
    "ReviewExecutionHandoff": (".mods.review_contracts", "ReviewExecutionHandoff"),
    "ReviewInstallStep": (".mods.review_contracts", "ReviewInstallStep"),
    "ReviewViewSnapshot": (".mods.review_contracts", "ReviewViewSnapshot"),
    "ServerCreationConfirmDialog": (
        ".dialogs.server_creation_confirm_dialog",
        "ServerCreationConfirmDialog",
    ),
    "ServerMemoryDialog": (".dialogs.server_memory_dialog", "ServerMemoryDialog"),
    "ServerMonitorWindow": (".windows.server_monitor_window", "ServerMonitorWindow"),
    "ServerRenderPlan": (".services.manage_server_service", "ServerRenderPlan"),
    "ServerPropertiesDialog": (".dialogs.server_properties_dialog", "ServerPropertiesDialog"),
    "TaskCoordinator": (".services.task_coordinator", "TaskCoordinator"),
    "build_server_install_blocking_reason": (
        ".mods.mod_presentation",
        "build_server_install_blocking_reason",
    ),
    "format_online_version_report": (".mods.mod_presentation", "format_online_version_report"),
    "get_online_version_status_text": (".mods.mod_presentation", "get_online_version_status_text"),
    "mod_management_logger": (".mods.constants", "logger"),
    "run_application": (".core_frames.main_window", "run_application"),
    "sort_online_versions_for_server": (".mods.mod_presentation", "sort_online_versions_for_server"),
}
__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
