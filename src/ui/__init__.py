#!/usr/bin/env python3
"""使用者介面模組套件
提供 Minecraft 伺服器管理器的所有使用者介面元件和視窗
User Interface Modules Package
Provides all user interface components and windows for the Minecraft Server Manager
"""

from __future__ import annotations

from .. import lazy_exports

_EXPORTS: dict[str, tuple[str, str]] = {
    # main window
    "MinecraftServerManager": (".main_window", "MinecraftServerManager"),
    # main frames
    "CreateServerFrame": (".create_server_frame", "CreateServerFrame"),
    "ManageServerFrame": (".manage_server_frame", "ManageServerFrame"),
    "ModManagementFrame": (".mod_management", "ModManagementFrame"),
    # dialogs/windows
    "ServerMonitorWindow": (".server_monitor_window", "ServerMonitorWindow"),
    "ServerPropertiesDialog": (".server_properties_dialog", "ServerPropertiesDialog"),
    "WindowPreferencesDialog": (".window_preferences_dialog", "WindowPreferencesDialog"),
    # widgets
    "CustomDropdown": (".custom_dropdown", "CustomDropdown"),
    # services
    "search_mods_online": (".mod_search_service", "search_mods_online"),
    "enhance_local_mod": (".mod_search_service", "enhance_local_mod"),
}


__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
