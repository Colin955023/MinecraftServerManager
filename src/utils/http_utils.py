#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP 網路請求工具模組
提供標準化的 HTTP 請求功能，包含 JSON 取得、檔案下載等常用操作
HTTP Network Request Utilities Module
Provides standardized HTTP request functionality including JSON retrieval, file downloading and other common operations
"""
from typing import Any, Dict, List, Optional, Callable
import json
import urllib.request
import urllib.error
import urllib.parse
import concurrent.futures
from .logger import get_logger
from src.version_info import APP_NAME, APP_VERSION

logger = get_logger().bind(component="HTTPUtils")

class HTTPUtils:
    """
    HTTP 網路請求工具類別，提供各種 HTTP 操作的統一介面
    """

    @staticmethod
    def _get_default_headers(
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
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

    @classmethod
    def get_json(
        cls, url: str, timeout: int = 10, headers: Optional[Dict[str, str]] = None
    ) -> Optional[Dict[str, Any]]:
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
            logger.error("HTTP GET JSON 請求失敗: URL 參數無效")
            return None
        timeout = max(10, timeout)

        try:
            final_headers = cls._get_default_headers(headers)
            req = urllib.request.Request(url, headers=final_headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = response.read()
                return json.loads(data)
        except Exception as e:
            logger.exception(f"HTTP GET JSON 請求失敗 ({url}): {e}")
            return None

    @classmethod
    def get_content(
        cls,
        url: str,
        timeout: int = 30,
        stream: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[bytes]:
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
            logger.error("HTTP GET 請求失敗: URL 參數無效")
            return None
        timeout = max(30, timeout)

        try:
            final_headers = cls._get_default_headers(headers)
            req = urllib.request.Request(url, headers=final_headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except Exception as e:
            logger.exception(f"HTTP GET 請求失敗 ({url}): {e}")
            return None

    @classmethod
    def download_file(
        cls, url: str, local_path: str, timeout: int = 60, chunk_size: int = 65536
    ) -> bool:
        """
        從指定 URL 下載檔案並儲存到本機路徑
        """
        return cls.download_file_with_progress(
            url, local_path, timeout=timeout, chunk_size=chunk_size
        )

    @classmethod
    def download_file_with_progress(
        cls,
        url: str,
        local_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        timeout: int = 60,
        chunk_size: int = 65536,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """
        下載檔案並回報進度
        progress_callback: (downloaded_bytes, total_bytes) -> None
        """
        if not url or not isinstance(url, str):
            logger.error("檔案下載失敗: URL 參數無效")
            return False
        if not local_path or not isinstance(local_path, str):
            logger.error("檔案下載失敗: 本地路徑參數無效")
            return False

        timeout = max(60, timeout)

        try:
            final_headers = cls._get_default_headers()
            req = urllib.request.Request(url, headers=final_headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded = 0

                with open(local_path, "wb") as f:
                    while True:
                        if cancel_check and cancel_check():
                            return False
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)
            return True
        except Exception as e:
            logger.exception(f"檔案下載失敗 ({url} -> {local_path}): {e}")
            return False

    @staticmethod
    def get_json_batch(
        urls: List[str],
        timeout: int = 10,
        headers: Optional[Dict[str, str]] = None,
        max_workers: int = 10,
    ) -> List[Optional[Dict[str, Any]]]:
        """
        批次發送 HTTP GET 請求並解析回傳的 JSON 資料
        """
        try:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(max_workers, len(urls))
            ) as executor:
                futures = [
                    executor.submit(HTTPUtils.get_json, url, timeout, headers)
                    for url in urls
                ]
                return [f.result() for f in futures]
        except Exception as e:
            logger.exception(f"批次 HTTP 請求失敗: {e}")
            return [None] * len(urls)

    @staticmethod
    async def get_json_batch_async(
        urls: List[str],
        timeout: int = 10,
        headers: Optional[Dict[str, str]] = None,
        max_workers: int = 10,
    ) -> List[Optional[Dict[str, Any]]]:
        """
        相容性包裝：使用 ThreadPoolExecutor 模擬 async 批次請求
        """
        return HTTPUtils.get_json_batch(urls, timeout, headers, max_workers)

# ====== 向後相容性函數別名 ======
# 提供向後相容的模組級別函數別名
get_json = HTTPUtils.get_json
get_content = HTTPUtils.get_content
download_file = HTTPUtils.download_file
get_json_batch = HTTPUtils.get_json_batch
get_json_batch_async = HTTPUtils.get_json_batch_async
