from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import src.core.mods.modrinth_http as planning_adapter_module
from src.core import LoaderManagerRulesAdapter, ModPlanning, ModrinthHttpAdapter
from src.models import ModrinthVersionLookupResult, OnlineModVersion, ProviderCatalogOutcome
from src.utils import normalize_identifier


@dataclass(slots=True)
class _PlanningProviderStub:
    project_names: dict[str, str] = field(default_factory=dict)
    version_details: dict[str, tuple[str, OnlineModVersion | None]] = field(default_factory=dict)
    versions: dict[tuple[str, str, str], list[OnlineModVersion]] = field(default_factory=dict)

    def find_projects(
        self,
        query: str | Iterable[str],
        *,
        exact: bool = False,
        include_details: bool = False,
        **_search_options: Any,
    ) -> Any:
        if isinstance(query, str):
            if include_details:
                return None
            name = self.project_names.get(normalize_identifier(query))
            if exact:
                return (
                    ProviderCatalogOutcome(
                        "found",
                        project_id=query,
                        display_name=name or query,
                        confidence=100,
                    )
                    if name
                    else ProviderCatalogOutcome("not_found")
                )
            return ProviderCatalogOutcome("not_found")
        return {
            normalize_identifier(project_id): self.project_names[normalize_identifier(project_id)]
            for project_id in query
            if normalize_identifier(project_id) in self.project_names
        }

    def resolve_versions(
        self,
        project_id: str = "",
        minecraft_version: str | None = None,
        loader: str | None = None,
        *,
        version_id: str | None = None,
        recommended: bool = False,
    ) -> Any:
        if version_id is not None:
            return self.version_details.get(version_id, ("", None))
        if recommended:
            return None
        key = (normalize_identifier(project_id), str(minecraft_version or ""), normalize_identifier(loader))
        return list(self.versions.get(key, self.versions.get((key[0], "", ""), [])))

    def resolve_files(
        self,
        _hashes: Iterable[str],
        _algorithm: str,
        *,
        _latest: bool = False,
        _minecraft_version: str | None = None,
        _loader: str | None = None,
    ) -> dict[str, ModrinthVersionLookupResult]:
        return {}


class _LoaderRulesStub:
    def compatible_versions(self, _minecraft_version: str, _loader: str) -> list[str]:
        return []


def _version(
    version_id: str,
    display_name: str,
    *,
    dependencies: list[dict[str, Any]] | None = None,
    filename: str = "",
) -> OnlineModVersion:
    files = [{"url": f"https://example.com/{filename}", "filename": filename, "primary": True}] if filename else []
    return OnlineModVersion(
        version_id=version_id,
        version_number=display_name,
        display_name=display_name,
        dependencies=list(dependencies or []),
        files=files,
    )


def _planning(provider: _PlanningProviderStub) -> ModPlanning:
    return ModPlanning(provider, _LoaderRulesStub())


def test_mod_planning_splits_required_and_optional_dependencies() -> None:
    root = _version(
        "root-v",
        "1.0.0",
        dependencies=[
            {"project_id": "DepRequired", "dependency_type": "required"},
            {"project_id": "DepOptional", "dependency_type": "optional"},
        ],
    )
    provider = _PlanningProviderStub(
        project_names={"deprequired": "Required Dep", "depoptional": "Optional Dep"},
        versions={
            ("deprequired", "", ""): [_version("required-v", "2.0.0", filename="required.jar")],
            ("depoptional", "", ""): [_version("optional-v", "3.0.0", filename="optional.jar")],
        },
    )

    plan = _planning(provider).build_dependency_plan(root, root_project_name="Root")

    assert [(item.project_name, item.decision_source) for item in plan.items] == [("Required Dep", "required:auto")]
    assert [(item.project_name, item.included_by_default, item.is_optional) for item in plan.advisory_items] == [
        ("Optional Dep", False, True)
    ]


