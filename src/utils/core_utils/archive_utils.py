"""壓縮檔安全處理工具"""

from __future__ import annotations

import os
import struct
import zipfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO

from .exceptions import ArchiveSecurityError
from .filesystem_utils import (
    is_path_within,
    open_regular_file,
    open_regular_file_for_write,
    resolve_stable_directory,
    resolve_stable_path,
)

SAFE_ZIP_MAX_MEMBERS = 100_000
SAFE_ZIP_MAX_MEMBER_BYTES = 512 * 1024 * 1024
SAFE_ZIP_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
SAFE_ZIP_MAX_COMPRESSION_RATIO = 200
ARCHIVE_METADATA_MAX_BYTES = 2 * 1024 * 1024
SAFE_ZIP_MAX_CENTRAL_DIRECTORY_BYTES = 64 * 1024 * 1024
SAFE_ZIP_MAX_ARCHIVE_BYTES = SAFE_ZIP_MAX_TOTAL_BYTES + SAFE_ZIP_MAX_CENTRAL_DIRECTORY_BYTES

_ZIP_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP64_EOCD_SIGNATURE = b"PK\x06\x06"
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_ZIP_EOCD_BYTES = 22
_ZIP_MAX_COMMENT_BYTES = 0xFFFF

_ZIP_COMPRESSION_LEVEL = 6

_ALLOWED_ZIP_COMPRESSION_TYPES = frozenset(
    {
        zipfile.ZIP_STORED,
        zipfile.ZIP_DEFLATED,
    }
)


def _read_zip_directory_limits(
    source: BinaryIO,
    *,
    max_members: int | None,
    max_central_directory_bytes: int | None,
    max_archive_bytes: int | None,
) -> None:
    """在建立 ZipFile 前，以固定尾端讀取限制 ZIP central directory"""
    source.seek(0, os.SEEK_END)
    file_size = source.tell()
    if max_archive_bytes is not None and file_size > max_archive_bytes:
        raise ArchiveSecurityError("ZIP 檔案大小超過安全上限")
    tail_size = min(file_size, _ZIP_EOCD_BYTES + _ZIP_MAX_COMMENT_BYTES)
    source.seek(file_size - tail_size)
    tail = source.read(tail_size)
    eocd_offset = tail.rfind(_ZIP_EOCD_SIGNATURE)
    if eocd_offset < 0 or eocd_offset + _ZIP_EOCD_BYTES > len(tail):
        raise zipfile.BadZipFile("找不到 ZIP central directory 結尾")

    (
        _signature,
        disk_number,
        central_directory_disk,
        _disk_members,
        total_members,
        central_directory_bytes,
        central_directory_offset,
        comment_bytes,
    ) = struct.unpack_from("<4s4H2LH", tail, eocd_offset)
    if eocd_offset + _ZIP_EOCD_BYTES + comment_bytes != len(tail):
        raise zipfile.BadZipFile("ZIP central directory 結尾格式無效")
    if disk_number != 0 or central_directory_disk != 0:
        raise zipfile.BadZipFile("不支援多磁碟 ZIP")

    if (
        total_members == 0xFFFF
        or central_directory_bytes == 0xFFFFFFFF
        or central_directory_offset == 0xFFFFFFFF
        or _disk_members == 0xFFFF
    ):
        locator_offset = tail.rfind(_ZIP64_LOCATOR_SIGNATURE, 0, eocd_offset)
        if locator_offset < 0 or locator_offset + 20 > len(tail):
            raise zipfile.BadZipFile("找不到 ZIP64 central directory 資訊")
        _signature, _disk, _zip64_offset, total_disks = struct.unpack_from("<4sLQL", tail, locator_offset)
        if total_disks != 1 or _disk != 0:
            raise zipfile.BadZipFile("不支援多磁碟 ZIP64")
        zip64_offset_in_tail = tail.rfind(_ZIP64_EOCD_SIGNATURE, 0, locator_offset)
        if zip64_offset_in_tail < 0 or zip64_offset_in_tail + 56 > len(tail):
            raise zipfile.BadZipFile("找不到 ZIP64 central directory 結尾")
        (
            _signature,
            record_bytes,
            _version_made,
            _version_needed,
            zip64_disk,
            zip64_central_directory_disk,
            _zip64_disk_members,
            total_members,
            central_directory_bytes,
            _central_directory_offset,
        ) = struct.unpack_from("<4sQ2H2L4Q", tail, zip64_offset_in_tail)
        if record_bytes < 44 or zip64_disk != 0 or zip64_central_directory_disk != 0:
            raise zipfile.BadZipFile("ZIP64 central directory 資訊無效")
        if zip64_offset_in_tail + record_bytes > len(tail):
            raise zipfile.BadZipFile("ZIP64 central directory 記錄不完整")

    if max_members is not None and total_members > max_members:
        raise ArchiveSecurityError("壓縮檔成員數量超過安全上限")
    if max_central_directory_bytes is not None and central_directory_bytes > max_central_directory_bytes:
        raise ArchiveSecurityError("壓縮檔 central directory 超過安全上限")


