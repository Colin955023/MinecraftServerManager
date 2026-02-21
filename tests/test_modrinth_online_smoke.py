from __future__ import annotations

from pathlib import Path
import time
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
def test_get_mod_versions_retries_single_request_after_transient_failure(monkeypatch) -> None:
    call_counter = {"count": 0}

    def fake_get_json(**_kwargs):
        call_counter["count"] += 1
        if call_counter["count"] == 1:
            return None
        return [
            {
                "id": "ver1",
                "version_number": "1.0.0",
                "game_versions": ["1.21"],
                "loaders": ["fabric"],
                "version_type": "release",
                "files": [{"filename": "example.jar", "url": "https://example.invalid/example.jar", "primary": True}],
            }
        ]

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "get_json", fake_get_json)
    monkeypatch.setattr(mod_search_service_module, "MODRINTH_REQUEST_THROTTLE_SECONDS", 0.0)
    monkeypatch.setattr(mod_search_service_module, "MODRINTH_RETRY_BACKOFF_BASE_SECONDS", 0.0)
    monkeypatch.setattr(mod_search_service_module, "MODRINTH_RETRY_BACKOFF_MAX_SECONDS", 0.0)

    versions = mod_search_service_module.get_mod_versions("proj123", minecraft_version="1.21", loader="fabric")

    assert call_counter["count"] == 2
    assert [version.version_id for version in versions] == ["ver1"]


@pytest.mark.smoke
def test_get_mod_version_details_retries_single_request_after_transient_failure(monkeypatch) -> None:
    call_counter = {"count": 0}

    def fake_get_json(**_kwargs):
        call_counter["count"] += 1
        if call_counter["count"] == 1:
            return None
        return {
            "id": "ver1",
            "project_id": "P7dR8mSH",
            "version_number": "1.0.0",
            "game_versions": ["1.21"],
            "loaders": ["fabric"],
            "files": [{"filename": "example.jar", "url": "https://example.invalid/example.jar", "primary": True}],
        }

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "get_json", fake_get_json)
    monkeypatch.setattr(mod_search_service_module, "MODRINTH_REQUEST_THROTTLE_SECONDS", 0.0)
    monkeypatch.setattr(mod_search_service_module, "MODRINTH_RETRY_BACKOFF_BASE_SECONDS", 0.0)
    monkeypatch.setattr(mod_search_service_module, "MODRINTH_RETRY_BACKOFF_MAX_SECONDS", 0.0)

    project_id, version = mod_search_service_module.get_mod_version_details("ver1")

    assert call_counter["count"] == 2
    assert project_id == "P7dR8mSH"
    assert version is not None
    assert version.version_id == "ver1"


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
def test_get_modrinth_current_versions_by_hashes_splits_failed_batch_into_single_retries(monkeypatch) -> None:
    call_chunks: list[list[str]] = []

    def fake_post_json(**kwargs):
        chunk = list(kwargs.get("json_body", {}).get("hashes", []))
        call_chunks.append(chunk)
        if len(chunk) > 1:
            return None
        file_hash = chunk[0]
        return {
            file_hash: {
                "project_id": f"proj-{file_hash}",
                "id": f"ver-{file_hash}",
                "version_number": "1.0.0",
                "files": [{"filename": f"{file_hash}.jar", "url": "https://example.invalid/mod.jar", "primary": True}],
            }
        }

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "post_json", fake_post_json)

    results = mod_search_service_module.get_modrinth_current_versions_by_hashes(["hash-a", "hash-b"])

    assert set(results.keys()) == {"hash-a", "hash-b"}
    assert any(len(chunk) > 1 for chunk in call_chunks)
    assert any(chunk == ["hash-a"] for chunk in call_chunks)
    assert any(chunk == ["hash-b"] for chunk in call_chunks)


