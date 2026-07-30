"""
Quilt 載入器 Adapter
"""

from pathlib import Path
from typing import Any

from defusedxml import ElementTree as ET

from ...models import LoaderVersion
from ...utils import HTTPUtils, get_logger
from .loader_adapter import ILoaderAdapter, parse_fabric_like_versions

logger = get_logger().bind(component="QuiltAdapter")


class QuiltAdapter(ILoaderAdapter):
    """Quilt 模組載入器 Adapter，透過 Quilt Meta API 取得版本資訊。"""

    def get_name(self) -> str:
        return "quilt"

    def fetch_remote_versions(self) -> dict[str, list[str]]:
        """從 Quilt Meta API 取得載入器版本列表。

        Returns:
            ``{"all": [version_string, ...]}`` 格式的版本字典。
        """
        quilt_url = "https://meta.quiltmc.org/v3/versions/loader"
        try:
            data = HTTPUtils.get_json(quilt_url, timeout=15)
            if data:
                stable_versions = [v for v in data if v.get("stable", False)]
                if not stable_versions:
                    test_keywords = ["pre", "prelease", "beta", "alpha", "snapshot", "rc"]
                    fallback = [
                        v
                        for v in data
                        if isinstance(v, dict)
                        and not any(keyword in str(v.get("version", "")).lower() for keyword in test_keywords)
                    ]
                    stable_versions = fallback or data
                logger.debug(f"Quilt 版本過濾: {len(data)} -> {len(stable_versions)} (只保留 stable)")
                return {"all": [str(v.get("version", "")) for v in stable_versions if v.get("version")]}
            return {}
        except Exception as e:
            logger.exception(f"載入 Quilt 版本失敗: {e}")
            raise

    def _get_latest_quilt_installer_version(self) -> str | None:
        metadata_url = "https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/maven-metadata.xml"
        try:
            content = HTTPUtils.get_content(metadata_url, timeout=15)
            if not content:
                return None
            root = ET.fromstring(content)
            release_version = root.findtext(".//versioning/release") or root.findtext(".//versioning/latest")
            if release_version:
                return release_version.strip()
        except Exception as e:
            logger.exception(f"讀取 Quilt installer metadata 失敗: {e}")
        return None

    def get_installer_url(self, _minecraft_version: str, _loader_version: str) -> str | None:
        installer_version = self._get_latest_quilt_installer_version() or "0.12.1"
        return (
            f"https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/"
            f"{installer_version}/quilt-installer-{installer_version}.jar"
        )

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
            "-dir",
            str(Path(download_dir).parents[0]),
        ]

    def requires_vanilla_server(self) -> bool:
        """
        Quilt 安裝器需要預先下載 Vanilla Server 核心。

        Returns:
            永遠回傳 True。
        """
        return True

    def get_compatible_versions(self, cache_data: Any, mc_version: str) -> list[LoaderVersion]:
        """
        從快取資料中解析出相容指定 MC 版本的 Quilt 版本列表。

        Args:
            cache_data: 從快取中取得的版本資料。
            mc_version: Minecraft 版本。

        Returns:
            相容的載入器版本列表。
        """
        return parse_fabric_like_versions(cache_data, mc_version)
