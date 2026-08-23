"""Modrinth 查詢與載入器規則工具"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.models import ModrinthVersionLookupResult, OnlineModVersion

SUPPORTED_MODRINTH_UPDATE_LOADERS: set[str] = {"fabric", "forge", "quilt", "neoforge"}


def normalize_identifier(value: str | None) -> str:
    """
    將字串正規化為可比較的識別字

    Args:
        value: 原始識別字或空值

    Returns:
        去除前後空白並轉為小寫的字串
    """
    return str(value or "").strip().lower()


def clean_api_identifier(value: str | None) -> str:
    """
    清理 API 回傳的識別字

    Args:
        value: 原始 API 識別字或空值

    Returns:
        去除前後空白後的字串
    """
    return str(value or "").strip()


def canonical_lookup_key(value: str | None) -> str:
    """
    產生用於比對與去重的標準化 key

    Args:
        value: 原始字串

    Returns:
        只保留小寫英數字的 key
    """
    return re.sub("[^a-z0-9]+", "", str(value or "").strip().lower())


def normalize_local_loader(loader: str | None) -> str:
    """
    將本地載入器名稱正規化為內部比較格式

    Args:
        loader: 原始載入器名稱

    Returns:
        正規化後的載入器名稱
    """
    normalized_loader = normalize_identifier(loader)
    if normalized_loader in {"fabric", "forge", "quilt", "neoforge"}:
        return normalized_loader
    if normalized_loader in {"vanilla", "原版"}:
        return "vanilla"
    return normalized_loader


def is_supported_modrinth_update_loader(loader: str | None) -> bool:
    """
    判斷目前載入器是否支援 Modrinth 更新規劃

    Args:
        loader: 原始載入器名稱

    Returns:
        若支援則回傳 True，否則回傳 False
    """
    normalized_loader = normalize_local_loader(loader)
    if not normalized_loader:
        return True
    return normalized_loader in SUPPORTED_MODRINTH_UPDATE_LOADERS


def get_modrinth_loader_filters(loader: str | None) -> list[str]:
    """
    回傳 Modrinth 查詢用 loader 過濾列表

    Args:
        loader: 原始載入器名稱

    Returns:
        載入器清單
    """
    normalized_loader = normalize_identifier(loader)
    if not normalized_loader:
        return []
    return [normalized_loader]


def apply_loader_specific_dependency_override(project_id: str | None) -> str:
    """
    回傳原始 project id，不再進行載入器特定的轉換

    Args:
        project_id: 原始 project id

    Returns:
        原始 project id
    """
    return clean_api_identifier(project_id)


def _split_camel_case_words(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return re.sub("(?<=[A-Z])(?=[A-Z][a-z])", " ", re.sub("(?<=[a-z0-9])(?=[A-Z])", " ", normalized))


def normalize_mod_search_query(raw_query: str) -> str:
    """
    將檔名或雜訊字串轉為較適合 Modrinth 搜尋的關鍵字

    Args:
        raw_query: 原始檔名或搜尋字串

    Returns:
        已移除常見載入器與版本雜訊的搜尋關鍵字
    """
    normalized = _split_camel_case_words(raw_query)
    if not normalized:
        return ""
    normalized = normalized.removesuffix(".jar.disabled").removesuffix(".jar")
    normalized = normalized.replace("_", " ").replace("-", " ")
    normalized = re.sub("(?i)\\b(?:fabric|forge|loader)\\b", " ", normalized)
    normalized = re.sub("(?i)\\bmc\\s*\\d+(?:\\.\\d+){1,2}[a-z0-9.-]*\\b", " ", normalized)
    normalized = re.sub("\\b\\d+(?:\\.\\d+){1,3}[a-z0-9.-]*\\b", " ", normalized)
    return re.sub("\\s+", " ", normalized).strip() or str(raw_query or "").strip()


def build_local_mod_lookup_candidates(
    filename: str, *, platform_id: str | None = None, platform_slug: str | None = None, local_name: str | None = None
) -> tuple[list[str], list[str], set[str]]:
    """
    從本地模組資訊組合搜尋與比對候選字串

    Args:
        filename: 模組檔名
        platform_id: 已知的 platform id
        platform_slug: 已知的 platform slug
        local_name: 本地顯示名稱

    Returns:
        (精確候選, 搜尋字串, 標準化比對 key) 三元組
    """
    filename_stem = filename.replace(".jar.disabled", "").replace(".jar", "")
    raw_candidates = [
        str(platform_id or "").strip(),
        str(platform_slug or "").strip(),
        str(local_name or "").strip(),
        filename_stem.strip(),
    ]
    exact_identifiers: list[str] = []
    search_terms: list[str] = []
    candidate_keys: set[str] = set()
    for raw_candidate in raw_candidates:
        if not raw_candidate:
            continue
        clean_candidate = clean_api_identifier(raw_candidate)
        if clean_candidate and clean_candidate not in exact_identifiers:
            exact_identifiers.append(clean_candidate)
        normalized_search = normalize_mod_search_query(raw_candidate)
        if normalized_search and normalized_search not in search_terms:
            search_terms.append(normalized_search)
        slug_candidate = re.sub("[^a-z0-9]+", "-", normalized_search.lower()).strip("-") if normalized_search else ""
        if slug_candidate and slug_candidate not in exact_identifiers:
            exact_identifiers.append(slug_candidate)
        for candidate_value in (raw_candidate, normalized_search, slug_candidate):
            candidate_key = canonical_lookup_key(candidate_value)
            if candidate_key:
                candidate_keys.add(candidate_key)
    return (exact_identifiers, search_terms, candidate_keys)


def parse_modrinth_version(item: dict[str, Any]) -> OnlineModVersion:
    """
    將 Modrinth 版本 API payload 轉換為內部版本模型

    Args:
        item: Modrinth 版本 API 回應，包含版本號、loader、檔案與 dependency 欄位

    Returns:
        填入 provider、版本資訊、檔案與 dependency 的 OnlineModVersion
    """
    from src.models import OnlineModVersion

    game_versions = [str(v) for v in item.get("game_versions", []) if v]
    loaders = [str(v) for v in item.get("loaders", []) if v]
    version_number = str(item.get("version_number", "") or "")
    display_name = version_number or str(item.get("name", "未知版本") or "未知版本")
    return OnlineModVersion(
        version_id=str(item.get("id", "") or ""),
        version_number=version_number,
        display_name=display_name,
        game_versions=game_versions,
        loaders=loaders,
        version_type=str(item.get("version_type", "") or ""),
        date_published=str(item.get("date_published", "") or ""),
        changelog=str(item.get("changelog", "") or item.get("body", "") or ""),
        provider="modrinth",
        files=list(item.get("files", []) or []),
        dependencies=list(item.get("dependencies", []) or []),
    )


def parse_modrinth_version_lookup_response(
    response: dict[str, Any] | None, algorithm: str
) -> dict[str, ModrinthVersionLookupResult]:
    """
    將 Modrinth 以雜湊查詢的回應轉成 lookup result 對照表

    Args:
        response: Modrinth 雜湊查詢 API 回應；None 表示查詢沒有結果
        algorithm: 查詢使用的雜湊演算法名稱，例如 sha1 或 sha512

    Returns:
        以雜湊值為 key、ModrinthVersionLookupResult 為 value 的字典
    """
    from src.models import ModrinthVersionLookupResult
    from src.utils import normalize_hash_algorithm

    normalized_algorithm = normalize_hash_algorithm(algorithm)
    if not isinstance(response, dict):
        return {}
    resolved: dict[str, ModrinthVersionLookupResult] = {}
    for file_hash, raw_item in response.items():
        normalized_hash = str(file_hash or "").strip().lower()
        if not normalized_hash or not isinstance(raw_item, dict):
            continue
        project_id = clean_api_identifier(str(raw_item.get("project_id", "") or ""))
        version = parse_modrinth_version(raw_item)
        resolved[normalized_hash] = ModrinthVersionLookupResult(
            file_hash=normalized_hash, algorithm=normalized_algorithm, project_id=project_id, version=version
        )
    return resolved


__all__ = [
    "apply_loader_specific_dependency_override",
    "build_local_mod_lookup_candidates",
    "canonical_lookup_key",
    "clean_api_identifier",
    "get_modrinth_loader_filters",
    "is_supported_modrinth_update_loader",
    "normalize_identifier",
    "normalize_local_loader",
    "normalize_mod_search_query",
    "parse_modrinth_version",
    "parse_modrinth_version_lookup_response",
]
