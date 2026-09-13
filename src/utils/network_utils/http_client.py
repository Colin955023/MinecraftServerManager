"""HTTPX 網路用戶端與下載工具"""

from __future__ import annotations

import errno
import hmac
import ipaddress
import socket
import ssl
import tempfile
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from contextlib import suppress
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, cast
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import orjson

from src.utils import (
    APP_NAME,
    APP_VERSION,
    GITHUB_OWNER,
    GITHUB_REPO,
    HashUtils,
    NetworkSecurityError,
    OperationCancelledError,
    OperationError,
    OperationResult,
    ResponseTooLargeError,
    atomic_replace_file,
    current_work_token,
    delete_within,
    format_bytes,
    get_logger,
    get_shared_manager,
    open_regular_file_for_write,
    resolve_stable_path,
)

from .http_models import HTTPJSONResponse, JSONContainer

logger = get_logger().bind(component="HTTPClient")
_PINNED_ADDRESS_EXTENSION = "codex_pinned_address"
_DNS_SLOTS = threading.BoundedSemaphore(16)


def _resolve_hostname(hostname: str, port: int) -> list[Any]:
    """限制 DNS 等待與同時解析數，系統解析停滯時不阻擋程式退出"""
    token = current_work_token()
    deadline = time.monotonic() + 10.0
    while not _DNS_SLOTS.acquire(timeout=0.05):
        token.check()
        if time.monotonic() >= deadline:
            raise OSError("DNS 解析佇列逾時")
    future = get_shared_manager().run(socket.getaddrinfo, hostname, port, type=socket.SOCK_STREAM)
    future.add_done_callback(lambda _future: _DNS_SLOTS.release())
    while True:
        token.check()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise OSError("DNS 解析逾時")
        try:
            return future.result(timeout=min(remaining, 0.1))
        except TimeoutError:
            if future.done():
                raise


