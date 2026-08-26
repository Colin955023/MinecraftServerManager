"""模組規劃所擁有的外部查詢 ports"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from src.models import ModrinthVersionLookupResult, OnlineModVersion


class ModPlanningProviderPort(Protocol):
    """提供模組規劃所需的 provider-neutral 版本資料"""

    def resolve_project_names(self, project_ids: Iterable[str]) -> dict[str, str]:
        """
        批次解析 project id 顯示名稱

        Args:
            project_ids: 待解析的 provider project ids
        """
        ...

    def get_version_details(self, version_id: str) -> tuple[str, OnlineModVersion | None]: ...

    def fetch_project_name(self, project_id: str) -> str | None:
        """
        解析單一 project id 顯示名稱

        Args:
            project_id: provider project id
        """
        ...

    def get_versions(
        self,
        project_id: str,
        minecraft_version: str | None = None,
        loader: str | None = None,
    ) -> list[OnlineModVersion]: ...

    def get_current_versions_by_hashes(
        self, hashes: list[str], algorithm: str
    ) -> dict[str, ModrinthVersionLookupResult]: ...

    def get_latest_versions_by_hashes(
        self,
        hashes: list[str],
        algorithm: str,
        minecraft_version: str | None = None,
        loader: str | None = None,
    ) -> dict[str, ModrinthVersionLookupResult]: ...

    def get_recommended_version(
        self,
        project_id: str,
        minecraft_version: str | None,
        loader: str | None,
    ) -> OnlineModVersion | None: ...


class LoaderRulesPort(Protocol):
    """投影模組規劃所需的本機載入器版本規則"""

    def compatible_versions(self, minecraft_version: str, loader: str) -> list[str]:
        """
        取得指定 Minecraft 與載入器的相容版本

        Args:
            minecraft_version: 目標 Minecraft 版本
            loader: 目標載入器類型
        """
        ...


__all__ = ["LoaderRulesPort", "ModPlanningProviderPort"]
