"""
server.properties 舊版本設定遷移與轉換服務
支援各 Minecraft 歷史版本之屬性更名、數值型別轉換與廢棄項目清理
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from src.utils import (
    SAFE_TEXT_FILE_MAX_BYTES,
    atomic_write_text,
    copy_within,
    get_logger,
    open_bounded_zip,
    read_archive_metadata_bytes,
    read_bytes_file,
)

from .server_properties_codec import PropertiesDocumentCodec

logger = get_logger().bind(component="ServerPropertiesMigration")


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """伺服器屬性遷移計畫"""

    needs_migration: bool
    changes: tuple[str, ...]
    migrated_properties: dict[str, str]

    def summary(self) -> str:
        """
        產生繁體中文使用者提示摘要

        Returns:
            多行變更說明文字
        """
        if not self.needs_migration or not self.changes:
            return "設定檔符合最新規範，無需遷移"
        lines = [f"偵測到 {len(self.changes)} 項需要遷移的舊版設定："]
        lines.extend(f"- {description}" for description in self.changes)
        return "\n".join(lines)


class ServerPropertiesMigrationService:
    """舊版 server.properties 自動遷移服務"""

    _GAMEMODE_MAP: ClassVar[dict[str, str]] = {
        "0": "survival",
        "1": "creative",
        "2": "adventure",
        "3": "spectator",
    }
    _DIFFICULTY_MAP: ClassVar[dict[str, str]] = {
        "0": "peaceful",
        "1": "easy",
        "2": "normal",
        "3": "hard",
    }

    _LEVEL_TYPE_MAP: ClassVar[dict[str, str]] = {
        "default": "minecraft:normal",
        "flat": "minecraft:flat",
        "largebiomes": "minecraft:large_biomes",
        "amplified": "minecraft:amplified",
    }
    _LEVEL_TYPE_NORMALIZED_MAP: ClassVar[dict[str, str]] = {
        "default": "minecraft:normal",
        "flat": "minecraft:flat",
        "largebiomes": "minecraft:large_biomes",
        "amplified": "minecraft:amplified",
    }

    _DEPRECATED_KEYS: ClassVar[dict[str, str]] = {
        "max-build-height": "自 1.17 起移除，世界高度由資料包與世界生成控制",
        "snooper-enabled": "自 1.18 起移除，遙測設定已廢棄",
        "announce-player-achievements": "自 1.12 起移除，已改為遊戲規則 announceAdvancements",
    }

    @classmethod
    def plan_migration(cls, properties: dict[str, str]) -> MigrationPlan:
        """
        分析既有屬性字典並產生遷移計畫

        Args:
            properties: 現有 server.properties 的鍵值字典

        Returns:
            包含所有變更項目的遷移計畫
        """
        changes: list[str] = []
        new_props = dict(properties)

        if "texture-pack" in new_props:
            old_val = new_props.pop("texture-pack")
            if "resource-pack" not in new_props:
                new_props["resource-pack"] = old_val
                changes.append("屬性更名：texture-pack ➔ resource-pack (1.7.2+)")
            else:
                changes.append("移除舊版重複屬性：texture-pack (已存在 resource-pack)")

        if "hellworld" in new_props:
            old_val = new_props.pop("hellworld")
            if "allow-nether" not in new_props:
                new_props["allow-nether"] = old_val
                changes.append("屬性更名：hellworld ➔ allow-nether")

        if "gamemode" in new_props:
            raw_gm = str(new_props["gamemode"]).strip()
            if raw_gm in cls._GAMEMODE_MAP:
                mapped_gm = cls._GAMEMODE_MAP[raw_gm]
                new_props["gamemode"] = mapped_gm
                changes.append(f"遊戲模式轉換：gamemode={raw_gm} ➔ {mapped_gm} (1.14+)")

        if "difficulty" in new_props:
            raw_diff = str(new_props["difficulty"]).strip()
            if raw_diff in cls._DIFFICULTY_MAP:
                mapped_diff = cls._DIFFICULTY_MAP[raw_diff]
                new_props["difficulty"] = mapped_diff
                changes.append(f"遊戲難度轉換：difficulty={raw_diff} ➔ {mapped_diff} (1.14+)")

        if "level-type" in new_props:
            raw_lt = str(new_props["level-type"]).strip()
            lookup_key = raw_lt.lower().replace("_", "")
            if (mapped_lt := cls._LEVEL_TYPE_NORMALIZED_MAP.get(lookup_key)) and raw_lt != mapped_lt:
                new_props["level-type"] = mapped_lt
                changes.append(f"地圖類型命名空間轉換：level-type={raw_lt} ➔ {mapped_lt} (1.19+)")

        for dep_key, reason in cls._DEPRECATED_KEYS.items():
            if dep_key in new_props:
                new_props.pop(dep_key)
                changes.append(f"移除廢棄屬性：{dep_key} ({reason})")

        return MigrationPlan(
            needs_migration=bool(changes),
            changes=tuple(changes),
            migrated_properties=new_props,
        )

    @classmethod
    def inspect_source(cls, source_path: Path | str) -> MigrationPlan | None:
        """
        唯讀檢查匯入來源中的 server.properties

        Args:
            source_path: 伺服器資料夾或 ZIP 壓縮檔路徑

        Returns:
            若含有 server.properties 則回傳遷移計畫；否則回傳 None
        """
        path = Path(source_path)
        content: str | None = None
        if path.is_dir():
            target = path / "server.properties"
            if target.is_file():
                raw = read_bytes_file(target, max_bytes=SAFE_TEXT_FILE_MAX_BYTES)
                if raw is not None:
                    try:
                        content = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        content = raw.decode("latin-1", errors="replace")
        elif path.is_file() and path.suffix.lower() == ".zip":
            try:
                with open_bounded_zip(path) as zf:
                    for member in zf.infolist():
                        if Path(member.filename).name.lower() == "server.properties":
                            raw = read_archive_metadata_bytes(
                                zf,
                                member.filename,
                                max_bytes=SAFE_TEXT_FILE_MAX_BYTES,
                            )
                            if raw is None:
                                break
                            try:
                                content = raw.decode("utf-8")
                            except UnicodeDecodeError:
                                content = raw.decode("latin-1", errors="replace")
                            break
            except Exception as e:
                logger.debug(f"讀取 ZIP 壓縮檔中 server.properties 失敗: {e}")
                return None

        if content is None:
            return None

        properties = PropertiesDocumentCodec.parse(content)
        return cls.plan_migration(properties)

    @classmethod
    def apply_migration_to_directory(
        cls,
        directory: Path | str,
        plan: MigrationPlan,
        *,
        create_backup: bool = True,
    ) -> bool:
        """
        將遷移計畫寫入指定目錄下的 server.properties

        Args:
            directory: 伺服器目錄路徑
            plan: 欲套用的遷移計畫
            create_backup: 是否將原檔備份至 server.properties.backup

        Returns:
            寫入成功回傳 True；否則回傳 False
        """
        target_dir = Path(directory)
        props_file = target_dir / "server.properties"
        if not props_file.is_file():
            return False

        if create_backup:
            backup_file = target_dir / "server.properties.backup"
            try:
                if not copy_within(target_dir, props_file, backup_file):
                    logger.warning(f"建立 server.properties.backup 失敗：{backup_file}")
                    return False
                logger.info(f"已建立 server.properties 備份：{backup_file}")
            except Exception as e:
                logger.warning(f"建立 server.properties.backup 失敗: {e}")

        serialized = PropertiesDocumentCodec.serialize(plan.migrated_properties)
        success = atomic_write_text(props_file, serialized)
        if success:
            logger.info(f"已成功套用 server.properties 遷移：共 {len(plan.changes)} 項更動")
        return success


__all__ = [
    "ServerPropertiesMigrationService",
]