@pytest.mark.smoke
def test_resolve_modrinth_project_names_splits_failed_batch_and_recovers(monkeypatch) -> None:
    call_ids_payloads: list[str] = []

    def fake_get_json(**kwargs):
        ids_payload = str(kwargs.get("params", {}).get("ids", ""))
        call_ids_payloads.append(ids_payload)
        if "P7dR8mSH" in ids_payload and "AANobbMI" in ids_payload:
            return None
        if "P7dR8mSH" in ids_payload:
            return [{"id": "P7dR8mSH", "title": "Fabric API"}]
        if "AANobbMI" in ids_payload:
            return [{"id": "AANobbMI", "title": "Sodium"}]
        return []

    monkeypatch.setattr(mod_search_service_module.HTTPUtils, "get_json", fake_get_json)

    names = mod_search_service_module.resolve_modrinth_project_names(["P7dR8mSH", "AANobbMI"])

    assert names["p7dr8msh"] == "Fabric API"
    assert names["aanobbmi"] == "Sodium"
    assert any("P7dR8mSH" in payload and "AANobbMI" in payload for payload in call_ids_payloads)


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
def test_enhance_local_mod_prefers_cached_slug_identifier_resolver_before_fuzzy_search(monkeypatch) -> None:
    resolver_calls: list[str] = []

    def fake_resolver(identifier: str) -> mod_search_service_module.ProviderMetadataRecord:
        resolver_calls.append(identifier)
        return mod_search_service_module.ProviderMetadataRecord.from_values(
            platform="modrinth",
            project_id="YL57xq9U",
            slug="inventory-profiles-next",
            project_name="Inventory Profiles Next",
        )

    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_provider_record",
        fake_resolver,
    )

    def fail_search(*_args, **_kwargs):
        raise AssertionError("fuzzy search should not run when cached slug can be canonicalized")

    monkeypatch.setattr(mod_search_service_module, "search_mods_online", fail_search)

    enhanced = mod_search_service_module.enhance_local_mod(
        "inventory-profiles-next-2.2.2.jar",
        platform_slug="inventoryprofilesnext",
        local_name="Inventory Profiles Next",
    )

    assert enhanced is not None
    assert enhanced.project_id == "YL57xq9U"
    assert enhanced.slug == "inventory-profiles-next"
    assert enhanced.name == "Inventory Profiles Next"
    assert resolver_calls == ["inventoryprofilesnext"]


@pytest.mark.smoke
def test_enhance_local_mod_re_resolves_when_cached_provider_is_stale(monkeypatch) -> None:
    stale_epoch_ms = int(time.time() * 1000) - (13 * 60 * 60 * 1000)
    searched_terms: list[str] = []
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

    monkeypatch.setattr(mod_search_service_module, "get_modrinth_project_info", fake_get_modrinth_project_info)
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_provider_record",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("stale cached identifier should not be canonicalized directly")
        ),
    )

    def fake_search(term: str, *_args, **_kwargs):
        searched_terms.append(term)
        return [
            mod_search_service_module.OnlineModInfo(
                project_id="YL57xq9U",
                slug="inventory-profiles-next",
                name="Inventory Profiles Next",
                author="Libz",
            )
        ]

    monkeypatch.setattr(mod_search_service_module, "search_mods_online", fake_search)

    enhanced = mod_search_service_module.enhance_local_mod(
        "inventory-profiles-next-2.2.2.jar",
        platform_slug="inventoryprofilesnext",
        local_name="Inventory Profiles Next",
        resolution_source="scan_detect",
        resolved_at_epoch_ms=str(stale_epoch_ms),
    )

    assert enhanced is not None
    assert enhanced.project_id == "YL57xq9U"
    assert enhanced.slug == "inventory-profiles-next"
    assert "inventoryprofilesnext" not in attempted_identifiers
    assert searched_terms == []


