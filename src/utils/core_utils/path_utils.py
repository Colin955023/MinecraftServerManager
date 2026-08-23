"""
路徑工具模組
提供專案中的路徑處理與檔案操作輔助函式
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, ClassVar

import orjson

from src.utils import (
    ArchiveSecurityError,
    atomic_write_json,
    atomic_write_text,
    get_logger,
)

logger = get_logger().bind(component="PathUtils")


class PathUtils:
    """路徑處理工具類別，提供專案路徑管理和安全路徑操作"""

    SAFE_ZIP_MAX_MEMBER_BYTES: ClassVar[int] = 512 * 1024 * 1024
    SAFE_ZIP_MAX_TOTAL_BYTES: ClassVar[int] = 2 * 1024 * 1024 * 1024
    SAFE_ZIP_MAX_COMPRESSION_RATIO: ClassVar[int] = 200
    _json_lock_registry_lock = threading.Lock()
    _json_path_locks: ClassVar[dict[str, threading.RLock]] = {}

    @staticmethod
    def best_effort_sync_dir(path: Path) -> None:
        """
        盡力同步目錄 metadata；不支援時忽略錯誤

        Args:
            path: 要同步的目錄路徑
        """
        try:
            fd = os.open(str(path), os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            return
        finally:
            os.close(fd)

    @staticmethod
    def _normalize_lock_key(path: Path | str) -> str:
        """將路徑正規化為鎖的 key，確保同一路徑共用同一把鎖"""
        p = Path(path)
        try:
            return str(p.resolve())
        except OSError:
            return str(p.absolute())

    @staticmethod
    def _get_json_path_lock(path: Path | str) -> threading.RLock:
        """取得 JSON 路徑專用鎖，避免同行程併發覆寫"""
        key = PathUtils._normalize_lock_key(path)
        with PathUtils._json_lock_registry_lock:
            lock = PathUtils._json_path_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                PathUtils._json_path_locks[key] = lock
            return lock

    @staticmethod
    def save_json_internal(path: Path | str, data: Any, indent: int = 2, *, skip_if_unchanged: bool = False) -> bool:
        """
        JSON 寫入核心：使用路徑專屬鎖後呼叫統一的 atomic_write_json

        Args:
            path: 要寫入的 JSON 檔案路徑
            data: 要寫入的資料
            indent: JSON 格式化縮排
            skip_if_unchanged: 是否在內容未變更時略過寫入

        Returns:
            寫入成功回傳 True，否則回傳 False
        """
        try:
            p = Path(path)
            p.parents[0].mkdir(parents=True, exist_ok=True)
            lock = PathUtils._get_json_path_lock(p)
            with lock:
                ok = atomic_write_json(p, data, indent=indent, skip_if_unchanged=skip_if_unchanged)
                if ok:
                    PathUtils.best_effort_sync_dir(p.parents[0])
                return bool(ok)
        except OSError, TypeError, ValueError:
            return False

    @staticmethod
    def is_path_within(base_dir: Path, target_path: Path, *, strict: bool = True) -> bool:
        """
        檢查 target_path 是否位於 base_dir 之下

        Args:
            base_dir: 基準目錄
            target_path: 待檢查路徑
            strict: 是否要求目標路徑必須存在

        Returns:
            若目標路徑位於基準目錄之下則回傳 True，否則回傳 False
        """
        try:
            base_resolved = base_dir.resolve(strict=True)
            target_resolved = target_path.resolve(strict=strict)
        except FileNotFoundError, OSError:
            return False
        try:
            target_resolved.relative_to(base_resolved)
            return True
        except ValueError:
            return False

    @staticmethod
    def _sanitize_archive_member_name(member_name: str) -> Path | None:
        """清理 zip/zip-like 內部檔案名稱，移除絕對路徑與父目錄參考"""
        try:
            if not member_name:
                return None
            normalized_name = str(member_name).replace("\\", "/")
            if PureWindowsPath(normalized_name).drive:
                return None
            p = PurePosixPath(normalized_name)
            if p.is_absolute():
                return None
            parts = p.parts
            if not parts or any(part in ("", ".", "..") for part in parts):
                return None
            return Path(*parts)
        except TypeError:
            return None
        except ValueError:
            return None

    @staticmethod
    def _is_zip_symlink(member: zipfile.ZipInfo) -> bool:
        """檢查 zip entry 是否宣告為 Unix symlink"""

        return ((member.external_attr >> 16) & 0o170000) == 0o120000

    @staticmethod
    def _validate_zip_member_size(
        member: zipfile.ZipInfo,
        *,
        max_member_uncompressed_bytes: int | None,
        max_compression_ratio: int | None,
    ) -> None:
        """檢查單一 zip member 的大小與壓縮比例"""

        if member.is_dir():
            return
        file_size = max(0, int(member.file_size))
        compressed_size = max(0, int(member.compress_size))
        if max_member_uncompressed_bytes is not None and file_size > max_member_uncompressed_bytes:
            raise ArchiveSecurityError(f"壓縮檔成員過大: {member.filename}")
        if max_compression_ratio is None or file_size == 0:
            return
        if compressed_size == 0:
            raise ArchiveSecurityError(f"壓縮檔成員壓縮比例異常: {member.filename}")
        if file_size / compressed_size > max_compression_ratio:
            raise ArchiveSecurityError(f"壓縮檔成員壓縮比例過高: {member.filename}")

    @staticmethod
    def safe_extract_zip(
        zip_path: Path,
        dest_dir: Path,
        progress_callback: Callable[[int, int], None] | None = None,
        *,
        max_total_uncompressed_bytes: int | None = SAFE_ZIP_MAX_TOTAL_BYTES,
        max_member_uncompressed_bytes: int | None = SAFE_ZIP_MAX_MEMBER_BYTES,
        max_compression_ratio: int | None = SAFE_ZIP_MAX_COMPRESSION_RATIO,
    ) -> None:
        """
        安全地解壓縮 Zip 檔案，防止 Zip Slip 漏洞

        Args:
            zip_path: Zip 檔案路徑
            dest_dir: 解壓縮目的地
            progress_callback: 進度回呼，接收 (已處理位元組數, 總位元組數)
            max_total_uncompressed_bytes: 最大解壓縮總位元組數，超過則拋出 ArchiveSecurityError
            max_member_uncompressed_bytes: 最大單一成員解壓縮位元組數，超過則拋出 ArchiveSecurityError
            max_compression_ratio: 最大壓縮比例，超過則拋出 ArchiveSecurityError
        """
        dest_dir = dest_dir.resolve(strict=False)
        dest_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.infolist()
            total_bytes = sum(max(0, int(member.file_size)) for member in members if not member.is_dir())
            if max_total_uncompressed_bytes is not None and total_bytes > max_total_uncompressed_bytes:
                raise ArchiveSecurityError("壓縮檔解壓後大小超過安全上限")
            sanitized_members: list[tuple[zipfile.ZipInfo, Path]] = []
            for member in members:
                if PathUtils._is_zip_symlink(member):
                    raise ArchiveSecurityError(f"壓縮檔包含不支援的符號連結: {member.filename}")
                PathUtils._validate_zip_member_size(
                    member,
                    max_member_uncompressed_bytes=max_member_uncompressed_bytes,
                    max_compression_ratio=max_compression_ratio,
                )
                sanitized = PathUtils._sanitize_archive_member_name(member.filename)
                if sanitized is None:
                    raise ArchiveSecurityError(f"壓縮檔包含不安全的成員名稱: {member.filename}")
                member_path = dest_dir / sanitized
                if not PathUtils.is_path_within(dest_dir, member_path, strict=False):
                    raise ArchiveSecurityError(f"壓縮檔嘗試路徑遍歷: {member.filename}")
                sanitized_members.append((member, sanitized))
            extracted_bytes = 0
            if progress_callback is not None:
                progress_callback(0, total_bytes)
            for member, sanitized in sanitized_members:
                member_path = dest_dir / sanitized
                if member.is_dir() or str(member.filename).endswith("/"):
                    member_path.mkdir(parents=True, exist_ok=True)
                    continue
                member_path.parents[0].mkdir(parents=True, exist_ok=True)
                member_extracted_bytes = 0
                with zf.open(member, "r") as source, member_path.open("wb") as target:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        next_member_bytes = member_extracted_bytes + len(chunk)
                        next_total_bytes = extracted_bytes + len(chunk)
                        if (
                            max_member_uncompressed_bytes is not None
                            and next_member_bytes > max_member_uncompressed_bytes
                        ):
                            raise ArchiveSecurityError(f"壓縮檔成員實際解壓大小超過安全上限: {member.filename}")
                        if max_total_uncompressed_bytes is not None and next_total_bytes > max_total_uncompressed_bytes:
                            raise ArchiveSecurityError("壓縮檔實際解壓大小超過安全上限")
                        target.write(chunk)
                        member_extracted_bytes = next_member_bytes
                        extracted_bytes = next_total_bytes
                        if progress_callback is not None and total_bytes > 0:
                            progress_callback(extracted_bytes, total_bytes)
            if progress_callback is not None:
                progress_callback(total_bytes if total_bytes > 0 else extracted_bytes, total_bytes)

    @staticmethod
    def get_project_root() -> Path:
        """
        取得專案根目錄的絕對路徑

        優先沿著目前模組位置向上尋找 pyproject.toml，這樣即使本檔案
        被搬到不同子目錄，仍可正確定位專案根目錄
        若為 frozen 執行，則退回可執行檔所在目錄

        Returns:
            專案根目錄的絕對 Path
        """
        current = Path(__file__).resolve()
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parents[0]

        for parent in current.parents:
            if (parent / "pyproject.toml").exists():
                return parent

        return current.parents[3]

    @staticmethod
    def load_json(path: Path | str, default: Any = None) -> Any:
        """
        安全讀取 JSON 檔案

        Args:
            path: JSON 檔案路徑
            default: 讀取失敗時回傳的預設值

        Returns:
            解析後的 JSON 內容，失敗時回傳預設值
        """
        try:
            p = Path(path)
            if not p.exists():
                return default
            return orjson.loads(p.read_bytes())
        except OSError, orjson.JSONDecodeError:
            return default

    @staticmethod
    def to_json_str(data: Any, indent: int | None = None) -> str:
        """
        將資料轉換為 JSON 字串

        Args:
            data: 要轉換的資料
            indent: JSON 縮排層級

        Returns:
            JSON 字串，失敗時回傳空字串
        """
        try:
            opt = orjson.OPT_INDENT_2 if indent == 2 else 0
            opt |= orjson.OPT_NON_STR_KEYS
            return orjson.dumps(data, option=opt).decode("utf-8")
        except TypeError:
            return ""

    @staticmethod
    def read_text_file(path: Path, encoding: str = "utf-8", errors: str = "replace") -> str | None:
        """
        讀取文字檔案，統一處理編碼和錯誤

        Args:
            path: 文字檔案路徑
            encoding: 文字編碼
            errors: 編碼錯誤處理方式

        Returns:
            讀取到的文字內容，失敗時回傳 None
        """
        try:
            if not path.exists():
                return None
            return path.read_text(encoding=encoding, errors=errors)
        except OSError:
            return None

    @staticmethod
    def write_text_file(path: Path, content: str, encoding: str = "utf-8", errors: str | None = None) -> bool:
        """
        寫入文字檔案，統一處理編碼和錯誤

        Args:
            path: 文字檔案路徑
            content: 要寫入的文字內容
            encoding: 文字編碼
            errors: 編碼錯誤處理方式

        Returns:
            若寫入成功則回傳 True，否則回傳 False
        """
        try:
            return atomic_write_text(path, content, encoding=encoding, errors=errors)
        except OSError:
            return False

    @staticmethod
    def delete_path(path: Path | str) -> bool:
        """
        刪除檔案或目錄

        Args:
            path: 要刪除的路徑

        Returns:
            若刪除成功則回傳 True，否則回傳 False
        """
        try:
            if isinstance(path, str):
                path = Path(path)
            if not path.exists():
                return True
            if path.is_dir():
                if path == PathUtils.get_project_root():
                    return False
                shutil.rmtree(path)
            else:
                path.unlink()
            return True
        except OSError:
            return False

    @staticmethod
    def delete_within(base_dir: Path | str, path: Path | str) -> bool:
        """
        僅在 path 位於 base_dir 之下時才刪除

        Args:
            base_dir: 允許刪除的根目錄
            path: 預計刪除的目標路徑

        Returns:
            若刪除成功則回傳 True，否則回傳 False
        """
        try:
            base = Path(base_dir).resolve(strict=True)
            target = Path(path).resolve(strict=False)
            if not PathUtils.is_path_within(base, target, strict=False):
                return False
            return PathUtils.delete_path(target)
        except OSError:
            return False

    @staticmethod
    def move_path(src: Path, dst: Path) -> bool:
        """
        移動檔案或目錄

        Args:
            src: 來源路徑
            dst: 目的地路徑

        Returns:
            若移動成功則回傳 True，否則回傳 False
        """
        try:
            if not src.exists():
                return False
            dst.parents[0].mkdir(parents=True, exist_ok=True)
            shutil.move(src, dst)
            return True
        except OSError:
            return False

    @staticmethod
    def move_within(base_dir: Path | str, src: Path, dst: Path) -> bool:
        """
        僅在來源與目的地都位於 base_dir 之下時才搬移

        Args:
            base_dir: 允許搬移的根目錄
            src: 來源路徑
            dst: 目的地路徑

        Returns:
            若搬移成功則回傳 True，否則回傳 False
        """
        try:
            base = Path(base_dir).resolve(strict=True)
            src_resolved = src.resolve(strict=False)
            dst_resolved = dst.resolve(strict=False)
            if not PathUtils.is_path_within(base, src_resolved, strict=False):
                return False
            if not PathUtils.is_path_within(base, dst_resolved, strict=False):
                return False
            return PathUtils.move_path(src_resolved, dst_resolved)
        except OSError:
            return False

    @staticmethod
    def replace_within(base_dir: Path | str, src: Path, dst: Path) -> bool:
        """
        僅在來源與目的地都位於 base_dir 之下時才以原子替換檔案

        Args:
            base_dir: 允許操作的根目錄
            src: 來源檔案路徑
            dst: 目的地檔案路徑

        Returns:
            若替換成功則回傳 True，否則回傳 False
        """
        try:
            base = Path(base_dir).resolve(strict=True)
            src_resolved = src.resolve(strict=True)
            dst_resolved = dst.resolve(strict=False)
            if not PathUtils.is_path_within(base, src_resolved, strict=False):
                return False
            if not PathUtils.is_path_within(base, dst_resolved, strict=False):
                return False
            if src_resolved.is_dir():
                return False
            dst_resolved.parents[0].mkdir(parents=True, exist_ok=True)
            src_resolved.replace(dst_resolved)
            return True
        except OSError:
            return False

    @staticmethod
    def copy_file(src: Path, dst: Path) -> bool:
        """
        複製檔案

        Args:
            src: 來源檔案路徑
            dst: 目的地檔案路徑

        Returns:
            若複製成功則回傳 True，否則回傳 False
        """
        try:
            if not src.exists():
                return False
            dst.parents[0].mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True
        except OSError:
            return False

    @staticmethod
    def copy_dir(
        src: Path,
        dst: Path,
        ignore_patterns: list[str] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> bool:
        """
        複製目錄

        Args:
            src: 來源目錄
            dst: 目的地目錄
            ignore_patterns: 要忽略的樣式列表
            progress_callback: 進度回呼，接收 (已複製檔案數, 總檔案數)

        Returns:
            若複製成功則回傳 True，否則回傳 False
        """
        try:
            if not src.exists() or not src.is_dir():
                return False
            ignore = shutil.ignore_patterns(*ignore_patterns) if ignore_patterns else None

            def _walk_entries() -> list[tuple[Path, list[str], list[str]]]:
                entries: list[tuple[Path, list[str], list[str]]] = []
                for root, dirs, files in os.walk(src, topdown=True):
                    root_path = Path(root)
                    if ignore is not None:
                        ignored = set(ignore(str(root_path), [*dirs, *files]))
                        dirs[:] = [name for name in dirs if name not in ignored]
                        files = [name for name in files if name not in ignored]
                    entries.append((root_path, list(dirs), list(files)))
                return entries

            entries = _walk_entries()
            total_files = sum((len(files) for _root, _dirs, files in entries))
            copied_files = 0
            dst.mkdir(parents=True, exist_ok=True)
            if progress_callback is not None:
                progress_callback(0, total_files)
            for root_path, dirs, files in entries:
                relative_root = root_path.relative_to(src)
                target_root = dst if relative_root == Path() else dst / relative_root
                target_root.mkdir(parents=True, exist_ok=True)
                for dir_name in dirs:
                    (target_root / dir_name).mkdir(parents=True, exist_ok=True)
                for file_name in files:
                    shutil.copy2(root_path / file_name, target_root / file_name)
                    copied_files += 1
                    if progress_callback is not None and total_files > 0:
                        progress_callback(copied_files, total_files)
            if progress_callback is not None:
                progress_callback(copied_files, total_files)
            return True
        except OSError:
            return False

    @staticmethod
    def find_executable(name: str) -> str | None:
        """
        尋找執行檔路徑

        Args:
            name: 執行檔名稱

        Returns:
            找到時回傳完整路徑，否則回傳 None
        """
        return shutil.which(name)


__all__ = ["PathUtils"]
