"""模組索引管理器：提供增量索引以加速模組掃描"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from pathlib import Path
from typing import Any

import orjson

from src.utils import HashUtils, atomic_write_json, atomic_write_text, get_logger

logger = get_logger().bind(component="ModIndexManager")
DEFAULT_INDEX_HASH_ALGORITHM = "sha512"
INDEX_SCHEMA_VERSION = 2


class ModIndexManager:
    """
    管理模組 JAR 檔案的增量索引
    通過快取檔案雜湊值和中繼資料，避免重複掃描未變更的檔案
    """

    def __init__(self, server_path: str, index_dir: str | None = None):
        """初始化索引管理器"""
        self.server_path = Path(server_path)
        self.mods_path = self.server_path / "mods"
        self.index_dir = Path(index_dir) if index_dir else self.server_path / ".modcache"
        self.index_file = self.index_dir / "mod_index.json"
        self.index_dir.mkdir(exist_ok=True)

        try:
            readme = self.index_dir / "README.txt"
            if not readme.exists():
                readme_content = (
                    "這個目錄由 Minecraft Server Manager 用於快取模組索引與檔案雜湊\n"
                    "可安全刪除，程式會在下次掃描/啟動時重建索引，但刪除會造成下次掃描較慢\n"
                )
                atomic_write_text(readme, readme_content, encoding="utf-8")
            if os.name == "nt":
                try:
                    FILE_ATTRIBUTE_HIDDEN = 0x02
                    ctypes.windll.kernel32.SetFileAttributesW(str(self.index_dir), FILE_ATTRIBUTE_HIDDEN)
                except AttributeError, OSError:
                    logger.debug("無法設定資料夾隱藏屬性，已略過")
        except OSError as e:
            logger.debug(f"初始化索引目錄時發生 OSError: {e}")
        self._index_lock = threading.RLock()
        self._index: dict[str, dict[str, Any]] = {}
        self._dirty = False
        self._last_save_ts = 0.0
        self._autosave_interval_sec = 1.0
        self._load_index()

    def repair_index_entries(self) -> int:
        """
        修復索引資料型別與欄位結構

        Returns:
            已修復的索引項目數量
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
                for namespace in ("provider_identity", "review_metadata", "issue"):
                    value = normalized_entry.get(namespace)
                    if value is not None and not isinstance(value, dict):
                        normalized_entry.pop(namespace, None)
                        repaired_count += 1
                sanitized[file_name] = normalized_entry
            if repaired_count > 0:
                self._index = sanitized
                self._dirty = True
        return repaired_count

    def should_reindex_file(self, file_path: Path) -> bool:
        """
        檢查檔案是否需要重新索引

        Args:
            file_path: JAR 檔案路徑

        Returns:
            若檔案需要重新索引回傳 True，否則回傳 False 表示可以使用快取
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
        取得快取的模組中繼資料

        Args:
            file_path: JAR 檔案路徑

        Returns:
            快取的中繼資料字典，如果檔案變更則回傳 None
        """
        cached = self._get_valid_entry(file_path)
        if cached:
            metadata = cached.get("metadata")
            if isinstance(metadata, dict) and metadata:
                logger.debug(f"使用快取中繼資料: {file_path.name}")
                return metadata
        return None

    def get_provider_identity(self, file_path: Path) -> dict[str, Any] | None:
        """
        讀取 provider identity；舊 provider_metadata 只作一次性 migration evidence

        Args:
            file_path: 檔案路徑

        Returns:
            快取的 provider metadata 字典，如果檔案變更則回傳 None
        """
        cached = self._get_valid_entry(file_path)
        if cached:
            identity = cached.get("provider_identity")
            if isinstance(identity, dict) and identity:
                return dict(identity)
            legacy = cached.get("provider_metadata")
            if isinstance(legacy, dict) and legacy:
                return {key: value for key, value in legacy.items() if key != "dependency_plan_v1"}
        return None

    def get_review_metadata(self, file_path: Path) -> dict[str, Any] | None:
        """
        讀取與 provider identity 分離的 Review cache namespace

        Args:
            file_path: 檔案路徑

        Returns:
            快取的 Review metadata 字典，如果檔案變更則回傳 None
        """
        cached = self._get_valid_entry(file_path)
        if not cached:
            return None
        review_metadata = cached.get("review_metadata")
        if isinstance(review_metadata, dict) and review_metadata:
            return dict(review_metadata)
        legacy = cached.get("provider_metadata")
        if isinstance(legacy, dict) and isinstance(legacy.get("dependency_plan_v1"), dict):
            return {"dependency_plan_v1": legacy["dependency_plan_v1"]}
        return None

    def get_cached_hash(self, file_path: Path, algorithm: str = DEFAULT_INDEX_HASH_ALGORITHM) -> str:
        """
        取得快取的指定演算法雜湊值

        Args:
            file_path: 檔案路徑
            algorithm: 雜湊演算法名稱

        Returns:
            快取中的雜湊值；不存在時回傳空字串
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

    def cache_metadata(self, file_path: Path, metadata: dict[str, Any], *, clear_issue: bool = False) -> None:
        """
        快取模組中繼資料

        Args:
            file_path: JAR 檔案路徑
            metadata: 模組中繼資料
            clear_issue: 是否清除既有的檔案問題標記
        """
        try:
            updates: dict[str, Any] = {"metadata": dict(metadata or {})}
            if clear_issue:
                updates["issue"] = {}
            self._update_entry(file_path, **updates)
            logger.debug(f"已快取中繼資料: {file_path.name}")
        except Exception as e:
            logger.warning(f"無法快取模組中繼資料: {e}")

    def mark_issue(self, file_path: Path, reason: str) -> bool:
        """
        在模組索引中記錄檔案解析問題，不移動原始檔案

        Args:
            file_path: 發生問題的模組檔案
            reason: 穩定的問題原因代碼

        Returns:
            問題資料成功寫入索引時回傳 True
        """
        normalized_reason = str(reason or "unknown_error").strip() or "unknown_error"
        if not self._update_entry(
            file_path,
            issue={"reason": normalized_reason, "detected_at": time.time()},
        ):
            return False
        self._save_index_if_due(force=True)
        return True

    def replace_provider_identity(self, file_path: Path, provider_identity: dict[str, Any]) -> bool:
        """
        原子替換完整 identity payload，並搬移 legacy Review snapshot

        Args:
            file_path: 檔案路徑
            provider_identity: 要寫入的 provider identity

        Returns:
            完整 payload 已持久化時為 True
        """
        try:
            with self._index_lock:
                cached = self._get_valid_entry(file_path) or {}
                legacy = cached.get("provider_metadata")
                review_metadata = dict(cached.get("review_metadata", {})) if isinstance(cached, dict) else {}
                if isinstance(legacy, dict) and isinstance(legacy.get("dependency_plan_v1"), dict):
                    review_metadata.setdefault("dependency_plan_v1", legacy["dependency_plan_v1"])
                self._update_entry(
                    file_path,
                    provider_identity=dict(provider_identity),
                    provider_metadata={},
                    review_metadata=review_metadata,
                )
            logger.debug(f"已替換 provider identity: {file_path.name}")
            return True
        except Exception as e:
            logger.warning(f"無法替換 provider identity: {e}")
            return False

    def replace_review_metadata(self, file_path: Path, review_metadata: dict[str, Any]) -> None:
        """
        原子替換 Review cache namespace，不得改寫 provider identity

        Args:
            file_path: Review metadata 所屬的本地 Mod 檔案
            review_metadata: 要完整取代舊值的 Review cache payload
        """
        try:
            self._update_entry(file_path, review_metadata=dict(review_metadata))
        except Exception as e:
            logger.warning(f"無法替換 Review metadata: {e}")

    def cache_file_hash(self, file_path: Path, algorithm: str, file_hash: str) -> None:
        """
        快取指定演算法的檔案雜湊值

        Args:
            file_path: 檔案路徑
            algorithm: 雜湊演算法名稱
            file_hash: 計算後的雜湊值
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
            logger.debug(f"已快取檔案雜湊: {file_path.name} ({normalized_algorithm})")
        except Exception as e:
            logger.warning(f"無法快取檔案雜湊: {e}")

    def ensure_cached_hash(self, file_path: Path, algorithm: str = DEFAULT_INDEX_HASH_ALGORITHM) -> str:
        """
        確保指定演算法的檔案雜湊已寫入索引，並回傳該值

        Args:
            file_path: 檔案路徑
            algorithm: 雜湊演算法名稱

        Returns:
            索引中的雜湊值；若尚未存在且無法計算，回傳空字串
        """
        normalized_algorithm = (
            str(algorithm or DEFAULT_INDEX_HASH_ALGORITHM).strip().lower() or DEFAULT_INDEX_HASH_ALGORITHM
        )
        cached_hash = self.get_cached_hash(file_path, normalized_algorithm)
        if cached_hash:
            return cached_hash
        computed_hash = HashUtils.compute_file_hash(str(file_path), normalized_algorithm)
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

    def flush(self) -> None:
        """立即儲存尚未落盤的索引內容"""
        self._save_index_if_due(force=True)

    def _load_index(self) -> None:
        """從磁碟載入索引"""
        with self._index_lock:
            if self.index_file.exists():
                try:
                    raw_payload = orjson.loads(self.index_file.read_bytes())
                    self._index = self._normalize_loaded_payload(raw_payload)
                    logger.info(f"模組索引已載入，包含 {len(self._index)} 個項目")
                except (OSError, orjson.JSONDecodeError, ValueError) as e:
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
        """將磁碟 payload 正規化為 entries 字典，支援舊版格式遷移"""
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
        logger.info(f"偵測到舊版索引格式，將自動遷移至 schema v{INDEX_SCHEMA_VERSION}")
        normalized_entries = {}
        for key, value in payload.items():
            if isinstance(key, str) and isinstance(value, dict):
                normalized_entries[key] = dict(value)
        return normalized_entries

    def _build_persist_payload(self) -> dict[str, Any]:
        """建構落盤 payload，保留 schema metadata 以支援未來演進"""
        return {"schema_version": INDEX_SCHEMA_VERSION, "entries": self._index}

    def _save_index(self) -> None:
        """將索引儲存為 JSON"""
        with self._index_lock:
            try:
                payload = self._build_persist_payload()
                ok = atomic_write_json(self.index_file, payload)
                if ok:
                    logger.debug("模組索引已儲存 (atomic)")
                    self._dirty = False
                    self._last_save_ts = time.time()
                else:
                    logger.warning("模組索引儲存失敗（atomic write 回傳 false）")
            except (OSError, TypeError, ValueError) as e:
                logger.warning(f"無法儲存索引檔案: {e}")

    def _save_index_if_due(self, *, force: bool = False) -> None:
        """依時間節流儲存索引，避免每個檔案都立即落盤"""
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

    def _update_entry(self, file_path: Path, **updates: Any) -> bool:
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
                return True
            except Exception as e:
                logger.warning(f"無法更新模組索引項目 {file_name}: {e}")
                return False

    def clear_index(self) -> None:
        """清空所有快取項目並將空索引寫入磁碟"""
        with self._index_lock:
            self._index = {}
            self._dirty = True
            self.flush()


__all__ = ["ModIndexManager"]
