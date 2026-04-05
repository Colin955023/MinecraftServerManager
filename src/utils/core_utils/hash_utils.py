"""檔案雜湊工具。

提供同步與非同步的檔案雜湊計算，並使用背景 worker pool 避免阻塞主執行緒。
"""

import asyncio
import concurrent.futures
import hashlib
import os
from functools import lru_cache
from pathlib import Path

from .logger import get_logger

logger = get_logger().bind(component="HashUtils")

_HASH_EXECUTOR: concurrent.futures.ThreadPoolExecutor | None = None
_DEFAULT_HASH_WORKERS = 4


def _get_hash_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _HASH_EXECUTOR
    if _HASH_EXECUTOR is None:
        # 硬體感知：根據 CPU 核心數設定並行數量
        workers = min(_DEFAULT_HASH_WORKERS, max(1, os.cpu_count() or _DEFAULT_HASH_WORKERS))
        _HASH_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="hash_worker")
    return _HASH_EXECUTOR


def compute_file_hash_sync(file_path: str | Path, algorithm: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
    """同步計算檔案雜湊值。

    Args:
        file_path: 要計算雜湊的檔案路徑。
        algorithm: 雜湊演算法名稱。
        chunk_size: 每次讀取的區塊大小。

    Returns:
        計算後的雜湊字串；失敗時回傳空字串。
    """
    normalized_algorithm = str(algorithm).strip().lower()
    normalized_path = str(file_path).strip()
    if not normalized_path:
        return ""

    try:
        hasher = hashlib.new(normalized_algorithm)
    except ValueError:
        logger.warning(f"不支援的檔案哈希演算法: {normalized_algorithm}")
        return ""

    try:
        with open(normalized_path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError as e:
        logger.warning(f"計算檔案雜湊失敗 {normalized_path}: {e}")
        return ""


@lru_cache(maxsize=1024)
def _compute_file_hash_cached_internal(
    file_path: str, algorithm: str, mtime_ns: int, file_size: int, chunk_size: int
) -> str:
    """
    透過快取避免重複計算，並發派任務到 ThreadPoolExecutor 防止阻塞主執行緒。
    """
    del mtime_ns, file_size  # 用於快取鍵值
    executor = _get_hash_executor()
    future = executor.submit(compute_file_hash_sync, file_path, algorithm, chunk_size)
    return future.result()


def compute_file_hash(
    file_path: str | Path, algorithm: str = "sha256", chunk_size: int = 1024 * 1024, use_cache: bool = True
) -> str:
    """計算檔案雜湊值（適用於單次呼叫或大量小檔呼叫）。

    Args:
        file_path: 要計算雜湊的檔案路徑。
        algorithm: 雜湊演算法名稱。
        chunk_size: 每次讀取的區塊大小。
        use_cache: 是否使用快取。

    Returns:
        計算後的雜湊字串；失敗時回傳空字串。
    """
    normalized_path = str(file_path).strip()
    if not normalized_path:
        return ""

    if not use_cache:
        executor = _get_hash_executor()
        future = executor.submit(compute_file_hash_sync, normalized_path, str(algorithm), int(chunk_size))
        return future.result()

    try:
        stat = Path(normalized_path).stat()
    except OSError as e:
        logger.warning(f"無法讀取檔案狀態以計算哈希: {e}")
        return ""

    return _compute_file_hash_cached_internal(
        normalized_path, str(algorithm).lower(), int(stat.st_mtime_ns), int(stat.st_size), int(chunk_size)
    )


async def compute_file_hash_async(
    file_path: str | Path, algorithm: str = "sha256", chunk_size: int = 1024 * 1024, use_cache: bool = True
) -> str:
    """非同步計算檔案雜湊值。

    Args:
        file_path: 要計算雜湊的檔案路徑。
        algorithm: 雜湊演算法名稱。
        chunk_size: 每次讀取的區塊大小。
        use_cache: 是否使用快取。

    Returns:
        計算後的雜湊字串；失敗時回傳空字串。
    """
    return await asyncio.to_thread(compute_file_hash, str(file_path), algorithm, chunk_size, use_cache)
