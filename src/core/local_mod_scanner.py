"""本地模組掃描與 metadata 解析 helper。"""

from __future__ import annotations

import contextlib
import re
import tomllib
import zipfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..utils import (
    ModIndexManager,
    PathUtils,
    ServerDetectionUtils,
    ServerDetectionVersionUtils,
    derive_provider_lifecycle_state,
    get_logger,
    record_and_mark,
)
from .mod_models import MODRINTH_HASH_ALGORITHM, LocalModInfo, ModPlatform, ModStatus

TomlDecodeError = tomllib.TOMLDecodeError
logger = get_logger().bind(component="LocalModScanner")


class LocalModScanner:
    """掃描 mods 目錄並建立 `LocalModInfo`。"""

    def __init__(
        self,
        *,
        index_manager: ModIndexManager,
        mods_path: Path,
        server_config: Any,
        resolve_platform_info: Callable[..., tuple[ModPlatform, str, str]],
        quarantine_file: Callable[[Path, str], None],
    ) -> None:
        self.index_manager = index_manager
        self.mods_path = mods_path
        self.server_config = server_config
        self._resolve_platform_info = resolve_platform_info
        self._quarantine_file = quarantine_file

    def scan_mods(self, create_mod_info_from_file: Callable[[Path], LocalModInfo | None]) -> list[LocalModInfo]:
        """
        掃描 mods 目錄，對每個檔案呼叫 `create_mod_info_from_file` 以建立 `LocalModInfo`。

        Args:
            create_mod_info_from_file: 用於從檔案建立 `LocalModInfo` 的回呼函式。
        Returns:
            LocalModInfo 物件的列表。
        """
        self.index_manager.cleanup_stale_entries()
        mods: list[LocalModInfo] = []
        files_to_scan = [
            file_path
            for file_path in self.mods_path.glob("*.jar*")
            if file_path.suffix == ".jar" or file_path.name.endswith(".jar.disabled")
        ]
        files_to_scan.sort(key=lambda path: path.name.lower())
        with ThreadPoolExecutor(max_workers=min(6, len(files_to_scan) or 1)) as executor:
            results = executor.map(create_mod_info_from_file, files_to_scan)
        for mod_info in results:
            if mod_info:
                mods.append(mod_info)
        self.index_manager.flush()
        return mods

    def create_mod_info_from_file(self, file_path: Path) -> LocalModInfo | None:
        """
        從指定的檔案建立 LocalModInfo 物件。

        Args:
            file_path: 要處理的模組檔案的路徑。
        Returns:
            LocalModInfo 物件，如果檔案無法處理或發生錯
        """
        try:
            filename, enabled, base_name = self.parse_file_info(file_path)
            cached_provider = self.index_manager.get_cached_provider_metadata(file_path) or {}
            mod_data = {
                "name": base_name,
                "version": "未知",
                "author": "",
                "description": "",
                "loader_type": "未知",
                "mc_version": "未知",
            }
            cached_metadata = self.index_manager.get_cached_metadata(file_path)
            if cached_metadata:
                mod_data.update(cached_metadata)
            else:
                self.extract_metadata_from_jar(file_path, mod_data)
                self.apply_fallback_logic(base_name, mod_data)
                self.index_manager.cache_metadata(
                    file_path,
                    {
                        "version": mod_data["version"],
                        "author": mod_data["author"],
                        "description": mod_data["description"],
                        "loader_type": mod_data["loader_type"],
                        "mc_version": mod_data["mc_version"],
                    },
                )
            self.apply_server_config_overrides(mod_data)
            platform, platform_id, platform_slug = self._resolve_platform_info(
                file_path,
                mod_data["name"],
                base_name,
                filename,
                cached_provider,
            )
            current_hash = ""
            hash_algorithm = ""
            if platform == ModPlatform.MODRINTH and platform_id:
                current_hash = self.index_manager.ensure_cached_hash(file_path, MODRINTH_HASH_ALGORITHM)
                hash_algorithm = MODRINTH_HASH_ALGORITHM if current_hash else ""
            refreshed_provider = self.index_manager.get_cached_provider_metadata(file_path) or cached_provider
            provider_lifecycle_state = str(
                refreshed_provider.get("lifecycle_state", "") or derive_provider_lifecycle_state(refreshed_provider)
            ).strip()
            try:
                stale_revalidation_failures = max(
                    0,
                    int(str(refreshed_provider.get("stale_revalidation_failures", "0") or "0").strip() or 0),
                )
            except TypeError:
                stale_revalidation_failures = 0
            except ValueError:
                stale_revalidation_failures = 0
            return LocalModInfo(
                id=base_name,
                name=mod_data["name"],
                filename=filename,
                version=mod_data["version"],
                minecraft_version=mod_data["mc_version"],
                loader_type=mod_data["loader_type"],
                description=mod_data["description"],
                author=mod_data["author"],
                platform=platform,
                platform_id=platform_id,
                platform_slug=platform_slug,
                status=ModStatus.ENABLED if enabled else ModStatus.DISABLED,
                file_path=str(file_path),
                file_size=file_path.stat().st_size,
                current_hash=current_hash,
                hash_algorithm=hash_algorithm,
                resolution_source=str(refreshed_provider.get("resolution_source", "") or "").strip(),
                resolved_at_epoch_ms=str(refreshed_provider.get("resolved_at_epoch_ms", "") or "").strip(),
                provider_lifecycle_state=provider_lifecycle_state,
                stale_revalidation_failures=stale_revalidation_failures,
                next_retry_not_before_epoch_ms=str(
                    refreshed_provider.get("next_retry_not_before_epoch_ms", "") or ""
                ).strip(),
            )
        except (OSError, zipfile.BadZipFile) as exc:
            record_and_mark(
                exc,
                marker_path=file_path,
                reason="io_or_bad_zip",
                details={"context": "create_mod_info_from_file"},
            )
            with contextlib.suppress(Exception):
                self._quarantine_file(file_path, "io_or_bad_zip")
            return None
        except (TypeError, ValueError, KeyError) as exc:
            logger.debug(f"解析模組檔案時遇到格式/型別問題 {file_path}: {exc}")
            return None
        except Exception as exc:
            record_and_mark(
                exc,
                marker_path=file_path,
                reason="unexpected_error",
                details={"context": "create_mod_info_from_file"},
            )
            with contextlib.suppress(Exception):
                self._quarantine_file(file_path, "unexpected_error")
            return None

    @staticmethod
    def parse_file_info(file_path: Path) -> tuple[str, bool, str]:
        """
        從檔案路徑解析出基本的檔案資訊，包括原始檔名、是否啟用（根據副檔名）以及基礎名稱（去除版本和 loader 等資訊）。
        Args:
            file_path: 要解析的檔案路徑。
        Returns:
            包含原始檔名、是否啟用以及基礎名稱的元組。
        """
        filename = file_path.name
        enabled = not filename.endswith(".jar.disabled")
        base_name = filename.removesuffix(".jar.disabled").removesuffix(".jar")
        return (filename, enabled, base_name)

    def get_manifest_version(self, jar: Any) -> str | None:
        """
        嘗試從 JAR 檔案的 MANIFEST.MF 中提取版本資訊，特別是當版本被指定為 ${file.jarVersion} 時。
        Args:
            jar: 已開啟的 zipfile.ZipFile 物件，代表 JAR 檔案。
        Returns:
            從 MANIFEST.MF 中提取的版本字串，如果無法提取或發生錯誤則返回 None。
        """
        try:
            if "META-INF/MANIFEST.MF" in jar.namelist():
                with jar.open("META-INF/MANIFEST.MF") as manifest_file:
                    for line in manifest_file.read().decode(errors="ignore").splitlines():
                        if line.startswith("Implementation-Version:"):
                            version = line.split(":", 1)[1].strip()
                            if version and version != "${projectversion}":
                                return version
        except (zipfile.BadZipFile, OSError) as exc:
            logger.exception(f"讀取 MANIFEST.MF 版本資訊失敗（IO/ZIP）: {exc}")
        return None

    def extract_metadata_from_jar(self, file_path: Path, mod_data: dict[str, str]) -> None:
        """
        嘗試從 JAR 檔案中提取模組元資料，優先考慮 fabric.mod.json、META-INF/mods.toml 和 mcmod.info。

        Args:
            file_path: JAR 檔案的路徑。
            mod_data: 用於存儲提取的元資料的字典，會被直接修改以填充相關資訊。
        """
        try:
            with zipfile.ZipFile(file_path, "r") as jar:
                metadata_extractors = [
                    ("fabric.mod.json", self.extract_fabric_metadata),
                    ("META-INF/mods.toml", self.extract_forge_metadata),
                    ("mcmod.info", self.extract_legacy_forge_metadata),
                ]
                for metadata_file, extractor in metadata_extractors:
                    try:
                        jar.getinfo(metadata_file)
                        extractor(jar, mod_data)
                        break
                    except KeyError:
                        continue
                    except (ValueError, TomlDecodeError) as exc:
                        logger.debug(f"讀取 {metadata_file} 時發生解析錯誤: {exc}")
                    except TypeError as exc:
                        logger.debug(f"讀取 {metadata_file} 時發生型別/編碼錯誤: {exc}")
                    except Exception as exc:
                        with contextlib.suppress(Exception):
                            record_and_mark(
                                exc,
                                marker_path=file_path,
                                reason="extract_metadata_unexpected",
                                details={"metadata_file": metadata_file},
                            )
                        logger.exception(f"讀取 {metadata_file} 時發生未預期錯誤: {exc}")
        except (zipfile.BadZipFile, OSError) as exc:
            record_and_mark(
                exc,
                marker_path=file_path,
                reason="io_or_bad_zip_extract",
                details={"context": "extract_metadata_from_jar"},
            )
            with contextlib.suppress(Exception):
                self._quarantine_file(file_path, "io_or_bad_zip_extract")
        except Exception as exc:
            record_and_mark(
                exc,
                marker_path=file_path,
                reason="unexpected_extract_error",
                details={"context": "extract_metadata_from_jar"},
            )
            with contextlib.suppress(Exception):
                self._quarantine_file(file_path, "unexpected_extract_error")

    def extract_fabric_metadata(self, jar: Any, mod_data: dict[str, str]) -> None:
        """
        從 fabric.mod.json 中提取模組元資料，並更新 mod_data 字典。
        Args:
            jar: 已開啟的 zipfile.ZipFile 物件，代表 JAR 檔案。
            mod_data: 用於存儲提取的元資料的字典，會被直接修改以填充相關資訊。
        """
        try:
            meta = self.read_json_from_jar(jar, "fabric.mod.json")
            if not meta or not isinstance(meta, dict):
                return
            mod_data["name"] = str(meta.get("name", mod_data["name"]) or mod_data["name"])
            mod_data["version"] = self.resolve_version(
                jar, str(meta.get("version", mod_data["version"]) or mod_data["version"])
            )
            mod_data["description"] = str(meta.get("description", mod_data["description"]) or mod_data["description"])
            mod_data["author"] = self.process_authors(meta.get("authors", []))
            mod_data["loader_type"] = "Fabric"
            depends = meta.get("depends", {})
            if isinstance(depends, dict):
                mc_version = depends.get("minecraft", mod_data["mc_version"])
                mod_data["mc_version"] = ServerDetectionVersionUtils.normalize_mc_version(mc_version)
        except (TypeError, ValueError) as exc:
            logger.error(f"無法從 JAR 檔案提取 Fabric 元資料: {exc}", "LocalModScanner")

    def extract_forge_metadata(self, jar: Any, mod_data: dict[str, str]) -> None:
        """從 `mods.toml` 提取 Forge 模組元資料。

        Args:
            jar: 已開啟的 JAR/ZIP 物件。
            mod_data: 會被直接更新的模組元資料字典。
        """

        try:
            meta = self.read_toml_from_jar(jar, "META-INF/mods.toml")
            if not meta or not isinstance(meta, dict):
                return
            modlist = meta.get("mods", [])
            if modlist and isinstance(modlist, list):
                modmeta = modlist[0]
                if isinstance(modmeta, dict):
                    mod_data["name"] = str(modmeta.get("displayName", mod_data["name"]) or mod_data["name"])
                    mod_data["version"] = self.resolve_version(
                        jar,
                        str(modmeta.get("version", mod_data["version"]) or mod_data["version"]),
                    )
                    mod_data["description"] = str(
                        modmeta.get("description", mod_data["description"]) or mod_data["description"]
                    )
                    mod_data["author"] = self.process_authors(modmeta.get("authors", mod_data["author"]))
            mod_data["loader_type"] = "Forge"
            if "dependencies" in meta:
                for dependency_group in meta["dependencies"].values():
                    if isinstance(dependency_group, list):
                        for dependency in dependency_group:
                            if isinstance(dependency, dict) and dependency.get("modId") == "minecraft":
                                mc_version = dependency.get("versionRange", mod_data["mc_version"])
                                mod_data["mc_version"] = ServerDetectionVersionUtils.normalize_mc_version(mc_version)
                                break
        except (KeyError, TomlDecodeError, ValueError) as exc:
            logger.debug(f"解析 Forge 元資料失敗（解析/格式）: {exc}")
        except TypeError as exc:
            logger.debug(f"解析 Forge 元資料失敗（型別/編碼）: {exc}")
        except Exception as exc:
            with contextlib.suppress(Exception):
                record_and_mark(
                    exc,
                    marker_path=None,
                    reason="extract_forge_metadata_unexpected",
                    details={"context": "extract_forge_metadata"},
                )
            logger.exception(f"解析 Forge 元資料時發生未預期錯誤: {exc}")

    def extract_legacy_forge_metadata(self, jar: Any, mod_data: dict[str, str]) -> None:
        """從 `mcmod.info` 提取舊版 Forge 模組元資料。

        Args:
            jar: 已開啟的 JAR/ZIP 物件。
            mod_data: 會被直接更新的模組元資料字典。
        """

        try:
            info = self.read_json_from_jar(jar, "mcmod.info")
            if not info:
                return
            if isinstance(info, list):
                if not info:
                    return
                info = info[0]
            if not isinstance(info, dict):
                return
            mod_data["name"] = str(info.get("name", mod_data["name"]) or mod_data["name"])
            mod_data["version"] = str(info.get("version", mod_data["version"]) or mod_data["version"])
            mod_data["description"] = str(info.get("description", mod_data["description"]) or mod_data["description"])
            authors = info.get("authorList") or info.get("author", mod_data["author"])
            mod_data["author"] = self.process_authors(authors)
            mod_data["mc_version"] = str(info.get("mcversion", mod_data["mc_version"]) or mod_data["mc_version"])
            mod_data["loader_type"] = "Forge"
        except (ValueError, TypeError) as exc:
            logger.debug(f"解析 legacy Forge mcmod.info 失敗（格式/型別）: {exc}")
        except Exception as exc:
            with contextlib.suppress(Exception):
                record_and_mark(
                    exc,
                    marker_path=None,
                    reason="extract_legacy_forge_metadata_unexpected",
                    details={"context": "extract_legacy_forge_metadata"},
                )
            logger.exception(f"解析 legacy Forge mcmod.info 時發生未預期錯誤: {exc}")

    @staticmethod
    def read_json_from_jar(jar: Any, file_path: str) -> dict | list | None:
        """讀取 JAR 內的 JSON 檔案並解析。

        Args:
            jar: 已開啟的 JAR/ZIP 物件。
            file_path: JAR 內的 JSON 檔案路徑。

        Returns:
            解析成功時回傳 dict 或 list，失敗時回傳 None。
        """

        try:
            with jar.open(file_path) as file_obj:
                return PathUtils.from_json_str(file_obj.read().decode("utf-8"))
        except (KeyError, OSError, ValueError) as exc:
            logger.debug(f"讀取 JAR 中的 JSON 失敗 {file_path}: {exc}")
            return None

    @staticmethod
    def read_toml_from_jar(jar: Any, file_path: str) -> dict[str, Any] | None:
        """讀取 JAR 內的 TOML 檔案並解析。

        Args:
            jar: 已開啟的 JAR/ZIP 物件。
            file_path: JAR 內的 TOML 檔案路徑。

        Returns:
            解析成功時回傳 TOML 字典，失敗時回傳 None。
        """

        try:
            with jar.open(file_path) as file_obj:
                toml_txt = file_obj.read().decode(errors="ignore")
                return tomllib.loads(toml_txt)
        except (KeyError, TomlDecodeError) as exc:
            logger.debug(f"讀取 JAR 中的 TOML 失敗 {file_path}: {exc}")
            return None
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug(f"讀取 JAR 中的 TOML 失敗（IO/編碼）{file_path}: {exc}")
            return None
        except Exception as exc:
            with contextlib.suppress(Exception):
                record_and_mark(
                    exc,
                    marker_path=None,
                    reason="read_toml_from_jar_unexpected",
                    details={"file": file_path},
                )
            logger.exception(f"讀取 JAR 中的 TOML 時發生未預期錯誤 {file_path}: {exc}")
            return None

    def resolve_version(self, jar: Any, version: str) -> str:
        """處理需要從 MANIFEST 補齊的版本字串。

        Args:
            jar: 已開啟的 JAR/ZIP 物件。
            version: 原始版本字串。

        Returns:
            已解析的版本字串。
        """

        if version == "${file.jarVersion}":
            manifest_version = self.get_manifest_version(jar)
            return manifest_version if manifest_version else version
        return version

    @staticmethod
    def process_authors(authors: Any) -> str:
        """將作者欄位整理為單一顯示字串。

        Args:
            authors: 原始作者欄位，可能為字串、列表或其他型別。

        Returns:
            整理後的作者字串；無有效資料時回傳空字串。
        """

        if isinstance(authors, list) and authors:
            return ", ".join(
                str(author)
                for author in authors
                if author and str(author).strip().lower() not in ["", "unknown", "author", "example author", "example"]
            )
        if isinstance(authors, str):
            return authors
        return ""

    def apply_fallback_logic(self, base_name: str, mod_data: dict[str, str]) -> None:
        """在 metadata 不完整時以檔名與預設規則補齊欄位。

        Args:
            base_name: 檔名去除副檔名後的基底名稱。
            mod_data: 會被直接更新的模組元資料字典。
        """

        mod_data["author"] = self.clean_author(mod_data["author"])
        if not mod_data["name"] or mod_data["name"] == "未知":
            mod_data["name"] = self.extract_name_from_filename(base_name)
        if not mod_data["version"] or mod_data["version"] == "未知":
            mod_data["version"] = self.extract_version_from_filename(base_name)
        if not mod_data["mc_version"] or str(mod_data["mc_version"]).strip() in {"", "未知"}:
            mod_data["mc_version"] = self.extract_mc_version_from_filename(base_name)
        if mod_data["loader_type"] == "未知":
            mod_data["loader_type"] = ServerDetectionUtils.detect_loader_from_text(base_name)

    @staticmethod
    def extract_name_from_filename(base_name: str) -> str:
        """從檔名推測模組名稱。

        Args:
            base_name: 檔名去除副檔名後的基底名稱。

        Returns:
            推測出的模組名稱。
        """

        clean_base = re.sub(r"(?i)[-_]?(forge|fabric|litemod|mc\d+\.\d+\.\d+|mc\d+\.\d+)", "", base_name)
        clean_base = re.sub(
            r"(?i)[-_]?(api|mod|core|library|lib|addon|additions|compat|integration|essentials|tools|generators|reforged|restored|beta|alpha|snapshot|universal|common|b\d*)$",
            "",
            clean_base,
        )
        clean_base = clean_base.strip("-_")
        parts = clean_base.split("-")
        if len(parts) > 1:
            for index, part in enumerate(parts):
                if any(char.isdigit() for char in part):
                    return "-".join(parts[:index]) if index > 0 else clean_base
            return clean_base
        return clean_base

    @staticmethod
    def extract_version_from_filename(base_name: str) -> str:
        """從檔名推測模組版本字串。

        Args:
            base_name: 檔名去除副檔名後的基底名稱。

        Returns:
            推測出的版本字串；無法判定時回傳 `未知`。
        """

        parts = base_name.split("-")
        if len(parts) > 1:
            for index, part in enumerate(parts):
                if any(char.isdigit() for char in part):
                    version = "-".join(parts[index:])
                    return ServerDetectionUtils.clean_version(version)
        return "未知"

    @staticmethod
    def extract_mc_version_from_filename(base_name: str) -> str:
        """從檔名推測 Minecraft 版本。

        Args:
            base_name: 檔名去除副檔名後的基底名稱。

        Returns:
            推測出的 Minecraft 版本；無法判定時回傳 `未知`。
        """

        patterns = [r"mc(\d+\.\d+\.\d+)", r"(\d+\.\d+\.\d+)", r"mc(\d+\.\d+)", r"(\d+\.\d+)"]
        for pattern in patterns:
            match = re.search(pattern, base_name, re.IGNORECASE)
            if match:
                return match.group(1)
        return "未知"

    def apply_server_config_overrides(self, mod_data: dict[str, str]) -> None:
        """以伺服器設定覆寫缺漏或不可信的模組欄位。

        Args:
            mod_data: 會被直接更新的模組元資料字典。
        """

        if not self.server_config:
            return
        loader_type = getattr(self.server_config, "loader_type", mod_data["loader_type"])
        mc_version_fallback = getattr(self.server_config, "minecraft_version", mod_data["mc_version"])
        if (
            not mod_data["mc_version"]
            or str(mod_data["mc_version"]).strip() in {"", "未知"}
            or not re.match(r"^\d+\.\d+", str(mod_data["mc_version"]))
        ):
            mod_data["mc_version"] = mc_version_fallback
        loader_mapping = {"unknown": "未知", "fabric": "Fabric", "forge": "Forge", "vanilla": "原版"}
        mod_data["loader_type"] = loader_mapping.get(str(loader_type).lower(), loader_type)

    @staticmethod
    def clean_author(author: str) -> str:
        """清理作者欄位中的預設值與無效文字。

        Args:
            author: 原始作者字串。

        Returns:
            清理後的作者字串；無有效內容時回傳空字串。
        """

        if not author:
            return ""
        author = str(author).strip()
        if author.lower() in {"", "unknown", "author", "example author", "example"}:
            return ""
        return author
