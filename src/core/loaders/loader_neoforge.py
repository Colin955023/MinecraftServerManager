"""
NeoForge 載入器 Adapter
"""

from typing import Any

from ...models import LoaderVersion
from ...utils import HTTPUtils, get_logger
from ..loaders.loader_adapter import ILoaderAdapter
from ..loaders.loader_adapter_utils import MavenMetadataParser, build_standard_installer_args

logger = get_logger().bind(component="NeoForgeAdapter")


class NeoForgeAdapter(ILoaderAdapter):
    """NeoForge 模組載入器 Adapter，透過 Maven metadata 取得版本資訊（支援 pre-release）。"""

    def get_name(self) -> str:
        return "neoforge"

    def fetch_remote_versions(self) -> dict[str, list[str]]:
        """從 Maven metadata 取得 NeoForge 版本列表（包含 pre-release）。

        Returns:
            ``{mc_version: [full_version_string, ...]}`` 格式的版本字典。
        """
        neoforge_url = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
        try:
            content = HTTPUtils.get_content(neoforge_url, timeout=15)
            if content:
                # NeoForge 允許 pre-release 版本
                version_dict = MavenMetadataParser.build_loader_version_dict_from_metadata(
                    content, allow_prerelease=True
                )
                if version_dict:
                    for mc_version in version_dict:
                        version_dict[mc_version].sort(
                            key=lambda full_version: (
                                MavenMetadataParser.parse_forge_version_tuple(full_version.split("-", 1)[1])
                                if "-" in full_version
                                else MavenMetadataParser.parse_forge_version_tuple(full_version),
                                full_version,
                            ),
                            reverse=True,
                        )
                        version_dict[mc_version] = version_dict[mc_version][:5]
                return version_dict
            return {}
        except Exception as e:
            logger.exception(f"載入 NeoForge 版本失敗: {e}")
            raise

    def get_installer_url(self, _minecraft_version: str, loader_version: str) -> str | None:
        full_version = loader_version.strip()
        return (
            f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{full_version}/"
            f"neoforge-{full_version}-installer.jar"
        )

    def get_installer_args(
        self, java_path: str, installer_path: str, minecraft_version: str, loader_version: str, download_dir: str
    ) -> list[str]:
        return build_standard_installer_args(java_path, installer_path, minecraft_version, loader_version, download_dir)

    def requires_vanilla_server(self) -> bool:
        """
        NeoForge 安裝器內建下載 Vanilla Server，無需預先下載。

        Returns:
            永遠回傳 False。
        """
        return False

    def get_compatible_versions(self, cache_data: Any, mc_version: str) -> list[LoaderVersion]:
        """
        從快取資料中解析出相容指定 MC 版本的 NeoForge 版本列表。
        NeoForge 支援 1.20 這種大版本號前綴匹配。

        Args:
            cache_data: 從快取中取得的版本資料。
            mc_version: Minecraft 版本。

        Returns:
            相容的載入器版本列表。
        """
        if not isinstance(cache_data, dict):
            return []

        # NeoForge 支援 1.20 這種大版本號前綴，需找出符合的 mc_version 群組
        mc_parts = mc_version.split(".")
        candidates = [mc_version]
        if len(mc_parts) >= 2:
            candidates.append(f"{mc_parts[0]}.{mc_parts[1]}")
            # NeoForge 1.20.1 對應 20.1，1.21.1 對應 21.1
            if mc_parts[0] == "1":
                candidates.append(f"{mc_parts[1]}")
                if len(mc_parts) >= 3:
                    candidates.append(f"{mc_parts[1]}.{mc_parts[2]}")

        result = []
        for candidate in candidates:
            if candidate in cache_data and isinstance(cache_data[candidate], list):
                for version in cache_data[candidate]:
                    result.append(LoaderVersion(version=version))
        return result
