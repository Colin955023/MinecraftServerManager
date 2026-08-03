from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from defusedxml import ElementTree as ET

from ...utils import HTTPUtils, ServerDetectionVersionUtils, atomic_write_json, get_logger, record_and_mark
from .base_adapter import BaseLoaderAdapter

if TYPE_CHECKING:
    from ...models import LoaderVersion
    from .loader_manager import LoaderManager

logger = get_logger().bind(component="FabricFamilyAdapter")


class FabricAdapter(BaseLoaderAdapter):
    """
    Fabric 載入器適配器。
    處理 Fabric 的版本獲取、相容性判斷與安裝參數。
    """

    def __init__(self, manager: LoaderManager):
        self.manager = manager

    def get_id(self) -> str:
        return "fabric"

    def preload_versions(self):
        from .loader_manager import OperationResult

        logger.debug("預先抓取 Fabric 載入器版本...")
        fabric_url = "https://meta.fabricmc.net/v2/versions/loader"
        try:
            data = HTTPUtils.get_json(fabric_url, timeout=15)
            if data:
                stable_versions = [v for v in data if v.get("stable", False)]
                logger.debug(f"Fabric 版本過濾: {len(data)} -> {len(stable_versions)} (只保留 stable)")
                fabric_path = Path(self.manager.fabric_cache_file)
                if not atomic_write_json(fabric_path, stable_versions):
                    logger.warning("寫入 Fabric 版本快取失敗")
            return OperationResult(True, "Fabric 版本預載完成")
        except (OSError, ValueError) as e:
            self.manager._record_loader_cache_error(
                self.manager.fabric_cache_file, "載入 Fabric 版本失敗", {"context": "_preload_fabric_versions"}
            )
            logger.exception(f"載入 Fabric 版本失敗（IO/解析）: {e}")
            return OperationResult(False, f"無法從 API 獲取 Fabric 版本：{e}", error=e)
        except Exception as e:
            self.manager._record_loader_cache_error(
                self.manager.fabric_cache_file, "載入 Fabric 版本失敗", {"url": fabric_url}
            )
            logger.exception(f"載入 Fabric 版本失敗: {e}")
            return OperationResult(False, f"無法從 API 獲取 Fabric 版本：{e}", error=e)

    def get_compatible_versions(self, mc_version: str) -> list[LoaderVersion]:
        cache_key = f"{self.get_id()}_{mc_version}"
        if cache_key in self.manager._version_cache:
            return self.manager._version_cache[cache_key]

        cache_file = self._get_cache_file_path()
        if not Path(cache_file).exists():
            return []

        try:
            if self.get_id() == "fabric" and not ServerDetectionVersionUtils.is_fabric_compatible_version(mc_version):
                return []
            result = self.manager._load_version_objects_from_cache(cache_file)
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

    def _get_cache_file_path(self) -> str:
        return self.manager.fabric_cache_file

    def get_installer_download_url(self, minecraft_version: str, loader_version: str) -> str | None:
        _ = minecraft_version, loader_version
        return "https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.1/fabric-installer-1.1.1.jar"

    def get_installer_args(
        self, java_path: str, minecraft_version: str, loader_version: str, download_path: str, installer_path: str
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
            str(Path(download_path).parents[0]),
        ]

    def needs_vanilla_jar(self) -> bool:
        return True

    def is_installer_required(self) -> bool:
        return True


class QuiltAdapter(FabricAdapter):
    """
    Quilt 載入器適配器，繼承自 FabricAdapter。
    Quilt 的安裝參數與是否需要 vanilla jar 的邏輯與 Fabric 一致，
    只需覆寫 API 端點、解析邏輯與安裝器 URL。
    """

    def get_id(self) -> str:
        return "quilt"

    def _get_cache_file_path(self) -> str:
        quilt_cache_file = getattr(self.manager, "quilt_cache_file", "")
        if quilt_cache_file:
            return quilt_cache_file
        return str(Path(self.manager.fabric_cache_file).with_name("quilt_versions_cache.json"))

    def preload_versions(self):
        from .loader_manager import OperationResult

        logger.debug("預先抓取 Quilt 載入器版本...")
        quilt_url = "https://meta.quiltmc.org/v3/versions/loader"
        cache_file = self._get_cache_file_path()
        try:
            data = HTTPUtils.get_json(quilt_url, timeout=15)
            if data:
                # 優先使用官方 stable 標記；若沒有 stable 欄位或結果為空，使用版本字串偵測排除 pre-release
                stable_versions = [v for v in data if v.get("stable", False)]
                if not stable_versions:
                    test_keywords = ["pre", "prelease", "beta", "alpha", "snapshot", "rc"]
                    fallback = [
                        v
                        for v in data
                        if isinstance(v, dict)
                        and "version" in v
                        and not any(k in v["version"].lower() for k in test_keywords)
                    ]
                    chosen = fallback
                    logger.debug(
                        f"Quilt metadata 未提供 stable 標記或結果為空，採用版本字串過濾: {len(data)} -> {len(chosen)}"
                    )
                else:
                    chosen = stable_versions
                    logger.debug(f"Quilt 版本過濾: {len(data)} -> {len(chosen)} (使用 stable 標記)")

                if chosen:
                    chosen.sort(
                        key=lambda item: (
                            self.manager._parse_forge_version_tuple(str(item.get("version", ""))),
                            int(item.get("build", 0) or 0),
                        ),
                        reverse=True,
                    )
                    chosen = chosen[:1]

                quilt_path = Path(cache_file)
                try:
                    wrote = atomic_write_json(quilt_path, chosen)
                    if wrote:
                        logger.debug(f"寫入 Quilt 版本快取: {quilt_path}，項目數={len(chosen)}")
                    else:
                        logger.warning(f"寫入 Quilt 版本快取失敗: {quilt_path}")
                except Exception as e:
                    logger.exception(f"嘗試寫入 Quilt 快取時發生例外: {e}")
            else:
                logger.debug("Quilt metadata 回傳空資料，未寫入快取")
            return OperationResult(True, "Quilt 版本預載完成")
        except (OSError, ValueError) as e:
            self.manager._record_loader_cache_error(
                cache_file, "載入 Quilt 版本失敗", {"context": "_preload_quilt_versions"}
            )
            logger.exception(f"載入 Quilt 版本失敗（IO/解析）: {e}")
            return OperationResult(False, f"無法從 API 獲取 Quilt 版本：{e}", error=e)
        except Exception as e:
            self.manager._record_loader_cache_error(cache_file, "載入 Quilt 版本失敗", {"url": quilt_url})
            logger.exception(f"載入 Quilt 版本失敗: {e}")
            return OperationResult(False, f"無法從 API 獲取 Quilt 版本：{e}", error=e)

    def get_installer_download_url(self, minecraft_version: str, loader_version: str) -> str | None:
        _ = minecraft_version, loader_version
        installer_version = self._get_latest_quilt_installer_version() or "0.12.1"
        return (
            f"https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/"
            f"{installer_version}/quilt-installer-{installer_version}.jar"
        )

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
        except (OSError, ET.ParseError, ValueError) as e:
            logger.exception(f"讀取 Quilt installer metadata 失敗（IO/解析）: {e}")
        except Exception as e:
            logger.exception(f"讀取 Quilt installer metadata 失敗: {e}")
        return None
