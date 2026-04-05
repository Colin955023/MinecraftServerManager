from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.models import OnlineModVersion, ResolvedDependencyReference
from src.utils import (
    DependencyPlanHooks,
    OnlineDependencyInstallItem,
    OnlineDependencyInstallPlan,
    expand_required_dependency_install_plan,
)


def _make_version(
    version_id: str,
    display_name: str,
    *,
    dependencies: list[dict[str, Any]] | None = None,
    files: list[dict[str, Any]] | None = None,
) -> OnlineModVersion:
    return OnlineModVersion(
        version_id=version_id,
        version_number=display_name,
        display_name=display_name,
        dependencies=list(dependencies or []),
        files=list(files or []),
    )


def _make_install_item(
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
        provider="modrinth",
        required_by=[parent_name] if parent_name else [],
        decision_source=decision_source,
        graph_depth=graph_depth,
        edge_kind=edge_kind,
        edge_source=edge_source,
    )


def test_expand_required_dependency_install_plan_splits_required_and_optional() -> None:
    root_version = _make_version(
        "root-v",
        "1.0.0",
        dependencies=[
            {"project_id": "dep-required", "dependency_type": "required"},
            {"project_id": "dep-optional", "dependency_type": "optional"},
        ],
    )
    required_version = _make_version(
        "dep-required-v",
        "2.0.0",
        files=[{"url": "https://example.com/required.jar", "filename": "required.jar", "primary": True}],
    )
    optional_version = _make_version(
        "dep-optional-v",
        "3.0.0",
        files=[{"url": "https://example.com/optional.jar", "filename": "optional.jar", "primary": True}],
    )

    def _resolve_project_names(_: set[str]) -> dict[str, str]:
        return {"dep-required": "Required Dep", "dep-optional": "Optional Dep"}

    def _resolve_dependency_entry(
        dependency: dict[str, Any], dependency_names: dict[str, str]
    ) -> ResolvedDependencyReference:
        project_id = str(dependency.get("project_id", "") or "")
        project_key = project_id.strip().lower()
        return ResolvedDependencyReference(
            project_id=project_id,
            project_name=dependency_names.get(project_key, project_id),
        )

    def _select_dependency_best_version(
        resolved_dependency: ResolvedDependencyReference, _: bool
    ) -> OnlineModVersion | None:
        if resolved_dependency.project_id == "dep-required":
            return required_version
        if resolved_dependency.project_id == "dep-optional":
            return optional_version
        return None

    def _analyze_dependency_best_version(
        best_version: OnlineModVersion,
        resolved_dependency: ResolvedDependencyReference,
        dependency_label: str,
        dependency_names: dict[str, str],
    ) -> Any:
        _ = (best_version, resolved_dependency, dependency_label, dependency_names)
        return SimpleNamespace(hard_errors=[])

    def _extract_dependency_download_target(best_version: OnlineModVersion) -> tuple[str, str] | None:
        primary_file = best_version.primary_file
        if not primary_file:
            return None
        return (str(primary_file.get("url", "") or ""), str(primary_file.get("filename", "") or ""))

    plan = OnlineDependencyInstallPlan()
    expand_required_dependency_install_plan(
        root_version=root_version,
        plan=plan,
        hooks=DependencyPlanHooks(
            resolve_project_names=_resolve_project_names,
            resolve_dependency_entry=_resolve_dependency_entry,
            select_dependency_best_version=_select_dependency_best_version,
            analyze_dependency_best_version=_analyze_dependency_best_version,
            extract_dependency_download_target=_extract_dependency_download_target,
            make_dependency_install_item=_make_install_item,
            maybe_installed_checker=lambda *_: False,
        ),
        installed_project_ids=set(),
        installed_versions_by_project={},
        installed_mods=[],
        root_project_name="Root",
    )

    assert len(plan.items) == 1
    assert len(plan.advisory_items) == 1
    assert plan.items[0].project_name == "Required Dep"
    assert plan.items[0].decision_source == "required:auto"
    assert plan.advisory_items[0].project_name == "Optional Dep"
    assert plan.advisory_items[0].enabled is False
    assert plan.advisory_items[0].is_optional is True


