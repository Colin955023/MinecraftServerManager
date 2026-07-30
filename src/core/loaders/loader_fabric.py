"""
Fabric 載入器 Adapter
"""

from typing import Any

from ...models import LoaderVersion
from ...utils import HTTPUtils, get_logger
from .loader_adapter import ILoaderAdapter, parse_fabric_like_versions

logger = get_logger().bind(component="FabricAdapter")


class FabricAdapter(ILoaderAdapter):
    """Fabric 模組載入器 Adapter，透過 Fabric Meta API 取得版本資訊。"""

    def get_name(self) -> str:
        return "fabric"

    def fetch_remote_versions(self) -> dict[str, list[str]]:
        """取得 Fabric 載入器版本。

        Returns:
            ``{"all": [version_string, ...]}`` 格式的版本字典。
        """
        fabric_url = "https://meta.fabricmc.net/v2/versions/loader"
        try:
            data = HTTPUtils.get_json(fabric_url, timeout=15)
            if data:
                stable_versions = [
                    str(v.get("version", "")) for v in data if v.get("stable", False) and v.get("version")
                ]
                logger.debug(f"Fabric 版本過濾: {len(data)} -> {len(stable_versions)} (只保留 stable)")
                return {"all": stable_versions}
            return {}
        except Exception as e:
            logger.exception(f"載入 Fabric 版本失敗: {e}")
            raise

    def get_installer_url(self, _minecraft_version: str, _loader_version: str) -> str | None:
        return "https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.1/fabric-installer-1.1.1.jar"  # 需抓取最新版本

    def get_installer_args(
        self, java_path: str, installer_path: str, minecraft_version: str, loader_version: str, download_dir: str
    ) -> list[str]:
        return [
            java_path,
            "-jar",
            installer_path,
            "server",
            "-mcversion",
            minecraft_version,
            "-loader",
            loader_version,
            "-downloadMinecraft",
            "-dir",
            download_dir,
        ]

    def requires_vanilla_server(self) -> bool:
        """
        Fabric 安裝器內建下載 Vanilla Server，無需預先下載。

        Returns:
            永遠回傳 False。
        """
        return False

    def get_compatible_versions(self, cache_data: Any, mc_version: str) -> list[LoaderVersion]:
        """
        取得相容的載入器版本列表。

        Args:
            cache_data: 從快取中取得的版本資料。
            mc_version: Minecraft 版本。

        Returns:
            相容的載入器版本列表。
        """
        return parse_fabric_like_versions(cache_data, mc_version)
