from __future__ import annotations

import shutil
import threading
from pathlib import Path

import pytest
from src.core import LoaderManager
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


@pytest.mark.smoke
def test_parse_remote_checksum_payload_accepts_sha256() -> None:
    checksum = "a" * 64
    payload = f"{checksum}  installer.jar\n".encode()

    assert LoaderManager._parse_remote_checksum_payload(payload, "sha256") == checksum


@pytest.mark.smoke
def test_download_file_with_progress_requires_secure_hash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manager = LoaderManager.__new__(LoaderManager)
    errors: list[str] = []

    monkeypatch.setattr(manager, "_fetch_secure_checksum", lambda _url: None)

    result = manager._download_file_with_progress(
        "https://example.invalid/installer.jar",
        str(tmp_path / "installer.jar"),
        lambda _percent, message: errors.append(str(message)),
        0,
        100,
        "下載安裝器...",
        None,
        require_secure_hash=True,
    )

    assert result is False
    assert errors[-1] == "下載失敗：缺少 SHA-256 / SHA-512 驗證資訊"


@pytest.mark.smoke
def test_download_and_run_installer_cleans_process_when_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = LoaderManager.__new__(LoaderManager)
    test_root = Path("tests") / ".tmp_loader_manager_cancelled"
    shutil.rmtree(test_root, ignore_errors=True)
    test_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(manager, "_download_file_with_progress", lambda *_args, **_kwargs: True)

    class _Stdout:
        def readline(self) -> str:
            return "Downloading installer...\n"

    class _Process:
        pid = 4321
        returncode = None
        stdout = _Stdout()

        def poll(self):
            return None

    cleaned: list[tuple[str, object]] = []

    def _record_tree_cleanup(pid: int) -> bool:
        cleaned.append(("tree", pid))
        return True

    def _record_path_cleanup(path: object) -> bool:
        cleaned.append(("path", str(path)))
        return True

    monkeypatch.setattr(
        "src.core.loader_manager.SubprocessUtils.popen_checked",
        lambda *_args, **_kwargs: _Process(),
    )
    monkeypatch.setattr(
        "src.core.loader_manager.SystemUtils.kill_process_tree",
        _record_tree_cleanup,
    )
    monkeypatch.setattr(
        "src.core.loader_manager.SystemUtils.kill_java_processes_in_path",
        _record_path_cleanup,
    )
    monkeypatch.setattr("src.core.loader_manager.record_and_mark", lambda *_args, **_kwargs: None)

    result = manager._download_and_run_installer(
        installer_url="https://example.invalid/installer.jar",
        installer_args=["java", "-jar", "{installer}", "--installServer"],
        minecraft_version="1.21.1",
        _loader_version="0.16.0",
        download_path=str(test_root / "server.jar"),
        progress_callback=None,
        cancel_flag={"cancelled": True},
        need_vanilla=False,
    )

    assert result is False
    assert ("tree", 4321) in cleaned
    assert ("path", str(test_root)) in cleaned
    shutil.rmtree(test_root, ignore_errors=True)
