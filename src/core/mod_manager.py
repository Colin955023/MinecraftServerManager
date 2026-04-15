"""模組管理器
負責管理 Minecraft 伺服器的模組，提供啟用/停用、移除等功能。
"""

import contextlib
import re
import tempfile
import threading
import time
import tomllib
import zipfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

TomlDecodeError = tomllib.TOMLDecodeError
from ..utils import (
    HTTPUtils,
    LocalProviderEnsureResult,
    ModIndexManager,
    PathUtils,
    ProviderMetadataRecord,
    ServerDetectionUtils,
    ServerDetectionVersionUtils,
    UIUtils,
    cache_provider_metadata_record,
    derive_provider_lifecycle_state,
    ensure_local_mod_provider_record,
    get_logger,
    is_cached_provider_metadata_fresh,
    record_and_mark,
    resolve_modrinth_provider_record,
)
from ..version_info import APP_VERSION, GITHUB_OWNER, GITHUB_REPO

logger = get_logger().bind(component="ModManager")
MODRINTH_HASH_ALGORITHM = "sha512"
MODRINTH_SEARCH_URL = "https://api.modrinth.com/v2/search"


class ModStatus(Enum):
    """模組狀態"""

    ENABLED = "enabled"
    DISABLED = "disabled"


class ModPlatform(Enum):
    """模組來源平台"""

    MODRINTH = "modrinth"
    LOCAL = "local"


@dataclass
class LocalModInfo:
    """本地模組資訊"""

    id: str
    name: str
    filename: str
    version: str
    minecraft_version: str
    loader_type: str
    description: str = ""
    author: str = ""
    platform: ModPlatform = ModPlatform.LOCAL
    platform_id: str = ""
    platform_slug: str = ""
    status: ModStatus = ModStatus.ENABLED
    file_path: str = ""
    download_url: str = ""
    homepage_url: str = ""
    dependencies: list[str] | None = None
    file_size: int = 0
    current_hash: str = ""
    hash_algorithm: str = ""
    resolution_source: str = ""
    resolved_at_epoch_ms: str = ""
    provider_lifecycle_state: str = ""
    stale_revalidation_failures: int = 0
    next_retry_not_before_epoch_ms: str = ""

    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []


