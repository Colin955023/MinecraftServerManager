from __future__ import annotations

from types import SimpleNamespace

from src.utils import (
    MODRINTH_PREFERRED_HASH_ALGORITHM,
    extract_primary_file_hash,
    is_allowed_version_type,
    normalize_hash_algorithm,
    select_best_mod_version,
    select_primary_file,
    version_type_priority,
)


def test_normalize_hash_algorithm_falls_back_to_sha512() -> None:
    assert normalize_hash_algorithm(None) == MODRINTH_PREFERRED_HASH_ALGORITHM
    assert normalize_hash_algorithm("SHA1") == "sha1"
    assert normalize_hash_algorithm("md5") == MODRINTH_PREFERRED_HASH_ALGORITHM


def test_select_primary_file_prefers_primary_jar_then_first_dict() -> None:
    primary = {"filename": "beta.jar", "primary": True}
    jar = {"filename": "alpha.jar"}
    fallback = {"filename": "notes.txt"}

    assert select_primary_file([fallback, jar, primary]) == primary
    assert select_primary_file([fallback, jar]) == jar
    assert select_primary_file([fallback]) == fallback


def test_extract_primary_file_hash_uses_selected_algorithm() -> None:
    version = SimpleNamespace(primary_file={"hashes": {"sha512": " ABC123 ", "sha1": " DEF456 "}})

    assert extract_primary_file_hash(version) == "abc123"
    assert extract_primary_file_hash(version, "sha1") == "def456"
    assert extract_primary_file_hash(SimpleNamespace(primary_file={"hashes": "bad"})) == ""


def test_version_type_priority_and_allow_rules() -> None:
    assert version_type_priority("release") > version_type_priority("beta")
    assert version_type_priority("beta") > version_type_priority("alpha")
    assert is_allowed_version_type("release") is True
    assert is_allowed_version_type("stable") is True
    assert is_allowed_version_type("beta") is True
    assert is_allowed_version_type("rc1") is False
    assert is_allowed_version_type("snapshot") is False


def test_select_best_mod_version_prefers_primary_release_candidate() -> None:
    release_primary = SimpleNamespace(
        primary_file={"filename": "release.jar"},
        version_type="release",
        date_published="2024-01-01T00:00:00Z",
        version_number="1.0.0",
    )
    beta_primary = SimpleNamespace(
        primary_file={"filename": "beta.jar"},
        version_type="beta",
        date_published="2024-02-01T00:00:00Z",
        version_number="2.0.0",
    )
    release_no_primary = SimpleNamespace(
        primary_file=None,
        version_type="release",
        date_published="2024-03-01T00:00:00Z",
        version_number="2.1.0",
    )

    assert select_best_mod_version([beta_primary, release_no_primary, release_primary]) is release_primary
    assert select_best_mod_version([]) is None
