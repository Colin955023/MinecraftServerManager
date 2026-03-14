#!/usr/bin/env python3
"""
模組索引管理器 - 提供增量索引以加速模組掃描
Mod Index Manager - Provides incremental indexing for faster mod scanning
"""

import hashlib
import json
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import get_logger

logger = get_logger().bind(component="ModIndexManager")

DEFAULT_INDEX_HASH_ALGORITHM = "sha512"


class ModIndexManager:
    """
    管理模組 JAR 檔案的增量索引
    通過快取檔案哈希值和元資料，避免重複掃描未變更的檔案
    """

    def __init__(self, server_path: str, index_dir: str | None = None):
        """
        初始化索引管理器
        Args:
            server_path: 伺服器路徑
            index_dir: 索引檔案保存目錄，預設為伺服器路徑下的 .modcache
        """
        self.server_path = Path(server_path)
        self.mods_path = self.server_path / "mods"
        self.index_dir = Path(index_dir) if index_dir else self.server_path / ".modcache"
        self.index_file = self.index_dir / "mod_index.json"
        self.index_dir.mkdir(exist_ok=True)

        # 內存索引
        self._index_lock = threading.RLock()
        self._index: dict[str, dict[str, Any]] = {}
        self._dirty = False
        self._last_save_ts = 0.0
        self._autosave_interval_sec = 1.0
        self._load_index()

    def _load_index(self) -> None:
        """從磁碟載入索引"""
        with self._index_lock:
            if self.index_file.exists():
                try:
                    with open(self.index_file, encoding="utf-8") as f:
                        self._index = json.load(f)
                    logger.info(f"模組索引已載入，包含 {len(self._index)} 個項目")
                except Exception as e:
                    logger.warning(f"無法載入索引檔案: {e}，將重新建立")
                    self._index = {}
            else:
                logger.info("未找到現有索引，將建立新索引")
                self._index = {}

    def _save_index(self) -> None:
        """將索引保存為 JSON"""
        with self._index_lock:
            try:
                with open(self.index_file, "w", encoding="utf-8") as f:
                    json.dump(self._index, f, indent=2, ensure_ascii=False)
                logger.debug("模組索引已保存")
                self._dirty = False
                self._last_save_ts = time.time()
            except Exception as e:
                logger.warning(f"無法保存索引檔案: {e}")

    def _save_index_if_due(self, *, force: bool = False) -> None:
        """依時間節流保存索引，避免每個檔案都立即落盤。"""
        with self._index_lock:
            if not self._dirty and not force:
                return
            now = time.time()
            if not force and (now - self._last_save_ts) < self._autosave_interval_sec:
                return
            self._save_index()

    @staticmethod
    @lru_cache(maxsize=256)
    def _compute_file_hash_cached(
        file_path: str,
        algorithm: str,
        mtime_ns: int,
        file_size: int,
        chunk_size: int = 65536,
    ) -> str:
        """
        計算檔案哈希值（用於檢測檔案變更與 provider 更新檢查）
        Args:
            file_path: 檔案路徑
            algorithm: 雜湊演算法名稱
            chunk_size: 讀取大小
        Returns:
            哈希值（十六進制）
        """
        del mtime_ns, file_size
        normalized_algorithm = (
            str(algorithm or DEFAULT_INDEX_HASH_ALGORITHM).strip().lower() or DEFAULT_INDEX_HASH_ALGORITHM
        )
        try:
            file_hash = hashlib.new(normalized_algorithm)
        except ValueError:
            logger.warning(f"不支援的檔案哈希演算法: {normalized_algorithm}")
            return ""

        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(chunk_size), b""):
                    file_hash.update(chunk)
            return file_hash.hexdigest()
        except Exception as e:
            logger.warning(f"無法計算檔案哈希: {e}")
            return ""

    @staticmethod
    def _compute_file_hash(
        file_path: str, algorithm: str = DEFAULT_INDEX_HASH_ALGORITHM, chunk_size: int = 65536
    ) -> str:
        """計算檔案哈希值，快取鍵會納入 mtime/size 避免內容替換後命中舊值。"""
        normalized_algorithm = (
            str(algorithm or DEFAULT_INDEX_HASH_ALGORITHM).strip().lower() or DEFAULT_INDEX_HASH_ALGORITHM
        )
        try:
            stat = Path(file_path).stat()
        except OSError as e:
            logger.warning(f"無法讀取檔案狀態以計算哈希: {e}")
            return ""

        return ModIndexManager._compute_file_hash_cached(
            str(file_path),
            normalized_algorithm,
            int(stat.st_mtime_ns),
            int(stat.st_size),
            int(chunk_size),
        )

    def _get_valid_entry(self, file_path: Path) -> dict[str, Any] | None:
        with self._index_lock:
            if self.should_reindex_file(file_path):
                return None

            file_name = file_path.name
            cached = self._index.get(file_name)
            if isinstance(cached, dict):
                return cached
            return None

    def _update_entry(self, file_path: Path, **updates: Any) -> None:
        file_name = file_path.name
        with self._index_lock:
            try:
                stat = file_path.stat()
                cached = self._index.get(file_name, {})
                entry = dict(cached) if isinstance(cached, dict) else {}
                entry.update(
                    {
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                        "timestamp": time.time(),
                    }
                )
                entry.update(updates)
                self._index[file_name] = entry
                self._dirty = True
                self._save_index_if_due()
            except Exception as e:
                logger.warning(f"無法更新模組索引項目 {file_name}: {e}")

    def should_reindex_file(self, file_path: Path) -> bool:
        """
        檢查檔案是否需要重新索引
        Args:
            file_path: JAR 檔案路徑
        Returns:
            True 如果檔案需要重新索引，False 表示可以使用快取
        """
        with self._index_lock:
            file_name = file_path.name
            if file_name not in self._index:
                return True  # 新檔案，需要索引

            cached_entry = self._index[file_name]

            # 檢查檔案大小和修改時間作為快速判斷
            try:
                current_stat = file_path.stat()
                if current_stat.st_size != cached_entry.get("size", 0) or current_stat.st_mtime != cached_entry.get(
                    "mtime", 0
                ):
                    return True
            except Exception:
                return True

            return False

    def get_cached_metadata(self, file_path: Path) -> dict[str, Any] | None:
        """
        獲取快取的模組元資料
        Args:
            file_path: JAR 檔案路徑
        Returns:
            快取的元資料字典，如果檔案變更則返回 None
        """
        cached = self._get_valid_entry(file_path)
        if cached:
            metadata = cached.get("metadata")
            if isinstance(metadata, dict) and metadata:
                logger.debug(f"使用快取元資料: {file_path.name}")
                return metadata
        return None

    def get_cached_provider_metadata(self, file_path: Path) -> dict[str, Any] | None:
        """獲取快取的 provider metadata。"""
        cached = self._get_valid_entry(file_path)
        if cached:
            provider_metadata = cached.get("provider_metadata")
            if isinstance(provider_metadata, dict) and provider_metadata:
                logger.debug(f"使用快取 provider metadata: {file_path.name}")
                return provider_metadata
        return None

    def get_cached_hash(self, file_path: Path, algorithm: str = DEFAULT_INDEX_HASH_ALGORITHM) -> str:
        """獲取快取的指定演算法哈希值。"""
        normalized_algorithm = (
            str(algorithm or DEFAULT_INDEX_HASH_ALGORITHM).strip().lower() or DEFAULT_INDEX_HASH_ALGORITHM
        )
        cached = self._get_valid_entry(file_path)
        if not cached:
            return ""

        hashes = cached.get("hashes")
        if not isinstance(hashes, dict):
            return ""
        return str(hashes.get(normalized_algorithm, "") or "").strip().lower()

    def cache_metadata(self, file_path: Path, metadata: dict[str, Any]) -> None:
        """
        快取模組元資料
        Args:
            file_path: JAR 檔案路徑
            metadata: 模組元資料
        """
        try:
            self._update_entry(file_path, metadata=dict(metadata or {}))
            logger.debug(f"已快取元資料: {file_path.name}")
        except Exception as e:
            logger.warning(f"無法快取模組元資料: {e}")

    def cache_provider_metadata(
        self, file_path: Path, provider_metadata: dict[str, Any], *, merge: bool = True
    ) -> None:
        """快取 provider metadata，供後續更新與比對使用。"""
        normalized_metadata = {
            str(key): value for key, value in dict(provider_metadata or {}).items() if value not in (None, "", [], {})
        }
        if not normalized_metadata:
            return

        try:
            cached_provider = self.get_cached_provider_metadata(file_path) or {}
            merged_provider = dict(cached_provider) if merge else {}
            merged_provider.update(normalized_metadata)
            self._update_entry(file_path, provider_metadata=merged_provider)
            logger.debug(f"已快取 provider metadata: {file_path.name}")
        except Exception as e:
            logger.warning(f"無法快取 provider metadata: {e}")

    def cache_file_hash(self, file_path: Path, algorithm: str, file_hash: str) -> None:
        """快取指定演算法的檔案哈希值。"""
        normalized_algorithm = (
            str(algorithm or DEFAULT_INDEX_HASH_ALGORITHM).strip().lower() or DEFAULT_INDEX_HASH_ALGORITHM
        )
        normalized_hash = str(file_hash or "").strip().lower()
        if not normalized_hash:
            return

        try:
            cached = self._get_valid_entry(file_path) or self._index.get(file_path.name, {})
            hashes = dict(cached.get("hashes", {})) if isinstance(cached, dict) else {}
            hashes[normalized_algorithm] = normalized_hash
            self._update_entry(file_path, hashes=hashes)
            logger.debug(f"已快取檔案哈希: {file_path.name} ({normalized_algorithm})")
        except Exception as e:
            logger.warning(f"無法快取檔案哈希: {e}")

    def ensure_cached_hash(self, file_path: Path, algorithm: str = DEFAULT_INDEX_HASH_ALGORITHM) -> str:
        """確保指定演算法的檔案哈希已寫入索引，並回傳該值。"""
        normalized_algorithm = (
            str(algorithm or DEFAULT_INDEX_HASH_ALGORITHM).strip().lower() or DEFAULT_INDEX_HASH_ALGORITHM
        )
        cached_hash = self.get_cached_hash(file_path, normalized_algorithm)
        if cached_hash:
            return cached_hash

        computed_hash = self._compute_file_hash(str(file_path), normalized_algorithm)
        if computed_hash:
            self.cache_file_hash(file_path, normalized_algorithm, computed_hash)
        return computed_hash

    def cleanup_stale_entries(self) -> int:
        """
        清理不存在的檔案對應的索引項
        Returns:
            清理的項目數
        """
        with self._index_lock:
            files_to_remove = []
            for file_name in self._index:
                file_path = self.mods_path / file_name
                if not file_path.exists():
                    files_to_remove.append(file_name)

            for file_name in files_to_remove:
                del self._index[file_name]
                logger.debug(f"已清理過期索引: {file_name}")

            if files_to_remove:
                self._dirty = True
                self._save_index_if_due(force=True)

            return len(files_to_remove)

    def get_statistics(self) -> dict[str, Any]:
        """獲取索引統計信息"""
        with self._index_lock:
            return {
                "total_cached": len(self._index),
                "index_file": str(self.index_file),
                "last_updated": self.index_file.stat().st_mtime if self.index_file.exists() else 0,
            }

    def clear_cache(self) -> None:
        """清空整個索引快取"""
        with self._index_lock:
            self._index.clear()
            self._dirty = False
            if self.index_file.exists():
                self.index_file.unlink()
            logger.info("已清空模組索引快取")

    def flush(self) -> None:
        """立即保存尚未落盤的索引內容。"""
        self._save_index_if_due(force=True)
