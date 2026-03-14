#!/usr/bin/env python3
"""Mod 查詢服務
提供 Modrinth 線上模組搜尋、版本查詢與本地模組資訊增強。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from src.version_info import APP_VERSION, GITHUB_OWNER, GITHUB_REPO

from ..utils import HTTPUtils, PathUtils, get_logger

logger = get_logger().bind(component="ModSearchService")

MODRINTH_SEARCH_URL = "https://api.modrinth.com/v2/search"
MODRINTH_PROJECT_URL = "https://modrinth.com/mod"
MODRINTH_PROJECT_BATCH_URL = "https://api.modrinth.com/v2/projects"
MODRINTH_PROJECT_DETAIL_URL_TEMPLATE = "https://api.modrinth.com/v2/project/{project_id}"
MODRINTH_VERSION_URL_TEMPLATE = "https://api.modrinth.com/v2/project/{project_id}/version"
MODRINTH_VERSION_DETAIL_URL_TEMPLATE = "https://api.modrinth.com/v2/version/{version_id}"
MODRINTH_VERSION_FILES_URL = "https://api.modrinth.com/v2/version_files"
MODRINTH_VERSION_FILES_UPDATE_URL = "https://api.modrinth.com/v2/version_files/update"
MODRINTH_SEARCH_TIMEOUT_SECONDS = 15
MODRINTH_VERSION_TIMEOUT_SECONDS = 15
MODRINTH_PROJECT_BATCH_TIMEOUT_SECONDS = 12
MODRINTH_PROJECT_DETAIL_TIMEOUT_SECONDS = 12
MODRINTH_VERSION_DETAIL_TIMEOUT_SECONDS = 12
MODRINTH_VERSION_FILES_TIMEOUT_SECONDS = 20
MODRINTH_PREFERRED_HASH_ALGORITHM = "sha512"
MIN_ACCEPTABLE_LOCAL_MOD_SEARCH_SCORE = 70
SUPPORTED_SORT_OPTIONS = {"relevance", "downloads", "newest", "updated", "follows"}
LOCAL_HASH_MAX_WORKERS = 4


@dataclass(slots=True)
class OnlineModVersion:
    """Modrinth 上單一模組版本資訊。"""

    version_id: str
    version_number: str
    display_name: str
    game_versions: list[str] = field(default_factory=list)
    loaders: list[str] = field(default_factory=list)
    version_type: str = ""
    date_published: str = ""
    changelog: str = ""
    provider: str = "modrinth"
    files: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[dict[str, Any]] = field(default_factory=list)

    @property
    def primary_file(self) -> dict[str, Any] | None:
        return select_primary_file(self.files)


@dataclass(slots=True)
class OnlineModInfo:
    """線上模組資訊。"""

    project_id: str
    slug: str
    name: str
    author: str
    description: str = ""
    latest_version: str = ""
    download_count: int = 0
    icon_url: str = ""
    homepage_url: str = ""
    url: str = ""
    categories: list[str] = field(default_factory=list)
    versions: list[str] = field(default_factory=list)
    server_side: str = ""
    client_side: str = ""
    source: str = "modrinth"
    available: bool = True


@dataclass(slots=True)
class OnlineModCompatibilityReport:
    """安裝前版本相容性與依賴分析結果。"""

    hard_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    missing_required_dependencies: list[str] = field(default_factory=list)
    optional_dependencies: list[str] = field(default_factory=list)
    incompatible_installed: list[str] = field(default_factory=list)
    installed_version_mismatches: list[str] = field(default_factory=list)
    embedded_dependencies: list[str] = field(default_factory=list)
    already_installed: list[str] = field(default_factory=list)

    @property
    def compatible(self) -> bool:
        return not self.hard_errors


@dataclass(slots=True)
class OnlineDependencyInstallItem:
    """必要依賴的自動安裝項目。"""

    project_id: str
    project_name: str
    version_id: str
    version_name: str
    filename: str
    download_url: str
    parent_name: str = ""
    maybe_installed: bool = False
    status_note: str = ""
    resolution_source: str = "project_id"
    resolution_confidence: str = "direct"
    enabled: bool = True
    is_optional: bool = False


@dataclass(slots=True)
class OnlineDependencyInstallPlan:
    """必要依賴的連鎖安裝計畫。"""

    items: list[OnlineDependencyInstallItem] = field(default_factory=list)
    advisory_items: list[OnlineDependencyInstallItem] = field(default_factory=list)
    unresolved_required: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def auto_install_count(self) -> int:
        return len(self.items)

    @property
    def has_unresolved_required(self) -> bool:
        return bool(self.unresolved_required)


@dataclass(slots=True)
class LocalMetadataEnsureSummary:
    """本地模組 metadata ensure / 專案識別摘要。"""

    total_scanned: int = 0
    resolved_by_hash: int = 0
    resolved_by_cached_project: int = 0
    resolved_by_lookup: int = 0
    unresolved: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def resolved_count(self) -> int:
        return self.resolved_by_hash + self.resolved_by_cached_project + self.resolved_by_lookup


@dataclass(slots=True)
class LocalModUpdateCandidate:
    """本地模組更新檢查結果。"""

    project_id: str
    project_name: str
    filename: str
    current_version: str
    target_version_id: str = ""
    target_version_name: str = ""
    target_version: OnlineModVersion | None = None
    target_filename: str = ""
    download_url: str = ""
    current_hash: str = ""
    hash_algorithm: str = MODRINTH_PREFERRED_HASH_ALGORITHM
    target_file_hash: str = ""
    current_issues: list[str] = field(default_factory=list)
    dependency_issues: list[str] = field(default_factory=list)
    hard_errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    metadata_source: str = ""
    metadata_note: str = ""
    metadata_resolved: bool = True
    server_side: str = ""
    client_side: str = ""
    report: OnlineModCompatibilityReport | None = None
    local_mod: Any = None

    @property
    def update_available(self) -> bool:
        if not self.target_version_id:
            return False
        if self.current_hash and self.target_file_hash:
            return self.current_hash != self.target_file_hash
        return _normalize_identifier(self.current_version) != _normalize_identifier(self.target_version_name)

    @property
    def actionable(self) -> bool:
        return self.update_available and not self.hard_errors and bool(self.download_url and self.target_filename)

    @property
    def has_issues(self) -> bool:
        return bool(self.current_issues or self.dependency_issues or self.hard_errors)


@dataclass(slots=True)
class LocalModUpdatePlan:
    """本地模組更新檢查彙總。"""

    candidates: list[LocalModUpdateCandidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    metadata_summary: LocalMetadataEnsureSummary = field(default_factory=LocalMetadataEnsureSummary)

    @property
    def has_candidates(self) -> bool:
        return bool(self.candidates)

    @property
    def actionable_count(self) -> int:
        return sum(1 for candidate in self.candidates if candidate.actionable)


@dataclass(slots=True)
class ResolvedDependencyReference:
    """解析後的依賴資訊，支援 project_id 與 version_id 兩種來源。"""

    project_id: str = ""
    project_name: str = ""
    version_id: str = ""
    version_name: str = ""
    file_name: str = ""
    version: OnlineModVersion | None = None
    resolution_source: str = "project_id"
    resolution_confidence: str = "direct"

    @property
    def label(self) -> str:
        if self.project_name:
            base = self.project_name
        elif self.project_id:
            base = f"未知模組（project id: {self.project_id}）"
        elif self.file_name:
            base = self.file_name
        elif self.version_id:
            base = f"未知模組（version id: {self.version_id}）"
        else:
            base = "未知依賴"

        if self.version_name:
            return f"{base}（需求版本：{self.version_name}）"
        return base

    @property
    def compare_project_id(self) -> str:
        return _normalize_identifier(self.project_id)


@dataclass(slots=True)
class ModrinthVersionLookupResult:
    """以雜湊查詢 Modrinth 版本後的結果。"""

    file_hash: str
    algorithm: str
    project_id: str
    version: OnlineModVersion


def _build_headers() -> dict[str, str]:
    return {"User-Agent": f"MinecraftServerManager/{APP_VERSION} (github.com/{GITHUB_OWNER}/{GITHUB_REPO})"}


def _normalize_sort(sort_by: str) -> str:
    if sort_by in SUPPORTED_SORT_OPTIONS:
        return sort_by
    if sort_by == "name":
        return "relevance"
    return "relevance"


def _normalize_local_loader(loader: str | None) -> str:
    normalized_loader = _normalize_identifier(loader)
    if normalized_loader in {"fabric", "forge"}:
        return normalized_loader
    if normalized_loader in {"vanilla", "原版"}:
        return "vanilla"
    return normalized_loader


def _expand_target_loader_aliases(loader: str | None, minecraft_version: str | None = None) -> set[str]:
    normalized_loader = _normalize_local_loader(loader)
    if not normalized_loader:
        return set()

    compatible_loaders = {normalized_loader}
    normalized_minecraft_version = _normalize_identifier(minecraft_version)

    if normalized_loader == "quilt":
        compatible_loaders.add("fabric")
    if normalized_loader == "neoforge" and normalized_minecraft_version == "1.20.1":
        compatible_loaders.add("forge")

    return compatible_loaders


def _get_modrinth_loader_filters(loader: str | None, minecraft_version: str | None = None) -> list[str]:
    """回傳 Modrinth 查詢用 loader 過濾列表（含 Prism 風格 loader alias 擴展）。"""
    normalized_loader = _normalize_identifier(loader)
    if not normalized_loader:
        return []

    ordered_loaders: list[str] = [normalized_loader]
    for alias_loader in sorted(_expand_target_loader_aliases(loader, minecraft_version)):
        if alias_loader not in ordered_loaders:
            ordered_loaders.append(alias_loader)
    return ordered_loaders


MODRINTH_LOADER_DEPENDENCY_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("qvIfYCYJ", "P7dR8mSH"),  # Quilt API -> Fabric API
    ("lwVhp9o5", "Ha28R6CL"),  # Quilt Standard Libraries -> Fabric Standard Libraries
)


def _apply_loader_specific_dependency_override(project_id: str | None, loader: str | None) -> str:
    clean_project_id = _clean_api_identifier(project_id)
    normalized_project_id = _normalize_identifier(clean_project_id)
    normalized_loader = _normalize_identifier(loader)
    if not clean_project_id or normalized_loader != "fabric":
        return clean_project_id

    for quilt_project_id, fabric_project_id in MODRINTH_LOADER_DEPENDENCY_OVERRIDES:
        if normalized_project_id == _normalize_identifier(quilt_project_id):
            return fabric_project_id

    return clean_project_id


def _normalize_identifier(value: str | None) -> str:
    return str(value or "").strip().lower()


def _clean_api_identifier(value: str | None) -> str:
    return str(value or "").strip()


def _normalize_hash_algorithm(algorithm: str | None) -> str:
    normalized = _normalize_identifier(algorithm)
    if normalized in {"sha512", "sha1"}:
        return normalized
    return MODRINTH_PREFERRED_HASH_ALGORITHM


def _split_camel_case_words(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return re.sub(
        r"(?<=[A-Z])(?=[A-Z][a-z])",
        " ",
        re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", normalized),
    )


def _canonical_lookup_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _compute_file_hash(file_path: str | None, algorithm: str = MODRINTH_PREFERRED_HASH_ALGORITHM) -> str:
    normalized_algorithm = _normalize_hash_algorithm(algorithm)
    normalized_path = str(file_path or "").strip()
    if not normalized_path:
        return ""

    try:
        hasher = hashlib.new(normalized_algorithm)
    except ValueError:
        return ""

    try:
        with open(normalized_path, "rb") as mod_file:
            for chunk in iter(lambda: mod_file.read(1024 * 1024), b""):
                if not chunk:
                    break
                hasher.update(chunk)
    except OSError as e:
        logger.warning(f"計算模組檔案雜湊失敗 {normalized_path}: {e}")
        return ""

    return hasher.hexdigest()


def _extract_primary_file_hash(
    version: OnlineModVersion | None, algorithm: str = MODRINTH_PREFERRED_HASH_ALGORITHM
) -> str:
    primary_file = getattr(version, "primary_file", None) or {}
    hashes = primary_file.get("hashes", {}) if isinstance(primary_file, dict) else {}
    if not isinstance(hashes, dict):
        return ""
    return str(hashes.get(_normalize_hash_algorithm(algorithm), "") or "").strip().lower()


def normalize_mod_search_query(raw_query: str) -> str:
    """將檔名/雜訊字串轉為較適合 Modrinth 搜尋的關鍵字。"""
    normalized = _split_camel_case_words(raw_query)
    if not normalized:
        return ""

    normalized = normalized.removesuffix(".jar.disabled").removesuffix(".jar")
    normalized = normalized.replace("_", " ").replace("-", " ")
    normalized = re.sub(r"(?i)\b(?:fabric|forge|loader)\b", " ", normalized)
    normalized = re.sub(r"(?i)\bmc\s*\d+(?:\.\d+){1,2}[a-z0-9.-]*\b", " ", normalized)
    normalized = re.sub(r"\b\d+(?:\.\d+){1,3}[a-z0-9.-]*\b", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip() or str(raw_query or "").strip()


def _build_local_mod_lookup_candidates(
    filename: str,
    *,
    platform_id: str | None = None,
    platform_slug: str | None = None,
    local_name: str | None = None,
) -> tuple[list[str], list[str], set[str]]:
    filename_stem = filename.replace(".jar.disabled", "").replace(".jar", "")
    raw_candidates = [
        str(platform_id or "").strip(),
        str(platform_slug or "").strip(),
        str(local_name or "").strip(),
        filename_stem.strip(),
    ]

    exact_identifiers: list[str] = []
    search_terms: list[str] = []
    candidate_keys: set[str] = set()

    for raw_candidate in raw_candidates:
        if not raw_candidate:
            continue

        clean_candidate = _clean_api_identifier(raw_candidate)
        if clean_candidate and clean_candidate not in exact_identifiers:
            exact_identifiers.append(clean_candidate)

        normalized_search = normalize_mod_search_query(raw_candidate)
        if normalized_search and normalized_search not in search_terms:
            search_terms.append(normalized_search)

        slug_candidate = re.sub(r"[^a-z0-9]+", "-", normalized_search.lower()).strip("-") if normalized_search else ""
        if slug_candidate and slug_candidate not in exact_identifiers:
            exact_identifiers.append(slug_candidate)

        for candidate_value in (raw_candidate, normalized_search, slug_candidate):
            candidate_key = _canonical_lookup_key(candidate_value)
            if candidate_key:
                candidate_keys.add(candidate_key)

    return exact_identifiers, search_terms, candidate_keys


def _score_local_mod_search_match(mod: OnlineModInfo, candidate_keys: set[str]) -> int:
    mod_keys = {
        _canonical_lookup_key(mod.project_id),
        _canonical_lookup_key(mod.slug),
        _canonical_lookup_key(mod.name),
    }
    mod_keys.discard("")
    if not mod_keys:
        return 0

    if candidate_keys & mod_keys:
        return 100

    for candidate_key in candidate_keys:
        if not candidate_key:
            continue
        for mod_key in mod_keys:
            if candidate_key in mod_key or mod_key in candidate_key:
                return 70
    return 10


def _normalize_filename_stem(value: str | None) -> str:
    filename = str(value or "").strip().lower()
    if filename.endswith(".jar.disabled"):
        filename = filename.removesuffix(".jar.disabled")
    elif filename.endswith(".jar"):
        filename = filename.removesuffix(".jar")
    return filename


def _normalize_lax_filename(value: str | None, *, exclude_digits: bool = False) -> str:
    normalized = _normalize_filename_stem(value)
    if not normalized:
        return ""

    allowed_pattern = r"[-+._0-9]" if exclude_digits else r"[-+._]"
    normalized = re.sub(allowed_pattern, " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _dependency_candidate_filenames(resolved_dependency: ResolvedDependencyReference) -> list[str]:
    candidates = [resolved_dependency.file_name]
    if resolved_dependency.version is not None and resolved_dependency.version.primary_file is not None:
        candidates.append(str(resolved_dependency.version.primary_file.get("filename", "") or "").strip())
    return [candidate for candidate in candidates if str(candidate or "").strip()]


def _dependency_maybe_installed_by_filename(
    resolved_dependency: ResolvedDependencyReference,
    installed_mods: list[Any] | None,
) -> bool:
    dependency_names = {
        _normalize_lax_filename(candidate, exclude_digits=True)
        for candidate in _dependency_candidate_filenames(resolved_dependency)
        if _normalize_lax_filename(candidate, exclude_digits=True)
    }
    if not dependency_names:
        return False

    for mod in installed_mods or []:
        installed_name = _normalize_lax_filename(getattr(mod, "filename", ""), exclude_digits=True)
        if installed_name and installed_name in dependency_names:
            return True
    return False


def _collect_installed_mod_identifiers(installed_mods: list[Any] | None) -> tuple[set[str], set[str]]:
    installed_project_ids: set[str] = set()
    installed_identifiers: set[str] = set()

    for mod in installed_mods or []:
        platform_id = _normalize_identifier(getattr(mod, "platform_id", ""))
        if platform_id:
            installed_project_ids.add(platform_id)
            installed_identifiers.add(platform_id)

        for raw_value in (
            getattr(mod, "id", ""),
            getattr(mod, "name", ""),
            getattr(mod, "filename", ""),
        ):
            normalized_value = _normalize_identifier(raw_value)
            if normalized_value:
                installed_identifiers.add(normalized_value)

        stem = _normalize_filename_stem(getattr(mod, "filename", ""))
        if stem:
            installed_identifiers.add(stem)

    return installed_project_ids, installed_identifiers


def _collect_installed_mod_versions(installed_mods: list[Any] | None) -> dict[str, set[str]]:
    versions_by_project: dict[str, set[str]] = {}
    for mod in installed_mods or []:
        project_id = _normalize_identifier(getattr(mod, "platform_id", ""))
        version = _normalize_identifier(getattr(mod, "version", ""))
        if not project_id or not version:
            continue
        versions_by_project.setdefault(project_id, set()).add(version)
    return versions_by_project


def _parse_modrinth_version(item: dict[str, Any]) -> OnlineModVersion:
    game_versions = [str(v) for v in item.get("game_versions", []) if v]
    loaders = [str(v) for v in item.get("loaders", []) if v]
    version_number = str(item.get("version_number", "") or "")
    display_name = version_number or str(item.get("name", "未知版本") or "未知版本")
    return OnlineModVersion(
        version_id=str(item.get("id", "") or ""),
        version_number=version_number,
        display_name=display_name,
        game_versions=game_versions,
        loaders=loaders,
        version_type=str(item.get("version_type", "") or ""),
        date_published=str(item.get("date_published", "") or ""),
        changelog=str(item.get("changelog", "") or item.get("body", "") or ""),
        provider="modrinth",
        files=list(item.get("files", []) or []),
        dependencies=list(item.get("dependencies", []) or []),
    )


def _parse_modrinth_version_lookup_response(
    response: dict[str, Any] | None,
    algorithm: str,
) -> dict[str, ModrinthVersionLookupResult]:
    normalized_algorithm = _normalize_hash_algorithm(algorithm)
    if not isinstance(response, dict):
        return {}

    resolved: dict[str, ModrinthVersionLookupResult] = {}
    for file_hash, raw_item in response.items():
        normalized_hash = str(file_hash or "").strip().lower()
        if not normalized_hash or not isinstance(raw_item, dict):
            continue
        project_id = _clean_api_identifier(str(raw_item.get("project_id", "") or ""))
        version = _parse_modrinth_version(raw_item)
        resolved[normalized_hash] = ModrinthVersionLookupResult(
            file_hash=normalized_hash,
            algorithm=normalized_algorithm,
            project_id=project_id,
            version=version,
        )
    return resolved


def get_modrinth_current_versions_by_hashes(
    hashes: list[str] | set[str] | tuple[str, ...],
    algorithm: str = MODRINTH_PREFERRED_HASH_ALGORITHM,
) -> dict[str, ModrinthVersionLookupResult]:
    normalized_hashes = [str(file_hash or "").strip().lower() for file_hash in hashes if str(file_hash or "").strip()]
    if not normalized_hashes:
        return {}

    response = HTTPUtils.post_json(
        url=MODRINTH_VERSION_FILES_URL,
        headers=_build_headers(),
        json_body={"hashes": normalized_hashes, "algorithm": _normalize_hash_algorithm(algorithm)},
        timeout=MODRINTH_VERSION_FILES_TIMEOUT_SECONDS,
    )
    return _parse_modrinth_version_lookup_response(response if isinstance(response, dict) else None, algorithm)


def get_modrinth_latest_versions_by_hashes(
    hashes: list[str] | set[str] | tuple[str, ...],
    algorithm: str = MODRINTH_PREFERRED_HASH_ALGORITHM,
    minecraft_version: str | None = None,
    loader: str | None = None,
) -> dict[str, ModrinthVersionLookupResult]:
    normalized_hashes = [str(file_hash or "").strip().lower() for file_hash in hashes if str(file_hash or "").strip()]
    if not normalized_hashes:
        return {}

    json_body: dict[str, Any] = {
        "hashes": normalized_hashes,
        "algorithm": _normalize_hash_algorithm(algorithm),
    }
    if minecraft_version:
        json_body["game_versions"] = [str(minecraft_version).strip()]
    loader_filters = _get_modrinth_loader_filters(loader, minecraft_version)
    if loader_filters:
        json_body["loaders"] = loader_filters

    response = HTTPUtils.post_json(
        url=MODRINTH_VERSION_FILES_UPDATE_URL,
        headers=_build_headers(),
        json_body=json_body,
        timeout=MODRINTH_VERSION_FILES_TIMEOUT_SECONDS,
    )
    return _parse_modrinth_version_lookup_response(response if isinstance(response, dict) else None, algorithm)


def _format_dependency_label(dependency: dict[str, Any], dependency_names: dict[str, str]) -> str:
    project_id = _clean_api_identifier(str(dependency.get("project_id", "") or ""))
    project_key = _normalize_identifier(project_id)
    version_id = _clean_api_identifier(str(dependency.get("version_id", "") or ""))
    file_name = str(dependency.get("file_name", "") or dependency.get("filename", "") or "").strip()
    if project_id:
        resolved_name = dependency_names.get(project_key, "").strip()
        return resolved_name or f"未知模組（project id: {project_id}）"
    if file_name:
        return file_name
    if version_id:
        return f"版本 {version_id}"
    return "未知依賴"


def _version_type_priority(version_type: str) -> int:
    normalized = _normalize_identifier(version_type)
    if normalized == "release":
        return 3
    if normalized in {"beta", "snapshot"}:
        return 2
    if normalized == "alpha":
        return 1
    return 0


def _is_release_version_type(version_type: str) -> bool:
    normalized = _normalize_identifier(version_type)
    if normalized in {"", "release", "stable"}:
        return True
    for marker in ("alpha", "beta", "snapshot", "pre", "prerelease", "rc"):
        if marker in normalized:
            return False
    return False


def _select_best_mod_version(versions: list[OnlineModVersion]) -> OnlineModVersion | None:
    if not versions:
        return None
    return max(
        versions,
        key=lambda version: (
            1 if version.primary_file else 0,
            _version_type_priority(version.version_type),
            str(version.date_published or ""),
            str(version.version_number or ""),
        ),
    )


def _fetch_modrinth_project_detail(project_id: str) -> dict[str, Any] | None:
    clean_project_id = _clean_api_identifier(project_id)
    if not clean_project_id:
        return None

    response = HTTPUtils.get_json(
        url=MODRINTH_PROJECT_DETAIL_URL_TEMPLATE.format(project_id=clean_project_id),
        headers=_build_headers(),
        timeout=MODRINTH_PROJECT_DETAIL_TIMEOUT_SECONDS,
        suppress_status_codes={404},
    )
    if not isinstance(response, dict):
        return None
    return response


def resolve_local_mod_project_info(local_mod: Any) -> OnlineModInfo | None:
    """盡量將本地模組對應到可用的 Modrinth 專案資訊。"""
    return enhance_local_mod(
        str(getattr(local_mod, "filename", "") or "").strip(),
        platform_id=str(getattr(local_mod, "platform_id", "") or "").strip(),
        platform_slug=str(getattr(local_mod, "platform_slug", "") or "").strip(),
        local_name=str(getattr(local_mod, "name", "") or "").strip(),
    )


def get_modrinth_project_info(project_id: str) -> OnlineModInfo | None:
    """依 project id 或 slug 取得單一 Modrinth 專案資訊。"""
    response = _fetch_modrinth_project_detail(project_id)
    if not response:
        return None

    slug = str(response.get("slug", "") or "").strip()
    resolved_project_id = _clean_api_identifier(str(response.get("id", "") or project_id))
    project_slug = slug or resolved_project_id
    url = f"{MODRINTH_PROJECT_URL}/{project_slug}" if project_slug else MODRINTH_PROJECT_URL
    categories = [str(category) for category in response.get("categories", []) if category]
    additional_categories = [str(category) for category in response.get("additional_categories", []) if category]
    homepage_url = str(
        response.get("website_url", "") or response.get("source_url", "") or response.get("issues_url", "") or url
    ).strip()

    return OnlineModInfo(
        project_id=resolved_project_id,
        slug=project_slug,
        name=str(response.get("title", "") or response.get("name", "") or project_slug or resolved_project_id),
        author=str(response.get("author", "") or "").strip(),
        description=str(response.get("description", "") or "").strip(),
        latest_version="",
        download_count=int(response.get("downloads", 0) or 0),
        icon_url=str(response.get("icon_url", "") or "").strip(),
        homepage_url=homepage_url or url,
        url=url,
        categories=[*categories, *[category for category in additional_categories if category not in categories]],
        versions=[str(version) for version in response.get("versions", []) if version],
        server_side=str(response.get("server_side", "") or "").strip(),
        client_side=str(response.get("client_side", "") or "").strip(),
    )


def _fetch_modrinth_project_name(project_id: str) -> str | None:
    response = _fetch_modrinth_project_detail(project_id)
    if not response:
        return None
    resolved_name = str(
        response.get("title", "")
        or response.get("name", "")
        or response.get("slug", "")
        or _clean_api_identifier(project_id)
    ).strip()
    return resolved_name or None


def get_mod_version_details(version_id: str) -> tuple[str, OnlineModVersion | None]:
    """依 Modrinth version id 取得精確版本資訊，並回傳其所屬 project id。"""
    clean_version_id = _clean_api_identifier(version_id)
    if not clean_version_id:
        return "", None

    response = HTTPUtils.get_json(
        url=MODRINTH_VERSION_DETAIL_URL_TEMPLATE.format(version_id=clean_version_id),
        headers=_build_headers(),
        timeout=MODRINTH_VERSION_DETAIL_TIMEOUT_SECONDS,
    )
    if not isinstance(response, dict):
        logger.error(f"取得 Modrinth 版本詳細資訊失敗: {clean_version_id}")
        return "", None

    project_id = _clean_api_identifier(str(response.get("project_id", "") or ""))
    return project_id, _parse_modrinth_version(response)


def _resolve_dependency_reference(
    dependency: dict[str, Any],
    dependency_names: dict[str, str],
    *,
    loader: str | None = None,
    version_details_cache: dict[str, tuple[str, OnlineModVersion | None]] | None = None,
) -> ResolvedDependencyReference:
    resolved = ResolvedDependencyReference(
        project_id=_clean_api_identifier(str(dependency.get("project_id", "") or "")),
        version_id=_clean_api_identifier(str(dependency.get("version_id", "") or "")),
        file_name=str(dependency.get("file_name", "") or dependency.get("filename", "") or "").strip(),
        resolution_source="project_id" if str(dependency.get("project_id", "") or "").strip() else "version_id",
        resolution_confidence="direct" if str(dependency.get("project_id", "") or "").strip() else "fallback",
    )

    if resolved.version_id:
        cache = version_details_cache if version_details_cache is not None else {}
        if resolved.version_id not in cache:
            cache[resolved.version_id] = get_mod_version_details(resolved.version_id)
        version_project_id, version_details = cache.get(resolved.version_id, ("", None))
        if version_details is not None:
            resolved.version = version_details
            resolved.version_name = str(version_details.display_name or version_details.version_number or "").strip()
        if not resolved.project_id and version_project_id:
            resolved.project_id = version_project_id
            resolved.resolution_source = "version_detail"
            resolved.resolution_confidence = "fallback"

    overridden_project_id = _apply_loader_specific_dependency_override(resolved.project_id, loader)
    if overridden_project_id and _normalize_identifier(overridden_project_id) != resolved.compare_project_id:
        resolved.project_id = overridden_project_id
        resolved.project_name = ""
        resolved.version_id = ""
        resolved.version_name = ""
        resolved.version = None
        resolved.resolution_source = "loader_override"
        resolved.resolution_confidence = "fallback"

    if resolved.project_id:
        resolved.project_name = dependency_names.get(resolved.compare_project_id, "").strip()
        if not resolved.project_name:
            fetched_name = _fetch_modrinth_project_name(resolved.project_id)
            if fetched_name:
                dependency_names[resolved.compare_project_id] = fetched_name
                resolved.project_name = fetched_name

    return resolved


def _check_loader_version_rule(
    minecraft_version: str | None,
    loader: str | None,
    loader_version: str | None,
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    notes: list[str] = []

    normalized_minecraft_version = str(minecraft_version or "").strip()
    normalized_loader = _normalize_identifier(loader)
    normalized_loader_version = _normalize_identifier(loader_version)
    if not normalized_minecraft_version or not normalized_loader or not normalized_loader_version:
        return warnings, notes

    try:
        from ..core.loader_manager import LoaderManager

        compatible_versions = LoaderManager().get_compatible_loader_versions(
            normalized_minecraft_version, normalized_loader
        )
    except Exception as e:
        logger.warning(f"讀取 {normalized_loader} 載入器規則失敗: {e}")
        return warnings, notes

    available_versions = {_normalize_identifier(version.version) for version in compatible_versions if version.version}
    if not available_versions:
        notes.append(
            f"目前找不到 {normalized_loader} 對 Minecraft {normalized_minecraft_version} 的本地規則快取，因此無法額外驗證 loader 版本 {loader_version}。"
        )
        return warnings, notes

    if normalized_loader_version in available_versions:
        notes.append(
            f"已使用內建 {normalized_loader.capitalize()} 規則確認 loader 版本 {loader_version} 適用於 Minecraft {normalized_minecraft_version}。"
        )
    else:
        warnings.append(
            f"目前伺服器設定的 {normalized_loader.capitalize()} loader 版本 {loader_version} 不在 Minecraft {normalized_minecraft_version} 的已知可用清單內，請確認伺服器設定是否正確。"
        )
    return warnings, notes


def resolve_modrinth_project_names(project_ids: list[str] | set[str] | tuple[str, ...]) -> dict[str, str]:
    """將 Modrinth project id 轉為較易讀的專案名稱。"""
    deduped_project_ids: dict[str, str] = {}
    for project_id in project_ids:
        clean_project_id = _clean_api_identifier(project_id)
        if not clean_project_id:
            continue
        deduped_project_ids.setdefault(_normalize_identifier(clean_project_id), clean_project_id)
    if not deduped_project_ids:
        return {}

    raw_ids = list(deduped_project_ids.values())

    response = HTTPUtils.get_json(
        url=MODRINTH_PROJECT_BATCH_URL,
        headers=_build_headers(),
        params={"ids": PathUtils.to_json_str(raw_ids)},
        timeout=MODRINTH_PROJECT_BATCH_TIMEOUT_SECONDS,
    )

    names: dict[str, str] = {}
    if isinstance(response, list):
        for item in response:
            if not isinstance(item, dict):
                continue
            project_id = _clean_api_identifier(str(item.get("id", "") or ""))
            project_key = _normalize_identifier(project_id)
            if not project_key:
                continue
            name = str(item.get("title", "") or item.get("name", "") or item.get("slug", "") or project_id).strip()
            names[project_key] = name or project_id
    else:
        logger.warning(f"批次解析 Modrinth 專案名稱失敗，共 {len(raw_ids)} 個 project id")

    for project_key, raw_project_id in deduped_project_ids.items():
        if project_key in names:
            continue
        resolved_name = _fetch_modrinth_project_name(raw_project_id)
        if resolved_name:
            names[project_key] = resolved_name
        else:
            logger.debug(f"無法解析 Modrinth 專案名稱，保留 project id: {raw_project_id}")
    return names


def analyze_mod_version_compatibility(
    version: OnlineModVersion,
    project_id: str = "",
    project_name: str = "",
    minecraft_version: str | None = None,
    loader: str | None = None,
    loader_version: str | None = None,
    installed_mods: list[Any] | None = None,
    dependency_names: dict[str, str] | None = None,
) -> OnlineModCompatibilityReport:
    """根據目前伺服器與已安裝模組分析可用版本的相容性。"""
    report = OnlineModCompatibilityReport()
    dependency_name_map = dependency_names or {}

    normalized_minecraft_version = _normalize_identifier(minecraft_version)
    compatible_loaders = _expand_target_loader_aliases(loader, minecraft_version)
    version_game_versions = {_normalize_identifier(entry) for entry in version.game_versions if entry}
    version_loaders = {_normalize_identifier(entry) for entry in version.loaders if entry}

    if (
        normalized_minecraft_version
        and version_game_versions
        and normalized_minecraft_version not in version_game_versions
    ):
        report.hard_errors.append(
            f"此版本支援的 Minecraft 版本為 {', '.join(version.game_versions)}，不符合目前伺服器的 {minecraft_version}。"
        )

    if compatible_loaders and version_loaders and compatible_loaders.isdisjoint(version_loaders):
        report.hard_errors.append(f"此版本支援的載入器為 {', '.join(version.loaders)}，不符合目前伺服器的 {loader}。")

    if not version.primary_file:
        report.hard_errors.append("此版本沒有可下載的 JAR 檔案。")

    rule_warnings, rule_notes = _check_loader_version_rule(minecraft_version, loader, loader_version)
    report.warnings.extend(rule_warnings)
    report.notes.extend(rule_notes)

    installed_project_ids, installed_identifiers = _collect_installed_mod_identifiers(installed_mods)
    installed_versions_by_project = _collect_installed_mod_versions(installed_mods)
    version_details_cache: dict[str, tuple[str, OnlineModVersion | None]] = {}

    normalized_project_id = _normalize_identifier(project_id)
    if normalized_project_id and normalized_project_id in installed_project_ids:
        existing_name = project_name or normalized_project_id
        report.already_installed.append(existing_name)
        report.warnings.append(f"目前伺服器已安裝 {existing_name}，請確認是否要覆蓋、升級或保留舊版本。")

    for dependency in version.dependencies:
        if not isinstance(dependency, dict):
            continue

        dependency_type = _normalize_identifier(str(dependency.get("dependency_type", "required") or "required"))
        resolved_dependency = _resolve_dependency_reference(
            dependency,
            dependency_name_map,
            loader=loader,
            version_details_cache=version_details_cache,
        )
        dependency_project_id = resolved_dependency.compare_project_id
        dependency_label = resolved_dependency.label
        normalized_label = _normalize_identifier(dependency_label)
        is_installed = False
        has_required_version = True

        if (dependency_project_id and dependency_project_id in installed_project_ids) or (
            normalized_label and normalized_label in installed_identifiers
        ):
            is_installed = True

        maybe_installed = False
        if not is_installed:
            maybe_installed = _dependency_maybe_installed_by_filename(resolved_dependency, installed_mods)

        required_version = _normalize_identifier(
            getattr(resolved_dependency.version, "version_number", "") or resolved_dependency.version_name
        )
        installed_versions = sorted(installed_versions_by_project.get(dependency_project_id, set()))
        if is_installed and required_version:
            has_required_version = required_version in installed_versions

        if dependency_type == "required" and is_installed and required_version and not has_required_version:
            installed_version_text = ", ".join(installed_versions) if installed_versions else "未知版本"
            mismatch_message = f"{dependency_label} 目前已安裝，但版本為 {installed_version_text}，與需求版本 {resolved_dependency.version_name or required_version} 不符。"
            report.installed_version_mismatches.append(mismatch_message)
            report.warnings.append(mismatch_message)
            report.missing_required_dependencies.append(dependency_label)
            continue

        if dependency_type == "required":
            if not is_installed:
                report.missing_required_dependencies.append(dependency_label)
                if maybe_installed:
                    report.notes.append(f"{dependency_label} 可能已存在本地相近檔名，請手動確認是否已安裝。")
                    report.warnings.append(f"必要依賴可能已存在但尚未能以 metadata 精確識別：{dependency_label}")
                else:
                    report.warnings.append(f"缺少必要依賴：{dependency_label}")
        elif dependency_type == "optional":
            if not is_installed:
                report.optional_dependencies.append(dependency_label)
        elif dependency_type == "incompatible":
            if is_installed:
                report.incompatible_installed.append(dependency_label)
                report.warnings.append(f"偵測到已安裝的不相容模組：{dependency_label}")
        elif dependency_type == "embedded":
            report.embedded_dependencies.append(dependency_label)
        elif not is_installed:
            report.notes.append(f"依賴 {dependency_label} 的類型為 {dependency_type}，請手動確認。")

    return report


def build_required_dependency_install_plan(
    version: OnlineModVersion,
    *,
    minecraft_version: str | None = None,
    loader: str | None = None,
    loader_version: str | None = None,
    installed_mods: list[Any] | None = None,
    root_project_id: str = "",
    root_project_name: str = "",
    max_depth: int = 20,
) -> OnlineDependencyInstallPlan:
    """為必要依賴建立可自動安裝的連鎖安裝計畫。"""
    plan = OnlineDependencyInstallPlan()
    installed_project_ids, _ = _collect_installed_mod_identifiers(installed_mods)
    installed_versions_by_project = _collect_installed_mod_versions(installed_mods)
    planned_project_ids: set[str] = set()
    normalized_root_project_id = _normalize_identifier(root_project_id)
    version_details_cache: dict[str, tuple[str, OnlineModVersion | None]] = {}

    def _resolve_dependency_entry(
        dependency: dict[str, Any],
        dependency_names: dict[str, str],
    ) -> ResolvedDependencyReference:
        return _resolve_dependency_reference(
            dependency,
            dependency_names,
            loader=loader,
            version_details_cache=version_details_cache,
        )

    def _select_dependency_best_version(
        resolved_dependency: ResolvedDependencyReference,
        *,
        log_filtered_fallback: bool,
    ) -> OnlineModVersion | None:
        dependency_api_project_id = _clean_api_identifier(resolved_dependency.project_id)
        if not dependency_api_project_id:
            return None

        if resolved_dependency.version is not None:
            dependency_versions = [resolved_dependency.version]
        else:
            dependency_versions = get_mod_versions(dependency_api_project_id, minecraft_version, loader)
            if not dependency_versions:
                if log_filtered_fallback:
                    logger.warning(
                        "以目前條件找不到必要依賴版本，回退為未過濾查詢: "
                        f"{resolved_dependency.label} ({resolved_dependency.compare_project_id})"
                    )
                dependency_versions = get_mod_versions(dependency_api_project_id)

        return _select_best_mod_version(dependency_versions)

    def _analyze_dependency_best_version(
        best_version: OnlineModVersion,
        resolved_dependency: ResolvedDependencyReference,
        dependency_label: str,
        dependency_names: dict[str, str],
    ) -> OnlineModCompatibilityReport:
        return analyze_mod_version_compatibility(
            best_version,
            project_id=resolved_dependency.project_id,
            project_name=dependency_label,
            minecraft_version=minecraft_version,
            loader=loader,
            loader_version=loader_version,
            installed_mods=installed_mods,
            dependency_names=dependency_names,
        )

    def _extract_dependency_download_target(best_version: OnlineModVersion) -> tuple[str, str] | None:
        primary_file = best_version.primary_file
        if not primary_file:
            return None

        download_url = str(primary_file.get("url", "") or "").strip()
        filename = str(primary_file.get("filename", "") or "").strip()
        if not download_url or not filename:
            return None
        return download_url, filename

    def _make_dependency_install_item(
        resolved_dependency: ResolvedDependencyReference,
        dependency_label: str,
        best_version: OnlineModVersion,
        download_url: str,
        filename: str,
        parent_name: str,
        *,
        maybe_installed: bool,
        status_note: str,
        enabled: bool,
        is_optional: bool,
    ) -> OnlineDependencyInstallItem:
        return OnlineDependencyInstallItem(
            project_id=resolved_dependency.project_id,
            project_name=dependency_label,
            version_id=best_version.version_id,
            version_name=best_version.display_name,
            filename=filename,
            download_url=download_url,
            parent_name=parent_name,
            maybe_installed=maybe_installed,
            status_note=status_note,
            resolution_source=resolved_dependency.resolution_source,
            resolution_confidence=resolved_dependency.resolution_confidence,
            enabled=enabled,
            is_optional=is_optional,
        )

    def walk_dependencies(
        current_version: OnlineModVersion,
        parent_name: str,
        depth: int,
        active_stack: set[str],
    ) -> None:
        if depth > max_depth:
            plan.unresolved_required.append(f"{parent_name} 的依賴深度超過上限，請手動確認。")
            return

        required_dependencies = [
            dependency
            for dependency in current_version.dependencies
            if isinstance(dependency, dict)
            and _normalize_identifier(str(dependency.get("dependency_type", "required") or "required")) == "required"
        ]
        optional_dependencies = [
            dependency
            for dependency in current_version.dependencies
            if isinstance(dependency, dict)
            and _normalize_identifier(str(dependency.get("dependency_type", "") or "")) == "optional"
        ]
        if not required_dependencies and not optional_dependencies:
            return

        dependency_project_ids = {
            _clean_api_identifier(str(dependency.get("project_id", "") or ""))
            for dependency in [*required_dependencies, *optional_dependencies]
            if str(dependency.get("project_id", "") or "").strip()
        }
        dependency_names = resolve_modrinth_project_names(dependency_project_ids)

        for dependency in required_dependencies:
            resolved_dependency = _resolve_dependency_entry(dependency, dependency_names)
            dependency_project_id = resolved_dependency.compare_project_id
            dependency_label = resolved_dependency.label
            if not dependency_project_id:
                plan.unresolved_required.append(f"{parent_name} 缺少可解析 project id 的必要依賴：{dependency_label}")
                continue

            if dependency_project_id == normalized_root_project_id:
                plan.notes.append(f"略過根模組自身依賴循環：{dependency_label}")
                continue
            if dependency_project_id in active_stack:
                plan.notes.append(f"略過循環依賴：{dependency_label}")
                continue
            if dependency_project_id in installed_project_ids:
                required_version = _normalize_identifier(
                    getattr(resolved_dependency.version, "version_number", "") or resolved_dependency.version_name
                )
                installed_versions = sorted(installed_versions_by_project.get(dependency_project_id, set()))
                if required_version and required_version not in installed_versions:
                    installed_version_text = ", ".join(installed_versions) if installed_versions else "未知版本"
                    plan.unresolved_required.append(
                        f"{dependency_label} 已安裝版本不符：需要 {resolved_dependency.version_name or required_version}，目前為 {installed_version_text}。"
                    )
                    continue
                logger.debug(f"必要依賴已存在，略過自動安裝: {dependency_label} ({dependency_project_id})")
                continue
            maybe_installed = _dependency_maybe_installed_by_filename(resolved_dependency, installed_mods)
            if dependency_project_id in planned_project_ids:
                logger.debug(f"必要依賴已加入安裝計畫，略過重複項目: {dependency_label} ({dependency_project_id})")
                continue

            best_version = _select_dependency_best_version(resolved_dependency, log_filtered_fallback=True)
            if best_version is None:
                plan.unresolved_required.append(f"找不到 {dependency_label} 的可下載版本。")
                continue

            dependency_report = _analyze_dependency_best_version(
                best_version,
                resolved_dependency,
                dependency_label,
                dependency_names,
            )
            if dependency_report.hard_errors:
                first_reason = dependency_report.hard_errors[0]
                plan.unresolved_required.append(f"{dependency_label} 無法自動安裝：{first_reason}")
                continue

            download_target = _extract_dependency_download_target(best_version)
            if download_target is None:
                plan.unresolved_required.append(f"{dependency_label} 缺少可下載的 JAR 檔案。")
                continue

            download_url, filename = download_target

            planned_project_ids.add(dependency_project_id)
            install_item = _make_dependency_install_item(
                resolved_dependency,
                dependency_label,
                best_version,
                download_url,
                filename,
                parent_name,
                maybe_installed=maybe_installed,
                status_note="可能已存在本地相近檔名，依 Prism Launcher 做法預設略過自動安裝。"
                if maybe_installed
                else "",
                enabled=not maybe_installed,
                is_optional=False,
            )
            if maybe_installed:
                plan.advisory_items.append(install_item)
                plan.notes.append(f"{dependency_label} 可能已存在本地相近檔名，已預設略過自動安裝，請手動確認。")
                logger.info(
                    f"必要依賴疑似已安裝，預設略過自動安裝: parent={parent_name}, dependency={dependency_label}, version={best_version.display_name}"
                )
            else:
                plan.items.append(install_item)
                logger.info(
                    f"已加入必要依賴安裝計畫: parent={parent_name}, dependency={dependency_label}, version={best_version.display_name}"
                )

            next_stack = set(active_stack)
            next_stack.add(dependency_project_id)
            walk_dependencies(best_version, dependency_label, depth + 1, next_stack)

        for dependency in optional_dependencies:
            resolved_dependency = _resolve_dependency_entry(dependency, dependency_names)
            dependency_project_id = resolved_dependency.compare_project_id
            dependency_label = resolved_dependency.label
            if not dependency_project_id:
                plan.notes.append(f"可選依賴缺少可解析 project id：{dependency_label}")
                continue

            if dependency_project_id == normalized_root_project_id:
                continue
            if dependency_project_id in installed_project_ids:
                continue
            if dependency_project_id in planned_project_ids:
                continue

            maybe_installed = _dependency_maybe_installed_by_filename(resolved_dependency, installed_mods)

            best_version = _select_dependency_best_version(resolved_dependency, log_filtered_fallback=False)
            if best_version is None:
                plan.notes.append(f"可選依賴目前查無可用版本：{dependency_label}")
                continue

            dependency_report = _analyze_dependency_best_version(
                best_version, resolved_dependency, dependency_label, dependency_names
            )
            optional_hard_errors = dependency_report.hard_errors
            if optional_hard_errors:
                optional_first_error = optional_hard_errors[0]
                plan.notes.append(f"可選依賴暫時無法自動安裝：{dependency_label}（{optional_first_error}）")
                continue

            download_target = _extract_dependency_download_target(best_version)
            if download_target is None:
                plan.notes.append(f"可選依賴缺少可下載 JAR：{dependency_label}")
                continue

            download_url, filename = download_target

            planned_project_ids.add(dependency_project_id)
            plan.advisory_items.append(
                _make_dependency_install_item(
                    resolved_dependency,
                    dependency_label,
                    best_version,
                    download_url,
                    filename,
                    parent_name,
                    maybe_installed=maybe_installed,
                    status_note="可選依賴，預設略過，可於 Review 勾選後一同安裝。",
                    enabled=False,
                    is_optional=True,
                )
            )

    initial_stack: set[str] = {normalized_root_project_id} if normalized_root_project_id else set()
    walk_dependencies(version, root_project_name or root_project_id or "根模組", 0, initial_stack)
    logger.info(
        f"必要依賴安裝計畫建立完成: root={root_project_name or root_project_id or 'unknown'}, auto_install={plan.auto_install_count}, unresolved={len(plan.unresolved_required)}"
    )
    return plan


def _map_hit_to_online_mod(hit: dict[str, Any]) -> OnlineModInfo:
    slug = str(hit.get("slug", "") or "")
    project_id = str(hit.get("project_id", "") or slug)
    project_slug = slug or project_id
    url = f"{MODRINTH_PROJECT_URL}/{project_slug}" if project_slug else MODRINTH_PROJECT_URL
    return OnlineModInfo(
        project_id=project_id,
        slug=project_slug,
        name=str(hit.get("title", "Unknown") or "Unknown"),
        author=str(hit.get("author", "?") or "?"),
        description=str(hit.get("description", "") or ""),
        latest_version=str(hit.get("latest_version", "") or ""),
        download_count=int(hit.get("downloads", 0) or 0),
        icon_url=str(hit.get("icon_url", "") or ""),
        homepage_url=str(hit.get("homepage_url", "") or url),
        url=url,
        categories=list(hit.get("categories", []) or []),
        versions=list(hit.get("versions", []) or []),
        server_side=str(hit.get("server_side", "") or "").strip(),
        client_side=str(hit.get("client_side", "") or "").strip(),
    )


def _is_server_compatible_online_mod(mod: OnlineModInfo) -> bool:
    server_side = str(getattr(mod, "server_side", "") or "").strip().lower()
    client_side = str(getattr(mod, "client_side", "") or "").strip().lower()
    if server_side in {"required", "optional"}:
        return True
    return client_side != "required"


def search_mods_online(
    query: str,
    minecraft_version: str | None = None,
    loader: str | None = None,
    categories: list[str] | None = None,
    sort_by: str = "relevance",
    limit: int = 20,
) -> list[OnlineModInfo]:
    """透過 Modrinth API 搜尋或瀏覽模組。"""
    raw_query = str(query or "").strip()
    normalized_query = normalize_mod_search_query(raw_query) if raw_query else ""
    if raw_query and normalized_query != raw_query:
        logger.debug(f"Modrinth 搜尋字串正規化: {raw_query} -> {normalized_query}")

    facets = [["project_type:mod"], ["server_side:required", "server_side:optional"]]
    if minecraft_version:
        facets.append([f"game_versions:{minecraft_version}"])

    loader_categories = _get_modrinth_loader_filters(loader, minecraft_version)
    if loader_categories:
        facets.append([f"categories:{loader_category}" for loader_category in loader_categories])

    if categories:
        category_facets = [f"categories:{cat}" for cat in categories if cat]
        if category_facets:
            facets.append(category_facets)

    params = {
        "limit": max(1, min(int(limit), 50)),
        "facets": PathUtils.to_json_str(facets),
        "index": _normalize_sort(sort_by),
    }
    if normalized_query:
        params["query"] = normalized_query

    response = HTTPUtils.get_json(
        url=MODRINTH_SEARCH_URL,
        headers=_build_headers(),
        params=params,
        timeout=MODRINTH_SEARCH_TIMEOUT_SECONDS,
    )
    if not response:
        logger.error("Modrinth API request failed")
        return []

    mods = [_map_hit_to_online_mod(hit) for hit in response.get("hits", []) if isinstance(hit, dict)]
    mods = [mod for mod in mods if _is_server_compatible_online_mod(mod)]
    if sort_by == "downloads":
        mods.sort(key=lambda item: item.download_count, reverse=True)
    elif sort_by == "name":
        mods.sort(key=lambda item: item.name.lower())
    return mods


def select_primary_file(files: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """從版本檔案列表中選出最適合下載的檔案。"""
    if not files:
        return None

    for file_info in files:
        if not isinstance(file_info, dict):
            continue
        if file_info.get("primary"):
            return file_info

    for file_info in files:
        if not isinstance(file_info, dict):
            continue
        filename = str(file_info.get("filename", "") or "")
        if filename.lower().endswith(".jar"):
            return file_info

    for file_info in files:
        if isinstance(file_info, dict):
            return file_info
    return None


def get_mod_versions(
    project_id: str,
    minecraft_version: str | None = None,
    loader: str | None = None,
) -> list[OnlineModVersion]:
    """取得指定 Modrinth 模組的穩定版本。"""
    clean_project_id = _clean_api_identifier(project_id)
    if not clean_project_id:
        return []

    url = MODRINTH_VERSION_URL_TEMPLATE.format(project_id=clean_project_id)
    response = HTTPUtils.get_json(url=url, headers=_build_headers(), timeout=MODRINTH_VERSION_TIMEOUT_SECONDS)
    if not isinstance(response, list):
        logger.error(f"取得 Modrinth 版本列表失敗: {clean_project_id}")
        return []

    loader_filters = set(_get_modrinth_loader_filters(loader, minecraft_version))
    versions: list[OnlineModVersion] = []
    for item in response:
        if not isinstance(item, dict):
            continue

        parsed_version = _parse_modrinth_version(item)
        game_versions = parsed_version.game_versions
        loaders = parsed_version.loaders

        if minecraft_version and minecraft_version not in game_versions:
            continue
        normalized_version_loaders = {_normalize_identifier(entry) for entry in loaders if entry}
        if loader_filters and loader_filters.isdisjoint(normalized_version_loaders):
            continue
        if not _is_release_version_type(parsed_version.version_type):
            continue

        versions.append(parsed_version)
    return versions


def get_recommended_mod_version(
    project_id: str,
    minecraft_version: str | None = None,
    loader: str | None = None,
) -> OnlineModVersion | None:
    """取得最適合目前條件的推薦版本，若條件下查無版本則回退到未過濾結果。"""
    clean_project_id = _clean_api_identifier(project_id)
    if not clean_project_id:
        return None

    versions = get_mod_versions(clean_project_id, minecraft_version, loader)
    if not versions:
        versions = get_mod_versions(clean_project_id)
    return _select_best_mod_version(versions)


def analyze_local_mod_file_compatibility(
    local_mod: Any,
    minecraft_version: str | None = None,
    loader: str | None = None,
) -> list[str]:
    """以本地模組已知 metadata 檢查目前伺服器條件是否明顯不相容。

    本地 jar 解析出的 Minecraft 版本常已失去 range 語意，只適合作為提示，
    不適合直接當成不相容判定依據。
    """
    issues: list[str] = []

    local_name = str(getattr(local_mod, "name", "") or getattr(local_mod, "filename", "模組")).strip() or "模組"
    str(getattr(local_mod, "minecraft_version", "") or "").strip()
    local_loader = str(getattr(local_mod, "loader_type", "") or "").strip()
    local_version = str(getattr(local_mod, "version", "") or "").strip()

    normalized_local_loader = _normalize_local_loader(local_loader)
    compatible_target_loaders = _expand_target_loader_aliases(loader, minecraft_version)
    if (
        normalized_local_loader
        and normalized_local_loader not in {"", "未知", "unknown"}
        and compatible_target_loaders
        and normalized_local_loader not in compatible_target_loaders
    ):
        issues.append(f"{local_name} 目前本地 metadata 顯示載入器為 {local_loader}，與伺服器的 {loader} 不一致。")

    if not local_version or local_version == "未知":
        issues.append(f"{local_name} 的本地版本資訊未知，無法精準判斷是否已是最新版本。")

    return issues


def build_local_mod_update_plan(
    local_mods: list[Any] | None,
    minecraft_version: str | None = None,
    loader: str | None = None,
    loader_version: str | None = None,
    hash_progress_callback: Callable[[int, int], None] | None = None,
) -> LocalModUpdatePlan:
    """為本地模組建立更新檢查計畫，優先採用 Prism 風格的 hash-first 批次檢查。"""
    plan = LocalModUpdatePlan()
    installed_mods = list(local_mods or [])
    plan.metadata_summary.total_scanned = len(installed_mods)

    hash_algorithm = MODRINTH_PREFERRED_HASH_ALGORITHM
    project_ids: list[str] = []
    resolved_project_info_by_filename: dict[str, OnlineModInfo] = {}
    metadata_source_by_filename: dict[str, str] = {}
    unresolved_mod_labels: list[str] = []
    local_hashes_by_filename: dict[str, str] = {}
    hash_progress_total = len(installed_mods)
    hash_progress_done = 0

    def _emit_hash_progress() -> None:
        if hash_progress_callback is None or hash_progress_total <= 0:
            return
        try:
            hash_progress_callback(hash_progress_done, hash_progress_total)
        except Exception as e:
            logger.debug(f"回報本地模組 hash 進度失敗: {e}")

    hash_compute_jobs: list[tuple[Any, str, str]] = []
    for local_mod in installed_mods:
        filename_key = str(getattr(local_mod, "filename", "") or "").strip()
        cached_hash = str(getattr(local_mod, "current_hash", "") or "").strip().lower()
        cached_algorithm = _normalize_hash_algorithm(getattr(local_mod, "hash_algorithm", hash_algorithm))
        if cached_hash and cached_algorithm == hash_algorithm:
            if filename_key:
                local_hashes_by_filename[filename_key] = cached_hash
            hash_progress_done += 1
            _emit_hash_progress()
            continue
        hash_compute_jobs.append((local_mod, filename_key, str(getattr(local_mod, "file_path", "") or "").strip()))

    if hash_compute_jobs:

        def _compute_local_hash(job: tuple[Any, str, str]) -> tuple[Any, str, str]:
            local_mod_obj, filename_key_obj, file_path_obj = job
            return local_mod_obj, filename_key_obj, _compute_file_hash(file_path_obj, hash_algorithm)

        max_workers = min(LOCAL_HASH_MAX_WORKERS, len(hash_compute_jobs))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for local_mod, filename_key, local_hash in executor.map(_compute_local_hash, hash_compute_jobs):
                if not local_hash:
                    hash_progress_done += 1
                    _emit_hash_progress()
                    continue
                local_mod.current_hash = local_hash
                local_mod.hash_algorithm = hash_algorithm
                if filename_key:
                    local_hashes_by_filename[filename_key] = local_hash
                hash_progress_done += 1
                _emit_hash_progress()

    known_hashes = list(local_hashes_by_filename.values())
    current_versions_by_hash = get_modrinth_current_versions_by_hashes(known_hashes, hash_algorithm)
    latest_versions_by_hash = get_modrinth_latest_versions_by_hashes(
        known_hashes,
        hash_algorithm,
        minecraft_version=minecraft_version,
        loader=loader,
    )

    for local_mod in installed_mods:
        filename_key = str(getattr(local_mod, "filename", "") or "").strip()
        local_hash = local_hashes_by_filename.get(filename_key, "")
        current_match = current_versions_by_hash.get(local_hash)
        latest_match = latest_versions_by_hash.get(local_hash)

        resolved_project_info = None
        metadata_source = ""
        existing_project_id = _clean_api_identifier(getattr(local_mod, "platform_id", ""))
        resolved_project_id = _clean_api_identifier(
            getattr(current_match, "project_id", "") or getattr(latest_match, "project_id", "")
        )
        if resolved_project_id:
            local_mod.platform_id = resolved_project_id
            resolved_project_info = OnlineModInfo(
                project_id=resolved_project_id,
                slug="",
                name="",
                author="",
            )
            metadata_source = "hash"
            plan.metadata_summary.resolved_by_hash += 1
        else:
            resolved_project_info = resolve_local_mod_project_info(local_mod)
            if resolved_project_info is not None:
                existing_platform_slug = str(getattr(local_mod, "platform_slug", "") or "").strip()
                if existing_project_id or existing_platform_slug:
                    metadata_source = "cached_provider"
                    plan.metadata_summary.resolved_by_cached_project += 1
                else:
                    metadata_source = "lookup"
                    plan.metadata_summary.resolved_by_lookup += 1

        if resolved_project_info is None:
            unresolved_label = str(
                getattr(local_mod, "name", "") or getattr(local_mod, "filename", "") or "模組"
            ).strip()
            if unresolved_label:
                unresolved_mod_labels.append(unresolved_label)
            plan.candidates.append(
                LocalModUpdateCandidate(
                    project_id=f"__unresolved__::{filename_key or unresolved_label}",
                    project_name=unresolved_label or "未識別模組",
                    filename=filename_key,
                    current_version=str(getattr(local_mod, "version", "") or "").strip(),
                    current_hash=local_hash,
                    hash_algorithm=hash_algorithm,
                    hard_errors=["無法建立可用的 Modrinth metadata，暫時無法自動檢查更新。"],
                    notes=["請確認檔名、模組來源，或稍後再試一次線上識別。"],
                    metadata_source="unresolved",
                    metadata_note="metadata ensure 失敗：找不到可用的 provider metadata 或雜湊對應結果。",
                    metadata_resolved=False,
                    local_mod=local_mod,
                )
            )
            continue

        if filename_key:
            resolved_project_info_by_filename[filename_key] = resolved_project_info
            metadata_source_by_filename[filename_key] = metadata_source
        project_id = _clean_api_identifier(getattr(resolved_project_info, "project_id", ""))
        if project_id:
            project_ids.append(project_id)

    project_name_map = resolve_modrinth_project_names(project_ids)

    for local_mod in installed_mods:
        filename_key = str(getattr(local_mod, "filename", "") or "").strip()
        resolved_project_info = resolved_project_info_by_filename.get(filename_key)
        project_id = _clean_api_identifier(getattr(resolved_project_info, "project_id", ""))
        if not project_id:
            continue

        project_key = _normalize_identifier(project_id)
        project_name = (
            project_name_map.get(project_key, "").strip()
            or str(getattr(resolved_project_info, "name", "") or "").strip()
            or str(getattr(local_mod, "name", "") or project_id).strip()
        )
        current_version = str(getattr(local_mod, "version", "") or "").strip()
        current_issues = analyze_local_mod_file_compatibility(local_mod, minecraft_version, loader)
        local_hash = local_hashes_by_filename.get(filename_key, "")
        current_match = current_versions_by_hash.get(local_hash)
        latest_match = latest_versions_by_hash.get(local_hash)
        recommended_version = latest_match.version if latest_match is not None else None

        if recommended_version is None:
            # Fallback: preserve the older project-based path when hash metadata is unavailable.
            recommended_version = get_recommended_mod_version(project_id, minecraft_version, loader)

        if recommended_version is None:
            if current_issues:
                plan.candidates.append(
                    LocalModUpdateCandidate(
                        project_id=project_id,
                        project_name=project_name,
                        filename=str(getattr(local_mod, "filename", "") or "").strip(),
                        current_version=current_version,
                        current_hash=local_hash,
                        hash_algorithm=hash_algorithm,
                        current_issues=current_issues,
                        notes=["目前找不到符合條件的線上版本，無法自動檢查更新。"],
                        local_mod=local_mod,
                    )
                )
            continue

        dependency_project_ids = {
            _clean_api_identifier(str(dependency.get("project_id", "") or ""))
            for dependency in recommended_version.dependencies
            if isinstance(dependency, dict) and str(dependency.get("project_id", "") or "").strip()
        }
        dependency_names = resolve_modrinth_project_names(dependency_project_ids)
        report = analyze_mod_version_compatibility(
            recommended_version,
            project_id=project_id,
            project_name=project_name,
            minecraft_version=minecraft_version,
            loader=loader,
            loader_version=loader_version,
            installed_mods=installed_mods,
            dependency_names=dependency_names,
        )
        dependency_issues = [
            *list(report.missing_required_dependencies),
            *list(report.installed_version_mismatches),
            *list(report.incompatible_installed),
        ]
        notes = list(report.notes)
        if report.optional_dependencies:
            notes.append(f"可選依賴：{', '.join(report.optional_dependencies)}")

        metadata_source = metadata_source_by_filename.get(filename_key, "")
        metadata_note = {
            "hash": "metadata 來源：使用本地檔案雜湊直接對應到 Modrinth 專案。",
            "cached_provider": "metadata 來源：使用已快取的 provider metadata / project id。",
            "lookup": "metadata 來源：使用專案識別查詢補齊。",
        }.get(metadata_source, "")

        primary_file = recommended_version.primary_file or {}
        target_version_name = str(recommended_version.display_name or recommended_version.version_number or "").strip()
        target_filename = str(primary_file.get("filename", "") or "").strip()
        download_url = str(primary_file.get("url", "") or "").strip()
        target_file_hash = _extract_primary_file_hash(recommended_version, hash_algorithm)

        if not current_version and current_match is not None:
            current_version = str(
                current_match.version.display_name or current_match.version.version_number or ""
            ).strip()

        if (
            latest_match is None
            and local_hash
            and target_file_hash
            and local_hash == target_file_hash
            and not current_issues
        ):
            continue

        candidate = LocalModUpdateCandidate(
            project_id=project_id,
            project_name=project_name,
            filename=str(getattr(local_mod, "filename", "") or "").strip(),
            current_version=current_version,
            target_version_id=str(recommended_version.version_id or "").strip(),
            target_version_name=target_version_name,
            target_version=recommended_version,
            target_filename=target_filename,
            download_url=download_url,
            current_hash=local_hash,
            hash_algorithm=hash_algorithm,
            target_file_hash=target_file_hash,
            current_issues=current_issues,
            dependency_issues=dependency_issues,
            hard_errors=list(report.hard_errors),
            notes=notes,
            metadata_source=metadata_source,
            metadata_note=metadata_note,
            metadata_resolved=True,
            server_side=str(getattr(resolved_project_info, "server_side", "") or "").strip(),
            client_side=str(getattr(resolved_project_info, "client_side", "") or "").strip(),
            report=report,
            local_mod=local_mod,
        )

        if candidate.update_available or candidate.has_issues:
            plan.candidates.append(candidate)

    if unresolved_mod_labels:
        plan.metadata_summary.unresolved = len(unresolved_mod_labels)
        preview = ", ".join(unresolved_mod_labels[:3])
        suffix = " 等" if len(unresolved_mod_labels) > 3 else ""
        plan.notes.append(
            f"有 {len(unresolved_mod_labels)} 個本地模組暫時無法對應到 Modrinth 專案，已略過自動更新檢查：{preview}{suffix}。"
        )
    else:
        plan.metadata_summary.unresolved = 0

    plan.metadata_summary.notes.append(
        "metadata ensure 結果："
        f"共檢查 {plan.metadata_summary.total_scanned} 個本地模組，"
        f"其中 {plan.metadata_summary.resolved_by_hash} 個以雜湊直接識別，"
        f"{plan.metadata_summary.resolved_by_cached_project} 個使用已快取 metadata，"
        f"{plan.metadata_summary.resolved_by_lookup} 個需額外查詢，"
        f"{plan.metadata_summary.unresolved} 個仍無法識別。"
    )

    if not plan.candidates and not plan.notes:
        plan.notes.append("所有已識別的本地模組目前都沒有可用更新，且未偵測到明顯相容性問題。")

    return plan


def enhance_local_mod(
    filename: str,
    *,
    platform_id: str | None = None,
    platform_slug: str | None = None,
    local_name: str | None = None,
) -> OnlineModInfo | None:
    """增強本地模組資訊，從線上查詢模組詳細資訊。"""
    exact_identifiers, search_terms, candidate_keys = _build_local_mod_lookup_candidates(
        filename,
        platform_id=platform_id,
        platform_slug=platform_slug,
        local_name=local_name,
    )

    for candidate_identifier in exact_identifiers:
        exact_match = get_modrinth_project_info(candidate_identifier)
        if exact_match is not None:
            return exact_match

    best_match: OnlineModInfo | None = None
    best_score = -1
    for search_term in search_terms:
        mods = search_mods_online(search_term, limit=8)
        if not mods:
            continue
        for mod in mods:
            score = _score_local_mod_search_match(mod, candidate_keys)
            if score > best_score:
                best_match = mod
                best_score = score
        if best_score >= 100:
            break

    if best_score < MIN_ACCEPTABLE_LOCAL_MOD_SEARCH_SCORE:
        return None

    return best_match
