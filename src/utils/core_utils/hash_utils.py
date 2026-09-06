"""
檔案雜湊工具
提供同步與非同步的檔案雜湊計算，並使用背景工作池避免阻塞主執行緒
"""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from src.utils import get_logger

from .filesystem_utils import open_regular_file

logger = get_logger().bind(component="HashUtils")
SAFE_HASH_FILE_MAX_BYTES = 512 * 1024 * 1024
_SUPPORTED_HASH_LENGTHS = {"sha1": 40, "sha256": 64, "sha512": 128}
_HASH_ALGORITHM_BY_LENGTH = {length: name for name, length in _SUPPORTED_HASH_LENGTHS.items()}


class HashUtils:
    """檔案雜湊工具類別"""

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
            bytes.fromhex(normalized_digest)
        except ValueError:
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
            with open_regular_file(normalized_path, allowed_root=allowed_root) as source:
                if os.fstat(source.fileno()).st_size > limit:
                    return ""
                return hashlib.file_digest(cast(Any, source), normalized_algorithm).hexdigest()
        except ValueError:
            logger.warning(f"不支援的檔案雜湊演算法: {normalized_algorithm}")
            return ""
        except OSError as e:
            logger.warning(f"計算檔案雜湊失敗 {normalized_path}: {e}")
            return ""

    @staticmethod
    @lru_cache(maxsize=1024)
    def _compute_file_hash_cached_internal(cache_key: tuple[str, str, int, int, int, int, str | None]) -> str:
        """依檔案路徑、演算法與檔案狀態快取雜湊，避免同路徑內容更新後命中舊值"""
        file_path, algorithm, mtime_ns, ctime_ns, size, max_bytes, allowed_root = cache_key
        try:
            with open_regular_file(file_path, allowed_root=allowed_root) as source:
                stat_result = os.fstat(source.fileno())
                current_state = (stat_result.st_mtime_ns, stat_result.st_ctime_ns, stat_result.st_size)
                if stat_result.st_size > max_bytes:
                    return ""
                if current_state != (mtime_ns, ctime_ns, size):
                    logger.debug(f"檔案狀態在雜湊前變更: {file_path}")
                return hashlib.file_digest(cast(Any, source), algorithm).hexdigest()
        except ValueError:
            logger.warning(f"不支援的檔案雜湊演算法: {algorithm}")
            return ""
        except OSError as e:
            logger.warning(f"計算檔案雜湊失敗 {file_path}: {e}")
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
            with open_regular_file(normalized_path, allowed_root=allowed_root) as source:
                stat_result = os.fstat(source.fileno())
                if stat_result.st_size > int(max_bytes):
                    return ""
        except OSError as e:
            logger.warning(f"無法讀取檔案狀態以計算雜湊: {e}")
            return ""

        return HashUtils._compute_file_hash_cached_internal(
            (
                normalized_path,
                str(algorithm).strip().lower(),
                int(stat_result.st_mtime_ns),
                int(stat_result.st_ctime_ns),
                int(stat_result.st_size),
                int(max_bytes),
                str(allowed_root) if allowed_root is not None else None,
            )
        )


__all__ = ["SAFE_HASH_FILE_MAX_BYTES", "HashUtils"]
