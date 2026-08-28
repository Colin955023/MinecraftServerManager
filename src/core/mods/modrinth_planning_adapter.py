"""Modrinth 與 LoaderManager 的模組規劃 adapters"""

from __future__ import annotations

from collections.abc import Iterable

from src.core import LoaderManager
from src.models import ModrinthVersionLookupResult, OnlineModVersion

from .modrinth_service import (
    fetch_modrinth_project_name,
    get_mod_version_details,
    get_mod_versions,
    get_modrinth_current_versions_by_hashes,
    get_modrinth_latest_versions_by_hashes,
    get_recommended_mod_version,
    resolve_modrinth_project_names,
)


class ModrinthPlanningAdapter:
    """將 Modrinth 查詢投影為模組規劃 port"""

    def resolve_project_names(self, project_ids: Iterable[str]) -> dict[str, str]:
        """
        批次解析 Modrinth project id 顯示名稱

        Args:
            project_ids: 待解析的 Modrinth project ids

        Returns:
            正規化 project id 到顯示名稱的對照
        """
        return resolve_modrinth_project_names(tuple(project_ids))

    def get_version_details(self, version_id: str) -> tuple[str, OnlineModVersion | None]:
        return get_mod_version_details(version_id)

    def fetch_project_name(self, project_id: str) -> str | None:
        """
        解析單一 Modrinth project id 顯示名稱

        Args:
            project_id: Modrinth project id

        Returns:
            可解析時的顯示名稱
        """
        return fetch_modrinth_project_name(project_id)

    def get_versions(
        self,
        project_id: str,
        minecraft_version: str | None = None,
        loader: str | None = None,
    ) -> list[OnlineModVersion]:
        return get_mod_versions(project_id, minecraft_version, loader)

    def get_current_versions_by_hashes(
        self, hashes: list[str], algorithm: str
    ) -> dict[str, ModrinthVersionLookupResult]:
        return get_modrinth_current_versions_by_hashes(hashes, algorithm)

    def get_latest_versions_by_hashes(
        self,
        hashes: list[str],
        algorithm: str,
        minecraft_version: str | None = None,
        loader: str | None = None,
    ) -> dict[str, ModrinthVersionLookupResult]:
        return get_modrinth_latest_versions_by_hashes(hashes, algorithm, minecraft_version, loader)

    def get_recommended_version(
        self,
        project_id: str,
        minecraft_version: str | None,
        loader: str | None,
    ) -> OnlineModVersion | None:
        return get_recommended_mod_version(project_id, minecraft_version, loader)


class LoaderManagerRulesAdapter:
    """只暴露既有 LoaderManager 的相容版本規則"""

    def __init__(self, loader_manager: LoaderManager) -> None:
        self._loader_manager = loader_manager

    def compatible_versions(self, minecraft_version: str, loader: str) -> list[str]:
        """
        取得指定 Minecraft 與載入器的相容版本

        Args:
            minecraft_version: 目標 Minecraft 版本
            loader: 目標載入器類型

        Returns:
            LoaderManager 已知的相容版本字串
        """
        return [
            version.version
            for version in self._loader_manager.get_compatible_loader_versions(minecraft_version, loader)
            if version.version
        ]


__all__ = ["LoaderManagerRulesAdapter", "ModrinthPlanningAdapter"]
