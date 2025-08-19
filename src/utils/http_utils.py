#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP 網路請求工具模組
提供標準化的 HTTP 請求功能，包含 JSON 取得、檔案下載等常用操作
HTTP Network Request Utilities Module
Provides standardized HTTP request functionality including JSON retrieval, file downloading and other common operations
"""
# ====== 標準函式庫 ======
from typing import Any, Dict, Optional
import requests
# ====== 專案內部模組 ======
from src.utils.log_utils import LogUtils
from src.utils.ui_utils import UIUtils

class HTTPUtils:
    """
    HTTP 網路請求工具類別，提供各種 HTTP 操作的統一介面
    HTTP network request utility class providing unified interface for various HTTP operations
    """
    # ====== JSON 資料請求 ======
    # 發送 GET 請求取得 JSON 資料
    @staticmethod
    def get_json(url: str, timeout: int = 10, headers: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """
        發送 HTTP GET 請求並解析回傳的 JSON 資料
        Send HTTP GET request and parse returned JSON data

        Args:
            url (str): 請求的目標 URL
            timeout (int): 請求超時時間（秒）
            headers (Optional[Dict[str, str]]): 可選的 HTTP 請求標頭

        Returns:
            Optional[Dict[str, Any]]: 成功時返回 JSON 字典，失敗時返回 None
        """
        if not url or not isinstance(url, str):
            LogUtils.error("HTTP GET JSON 請求失敗: URL 參數無效", "HTTPUtils")
            return None
        if timeout <= 0:
            timeout = 10

        try:
            response = requests.get(url, timeout=timeout, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            LogUtils.error(f"HTTP GET JSON 請求失敗 ({url}): {e}", "HTTPUtils")
            UIUtils.show_error("請求失敗", f"HTTP GET JSON 請求失敗 ({url}): {e}")
            return None

    # ====== 內容資料請求 ======
    # 發送 GET 請求取得 Response 物件
    @staticmethod
    def get_content(
        url: str, timeout: int = 30, stream: bool = False, headers: Optional[Dict[str, str]] = None
    ) -> Optional[requests.Response]:
        """
        發送 HTTP GET 請求並回傳完整的 Response 物件
        Send HTTP GET request and return complete Response object

        Args:
            url (str): 請求的目標 URL
            timeout (int): 請求超時時間（秒）
            stream (bool): 是否使用串流模式下載
            headers (Optional[Dict[str, str]]): 可選的 HTTP 請求標頭

        Returns:
            Optional[requests.Response]: 成功時返回 Response 物件，失敗時返回 None
        """
        if not url or not isinstance(url, str):
            LogUtils.error("HTTP GET 請求失敗: URL 參數無效", "HTTPUtils")
            return None
        if timeout <= 0:
            timeout = 30

        try:
            response = requests.get(url, timeout=timeout, stream=stream, headers=headers)
            response.raise_for_status()
            return response
        except Exception as e:
            LogUtils.error(f"HTTP GET 請求失敗 ({url}): {e}", "HTTPUtils")
            UIUtils.show_error("請求失敗", f"HTTP GET 請求失敗 ({url}): {e}")
            return None

    # ====== 檔案下載功能 ======
    # 下載檔案到本機
    @staticmethod
    def download_file(url: str, local_path: str, timeout: int = 60, chunk_size: int = 65536) -> bool:
        """
        從指定 URL 下載檔案並儲存到本機路徑
        Download file from specified URL and save to local path

        Args:
            url (str): 檔案下載的來源 URL
            local_path (str): 檔案儲存的本機路徑
            timeout (int): 下載超時時間（秒）
            chunk_size (int): 每次下載的資料塊大小（位元組）

        Returns:
            bool: 下載成功返回 True，失敗返回 False
        """
        if not url or not isinstance(url, str):
            LogUtils.error("檔案下載失敗: URL 參數無效", "HTTPUtils")
            return False
        if not local_path or not isinstance(local_path, str):
            LogUtils.error("檔案下載失敗: 本地路徑參數無效", "HTTPUtils")
            return False
        if timeout <= 0:
            timeout = 60
        if chunk_size <= 0:
            chunk_size = 65536

        try:
            response = HTTPUtils.get_content(url, timeout=timeout, stream=True)
            if response is None:
                return False

            with open(local_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    f.write(chunk)
            return True
        except Exception as e:
            LogUtils.error(f"檔案下載失敗 ({url} -> {local_path}): {e}", "HTTPUtils")
            UIUtils.show_error("檔案下載失敗", f"檔案下載失敗 ({url} -> {local_path}): {e}")
            return False

# ====== 向後相容性函數別名 ======
# 提供向後相容的模組級別函數別名
get_json = HTTPUtils.get_json
get_content = HTTPUtils.get_content
download_file = HTTPUtils.download_file
