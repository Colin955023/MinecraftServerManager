from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import src.core.mods.modrinth_planning_adapter as planning_adapter_module
from src.core import LoaderManagerRulesAdapter, ModPlanning, ModrinthPlanningAdapter
from src.models import ModrinthVersionLookupResult, OnlineModVersion
from src.utils import normalize_identifier


@dataclass(slots=True)
class _PlanningProviderStub:
    project_names: dict[str, str] = field(default_factory=dict)
    version_details: dict[str, tuple[str, OnlineModVersion | None]] = field(default_factory=dict)
    versions: dict[tuple[str, str, str], list[OnlineModVersion]] = field(default_factory=dict)

    def resolve_project_names(self, project_ids: Iterable[str]) -> dict[str, str]:
        return {
            normalize_identifier(project_id): self.project_names[normalize_identifier(project_id)]
            for project_id in project_ids
            if normalize_identifier(project_id) in self.project_names
        }

    def get_version_details(self, version_id: str) -> tuple[str, OnlineModVersion | None]:
        return self.version_details.get(version_id, ("", None))

    def fetch_project_name(self, project_id: str) -> str | None:
        return self.project_names.get(normalize_identifier(project_id))

    def get_versions(
        self,
        project_id: str,
        minecraft_version: str | None = None,
        loader: str | None = None,
    ) -> list[OnlineModVersion]:
        key = (normalize_identifier(project_id), str(minecraft_version or ""), normalize_identifier(loader))
        return list(self.versions.get(key, self.versions.get((key[0], "", ""), [])))

    def get_current_versions_by_hashes(
        self, hashes: list[str], algorithm: str
    ) -> dict[str, ModrinthVersionLookupResult]:
        del hashes, algorithm
        return {}

    def get_latest_versions_by_hashes(
        self,
        hashes: list[str],
        algorithm: str,
        minecraft_version: str | None = None,
        loader: str | None = None,
    ) -> dict[str, ModrinthVersionLookupResult]:
        del hashes, algorithm, minecraft_version, loader
        return {}

    def get_recommended_version(
        self,
        project_id: str,
        minecraft_version: str | None,
        loader: str | None,
    ) -> OnlineModVersion | None:
        del project_id, minecraft_version, loader
        return None


class _LoaderRulesStub:
    def compatible_versions(self, minecraft_version: str, loader: str) -> list[str]:
        del minecraft_version, loader
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

        def get_version_details(self, version_id: str) -> tuple[str, OnlineModVersion | None]:
            self.version_detail_calls += 1
            return super().get_version_details(version_id)

        def fetch_project_name(self, project_id: str) -> str | None:
            self.project_name_calls += 1
            return super().fetch_project_name(project_id)

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


def test_modrinth_planning_adapter_preserves_provider_project_id_case(monkeypatch) -> None:
    calls: list[str] = []
    expected = _version("VersionABC", "1.0.0")

    def get_versions(project_id: str, *_args: Any) -> list[OnlineModVersion]:
        calls.append(project_id)
        return [expected]

    monkeypatch.setattr(
        planning_adapter_module,
        "get_mod_versions",
        get_versions,
    )

    versions = ModrinthPlanningAdapter().get_versions("ProjectABC", "1.21.1", "fabric")

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
