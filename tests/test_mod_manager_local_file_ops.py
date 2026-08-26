from __future__ import annotations

from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from src.core import ModManager
from src.models import LocalModInfo, ModStatus
from src.utils import (
    build_non_official_source_warning,
    build_non_official_source_warning_message,
    get_non_official_download_host,
    read_json,
)


def test_import_local_mod_file_result_copies_mod_and_notifies(tmp_path: Path) -> None:
    server_path = tmp_path / "server"
    source_path = tmp_path / "downloads" / "example.jar"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"jar-bytes")

    manager = ModManager(str(server_path))
    notifications: list[str] = []
    manager.mod_file_installer.on_mod_list_changed = lambda: notifications.append("changed")

    result = manager.mod_file_installer.import_local_mod_file_result(source_path)

    target_path = server_path / "mods" / "example.jar"
    assert result.completed is True
    assert result.final_path == target_path
    assert target_path.read_bytes() == b"jar-bytes"
    assert notifications == ["changed"]


def test_quarantine_file_records_issue_in_mod_index(tmp_path: Path) -> None:
    server_path = tmp_path / "server"
    manager = ModManager(str(server_path))
    damaged_mod = server_path / "mods" / "damaged.jar"
    damaged_mod.write_bytes(b"not-a-jar")

    manager._quarantine_file(damaged_mod, "io_or_bad_zip")

    payload = read_json(server_path / ".modcache" / "mod_index.json", {})
    issue = payload["entries"]["damaged.jar"]["issue"]
    assert issue["reason"] == "io_or_bad_zip"
    assert issue["detected_at"] > 0


def test_delete_local_mods_result_deletes_existing_files_and_reports_missing(tmp_path: Path) -> None:
    server_path = tmp_path / "server"
    manager = ModManager(str(server_path))
    notifications: list[str] = []
    manager.mod_file_installer.on_mod_list_changed = lambda: notifications.append("changed")
    mods_dir = server_path / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    enabled_mod = mods_dir / "clumps.jar"
    disabled_mod = mods_dir / "fabric-api.jar.disabled"
    enabled_mod.write_bytes(b"enabled")
    disabled_mod.write_bytes(b"disabled")

    result = manager.mod_file_installer.delete_local_mods_result(["clumps", "missing-mod", "fabric-api"])

    assert result.partial is True
    assert result.affected_count == 2
    assert result.missing_ids == ("missing-mod",)
    assert enabled_mod.exists() is False
    assert disabled_mod.exists() is False
    assert notifications == ["changed"]


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
    ) == ("非官方下載來源：Example Mod 將從 mirror.example.com 下載，非 Modrinth 官方網域，請再次確認來源可信度")
    assert (
        get_non_official_download_host("https://edge.example.net/files/example2.jar", "modrinth") == "edge.example.net"
    )
    assert build_non_official_source_warning(
        "https://edge.example.net/files/example2.jar",
        "modrinth",
    ) == (
        "偵測到非官方下載來源：provider=modrinth host=edge.example.net url=https://edge.example.net/files/example2.jar"
    )
    assert build_non_official_source_warning_message(
        "Edge Mod",
        "https://edge.example.net/files/example2.jar",
        "modrinth",
        provider_label="Modrinth",
    ) == ("非官方下載來源：Edge Mod 將從 edge.example.net 下載，非 Modrinth 官方網域，請再次確認來源可信度")


def test_export_mod_list_html_escapes_mod_metadata() -> None:
    manager = ModManager.__new__(ModManager)
    manager.get_mod_list = lambda: [
        LocalModInfo(
            id="evil",
            name='<script>alert("x")</script>',
            filename="evil.jar",
            version="1.0<beta>",
            minecraft_version="1.21",
            loader_type="Fabric",
            author="Alice & Bob",
            description='"><img src=x onerror=alert(1)>',
            status=ModStatus.ENABLED,
        )
    ]

    html = manager.export_mod_list("html")

    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html
    assert "Alice &amp; Bob" in html
    assert "&quot;&gt;&lt;img src=x onerror=alert(1)&gt;" in html


def test_export_mod_list_xlsx_uses_minimal_valid_workbook() -> None:
    manager = ModManager.__new__(ModManager)
    manager.get_mod_list = lambda: [
        LocalModInfo(
            id="example<&",
            name="Example & <Core>",
            filename="example.jar",
            version="1.0",
            minecraft_version="1.21",
            loader_type="Fabric",
            author="Alice",
            description="Line 1\x01 Line 2",
            status=ModStatus.ENABLED,
        )
    ]

    payload = manager.export_mod_list("xlsx")

    assert isinstance(payload, bytes)
    with ZipFile(BytesIO(payload)) as workbook:
        assert {
            "[Content_Types].xml",
            "_rels/.rels",
            "xl/workbook.xml",
            "xl/_rels/workbook.xml.rels",
            "xl/worksheets/sheet1.xml",
        }.issubset(workbook.namelist())
        sheet = ElementTree.fromstring(workbook.read("xl/worksheets/sheet1.xml"))

    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    values = [node.text or "" for node in sheet.findall(".//x:t", namespace)]
    assert "Example & <Core>" in values
    assert "example<&" in values
    assert "Line 1 Line 2" in values
