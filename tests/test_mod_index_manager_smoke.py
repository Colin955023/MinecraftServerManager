from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from src.core import ModManager, ModPlatform
from src.utils import ModIndexManager, compute_file_hash


@pytest.mark.smoke
def test_mod_index_manager_preserves_provider_metadata_and_hashes_when_metadata_updates(tmp_path: Path) -> None:
    manager = ModIndexManager(str(tmp_path))
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    file_path = mods_dir / "fabric-api.jar"
    file_path.write_bytes(b"jar-bytes")

    manager.cache_provider_metadata(
        file_path,
        {
            "platform": "modrinth",
            "project_id": "P7dR8mSH",
            "slug": "fabric-api",
            "project_name": "Fabric API",
        },
    )
    manager.cache_file_hash(file_path, "sha512", "abc123")
    manager.cache_metadata(file_path, {"version": "0.120.0", "loader_type": "Fabric"})

    assert manager.get_cached_metadata(file_path) == {
        "version": "0.120.0",
        "loader_type": "Fabric",
    }
    assert manager.get_cached_provider_metadata(file_path) == {
        "platform": "modrinth",
        "project_id": "P7dR8mSH",
        "slug": "fabric-api",
        "project_name": "Fabric API",
    }
    assert manager.get_cached_hash(file_path, "sha512") == "abc123"


@pytest.mark.smoke
def test_mod_manager_uses_cached_provider_metadata_and_hash_for_scan(tmp_path: Path, monkeypatch) -> None:
    server_path = tmp_path / "server"
    mods_dir = server_path / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    file_path = mods_dir / "fabric-api.jar"
    file_path.write_bytes(b"jar-bytes")

    manager = ModManager(str(server_path))
    manager.index_manager.cache_metadata(
        file_path,
        {
            "version": "0.120.0",
            "author": "FabricMC",
            "description": "Core hooks",
            "loader_type": "Fabric",
            "mc_version": "1.21.1",
        },
    )
    manager.index_manager.cache_provider_metadata(
        file_path,
        {
            "platform": "modrinth",
            "project_id": "P7dR8mSH",
            "slug": "fabric-api",
            "project_name": "Fabric API",
        },
    )
    manager.index_manager.cache_file_hash(file_path, "sha512", "deadbeef")

    monkeypatch.setattr(
        manager,
        "_detect_platform_info",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should use cached provider metadata")),
    )

    mod_info = manager.create_mod_info_from_file(file_path)

    assert mod_info is not None
    assert mod_info.platform == ModPlatform.MODRINTH
    assert mod_info.platform_id == "P7dR8mSH"
    assert mod_info.platform_slug == "fabric-api"
    assert mod_info.current_hash == "deadbeef"
    assert mod_info.hash_algorithm == "sha512"


@pytest.mark.smoke
def test_mod_index_manager_ensure_cached_hash_defaults_to_sha512(tmp_path: Path) -> None:
    manager = ModIndexManager(str(tmp_path))
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    file_path = mods_dir / "example.jar"
    file_path.write_bytes(b"jar-bytes")

    computed_hash = manager.ensure_cached_hash(file_path)

    assert computed_hash
    assert manager.get_cached_hash(file_path) == computed_hash
    assert manager.get_cached_hash(file_path, "sha512") == computed_hash


@pytest.mark.smoke
def test_mod_manager_search_on_modrinth_returns_canonical_project_id_and_slug(tmp_path: Path, monkeypatch) -> None:
    manager = ModManager(str(tmp_path))

    def fake_get_json(url, timeout=None, headers=None, params=None):
        del timeout, headers
        assert url == "https://api.modrinth.com/v2/search"
        assert params == {"query": "Fabric API"}
        return {
            "hits": [
                {
                    "project_id": "P7dR8mSH",
                    "slug": "fabric-api",
                }
            ]
        }

    monkeypatch.setattr("src.core.mod_manager.HTTPUtils.get_json", fake_get_json)

    platform, project_id, slug = manager._search_on_modrinth("Fabric API", "fabric-api", "fabric-api.jar")

    assert platform == ModPlatform.MODRINTH
    assert project_id == "P7dR8mSH"
    assert slug == "fabric-api"


