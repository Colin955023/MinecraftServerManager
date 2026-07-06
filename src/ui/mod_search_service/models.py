"""Mod 查詢服務資料模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...models import OnlineModVersion
from ...utils import (
    MODRINTH_PREFERRED_HASH_ALGORITHM,
    RECOMMENDATION_CONFIDENCE_HIGH,
    RECOMMENDATION_SOURCE_HASH_METADATA,
    normalize_identifier,
)


@dataclass(slots=True)
class OnlineModInfo:
    """線上模組資訊。"""

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
    """安裝前版本相容性與依賴分析結果。"""

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
        """回傳相容性檢查是否通過。"""
        return not self.hard_errors


@dataclass(slots=True)
class LocalMetadataEnsureSummary:
    """本地模組 metadata ensure / 專案識別摘要。"""

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
    """本地模組更新檢查結果。"""

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
        """回傳此項目是否可由使用者執行。"""
        return self.update_available and (not self.hard_errors) and bool(self.download_url and self.target_filename)

    @property
    def has_issues(self) -> bool:
        return bool(self.current_issues or self.dependency_issues or self.hard_errors)


@dataclass(slots=True)
class LocalModUpdatePlan:
    """本地模組更新檢查彙總。"""

    candidates: list[LocalModUpdateCandidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    metadata_summary: LocalMetadataEnsureSummary = field(default_factory=LocalMetadataEnsureSummary)
    _has_candidates: bool = field(default=False, init=False, repr=False)
    _actionable_count: int = field(default=0, init=False, repr=False)

    @property
    def has_candidates(self) -> bool:
        return self._has_candidates

    @property
    def actionable_count(self) -> int:
        return self._actionable_count

    def finalize_summary(self) -> None:
        """計算並快取候選摘要，避免後續重複掃描 candidates。"""
        actionable_count = 0
        has_candidates = False
        for candidate in self.candidates:
            has_candidates = True
            if candidate.actionable:
                actionable_count += 1
        self._has_candidates = has_candidates
        self._actionable_count = actionable_count


__all__ = [
    "LocalMetadataEnsureSummary",
    "LocalModUpdateCandidate",
    "LocalModUpdatePlan",
    "OnlineModCompatibilityReport",
    "OnlineModInfo",
]
