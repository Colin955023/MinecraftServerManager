from __future__ import annotations

from src.utils import (
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