class HTTPClient:
    """專案唯一的同步 HTTP client，供 Qt 背景工作執行緒共用"""

    JSON_TIMEOUT_MIN_SECONDS = 10
    CONTENT_TIMEOUT_MIN_SECONDS = 30
    DOWNLOAD_TIMEOUT_MIN_SECONDS = 60
    MIN_CHUNK_SIZE = 1024

    MAX_JSON_RESPONSE_BYTES = 16 * 1024 * 1024
    MAX_CONTENT_RESPONSE_BYTES = 64 * 1024 * 1024
    MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
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
            follow_redirects=False,
            trust_env=False,
            transport=_PinnedHTTPTransport(
                http1=True,
                verify=True,
                trust_env=False,
                limits=httpx.Limits(
                    max_connections=cls.CONNECTION_POOL_SIZE,
                    max_keepalive_connections=cls.KEEPALIVE_POOL_SIZE,
                    keepalive_expiry=cls.KEEPALIVE_EXPIRY_SECONDS,
                ),
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

    @classmethod
    def _validate_url_policy(cls, url: str) -> httpx.URL:
        """驗證 URL 語法與靜態安全政策，不執行 DNS 查詢"""
        try:
            parsed = httpx.URL(url)
            hostname = (parsed.host or "").rstrip(".").lower()
            port = parsed.port
        except (TypeError, ValueError, httpx.InvalidURL) as e:
            raise NetworkSecurityError("URL 格式無效") from e

        if parsed.scheme.lower() != "https" or not hostname:
            raise NetworkSecurityError("只允許 HTTPS URL")
        if parsed.userinfo:
            raise NetworkSecurityError("URL 不可包含 credential")
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise NetworkSecurityError("拒絕 localhost URL")
        if port is not None and not 1 <= port <= 65535:
            raise NetworkSecurityError("URL port 無效")

        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return parsed
        if not address.is_global:
            raise NetworkSecurityError("拒絕非公開 IP URL")
        return parsed

    @classmethod
    def _resolve_public_address(cls, parsed: httpx.URL) -> str:
        """解析並固定單一公開 IP；任何非公開解析結果都採 fail-closed"""
        hostname = (parsed.host or "").rstrip(".").lower()
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            try:
                resolved = _resolve_hostname(hostname, parsed.port or 443)
            except OSError as e:
                raise NetworkSecurityError("URL hostname 無法解析") from e

            first_address = ""
            for result in resolved:
                try:
                    candidate = str(result[4][0])
                    candidate_address = ipaddress.ip_address(candidate)
                except IndexError, KeyError, TypeError, ValueError:
                    continue
                if not candidate_address.is_global:
                    raise NetworkSecurityError("URL hostname 解析至非公開位址") from None
                if not first_address:
                    first_address = str(candidate_address)
            if not first_address:
                raise NetworkSecurityError("URL hostname 沒有可用的公開位址") from None
            return first_address

        if not address.is_global:
            raise NetworkSecurityError("拒絕非公開 IP URL")
        return str(address)

    @classmethod
    def _validated_url_and_address(cls, url: str) -> tuple[httpx.URL, str]:
        """驗證 URL，並在實際 request attempt 前解析一次固定公開 IP"""
        parsed = cls._validate_url_policy(url)
        return parsed, cls._resolve_public_address(parsed)

    @classmethod
    def _is_valid_url(cls, url: str) -> bool:
        """只檢查 HTTPS URL 靜態政策；DNS 安全檢查在送出 request 前執行"""
        try:
            cls._validate_url_policy(url)
            return True
        except NetworkSecurityError, OSError, TypeError, ValueError:
            return False

    @staticmethod
    def _request_authority(parsed: httpx.URL) -> str:
        hostname = parsed.raw_host.decode("ascii").rstrip(".")
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        return f"{hostname}:{parsed.port}" if parsed.port is not None else hostname

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
        deadline: float | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        method = method.upper()
        current_url = url
        current_headers = dict(headers or {})
        current_headers.setdefault("Accept-Encoding", "identity")
        content = None
        if json_body is not None:
            content = orjson.dumps(json_body)
            current_headers.setdefault("Content-Type", "application/json")

        for redirect_count in range(cls.MAX_REDIRECTS + 1):
            if deadline is not None:
                cls._check_request_deadline(deadline)
            validated_url, pinned_address = cls._validated_url_and_address(current_url)
            remaining_timeout = timeout
            if deadline is not None:
                remaining_timeout = max(1, min(timeout, int(deadline - time.monotonic())))

            client = cls._get_client()
            request = client.build_request(
                method,
                validated_url,
                headers=current_headers,
                params=params,
                content=content,
                timeout=cls._make_timeout(remaining_timeout),
                extensions={_PINNED_ADDRESS_EXTENSION: pinned_address},
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

            source_url = current_url
            next_url = urljoin(source_url, location)
            response.close()
            if not cls._is_valid_url(next_url):
                raise NetworkSecurityError("重新導向目的地不符合 HTTPS/外部網路安全策略")

            current_headers = cls._redirect_headers(current_headers, source_url, next_url) or {}
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
        retry: bool = True,
        deadline: float | None = None,
    ) -> httpx.Response:
        return cls._request_with_retry(
            method,
            url,
            timeout=timeout,
            headers=headers,
            params=params,
            json_body=json_body,
            response_handler=lambda response: response,
            retry=retry,
            close_response=False,
            deadline=deadline,
        )

    @classmethod
    def _request_with_retry[ResponseT](
        cls,
        method: str,
        url: str,
        *,
        timeout: int,
        response_handler: Callable[[httpx.Response], ResponseT],
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        suppress_status_codes: set[int] | None = None,
        retry: bool = True,
        close_response: bool = True,
        deadline: float | None = None,
    ) -> ResponseT:
        """執行單一 HTTP retry state machine，並讓 caller 決定如何消費回應"""
        method = method.upper()
        suppressed = suppress_status_codes or set()
        max_attempts = cls.RETRY_TOTAL + 1 if retry and method in cls.RETRY_ALLOWED_METHODS else 1
        deadline = deadline or (
            time.monotonic() + timeout * max_attempts + cls.RETRY_MAX_DELAY_SECONDS * (max_attempts - 1)
        )

        for attempt in range(1, max_attempts + 1):
            cls._check_request_deadline(deadline)
            response: httpx.Response | None = None
            delay: float | None = None
            try:
                response = cls._send_stream_once(
                    method,
                    url,
                    timeout=timeout,
                    deadline=deadline,
                    headers=headers,
                    params=params,
                    json_body=json_body,
                )
                if (
                    response.status_code not in suppressed
                    and response.status_code in cls.RETRY_STATUS_CODES
                    and attempt < max_attempts
                ):
                    delay = cls._retry_delay_seconds(response, attempt)
                else:
                    result = response_handler(response)
                    if not close_response:
                        response = None
                    return result
            except httpx.TransportError:
                if attempt >= max_attempts:
                    raise
                delay = cls._retry_delay_seconds(None, attempt)
            finally:
                if response is not None:
                    response.close()

            if delay is not None:
                cls._wait_retry(delay, deadline)

        raise OperationError("HTTP retry loop terminated unexpectedly")

    @staticmethod
    def _check_request_deadline(deadline: float) -> None:
        current_work_token().check()
        if time.monotonic() >= deadline:
            raise httpx.ReadTimeout("HTTP 作業超過整體等待上限")

    @classmethod
    def _wait_retry(cls, delay: float, deadline: float, cancel_check: Callable[[], bool] | None = None) -> None:
        end = min(deadline, time.monotonic() + delay)
        while (remaining := end - time.monotonic()) > 0:
            cls._check_request_deadline(deadline)
            if cancel_check is not None and cancel_check():
                raise OperationCancelledError("下載已取消")
            current_work_token().wait(min(remaining, 0.1) if cancel_check is not None else remaining)

    @classmethod
    def _read_limited(cls, response: httpx.Response, max_bytes: int, deadline: float) -> bytes:
        cls._ensure_identity_content_encoding(response)
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
            cls._check_request_deadline(deadline)
            if len(payload) + len(chunk) > max_bytes:
                raise ResponseTooLargeError(f"HTTP 解碼後內容超過上限 {format_bytes(max_bytes)}")
            payload.extend(chunk)
        return bytes(payload)

    @staticmethod
    def _ensure_identity_content_encoding(response: httpx.Response) -> None:
        content_encoding = response.headers.get("Content-Encoding", "").strip().lower()
        if content_encoding and content_encoding != "identity":
            raise NetworkSecurityError(f"拒絕未要求的壓縮 HTTP 回應: {content_encoding}")

    @staticmethod
    def _cleanup_temp_file(temp_path: Path | None) -> None:
        if temp_path is None:
            return
        with suppress(OSError):
            if temp_path.exists():
                delete_within(temp_path.parent, temp_path)

    @classmethod
    def _download_failure(
        cls,
        *,
        url: str,
        local_path: str,
        message: str,
        exc: Exception | None = None,
        log_message: str | None = None,
    ) -> OperationResult:
        safe_url = cls._safe_url_for_log(url)
        final_log_message = log_message or f"檔案下載失敗 ({safe_url} -> {local_path}): {message}"
        if exc is None:
            logger.error(final_log_message)
        else:
            logger.error(f"{final_log_message}: {type(exc).__name__}: {cls._describe_request_failure(exc)}")
        return OperationResult(False, message, exc)

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
            except OSError as e:
                logger.debug(f"progress_callback/stat failed: {e}")
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
        suppressed = suppress_status_codes or set()

        max_attempts = cls.RETRY_TOTAL + 1 if method.upper() in cls.RETRY_ALLOWED_METHODS else 1
        deadline = time.monotonic() + timeout * max_attempts + cls.RETRY_MAX_DELAY_SECONDS * (max_attempts - 1)

        def _read_response(response: httpx.Response) -> bytes | None:
            if response.status_code in suppressed:
                return None
            response.raise_for_status()
            return cls._read_limited(response, max_bytes, deadline)

        return cls._request_with_retry(
            method,
            url,
            timeout=timeout,
            headers=headers,
            params=params,
            json_body=json_body,
            suppress_status_codes=suppressed,
            response_handler=_read_response,
            deadline=deadline,
        )

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
    ) -> JSONContainer | None:
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
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (suppress_status_codes or set()):
                return None
            logger.warning(f"HTTP {normalized_method} JSON 請求失敗 ({safe_url}): {cls._describe_request_failure(e)}")
        except (httpx.RequestError, NetworkSecurityError, ResponseTooLargeError, orjson.JSONDecodeError) as e:
            logger.warning(f"HTTP {normalized_method} JSON 請求失敗 ({safe_url}): {cls._describe_request_failure(e)}")
        return None

    @classmethod
    def fetch_json(
        cls,
        url: str,
        timeout: int = 10,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        suppress_status_codes: set[int] | None = None,
    ) -> JSONContainer | None:
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
        deadline = time.monotonic() + timeout * max_attempts + cls.RETRY_MAX_DELAY_SECONDS * (max_attempts - 1)

        def _parse_response(response: httpx.Response) -> HTTPJSONResponse:
            status_code = response.status_code
            if status_code == 404:
                return HTTPJSONResponse(status_code, error_kind="not_found")
            if status_code == 429:
                return HTTPJSONResponse(status_code, error_kind="rate_limited")
            if status_code >= 400:
                error_kind = "transient" if status_code >= 500 else "invalid_request"
                return HTTPJSONResponse(status_code, error_kind=error_kind)
            raw_bytes = cls._read_limited(response, cls.MAX_JSON_RESPONSE_BYTES, deadline)
            try:
                payload = orjson.loads(raw_bytes)
            except orjson.JSONDecodeError:
                return HTTPJSONResponse(status_code, error_kind="invalid_response")
            if not isinstance(payload, dict | list):
                return HTTPJSONResponse(status_code, error_kind="invalid_response")
            return HTTPJSONResponse(status_code, payload=payload)

        try:
            return cls._request_with_retry(
                "GET",
                url,
                timeout=timeout,
                headers=headers,
                params=params,
                response_handler=_parse_response,
                deadline=deadline,
            )
        except httpx.TimeoutException:
            return HTTPJSONResponse(None, error_kind="timeout")
        except httpx.TransportError:
            return HTTPJSONResponse(None, error_kind="transient")
        except NetworkSecurityError, ResponseTooLargeError:
            return HTTPJSONResponse(None, error_kind="invalid_response")

    @classmethod
    def post_json(
        cls,
        url: str,
        json_body: dict[str, Any],
        timeout: int = 10,
        headers: dict[str, str] | None = None,
        suppress_status_codes: set[int] | None = None,
    ) -> JSONContainer | None:
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
        except (httpx.HTTPError, NetworkSecurityError, ResponseTooLargeError) as e:
            if log_errors:
                logger.exception(f"HTTP GET 請求失敗 ({safe_url}): {cls._describe_request_failure(e)}")
            else:
                logger.debug(f"HTTP GET 請求未成功 ({safe_url}): {cls._describe_request_failure(e)}")
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
        expected_hash: str | None = None,
        expected_hash_algorithm: str | None = None,
        max_bytes: int = MAX_DOWNLOAD_BYTES,
    ) -> OperationResult:
        """
        下載檔案，並以單一結果物件回傳成功狀態與失敗原因

        Args:
            url: 下載來源 URL
            local_path: 下載目的地路徑
            progress_callback: 下載進度回呼函式，接收已下載位元組數與總位元組數
            timeout: 下載逾時秒數
            chunk_size: 下載分塊大小
            cancel_check: 取消檢查回呼函式，回傳 True 表示取消下載
            expected_hash: 預期的雜湊值（hexadecimal string）
            expected_hash_algorithm: 預期的雜湊演算法名稱（如 "sha256"、"sha1"）
            max_bytes: 下載回應允許的最大位元組數

        Returns:
            下載結果
        """
        if not url or not isinstance(url, str) or not cls._is_valid_url(url):
            return cls._download_failure(
                url=str(url),
                local_path=str(local_path),
                message="URL 參數無效或不符合 HTTPS 安全策略",
            )
        if not local_path or not isinstance(local_path, str):
            return cls._download_failure(
                url=url,
                local_path=str(local_path),
                message="本地路徑參數無效",
            )

        timeout = cls._normalize_positive_int(timeout, cls.DOWNLOAD_TIMEOUT_MIN_SECONDS)
        chunk_size = cls._normalize_positive_int(chunk_size, cls.MIN_CHUNK_SIZE)
        max_bytes = cls._normalize_positive_int(max_bytes, 1)
        try:
            local_path_obj = resolve_stable_path(local_path, create_parent=True)
        except OSError as e:
            return cls._download_failure(
                url=url,
                local_path=local_path,
                message="無法建立安全下載目錄",
                exc=e,
            )

        raw_expected_hash = str(expected_hash or "").strip()
        normalized_expected_hash, resolved_hash_algorithm = HashUtils.normalize_expected_hash(
            raw_expected_hash,
            expected_hash_algorithm,
        )
        if raw_expected_hash and not normalized_expected_hash:
            return cls._download_failure(
                url=url,
                local_path=local_path,
                message=f"預期雜湊格式無效 (len={len(raw_expected_hash)})",
            )

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
            return OperationResult(True)

        temp_path_obj: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                delete=False,
                prefix=local_path_obj.name + ".",
                suffix=".part",
                dir=local_path_obj.parent,
            ) as tmp_file:
                temp_path_obj = Path(tmp_file.name)
        except OSError as e:
            return cls._download_failure(
                url=url,
                local_path=local_path,
                message="無法建立安全下載暫存檔",
                exc=e,
            )

        max_attempts = cls.RETRY_TOTAL + 1
        deadline = time.monotonic() + 1800.0
        try:
            for attempt in range(1, max_attempts + 1):
                response: httpx.Response | None = None
                try:
                    cls._check_request_deadline(deadline)
                    if cancel_check is not None and cancel_check():
                        raise OperationCancelledError("下載已取消")
                    response = cls._open_stream("GET", url, timeout=timeout, retry=False, deadline=deadline)
                    if response.status_code in cls.RETRY_STATUS_CODES and attempt < max_attempts:
                        delay = cls._retry_delay_seconds(response, attempt)
                        response.close()
                        response = None
                        cls._wait_retry(delay, deadline, cancel_check)
                        continue
                    response.raise_for_status()
                    cls._ensure_identity_content_encoding(response)
                    total_size = int(response.headers.get("Content-Length", 0) or 0)

                    if total_size > max_bytes:
                        return cls._download_failure(
                            url=url,
                            local_path=local_path,
                            message=f"下載檔案超過大小上限：{format_bytes(max_bytes)}",
                        )

                    if total_size > 0:
                        try:
                            from src.utils import SystemUtils

                            free_space = SystemUtils.get_free_disk_bytes(local_path_obj.parent)
                        except OSError as e:
                            logger.debug(f"無法查詢目的地磁碟空間，略過預檢: {e}")
                        else:
                            if free_space < total_size:
                                failure_message = (
                                    f"磁碟空間不足：目的地 {local_path_obj.parent} 需要至少 {format_bytes(total_size)}，"
                                    f"目前剩餘 {format_bytes(free_space)}"
                                )
                                return cls._download_failure(
                                    url=url,
                                    local_path=local_path,
                                    message=failure_message,
                                )

                    downloaded = 0
                    hasher = HashUtils.new_hasher(resolved_hash_algorithm) if normalized_expected_hash else None
                    if normalized_expected_hash and hasher is None:
                        return cls._download_failure(
                            url=url,
                            local_path=local_path,
                            message="不支援的下載檔案雜湊演算法",
                        )
                    failure_result: OperationResult | None = None
                    with open_regular_file_for_write(temp_path_obj) as file_obj:
                        for chunk in response.iter_bytes(chunk_size=chunk_size):
                            cls._check_request_deadline(deadline)
                            if cancel_check and cancel_check():
                                failure_result = cls._download_failure(
                                    url=url,
                                    local_path=local_path,
                                    message="下載已取消",
                                )
                                break
                            if not chunk:
                                continue
                            if downloaded + len(chunk) > max_bytes:
                                failure_result = cls._download_failure(
                                    url=url,
                                    local_path=local_path,
                                    message=f"下載檔案超過大小上限：{format_bytes(max_bytes)}",
                                )
                                break
                            file_obj.write(chunk)
                            if hasher is not None:
                                hasher.update(chunk)
                            downloaded += len(chunk)
                            if progress_callback:
                                progress_callback(downloaded, total_size)

                    if failure_result is not None:
                        return failure_result

                    if normalized_expected_hash and hasher is not None:
                        computed = hasher.hexdigest().lower()
                        if not hmac.compare_digest(computed, normalized_expected_hash):
                            return cls._download_failure(
                                url=url,
                                local_path=local_path,
                                message=f"下載檔案雜湊驗證失敗：預期 {resolved_hash_algorithm.upper()} 不符",
                                log_message=(
                                    f"下載檔案的雜湊不符: algorithm={resolved_hash_algorithm} "
                                    f"expected={normalized_expected_hash} computed={computed}"
                                ),
                            )

                    if not atomic_replace_file(temp_path_obj, local_path_obj):
                        raise OSError(f"無法原子提交下載檔案: {local_path_obj}")
                    return OperationResult(True)
                except (httpx.TransportError, httpx.TimeoutException) as e:
                    if attempt >= max_attempts:
                        return cls._download_failure(
                            url=url,
                            local_path=local_path,
                            message=cls._describe_request_failure(e),
                            exc=e,
                        )
                    delay = cls._retry_delay_seconds(None, attempt)
                    cls._wait_retry(delay, deadline, cancel_check)
                except (httpx.HTTPError, NetworkSecurityError, ResponseTooLargeError, OSError, ValueError) as e:
                    return cls._download_failure(
                        url=url,
                        local_path=local_path,
                        message=cls._describe_request_failure(e),
                        exc=e,
                    )
                finally:
                    if response is not None:
                        response.close()
        except OperationCancelledError:
            return cls._download_failure(url=url, local_path=local_path, message="下載已取消")
        finally:
            cls._cleanup_temp_file(temp_path_obj)

        return OperationResult(False, "download_incomplete")


