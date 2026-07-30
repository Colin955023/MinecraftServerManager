"""
Forge 載入器 Adapter
"""

from typing import Any

from ...models import LoaderVersion
from ...utils import HTTPUtils, get_logger
from ..loaders.loader_adapter import ILoaderAdapter
from ..loaders.loader_adapter_utils import MavenMetadataParser, build_standard_installer_args

logger = get_logger().bind(component="ForgeAdapter")


class ForgeAdapter(ILoaderAdapter):
    """Forge 模組載入器 Adapter，透過 Maven metadata 取得版本資訊。"""

    def get_name(self) -> str:
        return "forge"

    def fetch_remote_versions(self) -> dict[str, list[str]]:
        """從 Maven metadata 取得 Forge 版本列表。

        Returns:
            ``{mc_version: [full_version_string, ...]}`` 格式的版本字典。
        """
        forge_url = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
        try:
            content = HTTPUtils.get_content(forge_url, timeout=15)
            if content:
                version_dict = MavenMetadataParser.build_loader_version_dict_from_metadata(content)
                if version_dict:
                    for mc_version in version_dict:
                        version_dict[mc_version].sort(
                            key=lambda full_version: (
                                MavenMetadataParser.parse_forge_version_tuple(full_version.split("-", 1)[1])
                                if "-" in full_version
                                else (0,),
                                full_version,
                            ),
                            reverse=True,
                        )
                        version_dict[mc_version] = version_dict[mc_version][:5]
                return version_dict
            return {}
        except Exception as e:
            logger.exception(f"載入 Forge 版本失敗: {e}")
            raise

    def get_installer_url(self, minecraft_version: str, loader_version: str) -> str | None:
        return (
            f"https://maven.minecraftforge.net/net/minecraftforge/forge/{minecraft_version}-{loader_version}/"
            f"forge-{minecraft_version}-{loader_version}-installer.jar"
        )

    def get_installer_args(
        self, java_path: str, installer_path: str, minecraft_version: str, loader_version: str, download_dir: str
    ) -> list[str]:
        return build_standard_installer_args(java_path, installer_path, minecraft_version, loader_version, download_dir)

    def requires_vanilla_server(self) -> bool:
        """
        Forge 安裝器內建下載 Vanilla Server，無需預先下載。

        Returns:
            永遠回傳 False。
        """
        return False

    def get_compatible_versions(self, cache_data: Any, mc_version: str) -> list[LoaderVersion]:
        """
        從快取資料中解析出相容指定 MC 版本的 Forge 版本列表。

        Args:
            cache_data: 從快取中取得的版本資料。
            mc_version: Minecraft 版本。

        Returns:
            相容的載入器版本列表。
        """
        if not isinstance(cache_data, dict):
            return []
        if mc_version in cache_data and isinstance(cache_data[mc_version], list):
            result = []
            for version in cache_data[mc_version]:
                if "-" in version and version.startswith(mc_version):
                    forge_version = version.split("-", 1)[1]
                    result.append(LoaderVersion(version=forge_version))
            return result
        return []
