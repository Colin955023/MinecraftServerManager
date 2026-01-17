#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minecraft 伺服器管理器 - 主套件
提供 Minecraft 伺服器建立、管理和監控功能的主要套件模組
Minecraft Server Manager - Main Package
Main package module providing Minecraft server creation, management and monitoring functionality
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any, Callable


def lazy_exports(
    module_globals: dict[str, Any],
    module_name: str,
    exports: Mapping[str, tuple[str, str]],
) -> tuple[Callable[[str], Any], Callable[[], list[str]], list[str]]:
    """Create PEP 562 module-level lazy exports.

    Returns a tuple of (__getattr__, __dir__, __all__) for use inside a
    module's __init__.py.
    """

    def __getattr__(name: str) -> Any:
        target = exports.get(name)
        if not target:
            raise AttributeError(f"module {module_name!r} has no attribute {name!r}")
        module_path, attribute_name = target
        module = importlib.import_module(module_path, module_name)
        value = getattr(module, attribute_name)
        module_globals[name] = value
        return value

    def __dir__() -> list[str]:
        return sorted(list(module_globals.keys()) + list(exports.keys()))

    __all__ = sorted(exports.keys())
    return __getattr__, __dir__, __all__
