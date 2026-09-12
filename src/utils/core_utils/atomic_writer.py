"""
原子性寫入工具
提供 JSON、文字與 bytes 的同目錄暫存檔案寫入，並在成功後以原子方式替換目標檔案
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import orjson

from .filesystem_utils import (
    is_reparse_point,
    move_within,
    read_bytes_file,
    resolve_stable_directory,
    resolve_stable_path,
    stable_directory,
)
from .logger import get_logger

logger = get_logger().bind(component="AtomicWriter")

_RETRY_COUNT = 3
_RETRY_DELAY = 0.02
_PATH_LOCKS = tuple(threading.RLock() for _ in range(64))


def _get_path_lock(path: Path) -> threading.RLock:
    """取得目標路徑共用鎖，避免同行程寫入互相覆蓋暫存結果"""
    try:
        key = str(path.resolve())
    except OSError:
        key = str(path.absolute())
    return _PATH_LOCKS[hash(key) % len(_PATH_LOCKS)]


def _best_effort_sync_dir(path: Path) -> None:
    """盡力同步目錄 metadata；平台不支援時忽略錯誤"""
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


def _replace_file(source: Path, target: Path) -> None:
    """以原子替換提交檔案，並盡力同步目標目錄"""
    source.replace(target)
    _best_effort_sync_dir(target.parent)


def best_effort_fsync(file_obj) -> None:
    """
    對檔案描述元執行 fsync，不將平台限制視為錯誤

    Args:
        file_obj: 已開啟且可取得 fileno 的檔案物件
    """
    try:
        os.fsync(file_obj.fileno())
    except AttributeError, OSError, ValueError:
        return


def _atomic_write_payload_stable_locked(
    path: Path,
    stable_parent: Path,
    writer: Callable[[Any], None],
    mode: str,
    **open_kwargs,
) -> bool:
    """在已穩定化目錄與已持有目標鎖的前提下寫入 payload"""
    if is_reparse_point(path):
        return False
    for attempt in range(_RETRY_COUNT):
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode=mode,
                delete=False,
                dir=stable_parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                **open_kwargs,
            ) as file_obj:
                tmp_path = Path(file_obj.name)
                writer(file_obj)
                file_obj.flush()
                best_effort_fsync(file_obj)
            if not move_within(stable_parent, tmp_path, path):
                raise OSError("無法安全提交原子寫入")
            _best_effort_sync_dir(stable_parent)
            return True
        except OSError:
            try:
                if tmp_path is not None and tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                logger.debug("嘗試移除暫存檔案 %s 時失敗；忽略錯誤", tmp_path)
            if attempt + 1 >= _RETRY_COUNT:
                return False
            time.sleep(_RETRY_DELAY * (attempt + 1))
    return False


def _atomic_write_payload(path: Path | str, writer: Callable[[Any], None], mode: str, **open_kwargs) -> bool:
    """以暫存檔與原子替換寫入 payload"""
    try:
        p = resolve_stable_path(path, create_parent=True)
        with stable_directory(p.parent) as stable_parent:
            p = stable_parent / p.name
            with _get_path_lock(p):
                return _atomic_write_payload_stable_locked(p, stable_parent, writer, mode, **open_kwargs)
    except OSError:
        return False


def atomic_write_json(path: Path | str, data, indent: int = 2, *, skip_if_unchanged: bool = False) -> bool:
    """
    以原子方式寫入 JSON 檔案

    Args:
        path: 目標檔案路徑
        data: 要寫入的資料
        indent: JSON 縮排層級（支援 0 或 2）
        skip_if_unchanged: 若內容相同則略過寫入

    Returns:
        寫入成功時回傳 True，失敗時回傳 False
    """
    try:
        opt = orjson.OPT_INDENT_2 if indent == 2 else 0
        opt |= orjson.OPT_NON_STR_KEYS
        payload_bytes = orjson.dumps(data, option=opt)
    except TypeError:
        return False
    if not skip_if_unchanged:
        return atomic_write_bytes(path, payload_bytes)

    try:
        p = resolve_stable_path(path, create_parent=True)
        with stable_directory(p.parent) as stable_parent:
            p = stable_parent / p.name
            with _get_path_lock(p):
                if is_reparse_point(p):
                    return False
                if p.exists():
                    existing_payload = read_bytes_file(p, max_bytes=len(payload_bytes), allowed_root=stable_parent)
                    if existing_payload == payload_bytes:
                        return True
                    if existing_payload is None:
                        logger.debug("無法讀取現有檔案以判斷是否相同，將覆寫: %s", p)
                return _atomic_write_payload_stable_locked(
                    p,
                    stable_parent,
                    lambda file_obj: file_obj.write(payload_bytes),
                    "wb",
                )
    except OSError:
        return False


def atomic_replace_file(source: Path | str, target: Path | str) -> bool:
    """
    將已完成的同檔案系統暫存檔原子提交到目標路徑

    Args:
        source: 已完成寫入的來源暫存檔
        target: 要取代的目標檔案

    Returns:
        替換成功時回傳 True，失敗時回傳 False
    """
    try:
        source_path = resolve_stable_path(source)
        target_path = resolve_stable_path(target, create_parent=True)
    except OSError:
        return False
    try:
        with (
            stable_directory(source_path.parent) as source_parent,
            stable_directory(target_path.parent, create=True) as target_parent,
        ):
            source_path = source_parent / source_path.name
            target_path = target_parent / target_path.name
            if source_path.is_dir() or is_reparse_point(source_path) or is_reparse_point(target_path):
                return False
            with _get_path_lock(target_path):
                _replace_file(source_path, target_path)
                return True
    except OSError:
        return False


def atomic_replace_file_within(
    base_dir: Path | str,
    source: Path | str,
    target: Path | str,
) -> bool:
    """
    僅在來源與目標都位於指定目錄內時，以原子方式替換檔案

    Args:
        base_dir: 允許操作的根目錄
        source: 已完成寫入的來源暫存檔
        target: 要取代的目標檔案

    Returns:
        替換成功時回傳 True，失敗時回傳 False
    """
    try:
        base_path = resolve_stable_directory(base_dir)
        source_path = resolve_stable_path(source)
        target_path = resolve_stable_path(target, create_parent=True)
        if source_path.is_dir() or is_reparse_point(source_path) or is_reparse_point(target_path):
            return False
        with _get_path_lock(target_path):
            return move_within(base_path, source_path, target_path)
    except OSError:
        return False


def atomic_write_text(
    path: Path | str,
    content: str,
    *,
    encoding: str = "utf-8",
    errors: str | None = None,
    newline: str | None = None,
) -> bool:
    """
    以原子方式寫入文字檔案

    Args:
        path: 目標檔案路徑
        content: 要寫入的文字內容
        encoding: 文字編碼
        errors: 編碼錯誤處理方式
        newline: 換行處理方式

    Returns:
        寫入成功時回傳 True，失敗時回傳 False
    """
    return _atomic_write_payload(
        path,
        lambda file_obj: file_obj.write(content),
        "w",
        encoding=encoding,
        errors=errors,
        newline=newline,
    )


def atomic_write_bytes(path: Path | str, content: bytes) -> bool:
    """
    以原子方式寫入二進位檔案

    Args:
        path: 目標檔案路徑
        content: 要寫入的位元組內容

    Returns:
        寫入成功時回傳 True，失敗時回傳 False
    """
    return _atomic_write_payload(path, lambda f: f.write(content), "wb")


__all__ = [
    "atomic_replace_file",
    "atomic_replace_file_within",
    "atomic_write_bytes",
    "atomic_write_json",
    "atomic_write_text",
]