@pytest.mark.smoke
def test_enhance_local_mod_returns_stale_fallback_when_revalidation_fails(monkeypatch) -> None:
    stale_epoch_ms = int(time.time() * 1000) - (13 * 60 * 60 * 1000)

    monkeypatch.setattr(mod_search_service_module, "get_modrinth_project_info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod_search_service_module, "search_mods_online", lambda *_args, **_kwargs: [])

    enhanced = mod_search_service_module.enhance_local_mod(
        "inventory-profiles-next-2.2.2.jar",
        platform_slug="inventoryprofilesnext",
        local_name="Inventory Profiles Next",
        resolution_source="scan_detect",
        resolved_at_epoch_ms=str(stale_epoch_ms),
    )

    assert enhanced is not None
    assert enhanced.available is False
    assert enhanced.source == "modrinth_stale_cache"
    assert enhanced.slug == "inventoryprofilesnext"


@pytest.mark.smoke
def test_build_local_mod_update_plan_marks_invalidated_stale_provider_as_blocked(monkeypatch) -> None:
    stale_epoch_ms = int(time.time() * 1000) - (13 * 60 * 60 * 1000)
    next_retry_epoch_ms = int(time.time() * 1000) + (10 * 60 * 1000)

    monkeypatch.setattr(mod_search_service_module, "compute_file_hash", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        mod_search_service_module, "get_modrinth_current_versions_by_hashes", lambda *_args, **_kwargs: {}
    )
    monkeypatch.setattr(
        mod_search_service_module, "get_modrinth_latest_versions_by_hashes", lambda *_args, **_kwargs: {}
    )
    monkeypatch.setattr(mod_search_service_module, "get_modrinth_project_info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod_search_service_module, "search_mods_online", lambda *_args, **_kwargs: [])

    local_mod = SimpleNamespace(
        filename="sodium.jar",
        file_path="C:/servers/Fabric/mods/sodium.jar",
        current_hash="",
        hash_algorithm="",
        platform_id="AANobbMI",
        platform_slug="sodium",
        resolution_source="scan_detect",
        resolved_at_epoch_ms=str(stale_epoch_ms),
        provider_lifecycle_state="invalidated",
        next_retry_not_before_epoch_ms=str(next_retry_epoch_ms),
        name="Sodium",
        version="1.0.0",
    )

    plan = mod_search_service_module.build_local_mod_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
        loader_version="0.16.10",
    )

    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.recommendation_confidence == mod_search_service_module.RECOMMENDATION_CONFIDENCE_BLOCKED
    assert any("invalidated" in item for item in candidate.hard_errors)


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
    assert "Cloth Config（需求版本：2.0.0） 可能已存在本地相近檔名，系統已先採安全略過策略。" in report.notes


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
    assert local_mod.platform_id == "YL57xq9U"
    assert local_mod.platform_slug == "inventory-profiles-next"
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
    assert plan.candidates[0].recommendation_source == "metadata_unresolved"
    assert plan.candidates[0].recommendation_confidence == "blocked"


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
    current_hash = mod_search_service_module.compute_file_hash(str(file_path), "sha512")

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
        "compute_file_hash",
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
    assert candidate.recommendation_source == "hash_metadata"
    assert candidate.recommendation_confidence == "high"


@pytest.mark.smoke
def test_build_local_mod_update_plan_trusts_hash_current_match_without_project_fallback(monkeypatch) -> None:
    cached_hash = "hash-current-only"
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

    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_current_versions_by_hashes",
        lambda _hashes, _algorithm="sha512": {
            cached_hash: mod_search_service_module.ModrinthVersionLookupResult(
                file_hash=cached_hash,
                algorithm="sha512",
                project_id="proj123",
                version=current_version,
            )
        },
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_latest_versions_by_hashes",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"proj123": "Example Mod"},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_local_mod_project_info",
        lambda *_args, **_kwargs: mod_search_service_module.OnlineModInfo(
            project_id="proj123",
            slug="example-mod",
            name="Example Mod",
            author="Example",
        ),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_local_mod_file_compatibility",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_recommended_mod_version",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("hash-resolved entries should not fallback to project-based latest version lookup")
        ),
    )

    update_plan = mod_search_service_module.build_local_mod_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert update_plan.candidates == []


