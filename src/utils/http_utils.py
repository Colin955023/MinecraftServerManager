#!/usr/bin/env python3
"""HTTP 網路請求工具模組
提供標準化的 HTTP 請求功能，包含 JSON 取得、檔案下載等常用操作
HTTP Network Request Utilities Module
Provides standardized HTTP request functionality including JSON retrieval, file downloading and other common operations
"""

import concurrent.futures
from typing import Any, Callable

import requests
from requests import RequestException

from src.version_info import APP_NAME, APP_VERSION

from .logger import get_logger

logger = get_logger().bind(component="HTTPUtils")


class HTTPUtils:
    """HTTP 網路請求工具類別，提供各種 HTTP 操作的統一介面"""

    @staticmethod
    def _get_default_headers(
        headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """獲取包含預設 User-Agent 的標頭
        Get headers with default User-Agent
        """
        default_headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION} (colin955023@gmail.com)"}
        if headers:
            default_headers.update(headers)
        return default_headers

    @classmethod
    def get_json(cls, url: str, timeout: int = 10, headers: dict[str, str] | None = None) -> dict[str, Any] | None:
        """發送 HTTP GET 請求並解析回傳的 JSON 資料（使用連線池）
        Send HTTP GET request and parse returned JSON data (with connection pooling)

        Args:
            url (str): 請求的目標 URL
            timeout (int): 請求超時時間（秒）
            headers (Dict[str, str] | None): 可選的 HTTP 請求標頭

        Returns:
            Dict[str, Any] | None: 成功時返回 JSON 字典，失敗時返回 None

        """
        if not url or not isinstance(url, str):
            logger.error("HTTP GET JSON 請求失敗: URL 參數無效")
            return None
        timeout = max(10, timeout)

        try:
            final_headers = cls._get_default_headers(headers)
            resp = requests.get(url, headers=final_headers, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except (RequestException, ValueError) as e:
            logger.exception(f"HTTP GET JSON 請求失敗 ({url}): {e}")
            return None

    @classmethod
    def get_content(
        cls,
        url: str,
        timeout: int = 30,
        stream: bool = False,
        headers: dict[str, str] | None = None,
    ) -> bytes | None:
        """發送 HTTP GET 請求並回傳完整的回應內容（使用連線池）
        Send HTTP GET request and return complete response content (with connection pooling)

        Args:
            url (str): 請求的目標 URL
            timeout (int): 請求超時時間（秒）
            stream (bool): 是否使用串流模式下載
            headers (Dict[str, str] | None): 可選的 HTTP 請求標頭

        Returns:
            bytes | None: 成功時返回回應內容位元組，失敗時返回 None

        """
        if not url or not isinstance(url, str):
            logger.error("HTTP GET 請求失敗: URL 參數無效")
            return None
        timeout = max(30, timeout)

        try:
            final_headers = cls._get_default_headers(headers)
            resp = requests.get(url, headers=final_headers, timeout=timeout, stream=stream)
            resp.raise_for_status()
            return resp.content
        except RequestException as e:
            logger.exception(f"HTTP GET 請求失敗 ({url}): {e}")
            return None

    @classmethod
    def download_file(
        cls,
        url: str,
        local_path: str,
        progress_callback: Callable[[int, int], None] | None = None,
        timeout: int = 60,
        chunk_size: int = 65536,
        cancel_check: Callable[[], bool] | None = None,
    ) -> bool:
        """下載檔案並儲存到本機路徑
        Download file from URL and save to local path

        Args:
            url: 下載 URL
            local_path: 本機儲存路徑
            progress_callback: 進度回調函數 (downloaded_bytes, total_bytes) -> None
            timeout: 超時時間（秒）
            chunk_size: 區塊大小
            cancel_check: 取消檢查函數，返回 True 則取消下載

        Returns:
            bool: 下載成功返回 True
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
            with requests.get(
                url,
                headers=final_headers,
                timeout=timeout,
                stream=True,
            ) as resp:
                resp.raise_for_status()
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0

                with open(local_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if cancel_check and cancel_check():
                            return False
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)
            return True
        except RequestException as e:
            logger.exception(f"檔案下載失敗 ({url} -> {local_path}): {e}")
            return False

    @staticmethod
    def get_json_batch(
        urls: list[str],
        timeout: int = 10,
        headers: dict[str, str] | None = None,
        max_workers: int = 5,
    ) -> list[dict[str, Any] | None]:
        """批次發送 HTTP GET 請求並解析回傳的 JSON 資料"""
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as executor:
                futures = [executor.submit(HTTPUtils.get_json, url, timeout, headers) for url in urls]
                return [f.result() for f in futures]
        except Exception as e:
            logger.exception(f"批次 HTTP 請求失敗: {e}")
            return [None] * len(urls)


# ====== 向後相容性函數別名 ======
# 提供向後相容的模組級別函數別名
get_json = HTTPUtils.get_json
get_content = HTTPUtils.get_content
download_file = HTTPUtils.download_file
get_json_batch = HTTPUtils.get_json_batch
