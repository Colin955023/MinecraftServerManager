"""本地模組中繼資料工具"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .modrinth_query_utils import normalize_identifier

_LAX_SEP_TRANS = str.maketrans("-+._", "    ")
_LAX_SEP_DIGIT_TRANS = str.maketrans("-+._0123456789", "              ")


def mod_filename_stem(value: str | None) -> str:
    """
    移除模組檔名的已知副檔名

    Args:
        value: 原始模組檔名

    Returns:
        移除 .jar 或 .jar.disabled 後的檔名
    """

    filename = str(value or "").strip()
    return filename.removesuffix(".jar.disabled").removesuffix(".jar")


def _normalize_lax_filename(value: str | None, *, exclude_digits: bool = False) -> str:
    """將檔名正規化為較寬鬆的比對格式"""

    normalized = mod_filename_stem(value).lower()
    if not normalized:
        return ""
    table = _LAX_SEP_DIGIT_TRANS if exclude_digits else _LAX_SEP_TRANS
    return " ".join(normalized.translate(table).split())


def _dependency_candidate_filenames(resolved_dependency: Any) -> list[str]:
    """從依賴資訊組出可能的檔名候選"""

    candidates = [str(getattr(resolved_dependency, "file_name", "") or "").strip()]
    version = getattr(resolved_dependency, "version", None)
    primary_file = getattr(version, "primary_file", None)
    if isinstance(primary_file, dict):
        candidates.append(str(primary_file.get("filename", "") or "").strip())
    return [candidate for candidate in candidates if candidate]


@dataclass(frozen=True, slots=True)
class InstalledModIndex:
    """一次建立、供整個規劃流程重用的本地模組索引"""

    project_ids: frozenset[str]
    identifiers: frozenset[str]
    versions_by_project: dict[str, frozenset[str]]
    lax_filenames: frozenset[str]

    def maybe_installed_by_filename(self, resolved_dependency: Any) -> bool:
        """
        以已建立的檔名集合判斷依賴是否可能已安裝

        Args:
            resolved_dependency: 已解析的依賴資訊

        Returns:
            bool: 若可能已安裝則回傳 True，否則回傳 False
        """
        dependency_names = {
            normalized
            for candidate in _dependency_candidate_filenames(resolved_dependency)
            if (normalized := _normalize_lax_filename(candidate, exclude_digits=True))
        }
        return not dependency_names.isdisjoint(self.lax_filenames)


def build_installed_mod_index(installed_mods: Iterable[Any] | None) -> InstalledModIndex:
    """
    以單次巡覽建立本地模組的所有比對索引

    Args:
        installed_mods: 已安裝的模組清單或空值

    Returns:
        已建立的本地模組索引
    """
    installed_project_ids: set[str] = set()
    installed_identifiers: set[str] = set()
    lax_filenames: set[str] = set()
    versions_by_project: dict[str, set[str]] = {}
    for mod in installed_mods or ():
        platform_id = normalize_identifier(getattr(mod, "platform_id", ""))
        if platform_id:
            installed_project_ids.add(platform_id)
            installed_identifiers.add(platform_id)
        for raw_value in (getattr(mod, "id", ""), getattr(mod, "name", ""), getattr(mod, "filename", "")):
            normalized_value = normalize_identifier(raw_value)
            if normalized_value:
                installed_identifiers.add(normalized_value)
        filename = getattr(mod, "filename", "")
        stem = mod_filename_stem(filename).lower()
        if stem:
            installed_identifiers.add(stem)
        lax_filename = _normalize_lax_filename(filename, exclude_digits=True)
        if lax_filename:
            lax_filenames.add(lax_filename)
        version = normalize_identifier(getattr(mod, "version", ""))
        if platform_id and version:
            versions_by_project.setdefault(platform_id, set()).add(version)
    return InstalledModIndex(
        project_ids=frozenset(installed_project_ids),
        identifiers=frozenset(installed_identifiers),
        versions_by_project={key: frozenset(values) for key, values in versions_by_project.items()},
        lax_filenames=frozenset(lax_filenames),
    )


__all__ = ["InstalledModIndex", "build_installed_mod_index", "mod_filename_stem"]
