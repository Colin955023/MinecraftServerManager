"""模組變更備份與回滾機制。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...models import ModFileOperationResult
from ...utils import PathUtils


class ModRollback:
    """處理模組變更時的檔案回滾與備份還原。"""

    def __init__(self, server_path: Path, logger: Any) -> None:
        self.server_path = server_path
        self.logger = logger

    def restore_backup_to_path(self, original_path: Path | None, backup_path: Path | None) -> bool:
        """
        將備份檔案還原回原始路徑。

        Args:
            original_path: 原始檔案路徑。
            backup_path: 備份檔案路徑。

        Returns:
            還原成功時回傳 True，否則回傳 False。
        """

        if original_path is None or backup_path is None or not backup_path.exists():
            return False
        restored = PathUtils.replace_within(self.server_path, backup_path, original_path)
        if not restored:
            self.logger.warning(f"回滾失敗：無法還原備份檔案到 {original_path}", "ModRollback")
        return restored

    def rollback_replaced_mod_file(
        self,
        *,
        old_path: Path | None,
        installed_path: Path | None,
        final_path: Path | None,
        backup_path: Path | None,
        cancelled: bool,
        operation_name: str,
    ) -> ModFileOperationResult:
        """
        回滾已寫入的新模組檔案與舊檔備份。

        Args:
            old_path: 舊模組檔案路徑。
            installed_path: 新下載檔案路徑。
            final_path: 最終生效檔案路徑。
            backup_path: 舊檔備份路徑。
            cancelled: 是否因取消而回滾。
            operation_name: 目前作業名稱。

        Returns:
            描述回滾結果的檔案操作結果物件。
        """

        rollback_performed = False
        for candidate_path in (final_path, installed_path):
            if candidate_path is None or not candidate_path.exists():
                continue
            if PathUtils.delete_within(self.server_path, candidate_path):
                rollback_performed = True
        if self.restore_backup_to_path(old_path, backup_path):
            rollback_performed = True
        action_text = "取消" if cancelled else "失敗"
        self.logger.warning(f"{operation_name}{action_text}，已嘗試回滾新檔案與舊版本狀態", "ModRollback")
        return ModFileOperationResult(
            status="cancelled" if cancelled else "failed",
            rollback_performed=rollback_performed,
            message=action_text,
        )