def test_expand_required_dependency_install_plan_marks_installed_version_mismatch() -> None:
    root_version = _make_version(
        "root-v",
        "1.0.0",
        dependencies=[{"project_id": "dep-required", "dependency_type": "required"}],
    )
    required_bound_version = _make_version("dep-required-v", "2.0.0")

    def _resolve_dependency_entry(
        dependency: dict[str, Any], dependency_names: dict[str, str]
    ) -> ResolvedDependencyReference:
        _ = dependency_names
        return ResolvedDependencyReference(
            project_id=str(dependency.get("project_id", "") or ""),
            project_name="Required Dep",
            version=required_bound_version,
            version_name="2.0.0",
            resolution_source="version_detail",
            resolution_confidence="fallback",
        )

    def _unexpected_select(_: ResolvedDependencyReference, __: bool) -> OnlineModVersion | None:
        raise AssertionError("installed mismatch path should not select remote versions")

    plan = OnlineDependencyInstallPlan()
    expand_required_dependency_install_plan(
        root_version=root_version,
        plan=plan,
        hooks=DependencyPlanHooks(
            resolve_project_names=lambda _: {"dep-required": "Required Dep"},
            resolve_dependency_entry=_resolve_dependency_entry,
            select_dependency_best_version=_unexpected_select,
            analyze_dependency_best_version=lambda *_: SimpleNamespace(hard_errors=[]),
            extract_dependency_download_target=lambda *_: None,
            make_dependency_install_item=_make_install_item,
            maybe_installed_checker=lambda *_: False,
        ),
        installed_project_ids={"dep-required"},
        installed_versions_by_project={"dep-required": {"1.0.0"}},
        installed_mods=[],
        root_project_name="Root",
    )

    assert not plan.items
    assert not plan.advisory_items
    assert any("已安裝版本不符" in message for message in plan.unresolved_required)


def test_expand_required_dependency_install_plan_respects_max_depth() -> None:
    root_version = _make_version(
        "root-v",
        "1.0.0",
        dependencies=[{"project_id": "dep-a", "dependency_type": "required"}],
    )
    dep_a_version = _make_version(
        "dep-a-v",
        "2.0.0",
        dependencies=[{"project_id": "dep-b", "dependency_type": "required"}],
        files=[{"url": "https://example.com/dep-a.jar", "filename": "dep-a.jar", "primary": True}],
    )

    def _resolve_dependency_entry(
        dependency: dict[str, Any], dependency_names: dict[str, str]
    ) -> ResolvedDependencyReference:
        project_id = str(dependency.get("project_id", "") or "")
        return ResolvedDependencyReference(
            project_id=project_id, project_name=dependency_names.get(project_id, project_id)
        )

    def _select_dependency_best_version(
        resolved_dependency: ResolvedDependencyReference, _: bool
    ) -> OnlineModVersion | None:
        if resolved_dependency.project_id == "dep-a":
            return dep_a_version
        return None

    def _extract_dependency_download_target(best_version: OnlineModVersion) -> tuple[str, str] | None:
        primary_file = best_version.primary_file
        if not primary_file:
            return None
        return (str(primary_file.get("url", "") or ""), str(primary_file.get("filename", "") or ""))

    plan = OnlineDependencyInstallPlan()
    expand_required_dependency_install_plan(
        root_version=root_version,
        plan=plan,
        hooks=DependencyPlanHooks(
            resolve_project_names=lambda _: {"dep-a": "Dependency A", "dep-b": "Dependency B"},
            resolve_dependency_entry=_resolve_dependency_entry,
            select_dependency_best_version=_select_dependency_best_version,
            analyze_dependency_best_version=lambda *_: SimpleNamespace(hard_errors=[]),
            extract_dependency_download_target=_extract_dependency_download_target,
            make_dependency_install_item=_make_install_item,
            maybe_installed_checker=lambda *_: False,
        ),
        installed_project_ids=set(),
        installed_versions_by_project={},
        installed_mods=[],
        root_project_name="Root",
        max_depth=0,
    )

    assert len(plan.items) == 1
    assert any("依賴深度超過上限" in message for message in plan.unresolved_required)
