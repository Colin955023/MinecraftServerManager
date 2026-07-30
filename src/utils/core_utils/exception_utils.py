"""
例外處理輔助器

提供集中化的例外記錄與非破壞性 marker 建立，以便 hotpath 能統一處理。

安全性注意事項：`record_and_mark` 會把例外發生當下最內層 stack frame 的
區域變數寫入 log 與 marker 檔案，方便除錯。為避免密碼、token、金鑰等
敏感資料意外落地到硬碟上的診斷檔案，這裡依變數「名稱」做關鍵字遮罩，
並限制每個值輸出的長度上限，避免超大物件塞爆 log／marker 檔案。
"""

from __future__ import annotations

import contextlib
import logging
import traceback
from pathlib import Path
from typing import Any

from .logger import get_logger
from .path_utils import PathUtils

logger = get_logger().bind(component="ExceptionUtils")
_RUNTIME_ISSUE_MARKER_NAME = ".runtime_issues"

# 預期內的例外類型 → 使用 WARNING 級別而非 ERROR
_EXPECTED_EXCEPTION_TYPES = (
    FileExistsError,
    FileNotFoundError,
    PermissionError,
    ValueError,
    TypeError,
    KeyError,
    IndexError,
)


def _log_level_for_exception(exc: BaseException) -> int:
    """根據例外類型回傳適當的日誌級別。預期錯誤用 WARNING，其餘用 ERROR。"""
    if isinstance(exc, _EXPECTED_EXCEPTION_TYPES):
        return logging.WARNING
    return logging.ERROR


_SENSITIVE_NAME_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "auth",
    "cookie",
    "session_id",
)
_MAX_REPR_LENGTH = 500


def _looks_sensitive(name: str) -> bool:
    """依變數名稱粗略判斷是否可能存放敏感資料。"""
    lowered = name.lower()
    return any(marker in lowered for marker in _SENSITIVE_NAME_MARKERS)


def _safe_repr(name: str, value: object) -> str:
    """回傳遮罩後、長度受限的變數表示；名稱疑似敏感時一律遮罩。"""
    if _looks_sensitive(name):
        return "***REDACTED***"
    try:
        text = repr(value)
    except Exception:
        return "<repr() failed>"
    if len(text) > _MAX_REPR_LENGTH:
        return f"{text[:_MAX_REPR_LENGTH]}...(truncated, {len(text)} chars total)"
    return text


def _format_exception_traceback(exc: BaseException) -> str:
    """以 exception 物件本身格式化 traceback，避免脫離 except 區塊時遺失資訊。"""
    try:
        return "".join(traceback.TracebackException.from_exception(exc).format()).strip()
    except Exception:
        return traceback.format_exc().strip()


def _default_marker_path() -> Path:
    """為無特定檔案關聯的例外提供集中 marker 路徑。"""
    return PathUtils.get_project_root() / _RUNTIME_ISSUE_MARKER_NAME


def record_and_mark(
    exc: BaseException,
    marker_path: Path | str | None = None,
    reason: str | None = None,
    details: Any | None = None,
) -> None:
    """
    記錄例外並在指定路徑建立 issue marker（非破壞性）。

    Args:
        exc: 要記錄的例外。
        marker_path: 若提供，會在同目錄建立 marker。
        reason: marker 中的原因欄位。
        details: 會寫入 marker 的額外資訊。
    """
    exc_type = type(exc).__name__ if exc is not None else "Exception"

    tb_str = _format_exception_traceback(exc)
    local_vars = {}
    tb = getattr(exc, "__traceback__", None)
    if tb:
        try:
            while tb.tb_next:
                tb = tb.tb_next
            frame = tb.tb_frame
            local_vars = {k: _safe_repr(k, v) for k, v in frame.f_locals.items() if k != "self"}
        except Exception:
            local_vars = {}

    try:
        log_level = _log_level_for_exception(exc)
        logger.bind(exception_type=exc_type).log(
            log_level, f"已處理例外: {exc}\nTraceback:\n{tb_str}\nLocals: {local_vars}"
        )
    except Exception:
        with contextlib.suppress(Exception):
            logger.error(f"記錄例外時發生錯誤: {exc}")

    try:
        p = Path(marker_path) if marker_path is not None else _default_marker_path()
        marker_details: dict[str, Any]
        if isinstance(details, dict):
            marker_details = dict(details)
        elif details is None:
            marker_details = {}
        else:
            marker_details = {"details": details}
        marker_details["exception_type"] = exc_type
        marker_details["traceback"] = tb_str
        marker_details["locals"] = local_vars
        # 若 marker_path 為檔案，使用其父目錄與檔名；PathUtils.mark_issue 會產生 marker 的檔名
        PathUtils.mark_issue(p, reason or str(exc), details=marker_details)
    except Exception:
        with contextlib.suppress(Exception):
            logger.debug(f"建立 marker 失敗: {marker_path}")
