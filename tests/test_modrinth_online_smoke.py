from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import src.core.mod_manager as mod_manager_module
import src.ui.mod_search_service as mod_search_service_module


@pytest.mark.smoke
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

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "get_json", fake_get_json)

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


@pytest.mark.smoke
def test_search_mods_online_passes_category_facets(monkeypatch) -> None:
    captured_params: dict[str, object] = {}

    def fake_get_json(**kwargs):
        captured_params.update(kwargs.get("params", {}))
        return {"hits": []}

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "get_json", fake_get_json)

    mod_search_service_module.search_mods_online(
        "sodium",
        minecraft_version="1.21",
        loader="fabric",
        categories=["optimization"],
    )

    assert "categories:optimization" in str(captured_params.get("facets", ""))
    assert "server_side:required" in str(captured_params.get("facets", ""))
    assert "server_side:optional" in str(captured_params.get("facets", ""))


@pytest.mark.smoke
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

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "get_json", fake_get_json)

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


@pytest.mark.smoke
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

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "get_json", fake_get_json)

    results = mod_search_service_module.search_mods_online("", minecraft_version="1.21", loader="fabric")

    assert [mod.project_id for mod in results] == ["server-mod"]


@pytest.mark.smoke
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

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "get_json", fake_get_json)

    versions = mod_search_service_module.get_mod_versions("proj123", minecraft_version="1.21", loader="fabric")

    assert len(versions) == 1
    assert versions[0].version_id == "ver1"
    assert versions[0].primary_file is not None
    assert versions[0].primary_file["filename"] == "example.jar"


@pytest.mark.smoke
def test_get_mod_versions_accepts_fabric_alias_for_quilt_loader(monkeypatch) -> None:
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

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "get_json", fake_get_json)

    versions = mod_search_service_module.get_mod_versions("proj123", minecraft_version="1.21", loader="quilt")

    assert [version.version_id for version in versions] == ["ver-fabric"]


@pytest.mark.smoke
def test_get_mod_versions_accepts_forge_alias_for_neoforge_on_1_20_1(monkeypatch) -> None:
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

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "get_json", fake_get_json)

    versions = mod_search_service_module.get_mod_versions(
        "proj123",
        minecraft_version="1.20.1",
        loader="neoforge",
    )

    assert [version.version_id for version in versions] == ["ver-forge"]


@pytest.mark.smoke
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

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "get_json", fake_get_json)

    versions = mod_search_service_module.get_mod_versions("proj123", minecraft_version="1.21", loader="fabric")

    assert [version.version_id for version in versions] == ["release1"]


@pytest.mark.smoke
def test_get_recommended_mod_version_returns_none_when_only_prerelease_exists(monkeypatch) -> None:
    def fake_get_mod_versions(_project_id: str, _minecraft_version=None, _loader=None):
        return []

    monkeypatch.setattr(mod_search_service_module, "get_mod_versions", fake_get_mod_versions)

    assert (
        mod_search_service_module.get_recommended_mod_version("proj123", minecraft_version="1.21", loader="fabric")
        is None
    )


@pytest.mark.smoke
def test_get_mod_versions_preserves_project_id_case_for_api(monkeypatch) -> None:
    captured_url = {"value": ""}

    def fake_get_json(**kwargs):
        captured_url["value"] = kwargs.get("url", "")
        return []

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "get_json", fake_get_json)

    mod_search_service_module.get_mod_versions("P7dR8mSH")

    assert captured_url["value"].endswith("/project/P7dR8mSH/version")


@pytest.mark.smoke
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

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "post_json", fake_post_json)

    results = mod_search_service_module.get_modrinth_latest_versions_by_hashes(
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


@pytest.mark.smoke
def test_get_modrinth_latest_versions_by_hashes_expands_loader_aliases_for_quilt(monkeypatch) -> None:
    captured_request: dict[str, object] = {}

    def fake_post_json(**kwargs):
        captured_request.update(kwargs)
        return {}

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "post_json", fake_post_json)

    mod_search_service_module.get_modrinth_latest_versions_by_hashes(
        ["abc123"],
        minecraft_version="1.21.1",
        loader="quilt",
    )

    assert captured_request["json_body"] == {
        "hashes": ["abc123"],
        "algorithm": "sha512",
        "game_versions": ["1.21.1"],
        "loaders": ["quilt", "fabric"],
    }


@pytest.mark.smoke
def test_get_modrinth_latest_versions_by_hashes_expands_loader_aliases_for_neoforge_1_20_1(monkeypatch) -> None:
    captured_request: dict[str, object] = {}

    def fake_post_json(**kwargs):
        captured_request.update(kwargs)
        return {}

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "post_json", fake_post_json)

    mod_search_service_module.get_modrinth_latest_versions_by_hashes(
        ["abc123"],
        minecraft_version="1.20.1",
        loader="neoforge",
    )

    assert captured_request["json_body"] == {
        "hashes": ["abc123"],
        "algorithm": "sha512",
        "game_versions": ["1.20.1"],
        "loaders": ["neoforge", "forge"],
    }


