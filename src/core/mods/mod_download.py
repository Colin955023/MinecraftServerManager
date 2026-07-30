"""模組檔案下載與雜湊驗證。"""

from __future__ import annotations

import contextlib
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...models import ModFileOperationResult
from ...utils import HTTPUtils, PathUtils, build_non_official_source_warning, record_and_mark
from .mod_op_utils import is_operation_cancelled, notify_mod_list_changed


class ModDownload:
    """處理遠端模組的網路下載與安全校驗。"""

    def __init__(
        self,
        server_path: Path,
        mods_path: Path,
        download_staging_root: Path,
        logger: Any,
        on_mod_list_changed: Callable | None = None,
    ) -> None:
        self.server_path = server_path
        self.mods_path = mods_path
        self.download_staging_root = download_staging_root
        self.logger = logger
        self.on_mod_list_changed = on_mod_list_changed

    @staticmethod
    def normalize_expected_hash(expected_hash: str | None) -> tuple[str, str]:
        """
        依雜湊長度推斷可接受的演算法。

        Args:
            expected_hash: 原始預期雜湊字串。

        Returns:
            正規化後的雜湊字串與演算法名稱；無法判定時演算法為空字串。
        """

        normalized_hash = str(expected_hash or "").strip().lower()
        if not normalized_hash:
            return ("", "")
        if len(normalized_hash) == 40:
            return (normalized_hash, "sha1")
        if len(normalized_hash) == 64:
            return (normalized_hash, "sha256")
        if len(normalized_hash) == 128:
            return (normalized_hash, "sha512")
        return (normalized_hash, "")

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
        """
        下載遠端模組並以原子方式安裝到 `mods` 目錄。

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
            self.logger.error("安裝遠端模組失敗：download_url 或 filename 為空", "ModDownload")
            return ModFileOperationResult(status="failed", message="missing_url_or_filename")
        safe_filename = Path(normalized_filename).name
        if not safe_filename.lower().endswith(".jar"):
            self.logger.error(f"安裝遠端模組失敗：不支援的檔案類型 {safe_filename}", "ModDownload")
            return ModFileOperationResult(status="failed", message="unsupported_file_type")
        non_official_warning = build_non_official_source_warning(normalized_url, provider)
        if non_official_warning:
            self.logger.warning(non_official_warning, "ModDownload")
        if is_operation_cancelled(cancel_check, self.logger):
            self.logger.info(f"遠端模組安裝在下載前已取消: {safe_filename}", "ModDownload")
            return ModFileOperationResult(status="cancelled", message="cancelled_before_download")
        try:
            target_path = self.mods_path / safe_filename
            normalized_expected_hash, expected_hash_algorithm = self.normalize_expected_hash(expected_hash)
            if not normalized_expected_hash:
                self.logger.error(
                    f"安裝遠端模組失敗：缺少預期雜湊，拒絕下載 {safe_filename}",
                    "ModDownload",
                )
                return ModFileOperationResult(status="failed", message="missing_secure_hash")
            if normalized_expected_hash and not expected_hash_algorithm:
                self.logger.error(
                    f"安裝遠端模組失敗：無法辨識的雜湊演算法（長度 {len(normalized_expected_hash)}）",
                    "ModDownload",
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
                    self.logger.info(f"遠端模組已存在且雜湊一致，略過下載: {safe_filename}", "ModDownload")
                    return ModFileOperationResult(status="completed", final_path=target_path)
            verification_note = f"，含雜湊驗證({expected_hash_algorithm})" if normalized_expected_hash else ""
            self.logger.info(f"開始下載遠端模組: {safe_filename} -> {target_path}{verification_note}", "ModDownload")
            with tempfile.TemporaryDirectory(prefix=f"{safe_filename}.", dir=self.download_staging_root) as staging_dir:
                staging_path = Path(staging_dir) / safe_filename
                download_failure_reason = ""

                def _capture_download_failure(message: str) -> None:
                    nonlocal download_failure_reason
                    download_failure_reason = message

                download_kwargs: dict[str, Any] = {
                    "progress_callback": progress_callback,
                    "failure_message_callback": _capture_download_failure,
                }
                if normalized_expected_hash:
                    download_kwargs["expected_hash"] = normalized_expected_hash
                if cancel_check is not None:
                    download_kwargs["cancel_check"] = cancel_check
                downloaded = HTTPUtils.download_file(normalized_url, str(staging_path), **download_kwargs)
                if not downloaded:
                    if is_operation_cancelled(cancel_check, self.logger):
                        self.logger.info(f"遠端模組下載已取消: {safe_filename}", "ModDownload")
                        return ModFileOperationResult(status="cancelled", message="cancelled_during_download")
                    failure_message = download_failure_reason or "download_incomplete"
                    self.logger.warning(f"遠端模組下載未完成: {safe_filename} | {failure_message}", "ModDownload")
                    return ModFileOperationResult(status="failed", message=failure_message)
                if is_operation_cancelled(cancel_check, self.logger):
                    PathUtils.delete_within(self.server_path, staging_path)
                    self.logger.info(f"遠端模組安裝在寫入前已取消: {safe_filename}", "ModDownload")
                    return ModFileOperationResult(status="cancelled", message="cancelled_before_replace")
                if not PathUtils.replace_within(self.server_path, staging_path, target_path):
                    self.logger.warning(f"遠端模組無法原子寫入目標路徑: {safe_filename}", "ModDownload")
                    return ModFileOperationResult(status="failed", message="replace_failed")
            if is_operation_cancelled(cancel_check, self.logger):
                rolled_back = PathUtils.delete_within(self.server_path, target_path)
                self.logger.info(f"遠端模組安裝在寫入後已取消，已回滾: {safe_filename}", "ModDownload")
                return ModFileOperationResult(
                    status="cancelled",
                    rollback_performed=rolled_back,
                    message="cancelled_after_replace",
                )
            if notify_change:
                notify_mod_list_changed(self.on_mod_list_changed)
            self.logger.info(f"遠端模組安裝完成: {safe_filename}", "ModDownload")
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
