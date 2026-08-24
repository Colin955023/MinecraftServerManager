from __future__ import annotations

from pathlib import Path

import pytest

from src.core import LoaderManager
from src.utils import PathUtils


def test_clear_cache_file_removes_cache_files_and_memory_cache(tmp_path: Path) -> None:
    manager = LoaderManager.__new__(LoaderManager)
    manager._initialized = False
    manager.__init__()
    manager.cache_dir = tmp_path

    fabric_cache = tmp_path / manager.LOADER_SPECS["fabric"].cache_name
    forge_cache = tmp_path / manager.LOADER_SPECS["forge"].cache_name
    fabric_cache.write_text("[]", encoding="utf-8")
    forge_cache.write_text("{}", encoding="utf-8")

    manager._version_cache = {"fabric_1.21": [object()]}

    manager.clear_cache_file()

    assert fabric_cache.exists() is False
    assert forge_cache.exists() is False
    assert manager._version_cache == {}


def _build_manager_for_preload_tests(tmp_path: Path, *, calls: list[str]) -> LoaderManager:
    manager = LoaderManager.__new__(LoaderManager)
    manager._initialized = False
    manager.__init__()
    manager.cache_dir = tmp_path

    def mock_preload(spec):
        calls.append(spec.id)

    manager._preload_loader = mock_preload
    return manager


def test_preload_loader_versions_reloads_when_cache_missing(tmp_path: Path) -> None:
    calls: list[str] = []
    manager = _build_manager_for_preload_tests(tmp_path, calls=calls)

    manager.preload_loader_versions()

    assert set(calls) == {"fabric", "forge", "quilt", "neoforge", "vanilla"}


def test_preload_loader_versions_skips_network_when_cache_fresh(
    tmp_path: Path,
) -> None:
    manager = LoaderManager.__new__(LoaderManager)
    manager._initialized = False
    manager.__init__()
    manager.cache_dir = tmp_path

    fabric_cache = tmp_path / manager.LOADER_SPECS["fabric"].cache_name
    forge_cache = tmp_path / manager.LOADER_SPECS["forge"].cache_name
    quilt_cache = tmp_path / manager.LOADER_SPECS["quilt"].cache_name
    neoforge_cache = tmp_path / manager.LOADER_SPECS["neoforge"].cache_name
    vanilla_cache = tmp_path / manager.LOADER_SPECS["vanilla"].cache_name
    fabric_cache.write_text("[]", encoding="utf-8")
    forge_cache.write_text("{}", encoding="utf-8")
    quilt_cache.write_text("[]", encoding="utf-8")
    neoforge_cache.write_text("{}", encoding="utf-8")
    vanilla_cache.write_text("[]", encoding="utf-8")

    calls: list[str] = []
    manager = _build_manager_for_preload_tests(tmp_path, calls=calls)

    manager.preload_loader_versions()

    assert calls == []


def test_preload_forge_versions_uses_numeric_sort_for_versions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = LoaderManager.__new__(LoaderManager)
    manager._initialized = False
    manager.__init__()
    manager.cache_dir = tmp_path

    forge_cache = tmp_path / manager.LOADER_SPECS["forge"].cache_name

    xml_content = b"""<?xml version="1.0" encoding="UTF-8"?>
<metadata>
    <versioning>
        <versions>
            <version>1.21.1-54.0.9</version>
            <version>1.21.1-54.0.10</version>
            <version>1.21.1-54.0.2</version>
        </versions>
    </versioning>
</metadata>
"""

    monkeypatch.setattr(
        "src.utils.network_utils.http_client.HTTPClient.fetch_bytes", lambda *_args, **_kwargs: xml_content
    )

    spec = manager.LOADER_SPECS["forge"]
    manager._preload_loader(spec)

    cache = PathUtils.load_json(forge_cache)
    assert isinstance(cache, dict)
    assert cache.get("1.21.1", [])[:3] == ["1.21.1-54.0.10", "1.21.1-54.0.9", "1.21.1-54.0.2"]


def _build_manager(tmp_path: Path) -> LoaderManager:
    manager = LoaderManager.__new__(LoaderManager)
    manager._initialized = False
    manager.__init__()
    manager.cache_dir = tmp_path
    return manager


def test_neoforge_metadata_preserves_full_loader_version(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)
    fabric_cache = tmp_path / manager.LOADER_SPECS["fabric"].cache_name
    forge_cache = tmp_path / manager.LOADER_SPECS["forge"].cache_name
    neoforge_cache = tmp_path / manager.LOADER_SPECS["neoforge"].cache_name

    fabric_cache.write_text("[]", encoding="utf-8")
    forge_cache.write_text("{}", encoding="utf-8")
    neoforge_cache.write_text(
        '{"1.21.1": ["1.21.1-21.1.165", "1.21.1-21.1.164"]}',
        encoding="utf-8",
    )

    versions = manager.get_compatible_loader_versions("1.21.1", "neoforge")

    assert [version.version for version in versions] == ["21.1.165", "21.1.164"]


def test_neoforge_compatible_versions_recover_old_short_cache_entries(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)
    fabric_cache = tmp_path / manager.LOADER_SPECS["fabric"].cache_name
    forge_cache = tmp_path / manager.LOADER_SPECS["forge"].cache_name
    neoforge_cache = tmp_path / manager.LOADER_SPECS["neoforge"].cache_name

    fabric_cache.write_text("[]", encoding="utf-8")
    forge_cache.write_text("{}", encoding="utf-8")
    neoforge_cache.write_text('{"21.1": ["21.1-165"]}', encoding="utf-8")

    versions = manager.get_compatible_loader_versions("1.21.1", "neoforge")

    assert [version.version for version in versions] == ["21.1.165"]


def test_normalize_neoforge_metadata_versions_groups_by_minecraft_version() -> None:
    versions = LoaderManager._normalize_version_strings(["21.1.165", "1.21.1-21.1.166-beta", "21.5.52-beta"])

    assert "1.21.1-21.1.165" in versions
    assert "1.21.1-21.1.166-beta" in versions
    assert "1.21.5-21.5.52-beta" in versions


def test_neoforge_beta_metadata_uses_minecraft_version_key(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)
    fabric_cache = tmp_path / manager.LOADER_SPECS["fabric"].cache_name
    forge_cache = tmp_path / manager.LOADER_SPECS["forge"].cache_name
    neoforge_cache = tmp_path / manager.LOADER_SPECS["neoforge"].cache_name

    fabric_cache.write_text("[]", encoding="utf-8")
    forge_cache.write_text("{}", encoding="utf-8")
    metadata = b"""<?xml version="1.0" encoding="UTF-8"?>
<metadata>
    <versioning>
        <versions>
            <version>21.5.52-beta</version>
        </versions>
    </versioning>
</metadata>
"""
    version_dict = manager._build_loader_version_dict_from_metadata(metadata, allow_prerelease=True)
    neoforge_cache.write_text(
        '{"1.21.5": ["1.21.5-21.5.52-beta"]}',
        encoding="utf-8",
    )

    versions = manager.get_compatible_loader_versions("1.21.5", "neoforge")

    assert version_dict == {"1.21.5": ["1.21.5-21.5.52-beta"]}
    assert [version.version for version in versions] == ["21.5.52-beta"]
