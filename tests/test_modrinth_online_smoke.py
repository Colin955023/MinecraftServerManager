from __future__ import annotations

import hashlib
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.core as mod_search_service_module
import src.core.mods.compatibility_analyzer as compatibility_analyzer_module
import src.core.mods.mod_file_installer as mod_file_installer_module
import src.core.mods.mod_manager as mod_manager_module
import src.core.mods.modrinth_service as mod_search_provider_module
import src.models as models_module
import src.utils as utils_module
from src.core import ModManager, ModPlanning

_IDENTITY_TEST_OVERRIDE: dict[str, object] = {}
_PLANNING_TEST_OVERRIDE: dict[str, object] = {}


class _EmptyLoaderRules:
    def compatible_versions(self, minecraft_version: str, loader: str) -> list[str]:
        del minecraft_version, loader
        return []


class _PlanningProvider:
    def resolve_project_names(self, project_ids):
        return mod_search_provider_module.resolve_modrinth_project_names(project_ids)

    def get_version_details(self, version_id):
        return mod_search_provider_module.get_mod_version_details(version_id)

    def fetch_project_name(self, project_id):
        return mod_search_provider_module.fetch_modrinth_project_name(project_id)

    def get_versions(self, project_id, minecraft_version=None, loader=None):
        return mod_search_provider_module.get_mod_versions(project_id, minecraft_version, loader)

    def get_current_versions_by_hashes(self, hashes, algorithm):
        return mod_search_provider_module.get_modrinth_current_versions_by_hashes(hashes, algorithm)

    def get_latest_versions_by_hashes(self, hashes, algorithm, minecraft_version=None, loader=None):
        return mod_search_provider_module.get_modrinth_latest_versions_by_hashes(
            hashes, algorithm, minecraft_version, loader
        )

    def get_recommended_version(self, project_id, minecraft_version, loader):
        return mod_search_provider_module.get_recommended_mod_version(project_id, minecraft_version, loader)


class _PlanningHarness:
    def __init__(self) -> None:
        self._planning = ModPlanning(_PlanningProvider(), _EmptyLoaderRules())
        self.provider = self._planning.provider

    def analyze_version(self, *args, **kwargs):
        override = _PLANNING_TEST_OVERRIDE.get("analyze_version")
        if callable(override):
            return override(*args, **kwargs)
        return self._planning.analyze_version(*args, **kwargs)

    def build_dependency_plan(self, *args, **kwargs):
        return self._planning.build_dependency_plan(*args, **kwargs)

    def build_local_update_plan(self, *args, **kwargs):
        kwargs.setdefault("provider_identity_resolver", _test_provider_identity_resolver)
        return self._planning.build_local_update_plan(*args, **kwargs)


_TEST_PLANNING = _PlanningHarness()


def _test_provider_identity_resolver(local_mod: object, hash_project_id: str):
    override = _IDENTITY_TEST_OVERRIDE.get("resolver")
    if callable(override):
        resolved = override(local_mod)
        if resolved is None:
            return models_module.ProviderIdentitySnapshot()
        return models_module.ProviderIdentitySnapshot(
            provider="modrinth",
            project_id=str(getattr(resolved, "project_id", "") or ""),
            alias=str(getattr(resolved, "slug", "") or ""),
            display_name=str(getattr(resolved, "name", "") or ""),
            provenance=("cached_provider" if str(getattr(local_mod, "platform_id", "") or "") else "exact_lookup"),
            lifecycle="fresh",
            observed_at_epoch_ms=int(time.time() * 1000),
            resolved_at_epoch_ms=int(time.time() * 1000),
        )
    if hash_project_id:
        return models_module.ProviderIdentitySnapshot(
            provider="modrinth",
            project_id=hash_project_id,
            display_name=str(getattr(local_mod, "name", "") or ""),
            provenance="hash",
            lifecycle="fresh",
            observed_at_epoch_ms=int(time.time() * 1000),
            resolved_at_epoch_ms=int(time.time() * 1000),
        )
    existing = getattr(local_mod, "provider_identity", None)
    if isinstance(existing, models_module.ProviderIdentitySnapshot):
        return existing
    project_id = str(getattr(local_mod, "platform_id", "") or "")
    now_ms = int(time.time() * 1000)
    return models_module.ProviderIdentitySnapshot(
        provider="modrinth" if project_id else "local",
        project_id=project_id,
        alias=str(getattr(local_mod, "platform_slug", "") or ""),
        display_name=str(getattr(local_mod, "name", "") or ""),
        provenance="cached_provider" if project_id else "unresolved",
        lifecycle="fresh" if project_id else "missing",
        observed_at_epoch_ms=now_ms,
        resolved_at_epoch_ms=now_ms if project_id else 0,
    )


@pytest.fixture(autouse=True)
def _reset_planning_test_overrides():
    _IDENTITY_TEST_OVERRIDE.clear()
    _PLANNING_TEST_OVERRIDE.clear()
    yield
    _IDENTITY_TEST_OVERRIDE.clear()
    _PLANNING_TEST_OVERRIDE.clear()


def _set_planning_dependency(monkeypatch: pytest.MonkeyPatch, name: str, value: object) -> None:
    if name == "provider_identity_fixture":
        monkeypatch.setitem(_IDENTITY_TEST_OVERRIDE, "resolver", value)
        return
    if name == "analyze_version":
        monkeypatch.setitem(_PLANNING_TEST_OVERRIDE, "analyze_version", value)
        return
    monkeypatch.setattr(mod_search_provider_module, name, value, raising=False)


def test_search_mods_online_maps_modrinth_hits(monkeypatch) -> None:
    def fake_get_json(**_kwargs):
        return {
            "hits": [
                {
                    "project_id": "proj123",
                    "slug": "sodium",
                    "title": "Sodium",
                    "author": "jellysquid3",
                    "description": "Client and server rendering optimizations.",
                    "latest_version": "mc1.21-0.6.0",
                    "downloads": 123456,
                    "categories": ["fabric", "optimization"],
                    "server_side": "required",
                    "client_side": "optional",
                }
            ]
        }

    monkeypatch.setattr(utils_module.HTTPClient, "fetch_json", fake_get_json)

    results = mod_search_service_module.search_mods_online("sodium", minecraft_version="1.21", loader="fabric")

    assert len(results) == 1
    assert results[0].project_id == "proj123"
    assert results[0].slug == "sodium"
    assert results[0].name == "Sodium"
    assert results[0].download_count == 123456
    assert results[0].url == "https://modrinth.com/mod/sodium"
    assert results[0].homepage_url == "https://modrinth.com/mod/sodium"
    assert results[0].server_side == "required"
    assert results[0].client_side == "optional"


def test_search_mods_online_passes_category_facets(monkeypatch) -> None:
    captured_params: dict[str, object] = {}

    def fake_get_json(**kwargs):
        captured_params.update(kwargs.get("params", {}))
        return {"hits": []}

    monkeypatch.setattr(utils_module.HTTPClient, "fetch_json", fake_get_json)

    mod_search_service_module.search_mods_online(
        "sodium",
        minecraft_version="1.21",
        loader="fabric",
        categories=["optimization"],
    )

    assert "categories:optimization" in str(captured_params.get("facets", ""))
    assert "server_side:required" in str(captured_params.get("facets", ""))
    assert "server_side:optional" in str(captured_params.get("facets", ""))
    assert "versions:1.21" in str(captured_params.get("facets", ""))
    assert "game_versions:1.21" not in str(captured_params.get("facets", ""))


def test_search_mods_online_supports_browse_mode_without_query(monkeypatch) -> None:
    captured_params: dict[str, object] = {}

    def fake_get_json(**kwargs):
        captured_params.update(kwargs.get("params", {}))
        return {
            "hits": [
                {
                    "project_id": "proj123",
                    "slug": "sodium",
                    "title": "Sodium",
                    "author": "jellysquid3",
                    "description": "Optimizations.",
                    "latest_version": "mc1.21-0.6.0",
                    "downloads": 123456,
                    "categories": ["fabric", "optimization"],
                }
            ]
        }

    monkeypatch.setattr(utils_module.HTTPClient, "fetch_json", fake_get_json)

    results = mod_search_service_module.search_mods_online(
        "",
        minecraft_version="1.21",
        loader="fabric",
        categories=["optimization"],
        sort_by="relevance",
    )

    assert len(results) == 1
    assert "query" not in captured_params
    assert captured_params["index"] == "relevance"
    assert "categories:optimization" in str(captured_params.get("facets", ""))


def test_search_mods_online_filters_out_pure_client_hits(monkeypatch) -> None:
    def fake_get_json(**_kwargs):
        return {
            "hits": [
                {
                    "project_id": "server-mod",
                    "slug": "lithium",
                    "title": "Lithium",
                    "author": "CaffeineMC",
                    "server_side": "required",
                    "client_side": "optional",
                },
                {
                    "project_id": "client-only-mod",
                    "slug": "minimap",
                    "title": "MiniMap",
                    "author": "Example",
                    "server_side": "unsupported",
                    "client_side": "required",
                },
            ]
        }

    monkeypatch.setattr(utils_module.HTTPClient, "fetch_json", fake_get_json)

    results = mod_search_service_module.search_mods_online("", minecraft_version="1.21", loader="fabric")

    assert [mod.project_id for mod in results] == ["server-mod"]


def test_get_mod_versions_filters_and_selects_primary_file(monkeypatch) -> None:
    def fake_get_json(**_kwargs):
        return [
            {
                "id": "ver1",
                "version_number": "1.0.0",
                "game_versions": ["1.21"],
                "loaders": ["fabric"],
                "version_type": "release",
                "date_published": "2026-03-01T12:00:00Z",
                "files": [
                    {"filename": "example-sources.jar", "url": "https://example.invalid/sources.jar", "primary": False},
                    {"filename": "example.jar", "url": "https://example.invalid/example.jar", "primary": True},
                ],
            },
            {
                "id": "ver2",
                "version_number": "1.0.0-forge",
                "game_versions": ["1.21"],
                "loaders": ["forge"],
                "version_type": "release",
                "date_published": "2026-03-01T12:00:00Z",
                "files": [{"filename": "forge.jar", "url": "https://example.invalid/forge.jar", "primary": True}],
            },
        ]

    monkeypatch.setattr(utils_module.HTTPClient, "fetch_json", fake_get_json)

    versions = mod_search_service_module.get_mod_versions("proj123", minecraft_version="1.21", loader="fabric")

    assert len(versions) == 1
    assert versions[0].version_id == "ver1"
    assert versions[0].primary_file is not None
    assert versions[0].primary_file["filename"] == "example.jar"


def test_get_mod_versions_requires_exact_quilt_loader(monkeypatch) -> None:
    def fake_get_json(**_kwargs):
        return [
            {
                "id": "ver-fabric",
                "version_number": "1.0.0",
                "game_versions": ["1.21"],
                "loaders": ["fabric"],
                "version_type": "release",
                "files": [{"filename": "fabric.jar", "url": "https://example.invalid/fabric.jar", "primary": True}],
            },
            {
                "id": "ver-forge",
                "version_number": "1.0.0-forge",
                "game_versions": ["1.21"],
                "loaders": ["forge"],
                "version_type": "release",
                "files": [{"filename": "forge.jar", "url": "https://example.invalid/forge.jar", "primary": True}],
            },
        ]

    monkeypatch.setattr(utils_module.HTTPClient, "fetch_json", fake_get_json)

    versions = mod_search_service_module.get_mod_versions("proj123", minecraft_version="1.21", loader="quilt")

    assert versions == []


