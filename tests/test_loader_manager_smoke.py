from __future__ import annotations

import threading
from pathlib import Path

import pytest
from src.core import LoaderManager
from src.utils import PathUtils


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


def _build_manager_with_stub_adapters(tmp_path: Path, *, preloaded_once: bool, calls: list[str]) -> LoaderManager:
    """以 __new__ 建立 LoaderManager 並注入可記錄呼叫的樁 adapter。"""
    from src.core.loaders.base_adapter import BaseLoaderAdapter

    manager = LoaderManager.__new__(LoaderManager)
    manager.fabric_cache_file = str(tmp_path / "fabric_versions_cache.json")
    manager.forge_cache_file = str(tmp_path / "forge_versions_cache.json")
    manager.quilt_cache_file = str(tmp_path / "quilt_versions_cache.json")
    manager.neoforge_cache_file = str(tmp_path / "neoforge_versions_cache.json")
    manager._version_cache = {}
    manager._preload_lock = threading.Lock()
    manager._preloaded_once = preloaded_once
    manager.LOADER_CACHE_TTL_SECONDS = 43200

    def _make_adapter(loader_id: str) -> BaseLoaderAdapter:
        class _StubAdapter(BaseLoaderAdapter):
            def get_id(self) -> str:
                return loader_id

            def preload_versions(self):
                calls.append(loader_id)
                return

            def get_compatible_versions(self, _mc_version: str) -> list:
                return []

            def get_installer_download_url(self, _minecraft_version: str, _loader_version: str) -> str | None:
                return None

            def get_installer_args(
                self,
                _java_path: str,
                _minecraft_version: str,
                _loader_version: str,
                _download_path: str,
                _installer_path: str,
            ) -> list[str]:
                return []

            def needs_vanilla_jar(self) -> bool:
                return False

            def is_installer_required(self) -> bool:
                return False

        return _StubAdapter()

    manager.adapters = {
        "fabric": _make_adapter("fabric"),
        "forge": _make_adapter("forge"),
        "quilt": _make_adapter("quilt"),
        "neoforge": _make_adapter("neoforge"),
    }
    return manager