@contextmanager
def open_bounded_zip(
    zip_path: Path | str,
    *,
    max_members: int | None = SAFE_ZIP_MAX_MEMBERS,
    max_central_directory_bytes: int | None = SAFE_ZIP_MAX_CENTRAL_DIRECTORY_BYTES,
    max_archive_bytes: int | None = SAFE_ZIP_MAX_ARCHIVE_BYTES,
) -> Generator[zipfile.ZipFile]:
    """
    檢查 ZIP central directory 後，以不跟隨 reparse point 的方式開啟

    Args:
        zip_path: ZIP 檔案路徑
        max_members: ZIP 成員數量上限
        max_central_directory_bytes: central directory 位元組上限
        max_archive_bytes: ZIP 實體檔案大小上限

    Returns:
        已通過限制檢查的 ZIP 內容管理器
    """
    with open_regular_file(zip_path) as source:
        _read_zip_directory_limits(
            source,
            max_members=max_members,
            max_central_directory_bytes=max_central_directory_bytes,
            max_archive_bytes=max_archive_bytes,
        )
        with zipfile.ZipFile(source, "r") as archive:
            if max_members is not None and len(archive.infolist()) > max_members:
                raise ArchiveSecurityError("壓縮檔成員數量超過安全上限")
            yield archive


class _BoundedZipWriter:
    """限制 ZIP 寫入成員名稱、數量與未壓縮大小"""

    def __init__(
        self,
        archive: zipfile.ZipFile,
        *,
        max_members: int | None,
        max_total_bytes: int | None,
        max_member_bytes: int | None,
    ) -> None:
        self._archive = archive
        self._max_members = max_members
        self._max_total_bytes = max_total_bytes
        self._max_member_bytes = max_member_bytes
        self._total_bytes = 0
        self._member_kinds: dict[tuple[str, ...], bool] = {}
        self._parent_keys: set[tuple[str, ...]] = set()

    def _prepare_member(self, member_name: str, size: int) -> str:
        if size < 0:
            raise ArchiveSecurityError("ZIP 成員大小不可為負數")
        if self._max_members is not None and len(self._member_kinds) >= self._max_members:
            raise ArchiveSecurityError("壓縮檔成員數量超過安全上限")
        if self._max_member_bytes is not None and size > self._max_member_bytes:
            raise ArchiveSecurityError(f"壓縮檔成員過大: {member_name}")
        if self._max_total_bytes is not None and self._total_bytes + size > self._max_total_bytes:
            raise ArchiveSecurityError("壓縮檔總輸出大小超過安全上限")
        sanitized = _sanitize_archive_member_name(member_name)
        if sanitized is None:
            raise ArchiveSecurityError(f"壓縮檔包含不安全的成員名稱: {member_name}")
        normalized_name = sanitized.as_posix()
        _validate_member_path_collision(
            zipfile.ZipInfo(normalized_name),
            sanitized,
            member_kinds=self._member_kinds,
            parent_keys=self._parent_keys,
        )
        self._total_bytes += size
        return normalized_name

    def writestr(self, member_name: str, data: bytes | str) -> None:
        """寫入已受大小與路徑限制的記憶體內容"""
        payload = data.encode() if isinstance(data, str) else data
        normalized_name = self._prepare_member(member_name, len(payload))
        self._archive.writestr(normalized_name, payload)

    def write_file(self, member_name: str, source: BinaryIO, *, expected_bytes: int) -> int:
        """串流寫入固定預期大小的來源並拒絕來源成長或縮短"""
        normalized_name = self._prepare_member(member_name, expected_bytes)
        copied_bytes = 0
        with self._archive.open(normalized_name, "w", force_zip64=True) as target:
            while chunk := source.read(min(1024 * 1024, expected_bytes - copied_bytes + 1)):
                if copied_bytes + len(chunk) > expected_bytes:
                    raise ArchiveSecurityError(f"壓縮檔成員實際大小超過預期: {member_name}")
                target.write(chunk)
                copied_bytes += len(chunk)
        if copied_bytes != expected_bytes:
            raise ArchiveSecurityError(f"壓縮檔成員實際大小小於預期: {member_name}")
        return copied_bytes


