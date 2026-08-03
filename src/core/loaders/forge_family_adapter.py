from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from defusedxml import ElementTree as ET

from ...models import LoaderVersion
from ...utils import HTTPUtils, PathUtils, atomic_write_json, get_logger, record_and_mark
from .base_adapter import BaseLoaderAdapter

if TYPE_CHECKING:
    from .loader_manager import LoaderManager

logger = get_logger().bind(component="ForgeFamilyAdapter")


class ForgeAdapter(BaseLoaderAdapter):
    """
    Forge 載入器適配器。
    處理 Forge 家族（包含 NeoForge）共用的 XML 解析與安裝參數。
    """

    def __init__(self, manager: LoaderManager):
        self.manager = manager

    def get_id(self) -> str:
        return "forge"

    def _get_cache_file_path(self) -> str:
        return self.manager.forge_cache_file

    def preload_versions(self):
        logger.debug("預先抓取 Forge 載入器版本...")
        cache_file = self._get_cache_file_path()
        try:
            forge_url = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
            content = HTTPUtils.get_content(forge_url, timeout=15)
            if content:
                logger.debug("成功獲取 Forge XML 數據")
                version_dict = self.manager._build_loader_version_dict_from_metadata(content)
                logger.debug(f"Forge 版本過濾後: {len(version_dict)} 個穩定版本群組")
                if version_dict:
                    for mc_version in version_dict:
                        version_dict[mc_version].sort(
                            key=lambda full_version: (
                                self.manager._parse_forge_version_tuple(full_version.split("-", 1)[1])
                                if "-" in full_version
                                else (0,),
                                full_version,
                            ),
                            reverse=True,
                        )
                        version_dict[mc_version] = version_dict[mc_version][:5]
                    forge_path = Path(cache_file)
                    if not atomic_write_json(forge_path, version_dict):
                        logger.warning("寫入 Forge 版本快取失敗")
        except (OSError, ET.ParseError, ValueError) as e:
            self.manager._record_loader_cache_error(
                cache_file, "載入 Forge 版本失敗", {"context": "_preload_forge_versions"}
            )
            logger.exception(f"Maven metadata API 方法失敗（IO/解析）: {e}")
        except Exception as e:
            self.manager._record_loader_cache_error(cache_file, "載入 Forge 版本失敗")
            logger.exception(f"Maven metadata API 方法失敗: {e}")

        return

    def get_compatible_versions(self, mc_version: str) -> list[LoaderVersion]:
        cache_key = f"{self.get_id()}_{mc_version}"
        if cache_key in self.manager._version_cache:
            return self.manager._version_cache[cache_key]

        cache_file = self._get_cache_file_path()
        if not Path(cache_file).exists():
            return []

        try:
            cache = PathUtils.load_json(Path(cache_file))
            if not cache:
                return []
            result = []
            if mc_version in cache and isinstance(cache[mc_version], list):
                for version in cache[mc_version]:
                    if "-" in version and version.startswith(mc_version):
                        forge_version = version.split("-", 1)[1]
                        result.append(LoaderVersion(version=forge_version))
            if result:
                self.manager._version_cache[cache_key] = result
            return result
        except (OSError, ValueError, TypeError) as e:
            with suppress(Exception):
                record_and_mark(
                    e,
                    Path(cache_file),
                    reason=f"get_compatible_loader_versions_{self.get_id()}",
                    details={"mc_version": mc_version},
                )
            logger.exception(f"獲取 {self.get_id()} 版本時發生錯誤（IO/解析）: {e}")
            return []
        except Exception as e:
            with suppress(Exception):
                record_and_mark(
                    e,
                    Path(cache_file),
                    reason=f"get_compatible_loader_versions_{self.get_id()}_unexpected",
                    details={"mc_version": mc_version},
                )
            logger.exception(f"獲取 {self.get_id()} 版本時發生錯誤: {e}")
            return []

    def get_installer_download_url(self, minecraft_version: str, loader_version: str) -> str | None:
        return (
            f"https://maven.minecraftforge.net/net/minecraftforge/forge/{minecraft_version}-{loader_version}/"
            f"forge-{minecraft_version}-{loader_version}-installer.jar"
        )

    def get_installer_args(
        self, java_path: str, minecraft_version: str, loader_version: str, download_path: str, installer_path: str
    ) -> list[str]:
        _ = minecraft_version, loader_version, download_path
        return [java_path, "-jar", installer_path, "--installServer"]

    def needs_vanilla_jar(self) -> bool:
        return False

    def is_installer_required(self) -> bool:
        return True


