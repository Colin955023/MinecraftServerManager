"""
Loader Adapter Interface.
定義所有 Minecraft 模組載入器必須實作的介面。
"""

from __future__ import annotations

from typing import Any, Protocol

from ...core import ServerDetectionUtils
from ...models import LoaderVersion


class ILoaderAdapter(Protocol):
    """Minecraft 模組載入器（Forge / Fabric / Quilt / NeoForge）的統一介面協定。

    所有載入器 Adapter 必須實作此協定中定義的方法，
    以確保 ServerManager 可以一致地操作不同載入器。
    """

    def get_name(self) -> str:
        """回傳載入器的識別名稱 (如 'forge', 'fabric')。"""
        ...

    def fetch_remote_versions(self) -> dict[str, list[str]]:
        """
        從遠端 API 或 Maven 取得並解析版本。
        回傳格式為: { "minecraft_version": ["mc_version-loader_version", ...] }
        """
        ...

    def get_installer_url(self, minecraft_version: str, loader_version: str) -> str | None:
        """回傳特定載入器版本的安裝器下載網址。"""
        ...

    def get_installer_args(
        self, java_path: str, installer_path: str, minecraft_version: str, loader_version: str, download_dir: str
    ) -> list[str]:
        """回傳執行安裝器 subprocess 所需的命令列參數。"""
        ...

    def requires_vanilla_server(self) -> bool:
        """標示此載入器是否需要在執行安裝器之前，先下載 Vanilla Server 核心。"""
        ...

    def get_compatible_versions(self, cache_data: Any, mc_version: str) -> list[LoaderVersion]:
        """從快取資料中解析出相容該 MC 版本的載入器版本列表。"""
        ...


def parse_fabric_like_versions(cache_data: Any, mc_version: str) -> list[LoaderVersion]:
    """
    共用的 Fabric/Quilt 版本解析邏輯，用於減少重複程式碼。

    Args:
        cache_data: 從遠端 API 或 Maven 取得的快取資料。
        mc_version: 目標 Minecraft 版本。

    Returns:
        相容該 MC 版本的載入器版本列表。
    """
    if not ServerDetectionUtils.is_fabric_compatible_version(mc_version):
        return []

    if isinstance(cache_data, dict) and "all" in cache_data:
        versions = cache_data["all"]
        return [LoaderVersion(version=v) for v in versions if isinstance(v, str)]

    if isinstance(cache_data, list):
        result = []
        for v in cache_data:
            if not isinstance(v, dict) or not v.get("version"):
                continue
            gv = v.get("game_versions")
            if (
                gv
                and isinstance(gv, list)
                and mc_version not in [gv_i.get("version") if isinstance(gv_i, dict) else gv_i for gv_i in gv]
            ):
                continue
            result.append(LoaderVersion(version=v["version"]))
        return result

    return []
