"""Provider 抽象定義。

集中描述線上模組來源需要提供的能力，讓 UI / 規劃流程不必直接依賴單一來源實作。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...models import ModrinthVersionLookupResult, OnlineModVersion
from ...utils import OnlineDependencyInstallPlan
from .models import OnlineModInfo


@dataclass(slots=True)
class ProviderDownloadContract:
    """描述某個 provider 可交付下載的核心欄位。"""

    provider: str
    project_id: str
    version_id: str
    download_url: str
    filename: str
    expected_hash: str = ""


@dataclass(slots=True)
class ProviderDependencyContext:
    """依賴解析所需的執行上下文。"""

    minecraft_version: str | None = None
    loader: str | None = None
    loader_version: str | None = None
    installed_mods: list[Any] | None = None
    root_project_id: str = ""
    root_project_name: str = ""
    max_depth: int = 20


class ModProvider(Protocol):
    """線上模組來源契約。"""

    provider_id: str

    def search(
        self,
        query: str,
        minecraft_version: str | None = None,
        loader: str | None = None,
        categories: list[str] | None = None,
        sort_by: str = "relevance",
        limit: int = 20,
    ) -> list[OnlineModInfo]:
        """
        搜尋符合條件的線上模組。

        Args:
            query: 搜尋關鍵字。
            minecraft_version: 目標 Minecraft 版本。
            loader: 目標載入器類型。
            categories: 額外分類條件。
            sort_by: 排序方式。
            limit: 最多回傳數量。

        Returns:
            搜尋到的模組清單。
        """
        ...

    def get_versions(
        self, project_id: str, minecraft_version: str | None = None, loader: str | None = None
    ) -> list[OnlineModVersion]: ...

    def get_project(self, project_id: str) -> OnlineModInfo | None: ...

    def get_version_details(self, version_id: str) -> tuple[str, OnlineModVersion | None]: ...

    def get_current_versions_by_hashes(
        self, hashes: list[str] | set[str] | tuple[str, ...], algorithm: str
    ) -> dict[str, ModrinthVersionLookupResult]: ...

    def get_latest_versions_by_hashes(
        self,
        hashes: list[str] | set[str] | tuple[str, ...],
        algorithm: str,
        minecraft_version: str | None = None,
        loader: str | None = None,
    ) -> dict[str, ModrinthVersionLookupResult]: ...

    def get_recommended_version(
        self, project_id: str, minecraft_version: str | None = None, loader: str | None = None
    ) -> OnlineModVersion | None: ...

    def resolve_local_project_info(self, local_mod: Any) -> OnlineModInfo | None:
        """
        依本地模組資訊解析對應的線上專案。

        Args:
            local_mod: 本地模組物件。

        Returns:
            解析後的線上專案資訊；無法解析時回傳 None。
        """
        ...

    def resolve_project_names(self, project_ids: list[str] | set[str] | tuple[str, ...]) -> dict[str, str]:
        """
        批次將 project id 轉為可讀名稱。

        Args:
            project_ids: 要解析的 project id 集合。

        Returns:
            以 project id 為 key 的名稱對應表。
        """
        ...

    def resolve_dependencies(
        self,
        version: OnlineModVersion,
        *,
        context: ProviderDependencyContext,
    ) -> OnlineDependencyInstallPlan:
        """
        解析指定版本所需的依賴安裝計畫。

        Args:
            version: 目標版本資訊。
            context: 依賴解析所需的執行上下文。

        Returns:
            依賴安裝計畫。
        """
        ...

    def get_download_contract(
        self,
        *,
        project_id: str,
        version: OnlineModVersion,
    ) -> ProviderDownloadContract | None: ...


__all__ = [
    "ModProvider",
    "ProviderDependencyContext",
    "ProviderDownloadContract",
]
