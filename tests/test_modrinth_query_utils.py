from __future__ import annotations

import src.utils.modrinth_query_utils as query_utils


def test_normalize_identifier_and_loader_aliases() -> None:
    assert query_utils.normalize_identifier("  Fabric  ") == "fabric"
    assert query_utils.clean_api_identifier("  qvIfYCYJ  ") == "qvIfYCYJ"
    assert query_utils.normalize_local_loader("原版") == "vanilla"
    assert query_utils.is_supported_modrinth_update_loader("forge") is True
    assert query_utils.is_supported_modrinth_update_loader("bukkit") is False
    assert query_utils.expand_target_loader_aliases("quilt", "1.20.1") == {"fabric", "quilt"}
    assert query_utils.get_modrinth_loader_filters("quilt", "1.20.1") == ["quilt", "fabric"]
    assert query_utils.get_modrinth_loader_filters("neoforge", "1.20.1") == ["neoforge", "forge"]


def test_loader_specific_dependency_override_only_applies_to_fabric() -> None:
    assert query_utils.apply_loader_specific_dependency_override("qvIfYCYJ", "fabric") == "P7dR8mSH"
    assert query_utils.apply_loader_specific_dependency_override("qvIfYCYJ", "forge") == "qvIfYCYJ"
    assert query_utils.apply_loader_specific_dependency_override("other", "fabric") == "other"


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
