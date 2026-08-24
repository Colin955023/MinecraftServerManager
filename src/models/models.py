"""
資料模型定義

定義應用程式中使用的核心資料結構與設定類別
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from src.utils import (
    MODRINTH_PREFERRED_HASH_ALGORITHM,
    RECOMMENDATION_CONFIDENCE_HIGH,
    RECOMMENDATION_SOURCE_HASH_METADATA,
    normalize_identifier,
)

MODRINTH_HASH_ALGORITHM = "sha512"

type JSONValue = dict[str, Any] | list[Any]


@dataclass(frozen=True, slots=True)
class HTTPJSONResponse:
    """保留 HTTP 狀態與失敗類型的 JSON 結果，供 domain adapter 判斷重試政策"""

    status_code: int | None
    payload: JSONValue | None = None
    error_kind: str = ""


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
    file_mtime: float = 0.0
    current_hash: str = ""
    hash_algorithm: str = ""
    provider_identity: Any | None = None

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
    provider_identity: Any | None = None
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
    _actionable_count: int = field(default=0, init=False, repr=False)

    def finalize_summary(self) -> None:
        """彙總候選項目並更新可執行數量"""
        self._actionable_count = sum(1 for candidate in self.candidates if candidate.actionable)

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


# ----------------------------------------------------------------------
# 載入器核心模型 (Loader Domain Models)
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LoaderInstallerArtifact:
    """一次建立流程固定使用的 Loader installer 與校驗資訊"""

    url: str
    expected_hash: str | None = None
    hash_algorithm: str | None = None


@dataclass(frozen=True, slots=True)
class LoaderSpec:
    """五種 server 類型的統一描述；差異資料化，共同流程留在 LoaderManager"""

    id: str
    cache_name: str
    api_url: str | None = None
    api_kind: str | None = None  # mojang_manifest / json / maven_xml
    stable_only: bool = True
    keep_latest: int | None = None
    installer_url: Callable[[str, str], str | None] | None = None
    installer_args: Callable[[str, str, str, str], list[str]] | None = None
    needs_vanilla: bool = False
    candidate_keys: Callable[[str], list[str]] | None = None
    normalize_loader_version: Callable[[str, str], str] | None = None
    parse_fallback_full_version: bool = False
    direct_download: bool = False


# ----------------------------------------------------------------------
# Provider 身份與中繼資料模型 (Provider Identity Models)
# ----------------------------------------------------------------------

ProviderLifecycle = Literal["fresh", "stale", "missing", "retrying", "invalidated"]
CatalogOutcomeKind = Literal["found", "not_found", "transient_failure", "rate_limited", "invalid_response"]


@dataclass(frozen=True, slots=True)
class ProviderCatalogOutcome:
    """Provider catalog 查詢後的中立結果模型"""

    kind: CatalogOutcomeKind
    provider: str = "modrinth"
    project_id: str = ""
    alias: str = ""
    display_name: str = ""
    confidence: int = 0

    @property
    def canonical(self) -> bool:
        return self.kind == "found" and bool(self.project_id)


@dataclass(frozen=True, slots=True)
class ProviderIdentityEvidence:
    """解析 provider identity 所需的本地與遠端線索"""

    file_path: Path | None = None
    project_id_hint: str = ""
    alias_hint: str = ""
    display_name: str = ""
    jar_aliases: tuple[str, ...] = ()
    search_terms: tuple[str, ...] = ()
    hash_project_id: str = ""


PROVIDER_IDENTITY_SCHEMA_VERSION = 2
PROVIDER_IDENTITY_TTL_SECONDS = 12 * 60 * 60


def _positive_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        parsed = int(value)
        return parsed if parsed > 0 else 0
    except TypeError, ValueError:
        return 0


@dataclass(frozen=True, slots=True)
class ProviderIdentitySnapshot:
    """Provider identity 在特定時間點的不可變生命週期快照"""

    provider: str = "local"
    project_id: str = ""
    alias: str = ""
    display_name: str = ""
    provenance: str = "unresolved"
    lifecycle: ProviderLifecycle = "missing"
    observed_at_epoch_ms: int = 0
    resolved_at_epoch_ms: int = 0
    failure_count: int = 0
    next_retry_not_before_epoch_ms: int = 0

    @property
    def canonical(self) -> bool:
        return self.provider != "local" and bool(self.project_id) and self.lifecycle == "fresh"

    def as_payload(self) -> dict[str, Any]:
        """
        輸出完整 replace payload；空 alias 會明確清除舊值

        Returns:
            可直接交給 identity store 取代舊紀錄的 payload
        """
        return {
            "schema_version": PROVIDER_IDENTITY_SCHEMA_VERSION,
            "provider": self.provider,
            "project_id": self.project_id,
            "alias": self.alias,
            "display_name": self.display_name,
            "provenance": self.provenance,
            "lifecycle": self.lifecycle,
            "observed_at_epoch_ms": self.observed_at_epoch_ms,
            "resolved_at_epoch_ms": self.resolved_at_epoch_ms,
            "failure_count": self.failure_count,
            "next_retry_not_before_epoch_ms": self.next_retry_not_before_epoch_ms,
        }

    @classmethod
    def from_payload(
        cls,
        raw: dict[str, Any] | None,
        *,
        now_epoch_ms: int | None = None,
        ttl_seconds: int = PROVIDER_IDENTITY_TTL_SECONDS,
    ) -> ProviderIdentitySnapshot:
        """
        從持久化 payload 還原並重新判定生命週期

        Args:
            raw: identity store 讀出的原始欄位
            now_epoch_ms: 測試或批次共用的目前時間
            ttl_seconds: fresh identity 的有效秒數

        Returns:
            經 schema、TTL 與 retry policy 正規化的快照
        """
        if not isinstance(raw, dict) or not raw:
            return cls()
        now_ms = int(now_epoch_ms if now_epoch_ms is not None else time.time() * 1000)
        schema_version = _positive_int(raw.get("schema_version"))
        provider = str(raw.get("provider", raw.get("platform", "local")) or "local").strip().lower()
        project_id = str(raw.get("project_id", "") or "").strip()
        alias = str(raw.get("alias", raw.get("slug", "")) or "").strip()
        display_name = str(raw.get("display_name", raw.get("project_name", "")) or "").strip()
        provenance = str(raw.get("provenance", raw.get("resolution_source", "legacy")) or "legacy").strip()
        resolved_at = _positive_int(raw.get("resolved_at_epoch_ms"))
        observed_at = _positive_int(raw.get("observed_at_epoch_ms")) or resolved_at
        failure_count = _positive_int(raw.get("failure_count", raw.get("stale_revalidation_failures")))
        next_retry = _positive_int(raw.get("next_retry_not_before_epoch_ms"))
        raw_lifecycle = str(raw.get("lifecycle", raw.get("lifecycle_state", "")) or "").strip().lower()
        if provider == "local" and (project_id or alias):
            provider = "modrinth"
        if not project_id:
            lifecycle: ProviderLifecycle = "retrying" if alias else "missing"
        elif schema_version < PROVIDER_IDENTITY_SCHEMA_VERSION or resolved_at <= 0:
            lifecycle = "stale"
        elif raw_lifecycle in {"retrying", "invalidated"} and now_ms < next_retry:
            lifecycle = cast(ProviderLifecycle, raw_lifecycle)
        elif now_ms - resolved_at > max(0, ttl_seconds) * 1000:
            lifecycle = "stale"
        else:
            lifecycle = "fresh"
        return cls(
            provider=provider,
            project_id=project_id,
            alias=alias,
            display_name=display_name,
            provenance=provenance,
            lifecycle=lifecycle,
            observed_at_epoch_ms=observed_at,
            resolved_at_epoch_ms=resolved_at,
            failure_count=failure_count,
            next_retry_not_before_epoch_ms=next_retry,
        )


# ----------------------------------------------------------------------
# 伺服器建立相關模型 (Server Creation Models)
# ----------------------------------------------------------------------

CreationStatus = Literal["completed", "cancelled", "failed", "confirmation_required"]


@dataclass(frozen=True, slots=True)
class ServerCreationWarning:
    """建立計畫中需要使用者注意或確認的警告"""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ServerCreationPlan:
    """完成驗證後可交由交易執行器提交的不可變建立計畫"""

    transaction_id: str
    name: str
    minecraft_version: str
    loader_type: str
    loader_version: str
    memory_max_mb: int
    memory_min_mb: int | None
    jvm_args: tuple[str, ...]
    properties: tuple[tuple[str, str], ...]
    final_path: Path
    staging_path: Path
    user_java_path: str | None
    installer_artifact: LoaderInstallerArtifact | None
    warnings: tuple[ServerCreationWarning, ...]

    @property
    def requires_unverified_installer_confirmation(self) -> bool:
        return any(warning.code == "installer_checksum_missing" for warning in self.warnings)

    def build_config(self, path: Path) -> ServerConfig:
        """
        建立指定交易路徑所使用的伺服器設定

        Args:
            path: staging 或最終伺服器路徑

        Returns:
            從不可變計畫產生的新設定物件
        """
        return ServerConfig(
            name=self.name,
            minecraft_version=self.minecraft_version,
            loader_type=self.loader_type,
            loader_version=self.loader_version,
            memory_max_mb=self.memory_max_mb,
            memory_min_mb=self.memory_min_mb,
            path=str(path),
            eula_accepted=True,
            properties=dict(self.properties),
            jvm_args=list(self.jvm_args),
        )


@dataclass(frozen=True, slots=True)
class ServerCreationResult:
    """伺服器建立交易的最終狀態與診斷資訊"""

    status: CreationStatus
    message: str
    config: ServerConfig | None = None
    diagnostic_id: str = ""
    cleanup_complete: bool = True

    @property
    def completed(self) -> bool:
        return self.status == "completed"


# ----------------------------------------------------------------------
# 伺服器匯入與檢測相關模型 (Server Import & Detection Models)
# ----------------------------------------------------------------------

ImportMode = Literal["direct_folder", "zip_archive", "in_place_recheck"]
ImportSourceKind = Literal["archive", "directory", "in_place"]
ImportStatus = Literal["completed", "skipped", "cancelled", "failed"]
ConflictType = Literal["none", "disk", "config", "both"]


@dataclass(slots=True)
class ServerDetectionScratch:
    """伺服器版本與載入器偵測過程的暫存結構"""

    loader_type: str = "unknown"
    minecraft_version: str = "unknown"
    loader_version: str = "unknown"


@dataclass(frozen=True, slots=True)
class ServerImportInspection:
    """不會修改來源的匯入候選快照"""

    transaction_id: str
    mode: ImportMode
    source_kind: ImportSourceKind
    source_path: Path
    name: str
    final_path: Path
    loader_type: str
    minecraft_version: str
    loader_version: str
    memory_max_mb: int
    memory_min_mb: int | None
    eula_accepted: bool
    main_jar: str
    startup_scripts: tuple[str, ...]
    startup_command: str
    evidence: tuple[tuple[str, str], ...]
    warnings: tuple[str, ...]
    committable: bool
    conflict_type: ConflictType = "none"

    def build_config(self, path: Path, previous: ServerConfig | None = None) -> ServerConfig:
        """
        建立提交邊界使用的可變持久化模型

        Args:
            path: 設定應指向的受管實例路徑
            previous: 重新偵測時要保留屬性與 JVM 參數的舊設定

        Returns:
            僅供交易提交使用的新 ServerConfig
        """
        return ServerConfig(
            name=self.name,
            path=str(path),
            minecraft_version=self.minecraft_version,
            loader_type=self.loader_type,
            loader_version=self.loader_version,
            memory_max_mb=self.memory_max_mb,
            memory_min_mb=self.memory_min_mb,
            eula_accepted=self.eula_accepted,
            properties=dict(previous.properties) if previous and previous.properties else None,
            jvm_args=list(previous.jvm_args) if previous else [],
        )


@dataclass(frozen=True, slots=True)
class ServerImportResult:
    """單一候選的最終交易結果"""

    status: ImportStatus
    message: str
    name: str
    config: ServerConfig | None = None
    warnings: tuple[str, ...] = ()
    evidence: tuple[tuple[str, str], ...] = ()
    diagnostic_id: str = ""
    cleanup_complete: bool = True

    @property
    def completed(self) -> bool:
        return self.status == "completed"


@dataclass(frozen=True, slots=True)
class ServerImportBatchResult:
    """批次執行的逐項結果與彙總計數"""

    items: tuple[ServerImportResult, ...]

    @property
    def completed_count(self) -> int:
        return sum(item.completed for item in self.items)

    @property
    def skipped_count(self) -> int:
        return sum(item.status == "skipped" for item in self.items)

    @property
    def failed_count(self) -> int:
        return sum(item.status == "failed" for item in self.items)


# ----------------------------------------------------------------------
# 線上依賴安裝計畫模型 (Online Dependency Install Plan Models)
# ----------------------------------------------------------------------


@dataclass(slots=True)
class OnlineDependencyInstallItem:
    """必要依賴的自動安裝項目"""

    project_id: str
    project_name: str
    version_id: str
    version_name: str
    filename: str
    download_url: str
    parent_name: str = ""
    maybe_installed: bool = False
    status_note: str = ""
    resolution_source: str = "project_id"
    resolution_confidence: str = "direct"
    enabled: bool = True
    is_optional: bool = False
    provider: str = "modrinth"
    expected_hash: str = ""
    required_by: list[str] = field(default_factory=list)
    decision_source: str = "required:auto"
    graph_depth: int = 1
    edge_kind: str = "required"
    edge_source: str = "required:modrinth_dependency"

    @classmethod
    def from_dict(cls, payload: Any) -> OnlineDependencyInstallItem | None:
        """
        從字典還原線上依賴安裝項目。

        Args:
            payload: 待解析的字典資料。

        Returns:
            解析成功時回傳安裝項目；資料格式不符時回傳 None。
        """
        if not isinstance(payload, dict):
            return None

        def _get_str(k: str, default: str = "") -> str:
            v = payload.get(k)
            return str(v).strip() if v is not None else default

        def _get_int(k: str, default: int = 1) -> int:
            try:
                v = int(payload.get(k, default))
                return v if v > 0 else default
            except ValueError, TypeError:
                return default

        edge_kind = _get_str("edge_kind", "required").lower() or "required"
        edge_source = _get_str("edge_source", "").lower()
        if not edge_source:
            edge_source = f"{edge_kind}:modrinth_dependency"
        req_by = payload.get("required_by", [])
        required_by = [str(x).strip() for x in req_by if str(x).strip()] if isinstance(req_by, list) else []
        return cls(
            project_id=_get_str("project_id"),
            project_name=_get_str("project_name"),
            version_id=_get_str("version_id"),
            version_name=_get_str("version_name"),
            filename=_get_str("filename"),
            download_url=_get_str("download_url"),
            parent_name=_get_str("parent_name"),
            maybe_installed=bool(payload.get("maybe_installed", False)),
            status_note=_get_str("status_note"),
            resolution_source=_get_str("resolution_source", "project_id"),
            resolution_confidence=_get_str("resolution_confidence", "direct"),
            enabled=bool(payload.get("enabled", True)),
            is_optional=bool(payload.get("is_optional", False)),
            provider=_get_str("provider", "modrinth") or "modrinth",
            expected_hash=_get_str("expected_hash"),
            required_by=required_by,
            decision_source=_get_str("decision_source") or "required:auto",
            graph_depth=_get_int("graph_depth", 1),
            edge_kind=edge_kind,
            edge_source=edge_source,
        )


@dataclass(slots=True)
class OnlineDependencyInstallPlan:
    """必要依賴的連鎖安裝計畫"""

    items: list[OnlineDependencyInstallItem] = field(default_factory=list)
    advisory_items: list[OnlineDependencyInstallItem] = field(default_factory=list)
    unresolved_required: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def auto_install_count(self) -> int:
        """取得可自動安裝的項目數量"""
        return len(self.items)


# ----------------------------------------------------------------------
# 執行期腳本與命令模型 (Runtime Command Models)
# ----------------------------------------------------------------------


@dataclass(slots=True)
class StartupScriptCommand:
    """從既有啟動腳本擷取出的 Java 啟動指令"""

    command_line: str = ""
    memory_max_mb: int | None = None
    memory_min_mb: int | None = None

    @property
    def has_java_command(self) -> bool:
        return bool(self.command_line)


# ----------------------------------------------------------------------
# UI / 狀態 / 工作排程模型 (UI, State & Work Scope Models)
# ----------------------------------------------------------------------


@dataclass(slots=True)
class SearchFilter:
    """搜尋元件共用的文字篩選器"""

    case_sensitive: bool = False
    normalize_whitespace: bool = True
    require_all_terms: bool = True

    def normalize(self, value: Any) -> str:
        """
        正規化搜尋文字。

        Args:
            value: 待正規化的任意值。

        Returns:
            套用空白與大小寫規則後的搜尋文字。
        """
        text = str(value or "").strip()
        if self.normalize_whitespace:
            text = re.sub(r"\s+", " ", text)
        return text if self.case_sensitive else text.lower()

    def matches(self, candidate: Any, query: Any) -> bool:
        """
        判斷候選文字是否符合查詢字串

        Args:
            candidate: 被比對的候選值；可為字串、序列或 dict
            query: 使用者輸入的查詢值

        Returns:
            候選值符合查詢時回傳 True
        """
        normalized_query = self.normalize(query)
        if not normalized_query:
            return True
        candidate_text = " ".join(self.normalize(value) for value in self._candidate_values(candidate))
        if not candidate_text:
            return False
        if not self.require_all_terms:
            return normalized_query in candidate_text
        return all(term in candidate_text for term in normalized_query.split())

    def _candidate_values(self, candidate: Any) -> list[Any]:
        if isinstance(candidate, Mapping):
            return list(candidate.values())
        if isinstance(candidate, (list, tuple, set, frozenset)):
            return list(candidate)
        return [candidate]


class WorkStatus(Enum):
    """工作狀態枚舉"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class WorkOutcome:
    """工作結果封裝"""

    status: WorkStatus
    value: Any = None
    error: BaseException | None = None

    @staticmethod
    def succeeded(value: Any = None) -> WorkOutcome:
        """
        建立成功的工作結果。

        Args:
            value: 工作完成後要攜帶的結果值。

        Returns:
            狀態為成功的工作結果。
        """
        return WorkOutcome(status=WorkStatus.SUCCEEDED, value=value)

    @staticmethod
    def failed(error: BaseException) -> WorkOutcome:
        """
        建立失敗的工作結果。

        Args:
            error: 導致工作失敗的例外。

        Returns:
            狀態為失敗並包含例外的工作結果。
        """
        return WorkOutcome(status=WorkStatus.FAILED, error=error)

    @staticmethod
    def cancelled() -> WorkOutcome:
        """
        建立已取消的工作結果。

        Returns:
            狀態為已取消的工作結果。
        """
        return WorkOutcome(status=WorkStatus.CANCELLED)

    @property
    def is_succeeded(self) -> bool:
        return self.status == WorkStatus.SUCCEEDED

    @property
    def is_failed(self) -> bool:
        return self.status == WorkStatus.FAILED

    @property
    def is_cancelled(self) -> bool:
        return self.status == WorkStatus.CANCELLED