def test_get_mod_versions_requires_exact_neoforge_loader(monkeypatch) -> None:
    def fake_get_json(**_kwargs):
        return [
            {
                "id": "ver-forge",
                "version_number": "1.0.0-forge",
                "game_versions": ["1.20.1"],
                "loaders": ["forge"],
                "version_type": "release",
                "files": [{"filename": "forge.jar", "url": "https://example.invalid/forge.jar", "primary": True}],
            },
            {
                "id": "ver-fabric",
                "version_number": "1.0.0-fabric",
                "game_versions": ["1.20.1"],
                "loaders": ["fabric"],
                "version_type": "release",
                "files": [{"filename": "fabric.jar", "url": "https://example.invalid/fabric.jar", "primary": True}],
            },
        ]

    monkeypatch.setattr(utils_module.HTTPClient, "fetch_json", fake_get_json)

    versions = mod_search_service_module.get_mod_versions(
        "proj123",
        minecraft_version="1.20.1",
        loader="neoforge",
    )

    assert versions == []


def test_get_mod_versions_skips_prerelease_entries(monkeypatch) -> None:
    def fake_get_json(**_kwargs):
        return [
            {
                "id": "beta1",
                "version_number": "1.1.0-beta.1",
                "game_versions": ["1.21"],
                "loaders": ["fabric"],
                "version_type": "beta",
                "files": [{"filename": "beta.jar", "url": "https://example.invalid/beta.jar", "primary": True}],
            },
            {
                "id": "release1",
                "version_number": "1.0.0",
                "game_versions": ["1.21"],
                "loaders": ["fabric"],
                "version_type": "release",
                "files": [{"filename": "release.jar", "url": "https://example.invalid/release.jar", "primary": True}],
            },
            {
                "id": "pre1",
                "version_number": "1.2.0-pre1",
                "game_versions": ["1.21"],
                "loaders": ["fabric"],
                "version_type": "pre-release",
                "files": [{"filename": "pre.jar", "url": "https://example.invalid/pre.jar", "primary": True}],
            },
        ]

    monkeypatch.setattr(utils_module.HTTPClient, "fetch_json", fake_get_json)

    versions = mod_search_service_module.get_mod_versions("proj123", minecraft_version="1.21", loader="fabric")

    assert [version.version_id for version in versions] == ["beta1", "release1"]


def test_get_recommended_mod_version_returns_none_when_only_prerelease_exists(monkeypatch) -> None:
    def fake_get_mod_versions(_project_id: str, _minecraft_version=None, _loader=None):
        return []

    _set_planning_dependency(monkeypatch, "get_mod_versions", fake_get_mod_versions)

    assert (
        mod_search_provider_module.get_recommended_mod_version("proj123", minecraft_version="1.21", loader="fabric")
        is None
    )


def test_get_mod_versions_preserves_project_id_case_for_api(monkeypatch) -> None:
    captured_url = {"value": ""}

    def fake_get_json(**kwargs):
        captured_url["value"] = kwargs.get("url", "")
        return []

    monkeypatch.setattr(utils_module.HTTPClient, "fetch_json", fake_get_json)

    mod_search_service_module.get_mod_versions("P7dR8mSH")

    assert captured_url["value"].endswith("/project/P7dR8mSH/version")