@contextmanager
def open_bounded_zip_writer(
    target: Path | str | BinaryIO,
    *,
    max_members: int | None = SAFE_ZIP_MAX_MEMBERS,
    max_total_bytes: int | None = SAFE_ZIP_MAX_TOTAL_BYTES,
    max_member_bytes: int | None = SAFE_ZIP_MAX_MEMBER_BYTES,
) -> Generator[_BoundedZipWriter]:
    """
    建立受限制的 ZIP 寫入器

    Args:
        target: ZIP 輸出檔案或二進位緩衝區
        max_members: 成員數量上限
        max_total_bytes: 總未壓縮輸出大小上限
        max_member_bytes: 單一成員大小上限

    Returns:
        已套用成員名稱與大小限制的 ZIP 寫入器
    """
    if isinstance(target, Path | str):
        with (
            open_regular_file_for_write(target) as output,
            zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=_ZIP_COMPRESSION_LEVEL) as archive,
        ):
            yield _BoundedZipWriter(
                archive,
                max_members=max_members,
                max_total_bytes=max_total_bytes,
                max_member_bytes=max_member_bytes,
            )
        return
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=_ZIP_COMPRESSION_LEVEL) as archive:
        yield _BoundedZipWriter(
            archive,
            max_members=max_members,
            max_total_bytes=max_total_bytes,
            max_member_bytes=max_member_bytes,
        )


def read_archive_metadata_bytes(
    archive: zipfile.ZipFile,
    member_name: str,
    *,
    max_bytes: int = ARCHIVE_METADATA_MAX_BYTES,
) -> bytes | None:
    """
    以固定大小上限讀取壓縮檔內的 metadata 成員

    Args:
        archive: 已開啟的 ZIP 壓縮檔
        member_name: 壓縮檔內的成員名稱
        max_bytes: 讀取的最大位元組數，超過此限制將回傳 None
    Returns:
        成員內容的位元組，或 None (成員不存在、為目錄、超過大小限制或讀取失敗)
    """
    try:
        limit = int(max_bytes)
        if limit < 0:
            return None
        member = archive.getinfo(member_name)
        if member.is_dir() or int(member.file_size) > limit:
            return None
        with archive.open(member, "r") as source:
            payload = source.read(limit + 1)
        return payload if len(payload) <= limit else None
    except KeyError, OSError, NotImplementedError, RuntimeError, ValueError, zipfile.BadZipFile:
        return None


def _is_safe_windows_archive_part(part: str) -> bool:
    """拒絕 NTFS ADS、保留裝置名與 Windows 會重新正規化的危險名稱"""
    if not part or part.endswith((" ", ".")):
        return False
    return not os.path.isreserved(part)


def _sanitize_archive_member_name(member_name: str) -> Path | None:
    """清理壓縮檔內部名稱，拒絕絕對路徑、父目錄參考與 Windows 危險名稱"""
    try:
        if not member_name:
            return None
        normalized_name = str(member_name).replace("\\", "/")
        if PureWindowsPath(normalized_name).drive:
            return None
        path = PurePosixPath(normalized_name)
        if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
            return None
        if any(not _is_safe_windows_archive_part(part) for part in path.parts):
            return None
        return Path(*path.parts)
    except TypeError, ValueError:
        return None


def _is_zip_symlink(member: zipfile.ZipInfo) -> bool:
    return ((member.external_attr >> 16) & 0o170000) == 0o120000


def _validate_zip_member_format(member: zipfile.ZipInfo) -> None:
    if member.flag_bits & 0x1:
        raise ArchiveSecurityError(f"壓縮檔包含不支援的加密成員: {member.filename}")
    if not member.is_dir() and member.compress_type not in _ALLOWED_ZIP_COMPRESSION_TYPES:
        raise ArchiveSecurityError(f"壓縮檔包含不支援的壓縮格式: {member.filename}")


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


def _member_path_key(path: Path) -> tuple[str, ...]:
    """以 Windows 大小寫不敏感語意建立目的路徑鍵值"""
    return tuple(part.casefold() for part in path.parts)


