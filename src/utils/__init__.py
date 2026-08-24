"""
src/utils/__init__.py
工具模組套件
提供 Minecraft 伺服器管理器應用程式的各種工具函數和輔助類別
"""

from __future__ import annotations

from src import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "APP_NAME": (".runtime_utils.app_info", "APP_NAME"),
    "APP_VERSION": (".runtime_utils.app_info", "APP_VERSION"),
    "AppException": (".core_utils.exceptions", "AppException"),
    "ArchiveSecurityError": (".core_utils.exceptions", "ArchiveSecurityError"),
    "BoolState": (".ui_support.ui_state", "BoolState"),
    "CancellationToken": (".runtime_utils.background_task", "CancellationToken"),
    "Colors": (".ui_support.ui_tokens", "Colors"),
    "ConfigurationError": (".core_utils.exceptions", "ConfigurationError"),
    "CreationCancelledError": (".core_utils.exceptions", "CreationCancelledError"),
    "DEPENDENCY_PLAN_PERSISTENCE_SCHEMA_VERSION": (
        ".mod_utils.dependency_plan_serializer",
        "DEPENDENCY_PLAN_PERSISTENCE_SCHEMA_VERSION",
    ),
    "FloatState": (".ui_support.ui_state", "FloatState"),
    "FontManager": (".ui_support.font_manager", "FontManager"),
    "FontSize": (".ui_support.ui_tokens", "FontSize"),
    "GITHUB_OWNER": (".runtime_utils.app_info", "GITHUB_OWNER"),
    "GITHUB_REPO": (".runtime_utils.app_info", "GITHUB_REPO"),
    "HTTPClient": (".network_utils.http_client", "HTTPClient"),
    "HashUtils": (".core_utils.hash_utils", "HashUtils"),
    "ImportCancelledError": (".core_utils.exceptions", "ImportCancelledError"),
    "JavaDownloader": (".java_support.java_downloader", "JavaDownloader"),
    "JavaInstallError": (".core_utils.exceptions", "JavaInstallError"),
    "JavaUtils": (".java_support.java_utils", "JavaUtils"),
    "JvmOptionPolicy": (".server_utils.server_runtime_utils", "JvmOptionPolicy"),
    "MANAGED_STARTUP_SCRIPT_NAME": (
        ".server_utils.server_detection_utils",
        "MANAGED_STARTUP_SCRIPT_NAME",
    ),
    "LOCAL_UPDATE_ERROR_METADATA_UNRESOLVED": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_ERROR_METADATA_UNRESOLVED",
    ),
    "LOCAL_UPDATE_ERROR_STALE_REVALIDATION_FAILED": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_ERROR_STALE_REVALIDATION_FAILED",
    ),
    "LOCAL_UPDATE_ERROR_STALE_REVALIDATION_INVALIDATED": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_ERROR_STALE_REVALIDATION_INVALIDATED",
    ),
    "LOCAL_UPDATE_METADATA_NOTE_STALE_REVALIDATION_FAILED": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_METADATA_NOTE_STALE_REVALIDATION_FAILED",
    ),
    "LOCAL_UPDATE_NOTE_CURRENT_VERSION_UNVERIFIED": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_NOTE_CURRENT_VERSION_UNVERIFIED",
    ),
    "LOCAL_UPDATE_NOTE_IDENTIFIED_NO_UPDATE": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_NOTE_IDENTIFIED_NO_UPDATE",
    ),
    "LOCAL_UPDATE_NOTE_METADATA_UNRESOLVED": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_NOTE_METADATA_UNRESOLVED",
    ),
    "LOCAL_UPDATE_NOTE_PROJECT_FALLBACK_ADVISORY": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_NOTE_PROJECT_FALLBACK_ADVISORY",
    ),
    "LOCAL_UPDATE_NOTE_STALE_BACKOFF_INVALIDATED": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_NOTE_STALE_BACKOFF_INVALIDATED",
    ),
    "LOCAL_UPDATE_NOTE_STALE_BACKOFF_RETRYING": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_NOTE_STALE_BACKOFF_RETRYING",
    ),
    "LOCAL_UPDATE_NOTE_STALE_RETRY_AUTO": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_NOTE_STALE_RETRY_AUTO",
    ),
    "LOCAL_UPDATE_PROMPT_ADVISORY_LINE_TEMPLATE": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_PROMPT_ADVISORY_LINE_TEMPLATE",
    ),
    "LOCAL_UPDATE_PROMPT_BLOCKED_LINE_TEMPLATE": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_PROMPT_BLOCKED_LINE_TEMPLATE",
    ),
    "LOCAL_UPDATE_PROMPT_RETRYABLE_LINE_TEMPLATE": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_PROMPT_RETRYABLE_LINE_TEMPLATE",
    ),
    "LOCAL_UPDATE_PROMPT_UNKNOWN_LINE_TEMPLATE": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_PROMPT_UNKNOWN_LINE_TEMPLATE",
    ),
    "LOCAL_UPDATE_REVIEW_PRECHECK_NOTE": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_REVIEW_PRECHECK_NOTE",
    ),
    "LOCAL_UPDATE_SKIPPED_BLOCKED_TEMPLATE": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_SKIPPED_BLOCKED_TEMPLATE",
    ),
    "LOCAL_UPDATE_SKIPPED_RETRYABLE_TEMPLATE": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_SKIPPED_RETRYABLE_TEMPLATE",
    ),
    "LOCAL_UPDATE_SKIPPED_UNKNOWN_TEMPLATE": (
        ".mod_utils.mod_semantics",
        "LOCAL_UPDATE_SKIPPED_UNKNOWN_TEMPLATE",
    ),
    "METADATA_SOURCE_CACHED_PROVIDER": (".mod_utils.mod_semantics", "METADATA_SOURCE_CACHED_PROVIDER"),
    "METADATA_SOURCE_HASH": (".mod_utils.mod_semantics", "METADATA_SOURCE_HASH"),
    "METADATA_SOURCE_LABELS": (".mod_utils.mod_semantics", "METADATA_SOURCE_LABELS"),
    "METADATA_SOURCE_LOOKUP": (".mod_utils.mod_semantics", "METADATA_SOURCE_LOOKUP"),
    "METADATA_SOURCE_SHORT_LABELS": (".mod_utils.mod_semantics", "METADATA_SOURCE_SHORT_LABELS"),
    "METADATA_SOURCE_STALE_PROVIDER": (".mod_utils.mod_semantics", "METADATA_SOURCE_STALE_PROVIDER"),
    "METADATA_SOURCE_UNRESOLVED": (".mod_utils.mod_semantics", "METADATA_SOURCE_UNRESOLVED"),
    "MODRINTH_PREFERRED_HASH_ALGORITHM": (
        ".mod_utils.mod_version_filtering",
        "MODRINTH_PREFERRED_HASH_ALGORITHM",
    ),
    "MemoryUtils": (".server_utils.server_memory_utils", "MemoryUtils"),
    "ModIndexManager": (".mod_utils.mod_index_manager", "ModIndexManager"),
    "NetworkSecurityError": (".core_utils.exceptions", "NetworkSecurityError"),
    "ONLINE_INSTALL_NO_ACTIONABLE_MESSAGE": (
        ".mod_utils.mod_semantics",
        "ONLINE_INSTALL_NO_ACTIONABLE_MESSAGE",
    ),
    "ONLINE_INSTALL_PROMPT_ADVISORY_LINE_TEMPLATE": (
        ".mod_utils.mod_semantics",
        "ONLINE_INSTALL_PROMPT_ADVISORY_LINE_TEMPLATE",
    ),
    "ONLINE_INSTALL_PROMPT_BLOCKED_LINE_TEMPLATE": (
        ".mod_utils.mod_semantics",
        "ONLINE_INSTALL_PROMPT_BLOCKED_LINE_TEMPLATE",
    ),
    "ONLINE_REVIEW_PRECHECK_NOTE": (".mod_utils.mod_semantics", "ONLINE_REVIEW_PRECHECK_NOTE"),
    "PathUtils": (".core_utils.path_utils", "PathUtils"),
    "ProviderIdentityPersistenceError": (".core_utils.exceptions", "ProviderIdentityPersistenceError"),
    "RECOMMENDATION_CONFIDENCE_ADVISORY": (
        ".mod_utils.mod_semantics",
        "RECOMMENDATION_CONFIDENCE_ADVISORY",
    ),
    "RECOMMENDATION_CONFIDENCE_BLOCKED": (
        ".mod_utils.mod_semantics",
        "RECOMMENDATION_CONFIDENCE_BLOCKED",
    ),
    "RECOMMENDATION_CONFIDENCE_HIGH": (".mod_utils.mod_semantics", "RECOMMENDATION_CONFIDENCE_HIGH"),
    "RECOMMENDATION_CONFIDENCE_LABELS": (
        ".mod_utils.mod_semantics",
        "RECOMMENDATION_CONFIDENCE_LABELS",
    ),
    "RECOMMENDATION_CONFIDENCE_RETRYABLE": (
        ".mod_utils.mod_semantics",
        "RECOMMENDATION_CONFIDENCE_RETRYABLE",
    ),
    "RECOMMENDATION_SOURCE_HASH_METADATA": (
        ".mod_utils.mod_semantics",
        "RECOMMENDATION_SOURCE_HASH_METADATA",
    ),
    "RECOMMENDATION_SOURCE_LABELS": (".mod_utils.mod_semantics", "RECOMMENDATION_SOURCE_LABELS"),
    "RECOMMENDATION_SOURCE_METADATA_UNRESOLVED": (
        ".mod_utils.mod_semantics",
        "RECOMMENDATION_SOURCE_METADATA_UNRESOLVED",
    ),
    "RECOMMENDATION_SOURCE_PROJECT_FALLBACK": (
        ".mod_utils.mod_semantics",
        "RECOMMENDATION_SOURCE_PROJECT_FALLBACK",
    ),
    "RECOMMENDATION_SOURCE_SHORT_LABELS": (
        ".mod_utils.mod_semantics",
        "RECOMMENDATION_SOURCE_SHORT_LABELS",
    ),
    "RECOMMENDATION_SOURCE_STALE_METADATA": (
        ".mod_utils.mod_semantics",
        "RECOMMENDATION_SOURCE_STALE_METADATA",
    ),
    "ResponseTooLargeError": (".core_utils.exceptions", "ResponseTooLargeError"),
    "RuntimePaths": (".runtime_utils.runtime_paths", "RuntimePaths"),
    "STARTUP_SCRIPT_CANDIDATES": (
        ".server_utils.server_detection_utils",
        "STARTUP_SCRIPT_CANDIDATES",
    ),
    "ScrollableComboBox": (".ui_support.ui_utils", "ScrollableComboBox"),
    "ServerCommands": (".server_utils.server_runtime_utils", "ServerCommands"),
    "ServerDetectionUtils": (".server_utils.server_detection_utils", "ServerDetectionUtils"),
    "ServerDetectionVersionUtils": (
        ".server_utils.server_detection_utils",
        "ServerDetectionVersionUtils",
    ),
    "ServerOperations": (".server_utils.server_runtime_utils", "ServerOperations"),
    "ServerPropertiesHelper": (".server_utils.server_properties_utils", "ServerPropertiesHelper"),
    "ServerPropertiesValidator": (".server_utils.server_properties_utils", "ServerPropertiesValidator"),
    "Sizes": (".ui_support.ui_tokens", "Sizes"),
    "Spacing": (".ui_support.ui_tokens", "Spacing"),
    "StatusPushButton": (".ui_support.status_button", "StatusPushButton"),
    "SubprocessUtils": (".runtime_utils.subprocess_utils", "SubprocessUtils"),
    "SystemUtils": (".runtime_utils.system_utils", "SystemUtils"),
    "TextState": (".ui_support.ui_state", "TextState"),
    "UIUtils": (".ui_support.ui_utils", "UIUtils"),
    "UIWorkScope": (".ui_support.ui_work_scope", "UIWorkScope"),
    "UpdateChecker": (".update_utils.update_checker", "UpdateChecker"),
    "UpdateParsing": (".update_utils.update_parsing", "UpdateParsing"),
    "ValueState": (".ui_support.qt_runtime", "ValueState"),
    "Variable": (".ui_support.ui_state", "Variable"),
    "WorkHandle": (".ui_support.ui_work_scope", "WorkHandle"),
    "apply_loader_specific_dependency_override": (
        ".mod_utils.modrinth_query_utils",
        "apply_loader_specific_dependency_override",
    ),
    "SUPPORTED_MODRINTH_UPDATE_LOADERS": (
        ".mod_utils.modrinth_query_utils",
        "SUPPORTED_MODRINTH_UPDATE_LOADERS",
    ),
    "apply_table_header_style": (".ui_support.ui_config", "apply_table_header_style"),
    "atomic_write_bytes": (".core_utils.atomic_writer", "atomic_write_bytes"),
    "atomic_write_json": (".core_utils.atomic_writer", "atomic_write_json"),
    "atomic_write_text": (".core_utils.atomic_writer", "atomic_write_text"),
    "build_non_official_source_warning": (
        ".mod_utils.download_source_policy",
        "build_non_official_source_warning",
    ),
    "build_non_official_source_warning_message": (
        ".mod_utils.download_source_policy",
        "build_non_official_source_warning_message",
    ),
    "bytes_to_mb": (".core_utils.units_utils", "bytes_to_mb"),
    "cancel_timer": (".ui_support.qt_runtime", "cancel_timer"),
    "center_window": (".ui_support.ui_config", "center_window"),
    "clean_api_identifier": (".mod_utils.modrinth_query_utils", "clean_api_identifier"),
    "collect_installed_mod_identifiers": (
        ".mod_utils.local_mod_metadata_utils",
        "collect_installed_mod_identifiers",
    ),
    "collect_installed_mod_versions": (
        ".mod_utils.local_mod_metadata_utils",
        "collect_installed_mod_versions",
    ),
    "dependency_candidate_filenames": (
        ".mod_utils.local_mod_metadata_utils",
        "dependency_candidate_filenames",
    ),
    "dependency_maybe_installed_by_filename": (
        ".mod_utils.local_mod_metadata_utils",
        "dependency_maybe_installed_by_filename",
    ),
    "deserialize_online_dependency_install_plan": (
        ".mod_utils.dependency_plan_serializer",
        "deserialize_online_dependency_install_plan",
    ),
    "ensure_application": (".ui_support.qt_runtime", "ensure_application"),
    "expand_required_dependency_install_plan": (
        ".mod_utils.mod_dependency_planner",
        "expand_required_dependency_install_plan",
    ),
    "extract_download_host": (".mod_utils.download_source_policy", "extract_download_host"),
    "extract_primary_file_hash": (".mod_utils.mod_version_filtering", "extract_primary_file_hash"),
    "format_bytes": (".core_utils.units_utils", "format_bytes"),
    "get_icon_path": (".ui_support.qt_runtime", "get_icon_path"),
    "get_logger": (".core_utils.logger", "get_logger"),
    "get_modrinth_loader_filters": (".mod_utils.modrinth_query_utils", "get_modrinth_loader_filters"),
    "get_non_official_download_host": (
        ".mod_utils.download_source_policy",
        "get_non_official_download_host",
    ),
    "get_settings_manager": (".runtime_utils.settings_manager", "get_settings_manager"),
    "get_shared_manager": (".runtime_utils.background_task", "get_shared_manager"),
    "initialize_ui_theme": (".ui_support.ui_config", "initialize_ui_theme"),
    "invoke_later": (".ui_support.qt_runtime", "invoke_later"),
    "is_allowed_version_type": (".mod_utils.mod_version_filtering", "is_allowed_version_type"),
    "is_qobject_alive": (".ui_support.qt_runtime", "is_qobject_alive"),
    "is_supported_modrinth_update_loader": (
        ".mod_utils.modrinth_query_utils",
        "is_supported_modrinth_update_loader",
    ),
    "migrate_online_dependency_install_plan_payload": (
        ".mod_utils.dependency_plan_serializer",
        "migrate_online_dependency_install_plan_payload",
    ),
    "normalize_filename_stem": (".mod_utils.local_mod_metadata_utils", "normalize_filename_stem"),
    "normalize_hash_algorithm": (".mod_utils.mod_version_filtering", "normalize_hash_algorithm"),
    "normalize_identifier": (".mod_utils.modrinth_query_utils", "normalize_identifier"),
    "normalize_lax_filename": (".mod_utils.local_mod_metadata_utils", "normalize_lax_filename"),
    "normalize_local_loader": (".mod_utils.modrinth_query_utils", "normalize_local_loader"),
    "normalize_mod_search_query": (".mod_utils.modrinth_query_utils", "normalize_mod_search_query"),
    "parse_modrinth_version": (".mod_utils.modrinth_query_utils", "parse_modrinth_version"),
    "parse_modrinth_version_lookup_response": (
        ".mod_utils.modrinth_query_utils",
        "parse_modrinth_version_lookup_response",
    ),
    "parse_version_safe": (".core_utils.version_utils", "parse_version_safe"),
    "resolve_color": (".ui_support.ui_config", "resolve_color"),
    "resolve_dependency_reference": (
        ".mod_utils.mod_dependency_planner",
        "resolve_dependency_reference",
    ),
    "run_in_background": (".runtime_utils.background_task", "run_in_background"),
    "run_on_ui_thread": (".ui_support.qt_runtime", "run_on_ui_thread"),
    "select_best_mod_version": (".mod_utils.mod_version_filtering", "select_best_mod_version"),
    "serialize_online_dependency_install_plan": (
        ".mod_utils.dependency_plan_serializer",
        "serialize_online_dependency_install_plan",
    ),
    "shutdown_shared_manager": (".runtime_utils.background_task", "shutdown_shared_manager"),
    "validate_online_dependency_install_plan_payload": (
        ".mod_utils.dependency_plan_serializer",
        "validate_online_dependency_install_plan_payload",
    ),
    "version_type_priority": (".mod_utils.mod_version_filtering", "version_type_priority"),
}

__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
