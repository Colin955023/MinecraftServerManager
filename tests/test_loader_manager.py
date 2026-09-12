from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import src.core.loader.loader_manager as loader_manager_module
from src.core import LoaderManager
from src.core.loader.loader_adapters import InstallerCommandContext
from src.utils import read_json


@pytest.fixture(autouse=True)
def isolate_loader_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """每個案例使用自己的 Loader 快取，避免測試彼此影響"""
    monkeypatch.setattr(loader_manager_module.RuntimePaths, "get_cache_dir", lambda: tmp_path / "loader-cache")


def _adapter(manager: LoaderManager, loader_id: str):
    return manager._adapters[loader_id]


def test_clear_cache_file_removes_cache_files_and_memory_cache(tmp_path: Path) -> None:
    manager = LoaderManager.__new__(LoaderManager)
    manager._initialized = False
    manager.__init__()
    manager.cache_dir = tmp_path

    fabric_cache = tmp_path / _adapter(manager, "fabric").cache_name
    forge_cache = tmp_path / _adapter(manager, "forge").cache_name
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

    fabric_cache = tmp_path / _adapter(manager, "fabric").cache_name
    forge_cache = tmp_path / _adapter(manager, "forge").cache_name
    quilt_cache = tmp_path / _adapter(manager, "quilt").cache_name
    neoforge_cache = tmp_path / _adapter(manager, "neoforge").cache_name
    vanilla_cache = tmp_path / _adapter(manager, "vanilla").cache_name
    fabric_cache.write_text("[]", encoding="utf-8")
    forge_cache.write_text("{}", encoding="utf-8")
    quilt_cache.write_text("[]", encoding="utf-8")
    neoforge_cache.write_text("{}", encoding="utf-8")
    vanilla_cache.write_text("[]", encoding="utf-8")

    calls: list[str] = []
    manager = _build_manager_for_preload_tests(tmp_path, calls=calls)

    manager.preload_loader_versions()

    assert calls == []


def test_json_loader_metadata_uses_http_json_helper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _build_manager(tmp_path)
    spec = _adapter(manager, "fabric")
    calls: list[str] = []

    def fetch_json(url: str, *_args, **_kwargs):
        calls.append(url)
        return []

    monkeypatch.setattr(loader_manager_module.HTTPClient, "fetch_json", fetch_json)
    monkeypatch.setattr(
        loader_manager_module.HTTPClient,
        "fetch_bytes",
        lambda *_args, **_kwargs: pytest.fail("JSON metadata 不應改走 fetch_bytes"),
    )

    assert manager._fetch_json_versions(spec) == []
    assert calls == [spec.api_url]


def test_preload_forge_versions_uses_numeric_sort_for_versions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = LoaderManager.__new__(LoaderManager)
    manager._initialized = False
    manager.__init__()
    manager.cache_dir = tmp_path

    forge_cache = tmp_path / _adapter(manager, "forge").cache_name

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

    spec = _adapter(manager, "forge")
    manager._preload_loader(spec)

    cache = read_json(forge_cache)
    assert isinstance(cache, dict)
    assert cache.get("1.21.1", [])[:3] == ["1.21.1-54.0.10", "1.21.1-54.0.9", "1.21.1-54.0.2"]


def test_minecraft_version_cache_refreshes_legacy_entries_without_server_sha1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _build_manager(tmp_path)
    vanilla_cache = tmp_path / _adapter(manager, "vanilla").cache_name
    vanilla_cache.write_text(
        '[{"id":"1.21.1","type":"release","url":"https://example.com/version.json",'
        '"time":"2026-08-30T00:00:00Z","server_url":"https://example.com/server.jar"}]',
        encoding="utf-8",
    )
    manifest = {
        "versions": [
            {
                "id": "1.21.1",
                "type": "release",
                "url": "https://example.com/version.json",
                "time": "2026-08-30T00:00:00Z",
                "releaseTime": "2026-08-30T00:00:00Z",
            }
        ]
    }
    detail_calls = 0
    manifest_url = _adapter(manager, "vanilla").api_url

    def fetch_json(url: str, *_args, **_kwargs):
        nonlocal detail_calls
        if url == manifest_url:
            return manifest
        detail_calls += 1
        return {
            "downloads": {
                "server": {
                    "url": "https://example.com/server.jar",
                    "sha1": "A" * 40,
                }
            }
        }

    monkeypatch.setattr(loader_manager_module.HTTPClient, "fetch_json", fetch_json)

    versions = manager.get_versions()
    cached = read_json(vanilla_cache)

    assert versions[0]["server_sha1"] == "a" * 40
    assert cached[0]["server_sha1"] == "a" * 40
    assert detail_calls == 1
    assert manager.get_versions()[0]["server_sha1"] == "a" * 40
    assert detail_calls == 1


