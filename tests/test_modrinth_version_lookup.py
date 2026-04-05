from __future__ import annotations

from src.models import ModrinthVersionLookupResult, OnlineModVersion
from src.utils import parse_modrinth_version, parse_modrinth_version_lookup_response


def test_parse_modrinth_version_maps_raw_payload_to_model() -> None:
    version = parse_modrinth_version(
        {
            "id": "version-1",
            "version_number": "1.2.3",
            "name": "Example Release",
            "game_versions": ["1.20.1"],
            "loaders": ["fabric"],
            "version_type": "release",
            "date_published": "2024-01-01T00:00:00Z",
            "changelog": "Changelog",
            "files": [{"filename": "example.jar", "primary": True}],
            "dependencies": [{"project_id": "abc123"}],
        }
    )

    assert isinstance(version, OnlineModVersion)
    assert version.version_id == "version-1"
    assert version.display_name == "1.2.3"
    assert version.primary_file["filename"] == "example.jar"


def test_parse_modrinth_version_lookup_response_normalizes_hashes() -> None:
    response = {
        " ABC123 ": {
            "project_id": " qvIfYCYJ ",
            "id": "version-1",
            "version_number": "1.2.3",
            "files": [{"filename": "example.jar", "primary": True}],
        }
    }

    parsed = parse_modrinth_version_lookup_response(response, "md5")

    assert set(parsed) == {"abc123"}
    result = parsed["abc123"]
    assert isinstance(result, ModrinthVersionLookupResult)
    assert result.algorithm == "sha512"
    assert result.project_id == "qvIfYCYJ"
    assert result.version.version_id == "version-1"
    assert result.version.primary_file["filename"] == "example.jar"


def test_parse_modrinth_version_lookup_response_ignores_invalid_payloads() -> None:
    assert parse_modrinth_version_lookup_response(None, "sha512") == {}
    assert parse_modrinth_version_lookup_response({"": {}}, "sha512") == {}