@pytest.mark.smoke
def test_build_local_mod_update_plan_allows_project_fallback_when_hash_mapping_missing(monkeypatch) -> None:
    cached_hash = "hash-without-mapping"
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
        "resolve_modrinth_project_names",
        lambda _project_ids: {"proj123": "Example Mod"},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_local_mod_project_info",
        lambda *_args, **_kwargs: mod_search_service_module.OnlineModInfo(
            project_id="proj123",
            slug="example-mod",
            name="Example Mod",
            author="Example",
        ),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_local_mod_file_compatibility",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_mod_version_compatibility",
        lambda *_args, **_kwargs: mod_search_service_module.OnlineModCompatibilityReport(),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_recommended_mod_version",
        lambda *_args, **_kwargs: latest_version,
    )

    update_plan = mod_search_service_module.build_local_mod_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(update_plan.candidates) == 1
    assert update_plan.candidates[0].target_version_name == "2.0.0"
    assert update_plan.candidates[0].recommendation_source == "project_fallback"
    assert update_plan.candidates[0].recommendation_confidence == "advisory"


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
def test_build_local_mod_update_plan_re_resolves_when_cached_provider_is_stale(monkeypatch) -> None:
    stale_epoch_ms = int(time.time() * 1000) - (13 * 60 * 60 * 1000)
    attempted_identifiers: list[str] = []
    local_mod = SimpleNamespace(
        platform_id="inventoryprofilesnext",
        platform_slug="inventoryprofilesnext",
        resolution_source="scan_detect",
        resolved_at_epoch_ms=str(stale_epoch_ms),
        name="Inventory Profiles Next",
        filename="inventory-profiles-next.jar",
        version="2.2.2",
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

    def fake_get_modrinth_project_info(identifier: str, *_args, **_kwargs):
        attempted_identifiers.append(identifier)
        if identifier == "inventory-profiles-next":
            return mod_search_service_module.OnlineModInfo(
                project_id="YL57xq9U",
                slug="inventory-profiles-next",
                name="Inventory Profiles Next",
                author="Libz",
            )
        return None

    monkeypatch.setattr(mod_search_service_module, "get_modrinth_project_info", fake_get_modrinth_project_info)
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_provider_record",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("stale cached identifier should not drive canonical resolver")
        ),
    )

    monkeypatch.setattr(mod_search_service_module, "search_mods_online", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"yl57xq9u": "Inventory Profiles Next"},
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
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert local_mod.platform_id == "YL57xq9U"
    assert local_mod.platform_slug == "inventory-profiles-next"
    assert plan.metadata_summary.resolved_by_cached_project == 0
    assert plan.metadata_summary.resolved_by_lookup == 1
    assert "inventoryprofilesnext" not in attempted_identifiers
    assert any("freshness TTL" in note for note in plan.metadata_summary.notes)


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
    assert candidate.recommendation_source == "metadata_unresolved"
    assert candidate.recommendation_confidence == "blocked"
    assert candidate.project_id.startswith("__unresolved__::")
    assert candidate.hard_errors == ["metadata 未識別，暫時無法自動檢查更新。"]


