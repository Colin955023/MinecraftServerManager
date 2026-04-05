"""本地模組中繼資料工具。"""

from __future__ import annotations

import re
from typing import Any

from .. import normalize_identifier


def normalize_filename_stem(value: str | None) -> str:
    """將檔名正規化為可比對的 stem。

    Args:
        value: 原始檔名或空值。

    Returns:
        去除常見 jar 副檔名後的小寫字串。
    """

    filename = str(value or "").strip().lower()
    if filename.endswith(".jar.disabled"):
        filename = filename.removesuffix(".jar.disabled")
    elif filename.endswith(".jar"):
        filename = filename.removesuffix(".jar")
    return filename


def normalize_lax_filename(value: str | None, *, exclude_digits: bool = False) -> str:
    """將檔名正規化為較寬鬆的比對格式。

    Args:
        value: 原始檔名或空值。
        exclude_digits: 是否保留數字字元。

    Returns:
        已簡化並壓縮空白的字串。
    """

    normalized = normalize_filename_stem(value)
    if not normalized:
        return ""
    allowed_pattern = "[-+._0-9]" if exclude_digits else "[-+._]"
    normalized = re.sub(allowed_pattern, " ", normalized)
    return re.sub("\\s+", " ", normalized).strip()


def dependency_candidate_filenames(resolved_dependency: Any) -> list[str]:
    """從依賴資訊組出可能的檔名候選。

    Args:
        resolved_dependency: 已解析的依賴資訊。

    Returns:
        候選檔名清單。
    """

    candidates = [str(getattr(resolved_dependency, "file_name", "") or "").strip()]
    version = getattr(resolved_dependency, "version", None)
    primary_file = getattr(version, "primary_file", None)
    if isinstance(primary_file, dict):
        candidates.append(str(primary_file.get("filename", "") or "").strip())
    return [candidate for candidate in candidates if str(candidate or "").strip()]


def dependency_maybe_installed_by_filename(resolved_dependency: Any, installed_mods: list[Any] | None) -> bool:
    """以寬鬆檔名規則判斷依賴是否可能已安裝。

    Args:
        resolved_dependency: 已解析的依賴資訊。
        installed_mods: 已安裝模組清單。

    Returns:
        若找到可能相符的檔名則回傳 True。
    """

    dependency_names = {
        normalize_lax_filename(candidate, exclude_digits=True)
        for candidate in dependency_candidate_filenames(resolved_dependency)
        if normalize_lax_filename(candidate, exclude_digits=True)
    }
    if not dependency_names:
        return False
    for mod in installed_mods or []:
        installed_name = normalize_lax_filename(getattr(mod, "filename", ""), exclude_digits=True)
        if installed_name and installed_name in dependency_names:
            return True
    return False


def collect_installed_mod_identifiers(installed_mods: list[Any] | None) -> tuple[set[str], set[str]]:
    """蒐集已安裝模組的識別字與候選字串。

    Args:
        installed_mods: 已安裝模組清單。

    Returns:
        (project ids, identifiers) 的二元組。
    """

    installed_project_ids: set[str] = set()
    installed_identifiers: set[str] = set()
    for mod in installed_mods or []:
        platform_id = normalize_identifier(getattr(mod, "platform_id", ""))
        if platform_id:
            installed_project_ids.add(platform_id)
            installed_identifiers.add(platform_id)
        for raw_value in (getattr(mod, "id", ""), getattr(mod, "name", ""), getattr(mod, "filename", "")):
            normalized_value = normalize_identifier(raw_value)
            if normalized_value:
                installed_identifiers.add(normalized_value)
        stem = normalize_filename_stem(getattr(mod, "filename", ""))
        if stem:
            installed_identifiers.add(stem)
    return (installed_project_ids, installed_identifiers)


def collect_installed_mod_versions(installed_mods: list[Any] | None) -> dict[str, set[str]]:
    """依 project id 彙整已安裝版本。

    Args:
        installed_mods: 已安裝模組清單。

    Returns:
        以 project id 為 key 的版本集合。
    """

    versions_by_project: dict[str, set[str]] = {}
    for mod in installed_mods or []:
        project_id = normalize_identifier(getattr(mod, "platform_id", ""))
        version = normalize_identifier(getattr(mod, "version", ""))
        if not project_id or not version:
            continue
        versions_by_project.setdefault(project_id, set()).add(version)
    return versions_by_project


__all__ = [
    "collect_installed_mod_identifiers",
    "collect_installed_mod_versions",
    "dependency_candidate_filenames",
    "dependency_maybe_installed_by_filename",
    "normalize_filename_stem",
    "normalize_lax_filename",
]
