"""
檔案雜湊工具
提供同步與非同步的檔案雜湊計算，並使用背景工作池避免阻塞主執行緒
"""

import hashlib
from functools import lru_cache
from pathlib import Path

from .logger import get_logger

logger = get_logger().bind(component="HashUtils")

__all__ = [
    "HashUtils",
]


class HashUtils:
    """檔案雜湊工具類別"""

    @staticmethod
    def compute_file_hash_sync(file_path: str | Path, algorithm: str = "sha256") -> str:
        """
        同步計算檔案雜湊值

        Args:
            file_path: 要計算雜湊的檔案路徑
            algorithm: 雜湊演算法名稱

        Returns:
            計算後的雜湊字串；失敗時回傳空字串
        """
        normalized_algorithm = str(algorithm).strip().lower()
        normalized_path = str(file_path).strip()
        if not normalized_path:
            return ""

        try:
            with Path(normalized_path).open("rb") as f:
                digest = hashlib.file_digest(f, normalized_algorithm)
            return digest.hexdigest()
        except ValueError:
            logger.warning(f"不支援的檔案哈希演算法: {normalized_algorithm}")
            return ""
        except OSError as e:
            logger.warning(f"計算檔案雜湊失敗 {normalized_path}: {e}")
            return ""

    @staticmethod
    @lru_cache(maxsize=1024)
    def _compute_file_hash_cached_internal(file_path: str, algorithm: str) -> str:
        """透過快取避免重複計算"""
        return HashUtils.compute_file_hash_sync(file_path, algorithm)

    @staticmethod
    def compute_file_hash(
        file_path: str | Path, algorithm: str = "sha256", chunk_size: int = 1024 * 1024, use_cache: bool = True
    ) -> str:
        """
        計算檔案雜湊值（適用於單次呼叫或大量小檔呼叫）

        Args:
            file_path: 要計算雜湊的檔案路徑
            algorithm: 雜湊演算法名稱
            use_cache: 是否使用快取

        Returns:
            計算後的雜湊字串；失敗時回傳空字串
        """
        normalized_path = str(file_path).strip()
        if not normalized_path:
            return ""

        if not use_cache:
            return HashUtils.compute_file_hash_sync(normalized_path, str(algorithm))

        try:
            stat = Path(normalized_path).stat()
        except OSError as e:
            logger.warning(f"無法讀取檔案狀態以計算哈希: {e}")
            return ""

        return HashUtils._compute_file_hash_cached_internal(
            normalized_path, str(algorithm).lower(), int(stat.st_mtime_ns), int(stat.st_size), int(chunk_size)
        )
