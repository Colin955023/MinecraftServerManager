"""Modrinth 查詢與載入器規則工具。"""

from __future__ import annotations

import re

SUPPORTED_MODRINTH_UPDATE_LOADERS: set[str] = {"fabric", "forge", "quilt", "neoforge"}
MODRINTH_QUERY_EXPORT_NAMES: tuple[str, ...] = (
    "SUPPORTED_MODRINTH_UPDATE_LOADERS",
    "apply_loader_specific_dependency_override",
    "build_local_mod_lookup_candidates",
    "canonical_lookup_key",
    "clean_api_identifier",
    "get_modrinth_loader_filters",
    "is_supported_modrinth_update_loader",
    "normalize_identifier",
    "normalize_local_loader",
    "normalize_mod_search_query",
)


def normalize_identifier(value: str | None) -> str:
    """將字串正規化為可比較的識別字。

    Args:
        value: 原始識別字或空值。

    Returns:
        去除前後空白並轉為小寫的字串。
    """

    return str(value or "").strip().lower()


def clean_api_identifier(value: str | None) -> str:
    """清理 API 回傳的識別字。

    Args:
        value: 原始 API 識別字或空值。

    Returns:
        去除前後空白後的字串。
    """

    return str(value or "").strip()


def normalize_local_loader(loader: str | None) -> str:
    """將本地載入器名稱正規化為內部比較格式。

    Args:
        loader: 原始載入器名稱。

    Returns:
        正規化後的載入器名稱。
    """

    normalized_loader = normalize_identifier(loader)
    if normalized_loader in {"fabric", "forge", "quilt", "neoforge"}:
        return normalized_loader
    if normalized_loader in {"vanilla", "原版"}:
        return "vanilla"
    return normalized_loader


def is_supported_modrinth_update_loader(loader: str | None) -> bool:
    """判斷目前載入器是否支援 Modrinth 更新規劃。

    Args:
        loader: 原始載入器名稱。

    Returns:
        若支援則回傳 True，否則回傳 False。
    """

    normalized_loader = normalize_local_loader(loader)
    if not normalized_loader:
        return True
    return normalized_loader in SUPPORTED_MODRINTH_UPDATE_LOADERS


def get_modrinth_loader_filters(loader: str | None) -> list[str]:
    """回傳 Modrinth 查詢用 loader 過濾列表。

    Args:
        loader: 原始載入器名稱。

    Returns:
        載入器清單，不再進行別名擴展。
    """

    normalized_loader = normalize_identifier(loader)
    if not normalized_loader:
        return []
    return [normalized_loader]


def apply_loader_specific_dependency_override(project_id: str | None) -> str:
    """回傳原始 project id，不再進行載入器特定的轉換。

    Args:
        project_id: 原始 project id。

    Returns:
        原始 project id。
    """

    return clean_api_identifier(project_id)


def _split_camel_case_words(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return re.sub("(?<=[A-Z])(?=[A-Z][a-z])", " ", re.sub("(?<=[a-z0-9])(?=[A-Z])", " ", normalized))


def normalize_mod_search_query(raw_query: str) -> str:
    """將檔名或雜訊字串轉為較適合 Modrinth 搜尋的關鍵字。

    Args:
        raw_query: 原始檔名或搜尋字串。

    Returns:
        已移除常見載入器與版本雜訊的搜尋關鍵字。
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


def canonical_lookup_key(value: str | None) -> str:
    """產生用於比對與去重的標準化 key。

    Args:
        value: 原始字串。

    Returns:
        只保留小寫英數字的 key。
    """

    return re.sub("[^a-z0-9]+", "", str(value or "").strip().lower())


def build_local_mod_lookup_candidates(
    filename: str, *, platform_id: str | None = None, platform_slug: str | None = None, local_name: str | None = None
) -> tuple[list[str], list[str], set[str]]:
    """從本地模組資訊組合搜尋與比對候選字串。

    Args:
        filename: 模組檔名。
        platform_id: 已知的 platform id。
        platform_slug: 已知的 platform slug。
        local_name: 本地顯示名稱。

    Returns:
        (精確候選, 搜尋字串, 標準化比對 key) 三元組。
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


__all__ = [
    *MODRINTH_QUERY_EXPORT_NAMES,
]