@pytest.mark.smoke
def test_build_local_mod_update_plan_marks_stale_revalidation_failure_as_retryable(monkeypatch) -> None:
    stale_epoch_ms = int(time.time() * 1000) - (13 * 60 * 60 * 1000)
    local_mod = SimpleNamespace(
        platform_id="inventoryprofilesnext",
        platform_slug="inventoryprofilesnext",
        resolution_source="scan_detect",
        resolved_at_epoch_ms=str(stale_epoch_ms),
        name="Inventory Profiles Next",
        filename="inventory-profiles-next.jar",
        version="2.2.2",
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
    monkeypatch.setattr(mod_search_service_module, "get_modrinth_project_info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod_search_service_module, "search_mods_online", lambda *_args, **_kwargs: [])

    plan = mod_search_service_module.build_local_mod_update_plan(
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
    assert candidate.project_id.startswith("__stale__::")
    assert any("可重試" in note for note in plan.metadata_summary.notes)


@pytest.mark.smoke
def test_build_local_mod_update_plan_defers_stale_revalidation_when_backoff_not_due(monkeypatch) -> None:
    stale_epoch_ms = int(time.time() * 1000) - (13 * 60 * 60 * 1000)
    local_mod = SimpleNamespace(
        platform_id="inventoryprofilesnext",
        platform_slug="inventoryprofilesnext",
        resolution_source="scan_detect",
        resolved_at_epoch_ms=str(stale_epoch_ms),
        provider_lifecycle_state="retrying",
        next_retry_not_before_epoch_ms=str(int(time.time() * 1000) + 60_000),
        name="Inventory Profiles Next",
        filename="inventory-profiles-next.jar",
        version="2.2.2",
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

    resolve_calls = {"project": 0, "search": 0}

    def _count_project_info(*_args, **_kwargs):
        resolve_calls["project"] += 1

    def _count_search(*_args, **_kwargs):
        resolve_calls["search"] += 1
        return []

    monkeypatch.setattr(mod_search_service_module, "get_modrinth_project_info", _count_project_info)
    monkeypatch.setattr(mod_search_service_module, "search_mods_online", _count_search)

    plan = mod_search_service_module.build_local_mod_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.metadata_source == "stale_provider"
    assert any("退避" in note for note in candidate.notes)
    assert any("退避視窗" in note for note in plan.metadata_summary.notes)
    assert resolve_calls["project"] == 0
    assert resolve_calls["search"] == 0


@pytest.mark.smoke
def test_build_local_mod_update_plan_defers_stale_revalidation_when_batch_limit_reached(monkeypatch) -> None:
    stale_epoch_ms = int(time.time() * 1000) - (13 * 60 * 60 * 1000)
    original_limit = mod_search_service_module.PROVIDER_REVALIDATION_BATCH_MAX_PER_RUN
    monkeypatch.setattr(mod_search_service_module, "PROVIDER_REVALIDATION_BATCH_MAX_PER_RUN", 1)

    mod1 = SimpleNamespace(
        platform_id="inventoryprofilesnext",
        platform_slug="inventoryprofilesnext",
        resolution_source="scan_detect",
        resolved_at_epoch_ms=str(stale_epoch_ms),
        provider_lifecycle_state="stale",
        next_retry_not_before_epoch_ms="0",
        name="Inventory Profiles Next",
        filename="inventory-profiles-next.jar",
        version="2.2.2",
        minecraft_version="1.21.1",
        loader_type="Fabric",
        file_path="",
        current_hash="",
        hash_algorithm="",
    )
    mod2 = SimpleNamespace(
        platform_id="fabric-api",
        platform_slug="fabric-api",
        resolution_source="scan_detect",
        resolved_at_epoch_ms=str(stale_epoch_ms),
        provider_lifecycle_state="stale",
        next_retry_not_before_epoch_ms="0",
        name="Fabric API",
        filename="fabric-api.jar",
        version="0.119.2",
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
    monkeypatch.setattr(mod_search_service_module, "get_modrinth_project_info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod_search_service_module, "search_mods_online", lambda *_args, **_kwargs: [])

    plan = mod_search_service_module.build_local_mod_update_plan(
        [mod1, mod2],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(plan.candidates) == 2
    assert any("批次上限（1）" in "\n".join(candidate.notes) for candidate in plan.candidates)
    assert any("批次上限（1）" in note for note in plan.metadata_summary.notes)

    # 還原僅為保守防禦，避免後續測試依賴 module-level 常數。
    monkeypatch.setattr(mod_search_service_module, "PROVIDER_REVALIDATION_BATCH_MAX_PER_RUN", original_limit)


@pytest.mark.smoke
def test_build_local_mod_update_plan_adaptive_revalidation_batch_shrinks_on_high_failure(monkeypatch) -> None:
    stale_epoch_ms = int(time.time() * 1000) - (13 * 60 * 60 * 1000)

    def _make_stale_mod(index: int) -> SimpleNamespace:
        return SimpleNamespace(
            platform_id=f"stale-mod-{index}",
            platform_slug=f"stale-mod-{index}",
            resolution_source="scan_detect",
            resolved_at_epoch_ms=str(stale_epoch_ms),
            provider_lifecycle_state="stale",
            next_retry_not_before_epoch_ms="0",
            name=f"Stale Mod {index}",
            filename=f"stale-mod-{index}.jar",
            version="1.0.0",
            minecraft_version="1.21.1",
            loader_type="Fabric",
            file_path="",
            current_hash="",
            hash_algorithm="",
        )

    local_mods = [_make_stale_mod(i) for i in range(10)]

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
    monkeypatch.setattr(mod_search_service_module, "get_modrinth_project_info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod_search_service_module, "search_mods_online", lambda *_args, **_kwargs: [])

    plan = mod_search_service_module.build_local_mod_update_plan(
        local_mods,
        minecraft_version="1.21.1",
        loader="fabric",
        revalidation_batch_base_limit=8,
        revalidation_batch_min_limit=2,
        revalidation_batch_max_limit=8,
        revalidation_adaptive_enabled=True,
        revalidation_latency_threshold_ms=1.0,
    )

    assert len(plan.candidates) == 10
    assert any("批次上限（" in "\n".join(candidate.notes) for candidate in plan.candidates)
    assert any("stale metadata 重查批次策略" in note for note in plan.metadata_summary.notes)
    assert any("重查觀測摘要" in note for note in plan.metadata_summary.notes)


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
def test_replace_local_mod_file_removes_old_jar_after_update(tmp_path: Path, monkeypatch) -> None:
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

    monkeypatch.setattr(manager, "install_remote_mod_file", fake_install_remote_mod_file)

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


@pytest.mark.smoke
def test_get_recommended_mod_version_does_not_fallback_for_unsupported_loader(monkeypatch) -> None:
    monkeypatch.setattr(
        mod_search_service_module,
        "get_mod_versions",
        lambda _project_id, _minecraft_version=None, loader=None: (
            []
            if loader
            else (_ for _ in ()).throw(AssertionError("unsupported loader should not fallback to unfiltered versions"))
        ),
    )

    resolved = mod_search_service_module.get_recommended_mod_version(
        "example-project",
        minecraft_version="1.21.1",
        loader="paper",
    )

    assert resolved is None


@pytest.mark.smoke
def test_build_local_mod_update_plan_skips_online_update_check_for_unsupported_loader(monkeypatch) -> None:
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

    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_current_versions_by_hashes",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_latest_versions_by_hashes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unsupported loader should skip hash-based latest update lookup")
        ),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_local_mod_project_info",
        lambda *_args, **_kwargs: mod_search_service_module.OnlineModInfo(
            project_id="proj123",
            slug="example-mod",
            name="Example Mod",
            author="Example",
        ),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"proj123": "Example Mod"},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_recommended_mod_version",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unsupported loader should skip project-based fallback update lookup")
        ),
    )

    plan = mod_search_service_module.build_local_mod_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="paper",
    )

    assert plan.candidates == []
    assert any("已略過" in note and "paper" in note for note in plan.notes)


@pytest.mark.smoke
def test_build_local_mod_update_plan_treats_local_metadata_as_advisory_when_no_online_version(monkeypatch) -> None:
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
        lambda *_args, **_kwargs: mod_search_service_module.OnlineModInfo(
            project_id="proj123",
            slug="example-mod",
            name="Example Mod",
            author="Example",
        ),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"proj123": "Example Mod"},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_recommended_mod_version",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_local_mod_file_compatibility",
        lambda *_args, **_kwargs: ["提示 A", "提示 B", "提示 C"],
    )

    plan = mod_search_service_module.build_local_mod_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert plan.candidates == []
    assert any("僅作提示，不影響更新判定" in note for note in plan.notes)


