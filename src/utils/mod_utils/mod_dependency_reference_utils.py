"""模組依賴參照解析工具。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...models import OnlineModVersion, ResolvedDependencyReference
from .. import (
    apply_loader_specific_dependency_override,
    clean_api_identifier,
    normalize_identifier,
)


def resolve_dependency_reference(
    dependency: dict[str, Any],
    dependency_names: dict[str, str],
    *,
    loader: str | None = None,
    version_details_cache: dict[str, tuple[str, OnlineModVersion | None]] | None = None,
    get_mod_version_details: Callable[[str], tuple[str, OnlineModVersion | None]],
    fetch_project_name: Callable[[str], str | None],
) -> ResolvedDependencyReference:
    """解析單一依賴項目，統一 project id / version id 回填流程。

    Args:
        dependency: 原始依賴資料。
        dependency_names: 依賴名稱快取（key 為 normalize 後 project id）。
        loader: 目前載入器名稱，用於套用 loader-specific override。
        version_details_cache: 版本詳情快取，避免重複查詢 version id。
        get_mod_version_details: 依 version id 取得 `(project_id, version)` 的函式。
        fetch_project_name: 依 project id 查詢專案名稱的函式。

    Returns:
        解析完成的依賴參照。
    """

    resolved = ResolvedDependencyReference(
        project_id=clean_api_identifier(str(dependency.get("project_id", "") or "")),
        version_id=clean_api_identifier(str(dependency.get("version_id", "") or "")),
        file_name=str(dependency.get("file_name", "") or dependency.get("filename", "") or "").strip(),
        resolution_source="project_id" if str(dependency.get("project_id", "") or "").strip() else "version_id",
        resolution_confidence="direct" if str(dependency.get("project_id", "") or "").strip() else "fallback",
    )
    if resolved.version_id:
        cache = version_details_cache if version_details_cache is not None else {}
        if resolved.version_id not in cache:
            cache[resolved.version_id] = get_mod_version_details(resolved.version_id)
        version_project_id, version_details = cache.get(resolved.version_id, ("", None))
        if version_details is not None:
            resolved.version = version_details
            resolved.version_name = str(version_details.display_name or version_details.version_number or "").strip()
        if not resolved.project_id and version_project_id:
            resolved.project_id = version_project_id
            resolved.resolution_source = "version_detail"
            resolved.resolution_confidence = "fallback"
    overridden_project_id = apply_loader_specific_dependency_override(resolved.project_id, loader)
    if overridden_project_id and normalize_identifier(overridden_project_id) != resolved.compare_project_id:
        resolved.project_id = overridden_project_id
        resolved.project_name = ""
        resolved.version_id = ""
        resolved.version_name = ""
        resolved.version = None
        resolved.resolution_source = "loader_override"
        resolved.resolution_confidence = "fallback"
    if resolved.project_id:
        resolved.project_name = dependency_names.get(resolved.compare_project_id, "").strip()
        if not resolved.project_name:
            fetched_name = fetch_project_name(resolved.project_id)
            if fetched_name:
                dependency_names[resolved.compare_project_id] = fetched_name
                resolved.project_name = fetched_name
    return resolved