def test_get_modrinth_latest_versions_by_hashes_posts_prism_style_payload(monkeypatch) -> None:
    captured_request: dict[str, object] = {}

    def fake_post_json(**kwargs):
        captured_request.update(kwargs)
        return {
            "abc123": {
                "project_id": "proj123",
                "id": "ver1",
                "version_number": "1.2.0",
                "game_versions": ["1.21.1"],
                "loaders": ["fabric"],
                "files": [
                    {
                        "filename": "example.jar",
                        "url": "https://example.invalid/example.jar",
                        "primary": True,
                        "hashes": {"sha512": "def456"},
                    }
                ],
            }
        }

    monkeypatch.setattr(utils_module.HTTPClient, "post_json", fake_post_json)

    results = mod_search_provider_module.get_modrinth_latest_versions_by_hashes(
        ["abc123"],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert captured_request["url"] == "https://api.modrinth.com/v2/version_files/update"
    assert captured_request["json_body"] == {
        "hashes": ["abc123"],
        "algorithm": "sha512",
        "game_versions": ["1.21.1"],
        "loaders": ["fabric"],
    }
    assert results["abc123"].project_id == "proj123"
    assert results["abc123"].version.version_id == "ver1"


def test_get_modrinth_latest_versions_by_hashes_uses_exact_quilt_loader(monkeypatch) -> None:
    captured_request: dict[str, object] = {}

    def fake_post_json(**kwargs):
        captured_request.update(kwargs)
        return {}

    monkeypatch.setattr(utils_module.HTTPClient, "post_json", fake_post_json)

    mod_search_provider_module.get_modrinth_latest_versions_by_hashes(
        ["abc123"],
        minecraft_version="1.21.1",
        loader="quilt",
    )

    assert captured_request["json_body"] == {
        "hashes": ["abc123"],
        "algorithm": "sha512",
        "game_versions": ["1.21.1"],
        "loaders": ["quilt"],
    }


def test_get_modrinth_latest_versions_by_hashes_uses_exact_neoforge_loader(monkeypatch) -> None:
    captured_request: dict[str, object] = {}

    def fake_post_json(**kwargs):
        captured_request.update(kwargs)
        return {}

    monkeypatch.setattr(utils_module.HTTPClient, "post_json", fake_post_json)

    mod_search_provider_module.get_modrinth_latest_versions_by_hashes(
        ["abc123"],
        minecraft_version="1.20.1",
        loader="neoforge",
    )

    assert captured_request["json_body"] == {
        "hashes": ["abc123"],
        "algorithm": "sha512",
        "game_versions": ["1.20.1"],
        "loaders": ["neoforge"],
    }


def test_search_mods_online_uses_exact_quilt_loader_facet(monkeypatch) -> None:
    captured_params: dict[str, object] = {}

    def fake_get_json(**kwargs):
        captured_params.update(kwargs.get("params", {}))
        return {"hits": []}

    monkeypatch.setattr(utils_module.HTTPClient, "fetch_json", fake_get_json)

    mod_search_service_module.search_mods_online("sodium", minecraft_version="1.21", loader="quilt")

    facets_text = str(captured_params.get("facets", ""))
    assert "categories:quilt" in facets_text
    assert "categories:fabric" not in facets_text


def test_mod_planning_build_local_update_plan_marks_invalidated_stale_provider_as_blocked(monkeypatch) -> None:
    stale_epoch_ms = int(time.time() * 1000) - (13 * 60 * 60 * 1000)
    next_retry_epoch_ms = int(time.time() * 1000) + (10 * 60 * 1000)

    monkeypatch.setattr(utils_module.HashUtils, "compute_file_hash", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(utils_module.HashUtils, "compute_file_hash_sync", lambda *_args, **_kwargs: "")
    _set_planning_dependency(monkeypatch, "get_modrinth_current_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "get_modrinth_latest_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "get_modrinth_project_info", lambda *_args, **_kwargs: None)
    _set_planning_dependency(monkeypatch, "search_mods_online", lambda *_args, **_kwargs: [])

    local_mod = SimpleNamespace(
        filename="sodium.jar",
        file_path="C:/servers/Fabric/mods/sodium.jar",
        current_hash="",
        hash_algorithm="",
        platform_id="AANobbMI",
        platform_slug="sodium",
        provider_identity=models_module.ProviderIdentitySnapshot(
            provider="modrinth",
            project_id="AANobbMI",
            alias="sodium",
            display_name="Sodium",
            provenance="scan_detect",
            lifecycle="invalidated",
            resolved_at_epoch_ms=stale_epoch_ms,
            failure_count=3,
            next_retry_not_before_epoch_ms=next_retry_epoch_ms,
        ),
        name="Sodium",
        version="1.0.0",
    )

    plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
        loader_version="0.16.10",
    )

    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.recommendation_confidence == utils_module.RECOMMENDATION_CONFIDENCE_BLOCKED
    assert any("invalidated" in item for item in candidate.hard_errors)


def test_mod_planning_analyze_version_reports_hard_errors() -> None:
    version = models_module.OnlineModVersion(
        version_id="ver1",
        version_number="1.0.0",
        display_name="1.0.0",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[{"filename": "example.jar", "url": "https://example.invalid/example.jar", "primary": True}],
    )

    report = _TEST_PLANNING.analyze_version(
        version,
        project_id="proj123",
        project_name="Example Mod",
        minecraft_version="1.21",
        loader="fabric",
        loader_version="0.16.0",
    )

    assert any("Minecraft" in item for item in report.hard_errors)
    assert any("載入器" in item for item in report.hard_errors)
    loader_rule_messages = list(report.notes) + list(report.warnings)
    assert any("0.16.0" in item for item in loader_rule_messages)


def test_mod_planning_analyze_version_reports_loader_mismatch_on_quilt_server() -> None:
    version = models_module.OnlineModVersion(
        version_id="ver1",
        version_number="1.0.0",
        display_name="1.0.0",
        game_versions=["1.21"],
        loaders=["fabric"],
        files=[{"filename": "example.jar", "url": "https://example.invalid/example.jar", "primary": True}],
    )

    report = _TEST_PLANNING.analyze_version(
        version,
        project_id="proj123",
        project_name="Example Mod",
        minecraft_version="1.21",
        loader="quilt",
    )

    assert any("載入器" in item for item in report.hard_errors)


def test_mod_planning_analyze_version_reports_dependencies() -> None:
    version = models_module.OnlineModVersion(
        version_id="ver1",
        version_number="1.0.0",
        display_name="1.0.0",
        game_versions=["1.21"],
        loaders=["fabric"],
        files=[{"filename": "example.jar", "url": "https://example.invalid/example.jar", "primary": True}],
        dependencies=[
            {"project_id": "cloth-config", "dependency_type": "required"},
            {"project_id": "modmenu", "dependency_type": "optional"},
            {"project_id": "legacy-conflict", "dependency_type": "incompatible"},
        ],
    )
    installed_mods = [
        SimpleNamespace(
            platform_id="proj123",
            id="example-mod",
            name="Example Mod",
            filename="example-mod-1.0.0.jar",
        ),
        SimpleNamespace(
            platform_id="legacy-conflict",
            id="legacy-conflict",
            name="Legacy Conflict",
            filename="legacy-conflict.jar",
        ),
    ]

    report = _TEST_PLANNING.analyze_version(
        version,
        project_id="proj123",
        project_name="Example Mod",
        minecraft_version="1.21",
        loader="fabric",
        installed_mods=installed_mods,
        dependency_names={
            "cloth-config": "Cloth Config",
            "modmenu": "Mod Menu",
            "legacy-conflict": "Legacy Conflict",
        },
    )

    assert report.already_installed == ["Example Mod"]
    assert report.missing_required_dependencies == ["Cloth Config"]
    assert report.optional_dependencies == ["Mod Menu"]
    assert report.incompatible_installed == ["Legacy Conflict"]
    assert any("不相容模組" in item for item in report.hard_errors)


def test_mod_planning_analyze_version_detects_version_id_dependency_mismatch(monkeypatch) -> None:
    dependency_version = models_module.OnlineModVersion(
        version_id="dep-v2",
        version_number="2.0.0",
        display_name="2.0.0",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[{"filename": "dep.jar", "url": "https://example.invalid/dep.jar", "primary": True}],
    )
    version = models_module.OnlineModVersion(
        version_id="root-v1",
        version_number="12.0.0.4",
        display_name="12.0.0.4",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[{"filename": "root.jar", "url": "https://example.invalid/root.jar", "primary": True}],
        dependencies=[{"version_id": "p7dr8msh", "dependency_type": "required"}],
    )
    installed_mods = [
        SimpleNamespace(
            platform_id="cloth-config",
            id="cloth-config",
            name="Cloth Config",
            filename="cloth-config-1.0.0.jar",
            version="1.0.0",
        )
    ]

    _set_planning_dependency(
        monkeypatch,
        "get_mod_version_details",
        lambda version_id: ("cloth-config", dependency_version) if version_id == "p7dr8msh" else ("", None),
    )
    _set_planning_dependency(
        monkeypatch,
        "fetch_modrinth_project_name",
        lambda project_id: "Cloth Config" if project_id == "cloth-config" else None,
    )

    report = _TEST_PLANNING.analyze_version(
        version,
        project_id="clumps",
        project_name="Clumps",
        minecraft_version="1.20.1",
        loader="forge",
        installed_mods=installed_mods,
        dependency_names={},
    )

    assert report.missing_required_dependencies == ["Cloth Config（需求版本：2.0.0）"]
    assert len(report.installed_version_mismatches) == 1
    assert "版本為 1.0.0" in report.installed_version_mismatches[0]
    assert "需求版本 2.0.0" in report.installed_version_mismatches[0]


def test_mod_planning_analyze_version_marks_required_dependency_as_maybe_installed(monkeypatch) -> None:
    dependency_version = models_module.OnlineModVersion(
        version_id="dep-v2",
        version_number="2.0.0",
        display_name="2.0.0",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[
            {"filename": "cloth-config-2.0.0.jar", "url": "https://example.invalid/cloth-config.jar", "primary": True}
        ],
    )
    version = models_module.OnlineModVersion(
        version_id="root-v1",
        version_number="12.0.0.4",
        display_name="12.0.0.4",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[{"filename": "root.jar", "url": "https://example.invalid/root.jar", "primary": True}],
        dependencies=[{"version_id": "p7dr8msh", "dependency_type": "required"}],
    )
    installed_mods = [SimpleNamespace(filename="cloth_config+1.0.0.jar", name="Unknown Mod")]

    _set_planning_dependency(
        monkeypatch,
        "get_mod_version_details",
        lambda version_id: ("cloth-config", dependency_version) if version_id == "p7dr8msh" else ("", None),
    )
    _set_planning_dependency(
        monkeypatch,
        "fetch_modrinth_project_name",
        lambda project_id: "Cloth Config" if project_id == "cloth-config" else None,
    )

    report = _TEST_PLANNING.analyze_version(
        version,
        project_id="clumps",
        project_name="Clumps",
        minecraft_version="1.20.1",
        loader="forge",
        installed_mods=installed_mods,
        dependency_names={},
    )

    assert report.missing_required_dependencies == ["Cloth Config（需求版本：2.0.0）"]
    assert "必要依賴可能已存在但尚未能以 metadata 精確識別：Cloth Config（需求版本：2.0.0）" in report.warnings
    assert "Cloth Config（需求版本：2.0.0） 可能已存在本地相近檔名，系統已先採安全略過策略" in report.notes


def test_mod_planning_build_dependency_plan_resolves_version_id_dependency(monkeypatch) -> None:
    dependency_version = models_module.OnlineModVersion(
        version_id="dep-v2",
        version_number="2.0.0",
        display_name="2.0.0",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[{"filename": "cloth-config.jar", "url": "https://example.invalid/cloth-config.jar", "primary": True}],
    )
    root_version = models_module.OnlineModVersion(
        version_id="root-v1",
        version_number="12.0.0.4",
        display_name="12.0.0.4",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[{"filename": "root.jar", "url": "https://example.invalid/root.jar", "primary": True}],
        dependencies=[{"version_id": "p7dr8msh", "dependency_type": "required"}],
    )

    _set_planning_dependency(
        monkeypatch,
        "get_mod_version_details",
        lambda version_id: ("cloth-config", dependency_version) if version_id == "p7dr8msh" else ("", None),
    )

    def fake_fetch_modrinth_project_name(project_id: str) -> str | None:
        return "Cloth Config" if project_id == "cloth-config" else None

    def fake_get_mod_versions(_project_id: str, _minecraft_version=None, _loader=None):
        return []

    _set_planning_dependency(monkeypatch, "fetch_modrinth_project_name", fake_fetch_modrinth_project_name)
    _set_planning_dependency(monkeypatch, "get_mod_versions", fake_get_mod_versions)

    plan = _TEST_PLANNING.build_dependency_plan(
        root_version,
        minecraft_version="1.20.1",
        loader="forge",
        installed_mods=[],
        root_project_id="clumps",
        root_project_name="Clumps",
    )

    assert bool(plan.unresolved_required) is False
    assert len(plan.items) == 1
    assert plan.items[0].project_id == "cloth-config"
    assert plan.items[0].project_name == "Cloth Config（需求版本：2.0.0）"
    assert plan.items[0].version_id == "dep-v2"


def test_mod_planning_build_dependency_plan_marks_maybe_installed_dependency_as_unresolved(monkeypatch) -> None:
    dependency_version = models_module.OnlineModVersion(
        version_id="dep-v2",
        version_number="2.0.0",
        display_name="2.0.0",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[
            {"filename": "cloth-config-2.0.0.jar", "url": "https://example.invalid/cloth-config.jar", "primary": True}
        ],
    )
    root_version = models_module.OnlineModVersion(
        version_id="root-v1",
        version_number="12.0.0.4",
        display_name="12.0.0.4",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[{"filename": "root.jar", "url": "https://example.invalid/root.jar", "primary": True}],
        dependencies=[{"version_id": "p7dr8msh", "dependency_type": "required"}],
    )
    installed_mods = [SimpleNamespace(filename="cloth_config+1.0.0.jar", name="Unknown Mod")]

    _set_planning_dependency(
        monkeypatch,
        "get_mod_version_details",
        lambda version_id: ("cloth-config", dependency_version) if version_id == "p7dr8msh" else ("", None),
    )
    _set_planning_dependency(
        monkeypatch,
        "fetch_modrinth_project_name",
        lambda project_id: "Cloth Config" if project_id == "cloth-config" else None,
    )

    plan = _TEST_PLANNING.build_dependency_plan(
        root_version,
        minecraft_version="1.20.1",
        loader="forge",
        installed_mods=installed_mods,
        root_project_id="clumps",
        root_project_name="Clumps",
    )

    assert plan.items == []
    assert bool(plan.unresolved_required) is False
    assert len(plan.advisory_items) == 1
    assert plan.advisory_items[0].project_name == "Cloth Config（需求版本：2.0.0）"
    assert plan.advisory_items[0].maybe_installed is True
    assert plan.advisory_items[0].included_by_default is False
    assert plan.advisory_items[0].filename == "cloth-config-2.0.0.jar"
    assert plan.advisory_items[0].download_url == "https://example.invalid/cloth-config.jar"
    assert "預設略過自動安裝" in plan.advisory_items[0].status_note
    assert any("已預設略過自動安裝" in note for note in plan.notes)


def test_mod_planning_build_local_update_plan_uses_resolved_online_project_id(monkeypatch) -> None:
    captured_project_ids: list[str] = []
    local_mod = SimpleNamespace(
        platform_id="inventoryprofilesnext",
        name="Inventory Profiles Next",
        filename="InventoryProfilesNext-fabric-1.21.11-2.2.2.jar",
        version="2.2.2",
        loader_type="Forge",
        minecraft_version="1.21.11",
    )
    resolved_info = models_module.OnlineModInfo(
        project_id="YL57xq9U",
        slug="inventory-profiles-next",
        name="Inventory Profiles Next",
        author="Libz",
    )

    _set_planning_dependency(monkeypatch, "provider_identity_fixture", lambda _local_mod: resolved_info)
    _set_planning_dependency(
        monkeypatch,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"yl57xq9u": "Inventory Profiles Next"},
    )

    def fake_get_recommended_mod_version(project_id: str, _minecraft_version=None, _loader=None):
        captured_project_ids.append(project_id)
        return

    _set_planning_dependency(monkeypatch, "get_recommended_mod_version", fake_get_recommended_mod_version)

    plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21.11",
        loader="fabric",
    )

    assert captured_project_ids == ["YL57xq9U"]
    assert local_mod.platform_id == "inventoryprofilesnext"
    assert plan.candidates == []


def test_mod_planning_build_local_update_plan_marks_low_confidence_lookup_as_unresolved(monkeypatch) -> None:
    local_mod = SimpleNamespace(
        platform_id="",
        platform_slug="",
        name="Inventory Profiles Next",
        filename="inventory-profiles-next.jar",
        version="2.2.1",
        minecraft_version="1.21.1",
        loader_type="Fabric",
        file_path="",
        current_hash="",
        hash_algorithm="",
    )

    _set_planning_dependency(monkeypatch, "get_modrinth_current_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "get_modrinth_latest_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "get_modrinth_project_info", lambda *_args, **_kwargs: None)
    _set_planning_dependency(
        monkeypatch,
        "search_mods_online",
        lambda *_args, **_kwargs: [
            models_module.OnlineModInfo(
                project_id="proj-unrelated",
                slug="totally-different-mod",
                name="Totally Different Mod",
                author="Someone",
            )
        ],
    )

    plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(plan.candidates) == 1
    assert plan.metadata_summary.unresolved == 1
    assert plan.candidates[0].metadata_source == "unresolved"
    assert plan.candidates[0].metadata_resolved is False
    assert plan.candidates[0].recommendation_source == "metadata_unresolved"
    assert plan.candidates[0].recommendation_confidence == "blocked"


def test_mod_planning_build_local_update_plan_detects_updates_for_camel_case_local_mod(monkeypatch) -> None:
    local_mod = SimpleNamespace(
        platform_id="inventoryprofilesnext",
        name="InventoryProfilesNext-fabric-1.21.11-2.2.1",
        filename="InventoryProfilesNext-fabric-1.21.11-2.2.1.jar",
        version="2.2.1",
        minecraft_version="1.21.11",
        loader_type="Fabric",
    )
    captured_project_ids: list[str] = []
    resolved_info = models_module.OnlineModInfo(
        project_id="YL57xq9U",
        slug="inventory-profiles-next",
        name="Inventory Profiles Next",
        author="Libz",
    )
    recommended_version = models_module.OnlineModVersion(
        version_id="ver-new",
        version_number="2.2.2",
        display_name="2.2.2",
        game_versions=["1.21.11"],
        loaders=["fabric"],
        files=[
            {
                "filename": "InventoryProfilesNext-fabric-1.21.11-2.2.2.jar",
                "url": "https://example.invalid/ipn-2.2.2.jar",
                "primary": True,
            }
        ],
    )

    def fake_provider_identity_fixture(_local_mod):
        return resolved_info

    def fake_get_recommended_mod_version(project_id: str, _minecraft_version=None, _loader=None):
        captured_project_ids.append(project_id)
        return recommended_version if project_id == "YL57xq9U" else None

    _set_planning_dependency(monkeypatch, "provider_identity_fixture", fake_provider_identity_fixture)
    _set_planning_dependency(monkeypatch, "get_recommended_mod_version", fake_get_recommended_mod_version)
    _set_planning_dependency(
        monkeypatch,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"yl57xq9u": "Inventory Profiles Next"},
    )
    _set_planning_dependency(
        monkeypatch,
        "analyze_version",
        lambda *_args, **_kwargs: models_module.OnlineModCompatibilityReport(),
    )

    update_plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21.11",
        loader="fabric",
    )

    assert captured_project_ids == ["YL57xq9U"]
    assert len(update_plan.candidates) == 1
    assert update_plan.candidates[0].project_name == "Inventory Profiles Next"
    assert update_plan.candidates[0].update_available is True
    assert update_plan.candidates[0].target_version_name == "2.2.2"


