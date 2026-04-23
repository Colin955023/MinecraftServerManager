"""模組 provider 解析 helper。"""

from __future__ import annotations

import contextlib
import re
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..utils import (
    HTTPUtils,
    LocalProviderEnsureResult,
    ProviderMetadataRecord,
    cache_provider_metadata_record,
    ensure_local_mod_provider_record,
    get_logger,
    is_cached_provider_metadata_fresh,
    record_and_mark,
    resolve_modrinth_provider_record,
)
from ..version_info import APP_VERSION, GITHUB_OWNER, GITHUB_REPO
from .mod_models import MODRINTH_SEARCH_URL, ModPlatform

logger = get_logger().bind(component="ModProviderResolver")


def resolve_platform_info_from_cache(
    *,
    index_manager: Any,
    file_path: Path,
    name: str,
    cached_provider: dict[str, object] | None,
    ensure_platform_provider_record: Callable[[ProviderMetadataRecord], LocalProviderEnsureResult],
) -> tuple[ModPlatform, str, str]:
    """依快取 provider metadata 解析平台資訊，必要時才重新偵測。

    Args:
        index_manager: 用於快取 provider metadata 的索引管理器。
        file_path: 目前掃描中的模組檔案路徑。
        name: 模組顯示名稱。
        cached_provider: 既有的 provider metadata 快取內容。
        ensure_platform_provider_record: 建立或補齊 provider record 的回呼。

    Returns:
        由平台、project id 與 slug 組成的解析結果。
    """

    raw_cached_provider = dict(cached_provider or {})
    cache_is_fresh = is_cached_provider_metadata_fresh(raw_cached_provider)
    cached_record = ProviderMetadataRecord.from_cached(raw_cached_provider)
    explicit_local_marker = str(raw_cached_provider.get("platform", "") or "").strip().lower() == "local"
    if not cache_is_fresh:
        cached_record = ProviderMetadataRecord.from_values(project_name=cached_record.project_name)
    if explicit_local_marker and (not cached_record.project_id) and (not cached_record.slug):
        return (ModPlatform.LOCAL, "", cached_record.slug)
    ensure_result = ensure_platform_provider_record(cached_record)
    resolved_record = ensure_result.record
    platform = ModPlatform.MODRINTH if resolved_record.project_id else ModPlatform.LOCAL
    platform_id = resolved_record.project_id
    platform_slug = resolved_record.slug
    cache_provider_metadata_record(
        index_manager,
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


def search_on_modrinth_candidates(name: str, base_name: str, filename: str) -> tuple[ModPlatform, str, str]:
    """依多組候選關鍵字搜尋 Modrinth 專案。

    Args:
        name: 模組顯示名稱。
        base_name: 檔名去除副檔名後的基底名稱。
        filename: 原始檔名。

    Returns:
        找到時回傳平台、project id 與 slug；找不到時回傳本地平台與空值。
    """

    try:
        search_keywords: list[str] = []
        if name and name != "未知":
            search_keywords.append(name)
        if base_name and base_name not in search_keywords:
            search_keywords.append(base_name)
        if filename and filename not in search_keywords:
            search_keywords.append(filename)
        for keyword in search_keywords:
            headers = {"User-Agent": f"MinecraftServerManager/{APP_VERSION} (github.com/{GITHUB_OWNER}/{GITHUB_REPO})"}
            data = HTTPUtils.get_json(MODRINTH_SEARCH_URL, timeout=8, headers=headers, params={"query": keyword})
            if data and data.get("hits"):
                hit = data["hits"][0]
                project_id = str(hit.get("project_id", "") or "").strip()
                slug = str(hit.get("slug", "") or project_id).strip()
                return (ModPlatform.MODRINTH, project_id or slug, slug)
    except (ValueError, TypeError) as exc:
        logger.debug(f"Modrinth 搜尋遇到解析/型別錯誤: {exc}")
    except Exception as exc:
        with contextlib.suppress(Exception):
            record_and_mark(
                exc,
                marker_path=None,
                reason="modrinth_search_failed",
                details={"name": name, "base_name": base_name, "filename": filename},
            )
        logger.exception(f"Modrinth 搜尋失敗: {exc}")
    return (ModPlatform.LOCAL, "", "")


class ModProviderResolver:
    """集中管理 provider metadata 與 Modrinth 身分解析。"""

    def __init__(
        self,
        *,
        index_manager: Any,
        modrinth_identity_cache: dict[str, tuple[str, str]],
        read_json_from_jar: Any,
        quarantine_file: Any,
    ) -> None:
        self.index_manager = index_manager
        self._modrinth_identity_cache = modrinth_identity_cache
        self._read_json_from_jar = read_json_from_jar
        self._quarantine_file = quarantine_file

    def resolve_platform_info(
        self,
        file_path: Path,
        name: str,
        base_name: str,
        filename: str,
        cached_provider: dict[str, object] | None = None,
    ) -> tuple[ModPlatform, str, str]:
        """優先使用快取 metadata，必要時再重新解析 provider 身分。

        Args:
            file_path: 目前掃描中的模組檔案路徑。
            name: 模組顯示名稱。
            base_name: 檔名去除副檔名後的基底名稱。
            filename: 原始檔名。
            cached_provider: 現有的 provider metadata 快取內容。

        Returns:
            由平台、project id 與 slug 組成的解析結果。
        """

        return resolve_platform_info_from_cache(
            index_manager=self.index_manager,
            file_path=file_path,
            name=name,
            cached_provider=cached_provider,
            ensure_platform_provider_record=lambda cached_record: self.ensure_platform_provider_record(
                file_path=file_path,
                name=name,
                base_name=base_name,
                filename=filename,
                cached_record=cached_record,
            ),
        )

    def ensure_platform_provider_record(
        self,
        *,
        file_path: Path,
        name: str,
        base_name: str,
        filename: str,
        cached_record: ProviderMetadataRecord,
    ) -> LocalProviderEnsureResult:
        """補齊或建立模組的 provider metadata record。

        Args:
            file_path: 模組檔案路徑。
            name: 模組顯示名稱。
            base_name: 檔名去除副檔名後的基底名稱。
            filename: 原始檔名。
            cached_record: 目前可用的快取 record。

        Returns:
            provider record 補齊結果，包含來源與最終 record。
        """

        return ensure_local_mod_provider_record(
            platform_id=cached_record.project_id,
            platform_slug=cached_record.slug,
            project_name=str(name or "").strip(),
            identifier_resolver=self.resolve_modrinth_provider_record_for_scan,
            fallback_resolver=lambda: self.detect_provider_record(file_path, name, base_name, filename),
        )

    def resolve_modrinth_provider_record_for_scan(self, identifier: str) -> ProviderMetadataRecord:
        """將掃描到的識別字轉成標準化的 Modrinth provider record。

        Args:
            identifier: 可能是 slug 或 project id 的識別字。

        Returns:
            已標準化的 provider record。
        """

        project_id, slug = self.resolve_modrinth_project_identity(identifier)
        return ProviderMetadataRecord.from_values(
            platform=ModPlatform.MODRINTH.value,
            project_id=project_id,
            slug=slug,
        )

    def detect_provider_record(
        self,
        file_path: Path,
        name: str,
        base_name: str,
        filename: str,
    ) -> ProviderMetadataRecord:
        """以 provider 偵測結果建立完整 record。

        Args:
            file_path: 模組檔案路徑。
            name: 模組顯示名稱。
            base_name: 檔名去除副檔名後的基底名稱。
            filename: 原始檔名。

        Returns:
            含平台、project id、slug 與名稱的 provider record。
        """

        platform, platform_id, platform_slug = self.detect_platform_info(file_path, name, base_name, filename)
        return ProviderMetadataRecord.from_values(
            platform=platform.value,
            project_id=platform_id,
            slug=platform_slug,
            project_name=str(name or "").strip(),
        )

    def resolve_modrinth_project_identity(self, identifier: str) -> tuple[str, str]:
        """將 slug 或 project id 解析為 canonical project id 與 slug。

        Args:
            identifier: 可能是 Modrinth slug 或 project id。

        Returns:
            由 canonical project id 與 slug 組成的 tuple。
        """

        clean_identifier = str(identifier or "").strip()
        if not clean_identifier:
            return ("", "")
        cache_key = clean_identifier.lower()
        cached_identity = self._modrinth_identity_cache.get(cache_key)
        if cached_identity is not None:
            return cached_identity
        resolved_record = resolve_modrinth_provider_record(
            clean_identifier,
            search_fallback=self.build_provider_record_from_search,
        )
        resolved = (resolved_record.project_id, resolved_record.slug or clean_identifier)
        self._modrinth_identity_cache[cache_key] = resolved
        return resolved

    def build_provider_record_from_search(self, query: str) -> ProviderMetadataRecord | None:
        """透過搜尋結果建立 provider record。

        Args:
            query: 用於搜尋 Modrinth 的查詢字串。

        Returns:
            成功解析時回傳 provider record，否則回傳 None。
        """

        platform, project_id, slug = self.search_on_modrinth(query, query, query)
        if platform != ModPlatform.MODRINTH or not project_id:
            return None
        return ProviderMetadataRecord.from_values(platform=platform.value, project_id=project_id, slug=slug)

    def detect_platform_info(
        self, file_path: Path, name: str, base_name: str, filename: str
    ) -> tuple[ModPlatform, str, str]:
        """從本地模組檔案與檔名線索偵測平台資訊。

        Args:
            file_path: 模組檔案路徑。
            name: 模組顯示名稱。
            base_name: 檔名去除副檔名後的基底名稱。
            filename: 原始檔名。

        Returns:
            由平台、project id 與 slug 組成的偵測結果。
        """

        platform = ModPlatform.LOCAL
        platform_id = ""
        platform_slug = ""
        try:
            with zipfile.ZipFile(file_path, "r") as jar:
                if "fabric.mod.json" in jar.namelist():
                    platform_slug = self.extract_platform_id_from_fabric(jar)
                elif "META-INF/mods.toml" in jar.namelist():
                    platform_slug = self.extract_platform_id_from_forge(jar)
                if platform_slug:
                    resolved_project_id, resolved_slug = self.resolve_modrinth_project_identity(platform_slug)
                    platform_id = resolved_project_id
                    platform_slug = resolved_slug or platform_slug
                if platform_id:
                    platform = ModPlatform.MODRINTH
        except (zipfile.BadZipFile, OSError) as exc:
            record_and_mark(
                exc,
                marker_path=file_path,
                reason="io_or_bad_zip_detect",
                details={"context": "detect_platform_info"},
            )
            with contextlib.suppress(Exception):
                self._quarantine_file(file_path, "io_or_bad_zip_detect")
        except Exception as exc:
            record_and_mark(
                exc,
                marker_path=file_path,
                reason="unexpected_detect_error",
                details={"context": "detect_platform_info"},
            )
            with contextlib.suppress(Exception):
                self._quarantine_file(file_path, "unexpected_detect_error")
        if platform == ModPlatform.LOCAL or not platform_id:
            platform, platform_id, searched_slug = self.search_on_modrinth(name, base_name, filename)
            platform_slug = searched_slug or platform_slug
        return (platform, platform_id, platform_slug)

    def extract_platform_id_from_fabric(self, jar: Any) -> str:
        """從 `fabric.mod.json` 提取平台識別字。

        Args:
            jar: 已開啟的 JAR/ZIP 物件。

        Returns:
            解析出的平台識別字；失敗時回傳空字串。
        """

        try:
            meta = self._read_json_from_jar(jar, "fabric.mod.json")
            if meta and isinstance(meta, dict):
                return str(meta.get("id", "") or "")
        except Exception as exc:
            with contextlib.suppress(Exception):
                record_and_mark(
                    exc,
                    marker_path=None,
                    reason="extract_platform_id_from_fabric_failed",
                    details={"context": "extract_platform_id_from_fabric"},
                )
            logger.exception(f"解析 fabric.mod.json 取得平台 ID 失敗: {exc}")
        return ""

    def extract_platform_id_from_forge(self, jar: Any) -> str:
        """從 `mods.toml` 提取平台識別字。

        Args:
            jar: 已開啟的 JAR/ZIP 物件。

        Returns:
            解析出的平台識別字；失敗時回傳空字串。
        """

        try:
            with jar.open("META-INF/mods.toml") as file_obj:
                toml_txt = file_obj.read().decode(errors="ignore")
                if "modrinth" in toml_txt.lower():
                    match = re.search(r'(modrinth|project_id)\s*=\s*"([^"]+)"', toml_txt, re.IGNORECASE)
                    if match:
                        return str(match.group(2) or "")
        except Exception as exc:
            with contextlib.suppress(Exception):
                record_and_mark(
                    exc,
                    marker_path=None,
                    reason="extract_platform_id_from_forge_failed",
                    details={"context": "extract_platform_id_from_forge"},
                )
            logger.exception(f"解析 mods.toml 取得平台 ID 失敗: {exc}")
        return ""

    def search_on_modrinth(self, name: str, base_name: str, filename: str) -> tuple[ModPlatform, str, str]:
        """使用多組名稱候選在 Modrinth 搜尋對應專案。

        Args:
            name: 模組顯示名稱。
            base_name: 檔名去除副檔名後的基底名稱。
            filename: 原始檔名。

        Returns:
            找到時回傳平台、project id 與 slug；找不到時回傳本地平台與空值。
        """

        return search_on_modrinth_candidates(name, base_name, filename)
