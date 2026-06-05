"""HTTP 網路請求工具模組
提供標準化的 HTTP 請求功能，包含 JSON 取得、檔案下載與通用重試策略等常用操作。
"""

import contextlib
import errno
import hashlib
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from requests import HTTPError, RequestException
from requests import exceptions as requests_exceptions
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ...version_info import APP_NAME, APP_VERSION, GITHUB_OWNER, GITHUB_REPO
from .. import get_logger
from ..runtime_utils.background_task import get_shared_manager
from ..runtime_utils.worker_pool import run_blocking_io

logger = get_logger().bind(component="HTTPUtils")


class RateLimiter:
    """簡單的本機頻率限制器（Token Bucket / 時間戳記延遲）。"""

    def __init__(self, calls_per_second: int = 10):
        self.delay = 1.0 / calls_per_second
        self.last_call_time: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, domain: str) -> None:
        """針對指定網域執行節流等待。

        Args:
            domain: 要限制請求頻率的網域名稱。
        """

        with self._lock:
            now = time.time()
            last = self.last_call_time.get(domain, 0.0)
            elapsed = now - last
            if elapsed < self.delay:
                sleep_time = self.delay - elapsed
                time.sleep(sleep_time)
                self.last_call_time[domain] = now + sleep_time
            else:
                self.last_call_time[domain] = now


