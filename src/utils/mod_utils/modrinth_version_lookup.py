"""Modrinth 版本查詢與回應解析工具。"""

from __future__ import annotations

from typing import Any

from ...models import ModrinthVersionLookupResult, OnlineModVersion
from .. import clean_api_identifier, normalize_hash_algorithm


def parse_modrinth_version(item: dict[str, Any]) -> OnlineModVersion:
    """將 Modrinth API 的版本資料轉為內部資料模型。

    Args:
        item: Modrinth 版本原始回應。

    Returns:
        轉換後的版本資料模型。
    """

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
    """將 Modrinth 雜湊查詢回應轉為 lookup 結果。

    Args:
        response: Modrinth API 雜湊查詢回應。
        algorithm: 雜湊演算法名稱。

    Returns:
        以雜湊值為 key 的 lookup 結果表。
    """

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
    "parse_modrinth_version",
    "parse_modrinth_version_lookup_response",
]
