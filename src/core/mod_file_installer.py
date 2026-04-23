"""模組檔案安裝與本地異動 helper。"""

from __future__ import annotations

import contextlib
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..utils import HTTPUtils, PathUtils, build_non_official_source_warning, record_and_mark
from .mod_models import LocalModInfo, LocalModMutationResult, ModFileOperationResult, ModStatus


class ModFileInstaller:
    """處理模組檔案寫入、替換、回滾與本地刪改。"""

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

    @staticmethod
    def success_mutation_result(
        message: str = "",
        *,
        final_path: Path | None = None,
        affected_count: int = 0,
    ) -> LocalModMutationResult:
        """建立成功的本地模組異動結果。

        Args:
            message: 結果訊息。
            final_path: 異動後的最終檔案路徑。
            affected_count: 受影響的檔案數量。

        Returns:
            表示成功的本地模組異動結果物件。
        """

        return LocalModMutationResult(
            status="completed",
            message=message,
            final_path=final_path,
            affected_count=affected_count,
        )

    @staticmethod
    def failure_mutation_result(
        title: str,
        message: str,
        *,
        missing_ids: tuple[str, ...] = (),
    ) -> LocalModMutationResult:
        """建立失敗的本地模組異動結果。

        Args:
            title: 失敗標題。
            message: 失敗訊息。
            missing_ids: 找不到的模組識別值。

        Returns:
            表示失敗的本地模組異動結果物件。
        """

        return LocalModMutationResult(
            status="failed",
            title=title,
            message=message,
            missing_ids=missing_ids,
        )

    @staticmethod
    def normalize_expected_hash(expected_hash: str | None) -> tuple[str, str]:
        """依雜湊長度推斷可接受的演算法。

        Args:
            expected_hash: 原始預期雜湊字串。

        Returns:
            正規化後的雜湊字串與演算法名稱；無法判定時演算法為空字串。
        """

        normalized_hash = str(expected_hash or "").strip().lower()
        if not normalized_hash:
            return ("", "")
        if len(normalized_hash) == 64:
            return (normalized_hash, "sha256")
        if len(normalized_hash) == 128:
            return (normalized_hash, "sha512")
        return (normalized_hash, "")

    def notify_mod_list_changed(self) -> None:
        """在主執行緒中觸發模組列表變更通知。"""

        if self.on_mod_list_changed and threading.current_thread() is threading.main_thread():
            self.on_mod_list_changed()

    def is_operation_cancelled(self, cancel_check: Callable[[], bool] | None) -> bool:
        """安全地檢查目前作業是否被取消。

        Args:
            cancel_check: 取消檢查回呼。

        Returns:
            若作業應取消則回傳 True，否則回傳 False。
        """

        if cancel_check is None:
            return False
        try:
            return bool(cancel_check())
        except Exception as exc:
            self.logger.exception(f"取消檢查回呼失敗: {exc}")
            return False

    def restore_backup_to_path(self, original_path: Path | None, backup_path: Path | None) -> bool:
        """將備份檔案還原回原始路徑。

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
            self.logger.warning(f"回滾失敗：無法還原備份檔案到 {original_path}", "ModFileInstaller")
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
        """回滾已寫入的新模組檔案與舊檔備份。

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
        self.logger.warning(f"{operation_name}{action_text}，已嘗試回滾新檔案與舊版本狀態", "ModFileInstaller")
        return ModFileOperationResult(
            status="cancelled" if cancelled else "failed",
            rollback_performed=rollback_performed,
            message=action_text,
        )

    def install_remote_mod_file_result(
        self,
        *,
        download_url: str,
        filename: str,
        progress_callback: Callable[[int, int], None] | None = None,
        expected_hash: str | None = None,
        provider: str | None = "modrinth",
        cancel_check: Callable[[], bool] | None = None,
        notify_change: bool = True,
    ) -> ModFileOperationResult:
        """下載遠端模組並以原子方式安裝到 `mods` 目錄。

        Args:
            download_url: 遠端檔案下載網址。
            filename: 要寫入的模組檔名。
            progress_callback: 可選的下載進度回呼。
            expected_hash: 預期檔案雜湊，需為 SHA-256 或 SHA-512。
            provider: 下載來源 provider 名稱。
            cancel_check: 可選的取消檢查回呼。
            notify_change: 成功後是否通知模組列表更新。

        Returns:
            描述安裝結果的檔案操作結果物件。
        """

        normalized_url = str(download_url or "").strip()
        normalized_filename = str(filename or "").strip()
        if not normalized_url or not normalized_filename:
            self.logger.error("安裝遠端模組失敗：download_url 或 filename 為空", "ModFileInstaller")
            return ModFileOperationResult(status="failed", message="missing_url_or_filename")
        safe_filename = Path(normalized_filename).name
        if not safe_filename.lower().endswith(".jar"):
            self.logger.error(f"安裝遠端模組失敗：不支援的檔案類型 {safe_filename}", "ModFileInstaller")
            return ModFileOperationResult(status="failed", message="unsupported_file_type")
        non_official_warning = build_non_official_source_warning(normalized_url, provider)
        if non_official_warning:
            self.logger.warning(non_official_warning, "ModFileInstaller")
        if self.is_operation_cancelled(cancel_check):
            self.logger.info(f"遠端模組安裝在下載前已取消: {safe_filename}", "ModFileInstaller")
            return ModFileOperationResult(status="cancelled", message="cancelled_before_download")
        try:
            target_path = self.mods_path / safe_filename
            normalized_expected_hash, expected_hash_algorithm = self.normalize_expected_hash(expected_hash)
            if not normalized_expected_hash:
                self.logger.error(
                    f"安裝遠端模組失敗：缺少 SHA-256 以上的預期雜湊，拒絕下載 {safe_filename}",
                    "ModFileInstaller",
                )
                return ModFileOperationResult(status="failed", message="missing_secure_hash")
            if normalized_expected_hash and not expected_hash_algorithm:
                self.logger.error(
                    f"安裝遠端模組失敗：僅接受 SHA-256 / SHA-512 雜湊（長度 {len(normalized_expected_hash)}）",
                    "ModFileInstaller",
                )
                return ModFileOperationResult(status="failed", message="unsupported_hash_algorithm")
            if normalized_expected_hash and target_path.exists():
                current_hash = PathUtils.calculate_checksum(target_path, expected_hash_algorithm)
                if current_hash and current_hash == normalized_expected_hash:
                    if progress_callback:
                        try:
                            size = target_path.stat().st_size
                            progress_callback(size, size)
                        except OSError as exc:
                            self.logger.exception(f"更新進度回呼時發生錯誤: {exc}")
                    self.logger.info(f"遠端模組已存在且雜湊一致，略過下載: {safe_filename}", "ModFileInstaller")
                    return ModFileOperationResult(status="completed", final_path=target_path)
            verification_note = f"，含雜湊驗證({expected_hash_algorithm})" if normalized_expected_hash else ""
            self.logger.info(
                f"開始下載遠端模組: {safe_filename} -> {target_path}{verification_note}", "ModFileInstaller"
            )
            with tempfile.TemporaryDirectory(prefix=f"{safe_filename}.", dir=self.download_staging_root) as staging_dir:
                staging_path = Path(staging_dir) / safe_filename
                download_kwargs: dict[str, Any] = {"progress_callback": progress_callback}
                if normalized_expected_hash:
                    download_kwargs["expected_hash"] = normalized_expected_hash
                if cancel_check is not None:
                    download_kwargs["cancel_check"] = cancel_check
                downloaded = HTTPUtils.download_file(normalized_url, str(staging_path), **download_kwargs)
                if not downloaded:
                    if self.is_operation_cancelled(cancel_check):
                        self.logger.info(f"遠端模組下載已取消: {safe_filename}", "ModFileInstaller")
                        return ModFileOperationResult(status="cancelled", message="cancelled_during_download")
                    self.logger.warning(f"遠端模組下載未完成: {safe_filename}", "ModFileInstaller")
                    return ModFileOperationResult(status="failed", message="download_incomplete")
                if self.is_operation_cancelled(cancel_check):
                    PathUtils.delete_within(self.server_path, staging_path)
                    self.logger.info(f"遠端模組安裝在寫入前已取消: {safe_filename}", "ModFileInstaller")
                    return ModFileOperationResult(status="cancelled", message="cancelled_before_replace")
                if not PathUtils.replace_within(self.server_path, staging_path, target_path):
                    self.logger.warning(f"遠端模組無法原子寫入目標路徑: {safe_filename}", "ModFileInstaller")
                    return ModFileOperationResult(status="failed", message="replace_failed")
            if self.is_operation_cancelled(cancel_check):
                rolled_back = PathUtils.delete_within(self.server_path, target_path)
                self.logger.info(f"遠端模組安裝在寫入後已取消，已回滾: {safe_filename}", "ModFileInstaller")
                return ModFileOperationResult(
                    status="cancelled",
                    rollback_performed=rolled_back,
                    message="cancelled_after_replace",
                )
            if notify_change:
                self.notify_mod_list_changed()
            self.logger.info(f"遠端模組安裝完成: {safe_filename}", "ModFileInstaller")
            return ModFileOperationResult(status="completed", final_path=target_path)
        except (OSError, ValueError) as exc:
            self.logger.exception(f"安裝遠端模組失敗（IO/參數） {safe_filename}: {exc}")
            return ModFileOperationResult(status="failed", message=str(exc))
        except Exception as exc:
            with contextlib.suppress(Exception):
                record_and_mark(
                    exc,
                    marker_path=target_path if "target_path" in locals() else None,
                    reason="install_remote_mod_file_unexpected",
                    details={"filename": safe_filename, "url": normalized_url},
                )
            self.logger.exception(f"安裝遠端模組失敗 {safe_filename}: {exc}")
            return ModFileOperationResult(status="failed", message=str(exc))

    def replace_local_mod_file(
        self,
        *,
        local_mod: LocalModInfo,
        download_url: str,
        filename: str,
        install_remote_mod_file_result: Callable[..., ModFileOperationResult],
        progress_callback: Callable[[int, int], None] | None = None,
        expected_hash: str | None = None,
        provider: str | None = "modrinth",
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path | None:
        """以遠端版本覆蓋既有本地模組，必要時自動回滾。

        Args:
            local_mod: 既有本地模組資訊。
            download_url: 新版本下載網址。
            filename: 新版本檔名。
            install_remote_mod_file_result: 實際執行遠端安裝的回呼。
            progress_callback: 可選的下載進度回呼。
            expected_hash: 預期檔案雜湊，需為 SHA-256 或 SHA-512。
            provider: 下載來源 provider 名稱。
            cancel_check: 可選的取消檢查回呼。

        Returns:
            更新成功時回傳最終檔案路徑，失敗時回傳 None。
        """

        if local_mod is None:
            self.logger.error("更新本地模組失敗：local_mod 為空", "ModFileInstaller")
            return None
        old_path_raw = str(getattr(local_mod, "file_path", "") or "").strip()
        old_path = Path(old_path_raw).resolve(strict=False) if old_path_raw else None
        old_path_is_internal = bool(
            old_path and old_path.exists() and PathUtils.is_path_within(self.server_path, old_path, strict=False)
        )
        backup_context: tempfile.TemporaryDirectory[str] | None = None
        backup_path: Path | None = None

        def cleanup_backup_context() -> None:
            if backup_context is not None:
                backup_context.cleanup()

        def rollback_and_stop(cancelled: bool, final_path: Path | None = None) -> None:
            self.rollback_replaced_mod_file(
                old_path=old_path,
                installed_path=final_path,
                final_path=final_path,
                backup_path=backup_path,
                cancelled=cancelled,
                operation_name="replace_local_mod_file",
            )
            cleanup_backup_context()

        try:
            if old_path_is_internal:
                if old_path is None:
                    self.logger.error("更新本地模組失敗：old_path 狀態異常", "ModFileInstaller")
                    return None
                backup_context = tempfile.TemporaryDirectory(
                    prefix=f"replace-backup-{Path(filename).name}.",
                    dir=self.download_staging_root,
                )
                backup_path = Path(backup_context.name) / old_path.name
                if not PathUtils.copy_file(old_path, backup_path):
                    self.logger.error(f"更新本地模組失敗：無法建立回滾備份 {old_path}", "ModFileInstaller")
                    backup_context.cleanup()
                    return None
            install_result = install_remote_mod_file_result(
                download_url=download_url,
                filename=filename,
                progress_callback=progress_callback,
                expected_hash=expected_hash,
                provider=provider,
                cancel_check=cancel_check,
                notify_change=False,
            )
            if not install_result.completed or not install_result.final_path:
                rollback_and_stop(cancelled=False)
                return None
            final_path = install_result.final_path
            if getattr(local_mod, "status", None) == ModStatus.DISABLED and final_path.suffix == ".jar":
                disabled_path = final_path.with_name(final_path.name + ".disabled")
                PathUtils.delete_within(self.server_path, disabled_path)
                final_path.rename(disabled_path)
                final_path = disabled_path
            if self.is_operation_cancelled(cancel_check):
                rollback_and_stop(cancelled=True, final_path=final_path)
                return None
            if old_path and old_path != final_path.resolve(strict=False) and old_path.exists():
                if PathUtils.is_path_within(self.server_path, old_path, strict=False):
                    if not PathUtils.delete_within(self.server_path, old_path):
                        rollback_and_stop(cancelled=False, final_path=final_path)
                        return None
                else:
                    self.logger.warning(f"略過刪除不在伺服器目錄內的舊模組檔案: {old_path}")
            if self.is_operation_cancelled(cancel_check):
                rollback_and_stop(cancelled=True, final_path=final_path)
                return None
            self.notify_mod_list_changed()
            cleanup_backup_context()
            return final_path
        except (OSError, ValueError) as exc:
            rollback_and_stop(cancelled=False)
            self.logger.exception(f"更新本地模組失敗（IO/參數） {getattr(local_mod, 'filename', 'unknown')}: {exc}")
            return None
        except Exception as exc:
            rollback_and_stop(cancelled=False)
            with contextlib.suppress(Exception):
                record_and_mark(
                    exc,
                    marker_path=None,
                    reason="replace_local_mod_file_unexpected",
                    details={"local_mod_filename": getattr(local_mod, "filename", None)},
                )
            self.logger.exception(f"更新本地模組失敗 {getattr(local_mod, 'filename', 'unknown')}: {exc}")
            return None

    def set_mod_state_result(self, mod_id: str, enable: bool) -> LocalModMutationResult:
        """切換本地模組的啟用或停用狀態。

        Args:
            mod_id: 模組識別值，不含副檔名。
            enable: `True` 表示啟用，`False` 表示停用。

        Returns:
            描述啟停結果的本地模組異動結果物件。
        """

        action = "啟用" if enable else "停用"
        try:
            safe_mod_id = Path(str(mod_id or "")).name
            if not safe_mod_id:
                self.logger.error(f"無效的模組識別字串: {mod_id}")
                return self.failure_mutation_result(f"{action}失敗", f"無效的模組識別字串: {mod_id}")
            if safe_mod_id != str(mod_id):
                self.logger.warning(f"淨化不安全的 mod_id: {mod_id} -> {safe_mod_id}")
            mod_id = safe_mod_id
            enabled_file = self.mods_path / f"{mod_id}.jar"
            disabled_file = self.mods_path / f"{mod_id}.jar.disabled"
            if not PathUtils.is_path_within(self.mods_path, enabled_file, strict=False):
                self.logger.error(f"模組路徑不在 mods 目錄內: {enabled_file}")
                return self.failure_mutation_result(f"{action}失敗", f"模組路徑不在 mods 目錄內: {enabled_file}")
            if enable:
                src_file = disabled_file
                dst_file = enabled_file
                conflict_bak_suffix = "disabled"
            else:
                src_file = enabled_file
                dst_file = disabled_file
                conflict_bak_suffix = "enabled"
            if dst_file.exists() and not src_file.exists():
                return self.success_mutation_result(
                    f"模組已處於目標狀態: {dst_file.name}",
                    final_path=dst_file,
                    affected_count=1,
                )
            if dst_file.exists() and src_file.exists():
                try:
                    same_size = dst_file.stat().st_size == src_file.stat().st_size
                except OSError:
                    same_size = False
                if same_size:
                    src_file.unlink(missing_ok=True)
                    return self.success_mutation_result(
                        f"模組已處於目標狀態並已清理重複檔案: {dst_file.name}",
                        final_path=dst_file,
                        affected_count=1,
                    )
                bak = self.mods_path / f"{mod_id}.{conflict_bak_suffix}.bak"
                if bak.exists():
                    bak = self.mods_path / f"{mod_id}.{conflict_bak_suffix}.{int(time.time())}.bak"
                src_file.rename(bak)
                return self.success_mutation_result(
                    f"偵測到衝突檔案，已改名保留備份: {bak.name}",
                    final_path=bak,
                    affected_count=1,
                )
            if src_file.exists():
                src_file.rename(dst_file)
                self.notify_mod_list_changed()
                return self.success_mutation_result(
                    f"已{action}模組: {dst_file.name}",
                    final_path=dst_file,
                    affected_count=1,
                )
            return self.failure_mutation_result(
                f"{action}失敗",
                f"找不到對應的模組檔案: {src_file.name}",
                missing_ids=(mod_id,),
            )
        except (OSError, PermissionError) as exc:
            self.logger.error(f"{action}模組失敗（IO/權限）: {exc}", "ModFileInstaller")
            return self.failure_mutation_result(f"{action}失敗", f"{action}模組失敗: {exc}")
        except Exception as exc:
            with contextlib.suppress(Exception):
                record_and_mark(
                    exc,
                    marker_path=None,
                    reason="set_mod_state_unexpected",
                    details={"mod": mod_id},
                )
            self.logger.exception(f"{action}模組時發生未預期錯誤: {exc}")
            return self.failure_mutation_result(f"{action}失敗", f"{action}模組失敗: {exc}")

    def import_local_mod_file_result(self, source_path: str | Path) -> LocalModMutationResult:
        """匯入本地模組檔案到目前伺服器的 `mods` 目錄。

        Args:
            source_path: 要匯入的本地模組檔案路徑。

        Returns:
            描述匯入結果的本地模組異動結果物件。
        """

        try:
            normalized_source = Path(source_path).expanduser().resolve(strict=False)
        except Exception as exc:
            return self.failure_mutation_result("匯入失敗", f"無法解析模組檔案路徑: {exc}")
        if not normalized_source.exists() or not normalized_source.is_file():
            return self.failure_mutation_result("匯入失敗", f"找不到模組檔案: {normalized_source}")
        safe_filename = normalized_source.name
        if not safe_filename.lower().endswith(".jar"):
            return self.failure_mutation_result("匯入失敗", f"不支援的模組檔案類型: {safe_filename}")
        try:
            target_path = self.mods_path / safe_filename
            with tempfile.TemporaryDirectory(prefix=f"{safe_filename}.", dir=self.download_staging_root) as staging_dir:
                staging_path = Path(staging_dir) / safe_filename
                if not PathUtils.copy_file(normalized_source, staging_path):
                    return self.failure_mutation_result("匯入失敗", f"無法複製模組檔案: {normalized_source}")
                if not PathUtils.replace_within(self.server_path, staging_path, target_path):
                    return self.failure_mutation_result("匯入失敗", f"無法寫入目標模組檔案: {target_path}")
            self.notify_mod_list_changed()
            return self.success_mutation_result(
                f"模組已匯入: {safe_filename}",
                final_path=target_path,
                affected_count=1,
            )
        except Exception as exc:
            with contextlib.suppress(Exception):
                record_and_mark(
                    exc,
                    marker_path=self.mods_path / safe_filename,
                    reason="import_local_mod_file_failed",
                    details={"source_path": str(normalized_source)},
                )
            self.logger.exception(f"匯入本地模組失敗 {safe_filename}: {exc}")
            return self.failure_mutation_result("匯入失敗", f"匯入模組失敗: {exc}")

    def delete_local_mods_result(self, mod_ids: list[str] | tuple[str, ...]) -> LocalModMutationResult:
        """刪除一或多個本地模組檔案。

        Args:
            mod_ids: 要刪除的模組識別值列表。

        Returns:
            描述刪除結果的本地模組異動結果物件。
        """

        normalized_ids: list[str] = []
        seen_ids: set[str] = set()
        for mod_id in mod_ids:
            safe_mod_id = Path(str(mod_id or "")).name
            if not safe_mod_id or safe_mod_id in seen_ids:
                continue
            seen_ids.add(safe_mod_id)
            normalized_ids.append(safe_mod_id)
        if not normalized_ids:
            return self.failure_mutation_result("刪除失敗", "沒有可刪除的模組識別值。")
        deleted_count = 0
        missing_ids: list[str] = []
        try:
            for mod_id in normalized_ids:
                deleted = False
                for ext in (".jar", ".jar.disabled"):
                    target_path = self.mods_path / f"{mod_id}{ext}"
                    if not target_path.exists():
                        continue
                    if not PathUtils.delete_within(self.server_path, target_path):
                        return self.failure_mutation_result("刪除失敗", f"無法刪除模組檔案: {target_path}")
                    deleted = True
                    deleted_count += 1
                    break
                if not deleted:
                    missing_ids.append(mod_id)
            if deleted_count > 0:
                self.notify_mod_list_changed()
            if deleted_count > 0 and not missing_ids:
                return self.success_mutation_result(f"已刪除 {deleted_count} 個模組檔案", affected_count=deleted_count)
            if deleted_count > 0 and missing_ids:
                return LocalModMutationResult(
                    status="partial",
                    title="部分刪除成功",
                    message=f"已刪除 {deleted_count} 個模組檔案，但仍有 {len(missing_ids)} 個找不到對應檔案。",
                    affected_count=deleted_count,
                    missing_ids=tuple(missing_ids),
                )
            return self.failure_mutation_result(
                "刪除失敗",
                "找不到任何可刪除的模組檔案。",
                missing_ids=tuple(missing_ids),
            )
        except Exception as exc:
            with contextlib.suppress(Exception):
                record_and_mark(
                    exc,
                    marker_path=self.mods_path,
                    reason="delete_local_mods_failed",
                    details={"mod_ids": normalized_ids},
                )
            self.logger.exception(f"刪除本地模組失敗 {normalized_ids}: {exc}")
            return self.failure_mutation_result("刪除失敗", f"刪除模組失敗: {exc}")
