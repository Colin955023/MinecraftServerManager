"""原子性寫入工具（最小實作）

提供 atomic_write_json(path, data) 以同目錄臨時檔 + os.replace 方式保證原子替換，並嘗試 fsync。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .logger import get_logger

logger = get_logger().bind(component="AtomicWriter")

_RETRY_COUNT = 3
_RETRY_DELAY = 0.02


def best_effort_fsync(file_obj) -> None:
    """盡力對檔案描述元執行 fsync，不將平台限制視為錯誤。

    Args:
        file_obj: 已開啟且可取得 fileno 的檔案物件。
    """

    try:
        os.fsync(file_obj.fileno())
    except AttributeError, OSError, ValueError:
        return


def atomic_write_json(path: Path | str, data, indent: int = 2, *, skip_if_unchanged: bool = False) -> bool:
    """以原子方式寫入 JSON 檔案。

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
            existing = p.read_text(encoding="utf-8")
            if existing == payload:
                return True
        except OSError, UnicodeDecodeError:
            # 若無法讀取現有檔案，視為需覆寫；記錄 debug 以便除錯
            logger.debug("無法讀取現有檔案以判斷是否相同，將覆寫: %s", p, exc_info=True)

    for attempt in range(_RETRY_COUNT):
        tmp_name = f"{p.name}.{os.getpid()}.{threading.get_ident()}.{int(time.time() * 1000)}.{attempt}.tmp"
        tmp_path = p.with_name(tmp_name)
        try:
            with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(payload)
                f.flush()
                best_effort_fsync(f)
            os.replace(tmp_path, p)
            return True
        except OSError:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                logger.debug(
                    "嘗試移除臨時檔案 %s 時失敗；忽略錯誤。",
                    tmp_path,
                    exc_info=True,
                )
            if attempt + 1 >= _RETRY_COUNT:
                return False
            time.sleep(_RETRY_DELAY * (attempt + 1))
    return False
