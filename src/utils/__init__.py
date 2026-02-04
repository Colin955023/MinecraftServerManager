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

import importlib

_EXPORTS: dict[str, tuple[str, str]] = {
    # logger
    "get_logger": (".logger", "get_logger"),
    # UI helpers
    "UIUtils": (".ui_utils", "UIUtils"),
    "DialogUtils": (".ui_utils", "DialogUtils"),
    "IconUtils": (".ui_utils", "IconUtils"),
    "ProgressDialog": (".ui_utils", "ProgressDialog"),
    # runtime paths
    "RuntimePaths": (".runtime_paths", "RuntimePaths"),
    # http
    "HTTPUtils": (".http_utils", "HTTPUtils"),
    # settings
    "get_settings_manager": (".settings_manager", "get_settings_manager"),
    # fonts
    "FontManager": (".font_manager", "FontManager"),
    # window
    "WindowManager": (".window_manager", "WindowManager"),
    # updates
    "UpdateChecker": (".update_checker", "UpdateChecker"),
    # restart
    "AppRestart": (".app_restart", "AppRestart"),
    "JavaDownloader": (".java_downloader", "JavaDownloader"),
    # java
    "JavaUtils": (".java_utils", "JavaUtils"),
    # paths
    "PathUtils": (".path_utils", "PathUtils"),
    # system
    "SystemUtils": (".system_utils", "SystemUtils"),
    # server utilities
    "MemoryUtils": (".server_utils", "MemoryUtils"),
    "ServerPropertiesHelper": (".server_utils", "ServerPropertiesHelper"),
    "ServerDetectionUtils": (".server_utils", "ServerDetectionUtils"),
    "ServerOperations": (".server_utils", "ServerOperations"),
    "ServerCommands": (".server_utils", "ServerCommands"),
    # singleton
    "Singleton": (".singleton", "Singleton"),
    # subprocess
    "SubprocessUtils": (".subprocess_utils", "SubprocessUtils"),
}


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if not target:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(list(globals().keys()) + list(_EXPORTS.keys()))


__all__ = sorted(_EXPORTS.keys())