def test_search_mods_online_normalizes_filename_like_query(monkeypatch) -> None:
    captured_params: dict[str, object] = {}

    def fake_get_json(**kwargs):
        captured_params.update(kwargs.get("params", {}))
        return {"hits": []}

    monkeypatch.setattr(utils_module.HTTPClient, "fetch_json", fake_get_json)

    mod_search_service_module.search_mods_online("letsdo-API-forge-1.2.15-forge", loader="forge")

    assert captured_params["query"] == "letsdo API"


def test_mod_planning_build_dependency_plan_collects_recursive_dependencies(monkeypatch) -> None:
    root_version = models_module.OnlineModVersion(
        version_id="root-v1",
        version_number="1.0.0",
        display_name="1.0.0",
        game_versions=["1.21"],
        loaders=["fabric"],
        files=[{"filename": "root.jar", "url": "https://example.invalid/root.jar", "primary": True}],
        dependencies=[{"project_id": "cloth-config", "dependency_type": "required"}],
    )

    def fake_get_mod_versions(project_id: str, minecraft_version=None, loader=None):
        if project_id == "cloth-config":
            return [
                models_module.OnlineModVersion(
                    version_id="cloth-v1",
                    version_number="15.0.0",
                    display_name="15.0.0",
                    game_versions=[minecraft_version or "1.21"],
                    loaders=[loader or "fabric"],
                    files=[
                        {
                            "filename": "cloth-config.jar",
                            "url": "https://example.invalid/cloth-config.jar",
                            "primary": True,
                        }
                    ],
                    dependencies=[{"project_id": "fabric-api", "dependency_type": "required"}],
                )
            ]
        if project_id == "fabric-api":
            return [
                models_module.OnlineModVersion(
                    version_id="fabric-api-v1",
                    version_number="0.100.0",
                    display_name="0.100.0",
                    game_versions=[minecraft_version or "1.21"],
                    loaders=[loader or "fabric"],
                    files=[
                        {
                            "filename": "fabric-api.jar",
                            "url": "https://example.invalid/fabric-api.jar",
                            "primary": True,
                        }
                    ],
                )
            ]
        return []

    _set_planning_dependency(monkeypatch, "get_mod_versions", fake_get_mod_versions)
    _set_planning_dependency(
        monkeypatch,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"cloth-config": "Cloth Config", "fabric-api": "Fabric API"},
    )

    plan = _TEST_PLANNING.build_dependency_plan(
        root_version,
        minecraft_version="1.21",
        loader="fabric",
        installed_mods=[],
        root_project_id="root-mod",
        root_project_name="Root Mod",
    )

    assert bool(plan.unresolved_required) is False
    assert [item.project_name for item in plan.items] == ["Cloth Config", "Fabric API"]


def test_mod_planning_build_dependency_plan_allows_prism_like_recursion_depth(monkeypatch) -> None:
    chain_length = 10
    dependency_ids = [f"dep-{index}" for index in range(chain_length)]
    root_version = models_module.OnlineModVersion(
        version_id="root-v1",
        version_number="1.0.0",
        display_name="1.0.0",
        game_versions=["1.21"],
        loaders=["fabric"],
        files=[{"filename": "root.jar", "url": "https://example.invalid/root.jar", "primary": True}],
        dependencies=[{"project_id": dependency_ids[0], "dependency_type": "required"}],
    )

    def fake_get_mod_versions(project_id: str, minecraft_version=None, loader=None):
        try:
            index = dependency_ids.index(project_id)
        except ValueError:
            return []

        dependencies = []
        if index + 1 < len(dependency_ids):
            dependencies.append({"project_id": dependency_ids[index + 1], "dependency_type": "required"})

        return [
            models_module.OnlineModVersion(
                version_id=f"{project_id}-v1",
                version_number="1.0.0",
                display_name="1.0.0",
                game_versions=[minecraft_version or "1.21"],
                loaders=[loader or "fabric"],
                files=[
                    {
                        "filename": f"{project_id}.jar",
                        "url": f"https://example.invalid/{project_id}.jar",
                        "primary": True,
                    }
                ],
                dependencies=dependencies,
            )
        ]

    _set_planning_dependency(monkeypatch, "get_mod_versions", fake_get_mod_versions)
    _set_planning_dependency(
        monkeypatch,
        "resolve_modrinth_project_names",
        lambda project_ids: {str(project_id).lower(): str(project_id).title() for project_id in project_ids},
    )

    plan = _TEST_PLANNING.build_dependency_plan(
        root_version,
        minecraft_version="1.21",
        loader="fabric",
        installed_mods=[],
        root_project_id="root-mod",
        root_project_name="Root Mod",
    )

    assert bool(plan.unresolved_required) is False
    assert len(plan.items) == chain_length


def test_mod_planning_build_dependency_plan_preserves_dependency_project_id_case_for_api(monkeypatch) -> None:
    root_version = models_module.OnlineModVersion(
        version_id="root-v1",
        version_number="1.0.0",
        display_name="1.0.0",
        game_versions=["1.21"],
        loaders=["fabric"],
        files=[{"filename": "root.jar", "url": "https://example.invalid/root.jar", "primary": True}],
        dependencies=[{"project_id": "P7dR8mSH", "dependency_type": "required"}],
    )
    captured_project_ids: list[str] = []

    def fake_get_mod_versions(project_id: str, _minecraft_version=None, _loader=None):
        captured_project_ids.append(project_id)
        return []

    def fake_resolve_modrinth_project_names(_project_ids):
        return {"p7dr8msh": "Fabric API"}

    _set_planning_dependency(monkeypatch, "get_mod_versions", fake_get_mod_versions)
    _set_planning_dependency(monkeypatch, "resolve_modrinth_project_names", fake_resolve_modrinth_project_names)

    plan = _TEST_PLANNING.build_dependency_plan(
        root_version,
        minecraft_version="1.21",
        loader="fabric",
        installed_mods=[],
        root_project_id="clumps",
        root_project_name="Clumps",
    )

    assert bool(plan.unresolved_required) is True
    assert captured_project_ids == ["P7dR8mSH", "P7dR8mSH"]


def test_mod_planning_build_dependency_plan_keeps_quilt_dependency_id_for_fabric_loader(
    monkeypatch,
) -> None:
    root_version = models_module.OnlineModVersion(
        version_id="root-v1",
        version_number="1.0.0",
        display_name="1.0.0",
        game_versions=["1.21"],
        loaders=["fabric"],
        files=[{"filename": "root.jar", "url": "https://example.invalid/root.jar", "primary": True}],
        dependencies=[{"project_id": "qvIfYCYJ", "dependency_type": "required"}],
    )
    captured_project_ids: list[str] = []

    def fake_get_mod_versions(project_id: str, minecraft_version=None, loader=None):
        captured_project_ids.append(project_id)
        return [
            models_module.OnlineModVersion(
                version_id="fabric-api-v1",
                version_number="0.100.0",
                display_name="0.100.0",
                game_versions=[minecraft_version or "1.21"],
                loaders=[loader or "fabric"],
                files=[
                    {
                        "filename": "fabric-api.jar",
                        "url": "https://example.invalid/fabric-api.jar",
                        "primary": True,
                    }
                ],
            )
        ]

    _set_planning_dependency(monkeypatch, "get_mod_versions", fake_get_mod_versions)
    _set_planning_dependency(
        monkeypatch,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"p7dr8msh": "Fabric API", "qvifycyj": "QSL"},
    )
    _set_planning_dependency(
        monkeypatch,
        "fetch_modrinth_project_name",
        lambda project_id: "Fabric API" if project_id == "P7dR8mSH" else "QSL",
    )

    plan = _TEST_PLANNING.build_dependency_plan(
        root_version,
        minecraft_version="1.21",
        loader="fabric",
        installed_mods=[],
        root_project_id="root-mod",
        root_project_name="Root Mod",
    )

    assert captured_project_ids == ["qvIfYCYJ"]
    assert len(plan.items) == 1
    assert plan.items[0].project_id == "qvIfYCYJ"
    assert plan.items[0].project_name == "QSL"


def test_mod_planning_build_dependency_plan_does_not_apply_quilt_override_for_forge_loader(
    monkeypatch,
) -> None:
    root_version = models_module.OnlineModVersion(
        version_id="root-v1",
        version_number="1.0.0",
        display_name="1.0.0",
        game_versions=["1.21"],
        loaders=["forge"],
        files=[{"filename": "root.jar", "url": "https://example.invalid/root.jar", "primary": True}],
        dependencies=[{"project_id": "qvIfYCYJ", "dependency_type": "required"}],
    )
    captured_project_ids: list[str] = []

    def fake_get_mod_versions(project_id: str, minecraft_version=None, loader=None):
        captured_project_ids.append(project_id)
        return [
            models_module.OnlineModVersion(
                version_id="dep-v1",
                version_number="1.0.0",
                display_name="1.0.0",
                game_versions=[minecraft_version or "1.21"],
                loaders=[loader or "forge"],
                files=[
                    {
                        "filename": "qsl.jar",
                        "url": "https://example.invalid/qsl.jar",
                        "primary": True,
                    }
                ],
            )
        ]

    _set_planning_dependency(monkeypatch, "get_mod_versions", fake_get_mod_versions)
    _set_planning_dependency(
        monkeypatch,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"qvifycyj": "QSL"},
    )
    _set_planning_dependency(
        monkeypatch,
        "fetch_modrinth_project_name",
        lambda project_id: "QSL" if project_id == "qvIfYCYJ" else None,
    )

    plan = _TEST_PLANNING.build_dependency_plan(
        root_version,
        minecraft_version="1.21",
        loader="forge",
        installed_mods=[],
        root_project_id="root-mod",
        root_project_name="Root Mod",
    )

    assert captured_project_ids == ["qvIfYCYJ"]
    assert len(plan.items) == 1
    assert plan.items[0].project_id == "qvIfYCYJ"
    assert plan.items[0].project_name == "QSL"


