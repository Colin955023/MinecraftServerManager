"""Modrinth API payload 解析"""

from __future__ import annotations

from typing import Any

from src.models import ModrinthVersionLookupResult, OnlineModVersion
from src.utils import clean_api_identifier, normalize_hash_algorithm

MODRINTH_MAX_VERSION_DEPENDENCIES = 2048


def parse_modrinth_version(item: dict[str, Any]) -> OnlineModVersion:
    """
    將 Modrinth 版本 API payload 轉換為內部版本模型

    Args:
        item: Modrinth 版本 API 回應

    Returns:
        內部版本模型
    """
    game_versions = [str(value) for value in item.get("game_versions", []) if value]
    loaders = [str(value) for value in item.get("loaders", []) if value]
    version_number = str(item.get("version_number", "") or "")
    display_name = version_number or str(item.get("name", "未知版本") or "未知版本")
    raw_dependencies = item.get("dependencies", [])
    dependencies = raw_dependencies[:MODRINTH_MAX_VERSION_DEPENDENCIES] if isinstance(raw_dependencies, list) else []
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
        dependencies=dependencies,
    )


def parse_modrinth_version_lookup_response(
    response: dict[str, Any] | None, algorithm: str
) -> dict[str, ModrinthVersionLookupResult]:
    """
    將 Modrinth 雜湊查詢回應轉成結果對照表

    Args:
        response: Modrinth 雜湊查詢回應
        algorithm: 雜湊演算法名稱

    Returns:
        以正規化雜湊值為 key 的結果對照表
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
        resolved[normalized_hash] = ModrinthVersionLookupResult(
            file_hash=normalized_hash,
            algorithm=normalized_algorithm,
            project_id=project_id,
            version=parse_modrinth_version(raw_item),
        )
    return resolved


__all__ = ["parse_modrinth_version", "parse_modrinth_version_lookup_response"]
