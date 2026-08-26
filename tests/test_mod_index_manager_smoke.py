from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.core import ModManager
from src.models import ModPlatform
from src.utils import HashUtils, ModIndexManager


def test_mod_index_manager_preserves_provider_metadata_and_hashes_when_metadata_updates(tmp_path: Path) -> None:
    manager = ModIndexManager(str(tmp_path))
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    file_path = mods_dir / "fabric-api.jar"
    file_path.write_bytes(b"jar-bytes")

    identity = {
        "schema_version": 2,
        "provider": "modrinth",
        "project_id": "P7dR8mSH",
        "alias": "fabric-api",
        "display_name": "Fabric API",
        "provenance": "test",
        "lifecycle": "fresh",
        "observed_at_epoch_ms": int(time.time() * 1000),
        "resolved_at_epoch_ms": int(time.time() * 1000),
        "failure_count": 0,
        "next_retry_not_before_epoch_ms": 0,
    }
    manager.replace_provider_identity(
        file_path,
        identity,
    )
    manager.cache_file_hash(file_path, "sha512", "abc123")
    manager.cache_metadata(file_path, {"version": "0.120.0", "loader_type": "Fabric"})

    assert manager.get_cached_metadata(file_path) == {
        "version": "0.120.0",
        "loader_type": "Fabric",
    }
    assert manager.get_provider_identity(file_path) == identity
    assert manager.get_cached_hash(file_path, "sha512") == "abc123"


def test_mod_manager_uses_cached_provider_metadata_and_hash_for_scan(tmp_path: Path) -> None:
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
    now_ms = int(time.time() * 1000)
    manager.index_manager.replace_provider_identity(
        file_path,
        {
            "schema_version": 2,
            "provider": "modrinth",
            "project_id": "P7dR8mSH",
            "alias": "fabric-api",
            "display_name": "Fabric API",
            "provenance": "test",
            "lifecycle": "fresh",
            "observed_at_epoch_ms": now_ms,
            "resolved_at_epoch_ms": now_ms,
            "failure_count": 0,
            "next_retry_not_before_epoch_ms": 0,
        },
    )
    manager.index_manager.cache_file_hash(file_path, "sha512", "deadbeef")

    mod_info = manager.local_mod_scanner.create_mod_info_from_file(file_path)

    assert mod_info is not None
    assert mod_info.platform == ModPlatform.MODRINTH
    assert mod_info.platform_id == "P7dR8mSH"
    assert mod_info.platform_slug == "fabric-api"
    assert mod_info.current_hash == "deadbeef"
    assert mod_info.hash_algorithm == "sha512"


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


def test_compute_file_hash_recomputes_when_file_content_changes(tmp_path: Path) -> None:
    ModIndexManager(str(tmp_path))
    file_path = tmp_path / "mods" / "cached.jar"
    file_path.parents[0].mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"first-content")

    first_hash = HashUtils.compute_file_hash_sync(file_path, algorithm="sha512")
    assert first_hash

    file_path.write_bytes(b"second-content")

    second_hash = HashUtils.compute_file_hash_sync(file_path, algorithm="sha512")
    assert second_hash
    assert second_hash != first_hash


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
        manager.replace_provider_identity(
            file_path,
            {
                "schema_version": 2,
                "provider": "modrinth",
                "project_id": "",
                "alias": file_path.stem,
                "lifecycle": "retrying",
            },
        )
        return manager.ensure_cached_hash(file_path)

    with ThreadPoolExecutor(max_workers=8) as executor:
        hashes = list(executor.map(worker, files))

    assert all(hashes)
    assert len(manager._index) == len(files)


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
                    "metadata": {"name": "Legacy Mod", "version": "1.0.0"},
                }
            }
        ),
        encoding="utf-8",
    )

    manager = ModIndexManager(str(tmp_path))
    meta = manager.get_cached_metadata(file_path)

    assert meta is not None
    assert meta["name"] == "Legacy Mod"


def test_mod_index_manager_repairs_corrupt_entry_types_on_load(tmp_path: Path) -> None:
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

    assert len(manager._index) == 1
    assert manager.get_cached_metadata(file_path) is None
    assert manager.get_provider_identity(file_path) is None
    assert manager.get_cached_hash(file_path, "sha512") == ""