def test_mod_planning_build_local_update_plan_reports_updates_and_dependency_issues(monkeypatch) -> None:
    local_mod = SimpleNamespace(
        platform_id="proj123",
        name="Example Mod",
        filename="example-mod.jar",
        version="1.0.0",
        minecraft_version="1.21",
        loader_type="Fabric",
    )
    recommended_version = models_module.OnlineModVersion(
        version_id="ver2",
        version_number="1.1.0",
        display_name="1.1.0",
        game_versions=["1.21"],
        loaders=["fabric"],
        files=[
            {"filename": "example-mod-1.1.0.jar", "url": "https://example.invalid/example-mod.jar", "primary": True}
        ],
        dependencies=[{"project_id": "cloth-config", "dependency_type": "required"}],
    )
    resolved_info = models_module.OnlineModInfo(
        project_id="proj123",
        slug="example-mod",
        name="Example Mod",
        author="Tester",
    )

    def fake_get_recommended_mod_version(project_id: str, _minecraft_version=None, _loader=None):
        return recommended_version if project_id == "proj123" else None

    def fake_resolve_modrinth_project_names(_project_ids):
        return {
            "proj123": "Example Mod",
            "cloth-config": "Cloth Config",
        }

    def fake_analyze_version(*_args, **_kwargs):
        return models_module.OnlineModCompatibilityReport(
            missing_required_dependencies=["Cloth Config"],
            notes=["已找到相容更新"],
        )

    _set_planning_dependency(monkeypatch, "get_recommended_mod_version", fake_get_recommended_mod_version)
    _set_planning_dependency(monkeypatch, "provider_identity_fixture", lambda _local_mod: resolved_info)
    _set_planning_dependency(monkeypatch, "resolve_modrinth_project_names", fake_resolve_modrinth_project_names)
    _set_planning_dependency(monkeypatch, "analyze_version", fake_analyze_version)

    update_plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21",
        loader="fabric",
        loader_version="0.16.0",
    )

    assert len(update_plan.candidates) == 1
    candidate = update_plan.candidates[0]
    assert candidate.project_name == "Example Mod"
    assert candidate.update_available is True
    assert candidate.target_version_name == "1.1.0"
    assert candidate.dependency_issues == ["Cloth Config"]
    assert candidate.target_version is recommended_version


def test_mod_planning_build_local_update_plan_prefers_hash_first_update_detection(tmp_path: Path, monkeypatch) -> None:
    file_path = tmp_path / "mods" / "example-mod.jar"
    file_path.parents[0].mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"old-mod")
    current_hash = utils_module.HashUtils.compute_file_hash(str(file_path), "sha512")

    current_version = models_module.OnlineModVersion(
        version_id="ver-current",
        version_number="1.0.0",
        display_name="1.0.0",
        game_versions=["1.21.1"],
        loaders=["fabric"],
        files=[
            {
                "filename": "example-mod.jar",
                "url": "https://example.invalid/current.jar",
                "primary": True,
                "hashes": {"sha512": current_hash},
            }
        ],
    )
    latest_version = models_module.OnlineModVersion(
        version_id="ver-latest",
        version_number="1.0.0",
        display_name="1.0.0",
        game_versions=["1.21.1"],
        loaders=["fabric"],
        files=[
            {
                "filename": "example-mod-new.jar",
                "url": "https://example.invalid/latest.jar",
                "primary": True,
                "hashes": {"sha512": "newhash456"},
            }
        ],
    )
    local_mod = SimpleNamespace(
        platform_id="",
        name="Example Mod",
        filename="example-mod.jar",
        version="1.0.0",
        minecraft_version="1.21.1",
        loader_type="Fabric",
        file_path=str(file_path),
    )

    _set_planning_dependency(
        monkeypatch,
        "get_modrinth_current_versions_by_hashes",
        lambda _hashes, _algorithm="sha512": {
            current_hash: models_module.ModrinthVersionLookupResult(
                file_hash=current_hash, algorithm="sha512", project_id="proj123", version=current_version
            )
        },
    )

    def fake_get_modrinth_latest_versions_by_hashes(
        _hashes,
        _algorithm="sha512",
        minecraft_version=None,
        loader=None,
    ):
        del minecraft_version, loader
        return {
            current_hash: models_module.ModrinthVersionLookupResult(
                file_hash=current_hash,
                algorithm="sha512",
                project_id="proj123",
                version=latest_version,
            )
        }

    _set_planning_dependency(
        monkeypatch, "get_modrinth_latest_versions_by_hashes", fake_get_modrinth_latest_versions_by_hashes
    )
    _set_planning_dependency(
        monkeypatch,
        "get_recommended_mod_version",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("fallback path should not be used")),
    )
    _set_planning_dependency(
        monkeypatch, "resolve_modrinth_project_names", lambda _project_ids: {"proj123": "Example Mod"}
    )
    _set_planning_dependency(
        monkeypatch,
        "analyze_version",
        lambda *_args, **_kwargs: models_module.OnlineModCompatibilityReport(),
    )

    update_plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(update_plan.candidates) == 1
    candidate = update_plan.candidates[0]
    assert candidate.project_id == "proj123"
    assert candidate.current_hash == current_hash
    assert candidate.target_file_hash == "newhash456"
    assert candidate.metadata_source == "hash"
    assert candidate.update_available is True


def test_mod_planning_build_local_update_plan_prefers_cached_local_hash(monkeypatch) -> None:
    cached_hash = "abc123cached"
    latest_version = models_module.OnlineModVersion(
        version_id="ver-latest",
        version_number="2.0.0",
        display_name="2.0.0",
        game_versions=["1.21.1"],
        loaders=["fabric"],
        files=[
            {
                "filename": "example-mod-new.jar",
                "url": "https://example.invalid/latest.jar",
                "primary": True,
                "hashes": {"sha512": "def456"},
            }
        ],
    )
    local_mod = SimpleNamespace(
        platform_id="proj123",
        name="Example Mod",
        filename="example-mod.jar",
        version="1.0.0",
        minecraft_version="1.21.1",
        loader_type="Fabric",
        file_path="C:/non-existent/example-mod.jar",
        current_hash=cached_hash,
        hash_algorithm="sha512",
    )

    _set_planning_dependency(
        monkeypatch,
        "HashUtils",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should use cached hash first")),
    )
    _set_planning_dependency(
        monkeypatch, "get_modrinth_current_versions_by_hashes", lambda _hashes, _algorithm="sha512": {}
    )

    def fake_get_modrinth_latest_versions_by_hashes(
        _hashes,
        _algorithm="sha512",
        minecraft_version=None,
        loader=None,
    ):
        del minecraft_version, loader
        return {
            cached_hash: models_module.ModrinthVersionLookupResult(
                file_hash=cached_hash,
                algorithm="sha512",
                project_id="proj123",
                version=latest_version,
            )
        }

    _set_planning_dependency(
        monkeypatch, "get_modrinth_latest_versions_by_hashes", fake_get_modrinth_latest_versions_by_hashes
    )
    _set_planning_dependency(
        monkeypatch, "resolve_modrinth_project_names", lambda _project_ids: {"proj123": "Example Mod"}
    )
    _set_planning_dependency(
        monkeypatch,
        "analyze_version",
        lambda *_args, **_kwargs: models_module.OnlineModCompatibilityReport(),
    )

    update_plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(update_plan.candidates) == 1
    candidate = update_plan.candidates[0]
    assert candidate.current_hash == cached_hash
    assert candidate.project_id == "proj123"
    assert candidate.target_version_name == "2.0.0"
    assert candidate.recommendation_source == "hash_metadata"
    assert candidate.recommendation_confidence == "high"


def test_mod_planning_build_local_update_plan_trusts_hash_current_match_without_project_fallback(monkeypatch) -> None:
    cached_hash = "hash-current-only"
    current_version = models_module.OnlineModVersion(
        version_id="ver-current",
        version_number="1.0.0",
        display_name="1.0.0",
        game_versions=["1.21.1"],
        loaders=["fabric"],
        files=[
            {
                "filename": "example-mod.jar",
                "url": "https://example.invalid/current.jar",
                "primary": True,
                "hashes": {"sha512": cached_hash},
            }
        ],
    )
    local_mod = SimpleNamespace(
        platform_id="proj123",
        name="Example Mod",
        filename="example-mod.jar",
        version="1.0.0",
        minecraft_version="1.21.1",
        loader_type="Fabric",
        file_path="C:/non-existent/example-mod.jar",
        current_hash=cached_hash,
        hash_algorithm="sha512",
    )

    _set_planning_dependency(
        monkeypatch,
        "get_modrinth_current_versions_by_hashes",
        lambda _hashes, _algorithm="sha512": {
            cached_hash: models_module.ModrinthVersionLookupResult(
                file_hash=cached_hash, algorithm="sha512", project_id="proj123", version=current_version
            )
        },
    )
    _set_planning_dependency(monkeypatch, "get_modrinth_latest_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(
        monkeypatch, "resolve_modrinth_project_names", lambda _project_ids: {"proj123": "Example Mod"}
    )
    _set_planning_dependency(
        monkeypatch,
        "provider_identity_fixture",
        lambda *_args, **_kwargs: models_module.OnlineModInfo(
            project_id="proj123", slug="example-mod", name="Example Mod", author="Example"
        ),
    )
    _set_planning_dependency(
        monkeypatch,
        "get_recommended_mod_version",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("hash-resolved entries should not fallback to project-based latest version lookup")
        ),
    )

    update_plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert update_plan.candidates == []


def test_mod_planning_build_local_update_plan_allows_project_fallback_when_hash_mapping_missing(monkeypatch) -> None:
    cached_hash = "hash-without-mapping"
    latest_version = models_module.OnlineModVersion(
        version_id="ver-latest",
        version_number="2.0.0",
        display_name="2.0.0",
        game_versions=["1.21.1"],
        loaders=["fabric"],
        files=[
            {
                "filename": "example-mod-new.jar",
                "url": "https://example.invalid/latest.jar",
                "primary": True,
                "hashes": {"sha512": "new-hash-002"},
            }
        ],
    )
    local_mod = SimpleNamespace(
        platform_id="proj123",
        name="Example Mod",
        filename="example-mod.jar",
        version="1.0.0",
        minecraft_version="1.21.1",
        loader_type="Fabric",
        file_path="C:/non-existent/example-mod.jar",
        current_hash=cached_hash,
        hash_algorithm="sha512",
    )

    _set_planning_dependency(monkeypatch, "get_modrinth_current_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "get_modrinth_latest_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(
        monkeypatch, "resolve_modrinth_project_names", lambda _project_ids: {"proj123": "Example Mod"}
    )
    _set_planning_dependency(
        monkeypatch,
        "provider_identity_fixture",
        lambda *_args, **_kwargs: models_module.OnlineModInfo(
            project_id="proj123", slug="example-mod", name="Example Mod", author="Example"
        ),
    )
    _set_planning_dependency(
        monkeypatch,
        "analyze_version",
        lambda *_args, **_kwargs: models_module.OnlineModCompatibilityReport(),
    )
    _set_planning_dependency(monkeypatch, "get_recommended_mod_version", lambda *_args, **_kwargs: latest_version)

    update_plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(update_plan.candidates) == 1
    assert update_plan.candidates[0].target_version_name == "2.0.0"
    assert update_plan.candidates[0].recommendation_source == "project_fallback"
    assert update_plan.candidates[0].recommendation_confidence == "advisory"


def test_mod_planning_build_local_update_plan_collects_metadata_summary(monkeypatch) -> None:
    local_mod_cached = SimpleNamespace(
        platform_id="inventoryprofilesnext",
        name="Inventory Profiles Next",
        filename="inventory-profiles-next.jar",
        version="2.2.2",
        minecraft_version="1.21.1",
        loader_type="Fabric",
    )
    local_mod_lookup = SimpleNamespace(
        platform_id="",
        name="Sodium",
        filename="sodium.jar",
        version="0.6.0",
        minecraft_version="1.21.1",
        loader_type="Fabric",
    )
    local_mod_unresolved = SimpleNamespace(
        platform_id="",
        name="Unknown Mod",
        filename="unknown-mod.jar",
        version="1.0.0",
        minecraft_version="1.21.1",
        loader_type="Fabric",
    )

    resolved_cached = models_module.OnlineModInfo(
        project_id="YL57xq9U",
        slug="inventory-profiles-next",
        name="Inventory Profiles Next",
        author="Libz",
    )
    resolved_lookup = models_module.OnlineModInfo(
        project_id="AANobbMI",
        slug="sodium",
        name="Sodium",
        author="jellysquid3",
    )

    _set_planning_dependency(monkeypatch, "get_modrinth_current_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "get_modrinth_latest_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(
        monkeypatch,
        "provider_identity_fixture",
        lambda local_mod: (
            resolved_cached
            if getattr(local_mod, "name", "") == "Inventory Profiles Next"
            else resolved_lookup
            if getattr(local_mod, "name", "") == "Sodium"
            else None
        ),
    )
    _set_planning_dependency(
        monkeypatch,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"yl57xq9u": "Inventory Profiles Next", "aanobbmi": "Sodium"},
    )
    _set_planning_dependency(monkeypatch, "get_recommended_mod_version", lambda *_args, **_kwargs: None)

    plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod_cached, local_mod_lookup, local_mod_unresolved],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert plan.metadata_summary.total_scanned == 3
    assert plan.metadata_summary.resolved_by_cached_project == 1
    assert plan.metadata_summary.resolved_by_lookup == 1
    assert plan.metadata_summary.unresolved == 1
    assert any("metadata ensure 結果" in note for note in plan.metadata_summary.notes)


