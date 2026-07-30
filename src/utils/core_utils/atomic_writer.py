"""
原子性寫入工具。
提供 JSON、文字與 bytes 的同目錄臨時檔 + `os.replace` 寫入流程，並盡力 fsync。
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .logger import get_logger

logger = get_logger().bind(component="AtomicWriter")

_RETRY_COUNT = 3
_RETRY_DELAY = 0.02


def best_effort_fsync(file_obj) -> None:
    """
    對檔案描述元執行 fsync，不將平台限制視為錯誤。

    Args:
        file_obj: 已開啟且可取得 fileno 的檔案物件。
    """
    try:
        os.fsync(file_obj.fileno())
    except AttributeError, OSError, ValueError:
        return


def _atomic_write_payload(path: Path | str, writer: Callable[[Any], None], mode: str, **open_kwargs) -> bool:
    """以暫存檔與原子替換寫入 payload。"""
    p = Path(path)
    p.parents[0].mkdir(parents=True, exist_ok=True)
    for attempt in range(_RETRY_COUNT):
        tmp_name = f"{p.name}.{os.getpid()}.{threading.get_ident()}.{int(time.time() * 1000)}.{attempt}.tmp"
        tmp_path = p.with_name(tmp_name)
        try:
            with open(tmp_path, mode, **open_kwargs) as file_obj:
                writer(file_obj)
                file_obj.flush()
                best_effort_fsync(file_obj)
            os.replace(tmp_path, p)
            return True
        except OSError:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                logger.debug("嘗試移除臨時檔案 %s 時失敗；忽略錯誤。", tmp_path, exc_info=True)
            if attempt + 1 >= _RETRY_COUNT:
                return False
            time.sleep(_RETRY_DELAY * (attempt + 1))
    return False


def atomic_write_json(path: Path | str, data, indent: int = 2, *, skip_if_unchanged: bool = False) -> bool:
    """
    以原子方式寫入 JSON 檔案。

    Args:
        path: 目標檔案路徑。
        data: 要寫入的資料。
        indent: JSON 縮排層級。
        skip_if_unchanged: 若內容相同則略過寫入。

    Returns:
        寫入成功時回傳 True，失敗時回傳 False。
    """
    p = Path(path)
    p.parents[0].mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=indent, ensure_ascii=False)

    if skip_if_unchanged and p.exists():
        try:
            if p.read_text(encoding="utf-8") == payload:
                return True
        except OSError, UnicodeDecodeError:
            logger.debug("無法讀取現有檔案以判斷是否相同，將覆寫: %s", p, exc_info=True)

    return atomic_write_text(p, payload, encoding="utf-8", newline="\n")


def atomic_write_text(
    path: Path | str,
    content: str,
    *,
    encoding: str = "utf-8",
    errors: str | None = None,
    newline: str | None = None,
) -> bool:
    """
    以原子方式寫入文字檔案。

    Args:
        path: 目標檔案路徑。
        content: 要寫入的文字內容。
        encoding: 文字編碼。
        errors: 編碼錯誤處理方式。
        newline: 換行處理方式。

    Returns:
        寫入成功時回傳 True，失敗時回傳 False。
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
    以原子方式寫入二進位檔案。

    Args:
        path: 目標檔案路徑。
        content: 要寫入的位元組內容。

    Returns:
        寫入成功時回傳 True，失敗時回傳 False。
    """
    return _atomic_write_payload(path, lambda f: f.write(content), "wb")
