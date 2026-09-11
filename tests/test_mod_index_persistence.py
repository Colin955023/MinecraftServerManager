from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import src.core.mods.mod_index_persistence as mod_index_module
from src.core import ModManager
from src.core.mods.mod_index_persistence import ModIndexPersistence
from src.models import ModPlatform
from src.utils import HashUtils


def test_mod_index_persistence_preserves_provider_identity_and_hashes_when_metadata_updates(tmp_path: Path) -> None:
    manager = ModIndexPersistence(str(tmp_path))
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


def test_mod_manager_uses_cached_provider_identity_and_hash_for_scan(tmp_path: Path) -> None:
    server_path = tmp_path / "server"
    mods_dir = server_path / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    file_path = mods_dir / "fabric-api.jar"
    file_path.write_bytes(b"jar-bytes")

    persistence = ModIndexPersistence(str(server_path))
    persistence.cache_metadata(
        file_path,
        {
            "name": "Fabric API",
            "version": "0.120.0",
            "author": "FabricMC",
            "description": "Core hooks",
            "loader_type": "Fabric",
            "mc_version": "1.21.1",
        },
    )
    now_ms = int(time.time() * 1000)
    persistence.replace_provider_identity(
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
    persistence.cache_file_hash(file_path, "sha512", "deadbeef")
    persistence.flush()
    manager = ModManager(str(server_path))

    mod_info = manager.local_mod_scanner.create_mod_info_from_file(file_path)

    assert mod_info is not None
    assert mod_info.platform == ModPlatform.MODRINTH
    assert mod_info.platform_id == "P7dR8mSH"
    assert mod_info.platform_slug == "fabric-api"
    assert mod_info.current_hash == "deadbeef"
    assert mod_info.hash_algorithm == "sha512"


def test_mod_index_persistence_ensure_cached_hash_defaults_to_sha512(tmp_path: Path) -> None:
    manager = ModIndexPersistence(str(tmp_path))
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    file_path = mods_dir / "example.jar"
    file_path.write_bytes(b"jar-bytes")

    computed_hash = manager.ensure_cached_hash(file_path)

    assert computed_hash
    assert manager.get_cached_hash(file_path) == computed_hash
    assert manager.get_cached_hash(file_path, "sha512") == computed_hash


def test_compute_file_hash_recomputes_when_file_content_changes(tmp_path: Path) -> None:
    ModIndexPersistence(str(tmp_path))
    file_path = tmp_path / "mods" / "cached.jar"
    file_path.parents[0].mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"first-content")

    first_hash = HashUtils.compute_file_hash_sync(file_path, algorithm="sha512")
    assert first_hash

    file_path.write_bytes(b"second-content")

    second_hash = HashUtils.compute_file_hash_sync(file_path, algorithm="sha512")
    assert second_hash
    assert second_hash != first_hash


def test_mod_index_persistence_thread_safe_parallel_updates(tmp_path: Path) -> None:
    manager = ModIndexPersistence(str(tmp_path))
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
    manager.flush()
    payload = json.loads(manager.index_file.read_text(encoding="utf-8"))
    assert len(payload["entries"]) == len(files)


def test_mod_index_persistence_migrates_legacy_plain_dict_payload(tmp_path: Path) -> None:
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

    manager = ModIndexPersistence(str(tmp_path))
    meta = manager.get_cached_metadata(file_path)

    assert meta is not None
    assert meta["name"] == "Legacy Mod"


def test_mod_index_persistence_repairs_corrupt_entry_types_on_load(tmp_path: Path) -> None:
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
                        "hashes": "bad",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    manager = ModIndexPersistence(str(tmp_path))

    repaired_payload = json.loads(index_file.read_text(encoding="utf-8"))
    assert len(repaired_payload["entries"]) == 1
    assert manager.get_cached_metadata(file_path) is None
    assert manager.get_provider_identity(file_path) is None
    assert manager.get_cached_hash(file_path, "sha512") == ""


def test_mod_index_persistence_discards_oversized_index_without_parsing(tmp_path: Path) -> None:
    index_dir = tmp_path / ".modcache"
    index_dir.mkdir(parents=True, exist_ok=True)
    index_file = index_dir / "mod_index.json"
    index_file.write_bytes(b"{" + b"x" * mod_index_module.MOD_INDEX_MAX_BYTES)

    manager = ModIndexPersistence(str(tmp_path))

    assert manager.get_cached_metadata(tmp_path / "missing.jar") is None
    assert manager.get_provider_identity(tmp_path / "missing.jar") is None


def test_mod_index_persistence_drops_stale_entry_when_file_disappears(tmp_path: Path) -> None:
    manager = ModIndexPersistence(str(tmp_path))
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    file_path = mods_dir / "removed.jar"
    file_path.write_bytes(b"jar-bytes")
    manager.cache_metadata(file_path, {"version": "1.0.0", "loader_type": "Fabric"})
    manager.flush()
    assert manager.get_cached_metadata(file_path) is not None

    file_path.unlink()
    manager.cache_metadata(file_path, {"version": "2.0.0", "loader_type": "Fabric"})
    assert manager.replace_provider_identity(file_path, {"provider": "modrinth"}) is False
    manager.flush()

    payload = json.loads(manager.index_file.read_text(encoding="utf-8"))
    assert "removed.jar" not in payload["entries"]
