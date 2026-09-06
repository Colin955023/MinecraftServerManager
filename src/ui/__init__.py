"""
src/ui/__init__.py
使用者介面模組套件
提供 Minecraft 伺服器管理器的所有使用者介面元件和視窗
"""

from __future__ import annotations

from src import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "BoolState": (".support.ui_state", "BoolState"),
    "Colors": (".support.ui_tokens", "Colors"),
    "FloatState": (".support.ui_state", "FloatState"),
    "FontManager": (".support.font_manager", "FontManager"),
    "FontSize": (".support.ui_tokens", "FontSize"),
    "JvmArgsDialog": (".dialogs.jvm_args_dialog", "JvmArgsDialog"),
    "FluentInputDialog": (".dialogs.main_window_dialogs", "FluentInputDialog"),
    "ImportDialog": (".dialogs.main_window_dialogs", "ImportDialog"),
    "MainWindow": (".core_frames.main_window", "MainWindow"),
    "ManageServerService": (".services.manage_server_service", "ManageServerService"),
    "MessageDialog": (".dialogs.modal_msfluent_window", "MessageDialog"),
    "ModManagementFrame": (".mods.frame", "ModManagementFrame"),
    "ModalMSFluentWindow": (".dialogs.modal_msfluent_window", "ModalMSFluentWindow"),
    "ProgressDialog": (".dialogs.progress_dialog", "ProgressDialog"),
    "ScrollableComboBox": (".support.ui_utils", "ScrollableComboBox"),
    "RestoreBackupDialog": (".dialogs.restore_backup_dialog", "RestoreBackupDialog"),
    "ServerCreationConfirmDialog": (
        ".dialogs.server_creation_confirm_dialog",
        "ServerCreationConfirmDialog",
    ),
    "ServerMemoryDialog": (".dialogs.server_memory_dialog", "ServerMemoryDialog"),
    "ServerInitializationDialog": (".dialogs.main_window_dialogs", "ServerInitializationDialog"),
    "ServerMonitorWindow": (".windows.server_monitor_window", "ServerMonitorWindow"),
    "ServerPropertiesDialog": (".dialogs.server_properties_dialog", "ServerPropertiesDialog"),
    "ServerRenderPlan": (".services.manage_server_service", "ServerRenderPlan"),
    "Sizes": (".support.ui_tokens", "Sizes"),
    "Spacing": (".support.ui_tokens", "Spacing"),
    "StatusPushButton": (".support.status_button", "StatusPushButton"),
    "TaskCoordinator": (".services.task_coordinator", "TaskCoordinator"),
    "TextState": (".support.ui_state", "TextState"),
    "UIUtils": (".support.ui_utils", "UIUtils"),
    "UIWorkScope": (".support.ui_work_scope", "UIWorkScope"),
    "UpdateChecker": (".services.update_checker", "UpdateChecker"),
    "ValueState": (".support.qt_runtime", "ValueState"),
    "WorkOutcome": (".support.ui_work_scope", "WorkOutcome"),
    "apply_table_header_style": (".support.ui_config", "apply_table_header_style"),
    "apply_window_icon": (".support.qt_runtime", "apply_window_icon"),
    "center_window": (".support.ui_config", "center_window"),
    "ensure_application": (".support.qt_runtime", "ensure_application"),
    "initialize_ui_theme": (".support.ui_config", "initialize_ui_theme"),
    "invoke_later": (".support.qt_runtime", "invoke_later"),
    "is_qobject_alive": (".support.qt_runtime", "is_qobject_alive"),
    "resolve_color": (".support.ui_config", "resolve_color"),
    "themed_surface_stylesheet": (".support.ui_config", "themed_surface_stylesheet"),
    "run_application": (".core_frames.main_window", "run_application"),
    "run_on_ui_thread": (".support.qt_runtime", "run_on_ui_thread"),
    "set_ui_closing": (".support.qt_runtime", "set_ui_closing"),
}
__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
