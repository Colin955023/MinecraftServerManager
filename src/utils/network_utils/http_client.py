"""HTTPX 網路用戶端與下載工具"""

from __future__ import annotations

import errno
import hashlib
import hmac
import ipaddress
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import orjson

from src.models import HTTPJSONResponse
from src.utils import (
    APP_NAME,
    APP_VERSION,
    GITHUB_OWNER,
    GITHUB_REPO,
    HashUtils,
    NetworkSecurityError,
    PathUtils,
    ResponseTooLargeError,
    format_bytes,
    get_logger,
)

logger = get_logger().bind(component="HTTPClient")

type JSONValue = dict[str, Any] | list[Any]


class HTTPClient:
    """專案唯一的同步 HTTP client，供 Qt 背景工作執行緒共用"""

    JSON_TIMEOUT_MIN_SECONDS = 10
    CONTENT_TIMEOUT_MIN_SECONDS = 30
    DOWNLOAD_TIMEOUT_MIN_SECONDS = 60
    MIN_CHUNK_SIZE = 1024

    MAX_JSON_RESPONSE_BYTES = 16 * 1024 * 1024
    MAX_CONTENT_RESPONSE_BYTES = 64 * 1024 * 1024
    MAX_REDIRECTS = 10

    RETRY_TOTAL = 3
    RETRY_BACKOFF_FACTOR = 0.6
    RETRY_MAX_DELAY_SECONDS = 60.0
    RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
    RETRY_ALLOWED_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

    CONNECTION_POOL_SIZE = 32
    KEEPALIVE_POOL_SIZE = 16
    KEEPALIVE_EXPIRY_SECONDS = 30.0
    POOL_TIMEOUT_SECONDS = 5.0
    CONNECT_TIMEOUT_SECONDS = 10.0
    WRITE_TIMEOUT_SECONDS = 15.0

    _client: httpx.Client | None = None
    _client_lock = threading.Lock()

    @classmethod
    def _normalize_positive_int(cls, value: int, minimum: int) -> int:
        try:
            normalized = int(value)
            return max(minimum, normalized)
        except TypeError, ValueError:
            return minimum

    @classmethod
    @lru_cache(maxsize=16)
    def _make_timeout(cls, timeout: int) -> httpx.Timeout:
        timeout_value = float(timeout)
        return httpx.Timeout(
            timeout_value,
            connect=min(timeout_value, cls.CONNECT_TIMEOUT_SECONDS),
            read=timeout_value,
            write=min(timeout_value, cls.WRITE_TIMEOUT_SECONDS),
            pool=min(timeout_value, cls.POOL_TIMEOUT_SECONDS),
        )

    @classmethod
    def _create_client(cls) -> httpx.Client:
        return httpx.Client(
            headers={"User-Agent": f"{APP_NAME}/{APP_VERSION} (github.com/{GITHUB_OWNER}/{GITHUB_REPO})"},
            http2=True,
            follow_redirects=False,
            verify=True,
            trust_env=False,
            limits=httpx.Limits(
                max_connections=cls.CONNECTION_POOL_SIZE,
                max_keepalive_connections=cls.KEEPALIVE_POOL_SIZE,
                keepalive_expiry=cls.KEEPALIVE_EXPIRY_SECONDS,
            ),
        )

    @classmethod
    def _get_client(cls) -> httpx.Client:
        client = cls._client
        if client is not None and not client.is_closed:
            return client

        with cls._client_lock:
            client = cls._client
            if client is None or client.is_closed:
                client = cls._create_client()
                cls._client = client
            return client

    @classmethod
    def close(cls) -> None:
        """關閉共用連線池；應在背景工作池停止後呼叫"""
        with cls._client_lock:
            client = cls._client
            cls._client = None
        if client is not None and not client.is_closed:
            client.close()

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        """只允許外部 HTTPS URL，拒絕 credential、localhost 與非公開 IP literal"""
        try:
            parsed = httpx.URL(url)
            hostname = (parsed.host or "").rstrip(".").lower()
            port = parsed.port
        except TypeError, ValueError, httpx.InvalidURL:
            return False

        if parsed.scheme.lower() != "https" or not hostname:
            return False
        if parsed.userinfo:
            return False
        if hostname == "localhost" or hostname.endswith(".localhost"):
            return False
        if port is not None and not 1 <= port <= 65535:
            return False

        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return True
        return address.is_global

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int | None]:
        parsed = urlsplit(url)
        return parsed.scheme.lower(), (parsed.hostname or "").rstrip(".").lower(), parsed.port

    @classmethod
    def _redirect_headers(
        cls, headers: dict[str, str] | None, source_url: str, destination_url: str
    ) -> dict[str, str] | None:
        if not headers or cls._origin(source_url) == cls._origin(destination_url):
            return headers
        sensitive = {"authorization", "cookie", "proxy-authorization"}
        return {key: value for key, value in headers.items() if key.lower() not in sensitive}

    @staticmethod
    def _safe_url_for_log(url: str) -> str:
        """移除 URL credential、query 與 fragment，避免 signed URL/token 寫入 log"""
        try:
            parsed = urlsplit(str(url))
            hostname = parsed.hostname or ""
            if not hostname:
                return "<invalid-url>"
            if ":" in hostname and not hostname.startswith("["):
                hostname = f"[{hostname}]"
            netloc = hostname
            if parsed.port is not None:
                netloc = f"{netloc}:{parsed.port}"
            return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
        except TypeError, ValueError:
            return "<invalid-url>"

    @staticmethod
    def _describe_request_failure(exc: Exception) -> str:
        if isinstance(exc, NetworkSecurityError):
            return str(exc) or "請求因安全策略被拒絕"
        if isinstance(exc, ResponseTooLargeError):
            return str(exc) or "HTTP 回應過大"
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            if status_code == 429:
                return "HTTP 429 請求過多"
            if 500 <= status_code < 600:
                return f"HTTP {status_code} 伺服器錯誤"
            if status_code == 401:
                return "HTTP 401 未授權"
            if status_code == 403:
                return "HTTP 403 拒絕存取"
            if status_code == 404:
                return "HTTP 404 找不到資源"
            return f"HTTP {status_code} 回應錯誤"
        if isinstance(exc, httpx.TimeoutException):
            return "請求逾時"
        if isinstance(exc, httpx.ConnectError):
            return "無法建立網路連線"
        if isinstance(exc, httpx.TransportError):
            return "網路傳輸失敗"
        if isinstance(exc, orjson.JSONDecodeError):
            return "回應內容不是有效 JSON"
        if isinstance(exc, OSError):
            if getattr(exc, "errno", None) == errno.ENOSPC:
                return "磁碟空間不足"
            return f"I/O 錯誤: {exc}"
        return str(exc) or exc.__class__.__name__

    @classmethod
    def _retry_delay_seconds(cls, response: httpx.Response | None, retry_index: int) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After", "").strip()
            if retry_after:
                try:
                    return min(cls.RETRY_MAX_DELAY_SECONDS, max(0.0, float(retry_after)))
                except ValueError:
                    with suppress(TypeError, ValueError, OverflowError):
                        retry_at = parsedate_to_datetime(retry_after)
                        if retry_at.tzinfo is not None:
                            return min(cls.RETRY_MAX_DELAY_SECONDS, max(0.0, retry_at.timestamp() - time.time()))
        delay = cls.RETRY_BACKOFF_FACTOR * (2 ** max(0, retry_index - 1))
        return min(cls.RETRY_MAX_DELAY_SECONDS, delay)

    @classmethod
    def _send_stream_once(
        cls,
        method: str,
        url: str,
        *,
        timeout: int,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        method = method.upper()
        current_url = url
        current_headers = headers

        for redirect_count in range(cls.MAX_REDIRECTS + 1):
            if not cls._is_valid_url(current_url):
                raise NetworkSecurityError("拒絕非 HTTPS、本機/私有 IP 或含 credential 的 URL")

            client = cls._get_client()
            request = client.build_request(
                method,
                current_url,
                headers=current_headers,
                params=params,
                json=json_body,
                timeout=cls._make_timeout(timeout),
            )
            response = client.send(request, stream=True, follow_redirects=False)
            if not response.is_redirect:
                return response

            location = response.headers.get("Location", "").strip()
            if not location:
                return response
            if method not in cls.RETRY_ALLOWED_METHODS:
                response.close()
                raise NetworkSecurityError(f"拒絕自動跟隨 {method} 重新導向")
            if redirect_count >= cls.MAX_REDIRECTS:
                response.close()
                raise NetworkSecurityError("重新導向次數超過安全上限")

            source_url = str(response.url)
            next_url = urljoin(source_url, location)
            response.close()
            if not cls._is_valid_url(next_url):
                raise NetworkSecurityError("重新導向目的地不符合 HTTPS/外部網路安全策略")

            current_headers = cls._redirect_headers(current_headers, source_url, next_url)
            current_url = next_url
            params = None

        raise NetworkSecurityError("重新導向處理異常")

    @classmethod
    def _open_stream(
        cls,
        method: str,
        url: str,
        *,
        timeout: int,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        method = method.upper()
        max_attempts = cls.RETRY_TOTAL + 1 if method in cls.RETRY_ALLOWED_METHODS else 1

        for attempt in range(1, max_attempts + 1):
            try:
                response = cls._send_stream_once(
                    method,
                    url,
                    timeout=timeout,
                    headers=headers,
                    params=params,
                    json_body=json_body,
                )
            except httpx.TransportError:
                if attempt >= max_attempts:
                    raise
                time.sleep(cls._retry_delay_seconds(None, attempt))
                continue

            if response.status_code not in cls.RETRY_STATUS_CODES or attempt >= max_attempts:
                return response

            delay = cls._retry_delay_seconds(response, attempt)
            response.close()
            time.sleep(delay)

        raise RuntimeError("HTTP stream retry loop terminated unexpectedly")

    @classmethod
    def _read_limited(cls, response: httpx.Response, max_bytes: int) -> bytes:
        content_length = response.headers.get("Content-Length", "").strip()
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = 0
            if declared_size > max_bytes:
                raise ResponseTooLargeError(f"HTTP 回應宣告大小超過上限 {format_bytes(max_bytes)}")

        payload = bytearray()
        for chunk in response.iter_bytes(chunk_size=65536):
            if len(payload) + len(chunk) > max_bytes:
                raise ResponseTooLargeError(f"HTTP 解碼後內容超過上限 {format_bytes(max_bytes)}")
            payload.extend(chunk)
        return bytes(payload)

    @staticmethod
    def _cleanup_temp_file(temp_path: Path | None) -> None:
        if temp_path is None:
            return
        with suppress(OSError):
            if temp_path.exists():
                temp_path.unlink()

    @classmethod
    def _report_download_failure(
        cls,
        *,
        url: str,
        local_path: str,
        message: str,
        failure_message_callback: Callable[[str], None] | None = None,
        exc: Exception | None = None,
        log_message: str | None = None,
    ) -> None:
        if failure_message_callback:
            try:
                failure_message_callback(message)
            except Exception:
                logger.exception("下載失敗訊息 callback 執行失敗")
        safe_url = cls._safe_url_for_log(url)
        final_log_message = log_message or f"檔案下載失敗 ({safe_url} -> {local_path}): {message}"
        if exc is None:
            logger.error(final_log_message)
        else:
            logger.exception(final_log_message)

    @staticmethod
    def _resolve_expected_hash_algorithm(expected_hash: str, algorithm: str | None = None) -> str:
        if algorithm:
            normalized = str(algorithm).strip().lower().replace("-", "")
            if normalized in hashlib.algorithms_available:
                return normalized
        if not expected_hash:
            return ""
        return {40: "sha1", 64: "sha256", 128: "sha512"}.get(len(expected_hash), "")

    @classmethod
    def _existing_file_matches_hash(
        cls,
        local_path: Path,
        *,
        expected_hash: str,
        expected_hash_algorithm: str,
        progress_callback: Callable[[int, int], None] | None,
    ) -> bool:
        computed_hash = HashUtils.compute_file_hash_sync(local_path, expected_hash_algorithm)
        if not computed_hash or not hmac.compare_digest(computed_hash.lower(), expected_hash):
            return False
        if progress_callback:
            try:
                size = local_path.stat().st_size
                progress_callback(size, size)
            except OSError as exc:
                logger.debug(f"progress_callback/stat failed: {exc}")
        return True

    @classmethod
    def _read_content_with_retry(
        cls,
        method: str,
        url: str,
        *,
        timeout: int,
        max_bytes: int,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        suppress_status_codes: set[int] | None = None,
    ) -> bytes | None:
        method = method.upper()
        max_attempts = cls.RETRY_TOTAL + 1 if method in cls.RETRY_ALLOWED_METHODS else 1
        for attempt in range(1, max_attempts + 1):
            response: httpx.Response | None = None
            try:
                response = cls._send_stream_once(
                    method,
                    url,
                    timeout=timeout,
                    headers=headers,
                    params=params,
                    json_body=json_body,
                )
                if response.status_code in (suppress_status_codes or set()):
                    return None
                if response.status_code in cls.RETRY_STATUS_CODES and attempt < max_attempts:
                    delay = cls._retry_delay_seconds(response, attempt)
                    response.close()
                    response = None
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                return cls._read_limited(response, max_bytes)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (suppress_status_codes or set()):
                    return None
                if exc.response.status_code in cls.RETRY_STATUS_CODES and attempt < max_attempts:
                    delay = cls._retry_delay_seconds(exc.response, attempt)
                    time.sleep(delay)
                    continue
                if attempt >= max_attempts:
                    raise
            except httpx.TransportError:
                if attempt >= max_attempts:
                    raise
                time.sleep(cls._retry_delay_seconds(None, attempt))
                continue
            finally:
                if response is not None:
                    response.close()
        raise RuntimeError("HTTP retry loop terminated unexpectedly")

    @classmethod
    def _request_json_value(
        cls,
        method: str,
        url: str,
        *,
        timeout: int,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        suppress_status_codes: set[int] | None = None,
    ) -> JSONValue | None:
        """集中處理 GET／POST JSON 的安全驗證、解析與錯誤記錄"""
        normalized_method = method.upper()
        if not url or not isinstance(url, str) or not cls._is_valid_url(url):
            logger.error(f"HTTP {normalized_method} JSON 請求失敗: URL 參數無效或不符合 HTTPS 安全策略")
            return None
        normalized_timeout = cls._normalize_positive_int(timeout, cls.JSON_TIMEOUT_MIN_SECONDS)
        safe_url = cls._safe_url_for_log(url)
        try:
            raw_bytes = cls._read_content_with_retry(
                normalized_method,
                url,
                timeout=normalized_timeout,
                max_bytes=cls.MAX_JSON_RESPONSE_BYTES,
                headers=headers,
                params=params,
                json_body=json_body,
                suppress_status_codes=suppress_status_codes,
            )
            if raw_bytes is None:
                return None
            payload = orjson.loads(raw_bytes)
            return payload if isinstance(payload, dict | list) else None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (suppress_status_codes or set()):
                return None
            logger.warning(f"HTTP {normalized_method} JSON 請求失敗 ({safe_url}): {cls._describe_request_failure(exc)}")
        except (httpx.RequestError, NetworkSecurityError, ResponseTooLargeError, orjson.JSONDecodeError) as exc:
            logger.warning(f"HTTP {normalized_method} JSON 請求失敗 ({safe_url}): {cls._describe_request_failure(exc)}")
        return None

    @classmethod
    def fetch_json(
        cls,
        url: str,
        timeout: int = 10,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        suppress_status_codes: set[int] | None = None,
    ) -> JSONValue | None:
        """
        發送 HTTP GET 請求並解析 JSON 回應

        Args:
            url: 請求的 URL
            timeout: 請求逾時秒數
            headers: 額外的 HTTP 標頭
            params: URL 查詢參數
            suppress_status_codes: 要忽略的 HTTP 狀態碼集合，這些狀態碼不會觸發例外或錯誤日誌

        Returns:
            解析後的 JSON 資料，失敗時回傳 None
        """
        return cls._request_json_value(
            "GET",
            url,
            timeout=timeout,
            headers=headers,
            params=params,
            suppress_status_codes=suppress_status_codes,
        )

    @classmethod
    def fetch_json_response(
        cls,
        url: str,
        timeout: int = 10,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> HTTPJSONResponse:
        """
        取得不丟失 status code 的 JSON 結果，讓上層 adapter 能區分失敗種類

        Args:
            url: 符合 HTTPS policy 的請求網址
            timeout: 請求逾時秒數
            headers: 額外的 HTTP 標頭
            params: URL 查詢參數

        Returns:
            保留狀態碼、payload 與錯誤類型的回應模型
        """
        if not url or not isinstance(url, str) or not cls._is_valid_url(url):
            return HTTPJSONResponse(None, error_kind="invalid_request")
        timeout = cls._normalize_positive_int(timeout, cls.JSON_TIMEOUT_MIN_SECONDS)
        max_attempts = cls.RETRY_TOTAL + 1
        for attempt in range(1, max_attempts + 1):
            response: httpx.Response | None = None
            try:
                response = cls._send_stream_once("GET", url, timeout=timeout, headers=headers, params=params)
                status_code = response.status_code
                if status_code in cls.RETRY_STATUS_CODES and attempt < max_attempts:
                    delay = cls._retry_delay_seconds(response, attempt)
                    response.close()
                    response = None
                    time.sleep(delay)
                    continue
                if status_code == 404:
                    return HTTPJSONResponse(status_code, error_kind="not_found")
                if status_code == 429:
                    return HTTPJSONResponse(status_code, error_kind="rate_limited")
                if status_code >= 400:
                    return HTTPJSONResponse(
                        status_code, error_kind="transient" if status_code >= 500 else "invalid_request"
                    )
                raw_bytes = cls._read_limited(response, cls.MAX_JSON_RESPONSE_BYTES)
                try:
                    payload = orjson.loads(raw_bytes)
                except orjson.JSONDecodeError:
                    return HTTPJSONResponse(status_code, error_kind="invalid_response")
                if not isinstance(payload, dict | list):
                    return HTTPJSONResponse(status_code, error_kind="invalid_response")
                return HTTPJSONResponse(status_code, payload=payload)
            except httpx.TimeoutException:
                if attempt >= max_attempts:
                    return HTTPJSONResponse(None, error_kind="timeout")
            except httpx.TransportError:
                if attempt >= max_attempts:
                    return HTTPJSONResponse(None, error_kind="transient")
            except NetworkSecurityError, ResponseTooLargeError:
                return HTTPJSONResponse(None, error_kind="invalid_response")
            finally:
                if response is not None:
                    response.close()
            time.sleep(cls._retry_delay_seconds(None, attempt))
        return HTTPJSONResponse(None, error_kind="transient")

    @classmethod
    def post_json(
        cls,
        url: str,
        json_body: dict[str, Any],
        timeout: int = 10,
        headers: dict[str, str] | None = None,
        suppress_status_codes: set[int] | None = None,
    ) -> JSONValue | None:
        """
        發送 HTTP POST 請求並解析 JSON 回應

        Args:
            url: 請求的 URL
            json_body: 要傳送的 JSON 主體
            timeout: 請求逾時秒數
            headers: 額外的 HTTP 標頭
            suppress_status_codes: 要忽略的 HTTP 狀態碼集合，這些狀態碼不會觸發例外或錯誤日誌

        Returns:
            解析後的 JSON 資料，失敗時回傳 None
        """
        return cls._request_json_value(
            "POST",
            url,
            timeout=timeout,
            headers=headers,
            json_body=json_body,
            suppress_status_codes=suppress_status_codes,
        )

    @classmethod
    def fetch_bytes(
        cls,
        url: str,
        timeout: int = 30,
        headers: dict[str, str] | None = None,
        log_errors: bool = True,
    ) -> bytes | None:
        """
        發送 HTTP GET 請求並取得回應內容（限制最大回應大小）

        Args:
            url: 請求的 URL
            timeout: 請求逾時秒數
            headers: 額外的 HTTP 標頭
            log_errors: 是否記錄錯誤日誌

        Returns:
            回應內容，失敗時回傳 None
        """
        if not url or not isinstance(url, str) or not cls._is_valid_url(url):
            logger.error("HTTP GET 請求失敗: URL 參數無效或不符合 HTTPS 安全策略")
            return None
        timeout = cls._normalize_positive_int(timeout, cls.CONTENT_TIMEOUT_MIN_SECONDS)
        safe_url = cls._safe_url_for_log(url)
        try:
            return cls._read_content_with_retry(
                "GET",
                url,
                timeout=timeout,
                max_bytes=cls.MAX_CONTENT_RESPONSE_BYTES,
                headers=headers,
            )
        except (httpx.HTTPError, NetworkSecurityError, ResponseTooLargeError) as exc:
            if log_errors:
                logger.exception(f"HTTP GET 請求失敗 ({safe_url}): {cls._describe_request_failure(exc)}")
            else:
                logger.debug(f"HTTP GET 請求未成功 ({safe_url}): {cls._describe_request_failure(exc)}")
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
        expected_hash_algorithm: str | None = None,
        failure_message_callback: Callable[[str], None] | None = None,
    ) -> bool:
        """
        下載檔案到指定路徑，支援進度回呼、取消檢查與雜湊驗證

        Args:
            url: 要下載的檔案 URL
            local_path: 本地儲存路徑
            progress_callback: 進度回呼函式
            timeout: 下載逾時秒數
            chunk_size: 下載區塊大小
            cancel_check: 取消檢查函式
            expected_sha256: 預期的 SHA256 雜湊值
            expected_hash: 預期的雜湊值
            expected_hash_algorithm: 預期的雜湊演算法
            failure_message_callback: 失敗訊息回呼函式

        Returns:
            下載成功回傳 True，失敗回傳 False
        """
        if not url or not isinstance(url, str) or not cls._is_valid_url(url):
            cls._report_download_failure(
                url=str(url),
                local_path=str(local_path),
                message="URL 參數無效或不符合 HTTPS 安全策略",
                failure_message_callback=failure_message_callback,
            )
            return False
        if not local_path or not isinstance(local_path, str):
            cls._report_download_failure(
                url=url,
                local_path=str(local_path),
                message="本地路徑參數無效",
                failure_message_callback=failure_message_callback,
            )
            return False

        timeout = cls._normalize_positive_int(timeout, cls.DOWNLOAD_TIMEOUT_MIN_SECONDS)
        chunk_size = cls._normalize_positive_int(chunk_size, cls.MIN_CHUNK_SIZE)
        local_path_obj = Path(local_path)
        local_path_obj.parent.mkdir(parents=True, exist_ok=True)

        normalized_expected_hash = str(expected_hash or expected_sha256 or "").strip().lower()
        resolved_hash_algorithm = cls._resolve_expected_hash_algorithm(
            normalized_expected_hash,
            expected_hash_algorithm,
        )
        if normalized_expected_hash and not resolved_hash_algorithm:
            cls._report_download_failure(
                url=url,
                local_path=local_path,
                message=f"預期雜湊演算法無效 (len={len(normalized_expected_hash)})",
                failure_message_callback=failure_message_callback,
            )
            return False

        if (
            normalized_expected_hash
            and local_path_obj.exists()
            and cls._existing_file_matches_hash(
                local_path_obj,
                expected_hash=normalized_expected_hash,
                expected_hash_algorithm=resolved_hash_algorithm,
                progress_callback=progress_callback,
            )
        ):
            return True

        temp_path_obj: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                delete=False,
                prefix=local_path_obj.name + ".",
                suffix=".part",
                dir=local_path_obj.parent,
            ) as tmp_file:
                temp_path_obj = Path(tmp_file.name)
        except OSError:
            temp_path_obj = local_path_obj.with_name(local_path_obj.name + ".part")

        for attempt in range(1, cls.RETRY_TOTAL + 1):
            response: httpx.Response | None = None
            try:
                response = cls._open_stream("GET", url, timeout=timeout)
                response.raise_for_status()
                total_size = int(response.headers.get("Content-Length", 0) or 0)

                if total_size > 0:
                    try:
                        free_space = shutil.disk_usage(local_path_obj.parent).free
                    except OSError as exc:
                        logger.debug(f"無法查詢目的地磁碟空間，略過預檢: {exc}")
                    else:
                        if free_space < total_size:
                            failure_message = (
                                f"磁碟空間不足：目的地 {local_path_obj.parent} 需要至少 {format_bytes(total_size)}，"
                                f"目前剩餘 {format_bytes(free_space)}"
                            )
                            cls._report_download_failure(
                                url=url,
                                local_path=local_path,
                                message=failure_message,
                                failure_message_callback=failure_message_callback,
                            )
                            cls._cleanup_temp_file(temp_path_obj)
                            return False

                downloaded = 0
                hasher = hashlib.new(resolved_hash_algorithm) if normalized_expected_hash else None
                with temp_path_obj.open("wb") as file_obj:
                    for chunk in response.iter_bytes(chunk_size=chunk_size):
                        if cancel_check and cancel_check():
                            cls._report_download_failure(
                                url=url,
                                local_path=local_path,
                                message="下載已取消",
                                failure_message_callback=failure_message_callback,
                            )
                            cls._cleanup_temp_file(temp_path_obj)
                            return False
                        if not chunk:
                            continue
                        file_obj.write(chunk)
                        if hasher is not None:
                            hasher.update(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)

                if normalized_expected_hash and hasher is not None:
                    computed = hasher.hexdigest().lower()
                    if not hmac.compare_digest(computed, normalized_expected_hash):
                        cls._report_download_failure(
                            url=url,
                            local_path=local_path,
                            message=f"下載檔案雜湊驗證失敗：預期 {resolved_hash_algorithm.upper()} 不符",
                            failure_message_callback=failure_message_callback,
                            log_message=(
                                f"下載檔案的雜湊不符: algorithm={resolved_hash_algorithm} "
                                f"expected={normalized_expected_hash} computed={computed}"
                            ),
                        )
                        cls._cleanup_temp_file(temp_path_obj)
                        return False

                temp_path_obj.replace(local_path_obj)
                PathUtils.best_effort_sync_dir(local_path_obj.parent)
                return True
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                if attempt >= cls.RETRY_TOTAL:
                    cls._report_download_failure(
                        url=url,
                        local_path=local_path,
                        message=cls._describe_request_failure(exc),
                        failure_message_callback=failure_message_callback,
                        exc=exc,
                    )
                    cls._cleanup_temp_file(temp_path_obj)
                    return False
                delay = cls._retry_delay_seconds(None, attempt)
                time.sleep(delay)
                continue
            except (httpx.HTTPError, NetworkSecurityError, ResponseTooLargeError, OSError, ValueError) as exc:
                cls._report_download_failure(
                    url=url,
                    local_path=local_path,
                    message=cls._describe_request_failure(exc),
                    failure_message_callback=failure_message_callback,
                    exc=exc,
                )
                cls._cleanup_temp_file(temp_path_obj)
                return False
            finally:
                if response is not None:
                    response.close()

        cls._cleanup_temp_file(temp_path_obj)
        return False


__all__ = ["HTTPClient"]