_rate_limiter = RateLimiter(calls_per_second=10)  # 預設每秒 10 次


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
        except (TypeError, ValueError) as _:
            normalized = minimum
        return max(minimum, normalized)

    @classmethod
    def _configure_session(cls, session: requests.Session) -> None:
        """套用統一的 adapter/retry policy。"""
        adapter = HTTPAdapter(
            max_retries=Retry(
                total=cls.RETRY_TOTAL,
                connect=cls.RETRY_CONNECT,
                read=cls.RETRY_READ,
                status=cls.RETRY_STATUS,
                backoff_factor=cls.RETRY_BACKOFF_FACTOR,
                status_forcelist=cls.RETRY_STATUS_FORCELIST,
                allowed_methods=cls.RETRY_ALLOWED_METHODS,
                respect_retry_after_header=True,
            ),
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
    def _format_bytes(size: int) -> str:
        size = max(0, int(size))
        units = ["B", "KiB", "MiB", "GiB", "TiB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"

    @staticmethod
    def _describe_request_failure(exc: Exception) -> str:
        if isinstance(exc, HTTPError):
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code == 429:
                return "HTTP 429 Too Many Requests"
            if status_code is not None:
                if 500 <= int(status_code) < 600:
                    return f"HTTP {status_code} 伺服器錯誤"
                if status_code == 401:
                    return "HTTP 401 未授權"
                if status_code == 403:
                    return "HTTP 403 拒絕存取"
                if status_code == 404:
                    return "HTTP 404 找不到資源"
                return f"HTTP {status_code} 回應錯誤"
            return "HTTP 回應錯誤"
        if isinstance(exc, requests_exceptions.Timeout):
            return "請求逾時"
        if isinstance(exc, requests_exceptions.ConnectionError):
            return "無法建立網路連線"
        if isinstance(exc, requests_exceptions.TooManyRedirects):
            return "重新導向次數過多"
        if isinstance(exc, requests_exceptions.SSLError):
            return "SSL 驗證失敗"
        if isinstance(exc, ValueError):
            return "回應內容不是有效 JSON"
        if isinstance(exc, OSError):
            if getattr(exc, "errno", None) == errno.ENOSPC:
                return "磁碟空間不足"
            return f"I/O 錯誤: {exc}"
        return str(exc) or exc.__class__.__name__

    @staticmethod
    def get_default_headers(headers: dict[str, str] | None = None) -> dict[str, str]:
        """獲取包含預設 User-Agent 的標頭"""
        default_headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION} (github.com/{GITHUB_OWNER}/{GITHUB_REPO})"}
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
        suppress_status_codes: set[int] | None = None,
    ) -> dict[str, Any] | None:
        """發送 HTTP GET 請求並解析回傳的 JSON 資料。

        Args:
            url: 目標 URL。
            timeout: 請求逾時秒數。
            headers: 額外 HTTP headers。
            params: 查詢參數。
            suppress_status_codes: 需要靜默處理的 HTTP 狀態碼集合。

        Returns:
            成功時回傳 JSON 內容，失敗或被 suppress 時回傳 None。
        """
        if not url or not isinstance(url, str) or (not cls._is_valid_url(url)):
            logger.error("HTTP GET JSON 請求失敗: URL 參數無效")
            return None
        timeout = cls._normalize_int_value(timeout, cls.JSON_TIMEOUT_MIN_SECONDS)
        try:
            final_headers = cls.get_default_headers(headers)
            _rate_limiter.wait(urlparse(url).netloc)
            resp = cls._get_session().get(url, headers=final_headers, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except HTTPError as e:
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            if status_code is not None and status_code in (suppress_status_codes or set()):
                return None
            logger.exception(f"HTTP GET JSON 請求失敗 ({url}): {cls._describe_request_failure(e)}")
            return None
        except (RequestException, ValueError) as e:
            logger.exception(f"HTTP GET JSON 請求失敗 ({url}): {cls._describe_request_failure(e)}")
            return None

    @classmethod
    def post_json(
        cls,
        url: str,
        json_body: dict[str, Any],
        timeout: int = 10,
        headers: dict[str, str] | None = None,
        suppress_status_codes: set[int] | None = None,
    ) -> dict[str, Any] | list[Any] | None:
        """發送 HTTP POST 請求並解析回傳的 JSON 資料。

        Args:
            url: 目標 URL，必須為有效的 http/https 位址。
            json_body: 要送出的 JSON request body。
            timeout: 請求逾時秒數，會自動正規化為允許的最小值以上。
            headers: 額外 HTTP headers，會與預設 User-Agent 合併。
            suppress_status_codes: 指定需靜默處理的 HTTP 狀態碼集合。
                當回應狀態碼在此集合中時，函式回傳 None 並不記錄錯誤堆疊。

        Returns:
            成功時回傳 dict 或 list 型別的 JSON 內容；失敗或被 suppress 時回傳 None。
        """
        if not url or not isinstance(url, str) or (not cls._is_valid_url(url)):
            logger.error("HTTP POST JSON 請求失敗: URL 參數無效")
            return None
        timeout = cls._normalize_int_value(timeout, cls.JSON_TIMEOUT_MIN_SECONDS)
        try:
            final_headers = cls.get_default_headers(headers)
            _rate_limiter.wait(urlparse(url).netloc)
            resp = cls._get_session().post(url, headers=final_headers, json=json_body, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except HTTPError as e:
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            if status_code is not None and status_code in (suppress_status_codes or set()):
                return None
            logger.exception(f"HTTP POST JSON 請求失敗 ({url}): {cls._describe_request_failure(e)}")
            return None
        except (RequestException, ValueError) as e:
            logger.exception(f"HTTP POST JSON 請求失敗 ({url}): {cls._describe_request_failure(e)}")
            return None

    @classmethod
    def get_content(
        cls,
        url: str,
        timeout: int = 30,
        stream: bool = False,
        headers: dict[str, str] | None = None,
        log_errors: bool = True,
    ) -> bytes | None:
        """發送 HTTP GET 請求並回傳完整的回應內容。

        Args:
            url: 目標 URL。
            timeout: 請求逾時秒數。
            stream: 是否以串流方式請求。
            headers: 額外 HTTP headers。

        Returns:
            回應內容 bytes；失敗時回傳 None。
        """
        if not url or not isinstance(url, str) or (not cls._is_valid_url(url)):
            logger.error("HTTP GET 請求失敗: URL 參數無效")
            return None
        timeout = cls._normalize_int_value(timeout, cls.CONTENT_TIMEOUT_MIN_SECONDS)
        try:
            final_headers = cls.get_default_headers(headers)
            _rate_limiter.wait(urlparse(url).netloc)
            resp = cls._get_session().get(url, headers=final_headers, timeout=timeout, stream=stream)
            resp.raise_for_status()
            return resp.content
        except RequestException as e:
            if log_errors:
                logger.exception(f"HTTP GET 請求失敗 ({url}): {cls._describe_request_failure(e)}")
            else:
                logger.debug(f"HTTP GET 請求未成功 ({url}): {cls._describe_request_failure(e)}")
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
        expected_sha256: str | None = None,
        expected_hash: str | None = None,
        failure_message_callback: Callable[[str], None] | None = None,
    ) -> bool:
        """下載檔案並儲存到本機路徑。

        Args:
            url: 下載網址。
            local_path: 本機儲存路徑。
            progress_callback: 下載進度回呼。
            timeout: 逾時秒數。
            chunk_size: 每次讀取的區塊大小。
            cancel_check: 取消檢查回呼。
            expected_sha256: 預期的 SHA-256 雜湊。
            expected_hash: 預期的雜湊值，僅支援 sha256 / sha512。
            failure_message_callback: 可選的失敗原因回呼，用於回傳更具體的錯誤訊息。

        Returns:
            下載成功時回傳 True，失敗時回傳 False。
        """
        if not url or not isinstance(url, str) or (not cls._is_valid_url(url)):
            logger.error("檔案下載失敗: URL 參數無效")
            return False
        if not local_path or not isinstance(local_path, str):
            logger.error("檔案下載失敗: 本地路徑參數無效")
            return False
        timeout = cls._normalize_int_value(timeout, cls.DOWNLOAD_TIMEOUT_MIN_SECONDS)
        chunk_size = cls._normalize_int_value(chunk_size, cls.MIN_CHUNK_SIZE)
        local_path_obj = Path(local_path)
        local_path_obj.parents[0].mkdir(parents=True, exist_ok=True)
        normalized_expected_hash = str(expected_hash or expected_sha256 or "").strip().lower()
        expected_hash_algorithm = ""
        if normalized_expected_hash:
            if len(normalized_expected_hash) == 64:
                expected_hash_algorithm = "sha256"
            elif len(normalized_expected_hash) == 128:
                expected_hash_algorithm = "sha512"
            else:
                logger.error(f"檔案下載失敗: 僅接受 SHA-256 / SHA-512 預期雜湊 (len={len(normalized_expected_hash)})")
                return False
        # 若提供預期雜湊，先檢查本地檔案是否已符合，以避免重複下載
        if normalized_expected_hash and local_path_obj.exists():
            try:
                h = hashlib.new(expected_hash_algorithm)
                with local_path_obj.open("rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        h.update(chunk)
                if h.hexdigest().lower() == normalized_expected_hash:
                    # 直接回報完成（若有 progress callback，給予完成狀態）
                    if progress_callback:
                        try:
                            size = local_path_obj.stat().st_size
                            progress_callback(size, size)
                        except OSError as e:
                            logger.debug(f"progress_callback/stat failed: {e}")
                        except Exception as e:
                            logger.debug(f"progress_callback raised: {e}")
                    return True
            except OSError as e:
                logger.debug(f"檢查本地檔案雜湊失敗，將進行下載: {e}")
        try:
            with tempfile.NamedTemporaryFile(
                delete=False, prefix=local_path_obj.name + ".", suffix=".part", dir=local_path_obj.parents[0]
            ) as tmp_file:
                temp_path_obj = Path(tmp_file.name)
        except OSError:
            temp_path_obj = local_path_obj.with_name(local_path_obj.name + ".part")
        try:
            final_headers = cls.get_default_headers()
            _rate_limiter.wait(urlparse(url).netloc)
            with cls._get_session().get(url, headers=final_headers, timeout=timeout, stream=True) as resp:
                resp.raise_for_status()
                total_size = int(resp.headers.get("Content-Length", 0))
                if total_size > 0:
                    try:
                        free_space = shutil.disk_usage(local_path_obj.parent).free
                    except OSError as exc:
                        logger.debug(f"無法查詢目的地磁碟空間，略過預檢: {exc}")
                    else:
                        if free_space < total_size:
                            failure_message = (
                                f"磁碟空間不足：目的地 {local_path_obj.parent} 需要至少 {cls._format_bytes(total_size)}，"
                                f"目前剩餘 {cls._format_bytes(free_space)}。"
                            )
                            if failure_message_callback:
                                failure_message_callback(failure_message)
                            logger.error(f"檔案下載失敗 ({url} -> {local_path}): {failure_message}")
                            return False
                downloaded = 0
                hasher = hashlib.new(expected_hash_algorithm) if normalized_expected_hash else None
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
                        if hasher is not None:
                            hasher.update(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)
                if normalized_expected_hash and hasher is not None:
                    computed = hasher.hexdigest().lower()
                    if computed != normalized_expected_hash:
                        failure_message = f"下載檔案雜湊驗證失敗：預期 {expected_hash_algorithm.upper()} 不符。"
                        if failure_message_callback:
                            failure_message_callback(failure_message)
                        logger.error(
                            f"下載檔案的雜湊不符: algorithm={expected_hash_algorithm} expected={normalized_expected_hash} computed={computed}"
                        )
                        with contextlib.suppress(OSError):
                            if temp_path_obj.exists():
                                temp_path_obj.unlink()
                        return False
            temp_path_obj.replace(local_path_obj)
            try:
                fd = os.open(str(local_path_obj.parents[0]), os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except OSError as e:
                logger.debug(f"目錄 fsync 失敗 (path={local_path_obj.parents[0]}): {e}")
            return True
        except (RequestException, OSError) as e:
            failure_message = cls._describe_request_failure(e)
            if failure_message_callback:
                failure_message_callback(failure_message)
            logger.exception(f"檔案下載失敗 ({url} -> {local_path}): {failure_message}")
            if temp_path_obj.exists():
                with contextlib.suppress(OSError):
                    temp_path_obj.unlink()
            return False

    @staticmethod
    def get_json_batch(
        urls: list[str], timeout: int = 10, headers: dict[str, str] | None = None, max_workers: int = 5
    ) -> list[dict[str, Any] | None]:
        """批次發送 HTTP GET 請求並解析回傳的 JSON 資料。

        Args:
            urls: 要請求的 URL 清單。
            timeout: 請求逾時秒數。
            headers: 額外 HTTP headers。
            max_workers: 同時執行的工作數量。

        Returns:
            對應每個 URL 的 JSON 結果清單。
        """
        if not urls:
            return []
        try:
            batch_size = max(1, min(int(max_workers or 1), len(urls)))
            manager = get_shared_manager()
            results: list[dict[str, Any] | None] = []
            for start in range(0, len(urls), batch_size):
                batch = urls[start : start + batch_size]
                futures = [manager.run(HTTPUtils.get_json, url, timeout, headers) for url in batch]
                results.extend(future.result() for future in futures)
            return results
        except Exception as e:
            logger.exception(f"批次 HTTP 請求失敗: {e}")
            return [None] * len(urls)

    @classmethod
    async def get_json_async(cls, *args, **kwargs):
        """使用共用 requests 實作在線程中取得 JSON 回應。"""

        return await run_blocking_io(cls.get_json, *args, **kwargs)

    @classmethod
    async def post_json_async(cls, *args, **kwargs):
        """使用共用 requests 實作在線程中送出 JSON POST 請求。"""

        return await run_blocking_io(cls.post_json, *args, **kwargs)

    @classmethod
    async def get_content_async(cls, *args, **kwargs):
        """使用共用 requests 實作在線程中取得完整回應內容。"""

        return await run_blocking_io(cls.get_content, *args, **kwargs)

    @classmethod
    async def download_file_async(cls, *args, **kwargs):
        """使用共用 requests 實作在線程中下載檔案。"""

        return await run_blocking_io(cls.download_file, *args, **kwargs)
