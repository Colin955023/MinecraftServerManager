from __future__ import annotations

import zipfile
from types import SimpleNamespace
from typing import Any, cast

from src.core.mods.local_mod_scanner import LocalModScanner
from src.core.mods.mod_index_persistence import ModIndexPersistence
from src.utils import (
    ARCHIVE_METADATA_MAX_BYTES,
    build_installed_mod_index,
    mod_filename_stem,
)


def test_installed_mod_index_matches_normalized_dependency_names() -> None:
    dependency = SimpleNamespace(file_name="Cool-Mod-1.2.3.jar", version=None)
    installed_mods = [SimpleNamespace(filename="Cool Mod 1.2.3.jar")]

    assert build_installed_mod_index(installed_mods).maybe_installed_by_filename(dependency) is True


def test_mod_filename_stem_removes_known_mod_suffixes() -> None:
    assert mod_filename_stem("Example.jar.disabled") == "Example"
    assert mod_filename_stem("Example.jar") == "Example"


def test_installed_mod_index_deduplicates_identifiers() -> None:
    installed_mods = [
        SimpleNamespace(platform_id="P7dR8mSH", id="P7dR8mSH", name="Fabric API", filename="fabric-api.jar"),
        SimpleNamespace(platform_id="", id="other", name="Other", filename="other.jar"),
    ]

    index = build_installed_mod_index(installed_mods)

    assert index.project_ids == {"p7dr8msh"}
    assert "fabric api" in index.identifiers
    assert "fabric-api" in index.identifiers
    assert "other" in index.identifiers


def test_installed_mod_index_groups_versions_by_project_id() -> None:
    installed_mods = [
        SimpleNamespace(platform_id="P7dR8mSH", version="1.0.0"),
        SimpleNamespace(platform_id="P7dR8mSH", version="1.0.0"),
        SimpleNamespace(platform_id="qvIfYCYJ", version="0.15.0"),
        SimpleNamespace(platform_id="", version="ignored"),
    ]

    versions_by_project = build_installed_mod_index(installed_mods).versions_by_project

    assert versions_by_project == {"p7dr8msh": {"1.0.0"}, "qvifycyj": {"0.15.0"}}


def test_local_mod_scanner_extract_version_uses_clean_version() -> None:
    assert LocalModScanner.extract_version_from_filename("Connector-1.0.0-beta.46+1.20.1") == "1.0.0"


def test_local_mod_scanner_rejects_oversized_json_metadata(tmp_path) -> None:
    jar_path = tmp_path / "oversized.jar"
    with zipfile.ZipFile(jar_path, "w") as jar:
        jar.writestr("fabric.mod.json", '{"name":"Example"}')

    with zipfile.ZipFile(jar_path, "r") as jar:
        assert LocalModScanner.read_json_from_jar(jar, "fabric.mod.json", max_bytes=8) is None
        assert LocalModScanner.read_json_from_jar(jar, "fabric.mod.json", max_bytes=128) == {"name": "Example"}


def test_local_mod_scanner_rejects_oversized_manifest_metadata(tmp_path) -> None:
    jar_path = tmp_path / "oversized-manifest.jar"
    payload = b"Implementation-Version: 1.0.0\n" + b" " * ARCHIVE_METADATA_MAX_BYTES
    with zipfile.ZipFile(jar_path, "w") as jar:
        jar.writestr("META-INF/MANIFEST.MF", payload)

    scanner = LocalModScanner.__new__(LocalModScanner)
    with zipfile.ZipFile(jar_path, "r") as jar:
        assert scanner.get_manifest_version(jar) is None


class _IdentityServiceStub:
    def resolve(self, _evidence: Any) -> Any:
        return SimpleNamespace(canonical=False, project_id="", alias="")

    def load(self, _file_path: Any) -> Any:
        return SimpleNamespace(canonical=False, project_id="", alias="")

    def project(self, _mod_info: Any, _identity: Any) -> None:
        return None


def test_local_mod_scanner_preserves_jar_display_name_across_cached_rescan(tmp_path) -> None:
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()
    jar_path = mods_dir / "renamed-file-1.0.0.jar"
    with zipfile.ZipFile(jar_path, "w", compression=zipfile.ZIP_DEFLATED) as jar:
        jar.writestr(
            "fabric.mod.json",
            '{"id":"stable_mod","name":"Stable Display Name","version":"1.0.0",'
            '"description":"Stable description","authors":["Example"]}',
        )

    scanner = LocalModScanner(
        index_manager=ModIndexPersistence(str(tmp_path)),
        mods_path=mods_dir,
        server_config=None,
        provider_identity_service=cast(Any, _IdentityServiceStub()),
        quarantine_file=lambda _path, _reason: None,
    )

    first = scanner.create_mod_info_from_file(jar_path)
    second = scanner.create_mod_info_from_file(jar_path)

    assert first is not None
    assert second is not None
    assert first.name == "Stable Display Name"
    assert second.name == "Stable Display Name"
    assert second.description == "Stable description"