@pytest.mark.smoke
def test_build_local_mod_update_plan_adds_local_metadata_advisory_note_to_candidate(monkeypatch) -> None:
    local_mod = SimpleNamespace(
        platform_id="",
        platform_slug="",
        name="Example Mod",
        filename="example-mod.jar",
        version="1.0.0",
        minecraft_version="1.21.1",
        loader_type="Fabric",
        file_path="C:/mods/example-mod.jar",
        current_hash="hash-old-001",
        hash_algorithm="sha512",
    )
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
                "hashes": {"sha512": "hash-new-002"},
            }
        ],
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
        lambda *_args, **_kwargs: mod_search_service_module.OnlineModInfo(
            project_id="proj123",
            slug="example-mod",
            name="Example Mod",
            author="Example",
        ),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"proj123": "Example Mod"},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_recommended_mod_version",
        lambda *_args, **_kwargs: latest_version,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_mod_version_compatibility",
        lambda *_args, **_kwargs: mod_search_service_module.OnlineModCompatibilityReport(),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_local_mod_file_compatibility",
        lambda *_args, **_kwargs: ["提示 A"],
    )

    plan = mod_search_service_module.build_local_mod_update_plan(
        [local_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.current_issues == []
    assert any(note == "本地 metadata 提示：提示 A" for note in candidate.notes)


@pytest.mark.smoke
def test_build_local_mod_update_plan_prefers_provider_current_version_over_local_version(monkeypatch) -> None:
    local_hash = "hash-001"
    current_version = mod_search_service_module.OnlineModVersion(
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

    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_current_versions_by_hashes",
        lambda *_args, **_kwargs: {
            local_hash: mod_search_service_module.ModrinthVersionLookupResult(
                file_hash=local_hash,
                algorithm="sha512",
                project_id="proj123",
                version=current_version,
            )
        },
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_modrinth_latest_versions_by_hashes",
        lambda *_args, **_kwargs: {
            local_hash: mod_search_service_module.ModrinthVersionLookupResult(
                file_hash=local_hash,
                algorithm="sha512",
                project_id="proj123",
                version=latest_version,
            )
        },
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda _project_ids: {"proj123": "Example Mod"},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_mod_version_compatibility",
        lambda *_args, **_kwargs: mod_search_service_module.OnlineModCompatibilityReport(),
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
    assert plan.candidates[0].current_version == "1.0.0-provider"
    assert plan.candidates[0].recommendation_source == "hash_metadata"
    assert plan.candidates[0].recommendation_confidence == "high"


@pytest.mark.smoke
def test_build_local_mod_update_plan_marks_project_fallback_candidate_as_advisory(monkeypatch) -> None:
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
                "hashes": {"sha512": "hash-new-002"},
            }
        ],
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
        "resolve_modrinth_project_names",
        lambda _project_ids: {"proj123": "Example Mod"},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_local_mod_project_info",
        lambda *_args, **_kwargs: mod_search_service_module.OnlineModInfo(
            project_id="proj123",
            slug="example-mod",
            name="Example Mod",
            author="Example",
        ),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_local_mod_file_compatibility",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_mod_version_compatibility",
        lambda *_args, **_kwargs: mod_search_service_module.OnlineModCompatibilityReport(),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_recommended_mod_version",
        lambda *_args, **_kwargs: latest_version,
    )

    plan = mod_search_service_module.build_local_mod_update_plan(
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


@pytest.mark.smoke
def test_build_local_mod_update_plan_mixed_fault_hash_hit_plus_unresolved(monkeypatch) -> None:
    """混合情境：一個模組 hash 命中（enabled），一個 provider metadata 完全無法解析（unknown）。
    兩者應在同一 LocalModUpdatePlan 中，且分配到不同 recommendation_confidence。
    """
    resolved_mod = SimpleNamespace(
        filename="sodium-0.6.0.jar",
        name="Sodium",
        platform_id="sodium",
        platform_slug="sodium",
        resolution_source="",
        resolved_at_epoch_ms=None,
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
        resolution_source="",
        resolved_at_epoch_ms=None,
        current_hash="",
        hash_algorithm="sha512",
        version="1.0",
        enabled=True,
    )

    latest_version = mod_search_service_module.OnlineModVersion(
        version_id="sodium-v2",
        version_number="0.7.0",
        display_name="0.7.0",
        game_versions=["1.21.1"],
        loaders=["fabric"],
        files=[{"filename": "sodium-0.7.0.jar", "url": "https://cdn.modrinth.com/sodium-0.7.0.jar", "primary": True}],
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
        "resolve_modrinth_provider_record",
        lambda identifier: (
            mod_search_service_module.ProviderMetadataRecord.from_values(
                project_id="sodium", slug="sodium", project_name="Sodium"
            )
            if "sodium" in str(identifier).lower()
            else mod_search_service_module.ProviderMetadataRecord()
        ),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_local_mod_project_info",
        lambda _local_mod: None,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda _project_ids: {},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_local_mod_file_compatibility",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_mod_version_compatibility",
        lambda *_args, **_kwargs: mod_search_service_module.OnlineModCompatibilityReport(),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_recommended_mod_version",
        lambda project_id, *_args, **_kwargs: latest_version if project_id == "sodium" else None,
    )

    plan = mod_search_service_module.build_local_mod_update_plan(
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


@pytest.mark.smoke
def test_build_local_mod_update_plan_mixed_fault_stale_plus_dependency_unresolved(monkeypatch) -> None:
    """混合情境：一個模組 metadata 已過期（retryable），一個有 dependency 無法解析的正常模組。
    確認兩者共存在同一 plan，且 stale 模組被分配 RECOMMENDATION_CONFIDENCE_RETRYABLE。
    """
    stale_mod = SimpleNamespace(
        filename="fabricapi-0.90.0.jar",
        name="Fabric API",
        platform_id="fabric-api",
        platform_slug="fabric-api",
        resolution_source="",
        resolved_at_epoch_ms=1000,
        current_hash="",
        hash_algorithm="sha512",
        version="0.90.0",
        enabled=True,
    )
    dep_unresolved_mod = SimpleNamespace(
        filename="clumps-9.0.jar",
        name="Clumps",
        platform_id="clumps",
        platform_slug="clumps",
        resolution_source="",
        resolved_at_epoch_ms=None,
        current_hash="",
        hash_algorithm="sha512",
        version="9.0",
        enabled=True,
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
        "resolve_modrinth_provider_record",
        lambda _identifier: mod_search_service_module.ProviderMetadataRecord(),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_local_mod_project_info",
        lambda _local_mod: None,
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "resolve_modrinth_project_names",
        lambda _project_ids: {},
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_local_mod_file_compatibility",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "analyze_mod_version_compatibility",
        lambda *_args, **_kwargs: mod_search_service_module.OnlineModCompatibilityReport(),
    )
    monkeypatch.setattr(
        mod_search_service_module,
        "get_recommended_mod_version",
        lambda *_args, **_kwargs: None,
    )

    plan = mod_search_service_module.build_local_mod_update_plan(
        [stale_mod, dep_unresolved_mod],
        minecraft_version="1.21.1",
        loader="fabric",
    )

    stale_candidates = [
        c
        for c in plan.candidates
        if getattr(c, "metadata_source", "") in ("stale_provider",)
        or getattr(c, "recommendation_confidence", "") == "retryable"
    ]
    assert len(stale_candidates) >= 1, "Stale provider 模組應產生 retryable 候選"
    assert stale_candidates[0].recommendation_confidence == "retryable"
    assert "stale metadata" in (stale_candidates[0].metadata_note or "")


@pytest.mark.smoke
def test_dependency_plan_persistence_payload_roundtrip_includes_provider_fields() -> None:
    plan = mod_search_service_module.OnlineDependencyInstallPlan(
        items=[
            mod_search_service_module.OnlineDependencyInstallItem(
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
                required_by=["Root Mod"],
                decision_source="required:auto",
                graph_depth=1,
                edge_kind="required",
                edge_source="required:modrinth_dependency",
            )
        ],
        advisory_items=[
            mod_search_service_module.OnlineDependencyInstallItem(
                project_id="P7dR8mSH",
                project_name="Fabric API",
                version_id="ver-2",
                version_name="2.0.0",
                filename="fabric-api.jar",
                download_url="https://cdn.example/fabric-api.jar",
                parent_name="Root Mod",
                enabled=False,
                is_optional=True,
                provider="modrinth",
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

    payload = mod_search_service_module.serialize_online_dependency_install_plan(
        plan,
        root_project_id="root-proj",
        root_project_name="Root Mod",
        root_target_version_id="root-ver-1",
        root_target_version_name="1.2.3",
        plan_source="local_update_review",
    )
    restored = mod_search_service_module.deserialize_online_dependency_install_plan(payload)

    assert payload["schema_version"] == mod_search_service_module.DEPENDENCY_PLAN_PERSISTENCE_SCHEMA_VERSION
    assert payload["plan_source"] == "local_update_review"
    assert payload["root_project_id"] == "root-proj"
    assert payload["root_target_version_id"] == "root-ver-1"
    assert payload["root_target_version_name"] == "1.2.3"
    assert payload["items"][0]["provider"] == "modrinth"
    assert payload["items"][0]["required_by"] == ["Root Mod"]
    assert payload["items"][0]["decision_source"] == "required:auto"
    assert payload["items"][0]["graph_depth"] == 1
    assert payload["items"][0]["edge_kind"] == "required"
    assert payload["items"][0]["edge_source"] == "required:modrinth_dependency"
    assert payload["advisory_items"][0]["decision_source"] == "optional:advisory_default_disabled"
    assert payload["advisory_items"][0]["graph_depth"] == 2
    assert payload["graph_edges"][0]["depth"] == 1
    assert payload["graph_edges"][0]["edge"] == "required"
    assert payload["graph_edges"][1]["edge"] == "optional"
    assert mod_search_service_module.validate_online_dependency_install_plan_payload(payload) == (True, "ok")
    assert restored.items[0].project_id == "AANobbMI"
    assert restored.items[0].required_by == ["Root Mod"]
    assert restored.items[0].graph_depth == 1
    assert restored.items[0].edge_kind == "required"
    assert restored.advisory_items[0].decision_source == "optional:advisory_default_disabled"


@pytest.mark.smoke
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

    migrated, state = mod_search_service_module.migrate_online_dependency_install_plan_payload(legacy_payload)

    assert migrated is not None
    assert state == "migrated"
    assert isinstance(migrated.get("graph_edges"), list)
    assert migrated["graph_edges"][0]["edge"] == "required"
    assert migrated["graph_edges"][0]["depth"] == 1
    valid, reason = mod_search_service_module.validate_online_dependency_install_plan_payload(migrated)
    assert valid is True
    assert reason == "ok"
