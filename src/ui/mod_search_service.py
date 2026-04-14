"""Mod 查詢服務
提供 Modrinth 線上模組搜尋、版本查詢與本地模組資訊增強。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from ..core import LoaderManager
from ..models import ModrinthVersionLookupResult, OnlineModVersion, ResolvedDependencyReference
from ..utils import (
    DEPENDENCY_PLAN_PERSISTENCE_SCHEMA_VERSION,
    LOCAL_UPDATE_ERROR_METADATA_UNRESOLVED,
    LOCAL_UPDATE_ERROR_STALE_REVALIDATION_FAILED,
    LOCAL_UPDATE_ERROR_STALE_REVALIDATION_INVALIDATED,
    LOCAL_UPDATE_METADATA_NOTE_STALE_REVALIDATION_FAILED,
    LOCAL_UPDATE_NOTE_CURRENT_VERSION_UNVERIFIED,
    LOCAL_UPDATE_NOTE_IDENTIFIED_NO_UPDATE,
    LOCAL_UPDATE_NOTE_METADATA_UNRESOLVED,
    LOCAL_UPDATE_NOTE_PROJECT_FALLBACK_ADVISORY,
    LOCAL_UPDATE_NOTE_STALE_BACKOFF_INVALIDATED,
    LOCAL_UPDATE_NOTE_STALE_BACKOFF_RETRYING,
    LOCAL_UPDATE_NOTE_STALE_RETRY_AUTO,
    METADATA_SOURCE_CACHED_PROVIDER,
    METADATA_SOURCE_HASH,
    METADATA_SOURCE_LOOKUP,
    METADATA_SOURCE_STALE_PROVIDER,
    METADATA_SOURCE_UNRESOLVED,
    MODRINTH_PREFERRED_HASH_ALGORITHM,
    PROVIDER_LIFECYCLE_INVALIDATED,
    PROVIDER_LIFECYCLE_RETRYING,
    PROVIDER_LIFECYCLE_STALE,
    PROVIDER_REVALIDATION_BATCH_MAX_PER_RUN,
    RECOMMENDATION_CONFIDENCE_ADVISORY,
    RECOMMENDATION_CONFIDENCE_BLOCKED,
    RECOMMENDATION_CONFIDENCE_HIGH,
    RECOMMENDATION_CONFIDENCE_RETRYABLE,
    RECOMMENDATION_SOURCE_HASH_METADATA,
    RECOMMENDATION_SOURCE_METADATA_UNRESOLVED,
    RECOMMENDATION_SOURCE_PROJECT_FALLBACK,
    RECOMMENDATION_SOURCE_STALE_METADATA,
    DependencyPlanHooks,
    HTTPUtils,
    LocalProviderEnsureResult,
    OnlineDependencyInstallItem,
    OnlineDependencyInstallPlan,
    PathUtils,
    ProviderMetadataRecord,
    apply_provider_metadata,
    build_local_mod_lookup_candidates,
    canonical_lookup_key,
    clean_api_identifier,
    collect_installed_mod_identifiers,
    collect_installed_mod_versions,
    compute_file_hash,
    dependency_maybe_installed_by_filename,
    deserialize_online_dependency_install_plan,
    ensure_local_mod_provider_record,
    execute_resilient_batch_requests,
    execute_resilient_single_request,
    expand_required_dependency_install_plan,
    expand_target_loader_aliases,
    extract_primary_file_hash,
    fetch_modrinth_project_detail,
    get_logger,
    get_modrinth_loader_filters,
    is_allowed_version_type,
    is_cached_provider_metadata_fresh,
    is_provider_revalidation_retry_due,
    is_supported_modrinth_update_loader,
    migrate_online_dependency_install_plan_payload,
    normalize_hash_algorithm,
    normalize_identifier,
    normalize_local_loader,
    normalize_mod_search_query,
    parse_modrinth_version,
    parse_modrinth_version_lookup_response,
    recompute_adaptive_revalidation_batch_limit,
    resolve_dependency_reference,
    resolve_modrinth_provider_record,
    resolve_revalidation_batch_limits,
    select_best_mod_version,
    serialize_online_dependency_install_plan,
    should_attempt_provider_revalidation,
    validate_online_dependency_install_plan_payload,
)

__all__ = [
    "DEPENDENCY_PLAN_PERSISTENCE_SCHEMA_VERSION",
    "OnlineDependencyInstallItem",
    "OnlineDependencyInstallPlan",
    "deserialize_online_dependency_install_plan",
    "migrate_online_dependency_install_plan_payload",
    "serialize_online_dependency_install_plan",
    "validate_online_dependency_install_plan_payload",
]

logger = get_logger().bind(component="ModSearchService")
MODRINTH_SEARCH_URL = "https://api.modrinth.com/v2/search"
MODRINTH_PROJECT_URL = "https://modrinth.com/mod"
MODRINTH_PROJECT_BATCH_URL = "https://api.modrinth.com/v2/projects"
MODRINTH_VERSION_URL_TEMPLATE = "https://api.modrinth.com/v2/project/{project_id}/version"
MODRINTH_VERSION_DETAIL_URL_TEMPLATE = "https://api.modrinth.com/v2/version/{version_id}"
MODRINTH_VERSION_FILES_URL = "https://api.modrinth.com/v2/version_files"
MODRINTH_VERSION_FILES_UPDATE_URL = "https://api.modrinth.com/v2/version_files/update"
MODRINTH_SEARCH_TIMEOUT_SECONDS = 15
MODRINTH_VERSION_TIMEOUT_SECONDS = 15
MODRINTH_PROJECT_BATCH_TIMEOUT_SECONDS = 12
MODRINTH_PROJECT_DETAIL_TIMEOUT_SECONDS = 12
MODRINTH_VERSION_DETAIL_TIMEOUT_SECONDS = 12
MODRINTH_VERSION_FILES_TIMEOUT_SECONDS = 20
MIN_ACCEPTABLE_LOCAL_MOD_SEARCH_SCORE = 70
SUPPORTED_SORT_OPTIONS = {"relevance", "downloads", "newest", "updated", "follows"}
LOCAL_HASH_MAX_WORKERS = 4
MODRINTH_BATCH_HASH_LOOKUP_SIZE = 64
MODRINTH_BATCH_PROJECT_LOOKUP_SIZE = 64
MODRINTH_BATCH_RETRY_ATTEMPTS = 2
MODRINTH_REQUEST_THROTTLE_SECONDS = 0.03
MODRINTH_RETRY_BACKOFF_BASE_SECONDS = 0.25
MODRINTH_RETRY_BACKOFF_MAX_SECONDS = 1.5
MODRINTH_SINGLE_REQUEST_RETRY_ATTEMPTS = 2


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


def _normalize_sort(sort_by: str) -> str:
    if sort_by in SUPPORTED_SORT_OPTIONS:
        return sort_by
    if sort_by == "name":
        return "relevance"
    return "relevance"


def _resolve_local_update_recommendation_strategy(
    *, used_project_fallback: bool, metadata_resolved: bool
) -> tuple[str, str]:
    if not metadata_resolved:
        return (RECOMMENDATION_SOURCE_METADATA_UNRESOLVED, RECOMMENDATION_CONFIDENCE_BLOCKED)
    if used_project_fallback:
        return (RECOMMENDATION_SOURCE_PROJECT_FALLBACK, RECOMMENDATION_CONFIDENCE_ADVISORY)
    return (RECOMMENDATION_SOURCE_HASH_METADATA, RECOMMENDATION_CONFIDENCE_HIGH)


def _score_local_mod_search_match(mod: OnlineModInfo, candidate_keys: set[str]) -> int:
    mod_keys = {canonical_lookup_key(mod.project_id), canonical_lookup_key(mod.slug), canonical_lookup_key(mod.name)}
    mod_keys.discard("")
    if not mod_keys:
        return 0
    if candidate_keys & mod_keys:
        return 100
    for candidate_key in candidate_keys:
        if not candidate_key:
            continue
        for mod_key in mod_keys:
            if candidate_key in mod_key or mod_key in candidate_key:
                return 70
    return 10


def get_modrinth_current_versions_by_hashes(
    hashes: list[str] | set[str] | tuple[str, ...], algorithm: str = MODRINTH_PREFERRED_HASH_ALGORITHM
) -> dict[str, ModrinthVersionLookupResult]:
    """依雜湊值取得目前已知的 Modrinth 版本資訊。

    Args:
        hashes: 要查詢的檔案雜湊清單。
        algorithm: 雜湊演算法名稱。

    Returns:
        以雜湊值為 key 的查詢結果字典。
    """
    normalized_hashes = [str(file_hash or "").strip().lower() for file_hash in hashes if str(file_hash or "").strip()]
    if not normalized_hashes:
        return {}
    normalized_algorithm = normalize_hash_algorithm(algorithm)

    def _request_chunk(hash_chunk: list[str]) -> dict[str, Any] | None:
        response = HTTPUtils.post_json(
            url=MODRINTH_VERSION_FILES_URL,
            headers=HTTPUtils.get_default_headers(),
            json_body={"hashes": hash_chunk, "algorithm": normalized_algorithm},
            timeout=MODRINTH_VERSION_FILES_TIMEOUT_SECONDS,
        )
        return response if isinstance(response, dict) else None

    return _modrinth_versions_by_hashes(
        hashes=normalized_hashes, algorithm=algorithm, request_batch_builder=_request_chunk
    )


def _modrinth_versions_by_hashes(
    hashes: list[str] | set[str] | tuple[str, ...],
    algorithm: str,
    request_batch_builder,
    _url: str | None = None,
    _timeout_seconds: int | None = None,
) -> dict[str, ModrinthVersionLookupResult]:
    """將 Modrinth 的雜湊批次查詢邏輯抽成共用函式，避免重複實作。"""
    normalized_hashes = [str(file_hash or "").strip().lower() for file_hash in hashes if str(file_hash or "").strip()]
    if not normalized_hashes:
        return {}

    def _request_chunk(hash_chunk: list[str]) -> dict[str, Any] | None:
        return request_batch_builder(hash_chunk)

    raw_payload, batch_stats = execute_resilient_batch_requests(
        normalized_hashes,
        batch_size=MODRINTH_BATCH_HASH_LOOKUP_SIZE,
        max_attempts=MODRINTH_BATCH_RETRY_ATTEMPTS,
        request_batch=_request_chunk,
        throttle_seconds=MODRINTH_REQUEST_THROTTLE_SECONDS,
        retry_backoff_base_seconds=MODRINTH_RETRY_BACKOFF_BASE_SECONDS,
        retry_backoff_max_seconds=MODRINTH_RETRY_BACKOFF_MAX_SECONDS,
    )
    parsed = parse_modrinth_version_lookup_response(raw_payload, algorithm)
    logger.debug(
        f"Modrinth batch summary: items={batch_stats['requested_items']}, chunks={batch_stats['requested_chunks']}, retried_chunks={batch_stats['retried_chunks']}, split_chunks={batch_stats['split_chunks']}, failed_items={batch_stats['failed_items']}, resolved={len(parsed)}"
    )
    return parsed


def get_modrinth_latest_versions_by_hashes(
    hashes: list[str] | set[str] | tuple[str, ...],
    algorithm: str = MODRINTH_PREFERRED_HASH_ALGORITHM,
    minecraft_version: str | None = None,
    loader: str | None = None,
) -> dict[str, ModrinthVersionLookupResult]:
    """依雜湊值取得最新的 Modrinth 版本資訊。

    Args:
        hashes: 要查詢的檔案雜湊清單。
        algorithm: 雜湊演算法名稱。
        minecraft_version: 目標 Minecraft 版本。
        loader: 目標載入器類型。

    Returns:
        以雜湊值為 key 的查詢結果字典。
    """
    normalized_hashes = [str(file_hash or "").strip().lower() for file_hash in hashes if str(file_hash or "").strip()]
    if not normalized_hashes:
        return {}
    json_body: dict[str, Any] = {"hashes": normalized_hashes, "algorithm": normalize_hash_algorithm(algorithm)}
    if minecraft_version:
        json_body["game_versions"] = [str(minecraft_version).strip()]
    loader_filters = get_modrinth_loader_filters(loader, minecraft_version)
    if loader_filters:
        json_body["loaders"] = loader_filters

    def _request_chunk(hash_chunk: list[str]) -> dict[str, Any] | None:
        response = HTTPUtils.post_json(
            url=MODRINTH_VERSION_FILES_UPDATE_URL,
            headers=HTTPUtils.get_default_headers(),
            json_body={**json_body, "hashes": hash_chunk},
            timeout=MODRINTH_VERSION_FILES_TIMEOUT_SECONDS,
        )
        return response if isinstance(response, dict) else None

    return _modrinth_versions_by_hashes(
        hashes=normalized_hashes,
        algorithm=algorithm,
        _url=MODRINTH_VERSION_FILES_UPDATE_URL,
        _timeout_seconds=MODRINTH_VERSION_FILES_TIMEOUT_SECONDS,
        request_batch_builder=_request_chunk,
    )


def _fetch_modrinth_project_detail(project_id: str) -> dict[str, Any] | None:
    clean_project_id = clean_api_identifier(project_id)
    if not clean_project_id:
        return None
    response, success, attempts_used = execute_resilient_single_request(
        request_once=lambda: fetch_modrinth_project_detail(
            clean_project_id, timeout=MODRINTH_PROJECT_DETAIL_TIMEOUT_SECONDS
        ),
        is_success=lambda payload: isinstance(payload, dict),
        max_attempts=MODRINTH_SINGLE_REQUEST_RETRY_ATTEMPTS,
        throttle_seconds=MODRINTH_REQUEST_THROTTLE_SECONDS,
        retry_backoff_base_seconds=MODRINTH_RETRY_BACKOFF_BASE_SECONDS,
        retry_backoff_max_seconds=MODRINTH_RETRY_BACKOFF_MAX_SECONDS,
    )
    if success and attempts_used > 1:
        logger.debug(f"Modrinth project detail 重試成功: {clean_project_id}, attempts={attempts_used}")
    if not success:
        logger.debug(f"Modrinth project detail 取得失敗: {clean_project_id}, attempts={attempts_used}")
        return None
    return response


def resolve_local_mod_project_info(local_mod: Any) -> OnlineModInfo | None:
    """盡量將本地模組對應到可用的 Modrinth 專案資訊。

    Args:
        local_mod: 本地模組物件。

    Returns:
        解析後的 Modrinth 專案資訊，失敗時回傳 None。
    """
    _, resolved_project_info = _ensure_local_mod_provider_identity(
        str(getattr(local_mod, "filename", "") or "").strip(),
        platform_id=str(getattr(local_mod, "platform_id", "") or "").strip(),
        platform_slug=str(getattr(local_mod, "platform_slug", "") or "").strip(),
        local_name=str(getattr(local_mod, "name", "") or "").strip(),
        resolution_source=str(getattr(local_mod, "resolution_source", "") or "").strip(),
        resolved_at_epoch_ms=getattr(local_mod, "resolved_at_epoch_ms", None),
    )
    return resolved_project_info


def _build_provider_record_from_online_mod(mod_info: OnlineModInfo | None) -> ProviderMetadataRecord | None:
    if mod_info is None:
        return None
    project_id = clean_api_identifier(str(getattr(mod_info, "project_id", "") or ""))
    slug = str(getattr(mod_info, "slug", "") or "").strip()
    if not project_id and (not slug):
        return None
    return ProviderMetadataRecord.from_values(
        platform="modrinth",
        project_id=project_id,
        slug=slug,
        project_name=str(getattr(mod_info, "name", "") or "").strip(),
    )


def _normalize_cached_provider_identity(
    *,
    platform_id: str | None = None,
    platform_slug: str | None = None,
    resolution_source: str | None = None,
    resolved_at_epoch_ms: Any | None = None,
) -> tuple[str, str, bool]:
    clean_project_id = clean_api_identifier(platform_id)
    clean_slug = str(platform_slug or "").strip()
    if not clean_project_id and (not clean_slug):
        return ("", "", False)
    raw_cached_provider: dict[str, Any] = {"platform": "modrinth"}
    if clean_project_id:
        raw_cached_provider["project_id"] = clean_project_id
    if clean_slug:
        raw_cached_provider["slug"] = clean_slug
    clean_resolution_source = str(resolution_source or "").strip().lower()
    if clean_resolution_source:
        raw_cached_provider["resolution_source"] = clean_resolution_source
    if resolved_at_epoch_ms not in (None, ""):
        raw_cached_provider["resolved_at_epoch_ms"] = str(resolved_at_epoch_ms).strip()
    if is_cached_provider_metadata_fresh(raw_cached_provider):
        return (clean_project_id, clean_slug, False)
    return ("", "", True)


def _ensure_local_mod_provider_identity(
    filename: str,
    *,
    platform_id: str | None = None,
    platform_slug: str | None = None,
    local_name: str | None = None,
    resolution_source: str | None = None,
    resolved_at_epoch_ms: Any | None = None,
    allow_stale_fallback: bool = False,
) -> tuple[LocalProviderEnsureResult, OnlineModInfo | None]:
    """使用共用 orchestration 解析本地模組 provider identity。"""
    fresh_platform_id, fresh_platform_slug, cached_provider_is_stale = _normalize_cached_provider_identity(
        platform_id=platform_id,
        platform_slug=platform_slug,
        resolution_source=resolution_source,
        resolved_at_epoch_ms=resolved_at_epoch_ms,
    )
    stale_platform_id = clean_api_identifier(platform_id)
    stale_platform_slug = str(platform_slug or "").strip()
    exact_identifiers, search_terms, candidate_keys = build_local_mod_lookup_candidates(
        filename, platform_id=fresh_platform_id, platform_slug=fresh_platform_slug, local_name=local_name
    )
    fallback_project_info: OnlineModInfo | None = None

    def _identifier_resolver(identifier: str) -> ProviderMetadataRecord:
        nonlocal fallback_project_info
        exact_match = get_modrinth_project_info(identifier)
        if exact_match is not None:
            fallback_project_info = exact_match
            resolved_record = _build_provider_record_from_online_mod(exact_match)
            if resolved_record is not None:
                return resolved_record
        return resolve_modrinth_provider_record(identifier)

    def _local_mod_search_fallback_resolver() -> ProviderMetadataRecord | None:
        nonlocal fallback_project_info
        for candidate_identifier in exact_identifiers:
            exact_match = get_modrinth_project_info(candidate_identifier)
            if exact_match is None:
                continue
            fallback_project_info = exact_match
            return _build_provider_record_from_online_mod(exact_match)
        best_match: OnlineModInfo | None = None
        best_score = -1
        for search_term in search_terms:
            mods = search_mods_online(search_term, limit=8)
            if not mods:
                continue
            for mod in mods:
                score = _score_local_mod_search_match(mod, candidate_keys)
                if score > best_score:
                    best_match = mod
                    best_score = score
            if best_score >= 100:
                break
        if best_score < MIN_ACCEPTABLE_LOCAL_MOD_SEARCH_SCORE or best_match is None:
            return None
        fallback_project_info = best_match
        return _build_provider_record_from_online_mod(best_match)

    ensured = ensure_local_mod_provider_record(
        platform_id=fresh_platform_id,
        platform_slug=fresh_platform_slug,
        project_name=local_name,
        identifier_resolver=_identifier_resolver,
        fallback_resolver=_local_mod_search_fallback_resolver,
    )
    if fallback_project_info is not None:
        return (ensured, fallback_project_info)
    if ensured.record.project_id:
        return (
            ensured,
            OnlineModInfo(
                project_id=ensured.record.project_id,
                slug=ensured.record.slug,
                name=ensured.record.project_name or str(local_name or "").strip() or ensured.record.project_id,
                author="",
            ),
        )
    if allow_stale_fallback and cached_provider_is_stale and (stale_platform_id or stale_platform_slug):
        stale_identifier = stale_platform_id or stale_platform_slug
        return (
            LocalProviderEnsureResult(
                record=ProviderMetadataRecord.from_values(
                    project_id=stale_platform_id, slug=stale_platform_slug, project_name=str(local_name or "").strip()
                ),
                source="stale_cached_provider",
                resolved=False,
                lifecycle_state=PROVIDER_LIFECYCLE_STALE,
            ),
            OnlineModInfo(
                project_id=stale_identifier,
                slug=stale_platform_slug or stale_identifier,
                name=str(local_name or "").strip() or stale_identifier,
                author="",
                source="modrinth_stale_cache",
                available=False,
            ),
        )
    return (ensured, None)


def get_modrinth_project_info(project_id: str) -> OnlineModInfo | None:
    """依 project id 或 slug 取得單一 Modrinth 專案資訊。

    Args:
        project_id: Modrinth project id 或 slug。

    Returns:
        專案資訊，找不到時回傳 None。
    """
    response = _fetch_modrinth_project_detail(project_id)
    if not response:
        return None
    slug = str(response.get("slug", "") or "").strip()
    resolved_project_id = clean_api_identifier(str(response.get("id", "") or project_id))
    project_slug = slug or resolved_project_id
    url = f"{MODRINTH_PROJECT_URL}/{project_slug}" if project_slug else MODRINTH_PROJECT_URL
    categories = [str(category) for category in response.get("categories", []) if category]
    additional_categories = [str(category) for category in response.get("additional_categories", []) if category]
    homepage_url = str(
        response.get("website_url", "") or response.get("source_url", "") or response.get("issues_url", "") or url
    ).strip()
    return OnlineModInfo(
        project_id=resolved_project_id,
        slug=project_slug,
        name=str(response.get("title", "") or response.get("name", "") or project_slug or resolved_project_id),
        author=str(response.get("author", "") or "").strip(),
        description=str(response.get("description", "") or "").strip(),
        latest_version="",
        download_count=int(response.get("downloads", 0) or 0),
        icon_url=str(response.get("icon_url", "") or "").strip(),
        homepage_url=homepage_url or url,
        url=url,
        categories=[*categories, *[category for category in additional_categories if category not in categories]],
        versions=[str(version) for version in response.get("versions", []) if version],
        server_side=str(response.get("server_side", "") or "").strip(),
        client_side=str(response.get("client_side", "") or "").strip(),
    )


def _fetch_modrinth_project_name(project_id: str) -> str | None:
    response = _fetch_modrinth_project_detail(project_id)
    if not response:
        return None
    resolved_name = str(
        response.get("title", "")
        or response.get("name", "")
        or response.get("slug", "")
        or clean_api_identifier(project_id)
    ).strip()
    return resolved_name or None


def get_mod_version_details(version_id: str) -> tuple[str, OnlineModVersion | None]:
    """依 Modrinth version id 取得精確版本資訊，並回傳其所屬 project id。

    Args:
        version_id: Modrinth version id。

    Returns:
        `(project_id, version_info)` 的查詢結果。
    """
    clean_version_id = clean_api_identifier(version_id)
    if not clean_version_id:
        return ("", None)
    response, success, attempts_used = execute_resilient_single_request(
        request_once=lambda: HTTPUtils.get_json(
            url=MODRINTH_VERSION_DETAIL_URL_TEMPLATE.format(version_id=clean_version_id),
            headers=HTTPUtils.get_default_headers(),
            timeout=MODRINTH_VERSION_DETAIL_TIMEOUT_SECONDS,
        ),
        is_success=lambda payload: isinstance(payload, dict),
        max_attempts=MODRINTH_SINGLE_REQUEST_RETRY_ATTEMPTS,
        throttle_seconds=MODRINTH_REQUEST_THROTTLE_SECONDS,
        retry_backoff_base_seconds=MODRINTH_RETRY_BACKOFF_BASE_SECONDS,
        retry_backoff_max_seconds=MODRINTH_RETRY_BACKOFF_MAX_SECONDS,
    )
    if not success or not isinstance(response, dict):
        logger.error(f"取得 Modrinth 版本詳細資訊失敗: {clean_version_id}")
        return ("", None)
    if attempts_used > 1:
        logger.debug(f"Modrinth version detail 重試成功: {clean_version_id}, attempts={attempts_used}")
    project_id = clean_api_identifier(str(response.get("project_id", "") or ""))
    return (project_id, parse_modrinth_version(response))


def _resolve_dependency_reference(
    dependency: dict[str, Any],
    dependency_names: dict[str, str],
    *,
    loader: str | None = None,
    version_details_cache: dict[str, tuple[str, OnlineModVersion | None]] | None = None,
) -> ResolvedDependencyReference:
    return resolve_dependency_reference(
        dependency,
        dependency_names,
        loader=loader,
        version_details_cache=version_details_cache,
        get_mod_version_details=get_mod_version_details,
        fetch_project_name=_fetch_modrinth_project_name,
    )


def _check_loader_version_rule(
    minecraft_version: str | None, loader: str | None, loader_version: str | None
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    notes: list[str] = []
    normalized_minecraft_version = str(minecraft_version or "").strip()
    normalized_loader = normalize_identifier(loader)
    normalized_loader_version = normalize_identifier(loader_version)
    if not normalized_minecraft_version or not normalized_loader or (not normalized_loader_version):
        return (warnings, notes)
    try:
        compatible_versions = LoaderManager().get_compatible_loader_versions(
            normalized_minecraft_version, normalized_loader
        )
    except Exception as e:
        logger.warning(f"讀取 {normalized_loader} 載入器規則失敗: {e}")
        return (warnings, notes)
    available_versions = {normalize_identifier(version.version) for version in compatible_versions if version.version}
    if not available_versions:
        notes.append(
            f"目前找不到 {normalized_loader} 對 Minecraft {normalized_minecraft_version} 的本地規則快取，因此無法額外驗證 loader 版本 {loader_version}。"
        )
        return (warnings, notes)
    if normalized_loader_version in available_versions:
        notes.append(
            f"已使用內建 {normalized_loader.capitalize()} 規則確認 loader 版本 {loader_version} 適用於 Minecraft {normalized_minecraft_version}。"
        )
    else:
        warnings.append(
            f"目前伺服器設定的 {normalized_loader.capitalize()} loader 版本 {loader_version} 不在 Minecraft {normalized_minecraft_version} 的已知可用清單內，系統將維持安全檢查模式。"
        )
    return (warnings, notes)


def resolve_modrinth_project_names(project_ids: list[str] | set[str] | tuple[str, ...]) -> dict[str, str]:
    """將 Modrinth project id 轉為較易讀的專案名稱。

    Args:
        project_ids: 要解析的 project id 清單。

    Returns:
        以 project id 為 key 的名稱對應表。
    """
    deduped_project_ids: dict[str, str] = {}
    for project_id in project_ids:
        clean_project_id = clean_api_identifier(project_id)
        if not clean_project_id:
            continue
        deduped_project_ids.setdefault(normalize_identifier(clean_project_id), clean_project_id)
    if not deduped_project_ids:
        return {}
    raw_ids = list(deduped_project_ids.values())

    def _request_chunk(id_chunk: list[str]) -> dict[str, Any] | None:
        response = HTTPUtils.get_json(
            url=MODRINTH_PROJECT_BATCH_URL,
            headers=HTTPUtils.get_default_headers(),
            params={"ids": PathUtils.to_json_str(id_chunk)},
            timeout=MODRINTH_PROJECT_BATCH_TIMEOUT_SECONDS,
        )
        if not isinstance(response, list):
            return None
        payload: dict[str, Any] = {}
        for item in response:
            if not isinstance(item, dict):
                continue
            project_id = clean_api_identifier(str(item.get("id", "") or ""))
            if project_id:
                payload[project_id] = item
        return payload

    raw_payload, batch_stats = execute_resilient_batch_requests(
        raw_ids,
        batch_size=MODRINTH_BATCH_PROJECT_LOOKUP_SIZE,
        max_attempts=MODRINTH_BATCH_RETRY_ATTEMPTS,
        request_batch=_request_chunk,
        throttle_seconds=MODRINTH_REQUEST_THROTTLE_SECONDS,
        retry_backoff_base_seconds=MODRINTH_RETRY_BACKOFF_BASE_SECONDS,
        retry_backoff_max_seconds=MODRINTH_RETRY_BACKOFF_MAX_SECONDS,
    )
    names: dict[str, str] = {}
    for project_id, item in raw_payload.items():
        if not isinstance(item, dict):
            continue
        project_key = normalize_identifier(project_id)
        if not project_key:
            continue
        name = str(item.get("title", "") or item.get("name", "") or item.get("slug", "") or project_id).strip()
        names[project_key] = name or project_id
    logger.debug(
        f"Modrinth projects batch summary: items={batch_stats['requested_items']}, chunks={batch_stats['requested_chunks']}, retried_chunks={batch_stats['retried_chunks']}, split_chunks={batch_stats['split_chunks']}, failed_items={batch_stats['failed_items']}, resolved={len(names)}"
    )
    for project_key, raw_project_id in deduped_project_ids.items():
        if project_key in names:
            continue
        resolved_name = _fetch_modrinth_project_name(raw_project_id)
        if resolved_name:
            names[project_key] = resolved_name
        else:
            logger.debug(f"無法解析 Modrinth 專案名稱，保留 project id: {raw_project_id}")
    return names


def analyze_mod_version_compatibility(
    version: OnlineModVersion,
    project_id: str = "",
    project_name: str = "",
    minecraft_version: str | None = None,
    loader: str | None = None,
    loader_version: str | None = None,
    installed_mods: list[Any] | None = None,
    dependency_names: dict[str, str] | None = None,
) -> OnlineModCompatibilityReport:
    """根據目前伺服器與已安裝模組分析可用版本的相容性。

    Args:
        version: Modrinth 版本資訊。
        project_id: 模組 project id。
        project_name: 模組名稱。
        minecraft_version: 目標 Minecraft 版本。
        loader: 目標載入器類型。
        loader_version: 目標載入器版本。
        installed_mods: 已安裝模組清單。
        dependency_names: 依賴名稱對照表。

    Returns:
        相容性分析報告。
    """
    report = OnlineModCompatibilityReport()
    dependency_name_map = dependency_names or {}
    normalized_minecraft_version = normalize_identifier(minecraft_version)
    compatible_loaders = expand_target_loader_aliases(loader, minecraft_version)
    version_game_versions = {normalize_identifier(entry) for entry in version.game_versions if entry}
    version_loaders = {normalize_identifier(entry) for entry in version.loaders if entry}
    if (
        normalized_minecraft_version
        and version_game_versions
        and (normalized_minecraft_version not in version_game_versions)
    ):
        report.hard_errors.append(
            f"此版本支援的 Minecraft 版本為 {', '.join(version.game_versions)}，不符合目前伺服器的 {minecraft_version}。"
        )
    if compatible_loaders and version_loaders and compatible_loaders.isdisjoint(version_loaders):
        report.hard_errors.append(f"此版本支援的載入器為 {', '.join(version.loaders)}，不符合目前伺服器的 {loader}。")
    if not version.primary_file:
        report.hard_errors.append("此版本沒有可下載的 JAR 檔案。")
    rule_warnings, rule_notes = _check_loader_version_rule(minecraft_version, loader, loader_version)
    report.warnings.extend(rule_warnings)
    report.notes.extend(rule_notes)
    installed_project_ids, installed_identifiers = collect_installed_mod_identifiers(installed_mods)
    installed_versions_by_project = collect_installed_mod_versions(installed_mods)
    version_details_cache: dict[str, tuple[str, OnlineModVersion | None]] = {}
    normalized_project_id = normalize_identifier(project_id)
    if normalized_project_id and normalized_project_id in installed_project_ids:
        existing_name = project_name or normalized_project_id
        report.already_installed.append(existing_name)
        report.warnings.append(f"目前伺服器已安裝 {existing_name}，系統會以安全策略避免重複安裝。")
    for dependency in version.dependencies:
        if not isinstance(dependency, dict):
            continue
        dependency_type = normalize_identifier(str(dependency.get("dependency_type", "required") or "required"))
        resolved_dependency = _resolve_dependency_reference(
            dependency, dependency_name_map, loader=loader, version_details_cache=version_details_cache
        )
        dependency_project_id = resolved_dependency.compare_project_id
        dependency_label = resolved_dependency.label
        normalized_label = normalize_identifier(dependency_label)
        is_installed = False
        has_required_version = True
        if (dependency_project_id and dependency_project_id in installed_project_ids) or (
            normalized_label and normalized_label in installed_identifiers
        ):
            is_installed = True
        maybe_installed = False
        if not is_installed:
            maybe_installed = dependency_maybe_installed_by_filename(resolved_dependency, installed_mods)
        required_version = normalize_identifier(
            getattr(resolved_dependency.version, "version_number", "") or resolved_dependency.version_name
        )
        installed_versions = sorted(installed_versions_by_project.get(dependency_project_id, set()))
        if is_installed and required_version:
            has_required_version = required_version in installed_versions
        if dependency_type == "required" and is_installed and required_version and (not has_required_version):
            installed_version_text = ", ".join(installed_versions) if installed_versions else "未知版本"
            mismatch_message = f"{dependency_label} 目前已安裝，但版本為 {installed_version_text}，與需求版本 {resolved_dependency.version_name or required_version} 不符。"
            report.installed_version_mismatches.append(mismatch_message)
            report.warnings.append(mismatch_message)
            report.missing_required_dependencies.append(dependency_label)
            continue
        if dependency_type == "required":
            if not is_installed:
                report.missing_required_dependencies.append(dependency_label)
                if maybe_installed:
                    report.notes.append(f"{dependency_label} 可能已存在本地相近檔名，系統已先採安全略過策略。")
                    report.warnings.append(f"必要依賴可能已存在但尚未能以 metadata 精確識別：{dependency_label}")
                else:
                    report.warnings.append(f"缺少必要依賴：{dependency_label}")
        elif dependency_type == "optional":
            if not is_installed:
                report.optional_dependencies.append(dependency_label)
        elif dependency_type == "incompatible":
            if is_installed:
                report.incompatible_installed.append(dependency_label)
                report.warnings.append(f"偵測到已安裝的不相容模組：{dependency_label}")
        elif dependency_type == "embedded":
            report.embedded_dependencies.append(dependency_label)
        elif not is_installed:
            report.notes.append(f"依賴 {dependency_label} 的類型為 {dependency_type}，系統已先採安全保守策略。")
    return report


def build_required_dependency_install_plan(
    version: OnlineModVersion,
    *,
    minecraft_version: str | None = None,
    loader: str | None = None,
    loader_version: str | None = None,
    installed_mods: list[Any] | None = None,
    root_project_id: str = "",
    root_project_name: str = "",
    max_depth: int = 20,
) -> OnlineDependencyInstallPlan:
    """為必要依賴建立可自動安裝的連鎖安裝計畫。

    Args:
        version: Modrinth 版本資訊。
        minecraft_version: 目標 Minecraft 版本。
        loader: 目標載入器類型。
        loader_version: 目標載入器版本。
        installed_mods: 已安裝模組清單。
        root_project_id: 根專案 id。
        root_project_name: 根專案名稱。
        max_depth: 依賴展開深度上限。

    Returns:
        必要依賴安裝計畫。
    """
    plan = OnlineDependencyInstallPlan()
    installed_project_ids, _ = collect_installed_mod_identifiers(installed_mods)
    installed_versions_by_project = collect_installed_mod_versions(installed_mods)
    version_details_cache: dict[str, tuple[str, OnlineModVersion | None]] = {}

    def _resolve_dependency_entry(
        dependency: dict[str, Any], dependency_names: dict[str, str]
    ) -> ResolvedDependencyReference:
        return _resolve_dependency_reference(
            dependency, dependency_names, loader=loader, version_details_cache=version_details_cache
        )

    def _select_dependency_best_version(
        resolved_dependency: ResolvedDependencyReference, *, log_filtered_fallback: bool
    ) -> OnlineModVersion | None:
        dependency_api_project_id = clean_api_identifier(resolved_dependency.project_id)
        if not dependency_api_project_id:
            return None
        if resolved_dependency.version is not None:
            dependency_versions = [resolved_dependency.version]
        else:
            dependency_versions = get_mod_versions(dependency_api_project_id, minecraft_version, loader)
            if not dependency_versions:
                if log_filtered_fallback:
                    logger.warning(
                        f"以目前條件找不到必要依賴版本，回退為未過濾查詢: {resolved_dependency.label} ({resolved_dependency.compare_project_id})"
                    )
                dependency_versions = get_mod_versions(dependency_api_project_id)
        return select_best_mod_version(dependency_versions)

    def _analyze_dependency_best_version(
        best_version: OnlineModVersion,
        resolved_dependency: ResolvedDependencyReference,
        dependency_label: str,
        dependency_names: dict[str, str],
    ) -> OnlineModCompatibilityReport:
        return analyze_mod_version_compatibility(
            best_version,
            project_id=resolved_dependency.project_id,
            project_name=dependency_label,
            minecraft_version=minecraft_version,
            loader=loader,
            loader_version=loader_version,
            installed_mods=installed_mods,
            dependency_names=dependency_names,
        )

    def _extract_dependency_download_target(best_version: OnlineModVersion) -> tuple[str, str] | None:
        primary_file = best_version.primary_file
        if not primary_file:
            return None
        download_url = str(primary_file.get("url", "") or "").strip()
        filename = str(primary_file.get("filename", "") or "").strip()
        if not download_url or not filename:
            return None
        return (download_url, filename)

    def _make_dependency_install_item(
        resolved_dependency: ResolvedDependencyReference,
        dependency_label: str,
        best_version: OnlineModVersion,
        download_url: str,
        filename: str,
        parent_name: str,
        *,
        maybe_installed: bool,
        status_note: str,
        enabled: bool,
        is_optional: bool,
        decision_source: str,
        graph_depth: int,
        edge_kind: str,
        edge_source: str,
    ) -> OnlineDependencyInstallItem:
        expected_hash = (
            extract_primary_file_hash(best_version)
            or extract_primary_file_hash(best_version, "sha1")
            or extract_primary_file_hash(best_version, "sha256")
        )
        return OnlineDependencyInstallItem(
            project_id=resolved_dependency.project_id,
            project_name=dependency_label,
            version_id=best_version.version_id,
            version_name=best_version.display_name,
            filename=filename,
            download_url=download_url,
            parent_name=parent_name,
            maybe_installed=maybe_installed,
            status_note=status_note,
            resolution_source=resolved_dependency.resolution_source,
            resolution_confidence=resolved_dependency.resolution_confidence,
            enabled=enabled,
            is_optional=is_optional,
            provider=str(getattr(best_version, "provider", "modrinth") or "modrinth").strip() or "modrinth",
            expected_hash=expected_hash,
            required_by=[parent_name] if parent_name else [],
            decision_source=str(decision_source or "").strip() or "required:auto",
            graph_depth=max(1, int(graph_depth)),
            edge_kind=str(edge_kind or "required").strip().lower() or "required",
            edge_source=str(edge_source or "").strip().lower()
            or f"{str(edge_kind or 'required').strip().lower() or 'required'}:modrinth_dependency",
        )

    expand_required_dependency_install_plan(
        root_version=version,
        plan=plan,
        hooks=DependencyPlanHooks(
            resolve_project_names=resolve_modrinth_project_names,
            resolve_dependency_entry=_resolve_dependency_entry,
            select_dependency_best_version=lambda resolved_dependency, log_filtered_fallback: (
                _select_dependency_best_version(resolved_dependency, log_filtered_fallback=log_filtered_fallback)
            ),
            analyze_dependency_best_version=_analyze_dependency_best_version,
            extract_dependency_download_target=_extract_dependency_download_target,
            make_dependency_install_item=_make_dependency_install_item,
            maybe_installed_checker=dependency_maybe_installed_by_filename,
        ),
        installed_project_ids=installed_project_ids,
        installed_versions_by_project=installed_versions_by_project,
        installed_mods=installed_mods,
        root_project_id=root_project_id,
        root_project_name=root_project_name,
        max_depth=max_depth,
        log_debug=logger.debug,
        log_info=logger.info,
    )
    logger.info(
        f"必要依賴安裝計畫建立完成: root={root_project_name or root_project_id or 'unknown'}, auto_install={plan.auto_install_count}, unresolved={len(plan.unresolved_required)}"
    )
    return plan


def _map_hit_to_online_mod(hit: dict[str, Any]) -> OnlineModInfo:
    slug = str(hit.get("slug", "") or "")
    project_id = str(hit.get("project_id", "") or slug)
    project_slug = slug or project_id
    url = f"{MODRINTH_PROJECT_URL}/{project_slug}" if project_slug else MODRINTH_PROJECT_URL
    return OnlineModInfo(
        project_id=project_id,
        slug=project_slug,
        name=str(hit.get("title", "Unknown") or "Unknown"),
        author=str(hit.get("author", "?") or "?"),
        description=str(hit.get("description", "") or ""),
        latest_version=str(hit.get("latest_version", "") or ""),
        download_count=int(hit.get("downloads", 0) or 0),
        icon_url=str(hit.get("icon_url", "") or ""),
        homepage_url=str(hit.get("homepage_url", "") or url),
        url=url,
        categories=list(hit.get("categories", []) or []),
        versions=list(hit.get("versions", []) or []),
        server_side=str(hit.get("server_side", "") or "").strip(),
        client_side=str(hit.get("client_side", "") or "").strip(),
    )


def _is_server_compatible_online_mod(mod: OnlineModInfo) -> bool:
    server_side = str(getattr(mod, "server_side", "") or "").strip().lower()
    client_side = str(getattr(mod, "client_side", "") or "").strip().lower()
    if server_side in {"required", "optional"}:
        return True
    return client_side != "required"


def search_mods_online(
    query: str,
    minecraft_version: str | None = None,
    loader: str | None = None,
    categories: list[str] | None = None,
    sort_by: str = "relevance",
    limit: int = 20,
) -> list[OnlineModInfo]:
    """透過 Modrinth API 搜尋或瀏覽模組。

    Args:
        query: 搜尋關鍵字。
        minecraft_version: 目標 Minecraft 版本。
        loader: 目標載入器類型。
        categories: 額外分類條件。
        sort_by: 排序方式。
        limit: 最多回傳數量。

    Returns:
        搜尋到的模組清單。
    """
    raw_query = str(query or "").strip()
    normalized_query = normalize_mod_search_query(raw_query) if raw_query else ""
    if raw_query and normalized_query != raw_query:
        logger.debug(f"Modrinth 搜尋字串正規化: {raw_query} -> {normalized_query}")
    facets = [["project_type:mod"], ["server_side:required", "server_side:optional"]]
    if minecraft_version:
        facets.append([f"game_versions:{minecraft_version}"])
    loader_categories = get_modrinth_loader_filters(loader, minecraft_version)
    if loader_categories:
        facets.append([f"categories:{loader_category}" for loader_category in loader_categories])
    if categories:
        category_facets = [f"categories:{cat}" for cat in categories if cat]
        if category_facets:
            facets.append(category_facets)
    params = {
        "limit": max(1, min(int(limit), 50)),
        "facets": PathUtils.to_json_str(facets),
        "index": _normalize_sort(sort_by),
    }
    if normalized_query:
        params["query"] = normalized_query
    response = HTTPUtils.get_json(
        url=MODRINTH_SEARCH_URL,
        headers=HTTPUtils.get_default_headers(),
        params=params,
        timeout=MODRINTH_SEARCH_TIMEOUT_SECONDS,
    )
    if not response:
        logger.error("Modrinth API request failed")
        return []
    mods = [_map_hit_to_online_mod(hit) for hit in response.get("hits", []) if isinstance(hit, dict)]
    mods = [mod for mod in mods if _is_server_compatible_online_mod(mod)]
    if sort_by == "downloads":
        mods.sort(key=lambda item: item.download_count, reverse=True)
    elif sort_by == "name":
        mods.sort(key=lambda item: item.name.lower())
    return mods


def get_mod_versions(
    project_id: str, minecraft_version: str | None = None, loader: str | None = None
) -> list[OnlineModVersion]:
    """取得指定 Modrinth 模組的穩定版本。

    Args:
        project_id: Modrinth project id。
        minecraft_version: 目標 Minecraft 版本。
        loader: 目標載入器類型。

    Returns:
        符合條件的版本清單。
    """
    clean_project_id = clean_api_identifier(project_id)
    if not clean_project_id:
        return []
    url = MODRINTH_VERSION_URL_TEMPLATE.format(project_id=clean_project_id)
    response, success, attempts_used = execute_resilient_single_request(
        request_once=lambda: HTTPUtils.get_json(
            url=url, headers=HTTPUtils.get_default_headers(), timeout=MODRINTH_VERSION_TIMEOUT_SECONDS
        ),
        is_success=lambda payload: isinstance(payload, list),
        max_attempts=MODRINTH_SINGLE_REQUEST_RETRY_ATTEMPTS,
        throttle_seconds=MODRINTH_REQUEST_THROTTLE_SECONDS,
        retry_backoff_base_seconds=MODRINTH_RETRY_BACKOFF_BASE_SECONDS,
        retry_backoff_max_seconds=MODRINTH_RETRY_BACKOFF_MAX_SECONDS,
    )
    if not success or not isinstance(response, list):
        logger.error(f"取得 Modrinth 版本列表失敗: {clean_project_id}")
        return []
    if attempts_used > 1:
        logger.debug(f"Modrinth project versions 重試成功: {clean_project_id}, attempts={attempts_used}")
    loader_filters = set(get_modrinth_loader_filters(loader, minecraft_version))
    versions: list[OnlineModVersion] = []
    for item in response:
        if not isinstance(item, dict):
            continue
        parsed_version = parse_modrinth_version(item)
        game_versions = parsed_version.game_versions
        loaders = parsed_version.loaders
        if minecraft_version and minecraft_version not in game_versions:
            continue
        normalized_version_loaders = {normalize_identifier(entry) for entry in loaders if entry}
        if loader_filters and loader_filters.isdisjoint(normalized_version_loaders):
            continue
        if not is_allowed_version_type(parsed_version.version_type):
            continue
        versions.append(parsed_version)
    return versions


def get_recommended_mod_version(
    project_id: str, minecraft_version: str | None = None, loader: str | None = None
) -> OnlineModVersion | None:
    """取得最適合目前條件的推薦版本，若條件下查無版本則回退到未過濾結果。"""
    clean_project_id = clean_api_identifier(project_id)
    if not clean_project_id:
        return None
    versions = get_mod_versions(clean_project_id, minecraft_version, loader)
    if not versions:
        if not is_supported_modrinth_update_loader(loader):
            return None
        versions = get_mod_versions(clean_project_id)
    return select_best_mod_version(versions)


def analyze_local_mod_file_compatibility(
    local_mod: Any, minecraft_version: str | None = None, loader: str | None = None
) -> list[str]:
    """以本地模組已知 metadata 產生輔助提示。

    Args:
        local_mod: 本地模組物件。
        minecraft_version: 目標 Minecraft 版本。
        loader: 目標載入器類型。

    Returns:
        提示與警告清單。

    本地 jar 解析出的 Minecraft 版本常已失去 range 語意，只適合作為提示，
    不適合直接當成更新可行性的判定依據。
    """
    advisories: list[str] = []
    if not is_supported_modrinth_update_loader(loader):
        return advisories
    local_name = str(getattr(local_mod, "name", "") or getattr(local_mod, "filename", "模組")).strip() or "模組"
    str(getattr(local_mod, "minecraft_version", "") or "").strip()
    local_loader = str(getattr(local_mod, "loader_type", "") or "").strip()
    local_version = str(getattr(local_mod, "version", "") or "").strip()
    normalized_local_loader = normalize_local_loader(local_loader)
    compatible_target_loaders = expand_target_loader_aliases(loader, minecraft_version)
    if (
        normalized_local_loader
        and normalized_local_loader not in {"", "未知", "unknown"}
        and compatible_target_loaders
        and (normalized_local_loader not in compatible_target_loaders)
    ):
        advisories.append(f"{local_name} 目前本地 metadata 顯示載入器為 {local_loader}，與伺服器的 {loader} 不一致。")
    if not local_version or local_version == "未知":
        advisories.append(f"{local_name} 的本地版本資訊未知，無法精準判斷是否已是最新版本。")
    return advisories


def build_local_mod_update_plan(
    local_mods: list[Any] | None,
    minecraft_version: str | None = None,
    loader: str | None = None,
    loader_version: str | None = None,
    hash_progress_callback: Callable[[int, int], None] | None = None,
    revalidation_batch_base_limit: int | None = None,
    revalidation_batch_min_limit: int = 1,
    revalidation_batch_max_limit: int | None = None,
    revalidation_adaptive_enabled: bool = True,
    revalidation_failure_high_watermark: float = 0.6,
    revalidation_failure_low_watermark: float = 0.25,
    revalidation_latency_threshold_ms: float = 800.0,
) -> LocalModUpdatePlan:
    """為本地模組建立更新檢查計畫，優先採用 Prism 風格的 hash-first 批次檢查。

    Args:
        local_mods: 本地模組清單。
        minecraft_version: 目標 Minecraft 版本。
        loader: 目標載入器類型。
        loader_version: 目標載入器版本。
        hash_progress_callback: hash 進度回呼。
        revalidation_batch_base_limit: 重查批次基準上限。
        revalidation_batch_min_limit: 重查批次最小上限。
        revalidation_batch_max_limit: 重查批次最大上限。
        revalidation_adaptive_enabled: 是否啟用自適應調整。
        revalidation_failure_high_watermark: 高失敗率門檻。
        revalidation_failure_low_watermark: 低失敗率門檻。
        revalidation_latency_threshold_ms: 延遲門檻毫秒數。

    Returns:
        本地模組更新檢查計畫。
    """
    plan = LocalModUpdatePlan()
    installed_mods = list(local_mods or [])
    plan.metadata_summary.total_scanned = len(installed_mods)
    normalized_target_loader = normalize_local_loader(loader)
    supports_online_loader_updates = is_supported_modrinth_update_loader(loader)
    if normalized_target_loader and (not supports_online_loader_updates):
        plan.notes.append(
            f"目前本地更新的線上比對僅支援 Fabric / Forge 生態（含相容 alias），已略過 {loader} 的版本更新判定。"
        )
    hash_algorithm = MODRINTH_PREFERRED_HASH_ALGORITHM
    project_ids: list[str] = []
    resolved_project_info_by_filename: dict[str, OnlineModInfo] = {}
    metadata_source_by_filename: dict[str, str] = {}
    unresolved_mod_labels: list[str] = []
    local_hashes_by_filename: dict[str, str] = {}
    stale_provider_revalidation_count = 0
    stale_provider_retryable_count = 0
    stale_provider_revalidation_attempted_count = 0
    stale_provider_revalidation_success_count = 0
    stale_provider_revalidation_failure_count = 0
    stale_provider_revalidation_total_latency_ms = 0.0
    stale_provider_revalidation_backoff_deferred_count = 0
    stale_provider_revalidation_batch_deferred_count = 0
    stale_provider_revalidation_adaptive_adjustment_count = 0
    (
        configured_batch_base_limit,
        configured_batch_min_limit,
        configured_batch_max_limit,
        adaptive_revalidation_batch_limit,
    ) = resolve_revalidation_batch_limits(
        default_base_limit=PROVIDER_REVALIDATION_BATCH_MAX_PER_RUN,
        batch_base_limit=revalidation_batch_base_limit,
        batch_min_limit=revalidation_batch_min_limit,
        batch_max_limit=revalidation_batch_max_limit,
    )
    hash_progress_total = len(installed_mods)
    hash_progress_done = 0

    def _recompute_adaptive_revalidation_batch_limit() -> None:
        nonlocal adaptive_revalidation_batch_limit
        nonlocal stale_provider_revalidation_adaptive_adjustment_count
        next_limit = recompute_adaptive_revalidation_batch_limit(
            current_limit=adaptive_revalidation_batch_limit,
            attempted_count=stale_provider_revalidation_attempted_count,
            failure_count=stale_provider_revalidation_failure_count,
            total_latency_ms=stale_provider_revalidation_total_latency_ms,
            adaptive_enabled=revalidation_adaptive_enabled,
            failure_high_watermark=revalidation_failure_high_watermark,
            failure_low_watermark=revalidation_failure_low_watermark,
            latency_threshold_ms=revalidation_latency_threshold_ms,
            min_limit=configured_batch_min_limit,
            max_limit=configured_batch_max_limit,
        )
        if next_limit != adaptive_revalidation_batch_limit:
            adaptive_revalidation_batch_limit = next_limit
            stale_provider_revalidation_adaptive_adjustment_count += 1

    def _emit_hash_progress() -> None:
        if hash_progress_callback is None or hash_progress_total <= 0:
            return
        try:
            hash_progress_callback(hash_progress_done, hash_progress_total)
        except Exception as e:
            logger.debug(f"回報本地模組 hash 進度失敗: {e}")

    hash_compute_jobs: list[tuple[Any, str, str]] = []
    for local_mod in installed_mods:
        filename_key = str(getattr(local_mod, "filename", "") or "").strip()
        cached_hash = str(getattr(local_mod, "current_hash", "") or "").strip().lower()
        cached_algorithm = normalize_hash_algorithm(getattr(local_mod, "hash_algorithm", hash_algorithm))
        if cached_hash and cached_algorithm == hash_algorithm:
            if filename_key:
                local_hashes_by_filename[filename_key] = cached_hash
            hash_progress_done += 1
            _emit_hash_progress()
            continue
        hash_compute_jobs.append((local_mod, filename_key, str(getattr(local_mod, "file_path", "") or "").strip()))
    if hash_compute_jobs:

        def _compute_local_hash(job: tuple[Any, str, str]) -> tuple[Any, str, str]:
            local_mod_obj, filename_key_obj, file_path_obj = job
            return (local_mod_obj, filename_key_obj, compute_file_hash(file_path_obj, hash_algorithm))

        max_workers = min(LOCAL_HASH_MAX_WORKERS, len(hash_compute_jobs))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for local_mod, filename_key, local_hash in executor.map(_compute_local_hash, hash_compute_jobs):
                if not local_hash:
                    hash_progress_done += 1
                    _emit_hash_progress()
                    continue
                local_mod.current_hash = local_hash
                local_mod.hash_algorithm = hash_algorithm
                if filename_key:
                    local_hashes_by_filename[filename_key] = local_hash
                hash_progress_done += 1
                _emit_hash_progress()
    known_hashes = list(local_hashes_by_filename.values())
    current_versions_by_hash = get_modrinth_current_versions_by_hashes(known_hashes, hash_algorithm)
    latest_versions_by_hash: dict[str, ModrinthVersionLookupResult] = {}
    if supports_online_loader_updates:
        latest_versions_by_hash = get_modrinth_latest_versions_by_hashes(
            known_hashes, hash_algorithm, minecraft_version=minecraft_version, loader=loader
        )
    for local_mod in installed_mods:
        filename_key = str(getattr(local_mod, "filename", "") or "").strip()
        local_hash = local_hashes_by_filename.get(filename_key, "")
        current_match = current_versions_by_hash.get(local_hash)
        latest_match = latest_versions_by_hash.get(local_hash)
        resolved_project_info = None
        metadata_source = ""
        raw_existing_project_id = clean_api_identifier(getattr(local_mod, "platform_id", ""))
        raw_existing_project_slug = str(getattr(local_mod, "platform_slug", "") or "").strip()
        existing_project_id, existing_project_slug, cached_provider_is_stale = _normalize_cached_provider_identity(
            platform_id=raw_existing_project_id,
            platform_slug=raw_existing_project_slug,
            resolution_source=str(getattr(local_mod, "resolution_source", "") or "").strip(),
            resolved_at_epoch_ms=getattr(local_mod, "resolved_at_epoch_ms", None),
        )
        had_fresh_cached_identifier = bool(existing_project_id or existing_project_slug)
        if cached_provider_is_stale:
            stale_provider_revalidation_count += 1
        resolved_project_id = clean_api_identifier(
            getattr(current_match, "project_id", "") or getattr(latest_match, "project_id", "")
        )
        if resolved_project_id:
            apply_provider_metadata(local_mod, ProviderMetadataRecord.from_values(project_id=resolved_project_id))
            resolved_project_info = OnlineModInfo(project_id=resolved_project_id, slug="", name="", author="")
            metadata_source = METADATA_SOURCE_HASH
            plan.metadata_summary.resolved_by_hash += 1
        else:
            fallback_project_info: OnlineModInfo | None = None
            stale_revalidation_skip_reason = ""
            if cached_provider_is_stale and (raw_existing_project_id or raw_existing_project_slug):
                should_attempt_revalidation, revalidation_reason = should_attempt_provider_revalidation(
                    {
                        "next_retry_not_before_epoch_ms": str(
                            getattr(local_mod, "next_retry_not_before_epoch_ms", "") or ""
                        ).strip()
                    },
                    attempted_count=stale_provider_revalidation_attempted_count,
                    max_attempts=adaptive_revalidation_batch_limit,
                )
                if should_attempt_revalidation:
                    stale_provider_revalidation_attempted_count += 1
                else:
                    stale_revalidation_skip_reason = revalidation_reason
                    if revalidation_reason == "backoff":
                        stale_provider_revalidation_backoff_deferred_count += 1
                    elif revalidation_reason == "batch_limit":
                        stale_provider_revalidation_batch_deferred_count += 1

            def _stale_local_mod_fallback_resolver() -> ProviderMetadataRecord | None:
                nonlocal fallback_project_info
                fallback_project_info = resolve_local_mod_project_info(local_mod)
                return _build_provider_record_from_online_mod(fallback_project_info)

            if stale_revalidation_skip_reason:
                ensured = LocalProviderEnsureResult(
                    record=ProviderMetadataRecord.from_values(
                        project_name=str(getattr(local_mod, "name", "") or "").strip()
                    ),
                    source="stale_revalidation_deferred",
                    resolved=False,
                    lifecycle_state=str(getattr(local_mod, "provider_lifecycle_state", "") or "").strip().lower()
                    or PROVIDER_LIFECYCLE_STALE,
                )
            else:
                revalidation_start = time.perf_counter()
                ensured = ensure_local_mod_provider_record(
                    platform_id=existing_project_id,
                    platform_slug=existing_project_slug,
                    project_name=str(getattr(local_mod, "name", "") or "").strip(),
                    identifier_resolver=resolve_modrinth_provider_record,
                    fallback_resolver=_stale_local_mod_fallback_resolver,
                )
                revalidation_elapsed_ms = (time.perf_counter() - revalidation_start) * 1000.0
                stale_provider_revalidation_total_latency_ms += revalidation_elapsed_ms
                if ensured.record.project_id:
                    stale_provider_revalidation_success_count += 1
                else:
                    stale_provider_revalidation_failure_count += 1
                _recompute_adaptive_revalidation_batch_limit()
            apply_provider_metadata(local_mod, ensured.record)
            if ensured.record.project_id:
                metadata_source = (
                    METADATA_SOURCE_CACHED_PROVIDER
                    if ensured.source == METADATA_SOURCE_CACHED_PROVIDER or had_fresh_cached_identifier
                    else METADATA_SOURCE_LOOKUP
                )
                if metadata_source == METADATA_SOURCE_CACHED_PROVIDER:
                    plan.metadata_summary.resolved_by_cached_project += 1
                else:
                    plan.metadata_summary.resolved_by_lookup += 1
                resolved_project_info = fallback_project_info or OnlineModInfo(
                    project_id=ensured.record.project_id,
                    slug=ensured.record.slug,
                    name=ensured.record.project_name or str(getattr(local_mod, "name", "") or "").strip(),
                    author="",
                )
        if resolved_project_info is None:
            unresolved_label = str(
                getattr(local_mod, "name", "") or getattr(local_mod, "filename", "") or "模組"
            ).strip()
            if cached_provider_is_stale and (raw_existing_project_id or raw_existing_project_slug):
                stale_provider_retryable_count += 1
                stale_identifier = raw_existing_project_id or raw_existing_project_slug
                lifecycle_state = str(getattr(local_mod, "provider_lifecycle_state", "") or "").strip().lower()
                retry_due = is_provider_revalidation_retry_due(
                    {
                        "next_retry_not_before_epoch_ms": str(
                            getattr(local_mod, "next_retry_not_before_epoch_ms", "") or ""
                        ).strip()
                    }
                )
                is_invalidated_backoff = lifecycle_state == PROVIDER_LIFECYCLE_INVALIDATED and (not retry_due)
                is_retrying_backoff = lifecycle_state == PROVIDER_LIFECYCLE_RETRYING and (not retry_due)
                confidence = RECOMMENDATION_CONFIDENCE_RETRYABLE
                hard_error = LOCAL_UPDATE_ERROR_STALE_REVALIDATION_FAILED
                backoff_note = ""
                if is_invalidated_backoff:
                    confidence = RECOMMENDATION_CONFIDENCE_BLOCKED
                    hard_error = LOCAL_UPDATE_ERROR_STALE_REVALIDATION_INVALIDATED
                    backoff_note = LOCAL_UPDATE_NOTE_STALE_BACKOFF_INVALIDATED
                elif is_retrying_backoff:
                    backoff_note = LOCAL_UPDATE_NOTE_STALE_BACKOFF_RETRYING
                notes = [LOCAL_UPDATE_NOTE_STALE_RETRY_AUTO]
                if backoff_note:
                    notes.append(backoff_note)
                if stale_revalidation_skip_reason == "batch_limit":
                    notes.append(
                        f"本輪重查已達批次上限（{adaptive_revalidation_batch_limit}），此項將在後續檢查自動再試。"
                    )
                plan.candidates.append(
                    LocalModUpdateCandidate(
                        project_id=f"__stale__::{stale_identifier or filename_key or unresolved_label}",
                        project_name=unresolved_label or "過期 metadata 模組",
                        filename=filename_key,
                        current_version=str(getattr(local_mod, "version", "") or "").strip(),
                        current_hash=local_hash,
                        hash_algorithm=hash_algorithm,
                        recommendation_source=RECOMMENDATION_SOURCE_STALE_METADATA,
                        recommendation_confidence=confidence,
                        hard_errors=[hard_error],
                        notes=notes,
                        metadata_source=METADATA_SOURCE_STALE_PROVIDER,
                        metadata_note=LOCAL_UPDATE_METADATA_NOTE_STALE_REVALIDATION_FAILED,
                        metadata_resolved=False,
                        local_mod=local_mod,
                    )
                )
                continue
            if unresolved_label:
                unresolved_mod_labels.append(unresolved_label)
            plan.candidates.append(
                LocalModUpdateCandidate(
                    project_id=f"__unresolved__::{filename_key or unresolved_label}",
                    project_name=unresolved_label or "未識別模組",
                    filename=filename_key,
                    current_version=str(getattr(local_mod, "version", "") or "").strip(),
                    current_hash=local_hash,
                    hash_algorithm=hash_algorithm,
                    recommendation_source=RECOMMENDATION_SOURCE_METADATA_UNRESOLVED,
                    recommendation_confidence=RECOMMENDATION_CONFIDENCE_BLOCKED,
                    hard_errors=[LOCAL_UPDATE_ERROR_METADATA_UNRESOLVED],
                    notes=[LOCAL_UPDATE_NOTE_METADATA_UNRESOLVED],
                    metadata_source=METADATA_SOURCE_UNRESOLVED,
                    metadata_note="metadata ensure 失敗：找不到可用的 provider metadata 或雜湊對應結果。",
                    metadata_resolved=False,
                    local_mod=local_mod,
                )
            )
            continue
        if filename_key:
            resolved_project_info_by_filename[filename_key] = resolved_project_info
            metadata_source_by_filename[filename_key] = metadata_source
        apply_provider_metadata(
            local_mod,
            ProviderMetadataRecord.from_values(
                project_id=clean_api_identifier(getattr(resolved_project_info, "project_id", "")),
                slug=str(getattr(resolved_project_info, "slug", "") or "").strip(),
                project_name=str(getattr(resolved_project_info, "name", "") or "").strip(),
            ),
        )
        project_id = clean_api_identifier(getattr(resolved_project_info, "project_id", ""))
        if project_id:
            project_ids.append(project_id)
    project_name_map = resolve_modrinth_project_names(project_ids)
    for local_mod in installed_mods:
        filename_key = str(getattr(local_mod, "filename", "") or "").strip()
        resolved_project_info = resolved_project_info_by_filename.get(filename_key)
        project_id = clean_api_identifier(getattr(resolved_project_info, "project_id", ""))
        if not project_id:
            continue
        project_key = normalize_identifier(project_id)
        project_name = (
            project_name_map.get(project_key, "").strip()
            or str(getattr(resolved_project_info, "name", "") or "").strip()
            or str(getattr(local_mod, "name", "") or project_id).strip()
        )
        current_version = str(getattr(local_mod, "version", "") or "").strip()
        local_metadata_advisories = analyze_local_mod_file_compatibility(local_mod, minecraft_version, loader)
        local_hash = local_hashes_by_filename.get(filename_key, "")
        current_match = current_versions_by_hash.get(local_hash)
        latest_match = latest_versions_by_hash.get(local_hash)
        recommended_version = latest_match.version if latest_match is not None else None
        hash_metadata_resolved = bool(local_hash and (current_match is not None or latest_match is not None))
        used_project_fallback = False
        if recommended_version is None and supports_online_loader_updates and (not hash_metadata_resolved):
            recommended_version = get_recommended_mod_version(project_id, minecraft_version, loader)
            used_project_fallback = recommended_version is not None
        recommendation_source, recommendation_confidence = _resolve_local_update_recommendation_strategy(
            used_project_fallback=used_project_fallback, metadata_resolved=True
        )
        if recommended_version is None:
            if local_metadata_advisories:
                preview = "；".join(local_metadata_advisories[:2])
                suffix = "；其餘提示已省略。" if len(local_metadata_advisories) > 2 else ""
                plan.notes.append(f"{project_name}：{preview}（僅作提示，不影響更新判定）{suffix}")
            continue
        dependency_project_ids = {
            clean_api_identifier(str(dependency.get("project_id", "") or ""))
            for dependency in recommended_version.dependencies
            if isinstance(dependency, dict) and str(dependency.get("project_id", "") or "").strip()
        }
        dependency_names = resolve_modrinth_project_names(dependency_project_ids)
        report = analyze_mod_version_compatibility(
            recommended_version,
            project_id=project_id,
            project_name=project_name,
            minecraft_version=minecraft_version,
            loader=loader,
            loader_version=loader_version,
            installed_mods=installed_mods,
            dependency_names=dependency_names,
        )
        dependency_issues = [
            *list(report.missing_required_dependencies),
            *list(report.installed_version_mismatches),
            *list(report.incompatible_installed),
        ]
        notes = list(report.notes)
        if used_project_fallback:
            notes.append(LOCAL_UPDATE_NOTE_PROJECT_FALLBACK_ADVISORY)
        if local_metadata_advisories:
            notes.extend(f"本地 metadata 提示：{advisory}" for advisory in local_metadata_advisories)
        if report.optional_dependencies:
            notes.append(f"可選依賴：{', '.join(report.optional_dependencies)}")
        metadata_source = metadata_source_by_filename.get(filename_key, "")
        metadata_note = {
            METADATA_SOURCE_HASH: "metadata 來源：使用本地檔案雜湊直接對應到 Modrinth 專案。",
            METADATA_SOURCE_CACHED_PROVIDER: "metadata 來源：使用已快取的 provider metadata / project id。",
            METADATA_SOURCE_LOOKUP: "metadata 來源：使用專案識別查詢補齊。",
        }.get(metadata_source, "")
        primary_file = recommended_version.primary_file or {}
        target_version_name = str(recommended_version.display_name or recommended_version.version_number or "").strip()
        target_filename = str(primary_file.get("filename", "") or "").strip()
        download_url = str(primary_file.get("url", "") or "").strip()
        target_file_hash = extract_primary_file_hash(recommended_version, hash_algorithm)
        if current_match is not None:
            current_version = str(
                current_match.version.display_name or current_match.version.version_number or ""
            ).strip()
        elif used_project_fallback:
            notes.append(LOCAL_UPDATE_NOTE_CURRENT_VERSION_UNVERIFIED)
        if latest_match is None and local_hash and target_file_hash and (local_hash == target_file_hash):
            continue
        candidate = LocalModUpdateCandidate(
            project_id=project_id,
            project_name=project_name,
            filename=str(getattr(local_mod, "filename", "") or "").strip(),
            current_version=current_version,
            target_version_id=str(recommended_version.version_id or "").strip(),
            target_version_name=target_version_name,
            target_version=recommended_version,
            target_filename=target_filename,
            download_url=download_url,
            current_hash=local_hash,
            hash_algorithm=hash_algorithm,
            target_file_hash=target_file_hash,
            recommendation_source=recommendation_source,
            recommendation_confidence=recommendation_confidence,
            current_issues=[],
            dependency_issues=dependency_issues,
            hard_errors=list(report.hard_errors),
            notes=notes,
            metadata_source=metadata_source,
            metadata_note=metadata_note,
            metadata_resolved=True,
            server_side=str(getattr(resolved_project_info, "server_side", "") or "").strip(),
            client_side=str(getattr(resolved_project_info, "client_side", "") or "").strip(),
            report=report,
            local_mod=local_mod,
        )
        if candidate.update_available or candidate.has_issues:
            plan.candidates.append(candidate)
    if unresolved_mod_labels:
        plan.metadata_summary.unresolved = len(unresolved_mod_labels)
        preview = ", ".join(unresolved_mod_labels[:3])
        suffix = " 等" if len(unresolved_mod_labels) > 3 else ""
        plan.notes.append(
            f"有 {len(unresolved_mod_labels)} 個本地模組暫時無法對應到 Modrinth 專案，本次先略過自動更新，後續檢查會自動再試：{preview}{suffix}。"
        )
    else:
        plan.metadata_summary.unresolved = 0
    plan.metadata_summary.notes.append(
        f"metadata ensure 結果：共檢查 {plan.metadata_summary.total_scanned} 個本地模組，其中 {plan.metadata_summary.resolved_by_hash} 個以雜湊直接識別，{plan.metadata_summary.resolved_by_cached_project} 個使用已快取 metadata，{plan.metadata_summary.resolved_by_lookup} 個需額外查詢，{plan.metadata_summary.unresolved} 個仍無法識別。"
    )
    if stale_provider_revalidation_count > 0:
        plan.metadata_summary.notes.append(
            f"其中 {stale_provider_revalidation_count} 個 provider metadata 已超過 freshness TTL，已改為重新識別而非直接沿用舊值。"
        )
    if stale_provider_retryable_count > 0:
        plan.metadata_summary.notes.append(
            f"其中 {stale_provider_retryable_count} 個過期 metadata 重查失敗，已標記為可重試並暫停自動更新。"
        )
    if stale_provider_revalidation_count > 0 and revalidation_adaptive_enabled:
        plan.metadata_summary.notes.append(
            f"stale metadata 重查批次策略：基準 {configured_batch_base_limit}、區間 {configured_batch_min_limit}-{configured_batch_max_limit}，本輪最終上限 {adaptive_revalidation_batch_limit}。"
        )
    if stale_provider_revalidation_attempted_count > 0:
        average_latency_ms = stale_provider_revalidation_total_latency_ms / max(
            1, stale_provider_revalidation_attempted_count
        )
        success_rate = stale_provider_revalidation_success_count / max(1, stale_provider_revalidation_attempted_count)
        plan.metadata_summary.notes.append(
            f"本輪實際執行 {stale_provider_revalidation_attempted_count} 個 stale metadata 重查。"
        )
        plan.metadata_summary.notes.append(
            f"重查觀測摘要：成功率 {success_rate:.0%}、平均延遲 {average_latency_ms:.0f}ms"
            + (
                f"、自適應調整 {stale_provider_revalidation_adaptive_adjustment_count} 次。"
                if revalidation_adaptive_enabled
                else "。"
            )
        )
    if stale_provider_revalidation_backoff_deferred_count > 0:
        plan.metadata_summary.notes.append(
            f"另有 {stale_provider_revalidation_backoff_deferred_count} 個尚在退避視窗內，已延後至到期後自動重查。"
        )
    if stale_provider_revalidation_batch_deferred_count > 0:
        plan.metadata_summary.notes.append(
            f"另有 {stale_provider_revalidation_batch_deferred_count} 個因批次上限（{PROVIDER_REVALIDATION_BATCH_MAX_PER_RUN}）延後至後續檢查自動重查。"
        )
    if not plan.candidates and (not plan.notes):
        plan.notes.append(LOCAL_UPDATE_NOTE_IDENTIFIED_NO_UPDATE)
    plan.finalize_summary()
    return plan


def enhance_local_mod(
    filename: str,
    *,
    platform_id: str | None = None,
    platform_slug: str | None = None,
    local_name: str | None = None,
    resolution_source: str | None = None,
    resolved_at_epoch_ms: Any | None = None,
) -> OnlineModInfo | None:
    """增強本地模組資訊，從線上查詢模組詳細資訊。

    Args:
        filename: 本地模組檔名。
        platform_id: 既有的 platform id。
        platform_slug: 既有的 platform slug。
        local_name: 本地顯示名稱。
        resolution_source: 解析來源標記。
        resolved_at_epoch_ms: 解析時間毫秒值。

    Returns:
        增強後的模組資訊，失敗時回傳 None。
    """
    _ensured, resolved_project_info = _ensure_local_mod_provider_identity(
        filename,
        platform_id=platform_id,
        platform_slug=platform_slug,
        local_name=local_name,
        resolution_source=resolution_source,
        resolved_at_epoch_ms=resolved_at_epoch_ms,
        allow_stale_fallback=True,
    )
    if resolved_project_info is None:
        return None
    return resolved_project_info
