from __future__ import annotations

import pytest
from packaging.version import Version
from src.utils.server_detection_version_utils import ServerDetectionVersionUtils
from src.utils import UpdateParsing


@pytest.mark.smoke
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


@pytest.mark.smoke
@pytest.mark.parametrize("version_str", ["", "  ", "abc", "version-x.y.z", None])
def test_parse_version_invalid(version_str: str | None) -> None:
    assert UpdateParsing.parse_version(version_str) is None


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("loader_type", "loader_version", "expected"),
    [
        ("fabric", "", "fabric"),
        ("forge", "", "forge"),
        ("vanilla", "", "vanilla"),
        ("quilt", "", "unknown"),
        ("unknown", "47.2.0", "forge"),
    ],
)
def test_standardize_loader_type_supports_vanilla_fabric_and_forge(
    loader_type: str,
    loader_version: str,
    expected: str,
) -> None:
    assert ServerDetectionVersionUtils.standardize_loader_type(loader_type, loader_version) == expected


@pytest.mark.smoke
def test_detect_loader_from_text_supports_vanilla_and_rejects_unsupported_loader_text() -> None:
    assert ServerDetectionVersionUtils.detect_loader_from_text("Vanilla dedicated server") == "vanilla"
    assert ServerDetectionVersionUtils.detect_loader_from_text("NeoForge server") == "unknown"
    assert ServerDetectionVersionUtils.detect_loader_from_text("totally-random-loader-xyz 12345") == "unknown"
    assert ServerDetectionVersionUtils.detect_loader_from_text("Forge server") == "forge"