# ----------------------------------------------------------------------
# UI / 服務層模型 (UI & Service Models)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ServerRefreshPayload:
    """背景刷新完成後交給 UI callback 的列表資料載體"""

    signature: tuple[tuple[str, tuple[Any, ...]], ...]
    server_order: list[str]
    server_rows: dict[str, tuple[Any, ...]]


@dataclass(frozen=True)
class ServerProjection:
    """單輪伺服器狀態的不可變投影"""

    generation: int
    server_order: tuple[str, ...]
    server_rows: dict[str, tuple[Any, ...]]
    selected_server: str | None


@dataclass(frozen=True)
class ServerRenderPlan:
    """render 指令，只有有可觀察差異時才產生"""

    projection: ServerProjection
    has_changes: bool


OperationKind = Literal["local_scan", "online_search", "install", "version_load"]


@dataclass(frozen=True, slots=True)
class ModOperationScope:
    """將非同步操作綁定到特定工作階段、伺服器與世代"""

    session_id: str
    server_identity: str
    kind: OperationKind
    generation: int


@dataclass(frozen=True, slots=True)
class ModListRow:
    """工作階段持有的不可變列表列資料"""

    key: str
    values: tuple[str, ...]
    data: Any


@dataclass(frozen=True, slots=True)
class ModManagementSnapshot:
    """供 Presenter 唯讀消費的完整 Mod 管理狀態快照"""

    session_id: str
    active: bool
    server: ServerConfig | None
    server_identity: str
    local_mods: tuple[Any, ...]
    online_mods: tuple[Any, ...]
    local_rows: tuple[ModListRow, ...]
    online_rows: tuple[ModListRow, ...]
    pending_online_installs: tuple[PendingOnlineInstall, ...]
    selected_mod_ids: frozenset[str]
    status_message: str
    latest_online_request: OnlineBrowseRequest | None


