"""
伺服器備份功能
負責管理伺服器的備份與還原
"""

from __future__ import annotations

import datetime
import os
import stat
import tempfile
import uuid
import zipfile
from collections.abc import Callable, Iterator
from operator import itemgetter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.models import ServerConfig
from src.utils import (
    SystemUtils,
    atomic_replace_file_within,
    atomic_write_json,
    bytes_to_mb,
    delete_within,
    get_logger,
    is_path_within,
    is_reparse_point,
    list_bounded_directory,
    move_within,
    open_bounded_zip,
    open_bounded_zip_writer,
    open_regular_file,
    resolve_stable_directory,
    resolve_stable_path,
    safe_extract_zip,
    stable_directory,
    validate_server_name,
    walk_bounded_tree,
)

if TYPE_CHECKING:
    from .server_crud import ServerCRUD
    from .server_runtime import ServerRuntime

logger = get_logger().bind(component="ServerBackup")

_BACKUP_EXCLUDES = {"logs", "crash-reports", "backups", ".git"}
_BACKUP_MAX_MEMBERS = 100_000
_BACKUP_MAX_TOTAL_BYTES = 128 * 1024 * 1024 * 1024
_BACKUP_MAX_MEMBER_BYTES = 16 * 1024 * 1024 * 1024
_BACKUP_MAX_COMPRESSION_RATIO = 200
_BACKUP_DISK_RESERVE_BYTES = 1024 * 1024 * 1024
_MANAGED_TIMESTAMP_FORMAT = "%Y%m%d%H%M%S%f"
_SUPPORTED_TIMESTAMP_FORMATS = {
    12: "%Y%m%d%H%M",
    14: "%Y%m%d%H%M%S",
    20: _MANAGED_TIMESTAMP_FORMAT,
}


