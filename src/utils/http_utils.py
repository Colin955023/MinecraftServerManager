#!/usr/bin/env python3
"""HTTP 網路請求工具模組
提供標準化的 HTTP 請求功能，包含 JSON 取得、檔案下載等常用操作
HTTP Network Request Utilities Module
Provides standardized HTTP request functionality including JSON retrieval, file downloading and other common operations
"""

import concurrent.futures
import contextlib
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from requests import RequestException
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.version_info import APP_NAME, APP_VERSION

from .logger import get_logger

logger = get_logger().bind(component="HTTPUtils")


class HTTPUtils:
    """HTTP 網路請求工具類別，提供各種 HTTP 操作的統一介面"""

    JSON_TIMEOUT_MIN_SECONDS = 10
    CONTENT_TIMEOUT_MIN_SECONDS = 30
    DOWNLOAD_TIMEOUT_MIN_SECONDS = 60
    MIN_CHUNK_SIZE = 1024

    RETRY_TOTAL = 3
    RETRY_CONNECT = 3
    RETRY_READ = 3
    RETRY_STATUS = 3
    RETRY_BACKOFF_FACTOR = 0.6
    RETRY_STATUS_FORCELIST = (429, 500, 502, 503, 504)
    RETRY_ALLOWED_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
    CONNECTION_POOL_SIZE = 16

    _thread_local = threading.local()

    @classmethod
    def get_timeout_retry_policy(cls) -> dict[str, Any]:
        """回傳目前 HTTP timeout/retry policy（供文件與診斷使用）。"""
        return {
            "json_timeout_min_seconds": cls.JSON_TIMEOUT_MIN_SECONDS,
            "content_timeout_min_seconds": cls.CONTENT_TIMEOUT_MIN_SECONDS,
            "download_timeout_min_seconds": cls.DOWNLOAD_TIMEOUT_MIN_SECONDS,
            "retry_total": cls.RETRY_TOTAL,
            "retry_connect": cls.RETRY_CONNECT,
            "retry_read": cls.RETRY_READ,
            "retry_status": cls.RETRY_STATUS,
            "retry_backoff_factor": cls.RETRY_BACKOFF_FACTOR,
            "retry_status_forcelist": list(cls.RETRY_STATUS_FORCELIST),
            "retry_allowed_methods": sorted(cls.RETRY_ALLOWED_METHODS),
        }

    @staticmethod
    def _normalize_int_value(value: int, minimum: int) -> int:
        """確保輸入為有效正整數，且不低於指定下限。"""
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            normalized = minimum
        return max(minimum, normalized)

    @classmethod
    def _build_retry(cls) -> Retry:
        """建立統一的 retry 設定。"""
        return Retry(
            total=cls.RETRY_TOTAL,
            connect=cls.RETRY_CONNECT,
            read=cls.RETRY_READ,
            status=cls.RETRY_STATUS,
            backoff_factor=cls.RETRY_BACKOFF_FACTOR,
            status_forcelist=cls.RETRY_STATUS_FORCELIST,
            allowed_methods=cls.RETRY_ALLOWED_METHODS,
            respect_retry_after_header=True,
        )

    @classmethod
    def _configure_session(cls, session: requests.Session) -> None:
        """套用統一的 adapter/retry policy。"""
        adapter = HTTPAdapter(
            max_retries=cls._build_retry(),
            pool_connections=cls.CONNECTION_POOL_SIZE,
            pool_maxsize=cls.CONNECTION_POOL_SIZE,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

    @classmethod
    def _get_session(cls) -> requests.Session:
        """取得目前執行緒專屬的 Session，避免跨執行緒共用。"""
        session = getattr(cls._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            cls._configure_session(session)
            cls._thread_local.session = session
        return session

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        """僅接受具備主機名稱的 http/https URL。"""
        try:
            parsed = urlparse(url)
        except ValueError:
            return False
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)

    @staticmethod
    def _get_default_headers(
        headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """獲取包含預設 User-Agent 的標頭"""
        default_headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION} (colin955023@gmail.com)"}
        if headers:
            default_headers.update(headers)
        return default_headers

    @classmethod
    def get_json(
        cls,
        url: str,
        timeout: int = 10,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """發送 HTTP GET 請求並解析回傳的 JSON 資料"""
        if not url or not isinstance(url, str) or not cls._is_valid_url(url):
            logger.error("HTTP GET JSON 請求失敗: URL 參數無效")
            return None
        timeout = cls._normalize_int_value(timeout, cls.JSON_TIMEOUT_MIN_SECONDS)

        try:
            final_headers = cls._get_default_headers(headers)
            resp = cls._get_session().get(url, headers=final_headers, params=params, timeout=timeout)
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
        """發送 HTTP GET 請求並回傳完整的回應內容"""
        if not url or not isinstance(url, str) or not cls._is_valid_url(url):
            logger.error("HTTP GET 請求失敗: URL 參數無效")
            return None
        timeout = cls._normalize_int_value(timeout, cls.CONTENT_TIMEOUT_MIN_SECONDS)

        try:
            final_headers = cls._get_default_headers(headers)
            resp = cls._get_session().get(url, headers=final_headers, timeout=timeout, stream=stream)
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
        """下載檔案並儲存到本機路徑"""
        if not url or not isinstance(url, str) or not cls._is_valid_url(url):
            logger.error("檔案下載失敗: URL 參數無效")
            return False
        if not local_path or not isinstance(local_path, str):
            logger.error("檔案下載失敗: 本地路徑參數無效")
            return False

        timeout = cls._normalize_int_value(timeout, cls.DOWNLOAD_TIMEOUT_MIN_SECONDS)
        chunk_size = cls._normalize_int_value(chunk_size, cls.MIN_CHUNK_SIZE)

        local_path_obj = Path(local_path)
        local_path_obj.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.NamedTemporaryFile(
                delete=False,
                prefix=local_path_obj.name + ".",
                suffix=".part",
                dir=local_path_obj.parent,
            ) as tmp_file:
                temp_path_obj = Path(tmp_file.name)
        except Exception:
            temp_path_obj = local_path_obj.with_name(local_path_obj.name + ".part")

        try:
            final_headers = cls._get_default_headers()
            with cls._get_session().get(
                url,
                headers=final_headers,
                timeout=timeout,
                stream=True,
            ) as resp:
                resp.raise_for_status()
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0

                with open(temp_path_obj, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if cancel_check and cancel_check():
                            if temp_path_obj.exists():
                                with contextlib.suppress(OSError):
                                    temp_path_obj.unlink()
                            return False
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)

            with contextlib.suppress(OSError):
                local_path_obj.unlink(missing_ok=True)
            temp_path_obj.replace(local_path_obj)
            return True
        except (RequestException, OSError) as e:
            logger.exception(f"檔案下載失敗 ({url} -> {local_path}): {e}")
            if temp_path_obj.exists():
                with contextlib.suppress(OSError):
                    temp_path_obj.unlink()
            return False

    @staticmethod
    def get_json_batch(
        urls: list[str],
        timeout: int = 10,
        headers: dict[str, str] | None = None,
        max_workers: int = 5,
    ) -> list[dict[str, Any] | None]:
        """批次發送 HTTP GET 請求並解析回傳的 JSON 資料"""
        if not urls:
            return []
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as executor:
                futures = [executor.submit(HTTPUtils.get_json, url, timeout, headers) for url in urls]
                return [f.result() for f in futures]
        except Exception as e:
            logger.exception(f"批次 HTTP 請求失敗: {e}")
            return [None] * len(urls)