@pytest.mark.smoke
def test_search_mods_online_expands_loader_alias_facets_for_quilt(monkeypatch) -> None:
    captured_params: dict[str, object] = {}

    def fake_get_json(**kwargs):
        captured_params.update(kwargs.get("params", {}))
        return {"hits": []}

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "get_json", fake_get_json)

    mod_search_service_module.search_mods_online("sodium", minecraft_version="1.21", loader="quilt")

    facets_text = str(captured_params.get("facets", ""))
    assert "categories:quilt" in facets_text
    assert "categories:fabric" in facets_text


@pytest.mark.smoke
def test_enhance_local_mod_prefers_exact_project_lookup_before_fuzzy_search(monkeypatch) -> None:
    requested_urls: list[str] = []

    def fake_get_json(**kwargs):
        requested_urls.append(kwargs.get("url", ""))
        return {
            "id": "P7dR8mSH",
            "slug": "fabric-api",
            "title": "Fabric API",
            "description": "Core hooks and interoperability for Fabric mods.",
            "downloads": 987654,
            "categories": ["fabric", "library"],
            "versions": ["version-a"],
        }

    def fail_search(*_args, **_kwargs):
        raise AssertionError("fuzzy search should not run when platform_id is available")

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "get_json", fake_get_json)
    monkeypatch.setattr(mod_search_service_module, "search_mods_online", fail_search)

    enhanced = mod_search_service_module.enhance_local_mod(
        "fabric-api-0.120.0+1.21.1.jar",
        platform_id="fabric-api",
        local_name="Fabric API",
    )

    assert enhanced is not None
    assert enhanced.project_id == "P7dR8mSH"
    assert enhanced.slug == "fabric-api"
    assert enhanced.name == "Fabric API"
    assert requested_urls == ["https://api.modrinth.com/v2/project/fabric-api"]


@pytest.mark.smoke
def test_enhance_local_mod_rejects_low_confidence_fuzzy_match(monkeypatch) -> None:
    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_project_info",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "search_mods_online",
        lambda *_args, **_kwargs: [
            mod_search_service_module.OnlineModInfo(
                project_id="proj-unrelated",
                slug="totally-different-mod",
                name="Totally Different Mod",
                author="Someone",
            )
        ],
    )

    enhanced = mod_search_service_module.enhance_local_mod(
        "inventory-profiles-next-2.2.2.jar",
        platform_id="",
        local_name="Inventory Profiles Next",
    )

    assert enhanced is None


@pytest.mark.smoke
def test_analyze_mod_version_compatibility_reports_hard_errors() -> None:
    version = mod_search_service_module.OnlineModVersion(
        version_id="ver1",
        version_number="1.0.0",
        display_name="1.0.0",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[{"filename": "example.jar", "url": "https://example.invalid/example.jar", "primary": True}],
    )

    report = mod_search_service_module.analyze_mod_version_compatibility(
        version,
        project_id="proj123",
        project_name="Example Mod",
        minecraft_version="1.21",
        loader="fabric",
        loader_version="0.16.0",
    )

    assert report.compatible is False
    assert any("Minecraft" in item for item in report.hard_errors)
    assert any("載入器" in item for item in report.hard_errors)
    loader_rule_messages = list(report.notes) + list(report.warnings)
    assert any("0.16.0" in item for item in loader_rule_messages)


@pytest.mark.smoke
def test_analyze_mod_version_compatibility_accepts_fabric_version_on_quilt_server() -> None:
    version = mod_search_service_module.OnlineModVersion(
        version_id="ver1",
        version_number="1.0.0",
        display_name="1.0.0",
        game_versions=["1.21"],
        loaders=["fabric"],
        files=[{"filename": "example.jar", "url": "https://example.invalid/example.jar", "primary": True}],
    )

    report = mod_search_service_module.analyze_mod_version_compatibility(
        version,
        project_id="proj123",
        project_name="Example Mod",
        minecraft_version="1.21",
        loader="quilt",
    )

    assert not any("載入器" in item for item in report.hard_errors)


