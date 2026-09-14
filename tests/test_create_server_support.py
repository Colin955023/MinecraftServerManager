from __future__ import annotations

from types import SimpleNamespace

from src.ui.core_frames.create_server_support import (
    compose_server_name,
    extract_server_name_suffix,
    version_names,
)


def test_compose_and_extract_server_name_suffix() -> None:
    name = compose_server_name("Fabric", "1.21.1", " 我的服")
    assert name == "Fabric 1.21.1 我的服"
    assert extract_server_name_suffix(name, ("1.21.1",)) == " 我的服"


def test_version_names_normalizes_loader_results() -> None:
    assert version_names([SimpleNamespace(version="0.16.0"), "0.15.0", 3]) == ["0.16.0", "0.15.0", "3"]
