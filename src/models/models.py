"""
資料模型定義

定義應用程式中使用的核心資料結構與配置類別
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..utils import (
    MODRINTH_PREFERRED_HASH_ALGORITHM,
    RECOMMENDATION_CONFIDENCE_HIGH,
    RECOMMENDATION_SOURCE_HASH_METADATA,
    normalize_identifier,
)

MODRINTH_HASH_ALGORITHM = "sha512"
MODRINTH_SEARCH_URL = "https://api.modrinth.com/v2/search"
_IDENTITY_CACHE_DEFAULT_MAX_SIZE = 512


@dataclass(slots=True)
class DependencyPlanHooks:
    """必要依賴安裝計畫展開所需的 callback 集合"""

    resolve_project_names: Callable[[set[str]], dict[str, str]]
    resolve_dependency_entry: Callable[[dict[str, Any], dict[str, str]], ResolvedDependencyReference]
    select_dependency_best_version: Callable[[ResolvedDependencyReference, bool], OnlineModVersion | None]
    analyze_dependency_best_version: Callable[[OnlineModVersion, ResolvedDependencyReference, str, dict[str, str]], Any]
    extract_dependency_download_target: Callable[[OnlineModVersion], tuple[str, str] | None]
    make_dependency_install_item: Callable[..., Any]
    maybe_installed_checker: Callable[[ResolvedDependencyReference, list[Any] | None], bool]


class ModStatus(Enum):
    """模組狀態"""

    ENABLED = "enabled"
    DISABLED = "disabled"


class ModPlatform(Enum):
    """模組來源平台"""

    MODRINTH = "modrinth"
    LOCAL = "local"


@dataclass
class OnlineModVersion:
    """Modrinth 上單一模組版本資訊"""

    version_id: str
    version_number: str
    display_name: str
    game_versions: list[str] = field(default_factory=list)
    loaders: list[str] = field(default_factory=list)
    version_type: str = ""
    date_published: str = ""
    changelog: str = ""
    provider: str = "modrinth"
    files: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[dict[str, Any]] = field(default_factory=list)

    @property
    def primary_file(self) -> dict[str, Any] | None:
        if not self.files:
            return None
        for file_info in self.files:
            if isinstance(file_info, dict) and file_info.get("primary"):
                return file_info
        for file_info in self.files:
            if isinstance(file_info, dict):
                filename = str(file_info.get("filename", "") or "")
                if filename.lower().endswith(".jar"):
                    return file_info
        for file_info in self.files:
            if isinstance(file_info, dict):
                return file_info
        return None


@dataclass
class ModrinthVersionLookupResult:
    """以雜湊查詢 Modrinth 版本後的結果"""

    file_hash: str
    algorithm: str
    project_id: str
    version: OnlineModVersion


@dataclass(slots=True)
class ResolvedDependencyReference:
    """解析後的依賴資訊，支援 project_id 與 version_id 兩種來源"""

    project_id: str = ""
    project_name: str = ""
    version_id: str = ""
    version_name: str = ""
    file_name: str = ""
    version: OnlineModVersion | None = None
    resolution_source: str = "project_id"
    resolution_confidence: str = "direct"

    @property
    def label(self) -> str:
        if self.project_name:
            base = self.project_name
        elif self.project_id:
            base = f"未知模組（project id: {self.project_id}）"
        elif self.file_name:
            base = self.file_name
        elif self.version_id:
            base = f"未知模組（version id: {self.version_id}）"
        else:
            base = "未知依賴"
        if self.version_name:
            return f"{base}（需求版本：{self.version_name}）"
        return base

    @property
    def compare_project_id(self) -> str:
        return str(self.project_id or "").strip().lower()


@dataclass
class LoaderVersion:
    """模組載入器版本資訊的資料結構，支援 Forge 和 Fabric 載入器"""

    version: str
    build: str | None = None
    url: str | None = None
    stable: bool | None = None
    mc_version: str | None = None
    game_versions: list[str] = field(default_factory=list)


@dataclass
class ServerConfig:
    """伺服器完整配置資料類別，包含所有伺服器設定和屬性"""

    name: str
    minecraft_version: str
    loader_type: str
    loader_version: str
    memory_max_mb: int
    memory_min_mb: int | None = None
    path: str = ""
    eula_accepted: bool = False
    properties: dict[str, str] | None = None
    jvm_args: list[str] = field(default_factory=list)
    performance_profile: str = ""

    @property
    def memory_mb(self) -> int:
        return self.memory_max_mb

    @memory_mb.setter
    def memory_mb(self, value: int):
        self.memory_max_mb = value


@dataclass
class LocalModInfo:
    """本地模組資訊"""

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
    """描述遠端下載/覆蓋流程的最終狀態"""

    status: str
    final_path: Path | None = None
    rollback_performed: bool = False
    message: str = ""

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    @property
    def cancelled(self) -> bool:
        return self.status == "cancelled"


@dataclass(slots=True)
class LocalModMutationResult:
    """描述本地模組檔案異動結果，供 UI 層決定呈現方式"""

    status: str
    title: str = ""
    message: str = ""
    final_path: Path | None = None
    affected_count: int = 0
    missing_ids: tuple[str, ...] = ()

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    @property
    def partial(self) -> bool:
        return self.status == "partial"

    @property
    def failed(self) -> bool:
        return self.status == "failed"


@dataclass(slots=True)
class ModrinthIdentityCache:
    """
    執行緒安全、具容量上限的 Modrinth project identity 快取
    """

    max_size: int = _IDENTITY_CACHE_DEFAULT_MAX_SIZE
    _store: OrderedDict[str, tuple[str, str]] = field(default_factory=OrderedDict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if self.max_size < 0:
            raise ValueError("ModrinthIdentityCache.max_size must be >= 0")

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def get(self, key: str) -> tuple[str, str] | None:
        """
        取得快取中對應 key 的值，並將該項目移至末端

        Args:
            key: 要查詢的快取鍵值

        Returns:
            tuple: 對應的值（包含 project_id 與 slug），若不存在則回傳 None
        """
        with self._lock:
            value = self._store.get(key)
            if value is not None:
                self._store.move_to_end(key)
            return value

    def set(self, key: str, value: tuple[str, str]) -> None:
        """
        設定快取值，並在超過 max_size 時淘汰最舊項目

        Args:
            key: 要設定的快取鍵值
            value: 要設定的快取值（包含 project_id 與 slug）
        """
        with self._lock:
            self._store[key] = value
            self._store.move_to_end(key)
            while len(self._store) > self.max_size:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


@dataclass(slots=True)
class PendingOnlineInstall:
    """待安裝的線上模組項目"""

    project_id: str
    project_name: str
    version: Any
    report: Any | None = None
    homepage_url: str = ""
    source_url: str = ""
    server_side: str = ""
    client_side: str = ""


@dataclass(slots=True, kw_only=True)
class AbstractReviewEntry:
    """Review 項目共用屬性與狀態判斷"""

    blocking_reasons: list[str] = field(default_factory=list)
    warning_messages: list[str] = field(default_factory=list)
    enabled: bool = True
    provider: str = "modrinth"
    version_type: str = ""
    date_published: str = ""
    changelog: str = ""

    @property
    def actionable(self) -> bool:
        return self.enabled and (not self.blocking_reasons)

    @property
    def runnable(self) -> bool:
        return not self.blocking_reasons


@dataclass(slots=True, kw_only=True)
class PendingInstallReviewEntry(AbstractReviewEntry):
    """待安裝項目的最終驗證結果"""

    pending: PendingOnlineInstall
    report: Any | None
    dependency_plan: Any


@dataclass(slots=True, kw_only=True)
class LocalUpdateReviewEntry(AbstractReviewEntry):
    """本地模組更新 review 項目"""

    candidate: Any
    dependency_plan: Any

    @property
    def candidate_actionable(self) -> bool:
        return bool(getattr(self.candidate, "actionable", False))


@dataclass(slots=True)
class ReviewTaskNode:
    """Review 對話框中的共用 task 節點"""

    node_id: str
    root_key: str
    group_key: str
    title: str
    values: tuple[str, ...]
    node_kind: str
    parent_id: str | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class OnlineBrowseRequest:
    """線上模組瀏覽/搜尋請求"""

    query: str
    minecraft_version: str | None
    loader_type: str
    sort_by: str


@dataclass(slots=True)
class OnlineModInfo:
    """線上模組資訊"""

    project_id: str
    slug: str
    name: str
    author: str
    description: str = ""
    latest_version: str = ""
    download_count: int = 0
    icon_url: str = ""
    homepage_url: str = ""
    url: str = ""
    categories: list[str] = field(default_factory=list)
    versions: list[str] = field(default_factory=list)
    server_side: str = ""
    client_side: str = ""
    source: str = "modrinth"
    available: bool = True


@dataclass(slots=True)
class OnlineModCompatibilityReport:
    """安裝前版本相容性與依賴分析結果"""

    hard_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    missing_required_dependencies: list[str] = field(default_factory=list)
    optional_dependencies: list[str] = field(default_factory=list)
    incompatible_installed: list[str] = field(default_factory=list)
    installed_version_mismatches: list[str] = field(default_factory=list)
    embedded_dependencies: list[str] = field(default_factory=list)
    already_installed: list[str] = field(default_factory=list)

    @property
    def compatible(self) -> bool:
        return not self.hard_errors


@dataclass(slots=True)
class LocalMetadataEnsureSummary:
    """本地模組 metadata ensure / 專案識別摘要"""

    total_scanned: int = 0
    resolved_by_hash: int = 0
    resolved_by_cached_project: int = 0
    resolved_by_lookup: int = 0
    unresolved: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def resolved_count(self) -> int:
        return self.resolved_by_hash + self.resolved_by_cached_project + self.resolved_by_lookup


@dataclass(slots=True)
class LocalModUpdateCandidate:
    """本地模組更新檢查結果"""

    project_id: str
    project_name: str
    filename: str
    current_version: str
    target_version_id: str = ""
    target_version_name: str = ""
    target_version: OnlineModVersion | None = None
    target_filename: str = ""
    download_url: str = ""
    current_hash: str = ""
    hash_algorithm: str = MODRINTH_PREFERRED_HASH_ALGORITHM
    target_file_hash: str = ""
    recommendation_source: str = RECOMMENDATION_SOURCE_HASH_METADATA
    recommendation_confidence: str = RECOMMENDATION_CONFIDENCE_HIGH
    current_issues: list[str] = field(default_factory=list)
    dependency_issues: list[str] = field(default_factory=list)
    hard_errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    metadata_source: str = ""
    metadata_note: str = ""
    metadata_resolved: bool = True
    server_side: str = ""
    client_side: str = ""
    report: OnlineModCompatibilityReport | None = None
    local_mod: Any = None

    @property
    def update_available(self) -> bool:
        if not self.target_version_id:
            return False
        if self.current_hash and self.target_file_hash:
            return self.current_hash != self.target_file_hash
        return normalize_identifier(self.current_version) != normalize_identifier(self.target_version_name)

    @property
    def actionable(self) -> bool:
        return self.update_available and (not self.hard_errors) and bool(self.download_url and self.target_filename)

    @property
    def has_issues(self) -> bool:
        return bool(self.current_issues or self.dependency_issues or self.hard_errors)


@dataclass(slots=True)
class LocalModUpdatePlan:
    """本地模組更新檢查彙總"""

    candidates: list[LocalModUpdateCandidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    metadata_summary: LocalMetadataEnsureSummary = field(default_factory=LocalMetadataEnsureSummary)
    _has_candidates: bool = field(default=False, init=False, repr=False)
    _actionable_count: int = field(default=0, init=False, repr=False)

    def finalize_summary(self) -> None:
        """彙總候選項目並更新可執行數量"""
        actionable_count = 0
        has_candidates = False
        for candidate in self.candidates:
            has_candidates = True
            if candidate.actionable:
                actionable_count += 1
        self._has_candidates = has_candidates
        self._actionable_count = actionable_count

    @property
    def has_candidates(self) -> bool:
        return self._has_candidates

    @property
    def actionable_count(self) -> int:
        return self._actionable_count


@dataclass(slots=True)
class ServerOperationResult:
    """描述伺服器操作結果，供 UI 層決定如何呈現"""

    success: bool
    title: str = ""
    message: str = ""
    server_name: str = ""

    @property
    def failed(self) -> bool:
        return not self.success


@dataclass
class OperationResult:
    """通用操作結果類別，用於統一表示方法執行的成功與失敗狀態，以及相關訊息和錯誤資訊"""

    success: bool
    message: str = ""
    error: Exception | None = None
    extra: dict = field(default_factory=dict)