@pytest.mark.smoke
def test_analyze_mod_version_compatibility_reports_dependencies() -> None:
    version = mod_search_service_module.OnlineModVersion(
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

    report = mod_search_service_module.analyze_mod_version_compatibility(
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

    assert report.compatible is True
    assert report.already_installed == ["Example Mod"]
    assert report.missing_required_dependencies == ["Cloth Config"]
    assert report.optional_dependencies == ["Mod Menu"]
    assert report.incompatible_installed == ["Legacy Conflict"]


@pytest.mark.smoke
def test_analyze_mod_version_compatibility_detects_version_id_dependency_mismatch(monkeypatch) -> None:
    dependency_version = mod_search_service_module.OnlineModVersion(
        version_id="dep-v2",
        version_number="2.0.0",
        display_name="2.0.0",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[{"filename": "dep.jar", "url": "https://example.invalid/dep.jar", "primary": True}],
    )
    version = mod_search_service_module.OnlineModVersion(
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

    monkeypatch.setattr(
        mod_search_service_module,
        "get_mod_version_details",
        lambda version_id: ("cloth-config", dependency_version) if version_id == "p7dr8msh" else ("", None),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "_fetch_modrinth_project_name",
        lambda project_id: "Cloth Config" if project_id == "cloth-config" else None,
    )

    report = mod_search_service_module.analyze_mod_version_compatibility(
        version,
        project_id="clumps",
        project_name="Clumps",
        minecraft_version="1.20.1",
        loader="forge",
        installed_mods=installed_mods,
        dependency_names={},
    )

    assert report.compatible is True
    assert report.missing_required_dependencies == ["Cloth Config（需求版本：2.0.0）"]
    assert len(report.installed_version_mismatches) == 1
    assert "版本為 1.0.0" in report.installed_version_mismatches[0]
    assert "需求版本 2.0.0" in report.installed_version_mismatches[0]


@pytest.mark.smoke
def test_analyze_mod_version_compatibility_marks_required_dependency_as_maybe_installed(monkeypatch) -> None:
    dependency_version = mod_search_service_module.OnlineModVersion(
        version_id="dep-v2",
        version_number="2.0.0",
        display_name="2.0.0",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[
            {"filename": "cloth-config-2.0.0.jar", "url": "https://example.invalid/cloth-config.jar", "primary": True}
        ],
    )
    version = mod_search_service_module.OnlineModVersion(
        version_id="root-v1",
        version_number="12.0.0.4",
        display_name="12.0.0.4",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[{"filename": "root.jar", "url": "https://example.invalid/root.jar", "primary": True}],
        dependencies=[{"version_id": "p7dr8msh", "dependency_type": "required"}],
    )
    installed_mods = [SimpleNamespace(filename="cloth_config+1.0.0.jar", name="Unknown Mod")]

    monkeypatch.setattr(
        mod_search_service_module,
        "get_mod_version_details",
        lambda version_id: ("cloth-config", dependency_version) if version_id == "p7dr8msh" else ("", None),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "_fetch_modrinth_project_name",
        lambda project_id: "Cloth Config" if project_id == "cloth-config" else None,
    )

    report = mod_search_service_module.analyze_mod_version_compatibility(
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
    assert "Cloth Config（需求版本：2.0.0） 可能已存在本地相近檔名，請手動確認是否已安裝。" in report.notes


@pytest.mark.smoke
def test_build_required_dependency_install_plan_resolves_version_id_dependency(monkeypatch) -> None:
    dependency_version = mod_search_service_module.OnlineModVersion(
        version_id="dep-v2",
        version_number="2.0.0",
        display_name="2.0.0",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[{"filename": "cloth-config.jar", "url": "https://example.invalid/cloth-config.jar", "primary": True}],
    )
    root_version = mod_search_service_module.OnlineModVersion(
        version_id="root-v1",
        version_number="12.0.0.4",
        display_name="12.0.0.4",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[{"filename": "root.jar", "url": "https://example.invalid/root.jar", "primary": True}],
        dependencies=[{"version_id": "p7dr8msh", "dependency_type": "required"}],
    )

    monkeypatch.setattr(
        mod_search_service_module,
        "get_mod_version_details",
        lambda version_id: ("cloth-config", dependency_version) if version_id == "p7dr8msh" else ("", None),
    )

    def fake_fetch_modrinth_project_name(project_id: str) -> str | None:
        return "Cloth Config" if project_id == "cloth-config" else None

    def fake_get_mod_versions(_project_id: str, _minecraft_version=None, _loader=None):
        return []

    monkeypatch.setattr(mod_search_service_module, "_fetch_modrinth_project_name", fake_fetch_modrinth_project_name)
    monkeypatch.setattr(mod_search_service_module, "get_mod_versions", fake_get_mod_versions)

    plan = mod_search_service_module.build_required_dependency_install_plan(
        root_version,
        minecraft_version="1.20.1",
        loader="forge",
        installed_mods=[],
        root_project_id="clumps",
        root_project_name="Clumps",
    )

    assert plan.has_unresolved_required is False
    assert len(plan.items) == 1
    assert plan.items[0].project_id == "cloth-config"
    assert plan.items[0].project_name == "Cloth Config（需求版本：2.0.0）"
    assert plan.items[0].version_id == "dep-v2"


@pytest.mark.smoke
def test_build_required_dependency_install_plan_marks_maybe_installed_dependency_as_unresolved(monkeypatch) -> None:
    dependency_version = mod_search_service_module.OnlineModVersion(
        version_id="dep-v2",
        version_number="2.0.0",
        display_name="2.0.0",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[
            {"filename": "cloth-config-2.0.0.jar", "url": "https://example.invalid/cloth-config.jar", "primary": True}
        ],
    )
    root_version = mod_search_service_module.OnlineModVersion(
        version_id="root-v1",
        version_number="12.0.0.4",
        display_name="12.0.0.4",
        game_versions=["1.20.1"],
        loaders=["forge"],
        files=[{"filename": "root.jar", "url": "https://example.invalid/root.jar", "primary": True}],
        dependencies=[{"version_id": "p7dr8msh", "dependency_type": "required"}],
    )
    installed_mods = [SimpleNamespace(filename="cloth_config+1.0.0.jar", name="Unknown Mod")]

    monkeypatch.setattr(
        mod_search_service_module,
        "get_mod_version_details",
        lambda version_id: ("cloth-config", dependency_version) if version_id == "p7dr8msh" else ("", None),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "_fetch_modrinth_project_name",
        lambda project_id: "Cloth Config" if project_id == "cloth-config" else None,
    )

    plan = mod_search_service_module.build_required_dependency_install_plan(
        root_version,
        minecraft_version="1.20.1",
        loader="forge",
        installed_mods=installed_mods,
        root_project_id="clumps",
        root_project_name="Clumps",
    )

    assert plan.items == []
    assert plan.has_unresolved_required is False
    assert len(plan.advisory_items) == 1
    assert plan.advisory_items[0].project_name == "Cloth Config（需求版本：2.0.0）"
    assert plan.advisory_items[0].maybe_installed is True
    assert plan.advisory_items[0].enabled is False
    assert plan.advisory_items[0].filename == "cloth-config-2.0.0.jar"
    assert plan.advisory_items[0].download_url == "https://example.invalid/cloth-config.jar"
    assert "預設略過自動安裝" in plan.advisory_items[0].status_note
    assert any("已預設略過自動安裝" in note for note in plan.notes)


@pytest.mark.smoke
def test_build_local_mod_update_plan_uses_resolved_online_project_id(monkeypatch) -> None:
    captured_project_ids: list[str] = []
    local_mod = SimpleNamespace(
        platform_id="inventoryprofilesnext",
        name="Inventory Profiles Next",
        filename="InventoryProfilesNext-fabric-1.21.11-2.2.2.jar",
        version="2.2.2",
        loader_type="Fabric",
        minecraft_version="1.21.11",
    )
    resolved_info = mod_search_service_module.OnlineModInfo(
        project_id="YL57xq9U",
        slug="inventory-profiles-next",
        name="Inventory Profiles Next",
        author="Libz",
    )

    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_local_mod_project_info",
        lambda _local_mod: resolved_info,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"yl57xq9u": "Inventory Profiles Next"},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_local_mod_file_compatibility",
        lambda _local_mod, _minecraft_version=None, _loader=None: [],
    )

    def fake_get_recommended_mod_version(project_id: str, _minecraft_version=None, _loader=None):
        captured_project_ids.append(project_id)
        return

    monkeypatch.setattr(
        mod_search_service_module,
        "get_recommended_mod_version",
        fake_get_recommended_mod_version,
    )

    plan = mod_search_service_module.build_local_mod_update_plan(
        [local_mod],
        minecraft_version="1.21.11",
        loader="fabric",
    )

    assert captured_project_ids == ["YL57xq9U"]
    assert plan.candidates == []


@pytest.mark.smoke
def test_resolve_local_mod_project_info_normalizes_camel_case_local_names(monkeypatch) -> None:
    local_mod = SimpleNamespace(
        platform_id="inventoryprofilesnext",
        platform_slug="",
        name="InventoryProfilesNext-fabric-1.21.11-2.2.2",
        filename="InventoryProfilesNext-fabric-1.21.11-2.2.2.jar",
    )
    attempted_identifiers: list[str] = []
    resolved_info = mod_search_service_module.OnlineModInfo(
        project_id="YL57xq9U",
        slug="inventory-profiles-next",
        name="Inventory Profiles Next",
        author="Libz",
    )

    def fake_get_modrinth_project_info(identifier: str):
        attempted_identifiers.append(identifier)
        if identifier == "inventory-profiles-next":
            return resolved_info
        return None

    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_project_info",
        fake_get_modrinth_project_info,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "search_mods_online",
        lambda *_args, **_kwargs: [],
    )

    resolved = mod_search_service_module.resolve_local_mod_project_info(local_mod)

    assert resolved is resolved_info
    assert "inventory-profiles-next" in attempted_identifiers


@pytest.mark.smoke
def test_resolve_local_mod_project_info_uses_platform_slug_when_project_id_missing(monkeypatch) -> None:
    local_mod = SimpleNamespace(
        platform_id="",
        platform_slug="inventory-profiles-next",
        name="InventoryProfilesNext",
        filename="InventoryProfilesNext.jar",
    )
    attempted_identifiers: list[str] = []
    resolved_info = mod_search_service_module.OnlineModInfo(
        project_id="YL57xq9U",
        slug="inventory-profiles-next",
        name="Inventory Profiles Next",
        author="Libz",
    )

    def fake_get_modrinth_project_info(identifier: str):
        attempted_identifiers.append(identifier)
        if identifier == "inventory-profiles-next":
            return resolved_info
        return None

    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_project_info",
        fake_get_modrinth_project_info,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "search_mods_online",
        lambda *_args, **_kwargs: [],
    )

    resolved = mod_search_service_module.resolve_local_mod_project_info(local_mod)

    assert resolved is resolved_info
    assert attempted_identifiers[0] == "inventory-profiles-next"