@pytest.mark.smoke
def test_resolve_modrinth_project_identity_falls_back_to_search_when_direct_lookup_404(
    tmp_path: Path, monkeypatch
) -> None:
    manager = ModManager(str(tmp_path))

    def fake_get_json(url, timeout=None, headers=None, params=None, suppress_status_codes=None):
        del timeout, headers
        if "api.modrinth.com/v2/project/" in url:
            assert suppress_status_codes == {404}
            return None
        assert url == "https://api.modrinth.com/v2/search"
        assert params == {"query": "ferritecore"}
        return {"hits": [{"project_id": "uXXizFIs", "slug": "ferrite-core"}]}

    monkeypatch.setattr("src.core.mod_manager.HTTPUtils.get_json", fake_get_json)

    project_id, slug = manager.resolve_modrinth_project_identity("ferritecore")

    assert project_id == "uXXizFIs"
    assert slug == "ferrite-core"


@pytest.mark.smoke
def test_compute_file_hash_recomputes_when_file_content_changes(tmp_path: Path) -> None:
    ModIndexManager(str(tmp_path))
    file_path = tmp_path / "mods" / "cached.jar"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"first-content")

    first_hash = compute_file_hash(str(file_path), "sha512")
    assert first_hash

    file_path.write_bytes(b"second-content")

    second_hash = compute_file_hash(str(file_path), "sha512")
    assert second_hash
    assert second_hash != first_hash


@pytest.mark.smoke
def test_mod_index_manager_thread_safe_parallel_updates(tmp_path: Path) -> None:
    manager = ModIndexManager(str(tmp_path))
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)

    files = []
    for idx in range(24):
        file_path = mods_dir / f"mod-{idx}.jar"
        file_path.write_bytes(f"jar-bytes-{idx}".encode())
        files.append(file_path)

    def worker(file_path: Path) -> str:
        manager.cache_metadata(file_path, {"version": f"{file_path.stem}-1.0.0", "loader_type": "Fabric"})
        manager.cache_provider_metadata(file_path, {"platform": "local", "slug": file_path.stem})
        return manager.ensure_cached_hash(file_path)

    with ThreadPoolExecutor(max_workers=8) as executor:
        hashes = list(executor.map(worker, files))

    assert all(hashes)
    assert manager.get_statistics()["total_cached"] == len(files)


@pytest.mark.smoke
def test_mod_index_manager_migrates_legacy_plain_dict_payload(tmp_path: Path) -> None:
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    file_path = mods_dir / "legacy.jar"
    file_path.write_bytes(b"legacy")

    index_dir = tmp_path / ".modcache"
    index_dir.mkdir(parents=True, exist_ok=True)
    index_file = index_dir / "mod_index.json"
    index_file.write_text(
        json.dumps(
            {
                "legacy.jar": {
                    "size": file_path.stat().st_size,
                    "mtime": file_path.stat().st_mtime,
                    "metadata": {"version": "1.0.0"},
                }
            }
        ),
        encoding="utf-8",
    )

    manager = ModIndexManager(str(tmp_path))
    cached = manager.get_cached_metadata(file_path)

    assert cached == {"version": "1.0.0"}

    manager.flush()
    payload = json.loads(index_file.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert "entries" in payload
    assert "legacy.jar" in payload["entries"]


@pytest.mark.smoke
def test_mod_index_manager_repairs_invalid_entry_shapes_on_load(tmp_path: Path) -> None:
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    file_path = mods_dir / "broken.jar"
    file_path.write_bytes(b"broken")

    index_dir = tmp_path / ".modcache"
    index_dir.mkdir(parents=True, exist_ok=True)
    index_file = index_dir / "mod_index.json"
    index_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {
                    "broken.jar": {
                        "size": file_path.stat().st_size,
                        "mtime": file_path.stat().st_mtime,
                        "metadata": ["not-a-dict"],
                        "provider_metadata": "bad",
                        "hashes": "bad",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    manager = ModIndexManager(str(tmp_path))
    report = manager.get_index_consistency_report()

    assert report["schema_version"] == 1
    assert report["total_entries"] == 1
    assert manager.get_cached_metadata(file_path) is None
    assert manager.get_cached_provider_metadata(file_path) is None
    assert manager.get_cached_hash(file_path, "sha512") == ""
