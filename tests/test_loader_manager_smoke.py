from __future__ import annotations

import threading
from pathlib import Path

import pytest

from src.core.loader_manager import LoaderManager
from src.utils import PathUtils


@pytest.mark.smoke
def test_clear_cache_file_resets_preload_guard(tmp_path: Path) -> None:
    manager = LoaderManager.__new__(LoaderManager)
    fabric_cache = tmp_path / "fabric_versions_cache.json"
    forge_cache = tmp_path / "forge_versions_cache.json"
    fabric_cache.write_text("[]", encoding="utf-8")
    forge_cache.write_text("{}", encoding="utf-8")

    manager.fabric_cache_file = str(fabric_cache)
    manager.forge_cache_file = str(forge_cache)
    manager._version_cache = {"fabric_1.21": [object()]}
    manager._preloaded_once = True

    manager.clear_cache_file()

    assert fabric_cache.exists() is False
    assert forge_cache.exists() is False
    assert manager._version_cache == {}
    assert manager._preloaded_once is False


@pytest.mark.smoke
def test_preload_loader_versions_reloads_when_cache_missing_even_after_preloaded_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = LoaderManager.__new__(LoaderManager)
    manager.fabric_cache_file = str(tmp_path / "fabric_versions_cache.json")
    manager.forge_cache_file = str(tmp_path / "forge_versions_cache.json")
    manager._version_cache = {}
    manager._preload_lock = threading.Lock()
    manager._preloaded_once = True
    manager.LOADER_CACHE_TTL_SECONDS = 43200

    calls: list[str] = []
    monkeypatch.setattr(manager, "_preload_fabric_versions", lambda: calls.append("fabric"))
    monkeypatch.setattr(manager, "_preload_forge_versions", lambda: calls.append("forge"))

    manager.preload_loader_versions()

    assert calls == ["fabric", "forge"]
    assert manager._preloaded_once is True


@pytest.mark.smoke
def test_preload_loader_versions_skips_network_when_cache_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = LoaderManager.__new__(LoaderManager)
    fabric_cache = tmp_path / "fabric_versions_cache.json"
    forge_cache = tmp_path / "forge_versions_cache.json"
    fabric_cache.write_text("[]", encoding="utf-8")
    forge_cache.write_text("{}", encoding="utf-8")

    manager.fabric_cache_file = str(fabric_cache)
    manager.forge_cache_file = str(forge_cache)
    manager._version_cache = {}
    manager._preload_lock = threading.Lock()
    manager._preloaded_once = False
    manager.LOADER_CACHE_TTL_SECONDS = 43200

    calls: list[str] = []
    monkeypatch.setattr(manager, "_preload_fabric_versions", lambda: calls.append("fabric"))
    monkeypatch.setattr(manager, "_preload_forge_versions", lambda: calls.append("forge"))

    manager.preload_loader_versions()

    assert calls == []
    assert manager._preloaded_once is True


@pytest.mark.smoke
def test_preload_forge_versions_uses_numeric_sort_for_versions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = LoaderManager.__new__(LoaderManager)
    manager.forge_cache_file = str(tmp_path / "forge_versions_cache.json")

    xml_content = b"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
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

    monkeypatch.setattr("src.core.loader_manager.HTTPUtils.get_content", lambda *_args, **_kwargs: xml_content)

    manager._preload_forge_versions()

    cache = PathUtils.load_json(Path(manager.forge_cache_file))
    assert isinstance(cache, dict)
    assert cache.get("1.21.1", [])[:3] == ["1.21.1-54.0.10", "1.21.1-54.0.9", "1.21.1-54.0.2"]
