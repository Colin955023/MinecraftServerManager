"""Async HTTP 網路請求工具模組。"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from aiohttp import ClientError, ClientResponseError, ClientSession, ClientTimeout

from ...version_info import APP_NAME, APP_VERSION
from .. import get_logger

logger = get_logger().bind(component="AsyncHTTPUtils")

JsonResponse = dict[str, Any] | list[Any]


class AsyncRateLimiter:
    """async 版本的簡單網域節流器。"""

    def __init__(self, calls_per_second: int = 10) -> None:
        self.delay = 1.0 / max(1, calls_per_second)
        self.last_call_time: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait(self, domain: str) -> None:
        """針對指定網域執行非同步節流等待。"""
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            last = self.last_call_time.get(domain, 0.0)
            elapsed = now - last
            if elapsed < self.delay:
                sleep_time = self.delay - elapsed
                await asyncio.sleep(sleep_time)
                self.last_call_time[domain] = loop.time()
            else:
                self.last_call_time[domain] = now


_async_rate_limiter = AsyncRateLimiter(calls_per_second=10)


class AsyncHTTPUtils:
    """HTTPUtils 的 aiohttp 非同步對應實作。"""

    JSON_TIMEOUT_MIN_SECONDS = 10
    CONTENT_TIMEOUT_MIN_SECONDS = 30
    DOWNLOAD_TIMEOUT_MIN_SECONDS = 60
    MIN_CHUNK_SIZE = 1024

    @staticmethod
    def _normalize_int_value(value: int, minimum: int) -> int:
        """確保輸入為有效正整數，且不低於指定下限。"""
        try:
            normalized = int(value)
        except TypeError, ValueError:
            normalized = minimum
        return max(minimum, normalized)

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        """僅接受具備主機名稱的 http/https URL。"""
        try:
            parsed = urlparse(url)
        except ValueError:
            return False
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)

    @staticmethod
    def get_default_headers(headers: dict[str, str] | None = None) -> dict[str, str]:
        """獲取包含預設 User-Agent 的標頭。"""
        default_headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION} (colin955023@gmail.com)"}
        if headers:
            default_headers.update(headers)
        return default_headers

    @classmethod
    async def get_json(
        cls,
        url: str,
        timeout: int = 10,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        suppress_status_codes: set[int] | None = None,
    ) -> JsonResponse | None:
        """發送 async HTTP GET 請求並解析 JSON。"""
        if not url or not isinstance(url, str) or (not cls._is_valid_url(url)):
            logger.error("Async HTTP GET JSON 請求失敗: URL 參數無效")
            return None
        timeout = cls._normalize_int_value(timeout, cls.JSON_TIMEOUT_MIN_SECONDS)
        final_headers = cls.get_default_headers(headers)
        try:
            await _async_rate_limiter.wait(urlparse(url).netloc)
            async with (
                ClientSession(headers=final_headers, timeout=ClientTimeout(total=timeout)) as session,
                session.get(url, params=params) as response,
            ):
                if response.status in (suppress_status_codes or set()):
                    return None
                response.raise_for_status()
                return await response.json()
        except ClientResponseError as e:
            if e.status in (suppress_status_codes or set()):
                return None
            logger.exception(f"Async HTTP GET JSON 請求失敗 ({url}): {e}")
            return None
        except (ClientError, TimeoutError, ValueError) as e:
            logger.exception(f"Async HTTP GET JSON 請求失敗 ({url}): {e}")
            return None

    @classmethod
    async def post_json(
        cls,
        url: str,
        json_body: dict[str, Any],
        timeout: int = 10,
        headers: dict[str, str] | None = None,
        suppress_status_codes: set[int] | None = None,
    ) -> JsonResponse | None:
        """發送 async HTTP POST 請求並解析 JSON。"""
        if not url or not isinstance(url, str) or (not cls._is_valid_url(url)):
            logger.error("Async HTTP POST JSON 請求失敗: URL 參數無效")
            return None
        timeout = cls._normalize_int_value(timeout, cls.JSON_TIMEOUT_MIN_SECONDS)
        final_headers = cls.get_default_headers(headers)
        try:
            await _async_rate_limiter.wait(urlparse(url).netloc)
            async with (
                ClientSession(headers=final_headers, timeout=ClientTimeout(total=timeout)) as session,
                session.post(url, json=json_body) as response,
            ):
                if response.status in (suppress_status_codes or set()):
                    return None
                response.raise_for_status()
                return await response.json()
        except ClientResponseError as e:
            if e.status in (suppress_status_codes or set()):
                return None
            logger.exception(f"Async HTTP POST JSON 請求失敗 ({url}): {e}")
            return None
        except (ClientError, TimeoutError, ValueError) as e:
            logger.exception(f"Async HTTP POST JSON 請求失敗 ({url}): {e}")
            return None

    @classmethod
    async def get_content(
        cls,
        url: str,
        timeout: int = 30,
        stream: bool = False,
        headers: dict[str, str] | None = None,
    ) -> bytes | None:
        """發送 async HTTP GET 請求並回傳完整回應內容。"""
        del stream
        if not url or not isinstance(url, str) or (not cls._is_valid_url(url)):
            logger.error("Async HTTP GET 請求失敗: URL 參數無效")
            return None
        timeout = cls._normalize_int_value(timeout, cls.CONTENT_TIMEOUT_MIN_SECONDS)
        final_headers = cls.get_default_headers(headers)
        try:
            await _async_rate_limiter.wait(urlparse(url).netloc)
            async with (
                ClientSession(headers=final_headers, timeout=ClientTimeout(total=timeout)) as session,
                session.get(url) as response,
            ):
                response.raise_for_status()
                return await response.read()
        except (ClientError, TimeoutError) as e:
            logger.exception(f"Async HTTP GET 請求失敗 ({url}): {e}")
            return None

    @classmethod
    async def download_file(
        cls,
        url: str,
        local_path: str,
        progress_callback: Callable[[int, int], None] | None = None,
        timeout: int = 60,
        chunk_size: int = 65536,
        cancel_check: Callable[[], bool] | None = None,
        expected_sha256: str | None = None,
        expected_hash: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> bool:
        """下載檔案並儲存到本機路徑（async 版本）。"""
        if not url or not isinstance(url, str) or (not cls._is_valid_url(url)):
            logger.error("Async 檔案下載失敗: URL 參數無效")
            return False
        if not local_path or not isinstance(local_path, str):
            logger.error("Async 檔案下載失敗: 本地路徑參數無效")
            return False
        timeout = cls._normalize_int_value(timeout, cls.DOWNLOAD_TIMEOUT_MIN_SECONDS)
        chunk_size = cls._normalize_int_value(chunk_size, cls.MIN_CHUNK_SIZE)
        local_path_obj = Path(local_path)
        local_path_obj.parents[0].mkdir(parents=True, exist_ok=True)
        normalized_expected_hash = str(expected_hash or expected_sha256 or "").strip().lower()
        expected_hash_algorithm = cls._resolve_expected_hash_algorithm(normalized_expected_hash)
        if normalized_expected_hash and not expected_hash_algorithm:
            logger.error(f"Async 檔案下載失敗: 僅接受 SHA-256 / SHA-512 預期雜湊 (len={len(normalized_expected_hash)})")
            return False
        if normalized_expected_hash and cls._local_file_matches_hash(
            local_path_obj, expected_hash_algorithm, normalized_expected_hash
        ):
            cls._report_completed_progress(local_path_obj, progress_callback)
            return True
        temp_path_obj = cls._create_temp_download_path(local_path_obj)
        try:
            final_headers = cls.get_default_headers(headers)
            await _async_rate_limiter.wait(urlparse(url).netloc)
            async with (
                ClientSession(headers=final_headers, timeout=ClientTimeout(total=timeout)) as session,
                session.get(url) as response,
            ):
                response.raise_for_status()
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                hasher = hashlib.new(expected_hash_algorithm or "sha256")
                with temp_path_obj.open("wb") as file_obj:
                    async for chunk in response.content.iter_chunked(chunk_size):
                        if cancel_check and cancel_check():
                            cls._cleanup_temp_file(temp_path_obj)
                            return False
                        if not chunk:
                            continue
                        file_obj.write(chunk)
                        hasher.update(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)
                computed = hasher.hexdigest().lower()
                if normalized_expected_hash and computed != normalized_expected_hash:
                    logger.error(
                        f"Async 下載檔案的雜湊不符: algorithm={expected_hash_algorithm} expected={normalized_expected_hash} computed={computed}"
                    )
                    cls._cleanup_temp_file(temp_path_obj)
                    return False
            with contextlib.suppress(OSError):
                local_path_obj.unlink(missing_ok=True)
            temp_path_obj.replace(local_path_obj)
            cls._fsync_parent_dir(local_path_obj)
            return True
        except (ClientError, TimeoutError, OSError) as e:
            logger.exception(f"Async 檔案下載失敗 ({url} -> {local_path}): {e}")
            cls._cleanup_temp_file(temp_path_obj)
            return False

    @staticmethod
    def _resolve_expected_hash_algorithm(normalized_expected_hash: str) -> str:
        if not normalized_expected_hash:
            return ""
        if len(normalized_expected_hash) == 64:
            return "sha256"
        if len(normalized_expected_hash) == 128:
            return "sha512"
        return ""

    @staticmethod
    def _local_file_matches_hash(path: Path, algorithm: str, expected_hash: str) -> bool:
        if not path.exists() or not algorithm or not expected_hash:
            return False
        try:
            hasher = hashlib.new(algorithm)
            with path.open("rb") as file_obj:
                for chunk in iter(lambda: file_obj.read(8192), b""):
                    hasher.update(chunk)
            return hasher.hexdigest().lower() == expected_hash
        except OSError as e:
            logger.debug(f"Async 檢查本地檔案雜湊失敗，將進行下載: {e}")
            return False

    @staticmethod
    def _report_completed_progress(path: Path, progress_callback: Callable[[int, int], None] | None) -> None:
        if not progress_callback:
            return
        try:
            size = path.stat().st_size
            progress_callback(size, size)
        except OSError as e:
            logger.debug(f"Async progress_callback/stat failed: {e}")
        except Exception as e:
            logger.debug(f"Async progress_callback raised: {e}")

    @staticmethod
    def _create_temp_download_path(local_path_obj: Path) -> Path:
        try:
            with tempfile.NamedTemporaryFile(
                delete=False,
                prefix=local_path_obj.name + ".",
                suffix=".part",
                dir=local_path_obj.parents[0],
            ) as temp_file:
                return Path(temp_file.name)
        except OSError:
            return local_path_obj.with_name(local_path_obj.name + ".part")

    @staticmethod
    def _cleanup_temp_file(temp_path_obj: Path) -> None:
        with contextlib.suppress(OSError):
            if temp_path_obj.exists():
                temp_path_obj.unlink()

    @staticmethod
    def _fsync_parent_dir(path: Path) -> None:
        try:
            fd = os.open(str(path.parents[0]), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError as e:
            logger.debug(f"Async 目錄 fsync 失敗 (path={path.parents[0]}): {e}")

    @classmethod
    async def get_json_batch(
        cls,
        urls: list[str],
        timeout: int = 10,
        headers: dict[str, str] | None = None,
        max_concurrency: int = 5,
    ) -> list[JsonResponse | None]:
        """批次發送 async HTTP GET 請求並解析 JSON。"""
        if not urls:
            return []
        semaphore = asyncio.Semaphore(max(1, min(max_concurrency, len(urls))))

        async def _fetch(url: str) -> JsonResponse | None:
            async with semaphore:
                return await cls.get_json(url, timeout=timeout, headers=headers)

        return await asyncio.gather(*(_fetch(url) for url in urls))


__all__ = ["AsyncHTTPUtils", "AsyncRateLimiter", "JsonResponse"]