@pytest.mark.smoke
def test_build_local_mod_update_plan_marks_low_confidence_lookup_as_unresolved(monkeypatch) -> None:
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

    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_current_versions_by_hashes",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_latest_versions_by_hashes",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_project_info",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "search_mods_online",
        lambda *_args, **_kwargs: [
            mod_search_service_module.OnlineModInfo(
                project_id="proj-unrelated",
                slug="totally-different-mod",
                name="Totally Different Mod",
                author="Someone",
            )
        ],
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_local_mod_file_compatibility",
        lambda *_args, **_kwargs: [],
    )

    plan = mod_search_service_module.build_local_mod_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(plan.candidates) == 1
    assert plan.metadata_summary.unresolved == 1
    assert plan.candidates[0].metadata_source == "unresolved"
    assert plan.candidates[0].metadata_resolved is False


@pytest.mark.smoke
def test_build_local_mod_update_plan_detects_updates_for_camel_case_local_mod(monkeypatch) -> None:
    local_mod = SimpleNamespace(
        platform_id="inventoryprofilesnext",
        name="InventoryProfilesNext-fabric-1.21.11-2.2.1",
        filename="InventoryProfilesNext-fabric-1.21.11-2.2.1.jar",
        version="2.2.1",
        minecraft_version="1.21.11",
        loader_type="Fabric",
    )
    captured_project_ids: list[str] = []
    resolved_info = mod_search_service_module.OnlineModInfo(
        project_id="YL57xq9U",
        slug="inventory-profiles-next",
        name="Inventory Profiles Next",
        author="Libz",
    )
    recommended_version = mod_search_service_module.OnlineModVersion(
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

    def fake_resolve_local_mod_project_info(_local_mod):
        return resolved_info

    def fake_get_recommended_mod_version(project_id: str, _minecraft_version=None, _loader=None):
        captured_project_ids.append(project_id)
        return recommended_version if project_id == "YL57xq9U" else None

    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_local_mod_project_info",
        fake_resolve_local_mod_project_info,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_recommended_mod_version",
        fake_get_recommended_mod_version,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"yl57xq9u": "Inventory Profiles Next"},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_local_mod_file_compatibility",
        lambda _local_mod, _minecraft_version=None, _loader=None: [],
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_mod_version_compatibility",
        lambda *_args, **_kwargs: mod_search_service_module.OnlineModCompatibilityReport(),
    )

    update_plan = mod_search_service_module.build_local_mod_update_plan(
        [local_mod],
        minecraft_version="1.21.11",
        loader="fabric",
    )

    assert captured_project_ids == ["YL57xq9U"]
    assert len(update_plan.candidates) == 1
    assert update_plan.candidates[0].project_name == "Inventory Profiles Next"
    assert update_plan.candidates[0].update_available is True
    assert update_plan.candidates[0].target_version_name == "2.2.2"