def test_preload_loader_versions_reloads_when_cache_missing_even_after_preloaded_once(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    manager = _build_manager_with_stub_adapters(tmp_path, preloaded_once=True, calls=calls)

    manager.preload_loader_versions()

    assert calls == ["fabric", "forge", "quilt", "neoforge"]
    assert manager._preloaded_once is True


def test_preload_loader_versions_skips_network_when_cache_fresh(
    tmp_path: Path,
) -> None:
    fabric_cache = tmp_path / "fabric_versions_cache.json"
    forge_cache = tmp_path / "forge_versions_cache.json"
    quilt_cache = tmp_path / "quilt_versions_cache.json"
    neoforge_cache = tmp_path / "neoforge_versions_cache.json"
    fabric_cache.write_text("[]", encoding="utf-8")
    forge_cache.write_text("{}", encoding="utf-8")
    quilt_cache.write_text("[]", encoding="utf-8")
    neoforge_cache.write_text("{}", encoding="utf-8")

    calls: list[str] = []
    manager = _build_manager_with_stub_adapters(tmp_path, preloaded_once=False, calls=calls)

    manager.preload_loader_versions()

    assert calls == []
    assert manager._preloaded_once is True


def test_preload_forge_versions_uses_numeric_sort_for_versions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.loaders.forge_family_adapter import ForgeAdapter

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

    monkeypatch.setattr(
        "src.utils.network_utils.http_utils.HTTPUtils.get_content", lambda *_args, **_kwargs: xml_content
    )

    adapter = ForgeAdapter(manager)
    adapter.preload_versions()

    cache = PathUtils.load_json(Path(manager.forge_cache_file))
    assert isinstance(cache, dict)
    assert cache.get("1.21.1", [])[:3] == ["1.21.1-54.0.10", "1.21.1-54.0.9", "1.21.1-54.0.2"]


def test_get_installer_download_url_supports_known_loaders(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.loaders.fabric_family_adapter import FabricAdapter, QuiltAdapter
    from src.core.loaders.forge_family_adapter import ForgeAdapter, NeoForgeAdapter

    manager = LoaderManager.__new__(LoaderManager)
    manager.adapters = {
        "fabric": FabricAdapter(manager),
        "forge": ForgeAdapter(manager),
        "quilt": QuiltAdapter(manager),
        "neoforge": NeoForgeAdapter(manager),
    }
    monkeypatch.setattr(QuiltAdapter, "_get_latest_quilt_installer_version", staticmethod(lambda: "0.12.1"))

    assert manager.get_installer_download_url("fabric", "1.21.1", "0.16.0") == (
        "https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.1/fabric-installer-1.1.1.jar"
    )
    assert manager.get_installer_download_url("forge", "1.21.1", "54.0.10") == (
        "https://maven.minecraftforge.net/net/minecraftforge/forge/1.21.1-54.0.10/forge-1.21.1-54.0.10-installer.jar"
    )
    assert manager.get_installer_download_url("neoforge", "1.21.1", "21.1.165") == (
        "https://maven.neoforged.net/releases/net/neoforged/neoforge/21.1.165/neoforge-21.1.165-installer.jar"
    )
    assert manager.get_installer_download_url("neoforge", "1.21.5", "21.5.52-beta") == (
        "https://maven.neoforged.net/releases/net/neoforged/neoforge/21.5.52-beta/neoforge-21.5.52-beta-installer.jar"
    )
    assert manager.get_installer_download_url("quilt", "1.21.1", "0.26.0") == (
        "https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/0.12.1/quilt-installer-0.12.1.jar"
    )
    assert manager.get_installer_download_url("vanilla", "1.21.1", "") is None


def _build_manager_with_real_adapters(tmp_path: Path) -> LoaderManager:
    """以 __new__ 建立 LoaderManager 並注入真實 adapter（含 neoforge）。"""
    from src.core.loaders.fabric_family_adapter import FabricAdapter, QuiltAdapter
    from src.core.loaders.forge_family_adapter import ForgeAdapter, NeoForgeAdapter

    manager = LoaderManager.__new__(LoaderManager)
    manager.fabric_cache_file = str(tmp_path / "fabric_versions_cache.json")
    manager.forge_cache_file = str(tmp_path / "forge_versions_cache.json")
    manager.quilt_cache_file = str(tmp_path / "quilt_versions_cache.json")
    manager.neoforge_cache_file = str(tmp_path / "neoforge_versions_cache.json")
    manager._version_cache = {}
    manager.adapters = {
        "fabric": FabricAdapter(manager),
        "forge": ForgeAdapter(manager),
        "quilt": QuiltAdapter(manager),
        "neoforge": NeoForgeAdapter(manager),
    }
    return manager


def test_neoforge_metadata_preserves_full_loader_version(tmp_path: Path) -> None:
    manager = _build_manager_with_real_adapters(tmp_path)
    Path(manager.fabric_cache_file).write_text("[]", encoding="utf-8")
    Path(manager.forge_cache_file).write_text("{}", encoding="utf-8")
    Path(manager.neoforge_cache_file).write_text(
        '{"1.21.1": ["1.21.1-21.1.165", "1.21.1-21.1.164"]}',
        encoding="utf-8",
    )

    versions = manager.get_compatible_loader_versions("1.21.1", "neoforge")

    assert [version.version for version in versions] == ["21.1.165", "21.1.164"]


def test_neoforge_compatible_versions_recover_old_short_cache_entries(tmp_path: Path) -> None:
    manager = _build_manager_with_real_adapters(tmp_path)
    Path(manager.fabric_cache_file).write_text("[]", encoding="utf-8")
    Path(manager.forge_cache_file).write_text("{}", encoding="utf-8")
    Path(manager.neoforge_cache_file).write_text('{"21.1": ["21.1-165"]}', encoding="utf-8")

    versions = manager.get_compatible_loader_versions("1.21.1", "neoforge")

    assert [version.version for version in versions] == ["21.1.165"]


def test_normalize_neoforge_metadata_versions_groups_by_minecraft_version() -> None:
    versions = LoaderManager._normalize_version_strings(["21.1.165", "1.21.1.21.1.166-beta", "21.5.52-beta"])

    assert "1.21.1-21.1.165" in versions
    assert "1.21.1-21.1.166-beta" in versions
    assert "1.21.5-21.5.52-beta" in versions


def test_neoforge_beta_metadata_uses_minecraft_version_key(tmp_path: Path) -> None:
    manager = _build_manager_with_real_adapters(tmp_path)
    Path(manager.fabric_cache_file).write_text("[]", encoding="utf-8")
    Path(manager.forge_cache_file).write_text("{}", encoding="utf-8")
    metadata = b"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<metadata>
    <versioning>
        <versions>
            <version>21.5.52-beta</version>
        </versions>
    </versioning>
</metadata>
"""
    version_dict = manager._build_loader_version_dict_from_metadata(metadata, allow_prerelease=True)
    Path(manager.neoforge_cache_file).write_text(
        '{"1.21.5": ["1.21.5-21.5.52-beta"]}',
        encoding="utf-8",
    )

    versions = manager.get_compatible_loader_versions("1.21.5", "neoforge")

    assert version_dict == {"1.21.5": ["1.21.5-21.5.52-beta"]}
    assert [version.version for version in versions] == ["21.5.52-beta"]
