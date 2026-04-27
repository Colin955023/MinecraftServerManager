from __future__ import annotations

import zipfile

import pytest
from packaging.version import Version
from src.models import ServerConfig
from src.utils import ServerDetectionVersionUtils, UpdateParsing
from src.utils.server_utils.server_detection_utils import ServerDetectionUtils


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
    assert ServerDetectionVersionUtils.standardize_loader_type(loader_type, loader_version) == expected


def test_server_detection_utils_loader_text_alias_matches_version_utils() -> None:
    assert ServerDetectionUtils.detect_loader_from_text("Fabric server") == "fabric"
    assert ServerDetectionUtils.detect_loader_from_text("NeoForge server") == "neoforge"


def test_detect_loader_from_text_supports_vanilla_and_rejects_unsupported_loader_text() -> None:
    assert ServerDetectionVersionUtils.detect_loader_from_text("Vanilla dedicated server") == "vanilla"
    assert ServerDetectionVersionUtils.detect_loader_from_text("NeoForge server") == "neoforge"
    assert ServerDetectionVersionUtils.detect_loader_from_text("totally-random-loader-xyz 12345") == "unknown"
    assert ServerDetectionVersionUtils.detect_loader_from_text("Forge server") == "forge"


def test_parse_mc_version_prefers_packaging_release_tuple() -> None:
    assert ServerDetectionVersionUtils.parse_mc_version("v1.20.1") == [1, 20, 1]
    assert ServerDetectionVersionUtils.parse_mc_version("1.20.1-fabric.2") == [1, 20, 1]


def test_is_fabric_compatible_version_uses_standard_version_parser() -> None:
    assert ServerDetectionVersionUtils.is_fabric_compatible_version("1.14") is True
    assert ServerDetectionVersionUtils.is_fabric_compatible_version("1.13.2") is False
    assert ServerDetectionVersionUtils.is_fabric_compatible_version("v1.20.1") is True


def test_detect_server_type_reads_minecraft_version_from_server_jar_metadata(tmp_path) -> None:
    server_jar = tmp_path / "server.jar"
    with zipfile.ZipFile(server_jar, "w") as jar_file:
        jar_file.writestr("version.json", '{"id": "1.21.1", "name": "1.21.1"}')
    (tmp_path / "eula.txt").write_text("eula=true", encoding="utf-8")
    config = ServerConfig(
        name="imported",
        minecraft_version="Unknown",
        loader_type="Unknown",
        loader_version="Unknown",
        memory_max_mb=2048,
        path=str(tmp_path),
    )

    ServerDetectionUtils.detect_server_type(tmp_path, config, print_result=False)

    assert config.loader_type == "vanilla"
    assert config.minecraft_version == "1.21.1"
