#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核心模組套件
提供 Minecraft 伺服器管理器的核心功能模組，包含伺服器管理、版本控制、載入器管理等
Core Modules Package
Provides core functionality modules for Minecraft Server Manager including server management, version control, loader management
"""

from __future__ import annotations
from typing import Dict, Tuple
from .. import lazy_exports

_EXPORTS: Dict[str, Tuple[str, str]] = {
    "ServerManager": (".server_manager", "ServerManager"),
    "ServerConfig": (".server_manager", "ServerConfig"),
    "LoaderManager": (".loader_manager", "LoaderManager"),
    "MinecraftVersionManager": (".version_manager", "MinecraftVersionManager"),
    "ModManager": (".mod_manager", "ModManager"),
    "ModStatus": (".mod_manager", "ModStatus"),
    "ModPlatform": (".mod_manager", "ModPlatform"),
}

__getattr__, __dir__, __all__ = lazy_exports(globals(), __name__, _EXPORTS)
