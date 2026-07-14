"""模組管理共享模型。"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

MODRINTH_HASH_ALGORITHM = "sha512"
MODRINTH_SEARCH_URL = "https://api.modrinth.com/v2/search"
_IDENTITY_CACHE_DEFAULT_MAX_SIZE = 512


class ModStatus(Enum):
    """模組狀態。"""

    ENABLED = "enabled"
    DISABLED = "disabled"


class ModPlatform(Enum):
    """模組來源平台。"""

    MODRINTH = "modrinth"
    LOCAL = "local"


@dataclass
class LocalModInfo:
    """本地模組資訊。"""

    id: str
    name: str
    filename: str
    version: str
    minecraft_version: str
    loader_type: str
    description: str = ""
    author: str = ""
    platform: ModPlatform = ModPlatform.LOCAL
    platform_id: str = ""
    platform_slug: str = ""
    status: ModStatus = ModStatus.ENABLED
    file_path: str = ""
    download_url: str = ""
    homepage_url: str = ""
    dependencies: list[str] | None = None
    file_size: int = 0
    current_hash: str = ""
    hash_algorithm: str = ""
    resolution_source: str = ""
    resolved_at_epoch_ms: str = ""
    provider_lifecycle_state: str = ""
    stale_revalidation_failures: int = 0
    next_retry_not_before_epoch_ms: str = ""

    def __post_init__(self) -> None:
        if self.dependencies is None:
            self.dependencies = []


@dataclass(slots=True)
class ModFileOperationResult:
    """描述遠端下載/覆蓋流程的最終狀態。"""

    status: str
    final_path: Path | None = None
    rollback_performed: bool = False
    message: str = ""

    @property
    def completed(self) -> bool:
        """回傳此操作是否已完成。"""
        return self.status == "completed"

    @property
    def cancelled(self) -> bool:
        """回傳此操作是否已取消。"""
        return self.status == "cancelled"


@dataclass(slots=True)
class LocalModMutationResult:
    """描述本地模組檔案異動結果，供 UI 層決定呈現方式。"""

    status: str
    title: str = ""
    message: str = ""
    final_path: Path | None = None
    affected_count: int = 0
    missing_ids: tuple[str, ...] = ()

    @property
    def completed(self) -> bool:
        """回傳此操作是否已完成。"""
        return self.status == "completed"

    @property
    def partial(self) -> bool:
        """回傳此操作是否為部分完成。"""
        return self.status == "partial"

    @property
    def failed(self) -> bool:
        """回傳此操作是否已失敗。"""
        return self.status == "failed"


@dataclass(slots=True)
class ModrinthIdentityCache:
    """
    執行緒安全、具容量上限的 Modrinth project identity 快取。

    取代先前 `ModManager` 把私有的 `_modrinth_identity_cache` dict 以參照方式
    直接交給 `ModProviderResolver` 讀寫的作法：
    - 呼叫端只能透過 `get`/`set`/`clear` 存取，不會意外破壞內部資料結構，
      快取的生命週期與淘汰策略也統一由這個類別自己負責。
    - 內建鎖，避免掃描模組時多個背景執行緒同時讀寫造成 race condition。
    - 超過 `max_size` 時依 LRU 策略淘汰最舊項目，避免快取隨應用程式執行
      時間無限增長。
    """

    max_size: int = _IDENTITY_CACHE_DEFAULT_MAX_SIZE
    _store: OrderedDict[str, tuple[str, str]] = field(default_factory=OrderedDict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if self.max_size < 0:
            raise ValueError("ModrinthIdentityCache.max_size must be >= 0")

    def get(self, key: str) -> tuple[str, str] | None:
        """
        讀取快取值；命中時會將該項目標記為最近使用。

        Args:
            key (str): 快取鍵。
        Returns:
            tuple[str, str] | None: 快取值，若不存在則回傳 None
        """
        with self._lock:
            value = self._store.get(key)
            if value is not None:
                self._store.move_to_end(key)
            return value

    def set(self, key: str, value: tuple[str, str]) -> None:
        """
        寫入快取值，超過容量上限時淘汰最舊未使用的項目。
        Args:
            key (str): 快取鍵。
            value (tuple[str, str]): 要寫入的快取值。
        """
        with self._lock:
            self._store[key] = value
            self._store.move_to_end(key)
            while len(self._store) > self.max_size:
                self._store.popitem(last=False)

    def clear(self) -> None:
        """清空快取。"""
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