class NeoForgeAdapter(ForgeAdapter):
    """
    NeoForge 載入器適配器，繼承自 ForgeAdapter。
    NeoForge 與 Forge 的安裝參數及行為幾乎相同，
    僅覆寫 API 解析參數（允許 pre-release）以及版本相容比對邏輯。
    """

    def get_id(self) -> str:
        return "neoforge"

    def _get_cache_file_path(self) -> str:
        neoforge_cache_file = getattr(self.manager, "neoforge_cache_file", "")
        if neoforge_cache_file:
            return neoforge_cache_file
        return str(Path(self.manager.forge_cache_file).with_name("neoforge_versions_cache.json"))

    def preload_versions(self):
        logger.debug("預先抓取 NeoForge 載入器版本...")
        cache_file = self._get_cache_file_path()
        try:
            neoforge_url = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
            content = HTTPUtils.get_content(neoforge_url, timeout=15)
            if content:
                logger.debug("成功獲取 NeoForge XML 數據")
                version_dict = self.manager._build_loader_version_dict_from_metadata(content, allow_prerelease=True)
                group_count = len(version_dict)
                total_versions = sum(len(v) for v in version_dict.values()) if version_dict else 0
                logger.debug(f"NeoForge 解析後: groups={group_count} total_versions={total_versions}")
                if group_count > 0:
                    for mc_version in version_dict:
                        version_dict[mc_version].sort(
                            key=lambda full_version: (
                                self.manager._parse_forge_version_tuple(full_version.split("-", 1)[1])
                                if "-" in full_version
                                else self.manager._parse_forge_version_tuple(full_version),
                                full_version,
                            ),
                            reverse=True,
                        )
                        # 僅保留最新 5 個版本
                        version_dict[mc_version] = version_dict[mc_version][:5]

                    try:
                        wrote = atomic_write_json(Path(cache_file), version_dict)
                        if wrote:
                            logger.debug(
                                f"寫入 NeoForge 版本快取: {cache_file} groups={group_count} total_versions={total_versions}"
                            )
                        else:
                            logger.warning(f"寫入 NeoForge 版本快取失敗: {cache_file}")
                    except Exception as e:
                        logger.exception(f"嘗試寫入 NeoForge 快取時發生例外: {e}")
        except (OSError, ET.ParseError, ValueError) as e:
            self.manager._record_loader_cache_error(
                cache_file, "載入 NeoForge 版本失敗", {"context": "_preload_neoforge_versions"}
            )
            logger.exception(f"Maven metadata API 方法失敗（IO/解析）: {e}")
        except Exception as e:
            self.manager._record_loader_cache_error(cache_file, "載入 NeoForge 版本失敗")
            logger.exception(f"Maven metadata API 方法失敗: {e}")

        return

    def get_compatible_versions(self, mc_version: str) -> list[LoaderVersion]:
        cache_key = f"{self.get_id()}_{mc_version}"
        if cache_key in self.manager._version_cache:
            return self.manager._version_cache[cache_key]

        cache_file = self._get_cache_file_path()
        if not Path(cache_file).exists():
            return []

        try:
            cache = PathUtils.load_json(Path(cache_file))
            if not cache:
                return []
            result = []
            candidates = self.manager._build_neoforge_mc_version_candidates(mc_version)
            matched_key = None
            for cand in candidates:
                if cand in cache and isinstance(cache[cand], list):
                    matched_key = cand
                    break

            if matched_key:
                for version in cache[matched_key]:
                    if "-" in version:
                        loader_version = version.split("-", 1)[1]
                        loader_version = self._normalize_neoforge_loader_version(matched_key, loader_version)
                        result.append(LoaderVersion(version=loader_version))
            if result:
                self.manager._version_cache[cache_key] = result
            return result
        except (OSError, ValueError, TypeError) as e:
            with suppress(Exception):
                record_and_mark(
                    e,
                    Path(cache_file),
                    reason="get_compatible_loader_versions_neoforge",
                    details={"mc_version": mc_version},
                )
            logger.exception(f"獲取 NeoForge 版本時發生錯誤（IO/解析）: {e}")
            return []
        except Exception as e:
            with suppress(Exception):
                record_and_mark(
                    e,
                    Path(cache_file),
                    reason="get_compatible_loader_versions_neoforge_unexpected",
                    details={"mc_version": mc_version},
                )
            logger.exception(f"獲取 NeoForge 版本時發生錯誤: {e}")
            return []

    def get_installer_download_url(self, minecraft_version: str, loader_version: str) -> str | None:
        _ = minecraft_version
        full_version = loader_version.strip()
        return (
            f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{full_version}/"
            f"neoforge-{full_version}-installer.jar"
        )

    @staticmethod
    def _normalize_neoforge_loader_version(matched_key: str, loader_version: str) -> str:
        """正規化 NeoForge 載入器版本號。

        舊短格式快取（如 ``"21.1-165"``）的後段僅含 build 號碼（``"165"``），
        需與快取鍵（``"21.1"``）組合為完整版本號 ``"21.1.165"``。
        新格式（如 ``"1.21.1-21.1.165"``）的後段已是完整版本號，直接回傳。
        """
        if "." in loader_version:
            return loader_version
        return f"{matched_key}.{loader_version}"