ReviewMode = Literal["online_install", "local_update"]


@dataclass(frozen=True, slots=True)
class ReviewContextStamp:
    """用於拒絕過期執行的伺服器與本地 Mod revision 快照"""

    server_identity: str
    minecraft_version: str
    loader_type: str
    loader_version: str
    installed_mod_revision: tuple[tuple[str, str, str, str, int, int], ...]


@dataclass(frozen=True, slots=True)
class ReviewTaskView:
    """Review 任務樹中單一節點的不可變呈現資料"""

    node_id: str
    root_key: str
    group_key: str
    title: str
    values: tuple[str, ...]
    node_kind: str
    parent_id: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class ReviewRootView:
    """Review root 的摘要與專案頁面資料"""

    root_key: str
    summary: str
    project_page_url: str


@dataclass(frozen=True, slots=True)
class ReviewViewSnapshot:
    """UI 繪製完整 Review 對話框所需的不可變快照"""

    mode: ReviewMode
    subtitle: str
    overview: str
    task_nodes: tuple[ReviewTaskView, ...]
    roots: tuple[ReviewRootView, ...]
    group_specs: tuple[tuple[str, str], ...]
    action_label: str
    enabled_count: int
    actionable_count: int
    blocked_count: int

    def root(self, root_key: str) -> ReviewRootView | None:
        """
        依 root key 尋找摘要資料

        Args:
            root_key: Review root 的穩定識別碼

        Returns:
            相符的 root；不存在時回傳 None
        """
        return next((root for root in self.roots if root.root_key == root_key), None)


