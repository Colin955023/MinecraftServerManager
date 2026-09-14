"""
檔案雜湊工具
提供同步的檔案與記憶體內容雜湊計算
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Any

from .filesystem_utils import open_regular_file
from .logger import get_logger

logger = get_logger().bind(component="HashUtils")
SAFE_HASH_FILE_MAX_BYTES = 512 * 1024 * 1024
_SUPPORTED_HASH_LENGTHS = {"sha1": 40, "sha256": 64, "sha512": 128}
_HASH_ALGORITHM_BY_LENGTH = {length: name for name, length in _SUPPORTED_HASH_LENGTHS.items()}
_HASH_CACHE_LOCK = threading.Lock()
type _HashCacheKey = tuple[str, str, int, int, int, int, int, int, str | None]
_HASH_CACHE: dict[_HashCacheKey, str] = {}
_HASH_CACHE_MAX_SIZE = 1024


def _get_cached_hash(cache_key: _HashCacheKey) -> str | None:
    with _HASH_CACHE_LOCK:
        return _HASH_CACHE.get(cache_key)


def _set_cached_hash(cache_key: _HashCacheKey, digest: str) -> None:
    with _HASH_CACHE_LOCK:
        if len(_HASH_CACHE) >= _HASH_CACHE_MAX_SIZE:
            _HASH_CACHE.pop(next(iter(_HASH_CACHE)))
        _HASH_CACHE[cache_key] = digest


class HashUtils:
    """檔案雜湊工具類別"""

    @staticmethod
    def digest_bytes(content: bytes, algorithm: str = "sha256") -> str:
        """
        計算記憶體中位元組內容的雜湊

        Args:
            content: 要計算雜湊的位元組內容
            algorithm: 雜湊演算法名稱

        Returns:
            計算後的雜湊字串
        """
        try:
            return hashlib.new(str(algorithm).strip().lower(), content).hexdigest()
        except ValueError:
            return ""

    @staticmethod
    def normalize_expected_hash(
        digest: str | None,
        algorithm: str | None = None,
    ) -> tuple[str, str]:
        """
        驗證並正規化受支援的雜湊字串

        Args:
            digest: 原始雜湊字串
            algorithm: 雜湊演算法名稱（可選）

        Returns:
            (正規化的雜湊字串, 正規化的演算法名稱)，若驗證失敗則回傳 ("", "")
        """
        normalized_digest = str(digest or "").strip().lower()
        if not normalized_digest:
            return ("", "")
        normalized_algorithm = str(algorithm or "").strip().lower().replace("-", "")
        if not normalized_algorithm:
            normalized_algorithm = _HASH_ALGORITHM_BY_LENGTH.get(len(normalized_digest), "")
        expected_length = _SUPPORTED_HASH_LENGTHS.get(normalized_algorithm)
        if expected_length != len(normalized_digest):
            return ("", "")
        try:
            decoded = bytes.fromhex(normalized_digest)
        except ValueError:
            return ("", "")
        if len(decoded) * 2 != expected_length:
            return ("", "")
        return (normalized_digest, normalized_algorithm)

    @classmethod
    def is_valid_expected_hash(cls, digest: str | None, algorithm: str | None = None) -> bool:
        """
        判斷雜湊字串是否符合受支援演算法與 hexadecimal 格式

        Args:
            digest: 原始雜湊字串
            algorithm: 雜湊演算法名稱（可選）

        Returns:
            若符合則回傳 True，否則回傳 False
        """
        normalized_digest, normalized_algorithm = cls.normalize_expected_hash(digest, algorithm)
        return bool(normalized_digest and normalized_algorithm)

    @staticmethod
    def new_hasher(algorithm: str) -> Any | None:
        """
        建立受支援的雜湊

        Args:
            algorithm: 雜湊演算法名稱

        Returns:
            建立成功的雜湊器，若不支援則回傳 None
        """
        try:
            return hashlib.new(str(algorithm).strip().lower())
        except ValueError:
            return None

    @staticmethod
    def _digest_locked_file(source: Any, algorithm: str, max_bytes: int) -> str:
        """計算已拒絕並行寫入檔案的雜湊"""
        if max_bytes < 0 or os.fstat(source.fileno()).st_size > max_bytes:
            return ""
        return hashlib.file_digest(source, str(algorithm).strip().lower()).hexdigest()

    @staticmethod
    def compute_file_hash_sync(
        file_path: str | Path,
        algorithm: str = "sha256",
        *,
        max_bytes: int = SAFE_HASH_FILE_MAX_BYTES,
        allowed_root: str | Path | None = None,
    ) -> str:
        """
        同步計算檔案雜湊值

        Args:
            file_path: 要計算雜湊的檔案路徑
            algorithm: 雜湊演算法名稱
            max_bytes: 可讀取的最大檔案大小
            allowed_root: 可選的實際路徑根目錄

        Returns:
            計算後的雜湊字串；失敗時回傳空字串
        """
        normalized_algorithm = str(algorithm).strip().lower()
        normalized_path = str(file_path).strip()
        if not normalized_path:
            return ""

        try:
            limit = int(max_bytes)
            if limit < 0:
                return ""
            with open_regular_file(
                normalized_path,
                allowed_root=allowed_root,
                deny_write_sharing=True,
            ) as source:
                return HashUtils._digest_locked_file(source, normalized_algorithm, limit)
        except ValueError:
            logger.warning(f"不支援的檔案雜湊演算法: {normalized_algorithm}")
            return ""
        except OSError as e:
            logger.warning(f"計算檔案雜湊失敗 {normalized_path}: {e}")
            return ""

    @staticmethod
    def compute_file_hash(
        file_path: str | Path,
        algorithm: str = "sha256",
        use_cache: bool = True,
        *,
        max_bytes: int = SAFE_HASH_FILE_MAX_BYTES,
        allowed_root: str | Path | None = None,
    ) -> str:
        """
        計算檔案雜湊值（適用於單次呼叫或大量小檔呼叫）

        Args:
            file_path: 要計算雜湊的檔案路徑
            algorithm: 雜湊演算法名稱
            use_cache: 是否使用快取
            max_bytes: 可讀取的最大檔案大小
            allowed_root: 可選的實際路徑根目錄

        Returns:
            計算後的雜湊字串；失敗時回傳空字串
        """
        normalized_path = str(file_path).strip()
        if not normalized_path:
            return ""

        if not use_cache:
            return HashUtils.compute_file_hash_sync(
                normalized_path,
                str(algorithm),
                max_bytes=max_bytes,
                allowed_root=allowed_root,
            )

        try:
            limit = int(max_bytes)
            if limit < 0:
                return ""
            with open_regular_file(
                normalized_path,
                allowed_root=allowed_root,
                deny_write_sharing=True,
            ) as source:
                stat_result = os.fstat(source.fileno())
                if stat_result.st_size > limit:
                    return ""
                normalized_algorithm = str(algorithm).strip().lower()
                cache_key = (
                    normalized_path,
                    normalized_algorithm,
                    int(stat_result.st_dev),
                    int(stat_result.st_ino),
                    int(stat_result.st_mtime_ns),
                    int(stat_result.st_ctime_ns),
                    int(stat_result.st_size),
                    limit,
                    str(allowed_root) if allowed_root is not None else None,
                )
                cached = _get_cached_hash(cache_key)
                if cached is not None:
                    return cached
                digest = HashUtils._digest_locked_file(source, normalized_algorithm, limit)
                _set_cached_hash(cache_key, digest)
                return digest
        except ValueError:
            logger.warning(f"不支援的檔案雜湊演算法: {algorithm}")
            return ""
        except OSError as e:
            logger.warning(f"計算檔案雜湊失敗 {normalized_path}: {e}")
            return ""


__all__ = ["SAFE_HASH_FILE_MAX_BYTES", "HashUtils"]