def test_mod_planning_resolves_dependency_references_with_per_operation_caches() -> None:
    version = _version("resolved-v", "1.0.0")

    class _CountingProvider(_PlanningProviderStub):
        def __init__(self) -> None:
            super().__init__(
                project_names={"project-a": "Project Alpha"},
                version_details={"version-lookup-1": ("Project-A", version)},
            )
            self.version_detail_calls = 0
            self.project_name_calls = 0

        def resolve_versions(self, *args: Any, version_id: str | None = None, **kwargs: Any) -> Any:
            self.version_detail_calls += 1
            return super().resolve_versions(*args, version_id=version_id, **kwargs)

        def find_projects(self, query: str | Iterable[str], **kwargs: Any) -> Any:
            self.project_name_calls += 1
            return super().find_projects(query, **kwargs)

    provider = _CountingProvider()
    root = _version(
        "root-v",
        "1.0.0",
        dependencies=[
            {"version_id": "version-lookup-1", "dependency_type": "required"},
            {"version_id": "version-lookup-1", "dependency_type": "required"},
            {"project_id": "Cached-Project", "dependency_type": "optional"},
            {"file_name": "optional-lib.jar", "dependency_type": "optional"},
        ],
    )

    report = _planning(provider).analyze_version(
        root,
        dependency_names={"cached-project": "Cached Project"},
    )

    assert provider.version_detail_calls == 1
    assert provider.project_name_calls == 1
    assert any(message.startswith("Project Alpha") for message in report.missing_required_dependencies)
    assert "Cached Project" in report.optional_dependencies
    assert "optional-lib.jar" in report.optional_dependencies


def test_mod_planning_marks_installed_version_mismatch() -> None:
    root = _version(
        "root-v",
        "1.0.0",
        dependencies=[{"version_id": "required-v", "dependency_type": "required"}],
    )
    required = _version("required-v", "2.0.0")
    provider = _PlanningProviderStub(
        project_names={"deprequired": "Required Dep"},
        version_details={"required-v": ("DepRequired", required)},
    )
    installed = [type("Installed", (), {"platform_id": "DepRequired", "version": "1.0.0"})()]

    plan = _planning(provider).build_dependency_plan(root, installed_mods=installed, root_project_name="Root")

    assert not plan.items
    assert any("已安裝版本不符" in message for message in plan.unresolved_required)


def test_mod_planning_respects_max_depth() -> None:
    root = _version(
        "root-v",
        "1.0.0",
        dependencies=[{"project_id": "DepA", "dependency_type": "required"}],
    )
    dependency_a = _version(
        "dep-a-v",
        "2.0.0",
        dependencies=[{"project_id": "DepB", "dependency_type": "required"}],
        filename="dep-a.jar",
    )
    provider = _PlanningProviderStub(
        project_names={"depa": "Dependency A", "depb": "Dependency B"},
        versions={("depa", "", ""): [dependency_a]},
    )

    plan = _planning(provider).build_dependency_plan(root, root_project_name="Root", max_depth=0)

    assert len(plan.items) == 1
    assert any("依賴深度超過上限" in message for message in plan.unresolved_required)


def test_mod_planning_bounds_dependency_edges() -> None:
    root = _version(
        "root-v",
        "1.0.0",
        dependencies=[{"project_id": "root", "dependency_type": "required"} for _ in range(2050)],
    )
    provider = _PlanningProviderStub(project_names={"root": "Root"})

    plan = _planning(provider).build_dependency_plan(root, root_project_id="root", root_project_name="Root")

    assert not plan.items
    assert any("依賴邊超過安全上限" in message for message in plan.unresolved_required)


def test_modrinth_http_adapter_preserves_provider_project_id_case(monkeypatch) -> None:
    calls: list[str] = []
    expected = _version("VersionABC", "1.0.0")

    def resolve_versions(project_id: str, *_args: Any) -> list[OnlineModVersion]:
        calls.append(project_id)
        return [expected]

    monkeypatch.setattr(planning_adapter_module, "_get_versions", resolve_versions)

    versions = ModrinthHttpAdapter().resolve_versions("ProjectABC", "1.21.1", "fabric")

    assert versions == [expected]
    assert calls == ["ProjectABC"]


def test_loader_rules_adapter_uses_injected_loader_manager() -> None:
    manager = type(
        "RulesManager",
        (),
        {
            "get_compatible_loader_versions": lambda _self, minecraft_version, loader: [
                type("LoaderVersion", (), {"version": f"{minecraft_version}-{loader}"})()
            ]
        },
    )()

    assert LoaderManagerRulesAdapter(manager).compatible_versions("1.21.1", "fabric") == ["1.21.1-fabric"]
