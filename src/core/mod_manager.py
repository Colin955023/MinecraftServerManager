"""模組管理器
負責管理 Minecraft 伺服器的模組，提供啟用/停用、移除等功能。
"""

import contextlib
import re
import tomllib
import zipfile
from collections.abc import Callable
from pathlib import Path

TomlDecodeError = tomllib.TOMLDecodeError
from ..utils import (
    LocalProviderEnsureResult,
    ModIndexManager,
    PathUtils,
    ProviderMetadataRecord,
    ServerDetectionUtils,
    ServerDetectionVersionUtils,
    ensure_local_mod_provider_record,
    get_logger,
    record_and_mark,
)
from .local_mod_scanner import LocalModScanner
from .mod_file_installer import ModFileInstaller
from .mod_models import (
    LocalModInfo,
    LocalModMutationResult,
    ModFileOperationResult,
    ModPlatform,
    ModStatus,
)
from .mod_provider_resolver import (
    ModProviderResolver,
    resolve_platform_info_from_cache,
    search_on_modrinth_candidates,
)

logger = get_logger().bind(component="ModManager")


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
        self._local_mod_scanner: LocalModScanner | None = None
        self._mod_file_installer: ModFileInstaller | None = None
        self._provider_resolver: ModProviderResolver | None = None

    def _get_local_mod_scanner(self) -> LocalModScanner:
        """延後建立本地模組掃描器，讓 `ModManager` 保持 orchestration 角色。"""
        scanner = getattr(self, "_local_mod_scanner", None)
        if scanner is None:
            scanner = LocalModScanner(
                index_manager=self.index_manager,
                mods_path=self.mods_path,
                server_config=self.server_config,
                resolve_platform_info=self._resolve_platform_info,
                quarantine_file=self._quarantine_file,
            )
            self._local_mod_scanner = scanner
        return scanner

    def _get_mod_file_installer(self) -> ModFileInstaller:
        """延後建立檔案安裝器，並同步最新的 UI 通知回呼。"""
        installer = getattr(self, "_mod_file_installer", None)
        if installer is None:
            installer = ModFileInstaller(
                server_path=self.server_path,
                mods_path=self.mods_path,
                download_staging_root=self.download_staging_root,
                on_mod_list_changed=self.on_mod_list_changed,
                logger=logger,
            )
            self._mod_file_installer = installer
        installer.on_mod_list_changed = self.on_mod_list_changed
        return installer

    def _get_provider_resolver(self) -> ModProviderResolver:
        """延後建立 provider 解析器，避免 `__new__` 測試案例需要完整初始化。"""
        resolver = getattr(self, "_provider_resolver", None)
        if resolver is None:
            resolver = ModProviderResolver(
                index_manager=self.index_manager,
                modrinth_identity_cache=self._modrinth_identity_cache,
                read_json_from_jar=self._read_json_from_jar,
                quarantine_file=self._quarantine_file,
            )
            self._provider_resolver = resolver
        return resolver

    @staticmethod
    def _success_mutation_result(
        message: str = "",
        *,
        final_path: Path | None = None,
        affected_count: int = 0,
    ) -> LocalModMutationResult:
        """建立成功的本地模組異動結果。"""
        return LocalModMutationResult(
            status="completed", message=message, final_path=final_path, affected_count=affected_count
        )

    @staticmethod
    def _failure_mutation_result(
        title: str,
        message: str,
        *,
        missing_ids: tuple[str, ...] = (),
    ) -> LocalModMutationResult:
        """建立失敗的本地模組異動結果。"""
        return LocalModMutationResult(status="failed", title=title, message=message, missing_ids=missing_ids)

    @staticmethod
    def _normalize_expected_hash(expected_hash: str | None) -> tuple[str, str]:
        return ModFileInstaller.normalize_expected_hash(expected_hash)

    @staticmethod
    def _is_operation_cancelled(cancel_check: Callable[[], bool] | None) -> bool:
        if cancel_check is None:
            return False
        try:
            return bool(cancel_check())
        except Exception as e:
            logger.exception(f"取消檢查回呼失敗: {e}")
            return False

    def _restore_backup_to_path(self, original_path: Path | None, backup_path: Path | None) -> bool:
        return self._get_mod_file_installer().restore_backup_to_path(original_path, backup_path)

    def _rollback_replaced_mod_file(
        self,
        *,
        old_path: Path | None,
        installed_path: Path | None,
        final_path: Path | None,
        backup_path: Path | None,
        cancelled: bool,
        operation_name: str,
    ) -> ModFileOperationResult:
        return self._get_mod_file_installer().rollback_replaced_mod_file(
            old_path=old_path,
            installed_path=installed_path,
            final_path=final_path,
            backup_path=backup_path,
            cancelled=cancelled,
            operation_name=operation_name,
        )

    def _install_remote_mod_file_result(
        self,
        download_url: str,
        filename: str,
        progress_callback: Callable[[int, int], None] | None = None,
        expected_hash: str | None = None,
        *,
        provider: str | None = "modrinth",
        cancel_check: Callable[[], bool] | None = None,
        notify_change: bool = True,
    ) -> ModFileOperationResult:
        return self._get_mod_file_installer().install_remote_mod_file_result(
            download_url=download_url,
            filename=filename,
            progress_callback=progress_callback,
            expected_hash=expected_hash,
            provider=provider,
            cancel_check=cancel_check,
            notify_change=notify_change,
        )

    def scan_mods(self) -> list[LocalModInfo]:
        """掃描 mods 目錄中的模組檔案並建立模組資訊列表。

        Returns:
            掃描後的模組資訊清單。
        """
        return self._get_local_mod_scanner().scan_mods(self.create_mod_info_from_file)

    def create_mod_info_from_file(self, file_path: Path) -> LocalModInfo | None:
        """依 Prism Launcher 行為，從 jar metadata 取得版本，支援 fallback 與多格式。

        Args:
            file_path: 要解析的模組 JAR 檔案路徑。

        Returns:
            解析成功時回傳 LocalModInfo，失敗時回傳 None。
        """
        return self._get_local_mod_scanner().create_mod_info_from_file(file_path)

    def _resolve_platform_info(
        self,
        file_path: Path,
        name: str,
        base_name: str,
        filename: str,
        cached_provider: dict[str, object] | None = None,
    ) -> tuple[ModPlatform, str, str]:
        """優先使用索引中的 provider metadata，必要時才重新偵測。"""
        return resolve_platform_info_from_cache(
            index_manager=self.index_manager,
            file_path=file_path,
            name=name,
            cached_provider=cached_provider,
            ensure_platform_provider_record=lambda cached_record: self._ensure_platform_provider_record(
                file_path=file_path,
                name=name,
                base_name=base_name,
                filename=filename,
                cached_record=cached_record,
            ),
        )

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
        return self._get_provider_resolver().resolve_modrinth_project_identity(identifier)

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
        return self._get_provider_resolver().detect_platform_info(file_path, name, base_name, filename)

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
        return search_on_modrinth_candidates(name, base_name, filename)

    def _clean_author(self, author: str) -> str:
        """清理作者字串"""
        if not author:
            return ""
        author = str(author).strip()
        if author.lower() in ["", "unknown", "author", "example author", "example"]:
            return ""
        return author

    def set_mod_state_result(self, mod_id: str, enable: bool) -> LocalModMutationResult:
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
            本地模組異動結果。
        """
        return self._get_mod_file_installer().set_mod_state_result(mod_id, enable)

    def set_mod_state(self, mod_id: str, enable: bool) -> bool:
        """設定模組啟用或停用狀態。"""
        return self.set_mod_state_result(mod_id, enable).completed

    def import_local_mod_file_result(self, source_path: str | Path) -> LocalModMutationResult:
        """匯入本地模組檔案到目前伺服器的 mods 目錄。

        Args:
            source_path: 要匯入的本地模組檔案路徑。

        Returns:
            匯入流程結果，供 UI 或呼叫端判斷成功與失敗原因。
        """

        return self._get_mod_file_installer().import_local_mod_file_result(source_path)

    def import_local_mod_file(self, source_path: str | Path) -> Path | None:
        """匯入本地模組檔案。

        Args:
            source_path: 要匯入的本地模組檔案路徑。

        Returns:
            匯入成功時回傳最終檔案路徑，失敗時回傳 None。
        """

        result = self.import_local_mod_file_result(source_path)
        return result.final_path if result.completed else None

    def delete_local_mods_result(self, mod_ids: list[str] | tuple[str, ...]) -> LocalModMutationResult:
        """刪除一或多個本地模組檔案。

        Args:
            mod_ids: 要刪除的模組識別值列表。

        Returns:
            刪除流程結果，包含成功數量與缺失模組資訊。
        """

        return self._get_mod_file_installer().delete_local_mods_result(mod_ids)

    def delete_local_mods(self, mod_ids: list[str] | tuple[str, ...]) -> bool:
        """刪除一或多個本地模組檔案。

        Args:
            mod_ids: 要刪除的模組識別值列表。

        Returns:
            全部刪除成功時回傳 True，否則回傳 False。
        """

        return self.delete_local_mods_result(mod_ids).completed

    def get_mod_list(self, include_disabled: bool = True) -> list[LocalModInfo]:
        """獲取模組列表"""
        mods = self.scan_mods()
        if include_disabled:
            return mods
        return [mod for mod in mods if mod.status == ModStatus.ENABLED]

    def install_remote_mod_file(
        self,
        *,
        download_url: str,
        filename: str,
        progress_callback: Callable[[int, int], None] | None = None,
        provider: str | None = "modrinth",
        expected_hash: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path | None:
        """
        下載遠端模組檔案並安裝到目前伺服器的 mods 目錄。

        Args:
            download_url: 遠端檔案下載網址。
            filename: 要寫入的檔名。
            progress_callback: 可選的下載進度回呼。
            expected_hash: 預期檔案雜湊，需為 SHA-256 或 SHA-512；若缺少則拒絕下載。

        Returns:
            安裝成功時回傳目標檔案路徑，失敗時回傳 None。
        """
        result = self._install_remote_mod_file_result(
            download_url=download_url,
            filename=filename,
            progress_callback=progress_callback,
            expected_hash=expected_hash,
            provider=provider,
            cancel_check=cancel_check,
        )
        return result.final_path if result.completed else None

    def replace_local_mod_file(
        self,
        local_mod: LocalModInfo,
        download_url: str,
        filename: str,
        progress_callback: Callable[[int, int], None] | None = None,
        expected_hash: str | None = None,
        *,
        provider: str | None = "modrinth",
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path | None:
        """
        以遠端版本覆蓋本地模組，並盡量保留原本啟用/停用狀態。

        Args:
            local_mod: 目前本地模組資訊。
            download_url: 遠端檔案下載網址。
            filename: 新版本檔名。
            progress_callback: 可選的下載進度回呼。
            expected_hash: 預期檔案雜湊，需為 SHA-256 或 SHA-512；若缺少則拒絕下載。

        Returns:
            更新成功時回傳最終檔案路徑，失敗時回傳 None。
        """
        return self._get_mod_file_installer().replace_local_mod_file(
            local_mod=local_mod,
            download_url=download_url,
            filename=filename,
            install_remote_mod_file_result=self._install_remote_mod_file_result,
            progress_callback=progress_callback,
            expected_hash=expected_hash,
            provider=provider,
            cancel_check=cancel_check,
        )

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
