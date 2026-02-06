#!/usr/bin/env python3
"""工具模組套件
提供 Minecraft 伺服器管理器應用程式的各種工具函數和輔助類別
Utility Modules Package
Provides various utility functions and helper classes for the Minecraft Server Manager application

Logger can be imported conveniently:
    from src.utils import get_logger
    logger = get_logger().bind(component="ComponentName")
"""

from __future__ import annotations

import src

# 使用統一的 lazy_exports 機制（單一來源原則）
_EXPORTS: dict[str, tuple[str, str]] = {
    "get_logger": (".logger", "get_logger"),
    "UIUtils": (".ui_utils", "UIUtils"),
    "IconUtils": (".ui_utils", "IconUtils"),
    "ProgressDialog": (".ui_utils", "ProgressDialog"),
    "RuntimePaths": (".runtime_paths", "RuntimePaths"),
    "HTTPUtils": (".http_utils", "HTTPUtils"),
    "get_settings_manager": (".settings_manager", "get_settings_manager"),
    "FontManager": (".font_manager", "FontManager"),
    "WindowManager": (".window_manager", "WindowManager"),
    "UpdateChecker": (".update_checker", "UpdateChecker"),
    "FontSize": (".ui_utils", "FontSize"),
    "Colors": (".ui_utils", "Colors"),
    "Spacing": (".ui_utils", "Spacing"),
    "Sizes": (".ui_utils", "Sizes"),
    "get_button_style": (".ui_utils", "get_button_style"),
    "get_dropdown_style": (".ui_utils", "get_dropdown_style"),
    "AppRestart": (".app_restart", "AppRestart"),
    "JavaDownloader": (".java_downloader", "JavaDownloader"),
    "JavaUtils": (".java_utils", "JavaUtils"),
    "PathUtils": (".path_utils", "PathUtils"),
    "SystemUtils": (".system_utils", "SystemUtils"),
    "MemoryUtils": (".server_utils", "MemoryUtils"),
    "ServerPropertiesHelper": (".server_utils", "ServerPropertiesHelper"),
    "ServerPropertiesValidator": (".server_utils", "ServerPropertiesValidator"),
    "ServerDetectionUtils": (".server_utils", "ServerDetectionUtils"),
    "ServerOperations": (".server_utils", "ServerOperations"),
    "ServerCommands": (".server_utils", "ServerCommands"),
    "Singleton": (".singleton", "Singleton"),
    "SubprocessUtils": (".subprocess_utils", "SubprocessUtils"),
}

__getattr__, __dir__, __all__ = src.lazy_exports(globals(), __name__, _EXPORTS)
