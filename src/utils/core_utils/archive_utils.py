"""壓縮檔安全處理工具"""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath

from .exceptions import ArchiveSecurityError
from .filesystem_utils import is_path_within

SAFE_ZIP_MAX_MEMBER_BYTES = 512 * 1024 * 1024
SAFE_ZIP_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
SAFE_ZIP_MAX_COMPRESSION_RATIO = 200


def _sanitize_archive_member_name(member_name: str) -> Path | None:
    """清理壓縮檔內部名稱，拒絕絕對路徑與父目錄參考"""
    try:
        if not member_name:
            return None
        normalized_name = str(member_name).replace("\\", "/")
        if PureWindowsPath(normalized_name).drive:
            return None
        path = PurePosixPath(normalized_name)
        if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
            return None
        return Path(*path.parts)
    except TypeError, ValueError:
        return None


def _is_zip_symlink(member: zipfile.ZipInfo) -> bool:
    return ((member.external_attr >> 16) & 0o170000) == 0o120000


def _validate_zip_member_size(
    member: zipfile.ZipInfo,
    *,
    max_member_uncompressed_bytes: int | None,
    max_compression_ratio: int | None,
) -> None:
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
    安全解壓縮 ZIP，拒絕路徑穿越、符號連結與異常大小

    Args:
        zip_path: ZIP 檔案路徑
        dest_dir: 解壓縮目的目錄
        progress_callback: 接收已處理位元組數與總位元組數的回呼
        max_total_uncompressed_bytes: 解壓縮後的總位元組上限
        max_member_uncompressed_bytes: 單一成員的解壓縮位元組上限
        max_compression_ratio: 單一成員允許的最大壓縮比例
    """
    dest_dir = dest_dir.resolve(strict=False)
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        members = archive.infolist()
        total_bytes = sum(max(0, int(member.file_size)) for member in members if not member.is_dir())
        if max_total_uncompressed_bytes is not None and total_bytes > max_total_uncompressed_bytes:
            raise ArchiveSecurityError("壓縮檔解壓後大小超過安全上限")
        sanitized_members: list[tuple[zipfile.ZipInfo, Path]] = []
        for member in members:
            if _is_zip_symlink(member):
                raise ArchiveSecurityError(f"壓縮檔包含不支援的符號連結: {member.filename}")
            _validate_zip_member_size(
                member,
                max_member_uncompressed_bytes=max_member_uncompressed_bytes,
                max_compression_ratio=max_compression_ratio,
            )
            sanitized = _sanitize_archive_member_name(member.filename)
            if sanitized is None:
                raise ArchiveSecurityError(f"壓縮檔包含不安全的成員名稱: {member.filename}")
            if not is_path_within(dest_dir, dest_dir / sanitized, strict=False):
                raise ArchiveSecurityError(f"壓縮檔嘗試路徑穿越: {member.filename}")
            sanitized_members.append((member, sanitized))

        extracted_bytes = 0
        if progress_callback is not None:
            progress_callback(0, total_bytes)
        for member, sanitized in sanitized_members:
            member_path = dest_dir / sanitized
            if member.is_dir() or member.filename.endswith("/"):
                member_path.mkdir(parents=True, exist_ok=True)
                continue
            member_path.parent.mkdir(parents=True, exist_ok=True)
            member_extracted_bytes = 0
            with archive.open(member, "r") as source, member_path.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    next_member_bytes = member_extracted_bytes + len(chunk)
                    next_total_bytes = extracted_bytes + len(chunk)
                    if max_member_uncompressed_bytes is not None and next_member_bytes > max_member_uncompressed_bytes:
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


__all__ = ["safe_extract_zip"]