def test_vanilla_download_paths_pass_mojang_sha1_to_http_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _build_manager(tmp_path)
    expected_sha1 = "b" * 40
    monkeypatch.setattr(
        manager,
        "_get_server_download_info",
        lambda _minecraft_version: ("https://example.com/server.jar", expected_sha1),
    )
    calls: list[dict] = []

    def download_file(*_args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(success=True, message="")

    monkeypatch.setattr(loader_manager_module.HTTPClient, "download_file", download_file)

    assert manager._download_vanilla_server("1.21.1", str(tmp_path / "installer-server.jar")) is True
    assert (
        manager.download_server_jar_with_progress(
            "vanilla",
            "1.21.1",
            "",
            str(tmp_path / "server.jar"),
        )
        is True
    )

    assert len(calls) == 2
    assert all(call["expected_hash"] == expected_sha1 for call in calls)
    assert all(call["expected_hash_algorithm"] == "sha1" for call in calls)


def _build_manager(tmp_path: Path) -> LoaderManager:
    manager = LoaderManager.__new__(LoaderManager)
    manager._initialized = False
    manager.__init__()
    manager.cache_dir = tmp_path
    return manager


def test_neoforge_metadata_preserves_full_loader_version(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)
    fabric_cache = tmp_path / _adapter(manager, "fabric").cache_name
    forge_cache = tmp_path / _adapter(manager, "forge").cache_name
    neoforge_cache = tmp_path / _adapter(manager, "neoforge").cache_name

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
    fabric_cache = tmp_path / _adapter(manager, "fabric").cache_name
    forge_cache = tmp_path / _adapter(manager, "forge").cache_name
    neoforge_cache = tmp_path / _adapter(manager, "neoforge").cache_name

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


def test_installer_checksum_logs_do_not_include_sensitive_url(monkeypatch) -> None:
    sensitive_url = "https://user:password@example.com/installer.jar?token=secret"  # pragma: allowlist secret
    manager = LoaderManager.__new__(LoaderManager)
    manager._adapters = {
        "fabric": SimpleNamespace(
            direct_download=False,
            installer_url_factory=lambda: sensitive_url,
        )
    }
    messages: list[str] = []
    fake_logger = SimpleNamespace(
        info=messages.append,
        debug=lambda message, *args: messages.append(message % args if args else message),
    )
    attempts = 0

    def fetch_checksum(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError(sensitive_url)
        return b"a" * 64

    monkeypatch.setattr(loader_manager_module, "logger", fake_logger)
    monkeypatch.setattr(loader_manager_module.HTTPClient, "fetch_bytes", fetch_checksum)

    artifact = manager.resolve_installer_artifact("fabric", "1.21.1", "0.16.0")

    assert artifact is not None
    assert artifact.hash_algorithm == "sha256"
    logged = "\n".join(messages)
    assert "https://" not in logged
    assert "password" not in logged
    assert "token=secret" not in logged


def test_neoforge_beta_metadata_uses_minecraft_version_key(tmp_path: Path) -> None:
    manager = _build_manager(tmp_path)
    fabric_cache = tmp_path / _adapter(manager, "fabric").cache_name
    forge_cache = tmp_path / _adapter(manager, "forge").cache_name
    neoforge_cache = tmp_path / _adapter(manager, "neoforge").cache_name

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


def test_vanilla_compatible_versions_refresh_legacy_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _build_manager(tmp_path)
    vanilla_cache = tmp_path / _adapter(manager, "vanilla").cache_name
    vanilla_cache.write_text(
        '[{"id":"1.21.1","server_url":"https://example.com/server.jar"}]',
        encoding="utf-8",
    )
    calls: list[str] = []

    def refresh(spec) -> None:
        calls.append(spec.id)
        vanilla_cache.write_text(
            '[{"id":"1.21.1","server_url":"https://example.com/server.jar",'
            '"server_sha1":"cccccccccccccccccccccccccccccccccccccccc"}]',
            encoding="utf-8",
        )

    monkeypatch.setattr(manager, "_preload_loader", refresh)

    versions = manager.get_compatible_loader_versions("1.21.1", "vanilla")

    assert [version.version for version in versions] == ["1.21.1"]
    assert calls == ["vanilla"]


def test_quilt_installer_uses_prevalidated_server_without_download_flag() -> None:
    manager = LoaderManager.__new__(LoaderManager)
    manager._initialized = False
    manager.__init__()
    args = _adapter(manager, "quilt").installer_args(
        InstallerCommandContext(
            java_path="java",
            minecraft_version="1.21.1",
            loader_version="0.27.0",
            installer_path="installer.jar",
        )
    )

    assert "--download-server" not in args


def test_sort_version_dict_preserves_all_versions_descending() -> None:
    raw_dict = {
        "1.20.1": [
            "47.1.0",
            "47.2.0",
            "47.3.0",
            "47.3.29",
            "47.0.1",
            "47.3.1",
            "47.2.19",
        ]
    }
    sorted_dict = LoaderManager._sort_version_dict(raw_dict)
    assert len(sorted_dict["1.20.1"]) == 7
    assert sorted_dict["1.20.1"][0] == "47.3.29"
    assert "47.3.29" in sorted_dict["1.20.1"]
    assert "47.0.1" in sorted_dict["1.20.1"]


def test_filter_quilt_versions_preserves_and_sorts_all_stable_versions() -> None:
    from src.core.loader.loader_adapters import filter_quilt_versions

    items = [
        {"version": "0.20.0", "build": 1, "stable": True},
        {"version": "0.27.0-beta.1", "build": 5, "stable": False},
        {"version": "0.26.0", "build": 3, "stable": True},
        {"version": "0.25.0", "build": 2, "stable": True},
    ]
    filtered = filter_quilt_versions(items)
    versions = [item["version"] for item in filtered]
    assert versions == ["0.26.0", "0.25.0", "0.20.0"]