class ServerBackupManager:
    """伺服器備份管理器"""

    def __init__(self, server_crud: ServerCRUD, server_runtime: ServerRuntime):
        self.server_crud = server_crud
        self.server_runtime = server_runtime

    @staticmethod
    def _is_safe_server_name(server_name: str) -> bool:
        """確認備份檔名前綴是單一安全路徑元件"""
        try:
            validate_server_name(server_name)
            return True
        except ValueError:
            return False

    def _validated_server_path(self, config: ServerConfig) -> Path:
        """取得受管且不含 reparse point 的伺服器路徑"""
        servers_root = resolve_stable_directory(self.server_crud.servers_root)
        raw_path = Path(config.path)
        server_path = resolve_stable_directory(raw_path)
        if server_path == servers_root or not is_path_within(servers_root, server_path, strict=False):
            raise OSError("伺服器路徑不在 servers_root 內")
        return server_path

    def backup_server(
        self, server_name: str, max_backups: int = 10, progress_callback: Callable[[float, str], None] | None = None
    ) -> bool:
        """
        備份伺服器
        先在備份目錄建立暫存 ZIP，完整成功後再原子替換最終檔案
        使用微秒時間戳與隨機識別碼確保檔名唯一，最多保留 max_backups 份

        Args:
            server_name: 伺服器名稱
            max_backups: 最多保留的備份份數
            progress_callback: 進度回呼，接收 (進度百分比 0-100, 狀態文字)

        Returns:
            備份成功回傳 True，失敗回傳 False
        """
        temp_backup_file: Path | None = None
        if not self._is_safe_server_name(server_name):
            logger.error("備份失敗：伺服器名稱不是安全的檔名元件")
            return False
        if not self.server_runtime.begin_maintenance(server_name):
            logger.error(f"備份失敗：伺服器 {server_name} 正在執行或進行其他維護操作")
            return False
        try:
            with self.server_crud.operation_lock:
                if self.server_runtime.observe(server_name).is_running:
                    logger.error(f"備份失敗：伺服器 {server_name} 正在執行中，無法建立一致的備份")
                    return False

                config = self.server_crud.snapshot().get(server_name)
                if not config:
                    logger.error(f"備份失敗：找不到伺服器 {server_name}")
                    return False

                try:
                    server_path = self._validated_server_path(config)
                except OSError as e:
                    logger.error(f"備份失敗：伺服器路徑不安全 {e}")
                    return False
                if not server_path.exists() or not server_path.is_dir():
                    logger.error(f"備份失敗：伺服器路徑不存在 {server_path}")
                    return False

            backup_dir = self._get_backup_dir(config)
            timestamp = datetime.datetime.now().strftime(_MANAGED_TIMESTAMP_FORMAT)
            backup_filename = f"{server_name}_{timestamp}-{uuid.uuid4().hex[:8]}.zip"
            backup_file = backup_dir / backup_filename

            logger.info(f"開始備份伺服器 {server_name} 至 {backup_file}")

            if progress_callback:
                progress_callback(0, "正在掃描檔案...")

            def _ignore(root: str, names: list[str]) -> list[str]:
                root_path = Path(root)
                return [name for name in names if name in _BACKUP_EXCLUDES and (root_path / name).exists()]

            def _iter_backup_files() -> Iterator[tuple[Path, int]]:
                for root_path, _dirs, files in walk_bounded_tree(
                    server_path,
                    ignore=_ignore,
                    max_entries=_BACKUP_MAX_MEMBERS,
                ):
                    for file in files:
                        file_path = root_path / file
                        try:
                            metadata = file_path.stat(follow_symlinks=False)
                            if not stat.S_ISREG(metadata.st_mode):
                                raise OSError(f"備份來源不是一般檔案: {file_path}")
                            file_size = metadata.st_size
                        except OSError as e:
                            raise OSError(f"無法讀取備份來源檔案資訊: {file_path}") from e
                        yield file_path, file_size

            planned_files: list[tuple[Path, int]] = []
            total_size = 0
            for file_path, file_size in _iter_backup_files():
                planned_files.append((file_path, file_size))
                file_count = len(planned_files)
                total_size += file_size
                if file_count > _BACKUP_MAX_MEMBERS:
                    raise ValueError(f"備份檔案數超過安全上限 {_BACKUP_MAX_MEMBERS}")
                if total_size > _BACKUP_MAX_TOTAL_BYTES:
                    raise ValueError(f"備份總大小超過安全上限 {_BACKUP_MAX_TOTAL_BYTES} bytes")
                if file_size > _BACKUP_MAX_MEMBER_BYTES:
                    raise ValueError(f"備份單檔大小超過安全上限 {_BACKUP_MAX_MEMBER_BYTES} bytes")

            file_count = len(planned_files)
            if file_count > _BACKUP_MAX_MEMBERS:
                raise ValueError(f"備份檔案數超過安全上限 {_BACKUP_MAX_MEMBERS}")
            if total_size > _BACKUP_MAX_TOTAL_BYTES:
                raise ValueError(f"備份總大小超過安全上限 {_BACKUP_MAX_TOTAL_BYTES} bytes")

            if progress_callback:
                progress_callback(5, f"準備備份 {file_count} 個檔案...")

            with stable_directory(backup_dir) as backup_dir:
                backup_file = backup_dir / backup_filename
                fd, temp_name = tempfile.mkstemp(prefix=f".{backup_filename}.", suffix=".tmp", dir=backup_dir)
                temp_backup_file = Path(temp_name)
                os.close(fd)

                processed_size = 0
                processed_count = 0
                with open_bounded_zip_writer(
                    temp_backup_file,
                    max_members=_BACKUP_MAX_MEMBERS,
                    max_total_bytes=_BACKUP_MAX_TOTAL_BYTES,
                    max_member_bytes=_BACKUP_MAX_MEMBER_BYTES,
                ) as zf:
                    for i, (file_path, file_size) in enumerate(_iter_backup_files()):
                        if i >= file_count or (file_path, file_size) != planned_files[i]:
                            raise ValueError("備份來源在掃描後變更")
                        rel_path = file_path.relative_to(server_path)
                        if progress_callback and i % 10 == 0:
                            pct = 5 + (processed_size / total_size * 90 if total_size > 0 else 0)
                            progress_callback(pct, f"正在壓縮: {rel_path.name}")
                        try:
                            with open_regular_file(file_path, allowed_root=server_path) as source:
                                zf.write_file(rel_path.as_posix(), source, expected_bytes=file_size)
                        except Exception as e:
                            raise OSError(f"備份檔案失敗: {file_path}") from e
                        processed_size += file_size
                        processed_count += 1
                    if processed_count != file_count:
                        raise ValueError("備份來源在掃描後遺失檔案")

                if is_reparse_point(backup_dir):
                    raise OSError("備份目錄在提交前變成 reparse point")
                if not atomic_replace_file_within(backup_dir, temp_backup_file, backup_file):
                    raise OSError("備份檔案無法安全原子提交")
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
                delete_within(temp_backup_file.parent, temp_backup_file)
            logger.exception(f"伺服器 {server_name} 備份時發生錯誤: {e}")
            return False
        finally:
            self.server_runtime.end_maintenance(server_name)

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
        if not self._is_safe_server_name(server_name):
            return []
        if backup_dir_override:
            backup_dir = backup_dir_override
        else:
            config = self.server_crud.snapshot().get(server_name)
            if not config:
                return []
            try:
                backup_dir = self._get_backup_dir(config)
            except OSError:
                return []

        if is_reparse_point(backup_dir) or not backup_dir.exists() or not backup_dir.is_dir():
            return []

        backups: list[dict[str, Any]] = []
        prefix = f"{server_name}_"
        try:
            backup_files = list_bounded_directory(backup_dir, reject_reparse=False)
        except OSError:
            return []
        for file_path in backup_files:
            if (
                is_reparse_point(file_path)
                or not file_path.is_file()
                or file_path.suffix.lower() != ".zip"
                or not file_path.name.startswith(prefix)
            ):
                continue
            timestamp_str, dt = self._parse_backup_timestamp(file_path.stem.removeprefix(prefix))
            if dt is None:
                continue
            try:
                size_mb = bytes_to_mb(file_path.stat().st_size)
            except OSError:
                continue
            backups.append(
                {
                    "filename": file_path.name,
                    "path": str(file_path),
                    "timestamp": timestamp_str,
                    "readable_time": dt.strftime("%Y/%m/%d %H:%M:%S"),
                    "size_mb": round(size_mb, 2),
                    "datetime": dt,
                }
            )

        backups.sort(key=itemgetter("datetime"), reverse=True)
        return backups

    def delete_backups(self, server_name: str, backup_dir: Path) -> bool:
        """
        刪除指定伺服器位於外部目錄的所有受管理備份

        Args:
            server_name: 伺服器名稱
            backup_dir: 外部備份資料夾

        Returns:
            全部備份刪除成功時回傳 True
        """
        if not self._is_safe_server_name(server_name) or is_reparse_point(backup_dir):
            return False
        for backup in self.list_backups(server_name, backup_dir_override=backup_dir):
            if not delete_within(backup_dir, Path(backup["path"])):
                logger.warning(f"刪除備份失敗: {backup['filename']}")
                return False
        return True

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
        staging_path: Path | None = None
        rollback_path: Path | None = None
        journal_path: Path | None = None
        if not self.server_runtime.begin_maintenance(server_name):
            logger.error(f"還原失敗：伺服器 {server_name} 正在執行或進行其他維護操作")
            return False
        try:
            with self.server_crud.operation_lock:
                if self.server_runtime.observe(server_name).is_running:
                    logger.error(f"還原失敗：伺服器 {server_name} 正在執行中，無法還原")
                    return False

                config = self.server_crud.snapshot().get(server_name)
            if not config:
                logger.error(f"還原失敗：找不到伺服器 {server_name}")
                return False

            try:
                server_path = self._validated_server_path(config)
            except OSError as e:
                logger.error(f"還原失敗：伺服器路徑不安全 {e}")
                return False
            if not server_path.exists() or not server_path.is_dir():
                logger.error(f"還原失敗：伺服器路徑包含符號連結或 reparse point {server_path}")
                return False
            server_parent = resolve_stable_directory(server_path.parent)
            try:
                backup_dir = self._get_backup_dir(config)
            except OSError as e:
                logger.error(f"還原失敗：備份目錄不安全 {e}")
                return False
            backup_file = resolve_stable_path(backup_path_str)

            if (
                is_reparse_point(backup_file)
                or not is_path_within(backup_dir, backup_file, strict=True)
                or not backup_file.is_file()
            ):
                logger.error(f"還原失敗：找不到備份檔 {backup_file}")
                return False

            logger.info(f"開始從 {backup_file.name} 還原伺服器 {server_name}")

            declared_total_bytes, declared_max_member_bytes, declared_members = self._archive_declared_sizes(
                backup_file
            )
            if declared_members > _BACKUP_MAX_MEMBERS:
                raise ValueError(f"備份檔案數超過安全上限 {_BACKUP_MAX_MEMBERS}")
            if declared_total_bytes > _BACKUP_MAX_TOTAL_BYTES:
                raise ValueError(f"備份總大小超過安全上限 {_BACKUP_MAX_TOTAL_BYTES} bytes")
            if declared_max_member_bytes > _BACKUP_MAX_MEMBER_BYTES:
                raise ValueError(f"備份單檔大小超過安全上限 {_BACKUP_MAX_MEMBER_BYTES} bytes")
            available_bytes = SystemUtils.get_free_disk_bytes(server_path.parent)
            required_bytes = declared_total_bytes + _BACKUP_DISK_RESERVE_BYTES
            if required_bytes > available_bytes:
                raise OSError(f"還原所需空間不足；需要 {required_bytes} bytes，可用 {available_bytes} bytes")

            if progress_callback:
                progress_callback(0, f"準備還原 {backup_file.name}...")

            def _on_extract_progress(extracted_bytes: int, total_bytes: int) -> None:
                if not progress_callback:
                    return
                pct = 5 + (extracted_bytes / total_bytes * 90 if total_bytes > 0 else 90)
                progress_callback(pct, f"解壓縮中... {extracted_bytes}/{total_bytes} bytes")

            staging_path = resolve_stable_directory(
                server_parent / f".{server_path.name}.restore-{uuid.uuid4().hex}",
                create=True,
            )
            safe_extract_zip(
                backup_file,
                staging_path,
                progress_callback=_on_extract_progress,
                max_members=_BACKUP_MAX_MEMBERS,
                max_total_uncompressed_bytes=_BACKUP_MAX_TOTAL_BYTES,
                max_member_uncompressed_bytes=_BACKUP_MAX_MEMBER_BYTES,
                max_compression_ratio=_BACKUP_MAX_COMPRESSION_RATIO,
            )

            for excluded_name in _BACKUP_EXCLUDES:
                staged_excluded = staging_path / excluded_name
                if staged_excluded.exists() and not delete_within(staging_path, staged_excluded):
                    raise OSError(f"無法清除備份中的排除項目: {excluded_name}")

            prepared_path = staging_path
            rollback_path = server_parent / f".{server_path.name}.restore-rollback-{uuid.uuid4().hex}"
            journal_path = server_parent / f"{rollback_path.name}.json"
            if not atomic_write_json(
                journal_path,
                {
                    "schema_version": 1,
                    "server_name": server_name,
                    "server_path": str(server_path),
                    "prepared_path": str(prepared_path),
                },
            ):
                raise OSError("無法建立還原交易識別標記")
            if not move_within(server_parent, server_path, rollback_path):
                raise OSError("無法將原伺服器目錄移至還原回滾位置")
            moved_excludes: list[str] = []
            try:
                for excluded_name in _BACKUP_EXCLUDES:
                    preserved_path = rollback_path / excluded_name
                    if preserved_path.exists():
                        if not move_within(server_parent, preserved_path, prepared_path / excluded_name):
                            raise OSError(f"無法保留排除目錄: {excluded_name}")
                        moved_excludes.append(excluded_name)
                if not move_within(server_parent, prepared_path, server_path):
                    raise OSError("無法將還原內容移至伺服器目錄")
            except Exception:
                for excluded_name in reversed(moved_excludes):
                    staged_preserved = prepared_path / excluded_name
                    if staged_preserved.exists():
                        try:
                            if not move_within(server_parent, staged_preserved, rollback_path / excluded_name):
                                raise OSError(f"無法復原排除目錄: {excluded_name}")
                        except OSError as e:
                            logger.exception(f"還原失敗時無法復原排除目錄 {excluded_name}: {e}")
                if not move_within(server_parent, rollback_path, server_path):
                    raise OSError("還原失敗時無法復原伺服器目錄") from None
                if journal_path is not None:
                    delete_within(server_parent, journal_path)
                raise

            if rollback_path.exists() and not delete_within(server_path.parent, rollback_path):
                logger.warning(f"還原成功，但舊伺服器暫存目錄無法清除: {rollback_path}")
            if not delete_within(server_parent, journal_path):
                logger.warning(f"還原成功，但交易識別標記無法清除: {journal_path}")

            if progress_callback:
                progress_callback(100, "還原完成！")

            logger.info(f"伺服器 {server_name} 還原成功")
            return True
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            logger.exception(f"還原伺服器時發生錯誤: {e}")
            return False
        finally:
            if staging_path is not None:
                delete_within(staging_path.parent, staging_path)
            if rollback_path is not None and rollback_path.exists():
                logger.error(f"還原回滾目錄仍存在，為避免資料遺失不自動刪除: {rollback_path}")
            self.server_runtime.end_maintenance(server_name)

    @staticmethod
    def _archive_declared_sizes(backup_file: Path) -> tuple[int, int, int]:
        """取得 ZIP 宣告的總大小、最大單檔大小與檔案數"""
        total_bytes = 0
        max_member_bytes = 0
        member_count = 0
        with open_bounded_zip(backup_file, max_members=_BACKUP_MAX_MEMBERS) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                file_size = max(0, int(member.file_size))
                total_bytes += file_size
                max_member_bytes = max(max_member_bytes, file_size)
                member_count += 1
        return total_bytes, max_member_bytes, member_count

    def _get_backup_dir(self, config: ServerConfig) -> Path:
        """取得設定的外部備份存放目錄"""
        server_path = self._validated_server_path(config)
        backup_path = str(config.backup_path or "").strip()
        if not backup_path:
            raise OSError("尚未設定備份目錄")
        backup_dir = resolve_stable_directory(backup_path)
        if is_reparse_point(backup_dir) or not backup_dir.is_dir():
            raise OSError("備份目錄不是安全的一般資料夾")
        if backup_dir == server_path or is_path_within(server_path, backup_dir, strict=False):
            raise OSError("備份目錄不得位於伺服器資料夾內")
        servers_root = resolve_stable_directory(self.server_crud.servers_root)
        if backup_dir == servers_root:
            raise OSError("備份目錄不得為伺服器根目錄")
        return backup_dir

    @staticmethod
    def _parse_backup_timestamp(value: str) -> tuple[str, datetime.datetime | None]:
        """解析目前與既有備份檔名中的時間戳"""
        timestamp_str = value.partition("-")[0]
        timestamp_format = _SUPPORTED_TIMESTAMP_FORMATS.get(len(timestamp_str))
        if timestamp_format is None or not timestamp_str.isdigit():
            return timestamp_str, None
        try:
            return timestamp_str, datetime.datetime.strptime(timestamp_str, timestamp_format)
        except ValueError:
            return timestamp_str, None

    def _cleanup_old_backups(self, backup_dir: Path, server_name: str, max_backups: int) -> None:
        """清理超過保留數量的舊備份"""
        try:
            backups = self.list_backups(server_name, backup_dir_override=backup_dir)
            if len(backups) <= max_backups:
                return

            to_delete = backups[max_backups:]
            for b in to_delete:
                path = Path(b["path"])
                if delete_within(backup_dir, path):
                    logger.info(f"已刪除舊備份: {path.name}")
                else:
                    logger.warning(f"刪除舊備份失敗 {path.name}: 路徑已變更或不是安全檔案")
        except Exception as e:
            logger.exception(f"清理舊備份時發生錯誤: {e}")


__all__ = ["ServerBackupManager"]
