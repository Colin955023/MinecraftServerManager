"""Modrinth 版本篩選與檔案選擇工具。"""

from __future__ import annotations

from typing import Any

from .. import normalize_identifier

MODRINTH_PREFERRED_HASH_ALGORITHM = "sha512"


def normalize_hash_algorithm(algorithm: str | None) -> str:
    """正規化 Modrinth 使用的雜湊演算法名稱。

    Args:
        algorithm: 原始演算法名稱。

    Returns:
        可用於查詢的標準化演算法名稱。
    """

    normalized = normalize_identifier(algorithm)
    if normalized in {"sha512", "sha1", "sha256"}:
        return normalized
    return MODRINTH_PREFERRED_HASH_ALGORITHM


def select_primary_file(files: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """從版本檔案列表中選出最適合下載的檔案。

    Args:
        files: 版本檔案列表。

    Returns:
        選中的檔案資訊，找不到時回傳 None。
    """

    if not files:
        return None
    for file_info in files:
        if not isinstance(file_info, dict):
            continue
        if file_info.get("primary"):
            return file_info
    for file_info in files:
        if not isinstance(file_info, dict):
            continue
        filename = str(file_info.get("filename", "") or "")
        if filename.lower().endswith(".jar"):
            return file_info
    for file_info in files:
        if isinstance(file_info, dict):
            return file_info
    return None


def extract_primary_file_hash(version: Any | None, algorithm: str = MODRINTH_PREFERRED_HASH_ALGORITHM) -> str:
    """擷取版本主要檔案的雜湊值。

    Args:
        version: 版本物件或空值。
        algorithm: 雜湊演算法名稱。

    Returns:
        主要檔案雜湊值，找不到時回傳空字串。
    """

    primary_file = getattr(version, "primary_file", None) or {}
    hashes = primary_file.get("hashes", {}) if isinstance(primary_file, dict) else {}
    if not isinstance(hashes, dict):
        return ""
    return str(hashes.get(normalize_hash_algorithm(algorithm), "") or "").strip().lower()


def version_type_priority(version_type: str) -> int:
    """回傳版本類型的排序優先權。

    Args:
        version_type: Modrinth 版本類型。

    Returns:
        用於比較版本優先順序的整數。
    """

    normalized = normalize_identifier(version_type)
    if normalized == "release":
        return 3
    if normalized in {"beta", "snapshot"}:
        return 2
    if normalized == "alpha":
        return 1
    return 0


def is_allowed_version_type(version_type: str) -> bool:
    """判斷版本類型是否在允許範圍內。

    Args:
        version_type: Modrinth 版本類型。

    Returns:
        若版本類型允許則回傳 True，否則回傳 False。
    """

    normalized = normalize_identifier(version_type)
    if normalized in {"", "release", "stable", "beta"}:
        return True
    if "beta" in normalized:
        return True
    for marker in ("alpha", "snapshot", "pre", "prerelease", "rc"):
        if marker in normalized:
            return False
    return False


def select_best_mod_version(versions: list[Any]) -> Any | None:
    """從版本清單中挑選最適合的候選版本。

    Args:
        versions: 候選版本清單。

    Returns:
        最佳候選版本，若清單為空則回傳 None。
    """

    if not versions:
        return None
    return max(
        versions,
        key=lambda version: (
            1 if getattr(version, "primary_file", None) else 0,
            version_type_priority(str(getattr(version, "version_type", "") or "")),
            str(getattr(version, "date_published", "") or ""),
            str(getattr(version, "version_number", "") or ""),
        ),
    )


__all__ = [
    "MODRINTH_PREFERRED_HASH_ALGORITHM",
    "extract_primary_file_hash",
    "is_allowed_version_type",
    "normalize_hash_algorithm",
    "select_best_mod_version",
    "select_primary_file",
    "version_type_priority",
]
