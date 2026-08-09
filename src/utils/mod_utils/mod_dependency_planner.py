"""依賴安裝計畫展開工具"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...models import DependencyPlanHooks, OnlineModVersion, ResolvedDependencyReference
from .dependency_plan_serializer import OnlineDependencyInstallPlan
from .modrinth_query_utils import (
    apply_loader_specific_dependency_override,
    clean_api_identifier,
    normalize_identifier,
)


def resolve_dependency_reference(
    dependency: dict[str, Any],
    dependency_names: dict[str, str],
    *,
    version_details_cache: dict[str, tuple[str, OnlineModVersion | None]] | None = None,
    get_mod_version_details: Callable[[str], tuple[str, OnlineModVersion | None]],
    fetch_project_name: Callable[[str], str | None],
) -> ResolvedDependencyReference:
    """
    解析單一依賴項目，統一 project id / version id 回填流程

    Args:
        dependency: 原始依賴資料
        dependency_names: 依賴名稱快取（key 為 normalize 後 project id）
        version_details_cache: 版本詳情快取，避免重複查詢 version id
        get_mod_version_details: 依 version id 取得 `(project_id, version)` 的函式
        fetch_project_name: 依 project id 查詢專案名稱的函式

    Returns:
        解析完成的依賴參照
    """
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
            cache[resolved.version_id] = get_mod_version_details(resolved.version_id)
        version_project_id, version_details = cache.get(resolved.version_id, ("", None))
        if version_details is not None:
            resolved.version = version_details
            resolved.version_name = str(version_details.display_name or version_details.version_number or "").strip()
        if not resolved.project_id and version_project_id:
            resolved.project_id = version_project_id
            resolved.resolution_source = "version_detail"
            resolved.resolution_confidence = "fallback"
    overridden_project_id = apply_loader_specific_dependency_override(resolved.project_id)
    if overridden_project_id and normalize_identifier(overridden_project_id) != resolved.compare_project_id:
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
            fetched_name = fetch_project_name(resolved.project_id)
            if fetched_name:
                dependency_names[resolved.compare_project_id] = fetched_name
                resolved.project_name = fetched_name
    return resolved


def expand_required_dependency_install_plan(
    *,
    root_version: OnlineModVersion,
    plan: OnlineDependencyInstallPlan,
    hooks: DependencyPlanHooks,
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
        hooks: 外部依賴 callback 集合
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
        dependency_names = hooks.resolve_project_names(dependency_project_ids)

        for dependency in required_dependencies:
            resolved_dependency = hooks.resolve_dependency_entry(dependency, dependency_names)
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

            maybe_installed = hooks.maybe_installed_checker(resolved_dependency, installed_mods)
            if dependency_project_id in planned_project_ids:
                _log_debug(f"必要依賴已加入安裝計畫，略過重複項目: {dependency_label} ({dependency_project_id})")
                continue

            best_version = hooks.select_dependency_best_version(resolved_dependency, True)
            if best_version is None:
                plan.unresolved_required.append(f"找不到 {dependency_label} 的可下載版本")
                continue

            dependency_report = hooks.analyze_dependency_best_version(
                best_version, resolved_dependency, dependency_label, dependency_names
            )
            hard_errors = list(getattr(dependency_report, "hard_errors", []) or [])
            if hard_errors:
                plan.unresolved_required.append(f"{dependency_label} 無法自動安裝：{hard_errors[0]}")
                continue

            download_target = hooks.extract_dependency_download_target(best_version)
            if download_target is None:
                plan.unresolved_required.append(f"{dependency_label} 缺少可下載的 JAR 檔案")
                continue
            download_url, filename = download_target

            planned_project_ids.add(dependency_project_id)
            install_item = hooks.make_dependency_install_item(
                resolved_dependency,
                dependency_label,
                best_version,
                download_url,
                filename,
                parent_name,
                maybe_installed=maybe_installed,
                status_note="可能已存在本地相近檔名，依 Prism Launcher 做法預設略過自動安裝" if maybe_installed else "",
                enabled=not maybe_installed,
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
            resolved_dependency = hooks.resolve_dependency_entry(dependency, dependency_names)
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

            maybe_installed = hooks.maybe_installed_checker(resolved_dependency, installed_mods)
            best_version = hooks.select_dependency_best_version(resolved_dependency, False)
            if best_version is None:
                plan.notes.append(f"可選依賴目前查無可用版本：{dependency_label}")
                continue

            dependency_report = hooks.analyze_dependency_best_version(
                best_version, resolved_dependency, dependency_label, dependency_names
            )
            optional_hard_errors = list(getattr(dependency_report, "hard_errors", []) or [])
            if optional_hard_errors:
                plan.notes.append(f"可選依賴暫時無法自動安裝：{dependency_label}（{optional_hard_errors[0]}）")
                continue

            download_target = hooks.extract_dependency_download_target(best_version)
            if download_target is None:
                plan.notes.append(f"可選依賴缺少可下載 JAR：{dependency_label}")
                continue
            download_url, filename = download_target

            planned_project_ids.add(dependency_project_id)
            plan.advisory_items.append(
                hooks.make_dependency_install_item(
                    resolved_dependency,
                    dependency_label,
                    best_version,
                    download_url,
                    filename,
                    parent_name,
                    maybe_installed=maybe_installed,
                    status_note="可選依賴，預設略過，可於 Review 勾選後一同安裝",
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
