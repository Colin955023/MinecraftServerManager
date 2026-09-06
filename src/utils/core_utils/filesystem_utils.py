"""一般檔案系統操作工具"""

from __future__ import annotations

import ctypes
import os
import shutil
import stat
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping
from contextlib import contextmanager, suppress
from ctypes import wintypes
from pathlib import Path
from typing import BinaryIO

SAFE_TEXT_FILE_MAX_BYTES = 2 * 1024 * 1024
SAFE_DIRECTORY_MAX_FILES = 100_000
SAFE_DIRECTORY_MAX_TOTAL_BYTES = 128 * 1024 * 1024 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_COPY_BUFFER_BYTES = 1024 * 1024
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_ALL = _FILE_SHARE_READ | _FILE_SHARE_WRITE | 0x00000004
_OPEN_EXISTING = 3
_CREATE_ALWAYS = 2


def _metadata_is_reparse_point(metadata: os.stat_result) -> bool:
    """由不跟隨連結的 metadata 判斷 reparse point"""
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def is_reparse_point(path: Path | str) -> bool:
    """
    判斷路徑是否為符號連結、junction 或 Windows reparse point

    Args:
        path: 要檢查的路徑

    Returns:
        路徑是 reparse point 時回傳 True
    """
    try:
        target = resolve_stable_path(path)
        metadata = target.lstat()
        return _metadata_is_reparse_point(metadata)
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _path_is_within_resolved(base_dir: Path, target_path: Path) -> bool:
    return target_path.is_relative_to(base_dir)


def _normalize_windows_handle_path(value: str) -> Path:
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith(("\\\\?\\", "\\\\.\\")):
        value = value[4:]
    return Path(value)


