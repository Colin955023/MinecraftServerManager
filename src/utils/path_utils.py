#!/usr/bin/env python3
"""路徑工具模組
Path Utilities Module
"""

import json
from pathlib import Path
from typing import Any


class PathUtils:
    """路徑處理工具類別，提供專案路徑管理和安全路徑操作
    Path utilities class for project path management and safe path operations
    """

    @staticmethod
    def get_project_root() -> Path:
        """獲取專案根目錄路徑"""
        return Path(__file__).parent.parent.parent

    @staticmethod
    def get_assets_path() -> Path:
        """獲取 assets 目錄路徑"""
        return PathUtils.get_project_root() / "assets"

    @staticmethod
    def load_json(path: Path) -> dict[str, Any] | None:
        """讀取 JSON 檔案，統一處理編碼和錯誤
        Load JSON file with unified encoding and error handling

        Args:
            path: JSON 檔案路徑 (JSON file path)

        Returns:
            Dict[str, Any] | None: JSON 資料字典，失敗時返回 None (JSON data dict, None on failure)

        """
        try:
            if not path.exists():
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def save_json(path: Path, data: dict[str, Any], indent: int = 2) -> bool:
        """儲存 JSON 檔案，統一處理編碼和錯誤
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
            path.write_text(json.dumps(data, indent=indent, ensure_ascii=False), encoding="utf-8")
            return True
        except (OSError, TypeError):
            return False

    @staticmethod
    def read_text_file(path: Path, encoding: str = "utf-8", errors: str = "replace") -> str | None:
        """讀取文字檔案，統一處理編碼和錯誤
        Read text file with unified encoding and error handling

        Args:
            path: 檔案路徑 (File path)
            encoding: 編碼方式 (Encoding)
            errors: 錯誤處理方式 (Error handling)

        Returns:
            str | None: 檔案內容，失敗時返回 None (File content, None on failure)
        """
        try:
            if not path.exists():
                return None
            return path.read_text(encoding=encoding, errors=errors)
        except OSError:
            return None

    @staticmethod
    def write_text_file(path: Path, content: str, encoding: str = "utf-8") -> bool:
        """寫入文字檔案，統一處理編碼和錯誤
        Write text file with unified encoding and error handling

        Args:
            path: 檔案路徑 (File path)
            content: 檔案內容 (File content)
            encoding: 編碼方式 (Encoding)

        Returns:
            bool: 寫入成功返回 True (True if written successfully)
        """
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding=encoding)
            return True
        except OSError:
            return False

    @staticmethod
    def ensure_dir_exists(path: Path) -> bool:
        """確保目錄存在，不存在則創建
        Ensure directory exists, create if not

        Args:
            path: 目錄路徑 (Directory path)

        Returns:
            bool: 成功返回 True (True if successful)
        """
        try:
            path.mkdir(parents=True, exist_ok=True)
            return True
        except OSError:
            return False
