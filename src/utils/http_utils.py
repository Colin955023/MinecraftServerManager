#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP 網路請求工具模組
提供標準化的 HTTP 請求功能，包含 JSON 取得、檔案下載等常用操作
HTTP Network Request Utilities Module
Provides standardized HTTP request functionality including JSON retrieval, file downloading and other common operations
"""
# ====== 標準函式庫 ======
from typing import Any, Dict, List, Optional
import asyncio
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import aiohttp
# ====== 專案內部模組 ======
from src.utils import LogUtils
from src.version_info import APP_NAME, APP_VERSION

class HTTPUtils:
    """
    HTTP 網路請求工具類別，提供各種 HTTP 操作的統一介面
    HTTP network request utility class providing unified interface for various HTTP operations
    """
    
    # 類別層級的共享 session，啟用連線池與自動重試
    _session = None
    
    @classmethod
    def _get_session(cls) -> requests.Session:
        """
        取得共享的 requests.Session 實例，配置連線池與重試策略
        Get shared requests.Session instance with connection pooling and retry strategy
        """
        if cls._session is None:
            cls._session = requests.Session()
            # 配置重試策略：連線錯誤重試 3 次，指數退避
            retry_strategy = Retry(
                total=3,
                backoff_factor=0.3,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "OPTIONS"]
            )
            adapter = HTTPAdapter(
                max_retries=retry_strategy,
                pool_connections=10,  # 連線池大小
                pool_maxsize=20       # 最大連線數
            )
            cls._session.mount("http://", adapter)
            cls._session.mount("https://", adapter)
        return cls._session
    
    @staticmethod
    def _get_default_headers(headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        獲取包含預設 User-Agent 的標頭
        Get headers with default User-Agent
        """
        default_headers = {
            "User-Agent": f"{APP_NAME}/{APP_VERSION} (colin955023@gmail.com)"
        }
        if headers:
            default_headers.update(headers)
        return default_headers

    # ====== JSON 資料請求 ======
    # 發送 GET 請求取得 JSON 資料
    @classmethod
    def get_json(cls, url: str, timeout: int = 10, headers: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """
        發送 HTTP GET 請求並解析回傳的 JSON 資料（使用連線池）
        Send HTTP GET request and parse returned JSON data (with connection pooling)

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
        timeout = max(10, timeout)

        try:
            session = cls._get_session()
            final_headers = cls._get_default_headers(headers)
            response = session.get(url, timeout=timeout, headers=final_headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            LogUtils.error_exc(f"HTTP GET JSON 請求失敗 ({url}): {e}", "HTTPUtils", e)
            return None

    # ====== 內容資料請求 ======
    # 發送 GET 請求取得 Response 物件
    @classmethod
    def get_content(
        cls, url: str, timeout: int = 30, stream: bool = False, headers: Optional[Dict[str, str]] = None
    ) -> Optional[requests.Response]:
        """
        發送 HTTP GET 請求並回傳完整的 Response 物件（使用連線池）
        Send HTTP GET request and return complete Response object (with connection pooling)

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
        timeout = max(30, timeout)

        try:
            session = cls._get_session()
            final_headers = cls._get_default_headers(headers)
            response = session.get(url, timeout=timeout, stream=stream, headers=final_headers)
            response.raise_for_status()
            return response
        except Exception as e:
            LogUtils.error_exc(f"HTTP GET 請求失敗 ({url}): {e}", "HTTPUtils", e)
            return None

    # ====== 檔案下載功能 ======
    # 下載檔案到本機
    @classmethod
    def download_file(cls, url: str, local_path: str, timeout: int = 60, chunk_size: int = 65536) -> bool:
        """
        從指定 URL 下載檔案並儲存到本機路徑（使用連線池）
        Download file from specified URL and save to local path (with connection pooling)

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

        timeout = max(60, timeout)
        chunk_size = max(65536, chunk_size)

        try:
            session = cls._get_session()
            final_headers = cls._get_default_headers()
            with session.get(url, stream=True, timeout=timeout, headers=final_headers) as r:
                r.raise_for_status()
                with open(local_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
            return True
        except Exception as e:
            LogUtils.error_exc(f"檔案下載失敗 ({url} -> {local_path}): {e}", "HTTPUtils", e)
            return False

    # ====== 非同步批次請求 ======
    # 非同步批次取得 JSON 資料
    @staticmethod
    async def get_json_batch_async(urls: List[str], timeout: int = 10, headers: Optional[Dict[str, str]] = None) -> List[Optional[Dict[str, Any]]]:
        """
        非同步批次發送 HTTP GET 請求並解析回傳的 JSON 資料
        Asynchronously batch send HTTP GET requests and parse returned JSON data

        Args:
            urls (List[str]): 請求的目標 URL 列表
            timeout (int): 請求超時時間（秒）
            headers (Optional[Dict[str, str]]): 可選的 HTTP 請求標頭

        Returns:
            List[Optional[Dict[str, Any]]]: JSON 字典列表，失敗的請求返回 None
        """
        timeout = max(10, timeout)
        final_headers = HTTPUtils._get_default_headers(headers)
        
        async def fetch_one(session: aiohttp.ClientSession, url: str) -> Optional[Dict[str, Any]]:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                    response.raise_for_status()
                    return await response.json()
            except Exception as e:
                LogUtils.error_exc(f"非同步 HTTP GET JSON 請求失敗 ({url}): {e}", "HTTPUtils", e)
                return None
        
        # 配置連線器限制並行數量
        connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
        async with aiohttp.ClientSession(headers=final_headers, connector=connector) as session:
            tasks = [fetch_one(session, url) for url in urls]
            return await asyncio.gather(*tasks)

    @staticmethod
    def get_json_batch(urls: List[str], timeout: int = 10, headers: Optional[Dict[str, str]] = None) -> List[Optional[Dict[str, Any]]]:
        """
        批次發送 HTTP GET 請求並解析回傳的 JSON 資料（同步包裝）
        Batch send HTTP GET requests and parse returned JSON data (synchronous wrapper)

        Args:
            urls (List[str]): 請求的目標 URL 列表
            timeout (int): 請求超時時間（秒）
            headers (Optional[Dict[str, str]]): 可選的 HTTP 請求標頭

        Returns:
            List[Optional[Dict[str, Any]]]: JSON 字典列表，失敗的請求返回 None
        """
        try:
            # 檢查是否已有執行中的事件迴圈
            try:
                loop = asyncio.get_running_loop()
                # 如果已在事件迴圈中，不能使用 run()，需要創建任務
                LogUtils.warning("已在事件迴圈中，退回使用同步請求", "HTTPUtils")
                return [HTTPUtils.get_json(url, timeout, headers) for url in urls]
            except RuntimeError:
                # 沒有執行中的迴圈，可以創建新的
                return asyncio.run(HTTPUtils.get_json_batch_async(urls, timeout, headers))
        except Exception as e:
            LogUtils.error_exc(f"批次 HTTP 請求失敗: {e}", "HTTPUtils", e)
            return [None] * len(urls)

# ====== 向後相容性函數別名 ======
# 提供向後相容的模組級別函數別名
get_json = HTTPUtils.get_json
get_content = HTTPUtils.get_content
download_file = HTTPUtils.download_file
get_json_batch = HTTPUtils.get_json_batch
get_json_batch_async = HTTPUtils.get_json_batch_async
