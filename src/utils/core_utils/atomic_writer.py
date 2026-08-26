"""
原子性寫入工具
提供 JSON、文字與 bytes 的同目錄臨時檔案寫入，並在成功後以原子方式替換目標檔案
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import orjson

from src.utils import get_logger, is_path_within

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


def _atomic_write_payload(path: Path | str, writer: Callable[[Any], None], mode: str, **open_kwargs) -> bool:
    """以暫存檔與原子替換寫入 payload"""
    p = Path(path)
    with _get_path_lock(p):
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        for attempt in range(_RETRY_COUNT):
            tmp_name = f"{p.name}.{os.getpid()}.{threading.get_ident()}.{int(time.time() * 1000)}.{attempt}.tmp"
            tmp_path = p.with_name(tmp_name)
            try:
                with tmp_path.open(mode, **open_kwargs) as file_obj:
                    writer(file_obj)
                    file_obj.flush()
                    best_effort_fsync(file_obj)
                _replace_file(tmp_path, p)
                return True
            except OSError:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    logger.debug(f"嘗試移除臨時檔案 {tmp_path} 時失敗；忽略錯誤")
                if attempt + 1 >= _RETRY_COUNT:
                    return False
                time.sleep(_RETRY_DELAY * (attempt + 1))
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
    p = Path(path)
    try:
        opt = orjson.OPT_INDENT_2 if indent == 2 else 0
        opt |= orjson.OPT_NON_STR_KEYS
        payload_bytes = orjson.dumps(data, option=opt)
    except TypeError:
        return False

    with _get_path_lock(p):
        if skip_if_unchanged and p.exists():
            try:
                if p.read_bytes() == payload_bytes:
                    return True
            except OSError:
                logger.debug(f"無法讀取現有檔案以判斷是否相同，將覆寫: {p}")

        return atomic_write_bytes(p, payload_bytes)


def atomic_replace_file(source: Path | str, target: Path | str) -> bool:
    """
    將已完成的同檔案系統暫存檔原子提交到目標路徑

    Args:
        source: 已完成寫入的來源暫存檔
        target: 要取代的目標檔案

    Returns:
        替換成功時回傳 True，失敗時回傳 False
    """
    source_path = Path(source)
    target_path = Path(target)
    with _get_path_lock(target_path):
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
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
        base_path = Path(base_dir).resolve(strict=True)
        source_path = Path(source).resolve(strict=True)
        target_path = Path(target).resolve(strict=False)
        if source_path.is_dir():
            return False
        if not is_path_within(base_path, source_path, strict=False):
            return False
        if not is_path_within(base_path, target_path, strict=False):
            return False
        return atomic_replace_file(source_path, target_path)
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
