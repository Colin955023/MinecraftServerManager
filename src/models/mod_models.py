"""模組與 Provider 共用領域模型"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal, cast

from src.utils import (
    MODRINTH_PREFERRED_HASH_ALGORITHM,
    RECOMMENDATION_CONFIDENCE_HIGH,
    RECOMMENDATION_SOURCE_HASH_METADATA,
    normalize_identifier,
)


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
        valid_files = [f for f in self.files if isinstance(f, dict)]
        if not valid_files:
            return None
        return next(
            (f for f in valid_files if f.get("primary")),
            next(
                (f for f in valid_files if str(f.get("filename", "") or "").lower().endswith(".jar")),
                valid_files[0],
            ),
        )


@dataclass
class ModrinthVersionLookupResult:
    """以雜湊查詢 Modrinth 版本後的結果"""

    file_hash: str
    algorithm: str
    project_id: str
    version: OnlineModVersion


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
    metadata_summary: Any = field(default_factory=dict)
    _actionable_count: int = field(default=0, init=False, repr=False)

    def finalize_summary(self) -> None:
        """彙總候選項目並更新可執行數量"""
        self._actionable_count = sum(1 for candidate in self.candidates if candidate.actionable)

    @property
    def actionable_count(self) -> int:
        return self._actionable_count


# ----------------------------------------------------------------------
# Provider 身分與中繼資料模型 (Provider Identity Models)
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
        provider = str(raw.get("provider", "local") or "local").strip().lower()
        project_id = str(raw.get("project_id", "") or "").strip()
        alias = str(raw.get("alias", "") or "").strip()
        display_name = str(raw.get("display_name", "") or "").strip()
        provenance = str(raw.get("provenance", "") or "").strip()
        resolved_at = _positive_int(raw.get("resolved_at_epoch_ms"))
        observed_at = _positive_int(raw.get("observed_at_epoch_ms")) or resolved_at
        failure_count = _positive_int(raw.get("failure_count"))
        next_retry = _positive_int(raw.get("next_retry_not_before_epoch_ms"))
        raw_lifecycle = str(raw.get("lifecycle", "") or "").strip().lower()
        if provider == "local" and (project_id or alias):
            provider = "modrinth"
        if not project_id:
            if raw_lifecycle in {"retrying", "invalidated"} and now_ms < next_retry:
                lifecycle = cast(ProviderLifecycle, raw_lifecycle)
            else:
                lifecycle = "retrying" if alias else "missing"
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
    included_by_default: bool = True
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
        從字典還原線上依賴安裝項目

        Args:
            payload: 待解析的字典資料

        Returns:
            解析成功時回傳安裝項目；資料格式不符時回傳 None
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
        required_by = (
            [normalized for item in req_by if (normalized := str(item).strip())] if isinstance(req_by, list) else []
        )
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
            included_by_default=bool(payload.get("included_by_default", True)),
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
