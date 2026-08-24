"""
伺服器備份功能
負責管理伺服器的備份與還原
"""

from __future__ import annotations

import datetime
import os
import tempfile
import zipfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from src.models import ServerConfig
from src.utils import PathUtils, bytes_to_mb, get_logger

logger = get_logger().bind(component="ServerBackup")


class ServerBackupManager:
    """伺服器備份管理器"""

    def __init__(self, server_crud):
        self.server_crud = server_crud

    def backup_server(
        self, server_name: str, max_backups: int = 10, progress_callback: Callable[[float, str], None] | None = None
    ) -> bool:
        """
        備份伺服器。先在備份目錄建立暫存 ZIP，完整成功後再原子替換最終檔案。
        使用 YYYYMMDDHHMM 格式，最多保留 max_backups 份。

        Args:
            server_name: 伺服器名稱
            max_backups: 最多保留的備份份數
            progress_callback: 進度回呼，接收 (進度百分比 0-100, 狀態文字)

        Returns:
            備份成功回傳 True，失敗回傳 False
        """
        temp_backup_file: Path | None = None
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
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M")
            backup_filename = f"{server_name}_{timestamp}.zip"
            backup_file = backup_dir / backup_filename

            logger.info(f"開始備份伺服器 {server_name} 至 {backup_file}")

            if progress_callback:
                progress_callback(0, "正在掃描檔案...")

            excludes = {"logs", "crash-reports", "backups", ".git"}
            files_to_backup: list[tuple[Path, int]] = []
            total_size = 0

            for root, dirs, files in os.walk(server_path):
                dirs[:] = [d for d in dirs if d not in excludes]
                for file in files:
                    file_path = Path(root) / file
                    if backup_dir in file_path.parents:
                        continue
                    try:
                        file_size = file_path.stat().st_size
                    except OSError as exc:
                        raise OSError(f"無法讀取備份來源檔案資訊: {file_path}") from exc
                    files_to_backup.append((file_path, file_size))
                    total_size += file_size

            if progress_callback:
                progress_callback(5, f"準備備份 {len(files_to_backup)} 個檔案...")

            fd, temp_name = tempfile.mkstemp(prefix=f".{backup_filename}.", suffix=".tmp", dir=backup_dir)
            temp_backup_file = Path(temp_name)
            os.close(fd)

            processed_size = 0
            with zipfile.ZipFile(temp_backup_file, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, (file_path, file_size) in enumerate(files_to_backup):
                    rel_path = file_path.relative_to(server_path)
                    if progress_callback and i % 10 == 0:
                        pct = 5 + (processed_size / total_size * 90 if total_size > 0 else 0)
                        progress_callback(pct, f"正在壓縮: {rel_path.name}")
                    try:
                        zf.write(file_path, arcname=str(rel_path))
                    except Exception as exc:
                        raise OSError(f"備份檔案失敗: {file_path}") from exc
                    processed_size += file_size

            Path.replace(temp_backup_file, backup_file)
            temp_backup_file = None

            if progress_callback:
                progress_callback(95, "正在清理舊備份...")

            logger.info(f"伺服器 {server_name} 備份成功")
            self._cleanup_old_backups(backup_dir, server_name, max_backups)

            if progress_callback:
                progress_callback(100, "備份完成！")
            return True
        except Exception as e:
            if temp_backup_file is not None:
                with suppress(OSError):
                    temp_backup_file.unlink(missing_ok=True)
            logger.exception(f"伺服器 {server_name} 備份時發生錯誤: {e}")
            return False

    def list_backups(self, server_name: str, backup_dir_override: Path | None = None) -> list[dict[str, Any]]:
        """
        列出所有備份
        回傳清單依時間由新到舊排序
        回傳格式: [{"filename": str, "path": str, "timestamp": str, "readable_time": str, "size_mb": float}]

        Args:
            server_name: 伺服器名稱
            backup_dir_override: 指定備份目錄；若為 None 則使用伺服器設定中的目錄

        Returns:
            備份資訊清單
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
            if len(timestamp_str) == 12 and timestamp_str.isdigit():
                try:
                    dt = datetime.datetime.strptime(timestamp_str, "%Y%m%d%H%M")
                    readable_time = dt.strftime("%Y/%m/%d %H:%M")
                    size_mb = bytes_to_mb(file_path.stat().st_size)
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

        backups.sort(key=lambda x: cast(Any, x["datetime"]), reverse=True)
        return backups

    def restore_backup(
        self, server_name: str, backup_path_str: str, progress_callback: Callable[[float, str], None] | None = None
    ) -> bool:
        """
        從備份檔還原伺服器會覆蓋現有檔案，但保留原本排除的資料夾（如 logs）

        Args:
            server_name: 伺服器名稱
            backup_path_str: 備份檔路徑
            progress_callback: 進度回呼，接收 (進度百分比 0-100, 狀態文字)

        Returns:
            還原成功回傳 True，失敗回傳 False
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

            if progress_callback:
                progress_callback(0, f"準備還原 {backup_file.name}...")

            def _on_extract_progress(extracted_bytes: int, total_bytes: int) -> None:
                if not progress_callback:
                    return
                pct = 5 + (extracted_bytes / total_bytes * 90 if total_bytes > 0 else 90)
                progress_callback(pct, f"解壓縮中... {extracted_bytes}/{total_bytes} bytes")

            PathUtils.safe_extract_zip(backup_file, server_path, progress_callback=_on_extract_progress)

            if progress_callback:
                progress_callback(100, "還原完成！")

            logger.info(f"伺服器 {server_name} 還原成功")
            return True
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            logger.exception(f"還原伺服器時發生錯誤: {e}")
            return False

    def _get_backup_dir(self, config: ServerConfig) -> Path:
        """取得伺服器的備份存放目錄"""
        server_path = Path(config.path)
        backup_dir = server_path / "backups"

        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir

    def _cleanup_old_backups(self, backup_dir: Path, server_name: str, max_backups: int) -> None:
        """清理超過保留數量的舊備份"""
        try:
            backups = self.list_backups(server_name, backup_dir_override=backup_dir)
            if len(backups) <= max_backups:
                return

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


__all__ = ["ServerBackupManager"]