def _windows_handle_is_reparse_point(handle: int) -> bool:
    class _FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("file_attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info = kernel32.GetFileInformationByHandleEx
    get_info.argtypes = [wintypes.HANDLE, wintypes.INT, ctypes.c_void_p, wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    info = _FileAttributeTagInfo()
    if not get_info(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        error = ctypes.get_last_error()
        raise OSError(error, "無法取得檔案 reparse 狀態")
    return bool(info.file_attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _windows_handle_path(handle: int) -> Path:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_path = kernel32.GetFinalPathNameByHandleW
    get_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    get_path.restype = wintypes.DWORD
    capacity = 512
    while capacity <= 32 * 1024:
        buffer = ctypes.create_unicode_buffer(capacity)
        length = get_path(handle, buffer, capacity, 0)
        if length == 0:
            error = ctypes.get_last_error()
            raise OSError(error, "無法取得檔案實際路徑")
        if length < capacity:
            return _normalize_windows_handle_path(buffer.value)
        capacity *= 2
    raise OSError("檔案實際路徑過長")


def _open_regular_file_windows(
    target: Path,
    allowed_root: Path | None,
    *,
    writable: bool = False,
) -> BinaryIO:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = create_file(
        str(target),
        _GENERIC_WRITE if writable else _GENERIC_READ,
        _FILE_SHARE_ALL,
        None,
        _CREATE_ALWAYS if writable else _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        error = ctypes.get_last_error()
        raise OSError(error, "無法開啟檔案")

    file_descriptor: int | None = None
    file_object: BinaryIO | None = None
    try:
        open_flags = (os.O_WRONLY if writable else os.O_RDONLY) | os.O_BINARY
        file_descriptor = msvcrt.open_osfhandle(int(handle), open_flags)
        file_object = os.fdopen(file_descriptor, "wb" if writable else "rb")
        file_descriptor = None
        if _windows_handle_is_reparse_point(int(handle)):
            raise OSError("檔案是 reparse point")
        if not stat.S_ISREG(os.fstat(file_object.fileno()).st_mode):
            raise OSError("檔案不是一般檔案")
        if allowed_root is not None and not _path_is_within_resolved(allowed_root, _windows_handle_path(int(handle))):
            raise OSError("檔案實際路徑超出允許根目錄")
        return file_object
    except Exception:
        if file_object is not None:
            file_object.close()
        elif file_descriptor is not None:
            os.close(file_descriptor)
        else:
            close_handle(handle)
        raise


def _open_directory_handle_windows(target: Path, *, share_mode: int = _FILE_SHARE_ALL) -> tuple[int, Path]:
    """開啟資料夾並保留 handle，回傳 handle 與實際路徑"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = create_file(
        str(target),
        _GENERIC_READ,
        share_mode,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        error = ctypes.get_last_error()
        raise OSError(error, "無法開啟資料夾")
    try:
        handle_value = int(handle)
        if _windows_handle_is_reparse_point(handle_value):
            raise OSError("資料夾是 reparse point")
        actual_path = _windows_handle_path(handle_value)
        if not actual_path.is_dir():
            raise OSError("路徑不是資料夾")
        return handle_value, actual_path
    except Exception:
        close_handle(handle)
        raise


def _absolute_path(path: Path | str) -> Path:
    """只做絕對化，不追蹤符號連結或 reparse point"""
    return Path(os.fspath(path)).absolute()


@contextmanager
def _stable_directory_handle(path: Path | str, *, create: bool = False) -> Generator[Path]:
    """逐層開啟資料夾並在整個操作期間保留防刪除 handle"""
    absolute = _absolute_path(path)
    current = Path(absolute.anchor)
    handles: list[int] = []
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    try:
        handle, current = _open_directory_handle_windows(
            current,
            share_mode=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
        )
        handles.append(handle)
        for component in absolute.parts[1:]:
            candidate = current / component
            if not candidate.exists():
                if not create:
                    raise FileNotFoundError(candidate)
                with suppress(FileExistsError):
                    candidate.mkdir()
            handle, current = _open_directory_handle_windows(
                candidate,
                share_mode=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
            )
            handles.append(handle)
        yield current
    finally:
        for handle in reversed(handles):
            close_handle(handle)


def resolve_stable_directory(path: Path | str, *, create: bool = False) -> Path:
    """
    逐層驗證資料夾並回傳不含 reparse point 的實際路徑

    Args:
        path: 要驗證的資料夾路徑
        create: 資料夾不存在時是否建立

    Returns:
        已由 Windows handle 驗證的實際資料夾路徑
    """
    with _stable_directory_handle(path, create=create) as stable_path:
        return stable_path


@contextmanager
def stable_directory(path: Path | str, *, create: bool = False) -> Generator[Path]:
    """
    在操作期間保留已驗證資料夾的 Windows handle

    Args:
        path: 要驗證的資料夾路徑
        create: 資料夾不存在時是否建立

    Returns:
        已驗證且在 context manager 期間受保護的實際資料夾路徑
    """
    with _stable_directory_handle(path, create=create) as stable_path:
        yield stable_path


def resolve_stable_path(path: Path | str, *, create_parent: bool = False) -> Path:
    """
    驗證路徑父資料夾並回傳固定實際父路徑下的目標

    Args:
        path: 要驗證的目標路徑
        create_parent: 父資料夾不存在時是否建立

    Returns:
        已由 Windows handle 驗證父資料夾的目標路徑
    """
    absolute = _absolute_path(path)
    parent = resolve_stable_directory(absolute.parent, create=create_parent)
    return parent / absolute.name


def open_regular_file_for_write(path: Path | str) -> BinaryIO:
    """
    以不跟隨 reparse point 的方式建立或截斷一般檔案

    Args:
        path: 要建立或截斷的檔案路徑

    Returns:
        已開啟的二進位可寫檔案物件
    """
    target = resolve_stable_path(path, create_parent=True)
    if is_reparse_point(target):
        raise OSError("寫入目標是符號連結或 reparse point")
    return _open_regular_file_windows(target, target.parent, writable=True)


def open_regular_file(path: Path | str, *, allowed_root: Path | str | None = None) -> BinaryIO:
    """
    以不跟隨 reparse point 的方式開啟一般檔案，並可限制實際路徑根目錄

    Args:
        path: 要開啟的檔案路徑
        allowed_root: 可選的實際路徑根目錄

    Returns:
        已開啟的二進位唯讀檔案物件
    """
    target = Path(path)
    if is_reparse_point(target):
        raise OSError("檔案是符號連結或 reparse point")
    try:
        metadata = target.stat(follow_symlinks=False)
    except OSError as e:
        raise OSError("檔案不存在或無法取得資訊") from e
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError("檔案不是一般檔案")

    root = None
    if allowed_root is not None:
        root = resolve_stable_directory(allowed_root)
        if not _path_is_within_resolved(root, target):
            raise OSError("檔案路徑超出允許根目錄")

    return _open_regular_file_windows(target, root)


def is_path_within(base_dir: Path, target_path: Path, *, strict: bool = True) -> bool:
    """
    檢查目標路徑是否位於基準目錄本身或其下

    Args:
        base_dir: 基準目錄
        target_path: 待檢查路徑
        strict: 是否要求目標路徑已存在

    Returns:
        目標位於基準目錄本身或其下時回傳 True
    """
    try:
        base_resolved = base_dir.resolve(strict=True)
        target_resolved = target_path.resolve(strict=strict)
    except FileNotFoundError, OSError:
        return False
    return target_resolved.is_relative_to(base_resolved)


def read_bytes_file(
    path: Path | str,
    *,
    max_bytes: int | None = None,
    allowed_root: Path | str | None = None,
) -> bytes | None:
    """
    以可選位元組上限讀取一般檔案，拒絕符號連結與 reparse point

    Args:
        path: 要讀取的檔案路徑
        max_bytes: 可讀取的最大位元組數；省略時不限制
        allowed_root: 可選的實際路徑根目錄

    Returns:
        檔案內容；檔案不安全或超過上限時回傳 None
    """
    try:
        source = open_regular_file(path, allowed_root=allowed_root)
        with source:
            if max_bytes is None:
                return source.read()
            limit = int(max_bytes)
            if limit < 0 or os.fstat(source.fileno()).st_size > limit:
                return None
            payload = source.read(limit + 1)
        return payload if len(payload) <= limit else None
    except OSError, ValueError:
        return None


def read_text_file(
    path: Path,
    encoding: str = "utf-8",
    errors: str = "replace",
    *,
    max_bytes: int | None = None,
    allowed_root: Path | str | None = None,
) -> str | None:
    """
    讀取文字檔案

    Args:
        path: 文字檔案路徑
        encoding: 文字編碼
        errors: 解碼錯誤處理方式
        max_bytes: 可選的原始位元組大小上限
        allowed_root: 可選的實際路徑根目錄

    Returns:
        文字內容；檔案不存在或讀取失敗時回傳 None
    """
    try:
        payload = read_bytes_file(path, max_bytes=max_bytes, allowed_root=allowed_root)
        return payload.decode(encoding, errors=errors) if payload is not None else None
    except LookupError, UnicodeError:
        return None


def _delete_path(path: Path) -> bool:
    try:
        if not os.path.lexists(path):
            return True
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or is_reparse_point(path):
            return False
        if stat.S_ISDIR(metadata.st_mode):
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
    except OSError:
        return False


def delete_within(base_dir: Path | str, path: Path | str) -> bool:
    """
    僅刪除基準目錄內的子項目，拒絕刪除基準目錄本身

    Args:
        base_dir: 允許刪除的基準目錄
        path: 待刪除路徑

    Returns:
        路徑合法且刪除成功時回傳 True
    """
    try:
        with _stable_directory_handle(base_dir) as base:
            raw_target = _absolute_path(path)
            if raw_target == base or not _path_is_within_resolved(base, raw_target):
                return False
            with _stable_directory_handle(raw_target.parent) as target_parent:
                target = target_parent / raw_target.name
                if target == base or not _path_is_within_resolved(base, target) or is_reparse_point(target):
                    return False
                return _delete_path(target)
    except OSError, ValueError:
        return False


def _move_path(src: Path, dst: Path) -> bool:
    try:
        if not os.path.lexists(src) or is_reparse_point(src):
            return False
        src.replace(dst)
        return True
    except OSError:
        return False


def move_within(base_dir: Path | str, src: Path, dst: Path) -> bool:
    """
    僅在來源與目的地都是基準目錄內的子項目時搬移

    Args:
        base_dir: 允許搬移的基準目錄
        src: 來源路徑
        dst: 目的路徑

    Returns:
        路徑合法且搬移成功時回傳 True
    """
    try:
        with _stable_directory_handle(base_dir) as base:
            raw_src = _absolute_path(src)
            raw_dst = _absolute_path(dst)
            if raw_src == base or raw_dst == base:
                return False
            if not _path_is_within_resolved(base, raw_src) or not _path_is_within_resolved(base, raw_dst):
                return False
            with (
                _stable_directory_handle(raw_src.parent) as src_parent,
                _stable_directory_handle(raw_dst.parent, create=True) as dst_parent,
            ):
                src_resolved = src_parent / raw_src.name
                dst_resolved = dst_parent / raw_dst.name
                if (
                    src_resolved == base
                    or dst_resolved == base
                    or not _path_is_within_resolved(base, src_resolved)
                    or not _path_is_within_resolved(base, dst_resolved)
                    or is_reparse_point(dst_resolved)
                ):
                    return False
                return _move_path(src_resolved, dst_resolved)
    except OSError, ValueError:
        return False


def move_within_strict(base_dir: Path | str, src: Path, dst: Path) -> None:
    """
    安全移動基準目錄內項目並保留原始系統錯誤

    Args:
        base_dir: 允許搬移的基準目錄
        src: 來源路徑
        dst: 目的路徑
    """
    with _stable_directory_handle(base_dir) as base:
        raw_source = _absolute_path(src)
        raw_destination = _absolute_path(dst)
        if (
            raw_source == base
            or raw_destination == base
            or not _path_is_within_resolved(base, raw_source)
            or not _path_is_within_resolved(base, raw_destination)
            or raw_source.parent != base
            or raw_destination.parent != base
        ):
            raise ValueError("移動來源與目的地必須是基準目錄的直接子項目")
        if is_reparse_point(raw_source) or os.path.lexists(raw_destination):
            raise OSError("移動來源不安全或目的地已存在")
        raw_source.replace(raw_destination)


def _copy_regular_file(
    src: Path,
    dst: Path,
    *,
    allowed_root: Path | None = None,
    max_bytes: int | None = None,
) -> bool:
    try:
        stable_dst = resolve_stable_path(dst, create_parent=True)
        if is_reparse_point(stable_dst):
            return False
        with (
            open_regular_file(src, allowed_root=allowed_root) as source,
            open_regular_file_for_write(stable_dst) as target,
        ):
            if max_bytes is None:
                shutil.copyfileobj(source, target, length=_COPY_BUFFER_BYTES)
            else:
                remaining = max(0, int(max_bytes))
                while chunk := source.read(min(_COPY_BUFFER_BYTES, remaining + 1)):
                    if len(chunk) > remaining:
                        return False
                    target.write(chunk)
                    remaining -= len(chunk)
        with suppress(OSError):
            shutil.copystat(src, stable_dst, follow_symlinks=False)
        return True
    except OSError:
        return False


def list_bounded_directory(
    path: Path | str,
    *,
    max_entries: int = SAFE_DIRECTORY_MAX_FILES,
    reject_reparse: bool = True,
) -> list[Path]:
    """
    列出單層目錄，並在保留過多項目前拒絕處理

    Args:
        path: 要列出的目錄
        max_entries: 允許列出的最大項目數
        reject_reparse: 是否拒絕目錄中的 reparse point

    Returns:
        目錄項目路徑清單
    """
    limit = int(max_entries)
    if limit < 0:
        raise ValueError("目錄項目上限不可為負數")
    directory = Path(path)
    if is_reparse_point(directory):
        raise OSError(f"目錄不可為 reparse point: {directory}")
    entries: list[Path] = []
    with os.scandir(directory) as iterator:
        for entry in iterator:
            if len(entries) >= limit:
                raise OSError(f"目錄項目數超過安全上限 {limit}")
            candidate = Path(entry.path)
            if reject_reparse and is_reparse_point(candidate):
                raise OSError(f"目錄包含 reparse point: {candidate}")
            entries.append(candidate)
    return entries


def walk_bounded_tree(
    path: Path | str,
    *,
    ignore: Callable[[str, list[str]], Iterable[str]] | None = None,
    max_entries: int = SAFE_DIRECTORY_MAX_FILES,
) -> Iterator[tuple[Path, list[str], list[str]]]:
    """
    逐層巡覽目錄，限制總項目數且不跟隨 reparse point

    Args:
        path: 要巡覽的根目錄
        ignore: 回傳要忽略的項目名稱回呼
        max_entries: 允許巡覽的最大項目數

    Yields:
        目前目錄、子目錄名稱清單與檔案名稱清單
    """
    limit = int(max_entries)
    if limit < 0:
        raise ValueError("目錄項目上限不可為負數")
    root = Path(path)
    try:
        if _metadata_is_reparse_point(root.stat(follow_symlinks=False)):
            raise OSError(f"目錄包含 reparse point: {root}")
    except FileNotFoundError as e:
        raise OSError(f"目錄不存在: {root}") from e
    pending = [root]
    visited_entries = 0
    while pending:
        current = pending.pop()
        dirs: list[str] = []
        files: list[str] = []
        with os.scandir(current) as iterator:
            for entry in iterator:
                visited_entries += 1
                if visited_entries > limit:
                    raise OSError(f"目錄項目數超過安全上限 {limit}")
                candidate = Path(entry.path)
                metadata = entry.stat(follow_symlinks=False)
                if _metadata_is_reparse_point(metadata):
                    raise OSError(f"目錄包含 reparse point: {candidate}")
                if stat.S_ISDIR(metadata.st_mode):
                    dirs.append(entry.name)
                elif stat.S_ISREG(metadata.st_mode):
                    files.append(entry.name)
                else:
                    raise OSError(f"目錄包含非一般檔案項目: {candidate}")
        dirs.sort(key=str.casefold)
        files.sort(key=str.casefold)
        if ignore is not None:
            ignored = set(ignore(str(current), dirs + files))
            dirs = [name for name in dirs if name not in ignored]
            files = [name for name in files if name not in ignored]
        yield current, dirs, files
        pending.extend(current / name for name in reversed(dirs))


def find_first_reparse_point(
    path: Path | str,
    *,
    max_entries: int = SAFE_DIRECTORY_MAX_FILES,
) -> Path | None:
    """
    以項目上限巡覽目錄並回傳第一個 reparse point

    Args:
        path: 要巡覽的檔案或目錄
        max_entries: 允許巡覽的最大項目數

    Returns:
        找到時回傳 reparse point，否則回傳 None
    """
    limit = int(max_entries)
    if limit < 0:
        raise ValueError("目錄項目上限不可為負數")
    root = Path(path)
    try:
        if _metadata_is_reparse_point(root.stat(follow_symlinks=False)):
            return root
    except FileNotFoundError:
        return None
    pending = [root]
    visited_entries = 0
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as iterator:
                for entry in iterator:
                    visited_entries += 1
                    if visited_entries > limit:
                        raise ValueError(f"目錄項目數超過安全上限 {limit}")
                    candidate = Path(entry.path)
                    metadata = entry.stat(follow_symlinks=False)
                    if _metadata_is_reparse_point(metadata):
                        return candidate
                    if stat.S_ISDIR(metadata.st_mode):
                        pending.append(candidate)
        except FileNotFoundError:
            continue
    return None


def copy_file(src: Path, dst: Path) -> bool:
    """
    複製單一檔案並建立目的目錄

    Args:
        src: 來源檔案
        dst: 目的檔案

    Returns:
        複製成功時回傳 True
    """
    return _copy_regular_file(src, dst)


def copy_dir(
    src: Path,
    dst: Path,
    ignore_patterns: list[str] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    manifest: Mapping[str, tuple[int, int]] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> bool:
    """
    複製目錄並回報已複製檔案數

    Args:
        src: 來源目錄
        dst: 目的目錄
        ignore_patterns: 要忽略的檔名樣式
        progress_callback: 接收已複製檔案數與總檔案數的回呼

    Returns:
        複製成功時回傳 True
    """
    try:
        src = resolve_stable_directory(src)
        if is_reparse_point(src) or not src.exists() or not src.is_dir():
            return False
        ignore = shutil.ignore_patterns(*ignore_patterns) if ignore_patterns else None
        total_files = len(manifest) if manifest is not None else 0
        total_bytes = sum(item[0] for item in manifest.values()) if manifest is not None else 0
        if manifest is None:
            for root_path, _dirs, files in walk_bounded_tree(src, ignore=ignore):
                for file_name in files:
                    metadata = (root_path / file_name).stat(follow_symlinks=False)
                    if not stat.S_ISREG(metadata.st_mode):
                        return False
                    total_files += 1
                    total_bytes += metadata.st_size
                    if total_files > SAFE_DIRECTORY_MAX_FILES or total_bytes > SAFE_DIRECTORY_MAX_TOTAL_BYTES:
                        return False

        copied_files = 0
        copied_bytes = 0
        dst = resolve_stable_directory(dst, create=True)
        if is_reparse_point(dst):
            return False
        if progress_callback is not None:
            progress_callback(0, total_files)
        seen_files: set[str] = set()
        for root_path, dirs, files in walk_bounded_tree(src, ignore=ignore):
            if cancel_check is not None and cancel_check():
                return False
            relative_root = root_path.relative_to(src)
            target_root = resolve_stable_directory(
                dst if relative_root == Path() else dst / relative_root,
                create=True,
            )
            if is_reparse_point(target_root):
                return False
            for dir_name in dirs:
                if is_reparse_point(resolve_stable_directory(target_root / dir_name, create=True)):
                    return False
            for file_name in files:
                if copied_files >= SAFE_DIRECTORY_MAX_FILES:
                    return False
                file_path = root_path / file_name
                metadata = file_path.stat(follow_symlinks=False)
                if not stat.S_ISREG(metadata.st_mode):
                    return False
                relative_file = (relative_root / file_name).as_posix().casefold()
                if manifest is not None:
                    expected = manifest.get(relative_file)
                    if expected is None or expected != (metadata.st_size, metadata.st_mtime_ns):
                        return False
                    seen_files.add(relative_file)
                remaining_bytes = SAFE_DIRECTORY_MAX_TOTAL_BYTES - copied_bytes
                if not _copy_regular_file(
                    file_path,
                    target_root / file_name,
                    allowed_root=src,
                    max_bytes=remaining_bytes,
                ):
                    return False
                copied_files += 1
                copied_bytes += metadata.st_size
                if progress_callback is not None and total_files > 0:
                    progress_callback(copied_files, total_files)
        if progress_callback is not None:
            progress_callback(copied_files, total_files)
        return manifest is None or seen_files == set(manifest)
    except OSError:
        return False


__all__ = [
    "SAFE_DIRECTORY_MAX_FILES",
    "SAFE_DIRECTORY_MAX_TOTAL_BYTES",
    "SAFE_TEXT_FILE_MAX_BYTES",
    "copy_dir",
    "copy_file",
    "delete_within",
    "is_path_within",
    "is_reparse_point",
    "list_bounded_directory",
    "move_within",
    "move_within_strict",
    "open_regular_file",
    "open_regular_file_for_write",
    "read_bytes_file",
    "read_text_file",
    "resolve_stable_directory",
    "resolve_stable_path",
    "stable_directory",
    "walk_bounded_tree",
]
