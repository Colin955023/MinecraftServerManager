"""模組供應者的中立查詢埠"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from src.models import ModrinthVersionLookupResult


class ModProviderPort(Protocol):
    """所有模組功能共用的 provider-neutral 查詢埠"""

    def find_projects(
        self,
        query: str | Iterable[str],
        *,
        exact: bool = False,
        search: bool = False,
        include_details: bool = False,
        minecraft_version: str | None = None,
        loader: str | None = None,
        categories: list[str] | None = None,
        sort_by: str = "relevance",
        limit: int = 20,
    ) -> Any: ...

    def resolve_versions(
        self,
        project_id: str = "",
        minecraft_version: str | None = None,
        loader: str | None = None,
        *,
        version_id: str | None = None,
        recommended: bool = False,
    ) -> Any: ...

    def resolve_files(
        self,
        hashes: Iterable[str],
        algorithm: str,
        *,
        latest: bool = False,
        minecraft_version: str | None = None,
        loader: str | None = None,
    ) -> dict[str, ModrinthVersionLookupResult]: ...


__all__ = ["ModProviderPort"]