class _PinnedHTTPTransport(httpx.BaseTransport):
    """使用已驗證 IP 連線，並依原始 HTTPS origin 隔離 connection pool"""

    def __init__(
        self,
        *,
        verify: ssl.SSLContext | str | bool = True,
        trust_env: bool = True,
        http1: bool = True,
        limits: httpx.Limits | None = None,
    ) -> None:
        self._verify = ssl.create_default_context() if verify is True and not trust_env else verify
        self._trust_env = trust_env
        self._http1 = http1
        self._limits = limits or httpx.Limits()
        self._max_origins = max(1, self._limits.max_connections or HTTPClient.CONNECTION_POOL_SIZE)
        self._origin_transports: OrderedDict[tuple[str, str, int], _OriginTransport] = OrderedDict()
        self._transport_lock = threading.Lock()

    @staticmethod
    def _origin_key(url: httpx.URL) -> tuple[str, str, int]:
        scheme = url.scheme.lower()
        hostname = (url.host or "").rstrip(".").lower()
        port = url.port or (443 if scheme == "https" else 80)
        return scheme, hostname, port

    def _new_transport(self) -> httpx.HTTPTransport:
        return httpx.HTTPTransport(
            verify=self._verify,
            trust_env=self._trust_env,
            http1=self._http1,
            limits=self._limits,
        )

    def _transport_for_origin(
        self, url: httpx.URL
    ) -> tuple[httpx.HTTPTransport, Callable[[], None], httpx.HTTPTransport | None]:
        key = self._origin_key(url)
        evicted: httpx.HTTPTransport | None = None
        with self._transport_lock:
            if entry := self._origin_transports.get(key):
                entry.active_requests += 1
                self._origin_transports.move_to_end(key)
                return entry.transport, lambda: self._release_origin(key), evicted

            if len(self._origin_transports) >= self._max_origins:
                for old_key, old_entry in self._origin_transports.items():
                    if old_entry.active_requests == 0:
                        evicted = old_entry.transport
                        del self._origin_transports[old_key]
                        break
            if len(self._origin_transports) >= self._max_origins:
                transport = self._new_transport()
                return transport, transport.close, evicted

            transport = self._new_transport()
            self._origin_transports[key] = _OriginTransport(transport, active_requests=1)
            return transport, lambda: self._release_origin(key), evicted

    def _release_origin(self, key: tuple[str, str, int]) -> None:
        with self._transport_lock:
            if entry := self._origin_transports.get(key):
                entry.active_requests = max(0, entry.active_requests - 1)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        pinned_address = request.extensions.get(_PINNED_ADDRESS_EXTENSION)
        if not isinstance(pinned_address, str):
            _validated_url, pinned_address = HTTPClient._validated_url_and_address(str(request.url))
        try:
            if not ipaddress.ip_address(pinned_address).is_global:
                raise NetworkSecurityError("拒絕連線至非公開 IP")
        except ValueError as e:
            raise NetworkSecurityError("固定連線 IP 無效") from e

        headers = httpx.Headers(request.headers)
        headers["Host"] = HTTPClient._request_authority(request.url)
        extensions = dict(request.extensions)
        extensions.pop(_PINNED_ADDRESS_EXTENSION, None)
        extensions["sni_hostname"] = request.url.raw_host.decode("ascii").rstrip(".")
        pinned_request = httpx.Request(
            request.method,
            request.url.copy_with(host=pinned_address),
            headers=headers,
            content=request.stream,
            extensions=extensions,
        )
        transport, release, evicted = self._transport_for_origin(request.url)
        if evicted is not None:
            evicted.close()
        try:
            response = transport.handle_request(pinned_request)
        except Exception:
            release()
            raise
        response.stream = _LeasedSyncByteStream(cast(httpx.SyncByteStream, response.stream), release)
        response.request = request
        return response

    def close(self) -> None:
        with self._transport_lock:
            transports = [entry.transport for entry in self._origin_transports.values()]
            self._origin_transports.clear()
        for transport in transports:
            transport.close()


class _OriginTransport:
    """保留每個 origin transport 與仍在讀取的回應數"""

    def __init__(self, transport: httpx.HTTPTransport, *, active_requests: int) -> None:
        self.transport = transport
        self.active_requests = active_requests


class _LeasedSyncByteStream(httpx.SyncByteStream):
    """回應關閉時釋放 origin transport 使用計數"""

    def __init__(self, stream: httpx.SyncByteStream, release: Callable[[], None]) -> None:
        self._stream = stream
        self._release = release
        self._released = False

    def __iter__(self):
        try:
            yield from self._stream
        finally:
            self.close()

    def close(self) -> None:
        try:
            self._stream.close()
        finally:
            if not self._released:
                self._released = True
                self._release()


__all__ = ["HTTPClient"]
