"""一般檔案系統操作工具"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path


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
    try:
        target_resolved.relative_to(base_resolved)
        return True
    except ValueError:
        return False


def read_text_file(path: Path, encoding: str = "utf-8", errors: str = "replace") -> str | None:
    """
    讀取文字檔案

    Args:
        path: 文字檔案路徑
        encoding: 文字編碼
        errors: 解碼錯誤處理方式

    Returns:
        文字內容；檔案不存在或讀取失敗時回傳 None
    """
    try:
        if not path.exists():
            return None
        return path.read_text(encoding=encoding, errors=errors)
    except OSError:
        return None


def _delete_path(path: Path) -> bool:
    try:
        if not path.exists():
            return True
        if path.is_dir():
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
        base = Path(base_dir).resolve(strict=True)
        target = Path(path).resolve(strict=False)
        if target == base or not is_path_within(base, target, strict=False):
            return False
        return _delete_path(target)
    except OSError:
        return False


def _move_path(src: Path, dst: Path) -> bool:
    try:
        if not src.exists():
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(src, dst)
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
        base = Path(base_dir).resolve(strict=True)
        src_resolved = src.resolve(strict=False)
        dst_resolved = dst.resolve(strict=False)
        if src_resolved == base or dst_resolved == base:
            return False
        if not is_path_within(base, src_resolved, strict=False):
            return False
        if not is_path_within(base, dst_resolved, strict=False):
            return False
        return _move_path(src_resolved, dst_resolved)
    except OSError:
        return False


def copy_file(src: Path, dst: Path) -> bool:
    """
    複製單一檔案並建立目的目錄

    Args:
        src: 來源檔案
        dst: 目的檔案

    Returns:
        複製成功時回傳 True
    """
    try:
        if not src.exists():
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except OSError:
        return False


def copy_dir(
    src: Path,
    dst: Path,
    ignore_patterns: list[str] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
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
        if not src.exists() or not src.is_dir():
            return False
        ignore = shutil.ignore_patterns(*ignore_patterns) if ignore_patterns else None
        entries: list[tuple[Path, list[str], list[str]]] = []
        for root, dirs, files in os.walk(src, topdown=True):
            root_path = Path(root)
            if ignore is not None:
                ignored = set(ignore(str(root_path), [*dirs, *files]))
                dirs[:] = [name for name in dirs if name not in ignored]
                files = [name for name in files if name not in ignored]
            entries.append((root_path, list(dirs), list(files)))

        total_files = sum(len(files) for _root, _dirs, files in entries)
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


__all__ = ["copy_dir", "copy_file", "delete_within", "is_path_within", "move_within", "read_text_file"]
