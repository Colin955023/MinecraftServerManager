"""
伺服器備份與還原模組
處理伺服器的備份建立、還原、清單查詢邏輯。
"""

import contextlib
import os
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...models import ServerOperationResult
from ...utils import PathUtils, get_logger, record_and_mark

if TYPE_CHECKING:
    from .server_startup import ServerStartup

logger = get_logger().bind(component="ServerBackup")


class ServerBackup:
    """處理伺服器的備份與還原邏輯。"""

    def __init__(self, startup: ServerStartup):
        self.startup = startup

    def _success_result(self, message: str = "", *, server_name: str = "") -> ServerOperationResult:
        return ServerOperationResult(success=True, message=message, server_name=server_name)

    def _failure_result(self, title: str, message: str, *, server_name: str = "") -> ServerOperationResult:
        return ServerOperationResult(success=False, title=title, message=message, server_name=server_name)

    def _get_backup_dir(self, server_name: str) -> Path | None:
        """取得伺服器備份目錄。"""
        config = self.startup.get_server_info(server_name)
        if not config or not config.get("path"):
            return None
        if config.get("backup_path"):
            return PathUtils.get_app_path(str(config["backup_path"]))
        return PathUtils.get_app_path(str(config["path"])) / "backups"

    def create_backup(self, server_name: str, note: str = "") -> ServerOperationResult:
        """
        建立伺服器備份。

        Args:
            server_name: 伺服器名稱
            note: 備份附註 (會加在檔名上)

        Returns:
            ServerOperationResult: 備份結果
        """
        config = self.startup.get_server_info(server_name)
        if not config or not config.get("path"):
            return self._failure_result("備份失敗", "找不到伺服器配置或路徑", server_name=server_name)

        server_path = PathUtils.get_app_path(str(config["path"]))
        if not server_path.exists():
            return self._failure_result("備份失敗", f"伺服器目錄不存在: {server_path}", server_name=server_name)

        backup_dir = self._get_backup_dir(server_name)
        if not backup_dir:
            return self._failure_result("備份失敗", "無法決定備份目錄", server_name=server_name)

        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            suffix = f"_{note}" if note else ""
            backup_filename = f"{server_name}_{timestamp}{suffix}.zip"
            backup_path = backup_dir / backup_filename

            logger.info(f"開始備份 {server_name} 至 {backup_path}")

            with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(server_path):
                    root_path = Path(root)
                    # 避免備份到備份資料夾本身
                    if backup_dir in root_path.parents or root_path == backup_dir:
                        continue

                    for file in files:
                        file_path = root_path / file
                        arcname = file_path.relative_to(server_path)
                        zipf.write(file_path, arcname)

            return self._success_result(f"成功建立備份: {backup_filename}", server_name=server_name)
        except Exception as e:
            logger.error(f"備份伺服器 {server_name} 失敗: {e}", exc_info=True)
            record_and_mark(f"backup_{server_name}", e)
            return self._failure_result("備份失敗", f"發生錯誤: {e}", server_name=server_name)

    def list_backups(self, server_name: str) -> list[dict[str, Any]]:
        """
        列出所有伺服器備份。

        Args:
            server_name: 伺服器名稱

        Returns:
            list[dict[str, Any]]: 備份清單，每個備份包含 filename、path、size、created_at 等資訊
        """
        backup_dir = self._get_backup_dir(server_name)
        if not backup_dir or not backup_dir.exists():
            return []

        backups = []
        for file in backup_dir.glob("*.zip"):
            try:
                stat = file.stat()
                backups.append(
                    {"filename": file.name, "path": str(file), "size": stat.st_size, "created_at": stat.st_mtime}
                )
            except Exception as e:
                logger.warning(f"無法讀取備份檔案資訊 {file}: {e}")

        # 依建立時間排序，新的在前面
        backups.sort(key=lambda x: float(str(x["created_at"])), reverse=True)
        return backups

    def restore_backup(self, server_name: str, backup_filename: str) -> ServerOperationResult:
        """
        還原伺服器備份。

        Args:
            server_name: 伺服器名稱
            backup_filename: 備份檔案名稱

        Returns:
            ServerOperationResult: 還原結果
        """
        config = self.startup.get_server_info(server_name)
        if not config or not config.get("path"):
            return self._failure_result("還原失敗", "找不到伺服器配置或路徑", server_name=server_name)

        server_path = PathUtils.get_app_path(str(config["path"]))
        original_backup_dir = self._get_backup_dir(server_name)
        if not original_backup_dir:
            return self._failure_result("還原失敗", "無法決定備份目錄", server_name=server_name)

        backup_path = original_backup_dir / backup_filename
        if not backup_path.exists():
            return self._failure_result("還原失敗", f"找不到備份檔案: {backup_filename}", server_name=server_name)

        try:
            logger.info(f"開始還原 {server_name} 從 {backup_path}")

            is_internal_backup = False
            # 判斷備份目錄是否在伺服器目錄內部
            with contextlib.suppress(ValueError):
                if original_backup_dir.is_relative_to(server_path):
                    is_internal_backup = True

            old_dir = None
            if server_path.exists():
                old_dir = server_path.with_name(f"{server_path.name}_old_{int(time.time())}")
                server_path.rename(old_dir)

                if is_internal_backup:
                    # 原本的備份檔現在已經在 old_dir 裡了，所以要更新路徑
                    rel_path = backup_path.relative_to(server_path)
                    backup_path = old_dir / rel_path
                    backup_dir = old_dir / original_backup_dir.relative_to(server_path)
                else:
                    backup_dir = original_backup_dir
            else:
                backup_dir = original_backup_dir

            server_path.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(backup_path, "r") as zipf:
                zipf.extractall(server_path)

            # 若備份目錄原本在伺服器目錄內，將其從 old_dir 移回新還原的伺服器目錄中
            if is_internal_backup and old_dir and backup_dir.exists():
                new_backup_dir = server_path / original_backup_dir.relative_to(server_path)
                new_backup_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(backup_dir), str(new_backup_dir))

            return self._success_result(f"成功從 {backup_filename} 還原", server_name=server_name)
        except Exception as e:
            logger.error(f"還原伺服器 {server_name} 失敗: {e}", exc_info=True)
            record_and_mark(f"restore_{server_name}", e)
            return self._failure_result("還原失敗", f"發生錯誤: {e}", server_name=server_name)
