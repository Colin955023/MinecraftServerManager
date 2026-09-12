"""Modrinth 網路查詢與本地 metadata 輔助"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from itertools import batched
from operator import attrgetter
from typing import Any
from urllib.parse import quote

from src.models import ModrinthVersionLookupResult, OnlineModInfo, OnlineModVersion, ProviderCatalogOutcome
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
    select_best_mod_version,
    serialize_json,
)

from .mod_search_constants import (
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
    logger,
)
from .modrinth_parsing import parse_modrinth_version, parse_modrinth_version_lookup_response


def _normalize_sort(sort_by: str) -> str:
    if sort_by in SUPPORTED_SORT_OPTIONS:
        return sort_by
    if sort_by == "name":
        return "relevance"
    return "relevance"


def _resolve_current_versions_by_hashes(
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
    normalized_hashes = [normalized.lower() for file_hash in hashes if (normalized := str(file_hash or "").strip())]
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
        normalized_hashes=normalized_hashes, algorithm=algorithm, request_batch_builder=_request_chunk
    )


def _modrinth_versions_by_hashes(
    normalized_hashes: list[str],
    algorithm: str,
    request_batch_builder: Callable[[list[str]], dict[str, Any] | None],
) -> dict[str, ModrinthVersionLookupResult]:
    """執行已正規化雜湊值的 Modrinth 批次查詢"""
    raw_payload: dict[str, Any] = {}
    for batch in batched(normalized_hashes, MODRINTH_BATCH_HASH_LOOKUP_SIZE, strict=False):
        chunk = list(batch)
        chunk_result = request_batch_builder(chunk)
        if chunk_result:
            raw_payload.update(chunk_result)

    parsed = parse_modrinth_version_lookup_response(raw_payload, algorithm)
    logger.debug(f"Modrinth batch summary: items={len(normalized_hashes)}, resolved={len(parsed)}")
    return parsed


def _resolve_latest_versions_by_hashes(
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
    normalized_hashes = [normalized.lower() for file_hash in hashes if (normalized := str(file_hash or "").strip())]
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
        normalized_hashes=normalized_hashes,
        algorithm=algorithm,
        request_batch_builder=_request_chunk,
    )


def _get_project_info(project_id: str) -> OnlineModInfo | None:
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


def _fetch_project_name(project_id: str) -> str | None:
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


def _get_version_details(version_id: str) -> tuple[str, OnlineModVersion | None]:
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


def _resolve_project_names(project_ids: list[str] | set[str] | tuple[str, ...]) -> dict[str, str]:
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
    for batch in batched(raw_ids, MODRINTH_BATCH_PROJECT_LOOKUP_SIZE, strict=False):
        chunk = list(batch)
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
        resolved_name = _fetch_project_name(raw_project_id)
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


def _search_mods(
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
        mods.sort(key=attrgetter("download_count"), reverse=True)
    elif sort_by == "name":
        mods.sort(key=lambda item: item.name.lower())
    return mods


def _get_versions(
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
    loader_filters = set(get_modrinth_loader_filters(loader))
    params: dict[str, str] = {}
    if minecraft_version:
        params["game_versions"] = serialize_json([minecraft_version])
    if loader_filters:
        params["loaders"] = serialize_json(sorted(loader_filters))
    response = HTTPClient.fetch_json(url=url, timeout=MODRINTH_VERSION_TIMEOUT_SECONDS, params=params or None)
    if not isinstance(response, list):
        logger.error(f"取得 Modrinth 版本列表失敗: {clean_project_id}")
        return []
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


def _get_recommended_version(
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
    versions = _get_versions(clean_project_id, minecraft_version, loader)
    if not versions:
        if not is_supported_modrinth_update_loader(loader):
            return None
        versions = _get_versions(clean_project_id)
    return select_best_mod_version(versions)


class ModrinthHttpAdapter:
    """集中擁有 Modrinth transport、fallback 與 response mapping"""

    def find_projects(
        self,
        query: str | Iterable[str],
        **options: Any,
    ) -> Any:
        """
        依查詢內容取得 Modrinth 專案

        Args:
            query: 查詢文字或專案識別碼集合
            options: 查詢模式、版本、載入器、分類、排序與數量選項

        Returns:
            專案查詢投影
        """
        exact = bool(options.get("exact", False))
        search = bool(options.get("search", False))
        include_details = bool(options.get("include_details", False))
        minecraft_version = options.get("minecraft_version")
        loader = options.get("loader")
        categories = options.get("categories")
        sort_by = str(options.get("sort_by", "relevance"))
        limit = int(options.get("limit", 20))
        if isinstance(query, str):
            if search:
                return _search_mods(
                    query,
                    minecraft_version=minecraft_version,
                    loader=loader,
                    categories=categories,
                    sort_by=sort_by,
                    limit=limit,
                )
            if include_details:
                return _get_project_info(query)
            if exact:
                return self._catalog_lookup(query)
            return self._catalog_search(query)
        return _resolve_project_names(tuple(query))

    def resolve_versions(
        self,
        project_id: str = "",
        minecraft_version: str | None = None,
        loader: str | None = None,
        *,
        version_id: str | None = None,
        recommended: bool = False,
    ) -> Any:
        """
        取得 Modrinth 版本、版本明細或推薦版本

        Args:
            project_id: 專案識別碼
            minecraft_version: 目標 Minecraft 版本
            loader: 目標載入器
            version_id: 指定版本識別碼
            recommended: 是否只取推薦版本

        Returns:
            版本查詢結果
        """
        if version_id is not None:
            return _get_version_details(version_id)
        if recommended:
            return _get_recommended_version(project_id, minecraft_version, loader)
        return _get_versions(project_id, minecraft_version, loader)

    def resolve_files(
        self,
        hashes: Iterable[str],
        algorithm: str,
        *,
        latest: bool = False,
        minecraft_version: str | None = None,
        loader: str | None = None,
    ) -> dict[str, ModrinthVersionLookupResult]:
        """
        依雜湊取得目前或目標 Modrinth 版本檔案

        Args:
            hashes: 待查詢檔案雜湊
            algorithm: 雜湊演算法名稱
            latest: 是否查詢符合條件的最新版本
            minecraft_version: 目標 Minecraft 版本
            loader: 目標載入器

        Returns:
            以雜湊索引的版本查詢結果
        """
        normalized_hashes = list(hashes)
        if latest:
            return _resolve_latest_versions_by_hashes(normalized_hashes, algorithm, minecraft_version, loader)
        return _resolve_current_versions_by_hashes(normalized_hashes, algorithm)

    def _catalog_lookup(self, identifier: str) -> ProviderCatalogOutcome:
        clean_identifier = str(identifier or "").strip()
        if not clean_identifier:
            return ProviderCatalogOutcome("invalid_response")
        response = HTTPClient.fetch_json_response(
            f"https://api.modrinth.com/v2/project/{quote(clean_identifier, safe='')}",
            timeout=MODRINTH_PROJECT_DETAIL_TIMEOUT_SECONDS,
        )
        mapped_error = self._map_catalog_error(response.error_kind)
        if mapped_error is not None:
            return ProviderCatalogOutcome(mapped_error)
        payload = response.payload
        if not isinstance(payload, dict):
            return ProviderCatalogOutcome("invalid_response")
        return self._map_catalog_project(payload, confidence=100)

    def _catalog_search(self, query: str) -> ProviderCatalogOutcome:
        clean_query = str(query or "").strip()
        if not clean_query:
            return ProviderCatalogOutcome("invalid_response")
        response = HTTPClient.fetch_json_response(
            MODRINTH_SEARCH_URL,
            timeout=MODRINTH_SEARCH_TIMEOUT_SECONDS,
            params={"query": clean_query, "limit": 8, "facets": '[["project_type:mod"]]'},
        )
        mapped_error = self._map_catalog_error(response.error_kind)
        if mapped_error is not None:
            return ProviderCatalogOutcome(mapped_error)
        payload = response.payload
        if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
            return ProviderCatalogOutcome("not_found")
        normalized_query = self._catalog_key(clean_query)
        best: tuple[int, dict[str, Any]] | None = None
        for hit in payload["hits"]:
            if not isinstance(hit, dict):
                continue
            keys = {
                self._catalog_key(hit.get("project_id")),
                self._catalog_key(hit.get("slug")),
                self._catalog_key(hit.get("title") or hit.get("name")),
            }
            keys.discard("")
            score = (
                100
                if normalized_query in keys
                else 70
                if any(normalized_query and (normalized_query in key or key in normalized_query) for key in keys)
                else 10
            )
            if best is None or score > best[0]:
                best = (score, hit)
        if best is None:
            return ProviderCatalogOutcome("invalid_response")
        return self._map_catalog_project(best[1], confidence=best[0])

    @staticmethod
    def _map_catalog_error(error_kind: str | None) -> str | None:
        if error_kind == "not_found":
            return "not_found"
        if error_kind == "rate_limited":
            return "rate_limited"
        if error_kind in {"timeout", "transient"}:
            return "transient_failure"
        if error_kind:
            return "invalid_response"
        return None

    @classmethod
    def _map_catalog_project(cls, payload: dict[str, Any], *, confidence: int) -> ProviderCatalogOutcome:
        project_id = str(payload.get("id", payload.get("project_id", "")) or "").strip()
        if not project_id:
            return ProviderCatalogOutcome("invalid_response")
        return ProviderCatalogOutcome(
            "found",
            provider="modrinth",
            project_id=project_id,
            alias=str(payload.get("slug", "") or "").strip(),
            display_name=str(payload.get("title", payload.get("name", "")) or "").strip(),
            confidence=confidence,
        )

    @staticmethod
    def _catalog_key(value: Any) -> str:
        return "".join(char for char in str(value or "").strip().lower() if char.isalnum())


__all__ = ["ModrinthHttpAdapter"]
