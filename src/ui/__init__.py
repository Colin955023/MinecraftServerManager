"""
src/ui/__init__.py
使用者介面模組套件
提供 Minecraft 伺服器管理器的所有使用者介面元件和視窗
"""

from __future__ import annotations

import re as re

from .. import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    "CreateServerService": (".create_server_service", "CreateServerService"),
    "ServerConfigInputs": (".create_server_service", "ServerConfigInputs"),
    "ModManagementRuntimeBase": (".mod_management.online_mod_queue", "ModManagementRuntimeBase"),
    "CreateServerFrame": (".create_server_frame", "CreateServerFrame"),
    "MinecraftServerManager": (".main_window", "MinecraftServerManager"),
    "ManageServerFrame": (".manage_server_frame", "ManageServerFrame"),
    "ServerListViewModel": (".server_list_view_model", "ServerListViewModel"),
    "ServerRefreshPayload": (".server_list_view_model", "ServerRefreshPayload"),
    "InstallReviewDialogBuilder": (".mod_management.install_review_dialog_builder", "InstallReviewDialogBuilder"),
    "LocalModListPresenter": (".mod_management.local_mod_list_presenter", "LocalModListPresenter"),
    "TreeVirtualizationState": (
        ".mod_management.local_tree_virtualization_state",
        "TreeVirtualizationState",
    ),
    "ModManagementFrame": (".mod_management.frame", "ModManagementFrame"),
    "OnlineBrowsePresenter": (".mod_management.online_browse_presenter", "OnlineBrowsePresenter"),
    "ProgressDialog": (".progress_dialog", "ProgressDialog"),
    "ServerMonitorWindow": (".server_monitor_window", "ServerMonitorWindow"),
    "ServerPropertiesDialog": (".server_properties_dialog", "ServerPropertiesDialog"),
    "ImportServerService": (".import_server_service", "ImportServerService"),
    "ManageServerService": (".manage_server_service", "ManageServerService"),
    "AboutPreferencesFrame": (".about_preferences_frame", "AboutPreferencesFrame"),
    "run": (".main_window", "run"),
}
__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
