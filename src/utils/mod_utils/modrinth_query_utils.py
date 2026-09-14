"""Modrinth 查詢與載入器規則工具"""

from __future__ import annotations

import re

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
    return " ".join(normalized.split()) or str(raw_query or "").strip()


__all__ = [
    "SUPPORTED_MODRINTH_UPDATE_LOADERS",
    "clean_api_identifier",
    "get_modrinth_loader_filters",
    "is_supported_modrinth_update_loader",
    "normalize_identifier",
    "normalize_local_loader",
    "normalize_mod_search_query",
]