@pytest.mark.smoke
def test_search_mods_online_normalizes_filename_like_query(monkeypatch) -> None:
    captured_params: dict[str, object] = {}

    def fake_get_json(**kwargs):
        captured_params.update(kwargs.get("params", {}))
        return {"hits": []}

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "get_json", fake_get_json)

    mod_search_service_module.search_mods_online("letsdo-API-forge-1.2.15-forge", loader="forge")

    assert captured_params["query"] == "letsdo API"


@pytest.mark.smoke
def test_build_required_dependency_install_plan_collects_recursive_dependencies(monkeypatch) -> None:
    root_version = mod_search_service_module.OnlineModVersion(
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
                mod_search_service_module.OnlineModVersion(
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
                mod_search_service_module.OnlineModVersion(
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

    monkeypatch.setattr(mod_search_service_module, "get_mod_versions", fake_get_mod_versions)
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"cloth-config": "Cloth Config", "fabric-api": "Fabric API"},
    )

    plan = mod_search_service_module.build_required_dependency_install_plan(
        root_version,
        minecraft_version="1.21",
        loader="fabric",
        installed_mods=[],
        root_project_id="root-mod",
        root_project_name="Root Mod",
    )

    assert plan.has_unresolved_required is False
    assert [item.project_name for item in plan.items] == ["Cloth Config", "Fabric API"]


@pytest.mark.smoke
def test_build_required_dependency_install_plan_allows_prism_like_recursion_depth(monkeypatch) -> None:
    chain_length = 10
    dependency_ids = [f"dep-{index}" for index in range(chain_length)]
    root_version = mod_search_service_module.OnlineModVersion(
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
            mod_search_service_module.OnlineModVersion(
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

    monkeypatch.setattr(mod_search_service_module, "get_mod_versions", fake_get_mod_versions)
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda project_ids: {str(project_id).lower(): str(project_id).title() for project_id in project_ids},
    )

    plan = mod_search_service_module.build_required_dependency_install_plan(
        root_version,
        minecraft_version="1.21",
        loader="fabric",
        installed_mods=[],
        root_project_id="root-mod",
        root_project_name="Root Mod",
    )

    assert plan.has_unresolved_required is False
    assert len(plan.items) == chain_length


@pytest.mark.smoke
def test_build_required_dependency_install_plan_preserves_dependency_project_id_case_for_api(monkeypatch) -> None:
    root_version = mod_search_service_module.OnlineModVersion(
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

    monkeypatch.setattr(mod_search_service_module, "get_mod_versions", fake_get_mod_versions)
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        fake_resolve_modrinth_project_names,
    )

    plan = mod_search_service_module.build_required_dependency_install_plan(
        root_version,
        minecraft_version="1.21",
        loader="fabric",
        installed_mods=[],
        root_project_id="clumps",
        root_project_name="Clumps",
    )

    assert plan.has_unresolved_required is True
    assert captured_project_ids == ["P7dR8mSH", "P7dR8mSH"]


@pytest.mark.smoke
def test_build_required_dependency_install_plan_overrides_quilt_dependency_to_fabric_for_fabric_loader(
    monkeypatch,
) -> None:
    root_version = mod_search_service_module.OnlineModVersion(
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
            mod_search_service_module.OnlineModVersion(
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

    monkeypatch.setattr(mod_search_service_module, "get_mod_versions", fake_get_mod_versions)
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"p7dr8msh": "Fabric API", "qvifycyj": "QSL"},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "_fetch_modrinth_project_name",
        lambda project_id: "Fabric API" if project_id == "P7dR8mSH" else "QSL",
    )

    plan = mod_search_service_module.build_required_dependency_install_plan(
        root_version,
        minecraft_version="1.21",
        loader="fabric",
        installed_mods=[],
        root_project_id="root-mod",
        root_project_name="Root Mod",
    )

    assert captured_project_ids == ["P7dR8mSH"]
    assert len(plan.items) == 1
    assert plan.items[0].project_id == "P7dR8mSH"
    assert plan.items[0].project_name == "Fabric API"


@pytest.mark.smoke
def test_build_required_dependency_install_plan_does_not_apply_quilt_override_for_forge_loader(
    monkeypatch,
) -> None:
    root_version = mod_search_service_module.OnlineModVersion(
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
            mod_search_service_module.OnlineModVersion(
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

    monkeypatch.setattr(mod_search_service_module, "get_mod_versions", fake_get_mod_versions)
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"qvifycyj": "QSL"},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "_fetch_modrinth_project_name",
        lambda project_id: "QSL" if project_id == "qvIfYCYJ" else None,
    )

    plan = mod_search_service_module.build_required_dependency_install_plan(
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


@pytest.mark.smoke
def test_build_local_mod_update_plan_reports_updates_and_dependency_issues(monkeypatch) -> None:
    local_mod = SimpleNamespace(
        platform_id="proj123",
        name="Example Mod",
        filename="example-mod.jar",
        version="1.0.0",
        minecraft_version="1.21",
        loader_type="Fabric",
    )
    recommended_version = mod_search_service_module.OnlineModVersion(
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
    resolved_info = mod_search_service_module.OnlineModInfo(
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

    def fake_analyze_mod_version_compatibility(*_args, **_kwargs):
        return mod_search_service_module.OnlineModCompatibilityReport(
            missing_required_dependencies=["Cloth Config"],
            notes=["已找到相容更新"],
        )

    monkeypatch.setattr(
        mod_search_service_module,
        "get_recommended_mod_version",
        fake_get_recommended_mod_version,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_local_mod_project_info",
        lambda _local_mod: resolved_info,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        fake_resolve_modrinth_project_names,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_mod_version_compatibility",
        fake_analyze_mod_version_compatibility,
    )

    update_plan = mod_search_service_module.build_local_mod_update_plan(
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


@pytest.mark.smoke
def test_build_local_mod_update_plan_prefers_hash_first_update_detection(tmp_path: Path, monkeypatch) -> None:
    file_path = tmp_path / "mods" / "example-mod.jar"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"old-mod")
    current_hash = mod_search_service_module._compute_file_hash(str(file_path))

    current_version = mod_search_service_module.OnlineModVersion(
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
    latest_version = mod_search_service_module.OnlineModVersion(
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

    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_current_versions_by_hashes",
        lambda _hashes, _algorithm="sha512": {
            current_hash: mod_search_service_module.ModrinthVersionLookupResult(
                file_hash=current_hash,
                algorithm="sha512",
                project_id="proj123",
                version=current_version,
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
            current_hash: mod_search_service_module.ModrinthVersionLookupResult(
                file_hash=current_hash,
                algorithm="sha512",
                project_id="proj123",
                version=latest_version,
            )
        }

    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_latest_versions_by_hashes",
        fake_get_modrinth_latest_versions_by_hashes,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_recommended_mod_version",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("fallback path should not be used")),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"proj123": "Example Mod"},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_local_mod_file_compatibility",
        lambda _local_mod, _minecraft_version=None, _loader=None: [],
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_mod_version_compatibility",
        lambda *_args, **_kwargs: mod_search_service_module.OnlineModCompatibilityReport(),
    )

    update_plan = mod_search_service_module.build_local_mod_update_plan(
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


@pytest.mark.smoke
def test_build_local_mod_update_plan_prefers_cached_local_hash(monkeypatch) -> None:
    cached_hash = "abc123cached"
    latest_version = mod_search_service_module.OnlineModVersion(
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

    monkeypatch.setattr(
        mod_search_service_module,
        "_compute_file_hash",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should use cached hash first")),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_current_versions_by_hashes",
        lambda _hashes, _algorithm="sha512": {},
    )

    def fake_get_modrinth_latest_versions_by_hashes(
        _hashes,
        _algorithm="sha512",
        minecraft_version=None,
        loader=None,
    ):
        del minecraft_version, loader
        return {
            cached_hash: mod_search_service_module.ModrinthVersionLookupResult(
                file_hash=cached_hash,
                algorithm="sha512",
                project_id="proj123",
                version=latest_version,
            )
        }

    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_latest_versions_by_hashes",
        fake_get_modrinth_latest_versions_by_hashes,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"proj123": "Example Mod"},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_local_mod_file_compatibility",
        lambda _local_mod, _minecraft_version=None, _loader=None: [],
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_mod_version_compatibility",
        lambda *_args, **_kwargs: mod_search_service_module.OnlineModCompatibilityReport(),
    )

    update_plan = mod_search_service_module.build_local_mod_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(update_plan.candidates) == 1
    candidate = update_plan.candidates[0]
    assert candidate.current_hash == cached_hash
    assert candidate.project_id == "proj123"
    assert candidate.target_version_name == "2.0.0"


@pytest.mark.smoke
def test_build_local_mod_update_plan_collects_metadata_summary(monkeypatch) -> None:
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

    resolved_cached = mod_search_service_module.OnlineModInfo(
        project_id="YL57xq9U",
        slug="inventory-profiles-next",
        name="Inventory Profiles Next",
        author="Libz",
    )
    resolved_lookup = mod_search_service_module.OnlineModInfo(
        project_id="AANobbMI",
        slug="sodium",
        name="Sodium",
        author="jellysquid3",
    )

    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_current_versions_by_hashes",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_latest_versions_by_hashes",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_local_mod_project_info",
        lambda local_mod: (
            resolved_cached
            if getattr(local_mod, "name", "") == "Inventory Profiles Next"
            else resolved_lookup
            if getattr(local_mod, "name", "") == "Sodium"
            else None
        ),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"yl57xq9u": "Inventory Profiles Next", "aanobbmi": "Sodium"},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_local_mod_file_compatibility",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_recommended_mod_version",
        lambda *_args, **_kwargs: None,
    )

    plan = mod_search_service_module.build_local_mod_update_plan(
        [local_mod_cached, local_mod_lookup, local_mod_unresolved],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert plan.metadata_summary.total_scanned == 3
    assert plan.metadata_summary.resolved_by_cached_project == 1
    assert plan.metadata_summary.resolved_by_lookup == 1
    assert plan.metadata_summary.unresolved == 1
    assert any("metadata ensure 結果" in note for note in plan.metadata_summary.notes)


@pytest.mark.smoke
def test_build_local_mod_update_plan_creates_blocked_candidate_for_unresolved_metadata(monkeypatch) -> None:
    local_mod = SimpleNamespace(
        platform_id="",
        name="Unknown Mod",
        filename="unknown-mod.jar",
        version="1.0.0",
        minecraft_version="1.21.1",
        loader_type="Fabric",
        file_path="C:/mods/unknown-mod.jar",
    )

    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_current_versions_by_hashes",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_latest_versions_by_hashes",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_local_mod_project_info",
        lambda _local_mod: None,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_local_mod_file_compatibility",
        lambda *_args, **_kwargs: [],
    )

    plan = mod_search_service_module.build_local_mod_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.metadata_resolved is False
    assert candidate.metadata_source == "unresolved"
    assert candidate.project_id.startswith("__unresolved__::")
    assert candidate.hard_errors == ["無法建立可用的 Modrinth metadata，暫時無法自動檢查更新。"]


@pytest.mark.smoke
def test_install_remote_mod_file_downloads_into_mods_dir(tmp_path: Path, monkeypatch) -> None:
    manager = mod_manager_module.ModManager(str(tmp_path))

    def fake_download_file(url, local_path, progress_callback=None, **_kwargs):
        assert url == "https://example.invalid/example.jar"
        path = Path(local_path)
        path.write_bytes(b"jar-bytes")
        if progress_callback:
            progress_callback(10, 10)
        return True

    monkeypatch.setattr(mod_manager_module.HTTPUtils, "download_file", fake_download_file)

    installed_path = manager.install_remote_mod_file(
        "https://example.invalid/example.jar",
        "example.jar",
    )

    assert installed_path == tmp_path / "mods" / "example.jar"
    assert installed_path.exists()
    assert installed_path.read_bytes() == b"jar-bytes"


@pytest.mark.smoke
def test_replace_local_mod_file_removes_old_jar_after_update(tmp_path: Path) -> None:
    manager = mod_manager_module.ModManager(str(tmp_path))
    old_path = tmp_path / "mods" / "example-old.jar"
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_bytes(b"old-bytes")
    new_path = tmp_path / "mods" / "example-new.jar"

    local_mod = mod_manager_module.LocalModInfo(
        id="example-old",
        name="Example Mod",
        filename="example-old.jar",
        version="1.0.0",
        minecraft_version="1.21",
        loader_type="Fabric",
        status=mod_manager_module.ModStatus.ENABLED,
        file_path=str(old_path),
    )

    def fake_install_remote_mod_file(download_url, filename, progress_callback=None):
        assert download_url == "https://example.invalid/example-new.jar"
        assert filename == "example-new.jar"
        new_path.write_bytes(b"new-bytes")
        if progress_callback:
            progress_callback(10, 10)
        return new_path

    manager.install_remote_mod_file = fake_install_remote_mod_file  # type: ignore[method-assign]

    replaced_path = manager.replace_local_mod_file(
        local_mod,
        "https://example.invalid/example-new.jar",
        "example-new.jar",
    )

    assert replaced_path == new_path
    assert new_path.exists()
    assert old_path.exists() is False


@pytest.mark.smoke
def test_build_local_mod_update_plan_reports_hash_progress(tmp_path: Path, monkeypatch) -> None:
    file_path = tmp_path / "mods" / "uncached.jar"
    file_path.parent.mkdir(parents=True, exist_ok=True)
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

    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_current_versions_by_hashes",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_latest_versions_by_hashes",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_local_mod_project_info",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_local_mod_file_compatibility",
        lambda *_args, **_kwargs: [],
    )

    progress_events: list[tuple[int, int]] = []
    plan = mod_search_service_module.build_local_mod_update_plan(
        [local_mod_cached, local_mod_uncached],
        minecraft_version="1.21.1",
        loader="fabric",
        hash_progress_callback=lambda done, total: progress_events.append((done, total)),
    )

    assert len(plan.candidates) == 2
    assert progress_events
    assert progress_events[-1] == (2, 2)
    assert all(total == 2 for _, total in progress_events)


@pytest.mark.smoke
def test_analyze_local_mod_file_compatibility_does_not_flag_lossy_mc_version_metadata() -> None:
    local_mod = SimpleNamespace(
        name="Example Mod",
        filename="example.jar",
        version="1.0.0",
        minecraft_version="1.20",
        loader_type="Fabric",
    )

    issues = mod_search_service_module.analyze_local_mod_file_compatibility(
        local_mod,
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert issues == []


@pytest.mark.smoke
def test_analyze_local_mod_file_compatibility_accepts_fabric_mod_on_quilt_server() -> None:
    local_mod = SimpleNamespace(
        name="Fabric API",
        filename="fabric-api.jar",
        version="1.0.0",
        minecraft_version="1.21.1",
        loader_type="Fabric",
    )

    issues = mod_search_service_module.analyze_local_mod_file_compatibility(
        local_mod,
        minecraft_version="1.21.1",
        loader="quilt",
    )

    assert issues == []