def _validate_member_path_collision(
    member: zipfile.ZipInfo,
    sanitized: Path,
    *,
    member_kinds: dict[tuple[str, ...], bool],
    parent_keys: set[tuple[str, ...]],
) -> None:
    key = _member_path_key(sanitized)
    if key in member_kinds:
        raise ArchiveSecurityError(f"壓縮檔包含重複或大小寫衝突的路徑: {member.filename}")
    if not member.is_dir() and key in parent_keys:
        raise ArchiveSecurityError(f"壓縮檔包含檔案/目錄路徑衝突: {member.filename}")

    for index in range(1, len(key)):
        parent_key = key[:index]
        if member_kinds.get(parent_key) is False:
            raise ArchiveSecurityError(f"壓縮檔包含檔案/目錄路徑衝突: {member.filename}")
        parent_keys.add(parent_key)

    member_kinds[key] = member.is_dir() or member.filename.endswith("/")


def safe_extract_zip(
    zip_path: Path,
    dest_dir: Path,
    progress_callback: Callable[[int, int], None] | None = None,
    *,
    max_members: int | None = SAFE_ZIP_MAX_MEMBERS,
    max_total_uncompressed_bytes: int | None = SAFE_ZIP_MAX_TOTAL_BYTES,
    max_member_uncompressed_bytes: int | None = SAFE_ZIP_MAX_MEMBER_BYTES,
    max_compression_ratio: int | None = SAFE_ZIP_MAX_COMPRESSION_RATIO,
    max_archive_bytes: int | None = SAFE_ZIP_MAX_ARCHIVE_BYTES,
) -> None:
    """
    安全解壓縮 ZIP，拒絕路徑穿越、符號連結、加密/非標準壓縮與異常大小

    Args:
        zip_path: ZIP 檔案路徑
        dest_dir: 解壓縮目的目錄
        progress_callback: 接收已處理位元組數與總位元組數的回呼
        max_members: ZIP 成員數量上限
        max_total_uncompressed_bytes: 解壓縮後的總位元組上限
        max_member_uncompressed_bytes: 單一成員的解壓縮位元組上限
        max_compression_ratio: 單一成員允許的最大壓縮比例
        max_archive_bytes: ZIP 實體檔案大小上限
    """
    dest_dir = resolve_stable_directory(dest_dir, create=True)
    with open_bounded_zip(zip_path, max_members=max_members, max_archive_bytes=max_archive_bytes) as archive:
        members = archive.infolist()
        if max_members is not None and len(members) > max_members:
            raise ArchiveSecurityError("壓縮檔成員數量超過安全上限")

        total_bytes = sum(max(0, int(member.file_size)) for member in members if not member.is_dir())
        if max_total_uncompressed_bytes is not None and total_bytes > max_total_uncompressed_bytes:
            raise ArchiveSecurityError("壓縮檔解壓後大小超過安全上限")

        member_kinds: dict[tuple[str, ...], bool] = {}
        parent_keys: set[tuple[str, ...]] = set()
        sanitized_members: list[tuple[zipfile.ZipInfo, Path]] = []
        for member in members:
            if _is_zip_symlink(member):
                raise ArchiveSecurityError(f"壓縮檔包含不支援的符號連結: {member.filename}")
            _validate_zip_member_format(member)
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
            _validate_member_path_collision(
                member,
                sanitized,
                member_kinds=member_kinds,
                parent_keys=parent_keys,
            )
            sanitized_members.append((member, sanitized))

        extracted_bytes = 0
        if progress_callback is not None:
            progress_callback(0, total_bytes)
        for member, sanitized in sanitized_members:
            member_path = dest_dir / sanitized
            if member.is_dir() or member.filename.endswith("/"):
                resolve_stable_directory(member_path, create=True)
                continue
            member_path = resolve_stable_path(member_path, create_parent=True)
            if not is_path_within(dest_dir, member_path, strict=False):
                raise ArchiveSecurityError(f"壓縮檔嘗試路徑穿越: {member.filename}")
            member_extracted_bytes = 0
            with archive.open(member, "r") as source, open_regular_file_for_write(member_path) as target:
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


__all__ = [
    "SAFE_ZIP_MAX_ARCHIVE_BYTES",
    "open_bounded_zip",
    "open_bounded_zip_writer",
    "read_archive_metadata_bytes",
    "safe_extract_zip",
]
