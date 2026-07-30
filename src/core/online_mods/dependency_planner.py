"""依賴規劃與本地更新 facade。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ...models import (
    LocalModUpdateCandidate,
    LocalModUpdatePlan,
    ModrinthVersionLookupResult,
    OnlineDependencyInstallItem,
    OnlineDependencyInstallPlan,
    OnlineModCompatibilityReport,
    OnlineModInfo,
    OnlineModVersion,
    ResolvedDependencyReference,
)
from ...utils import (
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
    clean_api_identifier,
    collect_installed_mod_identifiers,
    collect_installed_mod_versions,
    compute_file_hash,
    dependency_maybe_installed_by_filename,
    extract_primary_file_hash,
    get_shared_manager,
    is_supported_modrinth_update_loader,
    normalize_hash_algorithm,
    normalize_identifier,
    normalize_local_loader,
    select_best_mod_version,
)
from .. import (
    PROVIDER_LIFECYCLE_INVALIDATED,
    PROVIDER_LIFECYCLE_RETRYING,
    PROVIDER_REVALIDATION_BATCH_MAX_PER_RUN,
    ProviderMetadataRecord,
    apply_provider_metadata,
    ensure_local_mod_provider_record,
    is_provider_revalidation_retry_due,
    resolve_modrinth_provider_record,
)
from .compatibility_analyzer import (
    analyze_local_mod_file_compatibility,
    analyze_mod_version_compatibility,
    resolve_dependency_reference_with_provider_context,
)
from .constants import logger
from .modrinth_service import (
    build_provider_record_from_online_mod,
    fetch_modrinth_project_name,
    get_mod_version_details,
    get_mod_versions,
    get_modrinth_current_versions_by_hashes,
    get_modrinth_latest_versions_by_hashes,
    get_recommended_mod_version,
    normalize_cached_provider_identity,
    resolve_local_mod_project_info,
    resolve_modrinth_project_names,
)
from .revalidation_service import ProviderMetadataRevalidationService


def _resolve_local_update_recommendation_strategy(
    *, used_project_fallback: bool, metadata_resolved: bool
) -> tuple[str, str]:
    if not metadata_resolved:
        return (RECOMMENDATION_SOURCE_METADATA_UNRESOLVED, RECOMMENDATION_CONFIDENCE_BLOCKED)
    if used_project_fallback:
        return (RECOMMENDATION_SOURCE_PROJECT_FALLBACK, RECOMMENDATION_CONFIDENCE_ADVISORY)
    return (RECOMMENDATION_SOURCE_HASH_METADATA, RECOMMENDATION_CONFIDENCE_HIGH)


@dataclass(slots=True)
class DependencyPlanningService:
    """集中管理必要依賴規劃所需的查詢與轉換邏輯。"""

    minecraft_version: str | None = None
    loader: str | None = None
    loader_version: str | None = None
    installed_mods: list[Any] | None = None
    version_details_cache: dict[str, tuple[str, OnlineModVersion | None]] = field(default_factory=dict)

    def resolve_dependency_entry(
        self,
        dependency: dict[str, Any],
        dependency_names: dict[str, str],
    ) -> ResolvedDependencyReference:
        """
        解析單一依賴節點所需的 provider 與命名資訊。

        Args:
            dependency: 原始依賴描述字典。
            dependency_names: 依賴 project id 到名稱的對照表。

        Returns:
            已正規化的依賴參考物件。
        """

        return resolve_dependency_reference_with_provider_context(
            dependency,
            dependency_names,
            version_details_cache=self.version_details_cache,
            get_mod_version_details_fn=get_mod_version_details,
            fetch_project_name_fn=fetch_modrinth_project_name,
        )

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
            dependency_versions = get_mod_versions(
                dependency_api_project_id,
                self.minecraft_version,
                self.loader,
            )
            if not dependency_versions:
                if log_filtered_fallback:
                    logger.warning(
                        f"以目前條件找不到必要依賴版本，回退為未過濾查詢: {resolved_dependency.label} ({resolved_dependency.compare_project_id})"
                    )
                dependency_versions = get_mod_versions(dependency_api_project_id)
        return select_best_mod_version(dependency_versions)

    def analyze_dependency_best_version(
        self,
        best_version: OnlineModVersion,
        resolved_dependency: ResolvedDependencyReference,
        dependency_label: str,
        dependency_names: dict[str, str],
    ) -> OnlineModCompatibilityReport:
        """
        分析最佳依賴版本與目前伺服器環境的相容性。

        Args:
            best_version: 選出的最佳依賴版本。
            resolved_dependency: 已解析的依賴參考。
            dependency_label: 依賴顯示名稱。
            dependency_names: 依賴 project id 到名稱的對照表。

        Returns:
            相容性分析結果。
        """

        return analyze_mod_version_compatibility(
            best_version,
            project_id=resolved_dependency.project_id,
            project_name=dependency_label,
            minecraft_version=self.minecraft_version,
            loader=self.loader,
            loader_version=self.loader_version,
            installed_mods=self.installed_mods,
            dependency_names=dependency_names,
            get_mod_version_details_fn=get_mod_version_details,
            fetch_project_name_fn=fetch_modrinth_project_name,
        )

    def extract_dependency_download_target(self, best_version: OnlineModVersion) -> tuple[str, str] | None:
        """
        提取依賴版本的下載網址與檔名。

        Args:
            best_version: 目標依賴版本。

        Returns:
            可下載時回傳 `(download_url, filename)`，否則回傳 None。
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
        enabled: bool,
        is_optional: bool,
        decision_source: str,
        graph_depth: int,
        edge_kind: str,
        edge_source: str,
    ) -> OnlineDependencyInstallItem:
        """
        建立可直接交給安裝流程的依賴安裝項目。

        Args:
            resolved_dependency: 已解析的依賴參考。
            dependency_label: 依賴顯示名稱。
            best_version: 選出的最佳依賴版本。
            download_url: 下載網址。
            filename: 檔名。
            parent_name: 觸發此依賴的父模組名稱。
            maybe_installed: 是否可能已安裝。
            status_note: 額外狀態說明。
            enabled: 預設是否啟用。
            is_optional: 是否屬於可選依賴。
            decision_source: 決策來源。
            graph_depth: 依賴圖深度。
            edge_kind: 依賴邊型別。
            edge_source: 依賴邊來源。

        Returns:
            已完整填入的依賴安裝項目。
        """

        expected_hash = (
            extract_primary_file_hash(best_version)
            or extract_primary_file_hash(best_version, "sha256")
            or extract_primary_file_hash(best_version, "sha1")
        )
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
            provider=str(getattr(best_version, "provider", "modrinth") or "modrinth").strip() or "modrinth",
            expected_hash=expected_hash,
            required_by=[parent_name] if parent_name else [],
            decision_source=str(decision_source or "").strip() or "required:auto",
            graph_depth=max(1, int(graph_depth)),
            edge_kind=str(edge_kind or "required").strip().lower() or "required",
            edge_source=str(edge_source or "").strip().lower()
            or f"{str(edge_kind or 'required').strip().lower() or 'required'}:modrinth_dependency",
        )

    def expand_required_dependency_install_plan(
        self,
        *,
        root_version: OnlineModVersion,
        plan: OnlineDependencyInstallPlan,
        installed_project_ids: set[str],
        installed_versions_by_project: dict[str, set[str]],
        installed_mods: list[Any] | None,
        root_project_id: str = "",
        root_project_name: str = "",
        max_depth: int = 20,
        log_debug: Callable[[str], None] | None = None,
        log_info: Callable[[str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        """
        展開必要依賴安裝計畫，處理循環、版本檢查與 advisory 分流。

        Args:
            root_version: 起始模組版本。
            plan: 要填入結果的依賴安裝計畫。
            hooks: 外部依賴 callback 集合。
            installed_project_ids: 已安裝 project id（normalize 後）。
            installed_versions_by_project: 已安裝版本索引。
            installed_mods: 已安裝模組原始清單。
            root_project_id: 根專案 id。
            root_project_name: 根專案名稱。
            max_depth: 依賴遞迴深度上限。
            log_debug: debug 記錄函式。
            log_info: info 記錄函式。
        """

        planned_project_ids: set[str] = set()
        normalized_root_project_id = normalize_identifier(root_project_id)

        def _log_debug(message: str) -> None:
            if log_debug is not None:
                log_debug(message)

        def _log_info(message: str) -> None:
            if log_info is not None:
                log_info(message)

        def walk_dependencies(
            current_version: OnlineModVersion,
            parent_name: str,
            depth: int,
            active_stack: set[str],
        ) -> None:
            if is_cancelled and is_cancelled():
                plan.unresolved_required.append("已取消依賴規劃")
                return
            if progress_callback:
                progress_callback(f"規劃中... {parent_name}")
            if depth > max_depth:
                plan.unresolved_required.append(f"{parent_name} 的依賴深度超過上限，系統已先安全略過。")
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
            dependency_names = resolve_modrinth_project_names(dependency_project_ids)

            for dependency in required_dependencies:
                resolved_dependency = self.resolve_dependency_entry(dependency, dependency_names)
                dependency_project_id = resolved_dependency.compare_project_id
                dependency_label = resolved_dependency.label
                if not dependency_project_id:
                    plan.unresolved_required.append(
                        f"{parent_name} 缺少可解析 project id 的必要依賴：{dependency_label}"
                    )
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
                            f"{dependency_label} 已安裝版本不符：需要 {resolved_dependency.version_name or required_version}，目前為 {installed_version_text}。"
                        )
                        continue
                    _log_debug(f"必要依賴已存在，略過自動安裝: {dependency_label} ({dependency_project_id})")
                    continue

                maybe_installed = dependency_maybe_installed_by_filename(resolved_dependency, installed_mods)
                if dependency_project_id in planned_project_ids:
                    _log_debug(f"必要依賴已加入安裝計畫，略過重複項目: {dependency_label} ({dependency_project_id})")
                    continue

                best_version = self.select_dependency_best_version(resolved_dependency, True)
                if best_version is None:
                    plan.unresolved_required.append(f"找不到 {dependency_label} 的可下載版本。")
                    continue

                dependency_report = self.analyze_dependency_best_version(
                    best_version, resolved_dependency, dependency_label, dependency_names
                )
                hard_errors = list(getattr(dependency_report, "hard_errors", []) or [])
                if hard_errors:
                    first_reason = hard_errors[0]
                    plan.unresolved_required.append(f"{dependency_label} 無法自動安裝：{first_reason}")
                    continue

                download_target = self.extract_dependency_download_target(best_version)
                if download_target is None:
                    plan.unresolved_required.append(f"{dependency_label} 缺少可下載的 JAR 檔案。")
                    continue
                download_url, filename = download_target

                planned_project_ids.add(dependency_project_id)
                install_item = self.make_dependency_install_item(
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
                    decision_source="required:maybe_installed" if maybe_installed else "required:auto",
                    graph_depth=depth + 1,
                    edge_kind="required",
                    edge_source="required:modrinth_dependency",
                )
                if maybe_installed:
                    plan.advisory_items.append(install_item)
                    plan.notes.append(f"{dependency_label} 可能已存在本地相近檔名，已預設略過自動安裝並保留後續重查。")
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
                resolved_dependency = self.resolve_dependency_entry(dependency, dependency_names)
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
                best_version = self.select_dependency_best_version(resolved_dependency, False)
                if best_version is None:
                    plan.notes.append(f"可選依賴目前查無可用版本：{dependency_label}")
                    continue

                dependency_report = self.analyze_dependency_best_version(
                    best_version, resolved_dependency, dependency_label, dependency_names
                )
                optional_hard_errors = list(getattr(dependency_report, "hard_errors", []) or [])
                if optional_hard_errors:
                    optional_first_error = optional_hard_errors[0]
                    plan.notes.append(f"可選依賴暫時無法自動安裝：{dependency_label}（{optional_first_error}）")
                    continue

                download_target = self.extract_dependency_download_target(best_version)
                if download_target is None:
                    plan.notes.append(f"可選依賴缺少可下載 JAR：{dependency_label}")
                    continue
                download_url, filename = download_target

                planned_project_ids.add(dependency_project_id)
                plan.advisory_items.append(
                    self.make_dependency_install_item(
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
                        decision_source="optional:advisory_default_disabled",
                        graph_depth=depth + 1,
                        edge_kind="optional",
                        edge_source="optional:modrinth_dependency",
                    )
                )

        initial_stack: set[str] = {normalized_root_project_id} if normalized_root_project_id else set()
        walk_dependencies(root_version, root_project_name or root_project_id or "根模組", 0, initial_stack)


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
    is_cancelled: Callable[[], bool] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> OnlineDependencyInstallPlan:
    """
    為必要依賴建立可自動安裝的連鎖安裝計畫。

    Args:
        version: Modrinth 版本資訊。
        minecraft_version: 目標 Minecraft 版本。
        loader: 目標載入器類型。
        loader_version: 目標載入器版本。
        installed_mods: 已安裝模組清單。
        root_project_id: 根專案 id。
        root_project_name: 根專案名稱。
        max_depth: 依賴展開深度上限。

    Returns:
        必要依賴安裝計畫。
    """
    plan = OnlineDependencyInstallPlan()
    installed_project_ids, _ = collect_installed_mod_identifiers(installed_mods)
    installed_versions_by_project = collect_installed_mod_versions(installed_mods)
    planning_service = DependencyPlanningService(
        minecraft_version=minecraft_version,
        loader=loader,
        loader_version=loader_version,
        installed_mods=installed_mods,
    )

    planning_service.expand_required_dependency_install_plan(
        root_version=version,
        plan=plan,
        installed_project_ids=installed_project_ids,
        installed_versions_by_project=installed_versions_by_project,
        installed_mods=installed_mods,
        root_project_id=root_project_id,
        root_project_name=root_project_name,
        max_depth=max_depth,
        log_debug=logger.debug,
        log_info=logger.info,
        is_cancelled=is_cancelled,
        progress_callback=progress_callback,
    )
    logger.info(
        f"必要依賴安裝計畫建立完成: root={root_project_name or root_project_id or 'unknown'}, auto_install={plan.auto_install_count}, unresolved={len(plan.unresolved_required)}"
    )
    return plan


def build_local_mod_update_plan(
    local_mods: list[Any] | None,
    minecraft_version: str | None = None,
    loader: str | None = None,
    loader_version: str | None = None,
    hash_progress_callback: Callable[[int, int], None] | None = None,
    revalidation_batch_base_limit: int | None = None,
    revalidation_batch_min_limit: int = 1,
    revalidation_batch_max_limit: int | None = None,
    revalidation_adaptive_enabled: bool = True,
    revalidation_failure_high_watermark: float = 0.6,
    revalidation_failure_low_watermark: float = 0.25,
    revalidation_latency_threshold_ms: float = 800.0,
) -> LocalModUpdatePlan:
    """
    為本地模組建立更新檢查計畫，優先採用 Prism 風格的 hash-first 批次檢查。

    Args:
        local_mods: 本地模組清單。
        minecraft_version: 目標 Minecraft 版本。
        loader: 目標載入器類型。
        loader_version: 目標載入器版本。
        hash_progress_callback: hash 進度回呼。
        revalidation_batch_base_limit: 重查批次基準上限。
        revalidation_batch_min_limit: 重查批次最小上限。
        revalidation_batch_max_limit: 重查批次最大上限。
        revalidation_adaptive_enabled: 是否啟用自適應調整。
        revalidation_failure_high_watermark: 高失敗率門檻。
        revalidation_failure_low_watermark: 低失敗率門檻。
        revalidation_latency_threshold_ms: 延遲門檻毫秒數。

    Returns:
        本地模組更新檢查計畫。
    """
    plan = LocalModUpdatePlan()
    installed_mods = list(local_mods or [])
    plan.metadata_summary.total_scanned = len(installed_mods)
    normalized_target_loader = normalize_local_loader(loader)
    supports_online_loader_updates = is_supported_modrinth_update_loader(loader)
    if normalized_target_loader and (not supports_online_loader_updates):
        plan.notes.append(
            f"目前本地更新的線上比對僅支援 Fabric / Forge / Quilt / NeoForge，已略過 {loader} 的版本更新判定。"
        )
    hash_algorithm = MODRINTH_PREFERRED_HASH_ALGORITHM
    project_ids: list[str] = []
    resolved_project_info_by_filename: dict[str, OnlineModInfo] = {}
    metadata_source_by_filename: dict[str, str] = {}
    unresolved_mod_labels: list[str] = []
    local_hashes_by_filename: dict[str, str] = {}
    revalidation_service = ProviderMetadataRevalidationService(
        default_base_limit=PROVIDER_REVALIDATION_BATCH_MAX_PER_RUN,
        batch_base_limit=revalidation_batch_base_limit,
        batch_min_limit=revalidation_batch_min_limit,
        batch_max_limit=revalidation_batch_max_limit,
        adaptive_enabled=revalidation_adaptive_enabled,
        failure_high_watermark=revalidation_failure_high_watermark,
        failure_low_watermark=revalidation_failure_low_watermark,
        latency_threshold_ms=revalidation_latency_threshold_ms,
    )
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
            return (local_mod_obj, filename_key_obj, compute_file_hash(file_path_obj, hash_algorithm))

        manager = get_shared_manager()
        futures = [manager.run(_compute_local_hash, job) for job in hash_compute_jobs]
        for future in futures:
            local_mod, filename_key, local_hash = future.result()
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
    latest_versions_by_hash: dict[str, ModrinthVersionLookupResult] = {}
    if supports_online_loader_updates:
        latest_versions_by_hash = get_modrinth_latest_versions_by_hashes(
            known_hashes, hash_algorithm, minecraft_version=minecraft_version, loader=loader
        )
    for local_mod in installed_mods:
        filename_key = str(getattr(local_mod, "filename", "") or "").strip()
        local_hash = local_hashes_by_filename.get(filename_key, "")
        current_match = current_versions_by_hash.get(local_hash)
        latest_match = latest_versions_by_hash.get(local_hash)
        resolved_project_info = None
        metadata_source = ""
        raw_existing_project_id = clean_api_identifier(getattr(local_mod, "platform_id", ""))
        raw_existing_project_slug = str(getattr(local_mod, "platform_slug", "") or "").strip()
        existing_project_id, existing_project_slug, cached_provider_is_stale = normalize_cached_provider_identity(
            platform_id=raw_existing_project_id,
            platform_slug=raw_existing_project_slug,
            resolution_source=str(getattr(local_mod, "resolution_source", "") or "").strip(),
            resolved_at_epoch_ms=getattr(local_mod, "resolved_at_epoch_ms", None),
        )
        had_fresh_cached_identifier = bool(existing_project_id or existing_project_slug)
        if cached_provider_is_stale:
            revalidation_service.register_stale_provider()
        resolved_project_id = clean_api_identifier(
            getattr(current_match, "project_id", "") or getattr(latest_match, "project_id", "")
        )
        if resolved_project_id:
            apply_provider_metadata(local_mod, ProviderMetadataRecord.from_values(project_id=resolved_project_id))
            resolved_project_info = OnlineModInfo(project_id=resolved_project_id, slug="", name="", author="")
            metadata_source = METADATA_SOURCE_HASH
            plan.metadata_summary.resolved_by_hash += 1
        else:
            fallback_project_info: OnlineModInfo | None = None
            stale_revalidation_skip_reason = ""

            def _stale_local_mod_fallback_resolver() -> ProviderMetadataRecord | None:
                nonlocal fallback_project_info
                fallback_project_info = resolve_local_mod_project_info(local_mod)
                return build_provider_record_from_online_mod(fallback_project_info)

            if cached_provider_is_stale and (raw_existing_project_id or raw_existing_project_slug):
                revalidation_outcome = revalidation_service.revalidate(
                    local_mod=local_mod,
                    existing_project_id=existing_project_id,
                    existing_project_slug=existing_project_slug,
                    identifier_resolver=resolve_modrinth_provider_record,
                    fallback_resolver=_stale_local_mod_fallback_resolver,
                )
                ensured = revalidation_outcome.ensured
                stale_revalidation_skip_reason = revalidation_outcome.skip_reason
            else:
                ensured = ensure_local_mod_provider_record(
                    platform_id=existing_project_id,
                    platform_slug=existing_project_slug,
                    project_name=str(getattr(local_mod, "name", "") or "").strip(),
                    identifier_resolver=resolve_modrinth_provider_record,
                    fallback_resolver=_stale_local_mod_fallback_resolver,
                )
            apply_provider_metadata(local_mod, ensured.record)
            if ensured.record.project_id:
                metadata_source = (
                    METADATA_SOURCE_CACHED_PROVIDER
                    if ensured.source == METADATA_SOURCE_CACHED_PROVIDER or had_fresh_cached_identifier
                    else METADATA_SOURCE_LOOKUP
                )
                if metadata_source == METADATA_SOURCE_CACHED_PROVIDER:
                    plan.metadata_summary.resolved_by_cached_project += 1
                else:
                    plan.metadata_summary.resolved_by_lookup += 1
                resolved_project_info = fallback_project_info or OnlineModInfo(
                    project_id=ensured.record.project_id,
                    slug=ensured.record.slug,
                    name=ensured.record.project_name or str(getattr(local_mod, "name", "") or "").strip(),
                    author="",
                )
        if resolved_project_info is None:
            unresolved_label = str(
                getattr(local_mod, "name", "") or getattr(local_mod, "filename", "") or "模組"
            ).strip()
            if cached_provider_is_stale and (raw_existing_project_id or raw_existing_project_slug):
                revalidation_service.register_retryable_candidate()
                stale_identifier = raw_existing_project_id or raw_existing_project_slug
                lifecycle_state = str(getattr(local_mod, "provider_lifecycle_state", "") or "").strip().lower()
                retry_due = is_provider_revalidation_retry_due(
                    {
                        "next_retry_not_before_epoch_ms": str(
                            getattr(local_mod, "next_retry_not_before_epoch_ms", "") or ""
                        ).strip()
                    }
                )
                is_invalidated_backoff = lifecycle_state == PROVIDER_LIFECYCLE_INVALIDATED and (not retry_due)
                is_retrying_backoff = lifecycle_state == PROVIDER_LIFECYCLE_RETRYING and (not retry_due)
                confidence = RECOMMENDATION_CONFIDENCE_RETRYABLE
                hard_error = LOCAL_UPDATE_ERROR_STALE_REVALIDATION_FAILED
                backoff_note = ""
                if is_invalidated_backoff:
                    confidence = RECOMMENDATION_CONFIDENCE_BLOCKED
                    hard_error = LOCAL_UPDATE_ERROR_STALE_REVALIDATION_INVALIDATED
                    backoff_note = LOCAL_UPDATE_NOTE_STALE_BACKOFF_INVALIDATED
                elif is_retrying_backoff:
                    backoff_note = LOCAL_UPDATE_NOTE_STALE_BACKOFF_RETRYING
                notes = [LOCAL_UPDATE_NOTE_STALE_RETRY_AUTO]
                if backoff_note:
                    notes.append(backoff_note)
                if stale_revalidation_skip_reason == "batch_limit":
                    notes.append(
                        f"本輪重查已達批次上限（{revalidation_service.metrics.adaptive_revalidation_batch_limit}），此項將在後續檢查自動再試。"
                    )
                plan.candidates.append(
                    LocalModUpdateCandidate(
                        project_id=f"__stale__::{stale_identifier or filename_key or unresolved_label}",
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
                        local_mod=local_mod,
                    )
                )
                continue
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
                    recommendation_source=RECOMMENDATION_SOURCE_METADATA_UNRESOLVED,
                    recommendation_confidence=RECOMMENDATION_CONFIDENCE_BLOCKED,
                    hard_errors=[LOCAL_UPDATE_ERROR_METADATA_UNRESOLVED],
                    notes=[LOCAL_UPDATE_NOTE_METADATA_UNRESOLVED],
                    metadata_source=METADATA_SOURCE_UNRESOLVED,
                    metadata_note="metadata ensure 失敗：找不到可用的 provider metadata 或雜湊對應結果。",
                    metadata_resolved=False,
                    local_mod=local_mod,
                )
            )
            continue
        if filename_key:
            resolved_project_info_by_filename[filename_key] = resolved_project_info
            metadata_source_by_filename[filename_key] = metadata_source
        apply_provider_metadata(
            local_mod,
            ProviderMetadataRecord.from_values(
                project_id=clean_api_identifier(getattr(resolved_project_info, "project_id", "")),
                slug=str(getattr(resolved_project_info, "slug", "") or "").strip(),
                project_name=str(getattr(resolved_project_info, "name", "") or "").strip(),
            ),
        )
        project_id = clean_api_identifier(getattr(resolved_project_info, "project_id", ""))
        if project_id:
            project_ids.append(project_id)
    project_name_map = resolve_modrinth_project_names(project_ids)
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
        local_metadata_advisories = analyze_local_mod_file_compatibility(local_mod)
        local_hash = local_hashes_by_filename.get(filename_key, "")
        current_match = current_versions_by_hash.get(local_hash)
        latest_match = latest_versions_by_hash.get(local_hash)
        recommended_version = latest_match.version if latest_match is not None else None
        hash_metadata_resolved = bool(local_hash and (current_match is not None or latest_match is not None))
        used_project_fallback = False
        if recommended_version is None and supports_online_loader_updates and (not hash_metadata_resolved):
            recommended_version = get_recommended_mod_version(project_id, minecraft_version, loader)
            used_project_fallback = recommended_version is not None
        recommendation_source, recommendation_confidence = _resolve_local_update_recommendation_strategy(
            used_project_fallback=used_project_fallback, metadata_resolved=True
        )
        if recommended_version is None:
            if local_metadata_advisories:
                preview = "；".join(local_metadata_advisories[:2])
                suffix = "；其餘提示已省略。" if len(local_metadata_advisories) > 2 else ""
                plan.notes.append(f"{project_name}：{preview}（僅作提示，不影響更新判定）{suffix}")
            continue
        dependency_project_ids = {
            clean_api_identifier(str(dependency.get("project_id", "") or ""))
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
            get_mod_version_details_fn=get_mod_version_details,
            fetch_project_name_fn=fetch_modrinth_project_name,
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
            METADATA_SOURCE_HASH: "metadata 來源：使用本地檔案雜湊直接對應到 Modrinth 專案。",
            METADATA_SOURCE_CACHED_PROVIDER: "metadata 來源：使用已快取的 provider metadata / project id。",
            METADATA_SOURCE_LOOKUP: "metadata 來源：使用專案識別查詢補齊。",
        }.get(metadata_source, "")
        primary_file = recommended_version.primary_file or {}
        target_version_name = str(recommended_version.display_name or recommended_version.version_number or "").strip()
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
            f"有 {len(unresolved_mod_labels)} 個本地模組暫時無法對應到 Modrinth 專案，本次先略過自動更新，後續檢查會自動再試：{preview}{suffix}。"
        )
    else:
        plan.metadata_summary.unresolved = 0
    plan.metadata_summary.notes.append(
        f"metadata ensure 結果：共檢查 {plan.metadata_summary.total_scanned} 個本地模組，其中 {plan.metadata_summary.resolved_by_hash} 個以雜湊直接識別，{plan.metadata_summary.resolved_by_cached_project} 個使用已快取 metadata，{plan.metadata_summary.resolved_by_lookup} 個需額外查詢，{plan.metadata_summary.unresolved} 個仍無法識別。"
    )
    plan.metadata_summary.notes.extend(revalidation_service.build_summary_notes())
    if not plan.candidates and (not plan.notes):
        plan.notes.append(LOCAL_UPDATE_NOTE_IDENTIFIED_NO_UPDATE)
    plan.finalize_summary()
    return plan


__all__ = [
    "LocalModUpdateCandidate",
    "LocalModUpdatePlan",
    "build_local_mod_update_plan",
    "build_required_dependency_install_plan",
]