@dataclass(frozen=True, slots=True)
class ReviewInstallStep:
    """Executor 可直接執行的單一下載、安裝或更新步驟"""

    kind: Literal["dependency", "online_root", "local_root"]
    root_key: str
    project_name: str
    version_name: str
    download_url: str
    filename: str
    expected_hash: str
    provider: str
    local_file_path: str = ""
    local_status: str = "enabled"


@dataclass(frozen=True, slots=True)
class ReviewExecutionHandoff:
    """Review session 驗證後交給 executor 的不可變執行契約"""

    mode: ReviewMode
    context_stamp: ReviewContextStamp
    steps: tuple[ReviewInstallStep, ...]
    root_keys: tuple[str, ...]
    confirmation_prompt: str
    source_confirmation_prompt: str
    skipped_text: str = ""
    completion_notes: str = ""
    disabled_count: int = 0
    dependency_count: int = 0
    duplicate_dependency_count: int = 0

    @property
    def root_count(self) -> int:
        return len(self.root_keys)


class MainWindowSettings(TypedDict, total=False):
    """主視窗位置大小設定 Dictionary 型別"""

    width: int
    height: int
    x: int | None
    y: int | None
    maximized: bool


class WindowPreferences(TypedDict, total=False):
    """全域視窗偏好設定 Dictionary 型別"""

    remember_size_position: bool
    auto_center: bool
    adaptive_sizing: bool
    theme_mode: str
    main_window: MainWindowSettings
