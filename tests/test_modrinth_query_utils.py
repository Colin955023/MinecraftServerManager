from __future__ import annotations

import src.utils.mod_utils.modrinth_query_utils as query_utils


def test_normalize_identifier_and_loader() -> None:
    assert query_utils.normalize_identifier("  Fabric  ") == "fabric"
    assert query_utils.clean_api_identifier("  qvIfYCYJ  ") == "qvIfYCYJ"
    assert query_utils.normalize_local_loader("原版") == "vanilla"
    assert query_utils.normalize_local_loader("quilt") == "quilt"
    assert query_utils.normalize_local_loader("neoforge") == "neoforge"
    assert query_utils.is_supported_modrinth_update_loader("forge") is True
    assert query_utils.is_supported_modrinth_update_loader("quilt") is True
    assert query_utils.is_supported_modrinth_update_loader("neoforge") is True
    assert query_utils.is_supported_modrinth_update_loader("bukkit") is False


def test_get_modrinth_loader_filters() -> None:
    # 現在每個載入器都是獨立的，不再進行別名擴展
    assert query_utils.get_modrinth_loader_filters("quilt") == ["quilt"]
    assert query_utils.get_modrinth_loader_filters("neoforge") == ["neoforge"]
    assert query_utils.get_modrinth_loader_filters("fabric") == ["fabric"]
    assert query_utils.get_modrinth_loader_filters("forge") == ["forge"]


def test_loader_specific_dependency_override_no_longer_applied() -> None:
    # 移除了別名依賴重定向，所有 project id 都直接回傳
    assert query_utils.apply_loader_specific_dependency_override("qvIfYCYJ") == "qvIfYCYJ"
    assert query_utils.apply_loader_specific_dependency_override("other") == "other"


def test_build_local_mod_lookup_candidates_collects_search_and_keys() -> None:
    exact_identifiers, search_terms, candidate_keys = query_utils.build_local_mod_lookup_candidates(
        "CoolMod-1.20.1.jar",
        platform_id="  P7dR8mSH  ",
        platform_slug="cool-mod",
        local_name="Cool Mod",
    )

    assert exact_identifiers[0] == "P7dR8mSH"
    assert "p7d-r8m-sh" in exact_identifiers
    assert "cool-mod" in exact_identifiers
    assert "Cool Mod" in exact_identifiers
    assert "CoolMod-1.20.1" in exact_identifiers
    assert any(term.lower() == "cool mod" for term in search_terms)
    assert query_utils.canonical_lookup_key("P7dR8mSH") in candidate_keys
    assert query_utils.canonical_lookup_key("cool-mod") in candidate_keys
    assert query_utils.canonical_lookup_key("Cool Mod") in candidate_keys
    assert query_utils.canonical_lookup_key("CoolMod-1.20.1") in candidate_keys
    assert candidate_keys == {
        query_utils.canonical_lookup_key("P7dR8mSH"),
        query_utils.canonical_lookup_key("cool-mod"),
        query_utils.canonical_lookup_key("Cool Mod"),
        query_utils.canonical_lookup_key("CoolMod-1.20.1"),
    }
