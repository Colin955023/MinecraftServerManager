"""Modrinth 網路查詢與本地 metadata 輔助。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models import ModrinthVersionLookupResult, OnlineModVersion
from ...utils import (
    MODRINTH_PREFERRED_HASH_ALGORITHM,
    PROVIDER_LIFECYCLE_STALE,
    HTTPUtils,
    LocalProviderEnsureResult,
    PathUtils,
    ProviderMetadataRecord,
    build_local_mod_lookup_candidates,
    canonical_lookup_key,
    clean_api_identifier,
    ensure_local_mod_provider_record,
    execute_resilient_batch_requests,
    execute_resilient_single_request,
    extract_primary_file_hash,
    fetch_modrinth_project_detail,
    get_modrinth_loader_filters,
    is_allowed_version_type,
    is_cached_provider_metadata_fresh,
    is_supported_modrinth_update_loader,
    normalize_hash_algorithm,
    normalize_identifier,
    normalize_mod_search_query,
    parse_modrinth_version,
    parse_modrinth_version_lookup_response,
    resolve_modrinth_provider_record,
    select_best_mod_version,
)
from .constants import (
    MIN_ACCEPTABLE_LOCAL_MOD_SEARCH_SCORE,
    MODRINTH_BATCH_HASH_LOOKUP_SIZE,
    MODRINTH_BATCH_PROJECT_LOOKUP_SIZE,
    MODRINTH_BATCH_RETRY_ATTEMPTS,
    MODRINTH_PROJECT_BATCH_TIMEOUT_SECONDS,
    MODRINTH_PROJECT_BATCH_URL,
    MODRINTH_PROJECT_DETAIL_TIMEOUT_SECONDS,
    MODRINTH_PROJECT_URL,
    MODRINTH_REQUEST_THROTTLE_SECONDS,
    MODRINTH_RETRY_BACKOFF_BASE_SECONDS,
    MODRINTH_RETRY_BACKOFF_MAX_SECONDS,
    MODRINTH_SEARCH_TIMEOUT_SECONDS,
    MODRINTH_SEARCH_URL,
    MODRINTH_SINGLE_REQUEST_RETRY_ATTEMPTS,
    MODRINTH_VERSION_DETAIL_TIMEOUT_SECONDS,
    MODRINTH_VERSION_DETAIL_URL_TEMPLATE,
    MODRINTH_VERSION_FILES_TIMEOUT_SECONDS,
    MODRINTH_VERSION_FILES_UPDATE_URL,
    MODRINTH_VERSION_FILES_URL,
    MODRINTH_VERSION_TIMEOUT_SECONDS,
    MODRINTH_VERSION_URL_TEMPLATE,
    SUPPORTED_SORT_OPTIONS,
    logger,
)
from .models import OnlineModInfo


@dataclass(slots=True)
class ModrinthDownloadContract:
    """描述 Modrinth 版本可下載檔案的核心欄位。"""

    provider: str
    project_id: str
    version_id: str
    download_url: str
    filename: str
    expected_hash: str = ""


def _normalize_sort(sort_by: str) -> str:
    if sort_by in SUPPORTED_SORT_OPTIONS:
        return sort_by
    if sort_by == "name":
        return "relevance"
    return "relevance"


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
    loader_filters = get_modrinth_loader_filters(loader)
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


def build_provider_record_from_online_mod(mod_info: OnlineModInfo | None) -> ProviderMetadataRecord | None:
    """將線上模組資訊轉成可快取的 provider metadata 紀錄。

    Args:
        mod_info: 線上模組資訊。

    Returns:
        可寫入快取的 provider metadata；若資訊不足則回傳 None。
    """

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


def normalize_cached_provider_identity(
    *,
    platform_id: str | None = None,
    platform_slug: str | None = None,
    resolution_source: str | None = None,
    resolved_at_epoch_ms: Any | None = None,
) -> tuple[str, str, bool]:
    """清理快取中的 provider identity，並回報是否需要重新驗證。

    Args:
        platform_id: 快取中的 provider project id。
        platform_slug: 快取中的 provider slug。
        resolution_source: 原始解析來源。
        resolved_at_epoch_ms: 原始解析時間戳。

    Returns:
        清理後的 project id、slug，以及是否需要重新驗證的旗標。
    """

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
    fresh_platform_id, fresh_platform_slug, cached_provider_is_stale = normalize_cached_provider_identity(
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
            resolved_record = build_provider_record_from_online_mod(exact_match)
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
            return build_provider_record_from_online_mod(exact_match)
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
        return build_provider_record_from_online_mod(best_match)

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


def fetch_modrinth_project_name(project_id: str) -> str | None:
    """
    依 project id 或 slug 取得 Modrinth 專案名稱。

    Args:
        project_id: Modrinth project id 或 slug。
    Returns:
        專案名稱，找不到時回傳 None。
    """
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
        resolved_name = fetch_modrinth_project_name(raw_project_id)
        if resolved_name:
            names[project_key] = resolved_name
        else:
            logger.debug(f"無法解析 Modrinth 專案名稱，保留 project id: {raw_project_id}")
    return names


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
        facets.append([f"versions:{minecraft_version}"])
    loader_categories = get_modrinth_loader_filters(loader)
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
    loader_filters = set(get_modrinth_loader_filters(loader))
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


def get_modrinth_download_contract(
    *,
    project_id: str,
    version: OnlineModVersion,
) -> ModrinthDownloadContract | None:
    """
    建立下載指定 Modrinth 版本所需的最小契約資料。

    Args:
        project_id: 所屬專案的 project id。
        version: 目標版本資訊。

    Returns:
        可供下載流程使用的契約資料；欄位不足時回傳 None。
    """
    primary_file = getattr(version, "primary_file", None)
    if not primary_file:
        return None
    download_url = str(primary_file.get("url", "") or "").strip()
    filename = str(primary_file.get("filename", "") or "").strip()
    if not download_url or not filename:
        return None
    return ModrinthDownloadContract(
        provider="modrinth",
        project_id=str(project_id or "").strip(),
        version_id=str(getattr(version, "version_id", "") or "").strip(),
        download_url=download_url,
        filename=filename,
        expected_hash=(extract_primary_file_hash(version) or extract_primary_file_hash(version, "sha256")),
    )


__all__ = [
    "ModrinthDownloadContract",
    "OnlineModInfo",
    "enhance_local_mod",
    "get_mod_version_details",
    "get_mod_versions",
    "get_modrinth_current_versions_by_hashes",
    "get_modrinth_download_contract",
    "get_modrinth_latest_versions_by_hashes",
    "get_modrinth_project_info",
    "get_recommended_mod_version",
    "resolve_local_mod_project_info",
    "resolve_modrinth_project_names",
    "search_mods_online",
]
