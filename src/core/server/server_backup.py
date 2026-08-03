"""
伺服器備份功能
負責管理伺服器的備份與還原。
"""

from __future__ import annotations

import datetime
import os
import zipfile
from pathlib import Path
from typing import Any

from ...models import ServerConfig
from ...utils import get_logger

logger = get_logger().bind(component="ServerBackup")


class ServerBackupManager:
    """伺服器備份管理器"""

    def __init__(self, server_crud):
        self.server_crud = server_crud

    def _get_backup_dir(self, config: ServerConfig) -> Path:
        """取得伺服器的備份存放目錄"""
        if config.backup_path and config.backup_path.strip():
            backup_dir = Path(config.backup_path)
        else:
            server_path = Path(config.path)
            # 預設放在伺服器目錄外的備份區，或是伺服器目錄下的 backups 資料夾
            backup_dir = server_path / "backups"

        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir

    def backup_server(self, server_name: str, max_backups: int = 10) -> bool:
        """
        備份伺服器。
        使用 YYYYMMDDHHMM 格式。
        最多保留 max_backups 份。
        """
        try:
            config = self.server_crud.servers.get(server_name)
            if not config:
                logger.error(f"備份失敗：找不到伺服器 {server_name}")
                return False

            server_path = Path(config.path)
            if not server_path.exists() or not server_path.is_dir():
                logger.error(f"備份失敗：伺服器路徑不存在 {server_path}")
                return False

            backup_dir = self._get_backup_dir(config)
            now = datetime.datetime.now()
            timestamp = now.strftime("%Y%m%d%H%M")
            backup_filename = f"{server_name}_{timestamp}.zip"
            backup_file = backup_dir / backup_filename

            logger.info(f"開始備份伺服器 {server_name} 至 {backup_file}")

            # 排除的目錄
            excludes = {"logs", "crash-reports", "backups", ".git"}

            with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(server_path):
                    dirs[:] = [d for d in dirs if d not in excludes]
                    for file in files:
                        file_path = Path(root) / file
                        # 避免備份到備份檔自己（如果 backup_dir 在 server_path 下）
                        if backup_dir in file_path.parents:
                            continue
                        rel_path = file_path.relative_to(server_path)
                        zf.write(file_path, arcname=str(rel_path))

            logger.info(f"伺服器 {server_name} 備份成功。")
            self._cleanup_old_backups(backup_dir, server_name, max_backups)
            return True
        except Exception as e:
            logger.exception(f"伺服器 {server_name} 備份時發生錯誤: {e}")
            return False

    def _cleanup_old_backups(self, backup_dir: Path, server_name: str, max_backups: int) -> None:
        """清理超過保留數量的舊備份。"""
        try:
            backups = self.list_backups(server_name, backup_dir_override=backup_dir)
            if len(backups) <= max_backups:
                return

            # backups 預設已依時間由新到舊排序
            to_delete = backups[max_backups:]
            for b in to_delete:
                path = Path(b["path"])
                try:
                    path.unlink()
                    logger.info(f"已刪除舊備份: {path.name}")
                except Exception as e:
                    logger.warning(f"刪除舊備份失敗 {path.name}: {e}")
        except Exception as e:
            logger.exception(f"清理舊備份時發生錯誤: {e}")

    def list_backups(self, server_name: str, backup_dir_override: Path | None = None) -> list[dict[str, Any]]:
        """
        列出所有備份。
        回傳清單依時間由新到舊排序。
        回傳格式: [{"filename": str, "path": str, "timestamp": str, "readable_time": str, "size_mb": float}]
        """
        if backup_dir_override:
            backup_dir = backup_dir_override
        else:
            config = self.server_crud.servers.get(server_name)
            if not config:
                return []
            backup_dir = self._get_backup_dir(config)

        if not backup_dir.exists():
            return []

        backups = []
        prefix = f"{server_name}_"
        for file_path in backup_dir.glob(f"{prefix}*.zip"):
            name = file_path.stem
            timestamp_str = name[len(prefix) :]
            if len(timestamp_str) == 12 and timestamp_str.isdigit():  # YYYYMMDDHHMM
                try:
                    dt = datetime.datetime.strptime(timestamp_str, "%Y%m%d%H%M")
                    readable_time = dt.strftime("%Y/%m/%d %H:%M")
                    size_mb = file_path.stat().st_size / (1024 * 1024)
                    backups.append(
                        {
                            "filename": file_path.name,
                            "path": str(file_path),
                            "timestamp": timestamp_str,
                            "readable_time": readable_time,
                            "size_mb": round(size_mb, 2),
                            "datetime": dt,
                        }
                    )
                except ValueError:
                    continue

        backups.sort(key=lambda x: x["datetime"], reverse=True)  # type: ignore
        return backups

    def restore_backup(self, server_name: str, backup_path_str: str) -> bool:
        """
        從備份檔還原伺服器。會覆蓋現有檔案，但保留原本排除的資料夾（如 logs）。
        """
        try:
            config = self.server_crud.servers.get(server_name)
            if not config:
                logger.error(f"還原失敗：找不到伺服器 {server_name}")
                return False

            server_path = Path(config.path)
            backup_file = Path(backup_path_str)

            if not backup_file.exists() or not backup_file.is_file():
                logger.error(f"還原失敗：找不到備份檔 {backup_file}")
                return False

            logger.info(f"開始從 {backup_file.name} 還原伺服器 {server_name}")

            # 解壓縮覆蓋現有檔案
            with zipfile.ZipFile(backup_file, "r") as zf:
                zf.extractall(server_path)

            logger.info(f"伺服器 {server_name} 還原成功。")
            return True
        except Exception as e:
            logger.exception(f"還原伺服器時發生錯誤: {e}")
            return False
