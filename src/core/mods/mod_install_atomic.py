"""模組檔案安裝與本地原子化操作。"""

from __future__ import annotations

import contextlib
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...models import LocalModMutationResult
from ...utils import PathUtils, record_and_mark
from .mod_op_utils import notify_mod_list_changed

if TYPE_CHECKING:
    from .mod_rollback import ModRollback


class ModInstallAtomic:
    """處理本地模組的原子化替換、匯入、刪除與狀態切換。"""

    def __init__(
        self,
        server_path: Path,
        mods_path: Path,
        download_staging_root: Path,
        logger: Any,
        mod_rollback: ModRollback,
        on_mod_list_changed: Callable | None = None,
    ) -> None:
        self.server_path = server_path
        self.mods_path = mods_path
        self.download_staging_root = download_staging_root
        self.logger = logger
        self.mod_rollback = mod_rollback
        self.on_mod_list_changed = on_mod_list_changed

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
        """
        建立失敗的本地模組異動結果。

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

    def set_mod_state_result(self, mod_id: str, enable: bool) -> LocalModMutationResult:
        """
        切換本地模組的啟用或停用狀態。

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
                notify_mod_list_changed(self.on_mod_list_changed)
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
            self.logger.error(f"{action}模組失敗（IO/權限）: {exc}", "ModInstallAtomic")
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
        """
        匯入本地模組檔案到目前伺服器的 `mods` 目錄。

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
            notify_mod_list_changed(self.on_mod_list_changed)
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
        """
        刪除一或多個本地模組檔案。

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
                notify_mod_list_changed(self.on_mod_list_changed)
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
