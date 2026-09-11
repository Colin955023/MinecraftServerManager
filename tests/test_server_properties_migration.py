from __future__ import annotations

import zipfile
from pathlib import Path

from src.core.server.server_properties_migration import (
    ServerPropertiesMigrationService,
)
from src.utils import SAFE_TEXT_FILE_MAX_BYTES


def test_plan_migration_renames_texture_pack() -> None:
    props = {"texture-pack": "legacy_pack.zip", "server-port": "25565"}
    plan = ServerPropertiesMigrationService.plan_migration(props)

    assert plan.needs_migration is True
    assert "texture-pack" not in plan.migrated_properties
    assert plan.migrated_properties["resource-pack"] == "legacy_pack.zip"
    assert "屬性更名：texture-pack ➔ resource-pack (1.7.2+)" in plan.changes


def test_plan_migration_removes_duplicate_texture_pack_when_resource_pack_exists() -> None:
    props = {
        "texture-pack": "old.zip",
        "resource-pack": "new.zip",
    }
    plan = ServerPropertiesMigrationService.plan_migration(props)

    assert plan.needs_migration is True
    assert "texture-pack" not in plan.migrated_properties
    assert plan.migrated_properties["resource-pack"] == "new.zip"
    assert "移除舊版重複屬性：texture-pack (已存在 resource-pack)" in plan.changes


def test_plan_migration_renames_hellworld() -> None:
    props = {"hellworld": "false"}
    plan = ServerPropertiesMigrationService.plan_migration(props)

    assert plan.needs_migration is True
    assert "hellworld" not in plan.migrated_properties
    assert plan.migrated_properties["allow-nether"] == "false"


def test_plan_migration_converts_numeric_gamemode() -> None:
    cases = [
        ("0", "survival"),
        ("1", "creative"),
        ("2", "adventure"),
        ("3", "spectator"),
    ]
    for raw, expected in cases:
        plan = ServerPropertiesMigrationService.plan_migration({"gamemode": raw})
        assert plan.needs_migration is True
        assert plan.migrated_properties["gamemode"] == expected


def test_plan_migration_converts_numeric_difficulty() -> None:
    cases = [
        ("0", "peaceful"),
        ("1", "easy"),
        ("2", "normal"),
        ("3", "hard"),
    ]
    for raw, expected in cases:
        plan = ServerPropertiesMigrationService.plan_migration({"difficulty": raw})
        assert plan.needs_migration is True
        assert plan.migrated_properties["difficulty"] == expected


def test_plan_migration_converts_level_type() -> None:
    cases = [
        ("default", "minecraft:normal"),
        ("DEFAULT", "minecraft:normal"),
        ("flat", "minecraft:flat"),
        ("largebiomes", "minecraft:large_biomes"),
        ("large_biomes", "minecraft:large_biomes"),
        ("amplified", "minecraft:amplified"),
    ]
    for raw, expected in cases:
        plan = ServerPropertiesMigrationService.plan_migration({"level-type": raw})
        assert plan.needs_migration is True
        assert plan.migrated_properties["level-type"] == expected


def test_plan_migration_removes_deprecated_keys() -> None:
    props = {
        "max-build-height": "256",
        "snooper-enabled": "true",
        "announce-player-achievements": "true",
        "motd": "Test Server",
    }
    plan = ServerPropertiesMigrationService.plan_migration(props)

    assert plan.needs_migration is True
    assert "max-build-height" not in plan.migrated_properties
    assert "snooper-enabled" not in plan.migrated_properties
    assert "announce-player-achievements" not in plan.migrated_properties
    assert plan.migrated_properties["motd"] == "Test Server"
    assert len(plan.changes) == 3


def test_plan_migration_no_changes_needed() -> None:
    props = {
        "gamemode": "survival",
        "difficulty": "hard",
        "level-type": "minecraft:normal",
        "allow-nether": "true",
        "resource-pack": "https://example.invalid/pack.zip",
    }
    plan = ServerPropertiesMigrationService.plan_migration(props)

    assert plan.needs_migration is False
    assert len(plan.changes) == 0
    assert "無需遷移" in plan.summary()


def test_inspect_source_and_apply_migration_directory(tmp_path: Path) -> None:
    server_dir = tmp_path / "legacy_server"
    server_dir.mkdir()
    props_file = server_dir / "server.properties"
    props_file.write_text("gamemode=1\ndifficulty=2\nlevel-type=default\nmax-build-height=256\n", encoding="utf-8")

    plan = ServerPropertiesMigrationService.inspect_source(server_dir)
    assert plan is not None
    assert plan.needs_migration is True
    assert len(plan.changes) == 4

    summary = plan.summary()
    assert "遊戲模式轉換" in summary
    assert "遊戲難度轉換" in summary
    assert "地圖類型命名空間轉換" in summary
    assert "移除廢棄屬性" in summary

    success = ServerPropertiesMigrationService.apply_migration_to_directory(server_dir, plan, create_backup=True)
    assert success is True

    backup_file = server_dir / "server.properties.backup"
    assert backup_file.is_file()
    assert "gamemode=1" in backup_file.read_text(encoding="utf-8")

    migrated_content = props_file.read_text(encoding="utf-8")
    assert "gamemode=creative" in migrated_content
    assert "difficulty=normal" in migrated_content
    assert "level-type=minecraft\\:normal" in migrated_content or "level-type=minecraft:normal" in migrated_content
    assert "max-build-height" not in migrated_content


def test_inspect_source_zip(tmp_path: Path) -> None:
    zip_path = tmp_path / "legacy_server.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("server.properties", "gamemode=0\ntexture-pack=pack.zip\n")

    plan = ServerPropertiesMigrationService.inspect_source(zip_path)
    assert plan is not None
    assert plan.needs_migration is True
    assert plan.migrated_properties["gamemode"] == "survival"
    assert plan.migrated_properties["resource-pack"] == "pack.zip"


def test_inspect_source_zip_ignores_oversized_server_properties(tmp_path: Path) -> None:
    zip_path = tmp_path / "oversized_server_properties.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("server.properties", b"x" * (SAFE_TEXT_FILE_MAX_BYTES + 1))

    assert ServerPropertiesMigrationService.inspect_source(zip_path) is None
