from __future__ import annotations

from types import SimpleNamespace

from src.utils import (
    collect_installed_mod_identifiers,
    collect_installed_mod_versions,
    dependency_candidate_filenames,
    dependency_maybe_installed_by_filename,
    normalize_filename_stem,
    normalize_lax_filename,
)


def test_normalize_filename_helpers_handle_jar_variants() -> None:
    assert normalize_filename_stem("CoolMod.jar") == "coolmod"
    assert normalize_filename_stem("CoolMod.jar.disabled") == "coolmod"
    assert normalize_lax_filename("Cool-Mod 1.2.3.jar", exclude_digits=True) == "cool mod"
    assert normalize_lax_filename("Cool-Mod 1.2.3.jar") == "cool mod 1 2 3"


def test_dependency_candidate_filenames_uses_dependency_file_name_and_primary_file() -> None:
    dependency = SimpleNamespace(
        file_name="coolmod.jar",
        version=SimpleNamespace(primary_file={"filename": "coolmod-1.2.3.jar"}),
    )

    assert dependency_candidate_filenames(dependency) == ["coolmod.jar", "coolmod-1.2.3.jar"]


def test_dependency_maybe_installed_by_filename_matches_normalized_names() -> None:
    dependency = SimpleNamespace(file_name="Cool-Mod-1.2.3.jar", version=None)
    installed_mods = [SimpleNamespace(filename="Cool Mod 1.2.3.jar")]

    assert dependency_maybe_installed_by_filename(dependency, installed_mods) is True


def test_collect_installed_mod_identifiers_deduplicates_sources() -> None:
    installed_mods = [
        SimpleNamespace(platform_id="P7dR8mSH", id="P7dR8mSH", name="Fabric API", filename="fabric-api.jar"),
        SimpleNamespace(platform_id="", id="other", name="Other", filename="other.jar"),
    ]

    project_ids, identifiers = collect_installed_mod_identifiers(installed_mods)

    assert project_ids == {"p7dr8msh"}
    assert "fabric api" in identifiers
    assert "fabric-api" in identifiers
    assert "other" in identifiers


def test_collect_installed_mod_versions_groups_by_project_id() -> None:
    installed_mods = [
        SimpleNamespace(platform_id="P7dR8mSH", version="1.0.0"),
        SimpleNamespace(platform_id="P7dR8mSH", version="1.0.0"),
        SimpleNamespace(platform_id="qvIfYCYJ", version="0.15.0"),
        SimpleNamespace(platform_id="", version="ignored"),
    ]

    versions_by_project = collect_installed_mod_versions(installed_mods)

    assert versions_by_project == {"p7dr8msh": {"1.0.0"}, "qvifycyj": {"0.15.0"}}