class ModManager:
    """負責伺服器模組的掃描、啟用/停用、移除等功能"""

    index_manager: ModIndexManager

    def __init__(self, server_path: str, server_config=None) -> None:
        self.server_path = Path(server_path)
        self.mods_path = self.server_path / "mods"
        self.download_staging_root = self.server_path / ".download_staging"
        self.server_config = server_config
        self._modrinth_identity_cache: dict[str, tuple[str, str]] = {}
        self.mods_path.mkdir(parents=True, exist_ok=True)
        self.download_staging_root.mkdir(parents=True, exist_ok=True)
        self.index_manager: ModIndexManager = ModIndexManager(server_path)
        self.on_mod_list_changed: Callable | None = None

    @staticmethod
    def _normalize_expected_hash(expected_hash: str | None) -> tuple[str, str]:
        normalized_hash = str(expected_hash or "").strip().lower()
        if not normalized_hash:
            return ("", "")
        if len(normalized_hash) == 40:
            return (normalized_hash, "sha1")
        if len(normalized_hash) == 64:
            return (normalized_hash, "sha256")
        if len(normalized_hash) == 128:
            return (normalized_hash, "sha512")
        return (normalized_hash, "")

    def scan_mods(self) -> list[LocalModInfo]:
        """掃描 mods 目錄中的模組檔案並建立模組資訊列表。

        Returns:
            掃描後的模組資訊清單。
        """
        self.index_manager.cleanup_stale_entries()
        mods = []
        files_to_scan = []
        for file_path in self.mods_path.glob("*.jar*"):
            if file_path.suffix == ".jar" or file_path.name.endswith(".jar.disabled"):
                files_to_scan.append(file_path)
        files_to_scan.sort(key=lambda path: path.name.lower())
        with ThreadPoolExecutor(max_workers=min(6, len(files_to_scan) or 1)) as executor:
            results = executor.map(self.create_mod_info_from_file, files_to_scan)
        for mod_info in results:
            if mod_info:
                mods.append(mod_info)
        self.index_manager.flush()
        return mods

    def create_mod_info_from_file(self, file_path: Path) -> LocalModInfo | None:
        """依 Prism Launcher 行為，從 jar metadata 取得版本，支援 fallback 與多格式。

        Args:
            file_path: 要解析的模組 JAR 檔案路徑。

        Returns:
            解析成功時回傳 LocalModInfo，失敗時回傳 None。
        """
        try:
            filename, enabled, base_name = self._parse_file_info(file_path)
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
                self._extract_metadata_from_jar(file_path, mod_data)
                self._apply_fallback_logic(base_name, mod_data)
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
            self._apply_server_config_overrides(mod_data)
            platform, platform_id, platform_slug = self._resolve_platform_info(
                file_path, mod_data["name"], base_name, filename, cached_provider
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
                    0, int(str(refreshed_provider.get("stale_revalidation_failures", "0") or "0").strip() or 0)
                )
            except TypeError, ValueError:
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
        except (OSError, zipfile.BadZipFile) as e:
            record_and_mark(
                e, marker_path=file_path, reason="io_or_bad_zip", details={"context": "create_mod_info_from_file"}
            )
            with contextlib.suppress(Exception):
                self._quarantine_file(file_path, "io_or_bad_zip")
            return None
        except (TypeError, ValueError, KeyError) as e:
            logger.debug(f"解析模組檔案時遇到格式/型別問題 {file_path}: {e}")
            return None
        except Exception as e:
            record_and_mark(
                e, marker_path=file_path, reason="unexpected_error", details={"context": "create_mod_info_from_file"}
            )
            with contextlib.suppress(Exception):
                self._quarantine_file(file_path, "unexpected_error")
            return None

    def _resolve_platform_info(
        self,
        file_path: Path,
        name: str,
        base_name: str,
        filename: str,
        cached_provider: dict[str, object] | None = None,
    ) -> tuple[ModPlatform, str, str]:
        """優先使用索引中的 provider metadata，必要時才重新偵測。"""
        raw_cached_provider = dict(cached_provider or {})
        cache_is_fresh = is_cached_provider_metadata_fresh(raw_cached_provider)
        cached_record = ProviderMetadataRecord.from_cached(raw_cached_provider)
        explicit_local_marker = str(raw_cached_provider.get("platform", "") or "").strip().lower() == "local"
        if not cache_is_fresh:
            cached_record = ProviderMetadataRecord.from_values(project_name=cached_record.project_name)
        if explicit_local_marker and (not cached_record.project_id) and (not cached_record.slug):
            return (ModPlatform.LOCAL, "", cached_record.slug)
        ensure_result = self._ensure_platform_provider_record(
            file_path=file_path, name=name, base_name=base_name, filename=filename, cached_record=cached_record
        )
        resolved_record = ensure_result.record
        platform = ModPlatform.MODRINTH if resolved_record.project_id else ModPlatform.LOCAL
        platform_id = resolved_record.project_id
        platform_slug = resolved_record.slug
        cache_provider_metadata_record(
            self.index_manager,
            file_path,
            ProviderMetadataRecord.from_values(
                platform=platform.value,
                project_id=platform_id,
                slug=platform_slug,
                project_name=str(name or "").strip(),
            ),
            metadata_source=str(getattr(ensure_result, "source", "") or "").strip() or "scan_detect",
        )
        return (platform, platform_id, platform_slug)

    def _ensure_platform_provider_record(
        self, *, file_path: Path, name: str, base_name: str, filename: str, cached_record: ProviderMetadataRecord
    ) -> LocalProviderEnsureResult:
        return ensure_local_mod_provider_record(
            platform_id=cached_record.project_id,
            platform_slug=cached_record.slug,
            project_name=str(name or "").strip(),
            identifier_resolver=self._resolve_modrinth_provider_record_for_scan,
            fallback_resolver=lambda: self._detect_provider_record(file_path, name, base_name, filename),
        )

    def _resolve_modrinth_provider_record_for_scan(self, identifier: str) -> ProviderMetadataRecord:
        project_id, slug = self._resolve_modrinth_project_identity(identifier)
        return ProviderMetadataRecord.from_values(platform=ModPlatform.MODRINTH.value, project_id=project_id, slug=slug)

    def _detect_provider_record(
        self, file_path: Path, name: str, base_name: str, filename: str
    ) -> ProviderMetadataRecord:
        platform, platform_id, platform_slug = self._detect_platform_info(file_path, name, base_name, filename)
        return ProviderMetadataRecord.from_values(
            platform=platform.value, project_id=platform_id, slug=platform_slug, project_name=str(name or "").strip()
        )

    def _resolve_modrinth_project_identity(self, identifier: str) -> tuple[str, str]:
        """將 slug 或 project id 轉為 canonical Modrinth project id 與 slug。"""
        clean_identifier = str(identifier or "").strip()
        if not clean_identifier:
            return ("", "")
        cache_key = clean_identifier.lower()
        cached_identity = self._modrinth_identity_cache.get(cache_key)
        if cached_identity is not None:
            return cached_identity
        resolved_record = resolve_modrinth_provider_record(
            clean_identifier, search_fallback=self._build_provider_record_from_search
        )
        resolved = (resolved_record.project_id, resolved_record.slug or clean_identifier)
        self._modrinth_identity_cache[cache_key] = resolved
        return resolved

    def _build_provider_record_from_search(self, query: str) -> ProviderMetadataRecord | None:
        platform, project_id, slug = self._search_on_modrinth(query, query, query)
        if platform != ModPlatform.MODRINTH or not project_id:
            return None
        return ProviderMetadataRecord.from_values(platform=platform.value, project_id=project_id, slug=slug)

    def resolve_modrinth_project_identity(self, identifier: str) -> tuple[str, str]:
        """公開封裝：將使用者輸入的 Modrinth project id / slug 正規化。

        Args:
            identifier: 使用者輸入的 project id 或 slug。

        Returns:
            解析後的 project id 與 slug。
        """
        return self._resolve_modrinth_project_identity(identifier)

    def _parse_file_info(self, file_path: Path) -> tuple[str, bool, str]:
        """解析基本檔案資訊與啟用/停用狀態"""
        filename = file_path.name
        enabled = not filename.endswith(".jar.disabled")
        base_name = filename.removesuffix(".jar.disabled").removesuffix(".jar")
        return (filename, enabled, base_name)

    def _quarantine_file(self, file_path: Path, reason: str) -> None:
        """標記檔案為有問題（不移動），以便 UI/人員檢查後再決定復原或移動。

        會在同一目錄下建立隱藏 marker 檔案 `.{filename}.issue.json`，包含原因與時間戳。
        """
        try:
            marked = PathUtils.mark_issue(file_path, reason)
            if marked:
                logger.info(f"已標記檔案為有問題: {file_path} ({reason})")
            else:
                logger.warning(f"建立檔案問題標記失敗: {file_path} ({reason})")
        except Exception as exc:
            record_and_mark(
                exc,
                marker_path=None,
                reason="mark_issue_failed",
                details={"file": str(file_path), "context": "_quarantine_file", "reason": reason},
            )

    def _get_manifest_version(self, jar) -> str | None:
        """從 MANIFEST.MF 檔案中提取版本資訊"""
        try:
            if "META-INF/MANIFEST.MF" in jar.namelist():
                with jar.open("META-INF/MANIFEST.MF") as mf:
                    for line in mf.read().decode(errors="ignore").splitlines():
                        if line.startswith("Implementation-Version:"):
                            v = line.split(":", 1)[1].strip()
                            if v and v != "${projectversion}":
                                return v
        except (zipfile.BadZipFile, OSError) as e:
            logger.exception(f"讀取 MANIFEST.MF 版本資訊失敗（IO/ZIP）: {e}")
        return None

    def _extract_metadata_from_jar(self, file_path: Path, mod_data: dict) -> None:
        """根據模組載入器類型從 jar 檔案中提取元資料"""
        try:
            with zipfile.ZipFile(file_path, "r") as jar:
                metadata_extractors = [
                    ("fabric.mod.json", self._extract_fabric_metadata),
                    ("META-INF/mods.toml", self._extract_forge_metadata),
                    ("mcmod.info", self._extract_legacy_forge_metadata),
                ]
                for metadata_file, extractor in metadata_extractors:
                    try:
                        jar.getinfo(metadata_file)
                        extractor(jar, mod_data)
                        break
                    except KeyError:
                        continue
                    except (ValueError, TomlDecodeError) as e:
                        logger.debug(f"讀取 {metadata_file} 時發生解析錯誤: {e}")
                        continue
                    except TypeError as e:
                        logger.debug(f"讀取 {metadata_file} 時發生型別/編碼錯誤: {e}")
                        continue
                    except Exception as e:
                        with contextlib.suppress(Exception):
                            record_and_mark(
                                e,
                                marker_path=file_path,
                                reason="extract_metadata_unexpected",
                                details={"metadata_file": metadata_file},
                            )
                        logger.exception(f"讀取 {metadata_file} 時發生未預期錯誤: {e}")
                        continue
        except (zipfile.BadZipFile, OSError) as e:
            record_and_mark(
                e,
                marker_path=file_path,
                reason="io_or_bad_zip_extract",
                details={"context": "_extract_metadata_from_jar"},
            )
            with contextlib.suppress(Exception):
                self._quarantine_file(file_path, "io_or_bad_zip_extract")
        except Exception as e:
            record_and_mark(
                e,
                marker_path=file_path,
                reason="unexpected_extract_error",
                details={"context": "_extract_metadata_from_jar"},
            )
            with contextlib.suppress(Exception):
                self._quarantine_file(file_path, "unexpected_extract_error")

    def _extract_fabric_metadata(self, jar, mod_data: dict) -> None:
        """從 Fabric 模組中提取元資料"""
        try:
            meta = self._read_json_from_jar(jar, "fabric.mod.json")
            if not meta or not isinstance(meta, dict):
                return
            mod_data["name"] = meta.get("name", mod_data["name"])
            mod_data["version"] = self._resolve_version(jar, meta.get("version", mod_data["version"]))
            mod_data["description"] = meta.get("description", mod_data["description"])
            mod_data["author"] = self._process_authors(meta.get("authors", []))
            mod_data["loader_type"] = "Fabric"
            depends = meta.get("depends", {})
            if isinstance(depends, dict):
                mc_version = depends.get("minecraft", mod_data["mc_version"])
                mod_data["mc_version"] = ServerDetectionVersionUtils.normalize_mc_version(mc_version)
        except (TypeError, ValueError) as e:
            logger.error(f"無法從 JAR 檔案提取 Fabric 元資料: {e}", "ModManager")

    def _extract_forge_metadata(self, jar, mod_data: dict) -> None:
        """從 Forge 模組中提取元資料"""
        try:
            meta = self._read_toml_from_jar(jar, "META-INF/mods.toml")
            if not meta or not isinstance(meta, dict):
                return
            modlist = meta.get("mods", [])
            if modlist and isinstance(modlist, list):
                modmeta = modlist[0]
                if not isinstance(modmeta, dict):
                    return
                mod_data["name"] = modmeta.get("displayName", mod_data["name"])
                mod_data["version"] = self._resolve_version(jar, modmeta.get("version", mod_data["version"]))
                mod_data["description"] = modmeta.get("description", mod_data["description"])
                mod_data["author"] = self._process_authors(modmeta.get("authors", mod_data["author"]))
            mod_data["loader_type"] = "Forge"
            if "dependencies" in meta:
                for dep in meta["dependencies"].values():
                    if isinstance(dep, list):
                        for d in dep:
                            if not isinstance(d, dict):
                                continue
                            if d.get("modId") == "minecraft":
                                mc_version = d.get("versionRange", mod_data["mc_version"])
                                mod_data["mc_version"] = ServerDetectionVersionUtils.normalize_mc_version(mc_version)
                                break
        except (KeyError, TomlDecodeError, ValueError) as e:
            logger.debug(f"解析 Forge 元資料失敗（解析/格式）: {e}")
        except TypeError as e:
            logger.debug(f"解析 Forge 元資料失敗（型別/編碼）: {e}")
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(
                    e,
                    marker_path=None,
                    reason="extract_forge_metadata_unexpected",
                    details={"context": "_extract_forge_metadata"},
                )
            logger.exception(f"解析 Forge 元資料時發生未預期錯誤: {e}")

    def _extract_legacy_forge_metadata(self, jar, mod_data: dict) -> None:
        """從舊版 Forge 模組（mcmod.info）提取元資料"""
        try:
            info = self._read_json_from_jar(jar, "mcmod.info")
            if not info:
                return
            if isinstance(info, list):
                if not info:
                    return
                info = info[0]
            if not isinstance(info, dict):
                return
            mod_data["name"] = info.get("name", mod_data["name"])
            mod_data["version"] = info.get("version", mod_data["version"])
            mod_data["description"] = info.get("description", mod_data["description"])
            authors = info.get("authorList") or info.get("author", mod_data["author"])
            mod_data["author"] = self._process_authors(authors)
            mod_data["mc_version"] = info.get("mcversion", mod_data["mc_version"])
            mod_data["loader_type"] = "Forge"
        except (ValueError, TypeError) as e:
            logger.debug(f"解析 legacy Forge mcmod.info 失敗（格式/型別）: {e}")
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(
                    e,
                    marker_path=None,
                    reason="extract_legacy_forge_metadata_unexpected",
                    details={"context": "_extract_legacy_forge_metadata"},
                )
            logger.exception(f"解析 legacy Forge mcmod.info 時發生未預期錯誤: {e}")

    def _read_json_from_jar(self, jar, file_path: str) -> dict | list | None:
        """
        從 JAR 檔案中讀取 JSON"""
        try:
            with jar.open(file_path) as f:
                return PathUtils.from_json_str(f.read().decode("utf-8"))
        except (KeyError, OSError, ValueError) as e:
            logger.debug(f"讀取 JAR 中的 JSON 失敗 {file_path}: {e}")
            return None

    def _read_toml_from_jar(self, jar, file_path: str) -> dict | None:
        """從 JAR 檔案中讀取 TOML"""
        try:
            with jar.open(file_path) as f:
                toml_txt = f.read().decode(errors="ignore")
                return tomllib.loads(toml_txt)
        except (KeyError, TomlDecodeError) as e:
            logger.debug(f"讀取 JAR 中的 TOML 失敗 {file_path}: {e}")
            return None
        except (OSError, UnicodeDecodeError) as e:
            logger.debug(f"讀取 JAR 中的 TOML 失敗（IO/編碼）{file_path}: {e}")
            return None
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(
                    e,
                    marker_path=None,
                    reason="read_toml_from_jar_unexpected",
                    details={"file": file_path},
                )
            logger.exception(f"讀取 JAR 中的 TOML 時發生未預期錯誤 {file_path}: {e}")
            return None

    def _resolve_version(self, jar, version: str) -> str:
        """解析版本號，處理佔位符 ${file.jarVersion}"""
        if version == "${file.jarVersion}":
            manifest_version = self._get_manifest_version(jar)
            return manifest_version if manifest_version else version
        return version

    def _process_authors(self, authors) -> str:
        """處理並清理作者資訊"""
        if isinstance(authors, list) and authors:
            return ", ".join(
                [
                    str(a)
                    for a in authors
                    if a and str(a).strip().lower() not in ["", "unknown", "author", "example author", "example"]
                ]
            )
        if isinstance(authors, str):
            return authors
        return ""

    def _apply_fallback_logic(self, base_name: str, mod_data: dict) -> None:
        """套用後備邏輯來填充模組資料"""
        mod_data["author"] = self._clean_author(mod_data["author"])
        if not mod_data["name"] or mod_data["name"] == "未知":
            mod_data["name"] = self._extract_name_from_filename(base_name)
        if not mod_data["version"] or mod_data["version"] == "未知":
            mod_data["version"] = self._extract_version_from_filename(base_name)
        if not mod_data["mc_version"] or str(mod_data["mc_version"]).strip() in ["", "未知"]:
            mod_data["mc_version"] = self._extract_mc_version_from_filename(base_name)
        if mod_data["loader_type"] == "未知":
            mod_data["loader_type"] = ServerDetectionUtils.detect_loader_from_text(base_name)

    def _extract_name_from_filename(self, base_name: str) -> str:
        """解析檔名以提取模組名稱"""
        clean_base = base_name
        clean_base = re.sub("(?i)[-_]?(forge|fabric|litemod|mc\\d+\\.\\d+\\.\\d+|mc\\d+\\.\\d+)", "", clean_base)
        clean_base = re.sub(
            "(?i)[-_]?(api|mod|core|library|lib|addon|additions|compat|integration|essentials|tools|generators|reforged|restored|beta|alpha|snapshot|universal|common|b\\d*)$",
            "",
            clean_base,
        )
        clean_base = clean_base.strip("-_")
        parts = clean_base.split("-")
        if len(parts) > 1:
            for i, p in enumerate(parts):
                if any(c.isdigit() for c in p):
                    return "-".join(parts[:i]) if i > 0 else clean_base
            return clean_base
        return clean_base

    def _extract_version_from_filename(self, base_name: str) -> str:
        """解析檔名以提取版本"""
        parts = base_name.split("-")
        if len(parts) > 1:
            for i, p in enumerate(parts):
                if any(c.isdigit() for c in p):
                    version = "-".join(parts[i:])
                    return ServerDetectionUtils.clean_version(version)
        return "未知"

    def _extract_mc_version_from_filename(self, base_name: str) -> str:
        """解析檔名以提取 Minecraft 版本"""
        patterns = ["mc(\\d+\\.\\d+\\.\\d+)", "(\\d+\\.\\d+\\.\\d+)", "mc(\\d+\\.\\d+)", "(\\d+\\.\\d+)"]
        for pattern in patterns:
            m = re.search(pattern, base_name, re.IGNORECASE)
            if m:
                return m.group(1)
        return "未知"

    def _apply_server_config_overrides(self, mod_data: dict) -> None:
        """套用伺服器配置覆寫"""
        if not self.server_config:
            return
        loader_type = getattr(self.server_config, "loader_type", mod_data["loader_type"])
        mc_version_fallback = getattr(self.server_config, "minecraft_version", mod_data["mc_version"])
        if (
            not mod_data["mc_version"]
            or str(mod_data["mc_version"]).strip() in ["", "未知"]
            or (not re.match("^\\d+\\.\\d+", str(mod_data["mc_version"])))
        ):
            mod_data["mc_version"] = mc_version_fallback
        loader_mapping = {"unknown": "未知", "fabric": "Fabric", "forge": "Forge", "vanilla": "原版"}
        mod_data["loader_type"] = loader_mapping.get(loader_type.lower(), loader_type)

    def _detect_platform_info(
        self, file_path: Path, name: str, base_name: str, filename: str
    ) -> tuple[ModPlatform, str, str]:
        """從檔案路徑、名稱、基礎名稱和檔案名稱中偵測模組的平台和平台 ID"""
        platform = ModPlatform.LOCAL
        platform_id = ""
        platform_slug = ""
        try:
            with zipfile.ZipFile(file_path, "r") as jar:
                if "fabric.mod.json" in jar.namelist():
                    platform_slug = self._extract_platform_id_from_fabric(jar)
                elif "META-INF/mods.toml" in jar.namelist():
                    platform_slug = self._extract_platform_id_from_forge(jar)
                if platform_slug:
                    resolved_project_id, resolved_slug = self._resolve_modrinth_project_identity(platform_slug)
                    platform_id = resolved_project_id
                    platform_slug = resolved_slug or platform_slug
                if platform_id:
                    platform = ModPlatform.MODRINTH
        except (zipfile.BadZipFile, OSError) as e:
            record_and_mark(
                e, marker_path=file_path, reason="io_or_bad_zip_detect", details={"context": "_detect_platform_info"}
            )
            with contextlib.suppress(Exception):
                self._quarantine_file(file_path, "io_or_bad_zip_detect")
        except Exception as e:
            record_and_mark(
                e, marker_path=file_path, reason="unexpected_detect_error", details={"context": "_detect_platform_info"}
            )
            with contextlib.suppress(Exception):
                self._quarantine_file(file_path, "unexpected_detect_error")
        if platform == ModPlatform.LOCAL or not platform_id:
            platform, platform_id, searched_slug = self._search_on_modrinth(name, base_name, filename)
            platform_slug = searched_slug or platform_slug
        return (platform, platform_id, platform_slug)

    def _extract_platform_id_from_fabric(self, jar) -> str:
        """解析 Fabric 模組元資料以提取平台 ID"""
        try:
            meta = self._read_json_from_jar(jar, "fabric.mod.json")
            if meta and isinstance(meta, dict):
                return meta.get("id", "")
            return ""
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(
                    e,
                    marker_path=None,
                    reason="extract_platform_id_from_fabric_failed",
                    details={"context": "_extract_platform_id_from_fabric"},
                )
            logger.exception(f"解析 fabric.mod.json 取得平台 ID 失敗: {e}")
            return ""

    def _extract_platform_id_from_forge(self, jar) -> str:
        """解析 Forge 模組元資料以提取平台 ID"""
        try:
            with jar.open("META-INF/mods.toml") as f:
                toml_txt = f.read().decode(errors="ignore")
                if "modrinth" in toml_txt.lower():
                    m = re.search('(modrinth|project_id)\\s*=\\s*"([^"]+)"', toml_txt, re.IGNORECASE)
                    if m:
                        return m.group(2)
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(
                    e,
                    marker_path=None,
                    reason="extract_platform_id_from_forge_failed",
                    details={"context": "_extract_platform_id_from_forge"},
                )
            logger.exception(f"解析 mods.toml 取得平台 ID 失敗: {e}")
        return ""

    def _search_on_modrinth(self, name: str, base_name: str, filename: str) -> tuple[ModPlatform, str, str]:
        """在 Modrinth API 上搜索模組"""
        try:
            search_keywords = []
            if name and name != "未知":
                search_keywords.append(name)
            if base_name and base_name not in search_keywords:
                search_keywords.append(base_name)
            if filename and filename not in search_keywords:
                search_keywords.append(filename)
            for keyword in search_keywords:
                headers = {
                    "User-Agent": f"MinecraftServerManager/{APP_VERSION} (github.com/{GITHUB_OWNER}/{GITHUB_REPO})"
                }
                data = HTTPUtils.get_json(MODRINTH_SEARCH_URL, timeout=8, headers=headers, params={"query": keyword})
                if data and data.get("hits"):
                    hit = data["hits"][0]
                    project_id = str(hit.get("project_id", "") or "").strip()
                    slug = str(hit.get("slug", "") or project_id).strip()
                    return (ModPlatform.MODRINTH, project_id or slug, slug)
        except (ValueError, TypeError) as e:
            logger.debug(f"Modrinth 搜尋遇到解析/型別錯誤: {e}")
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(
                    e,
                    marker_path=None,
                    reason="modrinth_search_failed",
                    details={"name": name, "base_name": base_name, "filename": filename},
                )
            logger.exception(f"Modrinth 搜尋失敗: {e}")
        return (ModPlatform.LOCAL, "", "")

    def _clean_author(self, author: str) -> str:
        """清理作者字串"""
        if not author:
            return ""
        author = str(author).strip()
        if author.lower() in ["", "unknown", "author", "example author", "example"]:
            return ""
        return author

    def set_mod_state(self, mod_id: str, enable: bool) -> bool:
        """
        設定模組啟用或停用狀態

        Args:
            mod_id (str):
                模組的識別名稱（不含副檔名），實際檔案名稱將為：
                - 啟用狀態：{mod_id}.jar
                - 停用狀態：{mod_id}.jar.disabled

            enable (bool):
                True  表示啟用模組（移除 .disabled 後綴）
                False 表示停用模組（新增 .disabled 後綴）

        Returns:
            bool:
                True  表示操作成功或模組已在目標狀態
                False 表示操作失敗或發生例外錯誤
        """
        try:
            enabled_file = self.mods_path / f"{mod_id}.jar"
            disabled_file = self.mods_path / f"{mod_id}.jar.disabled"
            if enable:
                src_file = disabled_file
                dst_file = enabled_file
                conflict_bak_suffix = "disabled"
            else:
                src_file = enabled_file
                dst_file = disabled_file
                conflict_bak_suffix = "enabled"
            if dst_file.exists() and (not src_file.exists()):
                return True
            if dst_file.exists() and src_file.exists():
                try:
                    same_size = dst_file.stat().st_size == src_file.stat().st_size
                except OSError:
                    same_size = False
                if same_size:
                    src_file.unlink(missing_ok=True)
                    return True
                bak = self.mods_path / f"{mod_id}.{conflict_bak_suffix}.bak"
                if bak.exists():
                    bak = self.mods_path / f"{mod_id}.{conflict_bak_suffix}.{int(time.time())}.bak"
                src_file.rename(bak)
                return True
            if src_file.exists():
                src_file.rename(dst_file)
                if self.on_mod_list_changed and threading.current_thread() is threading.main_thread():
                    self.on_mod_list_changed()
                return True
            return False
        except (OSError, PermissionError) as e:
            action = "啟用" if enable else "停用"
            logger.error(f"{action}模組失敗（IO/權限）: {e}", "ModManager")
            if threading.current_thread() is threading.main_thread():
                UIUtils.show_error(f"{action}失敗", f"{action}模組失敗: {e}")
            return False
        except Exception as e:
            action = "啟用" if enable else "停用"
            with contextlib.suppress(Exception):
                record_and_mark(
                    e,
                    marker_path=None,
                    reason="set_mod_state_unexpected",
                    details={"mod": mod_id},
                )
            logger.exception(f"{action}模組時發生未預期錯誤: {e}")
            if threading.current_thread() is threading.main_thread():
                UIUtils.show_error(f"{action}失敗", f"{action}模組失敗: {e}")
            return False

    def get_mod_list(self, include_disabled: bool = True) -> list[LocalModInfo]:
        """獲取模組列表"""
        mods = self.scan_mods()
        if include_disabled:
            return mods
        return [mod for mod in mods if mod.status == ModStatus.ENABLED]

    def install_remote_mod_file(
        self,
        download_url: str,
        filename: str,
        progress_callback: Callable[[int, int], None] | None = None,
        expected_hash: str | None = None,
    ) -> Path | None:
        """下載遠端模組檔案並安裝到目前伺服器的 mods 目錄。

        Args:
            download_url: 遠端檔案下載網址。
            filename: 要寫入的檔名。
            progress_callback: 可選的下載進度回呼。
            expected_hash: 可選的預期檔案雜湊，用於下載驗證。

        Returns:
            安裝成功時回傳目標檔案路徑，失敗時回傳 None。
        """
        normalized_url = str(download_url or "").strip()
        normalized_filename = str(filename or "").strip()
        if not normalized_url or not normalized_filename:
            logger.error("安裝遠端模組失敗：download_url 或 filename 為空", "ModManager")
            return None
        safe_filename = Path(normalized_filename).name
        if not safe_filename.lower().endswith(".jar"):
            logger.error(f"安裝遠端模組失敗：不支援的檔案類型 {safe_filename}", "ModManager")
            return None
        try:
            target_path = self.mods_path / safe_filename
            normalized_expected_hash, expected_hash_algorithm = self._normalize_expected_hash(expected_hash)
            if normalized_expected_hash and not expected_hash_algorithm:
                logger.error(
                    f"安裝遠端模組失敗：無法判定雜湊演算法（長度 {len(normalized_expected_hash)}）",
                    "ModManager",
                )
                return None
            if normalized_expected_hash and target_path.exists():
                current_hash = PathUtils.calculate_checksum(target_path, expected_hash_algorithm)
                if current_hash and current_hash == normalized_expected_hash:
                    if progress_callback:
                        try:
                            size = target_path.stat().st_size
                            progress_callback(size, size)
                        except OSError as e:
                            logger.exception(f"更新進度回呼時發生錯誤: {e}")
                    logger.info(f"遠端模組已存在且雜湊一致，略過下載: {safe_filename}", "ModManager")
                    return target_path
            verification_note = f"，含雜湊驗證({expected_hash_algorithm})" if normalized_expected_hash else ""
            logger.info(f"開始下載遠端模組: {safe_filename} -> {target_path}{verification_note}", "ModManager")
            with tempfile.TemporaryDirectory(prefix=f"{safe_filename}.", dir=self.download_staging_root) as staging_dir:
                staging_path = Path(staging_dir) / safe_filename
                download_kwargs: dict[str, Any] = {"progress_callback": progress_callback}
                if normalized_expected_hash:
                    download_kwargs["expected_hash"] = normalized_expected_hash
                downloaded = HTTPUtils.download_file(normalized_url, str(staging_path), **download_kwargs)
                if not downloaded:
                    logger.warning(f"遠端模組下載未完成: {safe_filename}", "ModManager")
                    return None
                if not PathUtils.replace_within(self.server_path, staging_path, target_path):
                    logger.warning(f"遠端模組無法原子寫入目標路徑: {safe_filename}", "ModManager")
                    return None
            if self.on_mod_list_changed and threading.current_thread() is threading.main_thread():
                self.on_mod_list_changed()
            logger.info(f"遠端模組安裝完成: {safe_filename}", "ModManager")
            return target_path
        except (OSError, ValueError) as e:
            logger.exception(f"安裝遠端模組失敗（IO/參數） {safe_filename}: {e}")
            return None
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(
                    e,
                    marker_path=target_path if "target_path" in locals() else None,
                    reason="install_remote_mod_file_unexpected",
                    details={"filename": safe_filename, "url": normalized_url},
                )
            logger.exception(f"安裝遠端模組失敗 {safe_filename}: {e}")
            return None

    def replace_local_mod_file(
        self,
        local_mod: LocalModInfo,
        download_url: str,
        filename: str,
        progress_callback: Callable[[int, int], None] | None = None,
        expected_hash: str | None = None,
    ) -> Path | None:
        """以遠端版本覆蓋本地模組，並盡量保留原本啟用/停用狀態。

        Args:
            local_mod: 目前本地模組資訊。
            download_url: 遠端檔案下載網址。
            filename: 新版本檔名。
            progress_callback: 可選的下載進度回呼。
            expected_hash: 可選的預期檔案雜湊，用於下載驗證。

        Returns:
            更新成功時回傳最終檔案路徑，失敗時回傳 None。
        """
        if local_mod is None:
            logger.error("更新本地模組失敗：local_mod 為空", "ModManager")
            return None
        install_kwargs: dict[str, Any] = {"progress_callback": progress_callback}
        if str(expected_hash or "").strip():
            install_kwargs["expected_hash"] = expected_hash
        installed_path = self.install_remote_mod_file(download_url, filename, **install_kwargs)
        if installed_path is None:
            return None
        final_path = installed_path
        try:
            if local_mod.status == ModStatus.DISABLED and installed_path.suffix == ".jar":
                disabled_path = installed_path.with_name(installed_path.name + ".disabled")
                PathUtils.delete_within(self.server_path, disabled_path)
                installed_path.rename(disabled_path)
                final_path = disabled_path
            old_path_raw = str(getattr(local_mod, "file_path", "") or "").strip()
            old_path = Path(old_path_raw).resolve(strict=False) if old_path_raw else None
            if (
                old_path
                and old_path != final_path.resolve(strict=False)
                and old_path.exists()
                and not PathUtils.delete_within(self.server_path, old_path)
            ):
                logger.warning(f"略過刪除不在伺服器目錄內的舊模組檔案: {old_path}")
            if self.on_mod_list_changed and threading.current_thread() is threading.main_thread():
                self.on_mod_list_changed()
            return final_path
        except (OSError, ValueError) as e:
            logger.exception(f"更新本地模組失敗（IO/參數） {getattr(local_mod, 'filename', 'unknown')}: {e}")
            return None
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(
                    e,
                    marker_path=None,
                    reason="replace_local_mod_file_unexpected",
                    details={"local_mod_filename": getattr(local_mod, "filename", None)},
                )
            logger.exception(f"更新本地模組失敗 {getattr(local_mod, 'filename', 'unknown')}: {e}")
            return None

    def export_mod_list(self, format_type: str = "text") -> str:
        """匯出模組列表，支援 text、json、html 格式。

        Args:
            format_type: 輸出格式，預設為 text。

        Returns:
            依指定格式輸出的模組列表字串；格式不支援時回傳空字串。
        """
        mods = self.get_mod_list()
        if format_type == "text":
            lines = ["# 模組列表", ""]
            for mod in mods:
                status_icon = "✅" if mod.status == ModStatus.ENABLED else "❌"
                line = f"{status_icon} {mod.name} ({mod.version})"
                if mod.author:
                    line += f" - by {mod.author}"
                lines.append(line)
            return "\n".join(lines)
        if format_type == "json":
            export_data = []
            for mod in mods:
                export_data.append(
                    {
                        "name": mod.name,
                        "version": mod.version,
                        "enabled": mod.status == ModStatus.ENABLED,
                        "author": mod.author,
                        "filename": mod.filename,
                        "description": mod.description,
                        "id": mod.id,
                    }
                )
            return PathUtils.to_json_str(export_data, indent=2)
        if format_type == "html":
            html = [
                "<!DOCTYPE html>",
                '<html lang="zh-TW">',
                '<head><meta charset="UTF-8"><title>模組列表</title>',
                "<style>table{border-collapse:collapse;}th,td{border:1px solid silver;padding:6px;}th{background:whitesmoke;}</style>",
                "</head><body>",
                "<h2>模組列表</h2>",
                "<table>",
                "<tr><th>啟用</th><th>名稱</th><th>版本</th><th>作者</th><th>描述</th></tr>",
            ]
            for mod in mods:
                html.append(
                    f"<tr><td>{('✅' if mod.status == ModStatus.ENABLED else '❌')}</td><td>{mod.name}</td><td>{mod.version}</td><td>{mod.author}</td><td>{mod.description}</td></tr>"
                )
            html.append("</table></body></html>")
            return "\n".join(html)
        return ""
