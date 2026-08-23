from __future__ import annotations

import src.utils.mod_utils.modrinth_query_utils as query_utils
from src.utils import (
    apply_loader_specific_dependency_override,
    clean_api_identifier,
    get_modrinth_loader_filters,
    is_supported_modrinth_update_loader,
    normalize_identifier,
    normalize_local_loader,
)


def test_normalize_identifier_and_loader() -> None:
    assert normalize_identifier("  Fabric  ") == "fabric"
    assert clean_api_identifier("  qvIfYCYJ  ") == "qvIfYCYJ"
    assert normalize_local_loader("原版") == "vanilla"
    assert normalize_local_loader("quilt") == "quilt"
    assert normalize_local_loader("neoforge") == "neoforge"
    assert is_supported_modrinth_update_loader("forge") is True
    assert is_supported_modrinth_update_loader("quilt") is True
    assert is_supported_modrinth_update_loader("neoforge") is True
    assert is_supported_modrinth_update_loader("bukkit") is False


def test_get_modrinth_loader_filters() -> None:
    assert get_modrinth_loader_filters("quilt") == ["quilt"]
    assert get_modrinth_loader_filters("neoforge") == ["neoforge"]
    assert get_modrinth_loader_filters("fabric") == ["fabric"]
    assert get_modrinth_loader_filters("forge") == ["forge"]


def test_loader_specific_dependency_override_no_longer_applied() -> None:
    assert apply_loader_specific_dependency_override("qvIfYCYJ") == "qvIfYCYJ"
    assert apply_loader_specific_dependency_override("other") == "other"


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