def test_mod_planning_build_local_update_plan_creates_blocked_candidate_for_unresolved_metadata(monkeypatch) -> None:
    local_mod = SimpleNamespace(
        platform_id="",
        name="Unknown Mod",
        filename="unknown-mod.jar",
        version="1.0.0",
        minecraft_version="1.21.1",
        loader_type="Fabric",
        file_path="C:/mods/unknown-mod.jar",
    )

    _set_planning_dependency(monkeypatch, "get_modrinth_current_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "get_modrinth_latest_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "provider_identity_fixture", lambda _local_mod: None)

    plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.metadata_resolved is False
    assert candidate.metadata_source == "unresolved"
    assert candidate.recommendation_source == "metadata_unresolved"
    assert candidate.recommendation_confidence == "blocked"
    assert candidate.project_id == ""
    assert candidate.hard_errors == ["metadata 未識別，暫時無法自動檢查更新"]


def test_mod_planning_build_local_update_plan_marks_stale_revalidation_failure_as_retryable(monkeypatch) -> None:
    stale_epoch_ms = int(time.time() * 1000) - (13 * 60 * 60 * 1000)
    local_mod = SimpleNamespace(
        platform_id="inventoryprofilesnext",
        platform_slug="inventoryprofilesnext",
        provider_identity=models_module.ProviderIdentitySnapshot(
            provider="modrinth",
            project_id="inventoryprofilesnext",
            alias="inventoryprofilesnext",
            display_name="Inventory Profiles Next",
            provenance="scan_detect",
            lifecycle="stale",
            resolved_at_epoch_ms=stale_epoch_ms,
        ),
        name="Inventory Profiles Next",
        filename="inventory-profiles-next.jar",
        version="2.2.2",
        minecraft_version="1.21.1",
        loader_type="Fabric",
        file_path="",
        current_hash="",
        hash_algorithm="",
    )

    _set_planning_dependency(monkeypatch, "get_modrinth_current_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "get_modrinth_latest_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "get_modrinth_project_info", lambda *_args, **_kwargs: None)
    _set_planning_dependency(monkeypatch, "search_mods_online", lambda *_args, **_kwargs: [])

    plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.metadata_source == "stale_provider"
    assert candidate.recommendation_source == "stale_metadata"
    assert candidate.recommendation_confidence == "retryable"
    assert candidate.metadata_resolved is False
    assert candidate.project_id == ""


def test_mod_planning_build_local_update_plan_defers_stale_revalidation_when_backoff_not_due(monkeypatch) -> None:
    stale_epoch_ms = int(time.time() * 1000) - (13 * 60 * 60 * 1000)
    next_retry_epoch_ms = int(time.time() * 1000) + 60_000
    local_mod = SimpleNamespace(
        platform_id="inventoryprofilesnext",
        platform_slug="inventoryprofilesnext",
        provider_identity=models_module.ProviderIdentitySnapshot(
            provider="modrinth",
            project_id="inventoryprofilesnext",
            alias="inventoryprofilesnext",
            display_name="Inventory Profiles Next",
            provenance="scan_detect",
            lifecycle="retrying",
            resolved_at_epoch_ms=stale_epoch_ms,
            failure_count=1,
            next_retry_not_before_epoch_ms=next_retry_epoch_ms,
        ),
        name="Inventory Profiles Next",
        filename="inventory-profiles-next.jar",
        version="2.2.2",
        minecraft_version="1.21.1",
        loader_type="Fabric",
        file_path="",
        current_hash="",
        hash_algorithm="",
    )

    _set_planning_dependency(monkeypatch, "get_modrinth_current_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "get_modrinth_latest_versions_by_hashes", lambda *_args, **_kwargs: {})

    resolve_calls = {"project": 0, "search": 0}

    def _count_project_info(*_args, **_kwargs):
        resolve_calls["project"] += 1

    def _count_search(*_args, **_kwargs):
        resolve_calls["search"] += 1
        return []

    _set_planning_dependency(monkeypatch, "get_modrinth_project_info", _count_project_info)
    _set_planning_dependency(monkeypatch, "search_mods_online", _count_search)

    plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.metadata_source == "stale_provider"
    assert any("退避" in note for note in candidate.notes)
    assert resolve_calls["project"] == 0
    assert resolve_calls["search"] == 0


def test_install_remote_mod_file_downloads_into_mods_dir(tmp_path: Path, monkeypatch) -> None:
    manager = ModManager(str(tmp_path))

    def fake_download_file(url, local_path, progress_callback=None, expected_hash=None, **_kwargs):
        assert url == "https://example.invalid/example.jar"
        assert expected_hash == "c" * 64
        path = Path(local_path)
        assert ".download_staging" in path.parts
        assert path.parents[0] != tmp_path / "mods"
        path.write_bytes(b"jar-bytes")
        if progress_callback:
            progress_callback(10, 10)
        return models_module.OperationResult(True)

    monkeypatch.setattr(utils_module.HTTPClient, "download_file", fake_download_file)

    installed_path = manager.install_remote_mod_file(
        download_url="https://example.invalid/example.jar",
        filename="example.jar",
        expected_hash="c" * 64,
    )

    assert installed_path == tmp_path / "mods" / "example.jar"
    assert installed_path.exists()
    assert installed_path.read_bytes() == b"jar-bytes"


def test_install_remote_mod_file_reuses_existing_verified_file(tmp_path: Path, monkeypatch) -> None:
    manager = ModManager(str(tmp_path))
    target_path = tmp_path / "mods" / "example.jar"
    target_path.parents[0].mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(b"jar-bytes")
    expected_hash = hashlib.sha256(b"jar-bytes").hexdigest()

    def fake_download_file(*_args, **_kwargs):
        raise AssertionError("verified target should skip download")

    monkeypatch.setattr(utils_module.HTTPClient, "download_file", fake_download_file)

    installed_path = manager.install_remote_mod_file(
        download_url="https://example.invalid/example.jar",
        filename="example.jar",
        expected_hash=expected_hash,
    )

    assert installed_path == target_path
    assert installed_path.read_bytes() == b"jar-bytes"


def test_install_remote_mod_file_rejects_missing_or_sha1_hash(tmp_path: Path, monkeypatch) -> None:
    manager = ModManager(str(tmp_path))

    def fake_download_file(*_args, **_kwargs):
        raise AssertionError("remote mod install should reject insecure verification before download")

    monkeypatch.setattr(utils_module.HTTPClient, "download_file", fake_download_file)

    assert (
        manager.install_remote_mod_file(
            download_url="https://example.invalid/example.jar",
            filename="example.jar",
            expected_hash=None,
        )
        is None
    )
    assert (
        manager.install_remote_mod_file(
            download_url="https://example.invalid/example.jar",
            filename="example.jar",
            expected_hash="f" * 40,
        )
        is None
    )
    assert (tmp_path / "mods" / "example.jar").exists() is False


def test_replace_local_mod_file_removes_old_jar_after_update(tmp_path: Path, monkeypatch) -> None:
    manager = ModManager(str(tmp_path))
    old_path = tmp_path / "mods" / "example-old.jar"
    old_path.parents[0].mkdir(parents=True, exist_ok=True)
    old_path.write_bytes(b"old-bytes")
    new_path = tmp_path / "mods" / "example-new.jar"

    local_mod = mod_manager_module.LocalModInfo(
        id="example-old",
        name="Example Mod",
        filename="example-old.jar",
        version="1.0.0",
        minecraft_version="1.21",
        loader_type="Fabric",
        status=models_module.ModStatus.ENABLED,
        file_path=str(old_path),
    )

    def fake_install_remote_result(
        download_url,
        filename,
        progress_callback=None,
        expected_hash=None,
        provider="modrinth",
        cancel_check=None,
        notify_change=True,
    ):
        assert download_url == "https://example.invalid/example-new.jar"
        assert filename == "example-new.jar"
        assert expected_hash == "d" * 64
        assert provider == "modrinth"
        assert cancel_check is None
        assert notify_change is False
        new_path.write_bytes(b"new-bytes")
        if progress_callback:
            progress_callback(10, 10)
        return models_module.ModFileOperationResult(status="completed", final_path=new_path)

    monkeypatch.setattr(manager.mod_file_installer, "install_remote_mod_file_result", fake_install_remote_result)

    replaced_path = manager.mod_file_installer.replace_local_mod_file(
        local_mod,
        "https://example.invalid/example-new.jar",
        "example-new.jar",
        expected_hash="d" * 64,
    )

    assert replaced_path == new_path
    assert new_path.exists()
    assert old_path.exists() is False


def test_replace_local_mod_file_preserves_external_old_path(tmp_path: Path, monkeypatch) -> None:
    manager = ModManager(str(tmp_path))
    external_dir = tmp_path.parents[0] / f"{tmp_path.name}-external"
    external_dir.mkdir(parents=True, exist_ok=True)
    old_path = external_dir / "example-old.jar"
    old_path.write_bytes(b"old-bytes")
    new_path = tmp_path / "mods" / "example-new.jar"

    local_mod = mod_manager_module.LocalModInfo(
        id="example-old",
        name="Example Mod",
        filename="example-old.jar",
        version="1.0.0",
        minecraft_version="1.21",
        loader_type="Fabric",
        status=models_module.ModStatus.ENABLED,
        file_path=str(old_path),
    )

    def fake_install_remote_result(
        download_url,
        filename,
        progress_callback=None,
        expected_hash=None,
        provider="modrinth",
        cancel_check=None,
        notify_change=True,
    ):
        assert download_url == "https://example.invalid/example-new.jar"
        assert filename == "example-new.jar"
        assert expected_hash is None
        assert provider == "modrinth"
        assert cancel_check is None
        assert notify_change is False
        new_path.write_bytes(b"new-bytes")
        if progress_callback:
            progress_callback(10, 10)
        return models_module.ModFileOperationResult(status="completed", final_path=new_path)

    monkeypatch.setattr(manager.mod_file_installer, "install_remote_mod_file_result", fake_install_remote_result)

    replaced_path = manager.mod_file_installer.replace_local_mod_file(
        local_mod,
        "https://example.invalid/example-new.jar",
        "example-new.jar",
    )

    assert replaced_path == new_path
    assert new_path.exists()
    assert old_path.exists() is True


def test_install_remote_mod_file_cancellation_leaves_no_target_file(tmp_path: Path, monkeypatch) -> None:
    manager = ModManager(str(tmp_path))

    def fake_download_file(url, local_path, _progress_callback=None, expected_hash=None, cancel_check=None, **_kwargs):
        assert url == "https://example.invalid/example.jar"
        assert expected_hash == "e" * 64
        assert callable(cancel_check)
        Path(local_path).write_bytes(b"partial")
        return models_module.OperationResult(False, "下載已取消")

    monkeypatch.setattr(utils_module.HTTPClient, "download_file", fake_download_file)

    installed_path = manager.install_remote_mod_file(
        download_url="https://example.invalid/example.jar",
        filename="example.jar",
        expected_hash="e" * 64,
        cancel_check=lambda: True,
    )

    assert installed_path is None
    assert (tmp_path / "mods" / "example.jar").exists() is False


def test_replace_local_mod_file_rolls_back_when_internal_old_delete_fails(tmp_path: Path, monkeypatch) -> None:
    manager = ModManager(str(tmp_path))
    old_path = tmp_path / "mods" / "example-old.jar"
    old_path.parents[0].mkdir(parents=True, exist_ok=True)
    old_path.write_bytes(b"old-bytes")
    new_path = tmp_path / "mods" / "example-new.jar"

    local_mod = mod_manager_module.LocalModInfo(
        id="example-old",
        name="Example Mod",
        filename="example-old.jar",
        version="1.0.0",
        minecraft_version="1.21",
        loader_type="Fabric",
        status=models_module.ModStatus.ENABLED,
        file_path=str(old_path),
    )

    def fake_install_remote_result(*_args, **_kwargs):
        new_path.write_bytes(b"new-bytes")
        return models_module.ModFileOperationResult(status="completed", final_path=new_path)

    original_delete_within = mod_file_installer_module.delete_within

    def fake_delete_within(base_dir, path):
        if Path(path).resolve(strict=False) == old_path.resolve(strict=False):
            return False
        return original_delete_within(base_dir, path)

    monkeypatch.setattr(manager.mod_file_installer, "install_remote_mod_file_result", fake_install_remote_result)
    monkeypatch.setattr(mod_file_installer_module, "delete_within", fake_delete_within)

    replaced_path = manager.mod_file_installer.replace_local_mod_file(
        local_mod,
        "https://example.invalid/example-new.jar",
        "example-new.jar",
    )

    assert replaced_path is None
    assert old_path.exists()
    assert old_path.read_bytes() == b"old-bytes"
    assert new_path.exists() is False


def test_replace_local_mod_file_restores_same_path_when_cancelled_after_replace(tmp_path: Path, monkeypatch) -> None:
    manager = ModManager(str(tmp_path))
    old_path = tmp_path / "mods" / "example.jar"
    old_path.parents[0].mkdir(parents=True, exist_ok=True)
    old_path.write_bytes(b"old-bytes")

    local_mod = mod_manager_module.LocalModInfo(
        id="example",
        name="Example Mod",
        filename="example.jar",
        version="1.0.0",
        minecraft_version="1.21",
        loader_type="Fabric",
        status=models_module.ModStatus.ENABLED,
        file_path=str(old_path),
    )

    cancel_calls = {"count": 0}

    def fake_download_file(_url, local_path, **_kwargs):
        Path(local_path).write_bytes(b"new-bytes")
        return models_module.OperationResult(True)

    def cancel_check() -> bool:
        cancel_calls["count"] += 1
        return cancel_calls["count"] >= 3

    monkeypatch.setattr(utils_module.HTTPClient, "download_file", fake_download_file)

    replaced_path = manager.mod_file_installer.replace_local_mod_file(
        local_mod,
        "https://example.invalid/example.jar",
        "example.jar",
        cancel_check=cancel_check,
    )

    assert replaced_path is None
    assert old_path.exists()
    assert old_path.read_bytes() == b"old-bytes"


def test_mod_planning_build_local_update_plan_reports_hash_progress(tmp_path: Path, monkeypatch) -> None:
    file_path = tmp_path / "mods" / "uncached.jar"
    file_path.parents[0].mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"uncached-content")

    local_mod_cached = SimpleNamespace(
        platform_id="",
        platform_slug="",
        name="Cached Mod",
        filename="cached.jar",
        version="1.0.0",
        minecraft_version="1.21.1",
        loader_type="Fabric",
        file_path="C:/non-existent/cached.jar",
        current_hash="cached-hash-001",
        hash_algorithm="sha512",
    )
    local_mod_uncached = SimpleNamespace(
        platform_id="",
        platform_slug="",
        name="Uncached Mod",
        filename="uncached.jar",
        version="1.0.0",
        minecraft_version="1.21.1",
        loader_type="Fabric",
        file_path=str(file_path),
        current_hash="",
        hash_algorithm="",
    )

    _set_planning_dependency(monkeypatch, "get_modrinth_current_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "get_modrinth_latest_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "provider_identity_fixture", lambda *_args, **_kwargs: None)

    progress_events: list[tuple[int, int]] = []
    plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod_cached, local_mod_uncached],
        minecraft_version="1.21.1",
        loader="fabric",
        hash_progress_callback=lambda done, total: progress_events.append((done, total)),
    )

    assert len(plan.candidates) == 2
    assert progress_events
    assert progress_events[-1] == (2, 2)
    assert all(total == 2 for _, total in progress_events)


