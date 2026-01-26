#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路徑工具模組
Path Utilities Module
"""
from pathlib import Path
from typing import Any, Dict, Optional
import json

class PathUtils:
    """
    路徑處理工具類別，提供專案路徑管理和安全路徑操作
    Path utilities class for project path management and safe path operations
    """

    @staticmethod
    def get_project_root() -> Path:
        """
        獲取專案根目錄路徑
        """
        return Path(__file__).parent.parent.parent

    @staticmethod
    def get_assets_path() -> Path:
        """
        獲取 assets 目錄路徑
        """
        return PathUtils.get_project_root() / "assets"

    @staticmethod
    def load_json(path: Path) -> Optional[Dict[str, Any]]:
        """
        讀取 JSON 檔案，統一處理編碼和錯誤
        Load JSON file with unified encoding and error handling

        Args:
            path: JSON 檔案路徑 (JSON file path)

        Returns:
            Optional[Dict[str, Any]]: JSON 資料字典，失敗時返回 None (JSON data dict, None on failure)
        """
        try:
            if not path.exists():
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def save_json(path: Path, data: Dict[str, Any], indent: int = 2) -> bool:
        """
        儲存 JSON 檔案，統一處理編碼和錯誤
        Save JSON file with unified encoding and error handling

        Args:
            path: JSON 檔案路徑 (JSON file path)
            data: 要儲存的資料 (Data to save)
            indent: 縮排空格數 (Indentation spaces)

        Returns:
            bool: 儲存成功返回 True (True if saved successfully)
        """
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, indent=indent, ensure_ascii=False), encoding="utf-8"
            )
            return True
        except (OSError, TypeError):
            return False
