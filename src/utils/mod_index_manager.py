#!/usr/bin/env python3
"""
模組索引管理器 - 提供增量索引以加速模組掃描
Mod Index Manager - Provides incremental indexing for faster mod scanning
"""

import hashlib
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import get_logger

logger = get_logger().bind(component="ModIndexManager")


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
        self._index: dict[str, dict[str, Any]] = {}
        self._dirty = False
        self._last_save_ts = 0.0
        self._autosave_interval_sec = 1.0
        self._load_index()

    def _load_index(self) -> None:
        """從磁碟載入索引"""
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
        if not self._dirty and not force:
            return
        now = time.time()
        if not force and (now - self._last_save_ts) < self._autosave_interval_sec:
            return
        self._save_index()

    @staticmethod
    @lru_cache(maxsize=128)
    def _compute_file_hash(file_path: str, chunk_size: int = 65536) -> str:
        """
        計算檔案的 SHA256 哈希值（用於檢測檔案變更）
        Args:
            file_path: 檔案路徑
            chunk_size: 讀取大小
        Returns:
            SHA256 哈希值（十六進制）
        """
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(chunk_size), b""):
                    sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
        except Exception as e:
            logger.warning(f"無法計算檔案哈希: {e}")
            return ""

    def should_reindex_file(self, file_path: Path) -> bool:
        """
        檢查檔案是否需要重新索引
        Args:
            file_path: JAR 檔案路徑
        Returns:
            True 如果檔案需要重新索引，False 表示可以使用快取
        """
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
        if not self.should_reindex_file(file_path):
            file_name = file_path.name
            cached = self._index.get(file_name, {})
            metadata = cached.get("metadata")
            if metadata:
                logger.debug(f"使用快取元資料: {file_name}")
                return metadata
        return None

    def cache_metadata(self, file_path: Path, metadata: dict[str, Any]) -> None:
        """
        快取模組元資料
        Args:
            file_path: JAR 檔案路徑
            metadata: 模組元資料
        """
        file_name = file_path.name
        try:
            stat = file_path.stat()
            self._index[file_name] = {
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "timestamp": time.time(),
                "metadata": metadata,
            }
            self._dirty = True
            logger.debug(f"已快取元資料: {file_name}")
            self._save_index_if_due()
        except Exception as e:
            logger.warning(f"無法快取模組元資料: {e}")

    def cleanup_stale_entries(self) -> int:
        """
        清理不存在的檔案對應的索引項
        Returns:
            清理的項目數
        """
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
        return {
            "total_cached": len(self._index),
            "index_file": str(self.index_file),
            "last_updated": self.index_file.stat().st_mtime if self.index_file.exists() else 0,
        }

    def clear_cache(self) -> None:
        """清空整個索引快取"""
        self._index.clear()
        self._dirty = False
        if self.index_file.exists():
            self.index_file.unlink()
        logger.info("已清空模組索引快取")

    def flush(self) -> None:
        """立即保存尚未落盤的索引內容。"""
        self._save_index_if_due(force=True)
