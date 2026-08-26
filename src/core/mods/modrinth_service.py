"""Modrinth 網路查詢與本地 metadata 輔助"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from src.core import (
    MODRINTH_BATCH_HASH_LOOKUP_SIZE,
    MODRINTH_BATCH_PROJECT_LOOKUP_SIZE,
    MODRINTH_PROJECT_BATCH_TIMEOUT_SECONDS,
    MODRINTH_PROJECT_BATCH_URL,
    MODRINTH_PROJECT_DETAIL_TIMEOUT_SECONDS,
    MODRINTH_PROJECT_URL,
    MODRINTH_SEARCH_TIMEOUT_SECONDS,
    MODRINTH_SEARCH_URL,
    MODRINTH_VERSION_DETAIL_TIMEOUT_SECONDS,
    MODRINTH_VERSION_DETAIL_URL_TEMPLATE,
    MODRINTH_VERSION_FILES_TIMEOUT_SECONDS,
    MODRINTH_VERSION_FILES_UPDATE_URL,
    MODRINTH_VERSION_FILES_URL,
    MODRINTH_VERSION_TIMEOUT_SECONDS,
    MODRINTH_VERSION_URL_TEMPLATE,
    SUPPORTED_SORT_OPTIONS,
)
from src.core import (
    mod_search_logger as logger,
)
from src.models import ModrinthVersionLookupResult, OnlineModInfo, OnlineModVersion
from src.utils import (
    MODRINTH_PREFERRED_HASH_ALGORITHM,
    HTTPClient,
    clean_api_identifier,
    get_modrinth_loader_filters,
    is_allowed_version_type,
    is_supported_modrinth_update_loader,
    normalize_hash_algorithm,
    normalize_identifier,
    normalize_mod_search_query,
    parse_modrinth_version,
    parse_modrinth_version_lookup_response,
    select_best_mod_version,
    serialize_json,
)


def _normalize_sort(sort_by: str) -> str:
    if sort_by in SUPPORTED_SORT_OPTIONS:
        return sort_by
    if sort_by == "name":
        return "relevance"
    return "relevance"


def get_modrinth_current_versions_by_hashes(
    hashes: list[str] | set[str] | tuple[str, ...], algorithm: str = MODRINTH_PREFERRED_HASH_ALGORITHM
) -> dict[str, ModrinthVersionLookupResult]:
    """
    依雜湊值取得目前已知的 Modrinth 版本資訊

    Args:
        hashes: 要查詢的檔案雜湊清單
        algorithm: 雜湊演算法名稱

    Returns:
        以雜湊值為 key 的查詢結果字典
    """
    normalized_hashes = [str(file_hash or "").strip().lower() for file_hash in hashes if str(file_hash or "").strip()]
    if not normalized_hashes:
        return {}
    normalized_algorithm = normalize_hash_algorithm(algorithm)

    def _request_chunk(hash_chunk: list[str]) -> dict[str, Any] | None:
        response = HTTPClient.post_json(
            url=MODRINTH_VERSION_FILES_URL,
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
    """將 Modrinth 的雜湊批次查詢邏輯抽成共用函式，避免重複實作"""
    normalized_hashes = [str(file_hash or "").strip().lower() for file_hash in hashes if str(file_hash or "").strip()]
    if not normalized_hashes:
        return {}

    raw_payload: dict[str, Any] = {}
    for i in range(0, len(normalized_hashes), MODRINTH_BATCH_HASH_LOOKUP_SIZE):
        chunk = normalized_hashes[i : i + MODRINTH_BATCH_HASH_LOOKUP_SIZE]
        chunk_result = request_batch_builder(chunk)
        if chunk_result:
            raw_payload.update(chunk_result)

    parsed = parse_modrinth_version_lookup_response(raw_payload, algorithm)
    logger.debug(f"Modrinth batch summary: items={len(normalized_hashes)}, resolved={len(parsed)}")
    return parsed


def get_modrinth_latest_versions_by_hashes(
    hashes: list[str] | set[str] | tuple[str, ...],
    algorithm: str = MODRINTH_PREFERRED_HASH_ALGORITHM,
    minecraft_version: str | None = None,
    loader: str | None = None,
) -> dict[str, ModrinthVersionLookupResult]:
    """
    依雜湊值取得最新的 Modrinth 版本資訊

    Args:
        hashes: 要查詢的檔案雜湊清單
        algorithm: 雜湊演算法名稱
        minecraft_version: 目標 Minecraft 版本
        loader: 目標載入器類型

    Returns:
        以雜湊值為 key 的查詢結果字典
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
        response = HTTPClient.post_json(
            url=MODRINTH_VERSION_FILES_UPDATE_URL,
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


def get_modrinth_project_info(project_id: str) -> OnlineModInfo | None:
    """
    依 project id 或 slug 取得單一 Modrinth 專案資訊

    Args:
        project_id: Modrinth project id 或 slug

    Returns:
        專案資訊，找不到時回傳 None
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
        homepage_url=homepage_url or url,
        url=url,
        categories=[*categories, *[category for category in additional_categories if category not in categories]],
        versions=[str(version) for version in response.get("versions", []) if version],
        server_side=str(response.get("server_side", "") or "").strip(),
        client_side=str(response.get("client_side", "") or "").strip(),
    )


def _fetch_modrinth_project_detail(project_id: str) -> dict[str, Any] | None:
    """取得一般瀏覽顯示所需的完整 project payload；不處理 identity lifecycle"""
    identifier = clean_api_identifier(project_id)
    if not identifier:
        return None
    response = HTTPClient.fetch_json(
        url=f"https://api.modrinth.com/v2/project/{quote(identifier, safe='')}",
        timeout=MODRINTH_PROJECT_DETAIL_TIMEOUT_SECONDS,
        suppress_status_codes={404},
    )
    return response if isinstance(response, dict) else None


def fetch_modrinth_project_name(project_id: str) -> str | None:
    """
    依 project id 或 slug 取得 Modrinth 專案名稱

    Args:
        project_id: Modrinth project id 或 slug

    Returns:
        專案名稱，找不到時回傳 None
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
    """
    依 Modrinth version id 取得精確版本資訊，並回傳其所屬 project id

    Args:
        version_id: Modrinth version id

    Returns:
        (project_id, version_info)的查詢結果
    """
    clean_version_id = clean_api_identifier(version_id)
    if not clean_version_id:
        return ("", None)
    response = HTTPClient.fetch_json(
        url=MODRINTH_VERSION_DETAIL_URL_TEMPLATE.format(version_id=clean_version_id),
        timeout=MODRINTH_VERSION_DETAIL_TIMEOUT_SECONDS,
    )
    if not isinstance(response, dict):
        logger.error(f"取得 Modrinth 版本詳細資訊失敗: {clean_version_id}")
        return ("", None)
    project_id = clean_api_identifier(str(response.get("project_id", "") or ""))
    return (project_id, parse_modrinth_version(response))


def resolve_modrinth_project_names(project_ids: list[str] | set[str] | tuple[str, ...]) -> dict[str, str]:
    """
    將 Modrinth project id 轉為較易讀的專案名稱

    Args:
        project_ids: 要解析的 project id 清單

    Returns:
        以 project id 為 key 的名稱對應表
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
        response = HTTPClient.fetch_json(
            url=MODRINTH_PROJECT_BATCH_URL,
            params={"ids": serialize_json(id_chunk)},
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

    raw_payload: dict[str, Any] = {}
    for i in range(0, len(raw_ids), MODRINTH_BATCH_PROJECT_LOOKUP_SIZE):
        chunk = raw_ids[i : i + MODRINTH_BATCH_PROJECT_LOOKUP_SIZE]
        chunk_result = _request_chunk(chunk)
        if chunk_result:
            raw_payload.update(chunk_result)

    names: dict[str, str] = {}
    for project_id, item in raw_payload.items():
        if not isinstance(item, dict):
            continue
        project_key = normalize_identifier(project_id)
        if not project_key:
            continue
        name = str(item.get("title", "") or item.get("name", "") or item.get("slug", "") or project_id).strip()
        names[project_key] = name or project_id
    logger.debug(f"Modrinth projects batch summary: items={len(raw_ids)}, resolved={len(names)}")
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
    """
    透過 Modrinth API 搜尋或瀏覽模組

    Args:
        query: 搜尋關鍵字
        minecraft_version: 目標 Minecraft 版本
        loader: 目標載入器類型
        categories: 額外分類條件
        sort_by: 排序方式
        limit: 最多回傳數量

    Returns:
        搜尋到的模組清單
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
        "facets": serialize_json(facets),
        "index": _normalize_sort(sort_by),
    }
    if normalized_query:
        params["query"] = normalized_query
    response = HTTPClient.fetch_json(
        url=MODRINTH_SEARCH_URL,
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
    """
    取得指定 Modrinth 模組的穩定版本

    Args:
        project_id: Modrinth project id
        minecraft_version: 目標 Minecraft 版本
        loader: 目標載入器類型

    Returns:
        符合條件的版本清單
    """
    clean_project_id = clean_api_identifier(project_id)
    if not clean_project_id:
        return []
    url = MODRINTH_VERSION_URL_TEMPLATE.format(project_id=clean_project_id)
    response = HTTPClient.fetch_json(url=url, timeout=MODRINTH_VERSION_TIMEOUT_SECONDS)
    if not isinstance(response, list):
        logger.error(f"取得 Modrinth 版本列表失敗: {clean_project_id}")
        return []
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
    """
    取得最適合目前條件的推薦版本，若條件下查無版本則回退到未過濾結果

    Args:
        project_id: Modrinth project id
        minecraft_version: 目標 Minecraft 版本
        loader: 目標載入器類型

    Returns:
        最佳推薦版本，若查無版本則回傳 None
    """
    clean_project_id = clean_api_identifier(project_id)
    if not clean_project_id:
        return None
    versions = get_mod_versions(clean_project_id, minecraft_version, loader)
    if not versions:
        if not is_supported_modrinth_update_loader(loader):
            return None
        versions = get_mod_versions(clean_project_id)
    return select_best_mod_version(versions)


__all__ = [
    "fetch_modrinth_project_name",
    "get_mod_version_details",
    "get_mod_versions",
    "get_modrinth_current_versions_by_hashes",
    "get_modrinth_latest_versions_by_hashes",
    "get_modrinth_project_info",
    "get_recommended_mod_version",
    "resolve_modrinth_project_names",
    "search_mods_online",
]