def test_analyze_local_mod_file_compatibility_does_not_flag_lossy_mc_version_metadata() -> None:
    local_mod = SimpleNamespace(
        name="Example Mod",
        filename="example.jar",
        version="1.0.0",
        minecraft_version="1.20",
        loader_type="Fabric",
    )

    issues = compatibility_analyzer_module.analyze_local_mod_file_compatibility(local_mod, loader="fabric")
    assert issues == []


def test_analyze_local_mod_file_compatibility_reports_loader_mismatch_on_quilt_server() -> None:
    local_mod = SimpleNamespace(
        name="Fabric API",
        filename="fabric-api.jar",
        version="1.0.0",
        minecraft_version="1.21.1",
        loader_type="Fabric",
    )

    issues = compatibility_analyzer_module.analyze_local_mod_file_compatibility(local_mod, loader="quilt")

    assert issues
    assert any("載入器" in issue for issue in issues)


def test_get_recommended_mod_version_does_not_fallback_for_unsupported_loader(monkeypatch) -> None:
    _set_planning_dependency(
        monkeypatch,
        "get_mod_versions",
        lambda _project_id, _minecraft_version=None, loader=None: (
            []
            if loader
            else (_ for _ in ()).throw(AssertionError("unsupported loader should not fallback to unfiltered versions"))
        ),
    )

    resolved = mod_search_provider_module.get_recommended_mod_version(
        "example-project",
        minecraft_version="1.21.1",
        loader="paper",
    )

    assert resolved is None


def test_mod_planning_build_local_update_plan_skips_online_update_check_for_unsupported_loader(monkeypatch) -> None:
    local_mod = SimpleNamespace(
        platform_id="",
        platform_slug="",
        name="Example Mod",
        filename="example-mod.jar",
        version="1.0.0",
        minecraft_version="1.21.1",
        loader_type="Fabric",
        file_path="C:/mods/example-mod.jar",
        current_hash="abc123",
        hash_algorithm="sha512",
    )

    _set_planning_dependency(monkeypatch, "get_modrinth_current_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(
        monkeypatch,
        "get_modrinth_latest_versions_by_hashes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unsupported loader should skip hash-based latest update lookup")
        ),
    )
    _set_planning_dependency(
        monkeypatch,
        "provider_identity_fixture",
        lambda *_args, **_kwargs: models_module.OnlineModInfo(
            project_id="proj123", slug="example-mod", name="Example Mod", author="Example"
        ),
    )
    _set_planning_dependency(
        monkeypatch, "resolve_modrinth_project_names", lambda _project_ids: {"proj123": "Example Mod"}
    )
    _set_planning_dependency(
        monkeypatch,
        "get_recommended_mod_version",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unsupported loader should skip project-based fallback update lookup")
        ),
    )

    plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="paper",
    )

    assert plan.candidates == []
    assert any("已略過" in note and "paper" in note for note in plan.notes)


