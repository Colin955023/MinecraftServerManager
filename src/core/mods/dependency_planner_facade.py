"""依賴規劃與本地更新 facade"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.models import (
    LocalModUpdateCandidate,
    LocalModUpdatePlan,
    ModrinthVersionLookupResult,
    OnlineDependencyInstallItem,
    OnlineDependencyInstallPlan,
    OnlineModCompatibilityReport,
    OnlineModInfo,
    OnlineModVersion,
    ProviderIdentitySnapshot,
    ResolvedDependencyReference,
)
from src.utils import (
    LOCAL_UPDATE_ERROR_METADATA_UNRESOLVED,
    LOCAL_UPDATE_ERROR_STALE_REVALIDATION_FAILED,
    LOCAL_UPDATE_ERROR_STALE_REVALIDATION_INVALIDATED,
    LOCAL_UPDATE_METADATA_NOTE_STALE_REVALIDATION_FAILED,
    LOCAL_UPDATE_NOTE_CURRENT_VERSION_UNVERIFIED,
    LOCAL_UPDATE_NOTE_IDENTIFIED_NO_UPDATE,
    LOCAL_UPDATE_NOTE_METADATA_UNRESOLVED,
    LOCAL_UPDATE_NOTE_PROJECT_FALLBACK_ADVISORY,
    LOCAL_UPDATE_NOTE_STALE_BACKOFF_INVALIDATED,
    LOCAL_UPDATE_NOTE_STALE_BACKOFF_RETRYING,
    LOCAL_UPDATE_NOTE_STALE_RETRY_AUTO,
    METADATA_SOURCE_CACHED_PROVIDER,
    METADATA_SOURCE_HASH,
    METADATA_SOURCE_LOOKUP,
    METADATA_SOURCE_STALE_PROVIDER,
    METADATA_SOURCE_UNRESOLVED,
    MODRINTH_PREFERRED_HASH_ALGORITHM,
    RECOMMENDATION_CONFIDENCE_ADVISORY,
    RECOMMENDATION_CONFIDENCE_BLOCKED,
    RECOMMENDATION_CONFIDENCE_HIGH,
    RECOMMENDATION_CONFIDENCE_RETRYABLE,
    RECOMMENDATION_SOURCE_HASH_METADATA,
    RECOMMENDATION_SOURCE_METADATA_UNRESOLVED,
    RECOMMENDATION_SOURCE_PROJECT_FALLBACK,
    RECOMMENDATION_SOURCE_STALE_METADATA,
    HashUtils,
    clean_api_identifier,
    collect_installed_mod_identifiers,
    collect_installed_mod_versions,
    dependency_maybe_installed_by_filename,
    extract_primary_file_hash,
    get_shared_manager,
    is_supported_modrinth_update_loader,
    normalize_hash_algorithm,
    normalize_identifier,
    normalize_local_loader,
    select_best_mod_version,
)

from .compatibility_analyzer import analyze_local_mod_file_compatibility
from .mod_planning_ports import (
    LoaderRulesPort,
    ModPlanningProviderPort,
)
from .mod_search_constants import logger


def _resolve_reference(
    dependency: dict[str, Any],
    dependency_names: dict[str, str],
    *,
    version_details_cache: dict[str, tuple[str, OnlineModVersion | None]] | None = None,
    provider: ModPlanningProviderPort,
) -> ResolvedDependencyReference:
    """補上 provider 查詢能力後解析單筆依賴參照"""
    resolved = ResolvedDependencyReference(
        project_id=clean_api_identifier(str(dependency.get("project_id", "") or "")),
        version_id=clean_api_identifier(str(dependency.get("version_id", "") or "")),
        file_name=str(dependency.get("file_name", "") or dependency.get("filename", "") or "").strip(),
        resolution_source="project_id" if str(dependency.get("project_id", "") or "").strip() else "version_id",
        resolution_confidence="direct" if str(dependency.get("project_id", "") or "").strip() else "fallback",
    )
    if resolved.version_id:
        cache = version_details_cache if version_details_cache is not None else {}
        if resolved.version_id not in cache:
            cache[resolved.version_id] = provider.get_version_details(resolved.version_id)
        version_project_id, version_details = cache.get(resolved.version_id, ("", None))
        if version_details is not None:
            resolved.version = version_details
            resolved.version_name = str(version_details.display_name or version_details.version_number or "").strip()
        if not resolved.project_id and version_project_id:
            resolved.project_id = version_project_id
            resolved.resolution_source = "version_detail"
            resolved.resolution_confidence = "fallback"
    if resolved.project_id:
        resolved.project_name = dependency_names.get(resolved.compare_project_id, "").strip()
        if not resolved.project_name:
            fetched_name = provider.fetch_project_name(resolved.project_id)
            if fetched_name:
                dependency_names[resolved.compare_project_id] = fetched_name
                resolved.project_name = fetched_name
    return resolved


def _check_loader_version_rule(
    minecraft_version: str | None,
    loader: str | None,
    loader_version: str | None,
    loader_rules: LoaderRulesPort,
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    notes: list[str] = []
    normalized_minecraft_version = str(minecraft_version or "").strip()
    normalized_loader = normalize_identifier(loader)
    normalized_loader_version = normalize_identifier(loader_version)
    if not normalized_minecraft_version or not normalized_loader or (not normalized_loader_version):
        return (warnings, notes)
    try:
        compatible_versions = loader_rules.compatible_versions(normalized_minecraft_version, normalized_loader)
    except Exception as e:
        logger.warning(f"讀取 {normalized_loader} 載入器規則失敗: {e}")
        return (warnings, notes)
    available_versions = {normalize_identifier(version) for version in compatible_versions if version}
    if not available_versions:
        notes.append(
            f"目前找不到 {normalized_loader} 對 Minecraft {normalized_minecraft_version} 的本地規則快取，因此無法額外驗證 loader 版本 {loader_version}"
        )
        return (warnings, notes)
    if normalized_loader_version in available_versions:
        notes.append(
            f"已使用內建 {normalized_loader.capitalize()} 規則確認 loader 版本 {loader_version} 適用於 Minecraft {normalized_minecraft_version}"
        )
    else:
        warnings.append(
            f"目前伺服器設定的 {normalized_loader.capitalize()} loader 版本 {loader_version} 不在 Minecraft {normalized_minecraft_version} 的已知可用清單內，系統將維持安全檢查模式"
        )
    return (warnings, notes)


def _analyze_version_data(
    version: OnlineModVersion,
    project_id: str = "",
    project_name: str = "",
    minecraft_version: str | None = None,
    loader: str | None = None,
    loader_version: str | None = None,
    installed_mods: list[Any] | None = None,
    dependency_names: dict[str, str] | None = None,
    *,
    provider: ModPlanningProviderPort,
    loader_rules: LoaderRulesPort,
) -> OnlineModCompatibilityReport:
    """根據目前伺服器與已安裝模組分析可用版本的相容性"""
    report = OnlineModCompatibilityReport()
    dependency_name_map = dependency_names or {}
    normalized_minecraft_version = normalize_identifier(minecraft_version)
    normalized_loader = normalize_local_loader(loader)
    compatible_loaders = {normalized_loader} if normalized_loader else set()
    version_game_versions = {normalize_identifier(entry) for entry in version.game_versions if entry}
    version_loaders = {normalize_identifier(entry) for entry in version.loaders if entry}
    if (
        normalized_minecraft_version
        and version_game_versions
        and (normalized_minecraft_version not in version_game_versions)
    ):
        report.hard_errors.append(
            f"此版本支援的 Minecraft 版本為 {', '.join(version.game_versions)}，不符合目前伺服器的 {minecraft_version}"
        )
    if compatible_loaders and version_loaders and compatible_loaders.isdisjoint(version_loaders):
        report.hard_errors.append(f"此版本支援的載入器為 {', '.join(version.loaders)}，不符合目前伺服器的 {loader}")
    if not version.primary_file:
        report.hard_errors.append("此版本沒有可下載的 JAR 檔案")
    rule_warnings, rule_notes = _check_loader_version_rule(minecraft_version, loader, loader_version, loader_rules)
    report.warnings.extend(rule_warnings)
    report.notes.extend(rule_notes)
    installed_project_ids, installed_identifiers = collect_installed_mod_identifiers(installed_mods)
    installed_versions_by_project = collect_installed_mod_versions(installed_mods)
    version_details_cache: dict[str, tuple[str, OnlineModVersion | None]] = {}
    normalized_project_id = normalize_identifier(project_id)
    if normalized_project_id and normalized_project_id in installed_project_ids:
        existing_name = project_name or normalized_project_id
        report.already_installed.append(existing_name)
        report.warnings.append(f"目前伺服器已安裝 {existing_name}，系統會以安全策略避免重複安裝")
    for dependency in version.dependencies:
        if not isinstance(dependency, dict):
            continue
        dependency_type = normalize_identifier(str(dependency.get("dependency_type", "required") or "required"))
        resolved_dependency = _resolve_reference(
            dependency,
            dependency_name_map,
            version_details_cache=version_details_cache,
            provider=provider,
        )
        dependency_project_id = resolved_dependency.compare_project_id
        dependency_label = resolved_dependency.label
        normalized_label = normalize_identifier(dependency_label)
        is_installed = bool(
            (dependency_project_id and dependency_project_id in installed_project_ids)
            or (normalized_label and normalized_label in installed_identifiers)
        )
        maybe_installed = not is_installed and dependency_maybe_installed_by_filename(
            resolved_dependency, installed_mods
        )
        required_version = normalize_identifier(
            getattr(resolved_dependency.version, "version_number", "") or resolved_dependency.version_name
        )
        installed_versions = sorted(installed_versions_by_project.get(dependency_project_id, set()))
        has_required_version = not (is_installed and required_version) or required_version in installed_versions
        if dependency_type == "required" and is_installed and required_version and (not has_required_version):
            installed_version_text = ", ".join(installed_versions) if installed_versions else "未知版本"
            mismatch_message = f"{dependency_label} 目前已安裝，但版本為 {installed_version_text}，與需求版本 {resolved_dependency.version_name or required_version} 不符"
            report.installed_version_mismatches.append(mismatch_message)
            report.warnings.append(mismatch_message)
            report.missing_required_dependencies.append(dependency_label)
            continue
        if dependency_type == "required" and not is_installed:
            report.missing_required_dependencies.append(dependency_label)
            if maybe_installed:
                report.notes.append(f"{dependency_label} 可能已存在本地相近檔名，系統已先採安全略過策略")
                report.warnings.append(f"必要依賴可能已存在但尚未能以 metadata 精確識別：{dependency_label}")
            else:
                report.warnings.append(f"缺少必要依賴：{dependency_label}")
        elif dependency_type == "optional" and not is_installed:
            report.optional_dependencies.append(dependency_label)
        elif dependency_type == "incompatible" and is_installed:
            report.incompatible_installed.append(dependency_label)
            incompatible_message = f"偵測到已安裝的不相容模組：{dependency_label}"
            report.hard_errors.append(incompatible_message)
            report.warnings.append(incompatible_message)
        elif dependency_type == "embedded":
            report.embedded_dependencies.append(dependency_label)
        elif dependency_type not in {"required", "optional", "incompatible"} and not is_installed:
            report.notes.append(f"依賴 {dependency_label} 的類型為 {dependency_type}，系統已先採安全保守策略")
    return report


def _resolve_local_update_recommendation_strategy(
    *, used_project_fallback: bool, metadata_resolved: bool
) -> tuple[str, str]:
    if not metadata_resolved:
        return (RECOMMENDATION_SOURCE_METADATA_UNRESOLVED, RECOMMENDATION_CONFIDENCE_BLOCKED)
    if used_project_fallback:
        return (RECOMMENDATION_SOURCE_PROJECT_FALLBACK, RECOMMENDATION_CONFIDENCE_ADVISORY)
    return (RECOMMENDATION_SOURCE_HASH_METADATA, RECOMMENDATION_CONFIDENCE_HIGH)


@dataclass(frozen=True, slots=True)
class ModPlanning:
    """集中提供相容性、依賴安裝與本地更新三個完整 use cases"""

    provider: ModPlanningProviderPort
    loader_rules: LoaderRulesPort

    def analyze_version(
        self,
        version: OnlineModVersion,
        *,
        project_id: str = "",
        project_name: str = "",
        minecraft_version: str | None = None,
        loader: str | None = None,
        loader_version: str | None = None,
        installed_mods: list[Any] | None = None,
        dependency_names: dict[str, str] | None = None,
    ) -> OnlineModCompatibilityReport:
        """
        分析單一模組版本在指定伺服器環境中的相容性

        Args:
            version: 待分析的線上模組版本
            project_id: 根模組的 provider project id
            project_name: 根模組顯示名稱
            minecraft_version: 目標 Minecraft 版本
            loader: 目標載入器類型
            loader_version: 目標載入器版本
            installed_mods: 已安裝的本地模組
            dependency_names: 已解析的依賴名稱對照

        Returns:
            完整相容性報告
        """
        if dependency_names is None:
            dependency_project_ids = {
                clean_api_identifier(str(dependency.get("project_id", "") or ""))
                for dependency in version.dependencies
                if isinstance(dependency, dict) and str(dependency.get("project_id", "") or "").strip()
            }
            dependency_names = self.provider.resolve_project_names(dependency_project_ids)
        return _analyze_version_data(
            version,
            project_id=project_id,
            project_name=project_name,
            minecraft_version=minecraft_version,
            loader=loader,
            loader_version=loader_version,
            installed_mods=installed_mods,
            dependency_names=dependency_names,
            provider=self.provider,
            loader_rules=self.loader_rules,
        )

    def build_dependency_plan(
        self,
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
        """
        建立根模組版本的完整依賴安裝計畫

        Args:
            version: 根模組版本
            minecraft_version: 目標 Minecraft 版本
            loader: 目標載入器類型
            loader_version: 目標載入器版本
            installed_mods: 已安裝的本地模組
            root_project_id: 根模組的 provider project id
            root_project_name: 根模組顯示名稱
            max_depth: 依賴圖最大展開深度

        Returns:
            可交由 Review 與安裝流程使用的依賴計畫
        """
        plan = OnlineDependencyInstallPlan()
        installed_project_ids, _ = collect_installed_mod_identifiers(installed_mods)
        installed_versions_by_project = collect_installed_mod_versions(installed_mods)
        planning_service = _DependencyPlanningService(
            provider=self.provider,
            loader_rules=self.loader_rules,
            minecraft_version=minecraft_version,
            loader=loader,
            loader_version=loader_version,
            installed_mods=installed_mods,
        )

        _expand_dependency_plan(
            root_version=version,
            plan=plan,
            planning_service=planning_service,
            installed_project_ids=installed_project_ids,
            installed_versions_by_project=installed_versions_by_project,
            installed_mods=installed_mods,
            root_project_id=root_project_id,
            root_project_name=root_project_name,
            max_depth=max_depth,
            log_debug=logger.debug,
            log_info=logger.info,
        )
        logger.info(
            f"必要依賴安裝計畫建立完成: root={root_project_name or root_project_id or 'unknown'}, auto_install={plan.auto_install_count}, unresolved={len(plan.unresolved_required)}"
        )
        return plan

    def build_local_update_plan(
        self,
        local_mods: list[Any] | None,
        minecraft_version: str | None = None,
        loader: str | None = None,
        loader_version: str | None = None,
        hash_progress_callback: Callable[[int, int], None] | None = None,
        *,
        provider_identity_resolver: Callable[[Any, str], ProviderIdentitySnapshot],
        hash_cache_writer: Callable[[Any, str, str], None] | None = None,
        stage_progress_callback: Callable[[float, str], None] | None = None,
    ) -> LocalModUpdatePlan:
        """
        建立本地模組更新計畫並保留 identity 與 hash owner commands

        Args:
            local_mods: 待檢查的本地模組
            minecraft_version: 目標 Minecraft 版本
            loader: 目標載入器類型
            loader_version: 目標載入器版本
            hash_progress_callback: hash 計算進度回呼
            provider_identity_resolver: provider identity 解析 command
            hash_cache_writer: hash 持久化 command
            stage_progress_callback: 整體階段進度回呼

        Returns:
            可交由 Review 與執行流程使用的本地更新計畫
        """
        plan = LocalModUpdatePlan()
        installed_mods = list(local_mods or [])
        plan.metadata_summary.total_scanned = len(installed_mods)
        normalized_target_loader = normalize_local_loader(loader)
        supports_online_loader_updates = is_supported_modrinth_update_loader(loader)
        if normalized_target_loader and (not supports_online_loader_updates):
            plan.notes.append(
                f"目前本地更新的線上比對僅支援 Fabric / Forge / Quilt / NeoForge，已略過 {loader} 的版本更新判定"
            )
        hash_algorithm = MODRINTH_PREFERRED_HASH_ALGORITHM
        project_ids: list[str] = []
        resolved_project_info_by_filename: dict[str, OnlineModInfo] = {}
        provider_identity_by_filename: dict[str, ProviderIdentitySnapshot] = {}
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
            cached_algorithm = normalize_hash_algorithm(getattr(local_mod, "hash_algorithm", hash_algorithm))
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
                return (local_mod_obj, filename_key_obj, HashUtils.compute_file_hash(file_path_obj, hash_algorithm))

            manager = get_shared_manager()
            futures = [manager.run(_compute_local_hash, job) for job in hash_compute_jobs]
            for future in futures:
                local_mod, filename_key, local_hash = future.result()
                if not local_hash:
                    hash_progress_done += 1
                    _emit_hash_progress()
                    continue
                if hash_cache_writer is not None:
                    hash_cache_writer(local_mod, hash_algorithm, local_hash)
                if filename_key:
                    local_hashes_by_filename[filename_key] = local_hash
                hash_progress_done += 1
                _emit_hash_progress()
        known_hashes = list(local_hashes_by_filename.values())
        if stage_progress_callback:
            stage_progress_callback(0.35, "正在向 Modrinth 查詢線上模組版本資訊...")
        current_versions_by_hash = self.provider.get_current_versions_by_hashes(known_hashes, hash_algorithm)
        latest_versions_by_hash: dict[str, ModrinthVersionLookupResult] = {}
        if supports_online_loader_updates:
            if stage_progress_callback:
                stage_progress_callback(0.55, "正在查詢最新相容版本與更新清單...")
            latest_versions_by_hash = self.provider.get_latest_versions_by_hashes(
                known_hashes, hash_algorithm, minecraft_version=minecraft_version, loader=loader
            )
        if stage_progress_callback:
            stage_progress_callback(0.75, "正在比對版本差異與分析模組依賴關係...")
        for local_mod in installed_mods:
            filename_key = str(getattr(local_mod, "filename", "") or "").strip()
            local_hash = local_hashes_by_filename.get(filename_key, "")
            current_match = current_versions_by_hash.get(local_hash)
            latest_match = latest_versions_by_hash.get(local_hash)
            hash_project_id = clean_api_identifier(
                getattr(current_match, "project_id", "") or getattr(latest_match, "project_id", "")
            )
            identity = provider_identity_resolver(local_mod, hash_project_id)
            resolved_project_info: OnlineModInfo | None = None
            metadata_source = identity.provenance
            if identity.canonical:
                resolved_project_info = OnlineModInfo(
                    project_id=identity.project_id,
                    slug=identity.alias,
                    name=identity.display_name,
                    author="",
                )
                if identity.provenance == "hash":
                    metadata_source = METADATA_SOURCE_HASH
                elif identity.provenance in {"cached_provider", "scan_detect"}:
                    metadata_source = METADATA_SOURCE_CACHED_PROVIDER
                else:
                    metadata_source = METADATA_SOURCE_LOOKUP
            if hash_project_id and identity.canonical:
                plan.metadata_summary.resolved_by_hash += 1
            elif identity.canonical and metadata_source == METADATA_SOURCE_CACHED_PROVIDER:
                plan.metadata_summary.resolved_by_cached_project += 1
            elif identity.canonical:
                plan.metadata_summary.resolved_by_lookup += 1
            if resolved_project_info is None:
                unresolved_label = str(
                    getattr(local_mod, "name", "") or getattr(local_mod, "filename", "") or "模組"
                ).strip()
                if identity.lifecycle in {"stale", "retrying", "invalidated"}:
                    confidence = RECOMMENDATION_CONFIDENCE_RETRYABLE
                    hard_error = LOCAL_UPDATE_ERROR_STALE_REVALIDATION_FAILED
                    backoff_note = ""
                    if identity.lifecycle == "invalidated":
                        confidence = RECOMMENDATION_CONFIDENCE_BLOCKED
                        hard_error = LOCAL_UPDATE_ERROR_STALE_REVALIDATION_INVALIDATED
                        backoff_note = LOCAL_UPDATE_NOTE_STALE_BACKOFF_INVALIDATED
                    elif identity.lifecycle == "retrying":
                        backoff_note = LOCAL_UPDATE_NOTE_STALE_BACKOFF_RETRYING
                    notes = [LOCAL_UPDATE_NOTE_STALE_RETRY_AUTO]
                    if backoff_note:
                        notes.append(backoff_note)
                    plan.candidates.append(
                        LocalModUpdateCandidate(
                            project_id="",
                            project_name=unresolved_label or "過期 metadata 模組",
                            filename=filename_key,
                            current_version=str(getattr(local_mod, "version", "") or "").strip(),
                            current_hash=local_hash,
                            hash_algorithm=hash_algorithm,
                            recommendation_source=RECOMMENDATION_SOURCE_STALE_METADATA,
                            recommendation_confidence=confidence,
                            hard_errors=[hard_error],
                            notes=notes,
                            metadata_source=METADATA_SOURCE_STALE_PROVIDER,
                            metadata_note=LOCAL_UPDATE_METADATA_NOTE_STALE_REVALIDATION_FAILED,
                            metadata_resolved=False,
                            provider_identity=identity,
                            local_mod=local_mod,
                        )
                    )
                    continue
                if unresolved_label:
                    unresolved_mod_labels.append(unresolved_label)
                plan.candidates.append(
                    LocalModUpdateCandidate(
                        project_id="",
                        project_name=unresolved_label or "未識別模組",
                        filename=filename_key,
                        current_version=str(getattr(local_mod, "version", "") or "").strip(),
                        current_hash=local_hash,
                        hash_algorithm=hash_algorithm,
                        recommendation_source=RECOMMENDATION_SOURCE_METADATA_UNRESOLVED,
                        recommendation_confidence=RECOMMENDATION_CONFIDENCE_BLOCKED,
                        hard_errors=[LOCAL_UPDATE_ERROR_METADATA_UNRESOLVED],
                        notes=[LOCAL_UPDATE_NOTE_METADATA_UNRESOLVED],
                        metadata_source=METADATA_SOURCE_UNRESOLVED,
                        metadata_note="metadata ensure 失敗：找不到可用的 provider metadata 或雜湊對應結果",
                        metadata_resolved=False,
                        provider_identity=identity,
                        local_mod=local_mod,
                    )
                )
                continue
            if filename_key:
                resolved_project_info_by_filename[filename_key] = resolved_project_info
                provider_identity_by_filename[filename_key] = identity
                metadata_source_by_filename[filename_key] = metadata_source
            project_id = clean_api_identifier(getattr(resolved_project_info, "project_id", ""))
            if project_id:
                project_ids.append(project_id)
        project_name_map = self.provider.resolve_project_names(project_ids)
        for local_mod in installed_mods:
            filename_key = str(getattr(local_mod, "filename", "") or "").strip()
            resolved_project_info = resolved_project_info_by_filename.get(filename_key)
            project_id = clean_api_identifier(getattr(resolved_project_info, "project_id", ""))
            if not project_id:
                continue
            project_key = normalize_identifier(project_id)
            project_name = (
                project_name_map.get(project_key, "").strip()
                or str(getattr(resolved_project_info, "name", "") or "").strip()
                or str(getattr(local_mod, "name", "") or project_id).strip()
            )
            current_version = str(getattr(local_mod, "version", "") or "").strip()
            local_metadata_advisories = analyze_local_mod_file_compatibility(local_mod, loader)
            local_hash = local_hashes_by_filename.get(filename_key, "")
            current_match = current_versions_by_hash.get(local_hash)
            latest_match = latest_versions_by_hash.get(local_hash)
            recommended_version = latest_match.version if latest_match is not None else None
            hash_metadata_resolved = bool(local_hash and (current_match is not None or latest_match is not None))
            used_project_fallback = False
            if recommended_version is None and supports_online_loader_updates and (not hash_metadata_resolved):
                recommended_version = self.provider.get_recommended_version(project_id, minecraft_version, loader)
                used_project_fallback = recommended_version is not None
            recommendation_source, recommendation_confidence = _resolve_local_update_recommendation_strategy(
                used_project_fallback=used_project_fallback, metadata_resolved=True
            )
            if recommended_version is None:
                if local_metadata_advisories:
                    preview = "；".join(local_metadata_advisories[:2])
                    suffix = "；其餘提示已省略" if len(local_metadata_advisories) > 2 else ""
                    plan.notes.append(f"{project_name}：{preview}（僅作提示，不影響更新判定）{suffix}")
                continue
            report = self.analyze_version(
                recommended_version,
                project_id=project_id,
                project_name=project_name,
                minecraft_version=minecraft_version,
                loader=loader,
                loader_version=loader_version,
                installed_mods=installed_mods,
            )
            dependency_issues = [
                *list(report.missing_required_dependencies),
                *list(report.installed_version_mismatches),
                *list(report.incompatible_installed),
            ]
            notes = list(report.notes)
            if used_project_fallback:
                notes.append(LOCAL_UPDATE_NOTE_PROJECT_FALLBACK_ADVISORY)
            if local_metadata_advisories:
                notes.extend(f"本地 metadata 提示：{advisory}" for advisory in local_metadata_advisories)
            if report.optional_dependencies:
                notes.append(f"可選依賴：{', '.join(report.optional_dependencies)}")
            metadata_source = metadata_source_by_filename.get(filename_key, "")
            metadata_note = {
                METADATA_SOURCE_HASH: "metadata 來源：使用本地檔案雜湊直接對應到 Modrinth 專案",
                METADATA_SOURCE_CACHED_PROVIDER: "metadata 來源：使用已快取的 provider metadata / project id",
                METADATA_SOURCE_LOOKUP: "metadata 來源：使用專案識別查詢補齊",
            }.get(metadata_source, "")
            primary_file = recommended_version.primary_file or {}
            target_version_name = str(
                recommended_version.display_name or recommended_version.version_number or ""
            ).strip()
            target_filename = str(primary_file.get("filename", "") or "").strip()
            download_url = str(primary_file.get("url", "") or "").strip()
            target_file_hash = extract_primary_file_hash(recommended_version, hash_algorithm)
            if current_match is not None:
                current_version = str(
                    current_match.version.display_name or current_match.version.version_number or ""
                ).strip()
            elif used_project_fallback:
                notes.append(LOCAL_UPDATE_NOTE_CURRENT_VERSION_UNVERIFIED)
            if latest_match is None and local_hash and target_file_hash and (local_hash == target_file_hash):
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
                recommendation_source=recommendation_source,
                recommendation_confidence=recommendation_confidence,
                current_issues=[],
                dependency_issues=dependency_issues,
                hard_errors=list(report.hard_errors),
                notes=notes,
                metadata_source=metadata_source,
                metadata_note=metadata_note,
                metadata_resolved=True,
                provider_identity=provider_identity_by_filename.get(filename_key),
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
                f"有 {len(unresolved_mod_labels)} 個本地模組暫時無法對應到 Modrinth 專案，本次先略過自動更新，後續檢查會自動再試：{preview}{suffix}"
            )
        else:
            plan.metadata_summary.unresolved = 0
        plan.metadata_summary.notes.append(
            f"metadata ensure 結果：共檢查 {plan.metadata_summary.total_scanned} 個本地模組，其中 {plan.metadata_summary.resolved_by_hash} 個以雜湊直接識別，{plan.metadata_summary.resolved_by_cached_project} 個使用已快取 metadata，{plan.metadata_summary.resolved_by_lookup} 個需額外查詢，{plan.metadata_summary.unresolved} 個仍無法識別"
        )
        if not plan.candidates and (not plan.notes):
            plan.notes.append(LOCAL_UPDATE_NOTE_IDENTIFIED_NO_UPDATE)
        plan.finalize_summary()
        return plan


@dataclass(slots=True)
class _DependencyPlanningService:
    """集中管理必要依賴規劃"""

    provider: ModPlanningProviderPort
    loader_rules: LoaderRulesPort
    minecraft_version: str | None = None
    loader: str | None = None
    loader_version: str | None = None
    installed_mods: list[Any] | None = None
    version_details_cache: dict[str, tuple[str, OnlineModVersion | None]] = field(default_factory=dict)

    def select_dependency_best_version(
        self,
        resolved_dependency: ResolvedDependencyReference,
        log_filtered_fallback: bool,
    ) -> OnlineModVersion | None:
        dependency_api_project_id = clean_api_identifier(resolved_dependency.project_id)
        if not dependency_api_project_id:
            return None
        if resolved_dependency.version is not None:
            dependency_versions = [resolved_dependency.version]
        else:
            dependency_versions = self.provider.get_versions(
                dependency_api_project_id,
                self.minecraft_version,
                self.loader,
            )
            if not dependency_versions:
                if log_filtered_fallback:
                    logger.warning(
                        f"以目前條件找不到必要依賴版本，回退為未過濾查詢: {resolved_dependency.label} ({resolved_dependency.compare_project_id})"
                    )
                dependency_versions = self.provider.get_versions(dependency_api_project_id)
        return select_best_mod_version(dependency_versions)

    def extract_dependency_download_target(self, best_version: OnlineModVersion) -> tuple[str, str] | None:
        """
        提取依賴版本的下載網址與檔名

        Args:
            best_version: 目標依賴版本

        Returns:
            可下載時回傳(download_url, filename)，否則回傳 None
        """
        primary_file = best_version.primary_file
        if not primary_file:
            return None
        download_url = str(primary_file.get("url", "") or "").strip()
        filename = str(primary_file.get("filename", "") or "").strip()
        if not download_url or not filename:
            return None
        return (download_url, filename)

    def make_dependency_install_item(
        self,
        resolved_dependency: ResolvedDependencyReference,
        dependency_label: str,
        best_version: OnlineModVersion,
        download_url: str,
        filename: str,
        parent_name: str,
        *,
        maybe_installed: bool,
        status_note: str,
        included_by_default: bool,
        is_optional: bool,
        decision_source: str,
        graph_depth: int,
        edge_kind: str,
        edge_source: str,
    ) -> OnlineDependencyInstallItem:
        """
        建立可直接交給安裝流程的依賴安裝項目

        Args:
            resolved_dependency: 已解析的依賴參考
            dependency_label: 依賴顯示名稱
            best_version: 選出的最佳依賴版本
            download_url: 下載網址
            filename: 檔名
            parent_name: 觸發此依賴的父模組名稱
            maybe_installed: 是否可能已安裝
            status_note: 額外狀態說明
            included_by_default: 規劃器是否預設納入
            is_optional: 是否屬於可選依賴
            decision_source: 決策來源
            graph_depth: 依賴圖深度
            edge_kind: 依賴邊型別
            edge_source: 依賴邊來源

        Returns:
            已完整填入的依賴安裝項目
        """
        expected_hash = extract_primary_file_hash(best_version) or extract_primary_file_hash(best_version, "sha256")
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
            included_by_default=included_by_default,
            is_optional=is_optional,
            provider=str(getattr(best_version, "provider", "modrinth") or "modrinth").strip() or "modrinth",
            expected_hash=expected_hash,
            required_by=[parent_name] if parent_name else [],
            decision_source=str(decision_source or "").strip() or "required:auto",
            graph_depth=max(1, int(graph_depth)),
            edge_kind=str(edge_kind or "required").strip().lower() or "required",
            edge_source=str(edge_source or "").strip().lower()
            or f"{str(edge_kind or 'required').strip().lower() or 'required'}:modrinth_dependency",
        )


def _expand_dependency_plan(
    *,
    root_version: OnlineModVersion,
    plan: OnlineDependencyInstallPlan,
    planning_service: _DependencyPlanningService,
    installed_project_ids: set[str],
    installed_versions_by_project: dict[str, set[str]],
    installed_mods: list[Any] | None,
    root_project_id: str = "",
    root_project_name: str = "",
    max_depth: int = 20,
    log_debug: Callable[[str], None] | None = None,
    log_info: Callable[[str], None] | None = None,
) -> None:
    """
    展開必要依賴安裝計畫，處理循環、版本檢查與 advisory 分流

    Args:
        root_version: 起始模組版本
        plan: 要填入結果的依賴安裝計畫
        planning_service: 規劃 implementation 內部協作者
        installed_project_ids: 已安裝 project id（normalize 後）
        installed_versions_by_project: 已安裝版本索引
        installed_mods: 已安裝模組原始清單
        root_project_id: 根專案 id
        root_project_name: 根專案名稱
        max_depth: 依賴遞迴深度上限
        log_debug: debug 記錄函式
        log_info: info 記錄函式
    """
    planned_project_ids: set[str] = set()
    normalized_root_project_id = normalize_identifier(root_project_id)

    def _log_debug(message: str) -> None:
        if log_debug is not None:
            log_debug(message)

    def _log_info(message: str) -> None:
        if log_info is not None:
            log_info(message)

    def _resolve_planned_dependency(
        dependency: dict[str, Any],
        dependency_names: dict[str, str],
    ) -> ResolvedDependencyReference:
        return _resolve_reference(
            dependency,
            dependency_names,
            version_details_cache=planning_service.version_details_cache,
            provider=planning_service.provider,
        )

    def _analyze_planned_dependency(
        version: OnlineModVersion,
        resolved_dependency: ResolvedDependencyReference,
        dependency_label: str,
        dependency_names: dict[str, str],
    ) -> OnlineModCompatibilityReport:
        return _analyze_version_data(
            version,
            project_id=resolved_dependency.project_id,
            project_name=dependency_label,
            minecraft_version=planning_service.minecraft_version,
            loader=planning_service.loader,
            loader_version=planning_service.loader_version,
            installed_mods=planning_service.installed_mods,
            dependency_names=dependency_names,
            provider=planning_service.provider,
            loader_rules=planning_service.loader_rules,
        )

    def walk_dependencies(
        current_version: OnlineModVersion,
        parent_name: str,
        depth: int,
        active_stack: set[str],
    ) -> None:
        if depth > max_depth:
            plan.unresolved_required.append(f"{parent_name} 的依賴深度超過上限，系統已先安全略過")
            return

        required_dependencies = [
            dependency
            for dependency in current_version.dependencies
            if isinstance(dependency, dict)
            and normalize_identifier(str(dependency.get("dependency_type", "required") or "required")) == "required"
        ]
        optional_dependencies = [
            dependency
            for dependency in current_version.dependencies
            if isinstance(dependency, dict)
            and normalize_identifier(str(dependency.get("dependency_type", "") or "")) == "optional"
        ]
        if not required_dependencies and (not optional_dependencies):
            return

        dependency_project_ids = {
            clean_api_identifier(str(dependency.get("project_id", "") or ""))
            for dependency in [*required_dependencies, *optional_dependencies]
            if str(dependency.get("project_id", "") or "").strip()
        }
        dependency_names = planning_service.provider.resolve_project_names(dependency_project_ids)

        for dependency in required_dependencies:
            resolved_dependency = _resolve_planned_dependency(dependency, dependency_names)
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
                required_version = normalize_identifier(
                    getattr(resolved_dependency.version, "version_number", "") or resolved_dependency.version_name
                )
                installed_versions = sorted(installed_versions_by_project.get(dependency_project_id, set()))
                if required_version and required_version not in installed_versions:
                    installed_version_text = ", ".join(installed_versions) if installed_versions else "未知版本"
                    plan.unresolved_required.append(
                        f"{dependency_label} 已安裝版本不符：需要 {resolved_dependency.version_name or required_version}，目前為 {installed_version_text}"
                    )
                    continue
                _log_debug(f"必要依賴已存在，略過自動安裝: {dependency_label} ({dependency_project_id})")
                continue

            maybe_installed = dependency_maybe_installed_by_filename(resolved_dependency, installed_mods)
            if dependency_project_id in planned_project_ids:
                _log_debug(f"必要依賴已加入安裝計畫，略過重複項目: {dependency_label} ({dependency_project_id})")
                continue

            best_version = planning_service.select_dependency_best_version(resolved_dependency, True)
            if best_version is None:
                plan.unresolved_required.append(f"找不到 {dependency_label} 的可下載版本")
                continue

            dependency_report = _analyze_planned_dependency(
                best_version,
                resolved_dependency,
                dependency_label,
                dependency_names,
            )
            hard_errors = list(getattr(dependency_report, "hard_errors", []) or [])
            if hard_errors:
                plan.unresolved_required.append(f"{dependency_label} 無法自動安裝：{hard_errors[0]}")
                continue

            download_target = planning_service.extract_dependency_download_target(best_version)
            if download_target is None:
                plan.unresolved_required.append(f"{dependency_label} 缺少可下載的 JAR 檔案")
                continue
            download_url, filename = download_target

            planned_project_ids.add(dependency_project_id)
            install_item = planning_service.make_dependency_install_item(
                resolved_dependency,
                dependency_label,
                best_version,
                download_url,
                filename,
                parent_name,
                maybe_installed=maybe_installed,
                status_note="可能已存在本地相近檔名，依 Prism Launcher 做法預設略過自動安裝" if maybe_installed else "",
                included_by_default=not maybe_installed,
                is_optional=False,
                decision_source="required:maybe_installed" if maybe_installed else "required:auto",
                graph_depth=depth + 1,
                edge_kind="required",
                edge_source="required:modrinth_dependency",
            )
            if maybe_installed:
                plan.advisory_items.append(install_item)
                plan.notes.append(f"{dependency_label} 可能已存在本地相近檔名，已預設略過自動安裝並保留後續重查")
                _log_info(
                    f"必要依賴疑似已安裝，預設略過自動安裝: parent={parent_name}, dependency={dependency_label}, version={best_version.display_name}"
                )
            else:
                plan.items.append(install_item)
                _log_info(
                    f"已加入必要依賴安裝計畫: parent={parent_name}, dependency={dependency_label}, version={best_version.display_name}"
                )

            next_stack = set(active_stack)
            next_stack.add(dependency_project_id)
            walk_dependencies(best_version, dependency_label, depth + 1, next_stack)

        for dependency in optional_dependencies:
            resolved_dependency = _resolve_planned_dependency(dependency, dependency_names)
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

            maybe_installed = dependency_maybe_installed_by_filename(resolved_dependency, installed_mods)
            best_version = planning_service.select_dependency_best_version(resolved_dependency, False)
            if best_version is None:
                plan.notes.append(f"可選依賴目前查無可用版本：{dependency_label}")
                continue

            dependency_report = _analyze_planned_dependency(
                best_version,
                resolved_dependency,
                dependency_label,
                dependency_names,
            )
            optional_hard_errors = list(getattr(dependency_report, "hard_errors", []) or [])
            if optional_hard_errors:
                plan.notes.append(f"可選依賴暫時無法自動安裝：{dependency_label}（{optional_hard_errors[0]}）")
                continue

            download_target = planning_service.extract_dependency_download_target(best_version)
            if download_target is None:
                plan.notes.append(f"可選依賴缺少可下載 JAR：{dependency_label}")
                continue
            download_url, filename = download_target

            planned_project_ids.add(dependency_project_id)
            plan.advisory_items.append(
                planning_service.make_dependency_install_item(
                    resolved_dependency,
                    dependency_label,
                    best_version,
                    download_url,
                    filename,
                    parent_name,
                    maybe_installed=maybe_installed,
                    status_note="可選依賴，預設略過，可於 Review 勾選後一同安裝",
                    included_by_default=False,
                    is_optional=True,
                    decision_source="optional:advisory_default_disabled",
                    graph_depth=depth + 1,
                    edge_kind="optional",
                    edge_source="optional:modrinth_dependency",
                )
            )

    initial_stack: set[str] = {normalized_root_project_id} if normalized_root_project_id else set()
    walk_dependencies(root_version, root_project_name or root_project_id or "根模組", 0, initial_stack)


__all__ = ["ModPlanning"]
