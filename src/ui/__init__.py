"""
src/ui/__init__.py
使用者介面模組套件
提供 Minecraft 伺服器管理器的所有使用者介面元件和視窗
"""

from __future__ import annotations

from src import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "JvmArgsDialog": (".dialogs.jvm_args_dialog", "JvmArgsDialog"),
    "MainWindow": (".core_frames.main_window", "MainWindow"),
    "ManageServerService": (".services.manage_server_service", "ManageServerService"),
    "MessageDialog": (".dialogs.modal_msfluent_window", "MessageDialog"),
    "ModManagementFrame": (".mods.frame", "ModManagementFrame"),
    "ModalMSFluentWindow": (".dialogs.modal_msfluent_window", "ModalMSFluentWindow"),
    "ProgressDialog": (".dialogs.progress_dialog", "ProgressDialog"),
    "RestoreBackupDialog": (".dialogs.restore_backup_dialog", "RestoreBackupDialog"),
    "ServerCreationConfirmDialog": (
        ".dialogs.server_creation_confirm_dialog",
        "ServerCreationConfirmDialog",
    ),
    "ServerMemoryDialog": (".dialogs.server_memory_dialog", "ServerMemoryDialog"),
    "ServerMonitorWindow": (".windows.server_monitor_window", "ServerMonitorWindow"),
    "ServerPropertiesDialog": (".dialogs.server_properties_dialog", "ServerPropertiesDialog"),
    "ServerRenderPlan": (".services.manage_server_service", "ServerRenderPlan"),
    "TaskCoordinator": (".services.task_coordinator", "TaskCoordinator"),
    "run_application": (".core_frames.main_window", "run_application"),
}
__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
