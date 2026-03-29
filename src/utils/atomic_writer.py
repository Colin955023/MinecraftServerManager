"""原子性寫入工具（最小實作）

提供 atomic_write_json(path, data) 以同目錄臨時檔 + os.replace 方式保證原子替換，並嘗試 fsync。
"""

from __future__ import annotations
import json
import os
import time
import threading
from pathlib import Path

_RETRY_COUNT = 3
_RETRY_DELAY = 0.02


def _best_effort_fsync(file_obj):
    try:
        os.fsync(file_obj.fileno())
    except (AttributeError, OSError, ValueError):
        return


def atomic_write_json(path: Path | str, data, indent: int = 2, *, skip_if_unchanged: bool = False) -> bool:
    """以原子方式寫入 JSON 檔案。

    新增參數 `skip_if_unchanged`，當為 True 時若目標檔案存在且與要寫入的 payload 相同，
    則跳過實際寫入以減少 I/O 與避免觸發不必要的檔案變更事件。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=indent, ensure_ascii=False)

    if skip_if_unchanged and p.exists():
        try:
            existing = p.read_text(encoding="utf-8")
            if existing == payload:
                return True
        except (OSError, UnicodeDecodeError):
            # 若無法讀取現有檔案，視為需覆寫
            pass

    for attempt in range(_RETRY_COUNT):
        tmp_name = f"{p.name}.{os.getpid()}.{threading.get_ident()}.{int(time.time() * 1000)}.{attempt}.tmp"
        tmp_path = p.with_name(tmp_name)
        try:
            with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(payload)
                f.flush()
                _best_effort_fsync(f)
            os.replace(tmp_path, p)
            try:
                fd = os.open(str(p.parent), os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except OSError:
                pass
            return True
        except OSError:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            if attempt + 1 >= _RETRY_COUNT:
                return False
            time.sleep(_RETRY_DELAY * (attempt + 1))
    return False
