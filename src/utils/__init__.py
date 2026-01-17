#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具模組套件
提供 Minecraft 伺服器管理器應用程式的各種工具函數和輔助類別
Utility Modules Package
Provides various utility functions and helper classes for the Minecraft Server Manager application
"""

from __future__ import annotations

import importlib
from typing import Dict, Tuple

_EXPORTS: Dict[str, Tuple[str, str]] = {
    # logging
    "LogUtils": (".log_utils", "LogUtils"),
    # UI helpers
    "UIUtils": (".ui_utils", "UIUtils"),
    "DialogUtils": (".ui_utils", "DialogUtils"),
    "IconUtils": (".ui_utils", "IconUtils"),
    "ProgressDialog": (".ui_utils", "ProgressDialog"),
    # runtime paths
    "ensure_dir": (".runtime_paths", "ensure_dir"),
    "get_user_data_dir": (".runtime_paths", "get_user_data_dir"),
    "get_cache_dir": (".runtime_paths", "get_cache_dir"),
    # http
    "HTTPUtils": (".http_utils", "HTTPUtils"),
    "get_json": (".http_utils", "get_json"),
    "get_content": (".http_utils", "get_content"),
    "download_file": (".http_utils", "download_file"),
    # settings
    "get_settings_manager": (".settings_manager", "get_settings_manager"),
    # fonts
    "set_ui_scale_factor": (".font_manager", "set_ui_scale_factor"),
    "FontManager": (".font_manager", "FontManager"),
    "font_manager": (".font_manager", "font_manager"),
    "get_font": (".font_manager", "get_font"),
    "get_scale_factor": (".font_manager", "get_scale_factor"),
    "get_dpi_scaled_size": (".font_manager", "get_dpi_scaled_size"),
    "cleanup_fonts": (".font_manager", "cleanup_fonts"),
    # window
    "WindowManager": (".window_manager", "WindowManager"),
    # updates
    "check_and_prompt_update": (".update_checker", "check_and_prompt_update"),
    # restart
    "can_restart": (".app_restart", "can_restart"),
    "schedule_restart_and_exit": (".app_restart", "schedule_restart_and_exit"),
    # paths
    "PathUtils": (".path_utils", "PathUtils"),
    # server utilities
    "MemoryUtils": (".server_utils", "MemoryUtils"),
    "ServerPropertiesHelper": (".server_utils", "ServerPropertiesHelper"),
    "ServerDetectionUtils": (".server_utils", "ServerDetectionUtils"),
    "ServerOperations": (".server_utils", "ServerOperations"),
    "ServerCommands": (".server_utils", "ServerCommands"),
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
