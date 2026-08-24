"""
src/ui/__init__.py
使用者介面模組套件
提供 Minecraft 伺服器管理器的所有使用者介面元件和視窗
"""

from __future__ import annotations

from src import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "AboutPreferencesFrame": (".core_frames.about_preferences_frame", "AboutPreferencesFrame"),
    "ApplicationShell": (".services.application_shell", "ApplicationShell"),
    "CreateServerFrame": (".core_frames.create_server_frame", "CreateServerFrame"),
    "HostBound": (".mods.host_bound", "HostBound"),
    "InstallReviewDialogBuilder": (".mods.install_review_dialog_builder", "InstallReviewDialogBuilder"),
    "JvmArgsDialog": (".dialogs.jvm_args_dialog", "JvmArgsDialog"),
    "LocalModListPresenter": (".mods.local_mod_list_presenter", "LocalModListPresenter"),
    "LocalReviewSession": (".mods.review_workflow", "LocalReviewSession"),
    "LocalReviewSnapshotStore": (".mods.review_snapshot_store", "LocalReviewSnapshotStore"),
    "MainWindow": (".core_frames.main_window", "MainWindow"),
    "ManageServerFrame": (".core_frames.manage_server_frame", "ManageServerFrame"),
    "ManageServerService": (".services.manage_server_service", "ManageServerService"),
    "MessageDialog": (".dialogs.modal_msfluent_window", "MessageDialog"),
    "MODRINTH_PROJECT_PAGE_BASE_URL": (".mods.constants", "MODRINTH_PROJECT_PAGE_BASE_URL"),
    "ModManagementFrame": (".mods.frame", "ModManagementFrame"),
    "ModManagementInstallExecutor": (".mods.install_executor", "ModManagementInstallExecutor"),
    "ModManagementQueueOps": (".mods.online_mod_queue", "ModManagementQueueOps"),
    "ModManagementReviewOps": (".mods.review", "ModManagementReviewOps"),
    "ModManagementSession": (".mods.mod_management_session", "ModManagementSession"),
    "ModManagementTreeSyncOps": (".mods.tree_sync", "ModManagementTreeSyncOps"),
    "ModReviewWorkflow": (".mods.review_workflow", "ModReviewWorkflow"),
    "ModalMSFluentWindow": (".dialogs.modal_msfluent_window", "ModalMSFluentWindow"),
    "OnlineBrowsePresenter": (".mods.online_browse_presenter", "OnlineBrowsePresenter"),
    "OnlineReviewSession": (".mods.review_workflow", "OnlineReviewSession"),
    "PageRouter": (".core_frames.page_router", "PageRouter"),
    "ProgressDialog": (".dialogs.progress_dialog", "ProgressDialog"),
    "RestoreBackupDialog": (".dialogs.restore_backup_dialog", "RestoreBackupDialog"),
    "ReviewExecutionHandoff": (".mods.review_contracts", "ReviewExecutionHandoff"),
    "ReviewFormattingMixin": (".mods.review_formatting", "ReviewFormattingMixin"),
    "ReviewGroupingMixin": (".mods.review_grouping", "ReviewGroupingMixin"),
    "ReviewInstallStep": (".mods.review_contracts", "ReviewInstallStep"),
    "ReviewRootView": (".mods.review_contracts", "ReviewRootView"),
    "ReviewTaskView": (".mods.review_contracts", "ReviewTaskView"),
    "ReviewViewSnapshot": (".mods.review_contracts", "ReviewViewSnapshot"),
    "ServerCreationConfirmDialog": (
        ".dialogs.server_creation_confirm_dialog",
        "ServerCreationConfirmDialog",
    ),
    "ServerMonitorWindow": (".windows.server_monitor_window", "ServerMonitorWindow"),
    "ServerPropertiesDialog": (".dialogs.server_properties_dialog", "ServerPropertiesDialog"),
    "TaskCoordinator": (".services.task_coordinator", "TaskCoordinator"),
    "append_dependency_review_sections": (
        ".mods.review_dependency",
        "append_dependency_review_sections",
    ),
    "append_enabled_dependency_simulations": (
        ".mods.review_dependency",
        "append_enabled_dependency_simulations",
    ),
    "append_plan_note_section": (".mods.review_formatting", "append_plan_note_section"),
    "append_review_section": (".mods.review_formatting", "append_review_section"),
    "build_client_install_reminder_line": (
        ".mods.mod_presentation",
        "build_client_install_reminder_line",
    ),
    "build_dependency_key": (".mods.review_dependency", "build_dependency_key"),
    "build_dependency_review_key": (".mods.review_dependency", "build_dependency_review_key"),
    "build_dependency_status_text": (".mods.review_dependency", "build_dependency_status_text"),
    "build_installed_mod_simulation_item": (
        ".mods.review_dependency",
        "build_installed_mod_simulation_item",
    ),
    "build_local_update_execution_prompt": (
        ".mods.review_prompts",
        "build_local_update_execution_prompt",
    ),
    "build_local_update_review_key": (".mods.review_grouping", "build_local_update_review_key"),
    "build_local_update_review_subtitle": (
        ".mods.review_formatting",
        "build_local_update_review_subtitle",
    ),
    "build_non_official_source_confirmation_prompt": (
        ".mods.review_prompts",
        "build_non_official_source_confirmation_prompt",
    ),
    "build_online_install_execution_prompt": (
        ".mods.review_prompts",
        "build_online_install_execution_prompt",
    ),
    "build_online_install_review_subtitle": (
        ".mods.review_formatting",
        "build_online_install_review_subtitle",
    ),
    "build_online_review_root_status_text": (
        ".mods.review_grouping",
        "build_online_review_root_status_text",
    ),
    "build_pending_install_review_key": (".mods.review_grouping", "build_pending_install_review_key"),
    "build_review_context_stamp": (".mods.review_contracts", "build_review_context_stamp"),
    "build_review_root_status_text": (".mods.review_grouping", "build_review_root_status_text"),
    "build_server_install_blocking_reason": (
        ".mods.mod_presentation",
        "build_server_install_blocking_reason",
    ),
    "build_server_install_warning_line": (
        ".mods.mod_presentation",
        "build_server_install_warning_line",
    ),
    "collect_dependency_required_by": (".mods.review_dependency", "collect_dependency_required_by"),
    "collect_non_official_source_warning_messages": (
        ".mods.review_prompts",
        "collect_non_official_source_warning_messages",
    ),
    "collect_review_entry_enabled_overrides": (
        ".mods.review_selection",
        "collect_review_entry_enabled_overrides",
    ),
    "count_dependency_plan_items": (".mods.review_dependency", "count_dependency_plan_items"),
    "count_enabled_runnable_entries": (".mods.review_selection", "count_enabled_runnable_entries"),
    "count_local_update_review_groups": (".mods.review_grouping", "count_local_update_review_groups"),
    "count_online_install_review_groups": (
        ".mods.review_grouping",
        "count_online_install_review_groups",
    ),
    "count_review_nodes": (".mods.review_dependency", "count_review_nodes"),
    "dedupe_review_messages": (".mods.review_formatting", "dedupe_review_messages"),
    "describe_context_mismatch": (".mods.review_contracts", "describe_context_mismatch"),
    "format_completion_notes": (".mods.review_formatting", "format_completion_notes"),
    "format_local_update_review_text": (".mods.review_details", "format_local_update_review_text"),
    "format_local_update_source_text": (".mods.review_formatting", "format_local_update_source_text"),
    "format_metadata_source_label": (".mods.review_formatting", "format_metadata_source_label"),
    "format_online_version_report": (".mods.mod_presentation", "format_online_version_report"),
    "format_pending_install_review_text": (
        ".mods.review_details",
        "format_pending_install_review_text",
    ),
    "format_provider_label": (".mods.mod_presentation", "format_provider_label"),
    "format_published_at": (".mods.mod_presentation", "format_published_at"),
    "format_recommendation_confidence_label": (
        ".mods.review_formatting",
        "format_recommendation_confidence_label",
    ),
    "format_recommendation_source_label": (
        ".mods.review_formatting",
        "format_recommendation_source_label",
    ),
    "format_required_by_list": (".mods.review_formatting", "format_required_by_list"),
    "format_review_overview_text": (".mods.review_formatting", "format_review_overview_text"),
    "get_enabled_dependency_install_items": (
        ".mods.review_dependency",
        "get_enabled_dependency_install_items",
    ),
    "get_local_update_group_status_label": (
        ".mods.review_grouping",
        "get_local_update_group_status_label",
    ),
    "get_local_update_review_group_key": (".mods.review_grouping", "get_local_update_review_group_key"),
    "get_online_install_group_status_label": (
        ".mods.review_grouping",
        "get_online_install_group_status_label",
    ),
    "get_online_install_review_group_key": (
        ".mods.review_grouping",
        "get_online_install_review_group_key",
    ),
    "get_online_version_status_text": (".mods.mod_presentation", "get_online_version_status_text"),
    "get_review_group_specs": (".mods.review_grouping", "get_review_group_specs"),
    "get_sorted_dependency_review_items": (
        ".mods.review_dependency",
        "get_sorted_dependency_review_items",
    ),
    "is_optional_dependency_item": (".mods.review_dependency", "is_optional_dependency_item"),
    "mask_redundant_review_values": (".mods.review_formatting", "mask_redundant_review_values"),
    "mod_management_logger": (".mods.constants", "logger"),
    "normalize_status_value": (".mods.review_contracts", "normalize_status_value"),
    "resolve_local_update_review_project_page_url": (
        ".mods.review_formatting",
        "resolve_local_update_review_project_page_url",
    ),
    "resolve_online_mod_project_page_url": (
        ".mods.mod_presentation",
        "resolve_online_mod_project_page_url",
    ),
    "resolve_pending_install_review_project_page_url": (
        ".mods.review_formatting",
        "resolve_pending_install_review_project_page_url",
    ),
    "resolve_project_page_url": (".mods.mod_presentation", "resolve_project_page_url"),
    "run_application": (".core_frames.main_window", "run_application"),
    "set_review_entries_enabled": (".mods.review_selection", "set_review_entries_enabled"),
    "sort_online_versions_for_server": (".mods.mod_presentation", "sort_online_versions_for_server"),
    "summarize_changelog": (".mods.mod_presentation", "summarize_changelog"),
}
__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
