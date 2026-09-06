"""本地模組掃描與 metadata 解析 helper"""

from __future__ import annotations

import os
import re
import stat
import tomllib
import zipfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

import orjson

from src.models import (
    LocalModInfo,
    ModPlatform,
    ModStatus,
)
from src.utils import (
    ARCHIVE_METADATA_MAX_BYTES,
    MODRINTH_PREFERRED_HASH_ALGORITHM,
    SAFE_HASH_FILE_MAX_BYTES,
    clean_mod_version,
    detect_loader_from_text,
    get_logger,
    list_bounded_directory,
    normalize_minecraft_version,
    open_bounded_zip,
    open_regular_file,
    read_archive_metadata_bytes,
)

from .mod_index_persistence import ModIndexPersistence
from .provider_identity import ProviderIdentityService

logger = get_logger().bind(component="LocalModScanner")
_LOCAL_MOD_SCAN_BATCH_SIZE = 32


class LocalModScanner:
    """掃描 mods 目錄並建立 LocalModInfo"""

    def __init__(
        self,
        *,
        index_manager: ModIndexPersistence,
        mods_path: Path,
        server_config: Any,
        provider_identity_service: ProviderIdentityService,
        quarantine_file: Callable[[Path, str], None],
    ) -> None:
        self.index_manager = index_manager
        self.mods_path = mods_path
        self.server_config = server_config
        self._provider_identity_service = provider_identity_service
        self._quarantine_file = quarantine_file

    @staticmethod
    def parse_file_info(file_path: Path) -> tuple[str, bool, str]:
        """
        從檔案路徑解析出基本的檔案資訊，包括原始檔名、是否啟用（根據副檔名）以及基礎名稱（去除版本和 loader 等資訊）

        Args:
            file_path: 要解析的檔案路徑

        Returns:
            包含原始檔名、是否啟用以及基礎名稱的元組
        """
        filename = file_path.name
        enabled = not filename.endswith(".jar.disabled")
        base_name = filename.removesuffix(".jar.disabled").removesuffix(".jar")
        return (filename, enabled, base_name)

    @staticmethod
    def read_json_from_jar(
        jar: Any, file_path: str, *, max_bytes: int = ARCHIVE_METADATA_MAX_BYTES
    ) -> dict | list | None:
        """
        讀取 JAR 內的 JSON 檔案並解析

        Args:
            jar: 已開啟的 JAR/ZIP 物件
            file_path: JAR 內的 JSON 檔案路徑
            max_bytes: 最大允許讀取的位元組數

        Returns:
            解析成功時回傳 dict 或 list，失敗時回傳 None
        """

        try:
            payload = read_archive_metadata_bytes(jar, file_path, max_bytes=max_bytes)
            if payload is None:
                return None
            return orjson.loads(payload)
        except KeyError, OSError, ValueError:
            return None

    @staticmethod
    def read_toml_from_jar(
        jar: Any, file_path: str, *, max_bytes: int = ARCHIVE_METADATA_MAX_BYTES
    ) -> dict[str, Any] | None:
        """
        讀取 JAR 內的 TOML 檔案並解析

        Args:
            jar: 已開啟的 JAR/ZIP 物件
            file_path: JAR 內的 TOML 檔案路徑
            max_bytes: 最大允許讀取的位元組數

        Returns:
            解析成功時回傳 TOML 字典，失敗時回傳 None
        """

        try:
            payload = read_archive_metadata_bytes(jar, file_path, max_bytes=max_bytes)
            if payload is None:
                return None
            return tomllib.loads(payload.decode("utf-8"))
        except KeyError, tomllib.TOMLDecodeError, OSError, UnicodeDecodeError:
            return None
        except Exception as e:
            logger.debug(f"讀取 JAR 中的 TOML 時發生非預期錯誤 {file_path}: {e}")
            return None

    @staticmethod
    def process_authors(authors: Any) -> str:
        """
        將作者欄位整理為單一顯示字串

        Args:
            authors: 原始作者欄位，可能為字串、列表或其他型別

        Returns:
            整理後的作者字串；無有效資料時回傳空字串
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

    @staticmethod
    def extract_name_from_filename(base_name: str) -> str:
        """
        從檔名推測模組名稱

        Args:
            base_name: 檔名去除副檔名後的基底名稱

        Returns:
            推測出的模組名稱
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
        """
        從檔名推測模組版本字串

        Args:
            base_name: 檔名去除副檔名後的基底名稱

        Returns:
            推測出的版本字串；無法判定時回傳"未知"
        """

        parts = base_name.split("-")
        if len(parts) > 1:
            for index, part in enumerate(parts):
                if any(char.isdigit() for char in part):
                    version = "-".join(parts[index:])
                    return clean_mod_version(version)
        return "未知"

    @staticmethod
    def extract_mc_version_from_filename(base_name: str) -> str:
        """
        從檔名推測 Minecraft 版本

        Args:
            base_name: 檔名去除副檔名後的基底名稱

        Returns:
            推測出的 Minecraft 版本；無法判定時回傳"未知"
        """

        patterns = [r"mc(\d+\.\d+\.\d+)", r"(\d+\.\d+\.\d+)", r"mc(\d+\.\d+)", r"(\d+\.\d+)"]
        for pattern in patterns:
            match = re.search(pattern, base_name, re.IGNORECASE)
            if match:
                return match.group(1)
        return "未知"

    @staticmethod
    def clean_author(author: str) -> str:
        """
        清理作者欄位中的預設值與無效文字

        Args:
            author: 原始作者字串

        Returns:
            清理後的作者字串；無有效內容時回傳空字串
        """

        if not author:
            return ""
        author = str(author).strip()
        if author.lower() in {"", "unknown", "author", "example author", "example"}:
            return ""
        return author

    def scan_mods(self) -> list[LocalModInfo]:
        """
        掃描 mods 目錄，對每個檔案呼叫 create_mod_info_from_file 以建立 LocalModInfo

        Returns:
            LocalModInfo 物件的列表
        """
        self.index_manager.cleanup_stale_entries()
        mods: list[LocalModInfo] = []
        try:
            directory_entries = list_bounded_directory(self.mods_path)
        except OSError:
            directory_entries = []
        files_to_scan = [
            file_path
            for file_path in directory_entries
            if file_path.is_file() and (file_path.suffix == ".jar" or file_path.name.endswith(".jar.disabled"))
        ]
        files_to_scan.sort(key=lambda path: path.name.lower())
        for index, file_path in enumerate(files_to_scan, start=1):
            mod_info = self.create_mod_info_from_file(file_path)
            if mod_info:
                mods.append(mod_info)
            if index % _LOCAL_MOD_SCAN_BATCH_SIZE == 0:
                self.index_manager.flush()
        self.index_manager.flush()
        return mods

    def create_mod_info_from_file(self, file_path: Path) -> LocalModInfo | None:
        """
        從指定的檔案建立 LocalModInfo 物件

        Args:
            file_path: 要處理的模組檔案的路徑

        Returns:
            若檔案無法處理或發生錯誤時回傳 None，否則回傳 LocalModInfo 物件
        """
        try:
            with open_regular_file(file_path) as source:
                if os.fstat(source.fileno()).st_size > SAFE_HASH_FILE_MAX_BYTES:
                    return None
            file_stat = file_path.stat(follow_symlinks=False)
            if not stat.S_ISREG(file_stat.st_mode):
                return None
            filename, enabled, base_name = self.parse_file_info(file_path)
            mod_data = {
                "name": base_name,
                "version": "未知",
                "author": "",
                "description": "",
                "loader_type": "未知",
                "mc_version": "未知",
            }
            cached_metadata = self.index_manager.get_cached_metadata(file_path)
            cached_name = str(cached_metadata.get("name", "") or "").strip() if cached_metadata else ""
            if cached_metadata and cached_name:
                mod_data.update(cached_metadata)
            else:
                archive_readable = self.extract_metadata_from_jar(file_path, mod_data)
                self.apply_fallback_logic(base_name, mod_data)
                self.index_manager.cache_metadata(
                    file_path,
                    {
                        "name": mod_data["name"],
                        "version": mod_data["version"],
                        "author": mod_data["author"],
                        "description": mod_data["description"],
                        "loader_type": mod_data["loader_type"],
                        "mc_version": mod_data["mc_version"],
                    },
                    clear_issue=archive_readable,
                )
            self.apply_server_config_overrides(mod_data)
            identity = self._provider_identity_service.load(file_path)
            platform = ModPlatform.MODRINTH if identity.canonical else ModPlatform.LOCAL
            platform_id = identity.project_id if identity.canonical else ""
            platform_slug = identity.alias
            current_hash = ""
            hash_algorithm = ""
            if platform == ModPlatform.MODRINTH and platform_id:
                current_hash = self.index_manager.ensure_cached_hash(file_path, MODRINTH_PREFERRED_HASH_ALGORITHM)
                hash_algorithm = MODRINTH_PREFERRED_HASH_ALGORITHM if current_hash else ""
            mod_info = LocalModInfo(
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
                file_size=file_stat.st_size,
                file_mtime=file_stat.st_mtime,
                current_hash=current_hash,
                hash_algorithm=hash_algorithm,
                provider_identity=identity,
            )
            self._provider_identity_service.project(mod_info, identity)
            return mod_info
        except (OSError, zipfile.BadZipFile) as e:
            logger.warning(f"解析模組檔案失敗（檔案損毀或 IO 錯誤）: {file_path} - {e}")
            with suppress(Exception):
                self._quarantine_file(file_path, "io_or_bad_zip")
            return None
        except TypeError, ValueError, KeyError:
            return None
        except Exception as e:
            logger.warning(f"提取模組 metadata 時發生未預期錯誤: {file_path} - {e}")
            with suppress(Exception):
                self._quarantine_file(file_path, "unexpected_error")
            return None

    def get_manifest_version(self, jar: Any) -> str | None:
        """
        嘗試從 JAR 檔案的 MANIFEST.MF 中提取版本資訊，特別是當版本被指定為 ${file.jarVersion} 時

        Args:
            jar: 已開啟的 zipfile.ZipFile 物件，代表 JAR 檔案

        Returns:
            從 MANIFEST.MF 中提取的版本字串，如果無法提取或發生錯誤則回傳 None
        """
        try:
            payload = read_archive_metadata_bytes(jar, "META-INF/MANIFEST.MF")
            if payload is not None:
                for line in payload.decode(errors="ignore").splitlines():
                    if line.startswith("Implementation-Version:"):
                        version = line.split(":", 1)[1].strip()
                        if version and version != "${projectversion}":
                            return version
        except (zipfile.BadZipFile, OSError) as e:
            logger.exception(f"讀取 MANIFEST.MF 版本資訊失敗（IO/ZIP）: {e}")
        return None

    def extract_metadata_from_jar(self, file_path: Path, mod_data: dict[str, str]) -> bool:
        """
        嘗試從 JAR 檔案中提取模組 metadata，優先考慮 fabric.mod.json、META-INF/mods.toml 和 mcmod.info

        Args:
            file_path: JAR 檔案的路徑
            mod_data: 用於儲存提取的 metadata 的字典，會被直接修改以填充相關資訊

        Returns:
            JAR 可正常開啟並完成檢查時回傳 True，檔案損毀或讀取失敗時回傳 False
        """
        try:
            with open_bounded_zip(file_path) as jar:
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
                    except Exception as e:
                        logger.exception(f"讀取 {metadata_file} 時發生未預期錯誤: {e}")
            return True
        except (zipfile.BadZipFile, OSError) as e:
            logger.exception(f"提取模組 metadata 失敗: {file_path}\n{e}")
            with suppress(Exception):
                self._quarantine_file(file_path, "io_or_bad_zip_extract")
            return False
        except Exception as e:
            logger.exception(f"提取模組 metadata 時發生未預期錯誤: {file_path}\n{e}")
            with suppress(Exception):
                self._quarantine_file(file_path, "unexpected_extract_error")
            return False

    def extract_fabric_metadata(self, jar: Any, mod_data: dict[str, str]) -> None:
        """
        從 fabric.mod.json 中提取模組 metadata，並更新 mod_data 字典

        Args:
            jar: 已開啟的 zipfile.ZipFile 物件，代表 JAR 檔案
            mod_data: 用於儲存提取的 metadata 的字典，會被直接修改以填充相關資訊
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
                mod_data["mc_version"] = normalize_minecraft_version(mc_version)
        except (TypeError, ValueError) as e:
            logger.exception(f"無法從 JAR 檔案提取 Fabric metadata: {e}")

    def extract_forge_metadata(self, jar: Any, mod_data: dict[str, str]) -> None:
        """
        從 mods.toml 提取 Forge 模組 metadata

        Args:
            jar: 已開啟的 JAR/ZIP 物件
            mod_data: 會被直接更新的模組 metadata 字典
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
                                mod_data["mc_version"] = normalize_minecraft_version(mc_version)
                                break
        except Exception as e:
            logger.exception(f"解析 Forge metadata 時發生未預期錯誤: {e}")

    def extract_legacy_forge_metadata(self, jar: Any, mod_data: dict[str, str]) -> None:
        """
        從 mcmod.info 提取舊版 Forge 模組 metadata

        Args:
            jar: 已開啟的 JAR/ZIP 物件
            mod_data: 會被直接更新的模組 metadata 字典
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
        except Exception as e:
            logger.exception(f"解析 legacy Forge mcmod.info 時發生未預期錯誤: {e}")

    def resolve_version(self, jar: Any, version: str) -> str:
        """
        處理需要從 MANIFEST 補齊的版本字串

        Args:
            jar: 已開啟的 JAR/ZIP 物件
            version: 原始版本字串

        Returns:
            已解析的版本字串
        """

        if version == "${file.jarVersion}":
            manifest_version = self.get_manifest_version(jar)
            return manifest_version if manifest_version else version
        return version

    def apply_fallback_logic(self, base_name: str, mod_data: dict[str, str]) -> None:
        """
        在 metadata 不完整時以檔名與預設規則補齊欄位

        Args:
            base_name: 檔名去除副檔名後的基底名稱
            mod_data: 會被直接更新的模組 metadata 字典
        """

        mod_data["author"] = self.clean_author(mod_data["author"])
        if not mod_data["name"] or mod_data["name"] == "未知":
            mod_data["name"] = self.extract_name_from_filename(base_name)
        if not mod_data["version"] or mod_data["version"] == "未知":
            mod_data["version"] = self.extract_version_from_filename(base_name)
        if not mod_data["mc_version"] or str(mod_data["mc_version"]).strip() in {"", "未知"}:
            mod_data["mc_version"] = self.extract_mc_version_from_filename(base_name)
        if mod_data["loader_type"] == "未知":
            mod_data["loader_type"] = detect_loader_from_text(base_name)

    def apply_server_config_overrides(self, mod_data: dict[str, str]) -> None:
        """
        以伺服器設定覆寫缺漏或不可信的模組欄位

        Args:
            mod_data: 會被直接更新的模組 metadata 字典
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


__all__ = ["LocalModScanner"]
