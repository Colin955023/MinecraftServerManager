#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路徑工具模組
Path Utilities Module
"""
from pathlib import Path

class PathUtils:
    """
    路徑處理工具類別，提供專案路徑管理和安全路徑操作
    Path utilities class for project path management and safe path operations
    """
    
    @staticmethod
    def get_project_root() -> Path:
        """
        獲取專案根目錄路徑
        Get project root directory path

        Returns:
            Path: 專案根目錄路徑物件 (Project root directory path object)
        """
        return Path(__file__).parent.parent.parent

    @staticmethod
    def get_assets_path() -> Path:
        """
        獲取 assets 目錄路徑
        Get assets directory path

        Returns:
            Path: assets 目錄路徑物件 (Assets directory path object)
        """
        return PathUtils.get_project_root() / "assets"
