from __future__ import annotations

import zipfile

import pytest
from packaging.version import Version

from src.core import ServerCRUD, ServerImportService
from src.utils import (
    detect_loader_from_text,
    is_fabric_compatible_version,
    standardize_loader_type,
)
from src.utils.update_utils.update_parsing import UpdateParsing


@pytest.mark.parametrize(
    ("version_str", "expected"),
    [
        ("v1.6.6", Version("1.6.6")),
        ("1.7.0-beta.1", Version("1.7.0b1")),
        ("  V2.0.1+build7  ", Version("2.0.1+build7")),
        ("1", Version("1")),
    ],
)
def test_parse_version_valid(version_str: str, expected: Version) -> None:
    assert UpdateParsing.parse_version(version_str) == expected


@pytest.mark.parametrize("version_str", ["", "  ", "abc", "version-x.y.z", None])
def test_parse_version_invalid(version_str: str | None) -> None:
    assert UpdateParsing.parse_version(version_str) is None


@pytest.mark.parametrize(
    ("loader_type", "loader_version", "expected"),
    [
        ("fabric", "", "fabric"),
        ("forge", "", "forge"),
        ("vanilla", "", "vanilla"),
        ("quilt", "", "quilt"),
        ("unknown", "47.2.0", "forge"),
    ],
)
def test_standardize_loader_type_supports_vanilla_fabric_and_forge(
    loader_type: str,
    loader_version: str,
    expected: str,
) -> None:
    assert standardize_loader_type(loader_type, loader_version) == expected


def test_loader_text_semantics_recognizes_supported_loaders() -> None:
    assert detect_loader_from_text("Fabric server") == "fabric"
    assert detect_loader_from_text("NeoForge server") == "neoforge"


def test_detect_loader_from_text_supports_vanilla_and_rejects_unsupported_loader_text() -> None:
    assert detect_loader_from_text("Vanilla dedicated server") == "vanilla"
    assert detect_loader_from_text("NeoForge server") == "neoforge"
    assert detect_loader_from_text("totally-random-loader-xyz 12345") == "unknown"
    assert detect_loader_from_text("Forge server") == "forge"


def test_is_fabric_compatible_version_uses_standard_version_parser() -> None:
    assert is_fabric_compatible_version("1.14") is True
    assert is_fabric_compatible_version("1.13.2") is False
    assert is_fabric_compatible_version("v1.20.1") is True


def test_import_inspection_reads_minecraft_version_from_server_jar_metadata(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    server_jar = source / "server.jar"
    with zipfile.ZipFile(server_jar, "w") as jar_file:
        jar_file.writestr("version.json", '{"id": "1.21.1", "name": "1.21.1"}')
    (source / "eula.txt").write_text("eula=true", encoding="utf-8")

    inspection = ServerImportService(ServerCRUD(str(tmp_path / "servers"))).inspect(source, "imported")

    assert inspection.server.loader_type == "vanilla"
    assert inspection.server.minecraft_version == "1.21.1"