def test_mod_planning_build_local_update_plan_treats_local_metadata_as_advisory_when_no_online_version(
    monkeypatch,
) -> None:
    local_mod = SimpleNamespace(
        platform_id="",
        platform_slug="",
        name="Example Mod",
        filename="example-mod.jar",
        version="1.0.0",
        minecraft_version="1.21.1",
        loader_type="Forge",
        file_path="C:/mods/example-mod.jar",
        current_hash="hash-old-001",
        hash_algorithm="sha512",
    )

    _set_planning_dependency(monkeypatch, "get_modrinth_current_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "get_modrinth_latest_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(
        monkeypatch,
        "provider_identity_fixture",
        lambda *_args, **_kwargs: models_module.OnlineModInfo(
            project_id="proj123", slug="example-mod", name="Example Mod", author="Example"
        ),
    )
    _set_planning_dependency(
        monkeypatch, "resolve_modrinth_project_names", lambda _project_ids: {"proj123": "Example Mod"}
    )
    _set_planning_dependency(monkeypatch, "get_recommended_mod_version", lambda *_args, **_kwargs: None)

    plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert plan.candidates == []
    assert any("僅作提示，不影響更新判定" in note for note in plan.notes)


def test_mod_planning_build_local_update_plan_adds_local_metadata_advisory_note_to_candidate(monkeypatch) -> None:
    local_mod = SimpleNamespace(
        platform_id="",
        platform_slug="",
        name="Example Mod",
        filename="example-mod.jar",
        version="1.0.0",
        minecraft_version="1.21.1",
        loader_type="Forge",
        file_path="C:/mods/example-mod.jar",
        current_hash="hash-old-001",
        hash_algorithm="sha512",
    )
    latest_version = models_module.OnlineModVersion(
        version_id="ver-latest",
        version_number="2.0.0",
        display_name="2.0.0",
        game_versions=["1.21.1"],
        loaders=["fabric"],
        files=[
            {
                "filename": "example-mod-new.jar",
                "url": "https://example.invalid/latest.jar",
                "primary": True,
                "hashes": {"sha512": "hash-new-002"},
            }
        ],
    )

    _set_planning_dependency(monkeypatch, "get_modrinth_current_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "get_modrinth_latest_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(
        monkeypatch,
        "provider_identity_fixture",
        lambda *_args, **_kwargs: models_module.OnlineModInfo(
            project_id="proj123", slug="example-mod", name="Example Mod", author="Example"
        ),
    )
    _set_planning_dependency(
        monkeypatch, "resolve_modrinth_project_names", lambda _project_ids: {"proj123": "Example Mod"}
    )
    _set_planning_dependency(monkeypatch, "get_recommended_mod_version", lambda *_args, **_kwargs: latest_version)
    _set_planning_dependency(
        monkeypatch,
        "analyze_version",
        lambda *_args, **_kwargs: models_module.OnlineModCompatibilityReport(),
    )

    plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.current_issues == []
    assert any(note.startswith("本地 metadata 提示：") for note in candidate.notes)


def test_mod_planning_build_local_update_plan_prefers_provider_current_version_over_local_version(monkeypatch) -> None:
    local_hash = "hash-001"
    current_version = models_module.OnlineModVersion(
        version_id="ver-current",
        version_number="1.0.0",
        display_name="1.0.0-provider",
        game_versions=["1.21.1"],
        loaders=["fabric"],
        files=[
            {
                "filename": "example-mod.jar",
                "url": "https://example.invalid/current.jar",
                "primary": True,
                "hashes": {"sha512": local_hash},
            }
        ],
    )
    latest_version = models_module.OnlineModVersion(
        version_id="ver-latest",
        version_number="2.0.0",
        display_name="2.0.0",
        game_versions=["1.21.1"],
        loaders=["fabric"],
        files=[
            {
                "filename": "example-mod-new.jar",
                "url": "https://example.invalid/latest.jar",
                "primary": True,
                "hashes": {"sha512": "hash-002"},
            }
        ],
    )
    local_mod = SimpleNamespace(
        platform_id="proj123",
        platform_slug="example-mod",
        name="Example Mod",
        filename="example-mod.jar",
        version="0.9.0-local",
        minecraft_version="1.21.1",
        loader_type="Fabric",
        file_path="C:/mods/example-mod.jar",
        current_hash=local_hash,
        hash_algorithm="sha512",
    )

    _set_planning_dependency(
        monkeypatch,
        "get_modrinth_current_versions_by_hashes",
        lambda *_args, **_kwargs: {
            local_hash: models_module.ModrinthVersionLookupResult(
                file_hash=local_hash, algorithm="sha512", project_id="proj123", version=current_version
            )
        },
    )
    _set_planning_dependency(
        monkeypatch,
        "get_modrinth_latest_versions_by_hashes",
        lambda *_args, **_kwargs: {
            local_hash: models_module.ModrinthVersionLookupResult(
                file_hash=local_hash, algorithm="sha512", project_id="proj123", version=latest_version
            )
        },
    )
    _set_planning_dependency(
        monkeypatch, "resolve_modrinth_project_names", lambda _project_ids: {"proj123": "Example Mod"}
    )
    _set_planning_dependency(
        monkeypatch,
        "analyze_version",
        lambda *_args, **_kwargs: models_module.OnlineModCompatibilityReport(),
    )

    plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(plan.candidates) == 1
    assert plan.candidates[0].current_version == "1.0.0-provider"
    assert plan.candidates[0].recommendation_source == "hash_metadata"
    assert plan.candidates[0].recommendation_confidence == "high"


def test_mod_planning_build_local_update_plan_marks_project_fallback_candidate_as_advisory(monkeypatch) -> None:
    local_mod = SimpleNamespace(
        platform_id="proj123",
        platform_slug="example-mod",
        name="Example Mod",
        filename="example-mod.jar",
        version="1.0.0-local",
        minecraft_version="1.21.1",
        loader_type="Fabric",
        file_path="C:/mods/example-mod.jar",
        current_hash="hash-without-map",
        hash_algorithm="sha512",
    )
    latest_version = models_module.OnlineModVersion(
        version_id="ver-latest",
        version_number="2.0.0",
        display_name="2.0.0",
        game_versions=["1.21.1"],
        loaders=["fabric"],
        files=[
            {
                "filename": "example-mod-new.jar",
                "url": "https://example.invalid/latest.jar",
                "primary": True,
                "hashes": {"sha512": "hash-new-002"},
            }
        ],
    )

    _set_planning_dependency(monkeypatch, "get_modrinth_current_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "get_modrinth_latest_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(
        monkeypatch, "resolve_modrinth_project_names", lambda _project_ids: {"proj123": "Example Mod"}
    )
    _set_planning_dependency(
        monkeypatch,
        "provider_identity_fixture",
        lambda *_args, **_kwargs: models_module.OnlineModInfo(
            project_id="proj123", slug="example-mod", name="Example Mod", author="Example"
        ),
    )
    _set_planning_dependency(
        monkeypatch,
        "analyze_version",
        lambda *_args, **_kwargs: models_module.OnlineModCompatibilityReport(),
    )
    _set_planning_dependency(monkeypatch, "get_recommended_mod_version", lambda *_args, **_kwargs: latest_version)

    plan = _TEST_PLANNING.build_local_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(plan.candidates) == 1
    candidate_notes = plan.candidates[0].notes
    assert any("project fallback" in note for note in candidate_notes)
    assert any("尚未由 provider metadata 確認" in note for note in candidate_notes)
    assert plan.candidates[0].recommendation_source == "project_fallback"
    assert plan.candidates[0].recommendation_confidence == "advisory"


def test_mod_planning_build_local_update_plan_mixed_fault_hash_hit_plus_unresolved(monkeypatch) -> None:
    resolved_mod = SimpleNamespace(
        filename="sodium-0.6.0.jar",
        name="Sodium",
        platform_id="sodium",
        platform_slug="sodium",
        current_hash="",
        hash_algorithm="sha512",
        version="0.6.0",
        enabled=True,
    )
    unresolved_mod = SimpleNamespace(
        filename="mystery-mod-1.0.jar",
        name="Mystery Mod",
        platform_id="",
        platform_slug="",
        current_hash="",
        hash_algorithm="sha512",
        version="1.0",
        enabled=True,
    )

    latest_version = models_module.OnlineModVersion(
        version_id="sodium-v2",
        version_number="0.7.0",
        display_name="0.7.0",
        game_versions=["1.21.1"],
        loaders=["fabric"],
        files=[{"filename": "sodium-0.7.0.jar", "url": "https://cdn.modrinth.com/sodium-0.7.0.jar", "primary": True}],
    )

    _set_planning_dependency(monkeypatch, "get_modrinth_current_versions_by_hashes", lambda *_args, **_kwargs: {})
    _set_planning_dependency(monkeypatch, "get_modrinth_latest_versions_by_hashes", lambda *_args, **_kwargs: {})

    _set_planning_dependency(monkeypatch, "provider_identity_fixture", lambda _local_mod: None)
    _set_planning_dependency(monkeypatch, "resolve_modrinth_project_names", lambda _project_ids: {})
    _set_planning_dependency(
        monkeypatch,
        "analyze_version",
        lambda *_args, **_kwargs: models_module.OnlineModCompatibilityReport(),
    )
    _set_planning_dependency(
        monkeypatch,
        "get_recommended_mod_version",
        lambda project_id, *_args, **_kwargs: latest_version if project_id == "sodium" else None,
    )

    plan = _TEST_PLANNING.build_local_update_plan(
        [resolved_mod, unresolved_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    sodium_candidates = [c for c in plan.candidates if "sodium" in str(getattr(c, "project_id", "")).lower()]
    mystery_candidates = [
        c
        for c in plan.candidates
        if "mystery" in str(getattr(c, "project_name", "")).lower()
        or str(getattr(c, "project_id", "")).startswith("__unresolved__")
    ]

    assert len(plan.candidates) >= 1
    if sodium_candidates:
        assert sodium_candidates[0].recommendation_confidence in ("high", "advisory")
    if mystery_candidates:
        assert mystery_candidates[0].recommendation_confidence in ("blocked", "retryable")


def test_dependency_plan_persistence_payload_roundtrip_includes_provider_fields() -> None:
    plan = models_module.OnlineDependencyInstallPlan(
        items=[
            models_module.OnlineDependencyInstallItem(
                project_id="AANobbMI",
                project_name="Sodium",
                version_id="ver-1",
                version_name="1.0.0",
                filename="sodium.jar",
                download_url="https://cdn.example/sodium.jar",
                parent_name="Root Mod",
                resolution_source="project_id",
                resolution_confidence="direct",
                provider="modrinth",
                expected_hash="a" * 64,
                required_by=["Root Mod"],
                decision_source="required:auto",
                graph_depth=1,
                edge_kind="required",
                edge_source="required:modrinth_dependency",
            )
        ],
        advisory_items=[
            models_module.OnlineDependencyInstallItem(
                project_id="P7dR8mSH",
                project_name="Fabric API",
                version_id="ver-2",
                version_name="2.0.0",
                filename="fabric-api.jar",
                download_url="https://cdn.example/fabric-api.jar",
                parent_name="Root Mod",
                included_by_default=False,
                is_optional=True,
                provider="modrinth",
                expected_hash="b" * 64,
                required_by=["Root Mod"],
                decision_source="optional:advisory_default_disabled",
                graph_depth=2,
                edge_kind="optional",
                edge_source="optional:modrinth_dependency",
            )
        ],
        unresolved_required=["缺少必要依賴"],
        notes=["note"],
    )

    payload = utils_module.serialize_online_dependency_install_plan(
        plan,
        root_project_id="root-proj",
        root_project_name="Root Mod",
        root_target_version_id="root-ver-1",
        root_target_version_name="1.2.3",
        plan_source="local_update_review",
    )
    restored = utils_module.deserialize_online_dependency_install_plan(payload)

    assert payload["schema_version"] == 2
    assert payload["plan_source"] == "local_update_review"
    assert payload["root_project_id"] == "root-proj"
    assert payload["root_target_version_id"] == "root-ver-1"
    assert payload["root_target_version_name"] == "1.2.3"
    assert payload["items"][0]["provider"] == "modrinth"
    assert payload["items"][0]["expected_hash"] == "a" * 64
    assert payload["items"][0]["required_by"] == ["Root Mod"]
    assert payload["items"][0]["decision_source"] == "required:auto"
    assert payload["items"][0]["graph_depth"] == 1
    assert payload["items"][0]["edge_kind"] == "required"
    assert payload["items"][0]["edge_source"] == "required:modrinth_dependency"
    assert payload["advisory_items"][0]["expected_hash"] == "b" * 64
    assert payload["advisory_items"][0]["decision_source"] == "optional:advisory_default_disabled"
    assert payload["advisory_items"][0]["graph_depth"] == 2
    assert payload["graph_edges"][0]["depth"] == 1
    assert payload["graph_edges"][0]["edge"] == "required"
    assert payload["graph_edges"][1]["edge"] == "optional"
    assert utils_module.validate_online_dependency_install_plan_payload(payload) == (True, "ok")
    assert restored.items[0].project_id == "AANobbMI"
    assert restored.items[0].required_by == ["Root Mod"]
    assert restored.items[0].expected_hash == "a" * 64
    assert restored.items[0].graph_depth == 1
    assert restored.items[0].edge_kind == "required"
    assert restored.advisory_items[0].decision_source == "optional:advisory_default_disabled"
    assert restored.advisory_items[0].expected_hash == "b" * 64


def test_migrate_online_dependency_install_plan_payload_recovers_missing_graph_edges() -> None:
    legacy_payload = {
        "schema_version": 1,
        "plan_source": "local_update_review",
        "root_project_id": "root-proj",
        "root_project_name": "Root Mod",
        "root_target_version_id": "root-ver",
        "items": [
            {
                "project_id": "AANobbMI",
                "project_name": "Sodium",
                "version_id": "ver-1",
                "version_name": "1.0.0",
                "filename": "sodium.jar",
                "download_url": "https://cdn.example/sodium.jar",
                "required_by": ["Root Mod"],
                "enabled": True,
                "is_optional": False,
            }
        ],
        "advisory_items": [],
        "unresolved_required": [],
        "notes": [],
    }

    migrated, state = utils_module.migrate_online_dependency_install_plan_payload(legacy_payload)

    assert migrated is not None
    assert state == "migrated"
    assert isinstance(migrated.get("graph_edges"), list)
    assert migrated["graph_edges"][0]["edge"] == "required"
    assert migrated["graph_edges"][0]["depth"] == 1
    valid, reason = utils_module.validate_online_dependency_install_plan_payload(migrated)
    assert valid is True
    assert reason == "ok"
