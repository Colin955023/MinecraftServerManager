from __future__ import annotations

from pathlib import Path

import pytest
from src.core import ModManager
from src.utils import (
    build_non_official_source_warning,
    build_non_official_source_warning_message,
    get_non_official_download_host,
)


@pytest.mark.smoke
def test_import_local_mod_file_result_copies_mod_and_notifies(tmp_path: Path) -> None:
    server_path = tmp_path / "server"
    source_path = tmp_path / "downloads" / "example.jar"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"jar-bytes")

    manager = ModManager(str(server_path))
    notifications: list[str] = []
    manager.on_mod_list_changed = lambda: notifications.append("changed")

    result = manager.import_local_mod_file_result(source_path)

    target_path = server_path / "mods" / "example.jar"
    assert result.completed is True
    assert result.final_path == target_path
    assert target_path.read_bytes() == b"jar-bytes"
    assert notifications == ["changed"]


@pytest.mark.smoke
def test_delete_local_mods_result_deletes_existing_files_and_reports_missing(tmp_path: Path) -> None:
    server_path = tmp_path / "server"
    manager = ModManager(str(server_path))
    notifications: list[str] = []
    manager.on_mod_list_changed = lambda: notifications.append("changed")
    mods_dir = server_path / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    enabled_mod = mods_dir / "clumps.jar"
    disabled_mod = mods_dir / "fabric-api.jar.disabled"
    enabled_mod.write_bytes(b"enabled")
    disabled_mod.write_bytes(b"disabled")

    result = manager.delete_local_mods_result(["clumps", "missing-mod", "fabric-api"])

    assert result.partial is True
    assert result.affected_count == 2
    assert result.missing_ids == ("missing-mod",)
    assert enabled_mod.exists() is False
    assert disabled_mod.exists() is False
    assert notifications == ["changed"]


@pytest.mark.smoke
def test_download_source_policy_flags_non_official_hosts_only() -> None:
    assert get_non_official_download_host("https://cdn.modrinth.com/data/example.jar", "modrinth") == ""
    assert (
        get_non_official_download_host("https://mirror.example.com/files/example.jar", "modrinth")
        == "mirror.example.com"
    )
    assert build_non_official_source_warning(
        "https://mirror.example.com/files/example.jar",
        "modrinth",
    ) == (
        "偵測到非官方下載來源：provider=modrinth host=mirror.example.com "
        "url=https://mirror.example.com/files/example.jar"
    )
    assert build_non_official_source_warning_message(
        "Example Mod",
        "https://mirror.example.com/files/example.jar",
        "modrinth",
        provider_label="Modrinth",
    ) == ("非官方下載來源：Example Mod 將從 mirror.example.com 下載，非 Modrinth 官方網域，請再次確認來源可信度。")
