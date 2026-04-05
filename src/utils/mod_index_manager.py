"""模組索引管理器：提供增量索引以加速模組掃描。"""

import ctypes
import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from . import atomic_write_json, compute_file_hash, get_logger

logger = get_logger().bind(component="ModIndexManager")
DEFAULT_INDEX_HASH_ALGORITHM = "sha512"
INDEX_SCHEMA_VERSION = 1


# hash 工作池（共享）：預設 4 個工作執行緒。
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
        # 在 index 目錄內建立說明檔，並在 Windows 上嘗試將資料夾設為隱藏，避免使用者誤刪或困惑
        try:
            readme = self.index_dir / "README.txt"
            if not readme.exists():
                readme_content = (
                    "這個目錄由 Minecraft Server Manager 用於快取模組索引與檔案hash。\n"
                    "可安全刪除，程式會在下次掃描/啟動時重建索引，但刪除會造成下次掃描較慢。\n"
                )
                readme.write_text(readme_content, encoding="utf-8")
            if os.name == "nt":
                try:
                    FILE_ATTRIBUTE_HIDDEN = 0x02
                    ctypes.windll.kernel32.SetFileAttributesW(str(self.index_dir), FILE_ATTRIBUTE_HIDDEN)
                except (AttributeError, OSError):
                    # 無法設為隱藏則忽略
                    logger.debug("無法設定資料夾隱藏屬性，忽略")
        except OSError as e:
            logger.debug(f"初始化索引目錄時發生 OSError: {e}")
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
                        raw_payload = json.load(f)
                    self._index = self._normalize_loaded_payload(raw_payload)
                    logger.info(f"模組索引已載入，包含 {len(self._index)} 個項目")
                except (OSError, json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"無法載入索引檔案: {e}，將重新建立")
                    self._index = {}
            else:
                logger.info("未找到現有索引，將建立新索引")
                self._index = {}
            repaired_count = self.repair_index_entries()
            if repaired_count > 0:
                logger.info(f"模組索引修復完成，已修復 {repaired_count} 個項目")
                self._save_index_if_due(force=True)

    def _normalize_loaded_payload(self, payload: Any) -> dict[str, dict[str, Any]]:
        """將磁碟 payload 正規化為 entries 字典，支援舊版格式遷移。"""
        if not isinstance(payload, dict):
            logger.warning("索引檔案格式不是物件，將忽略並重建")
            return {}
        if "entries" in payload:
            entries = payload.get("entries")
            schema_version = payload.get("schema_version", 0)
            if schema_version != INDEX_SCHEMA_VERSION:
                logger.info(f"模組索引 schema 版本遷移: {schema_version} -> {INDEX_SCHEMA_VERSION}")
            if not isinstance(entries, dict):
                logger.warning("索引 entries 欄位格式錯誤，將忽略並重建")
                return {}
            normalized_entries: dict[str, dict[str, Any]] = {}
            for key, value in entries.items():
                if isinstance(key, str) and isinstance(value, dict):
                    normalized_entries[key] = dict(value)
            return normalized_entries
        logger.info("偵測到舊版索引格式，將自動遷移至 schema v1")
        normalized_entries = {}
        for key, value in payload.items():
            if isinstance(key, str) and isinstance(value, dict):
                normalized_entries[key] = dict(value)
        return normalized_entries

    def _build_persist_payload(self) -> dict[str, Any]:
        """建構落盤 payload，保留 schema metadata 以支援未來演進。"""
        return {"schema_version": INDEX_SCHEMA_VERSION, "entries": self._index}

    def _save_index(self) -> None:
        """將索引保存為 JSON"""
        with self._index_lock:
            try:
                payload = self._build_persist_payload()
                ok = atomic_write_json(self.index_file, payload)
                if ok:
                    logger.debug("模組索引已保存 (atomic)")
                    self._dirty = False
                    self._last_save_ts = time.time()
                else:
                    logger.warning("模組索引保存失敗（atomic write 返回 false）")
            except (OSError, TypeError, ValueError) as e:
                logger.warning(f"無法保存索引檔案: {e}")

    def repair_index_entries(self) -> int:
        """修復索引資料型別與欄位結構。

        Returns:
            已修復的索引項目數量。
        """
        repaired_count = 0
        with self._index_lock:
            sanitized: dict[str, dict[str, Any]] = {}
            for file_name, entry in self._index.items():
                if not isinstance(file_name, str):
                    repaired_count += 1
                    continue
                if not isinstance(entry, dict):
                    repaired_count += 1
                    continue
                normalized_entry = dict(entry)
                hashes = normalized_entry.get("hashes")
                if hashes is not None and (not isinstance(hashes, dict)):
                    normalized_entry.pop("hashes", None)
                    repaired_count += 1
                metadata = normalized_entry.get("metadata")
                if metadata is not None and (not isinstance(metadata, dict)):
                    normalized_entry.pop("metadata", None)
                    repaired_count += 1
                provider_metadata = normalized_entry.get("provider_metadata")
                if provider_metadata is not None and (not isinstance(provider_metadata, dict)):
                    normalized_entry.pop("provider_metadata", None)
                    repaired_count += 1
                sanitized[file_name] = normalized_entry
            if repaired_count > 0:
                self._index = sanitized
                self._dirty = True
        return repaired_count

    def get_index_consistency_report(self) -> dict[str, Any]:
        """回傳索引一致性檢查結果，供觀測與診斷使用。

        Returns:
            索引一致性摘要資料。
        """
        with self._index_lock:
            invalid_entries = 0
            missing_stats = 0
            for entry in self._index.values():
                if not isinstance(entry, dict):
                    invalid_entries += 1
                    continue
                if "size" not in entry or "mtime" not in entry:
                    missing_stats += 1
            return {
                "schema_version": INDEX_SCHEMA_VERSION,
                "total_entries": len(self._index),
                "invalid_entries": invalid_entries,
                "entries_missing_file_stats": missing_stats,
            }

    def _save_index_if_due(self, *, force: bool = False) -> None:
        """依時間節流保存索引，避免每個檔案都立即落盤。"""
        with self._index_lock:
            if not self._dirty and (not force):
                return
            now = time.time()
            if not force and now - self._last_save_ts < self._autosave_interval_sec:
                return
            self._save_index()

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
                entry.update({"size": stat.st_size, "mtime": stat.st_mtime, "timestamp": time.time()})
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
                return True
            cached_entry = self._index[file_name]
            try:
                current_stat = file_path.stat()
                if current_stat.st_size != cached_entry.get("size", 0) or current_stat.st_mtime != cached_entry.get(
                    "mtime", 0
                ):
                    return True
            except OSError:
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
        """獲取快取的指定演算法哈希值。

        Args:
            file_path: 檔案路徑。
            algorithm: 哈希演算法名稱。

        Returns:
            快取中的雜湊值；不存在時回傳空字串。
        """
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
        """快取 provider metadata，供後續更新與比對使用。

        Args:
            file_path: 檔案路徑。
            provider_metadata: 要寫入的 provider metadata。
            merge: 是否與既有快取合併。
        """
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
        """快取指定演算法的檔案哈希值。

        Args:
            file_path: 檔案路徑。
            algorithm: 哈希演算法名稱。
            file_hash: 計算後的雜湊值。
        """
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
        """確保指定演算法的檔案哈希已寫入索引，並回傳該值。

        Args:
            file_path: 檔案路徑。
            algorithm: 哈希演算法名稱。

        Returns:
            索引中的雜湊值；若尚未存在且無法計算，回傳空字串。
        """
        normalized_algorithm = (
            str(algorithm or DEFAULT_INDEX_HASH_ALGORITHM).strip().lower() or DEFAULT_INDEX_HASH_ALGORITHM
        )
        cached_hash = self.get_cached_hash(file_path, normalized_algorithm)
        if cached_hash:
            return cached_hash
        computed_hash = compute_file_hash(str(file_path), normalized_algorithm)
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
        """獲取索引統計資訊。

        Returns:
            索引統計摘要。
        """
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
