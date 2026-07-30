"""模組檔案安裝與本地異動 helper。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...models import LocalModInfo, LocalModMutationResult, ModFileOperationResult
from ...utils import PathUtils
from .mod_download import ModDownload
from .mod_install_atomic import ModInstallAtomic
from .mod_rollback import ModRollback


class ModFileInstaller:
    """處理模組檔案寫入、替換、回滾與本地刪改 (Facade 模式)。"""

    def __init__(
        self,
        *,
        server_path: Path,
        mods_path: Path,
        download_staging_root: Path,
        on_mod_list_changed: Callable | None,
        logger: Any,
    ) -> None:
        self.server_path = server_path
        self.mods_path = mods_path
        self.download_staging_root = download_staging_root
        self.on_mod_list_changed = on_mod_list_changed
        self.logger = logger

        # 實例化子模組
        self.rollback = ModRollback(server_path=server_path, logger=logger)
        self.download = ModDownload(
            server_path=server_path,
            mods_path=mods_path,
            download_staging_root=download_staging_root,
            logger=logger,
            on_mod_list_changed=on_mod_list_changed,
        )
        self.atomic = ModInstallAtomic(
            server_path=server_path,
            mods_path=mods_path,
            download_staging_root=download_staging_root,
            logger=logger,
            mod_rollback=self.rollback,
            on_mod_list_changed=on_mod_list_changed,
        )

    # 委派靜態工廠方法
    @staticmethod
    def success_mutation_result(
        message: str = "",
        *,
        final_path: Path | None = None,
        affected_count: int = 0,
    ) -> LocalModMutationResult:
        """
        建立成功的本地模組異動結果。

        Args:
            message: 結果訊息。
            final_path: 異動後的最終檔案路徑。
            affected_count: 受影響的檔案數量。

        Returns:
            表示成功的本地模組異動結果物件。
        """
        return ModInstallAtomic.success_mutation_result(
            message=message, final_path=final_path, affected_count=affected_count
        )

    @staticmethod
    def failure_mutation_result(
        title: str,
        message: str,
        *,
        missing_ids: tuple[str, ...] = (),
    ) -> LocalModMutationResult:
        """
        建立失敗的本地模組異動結果。

        Args:
            title: 失敗標題。
            message: 失敗訊息。
            missing_ids: 找不到的模組識別值。

        Returns:
            表示失敗的本地模組異動結果物件。
        """
        return ModInstallAtomic.failure_mutation_result(title=title, message=message, missing_ids=missing_ids)

    @staticmethod
    def normalize_expected_hash(expected_hash: str | None) -> tuple[str, str]:
        """
        依雜湊長度推斷可接受的演算法。

        Args:
            expected_hash: 原始預期雜湊字串。

        Returns:
            正規化後的雜湊字串與演算法名稱；無法判定時演算法為空字串。
        """
        return ModDownload.normalize_expected_hash(expected_hash)

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
        return self.rollback.rollback_replaced_mod_file(
            old_path=old_path,
            installed_path=installed_path,
            final_path=final_path,
            backup_path=backup_path,
            cancelled=cancelled,
            operation_name=operation_name,
        )

    def replace_local_mod_file(
        self,
        *,
        local_mod: LocalModInfo,
        download_url: str,
        filename: str,
        progress_callback: Callable[[int, int], None] | None = None,
        expected_hash: str | None = None,
        provider: str | None = "modrinth",
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path | None:
        """
        以遠端版本覆蓋既有本地模組，必要時自動回滾。

        Args:
            local_mod: 既有本地模組資訊。
            download_url: 新版本下載網址。
            filename: 新版本檔名。
            progress_callback: 可選的下載進度回呼。
            expected_hash: 預期檔案雜湊，需為 SHA-256 或 SHA-512。
            provider: 下載來源 provider 名稱。
            cancel_check: 可選的取消檢查回呼。

        Returns:
            更新成功時回傳最終檔案路徑，失敗時回傳 None。
        """
        old_path = Path(local_mod.file_path)
        is_disabled = old_path.name.endswith(".disabled")
        target_filename = filename + (".disabled" if is_disabled else "")

        backup_path = None
        if old_path.exists():
            import shutil

            backup_path = old_path.with_name(old_path.name + ".bak")
            try:
                shutil.copy2(old_path, backup_path)
            except Exception:
                return None

        try:
            result = self.download.install_remote_mod_file_result(
                download_url=download_url,
                filename=target_filename,
                progress_callback=progress_callback,
                expected_hash=expected_hash,
                provider=provider,
                cancel_check=cancel_check,
                notify_change=False,
            )
        except Exception:
            result = None

        cancelled = cancel_check() if cancel_check else False

        if not result or not result.completed or cancelled:
            self.rollback.rollback_replaced_mod_file(
                old_path=old_path,
                installed_path=result.final_path if result else None,
                final_path=old_path,
                backup_path=backup_path,
                cancelled=cancelled,
                operation_name="替換模組",
            )
            if backup_path and backup_path.exists():
                backup_path.unlink(missing_ok=True)
            return None

        if backup_path and backup_path.exists():
            backup_path.unlink(missing_ok=True)
        if old_path.exists() and old_path != result.final_path:
            # 只有在 mods 目錄內的檔案才會被刪除，並檢查是否刪除成功
            is_internal = PathUtils.is_path_within(self.mods_path, old_path)
            if is_internal:
                success = PathUtils.delete_within(self.mods_path, old_path)
                if not success:
                    self.rollback.rollback_replaced_mod_file(
                        old_path=old_path,
                        installed_path=result.final_path,
                        final_path=old_path,
                        backup_path=backup_path,
                        cancelled=False,
                        operation_name="替換模組",
                    )
                    if backup_path and backup_path.exists():
                        backup_path.unlink(missing_ok=True)
                    return None

        return result.final_path

    def set_mod_state_result(self, mod_id: str, enable: bool) -> LocalModMutationResult:
        """
        切換本地模組的啟用或停用狀態。

        Args:
            mod_id: 模組識別值，不含副檔名。
            enable: `True` 表示啟用，`False` 表示停用。

        Returns:
            描述啟停結果的本地模組異動結果物件。
        """
        return self.atomic.set_mod_state_result(mod_id=mod_id, enable=enable)

    def import_local_mod_file_result(self, source_path: str | Path) -> LocalModMutationResult:
        """
        匯入本地模組檔案到目前伺服器的 `mods` 目錄。

        Args:
            source_path: 要匯入的本地模組檔案路徑。

        Returns:
            描述匯入結果的本地模組異動結果物件。
        """
        return self.atomic.import_local_mod_file_result(source_path=source_path)

    def delete_local_mods_result(self, mod_ids: list[str] | tuple[str, ...]) -> LocalModMutationResult:
        """
        刪除一或多個本地模組檔案。

        Args:
            mod_ids: 要刪除的模組識別值列表。

        Returns:
            描述刪除結果的本地模組異動結果物件。
        """
        return self.atomic.delete_local_mods_result(mod_ids=mod_ids)
