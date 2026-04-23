"""例外處理輔助器

提供集中化的例外記錄與非破壞性 marker 建立，以便 hotpath 能統一處理。
"""

from __future__ import annotations

import contextlib
import traceback
from pathlib import Path
from typing import Any

from .logger import get_logger
from .path_utils import PathUtils

logger = get_logger().bind(component="ExceptionUtils")
_RUNTIME_ISSUE_MARKER_NAME = ".runtime_issues"


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
    """記錄例外並在指定路徑建立 issue marker（非破壞性）。

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
            local_vars = {k: repr(v) for k, v in frame.f_locals.items() if k != "self"}
        except Exception:
            local_vars = {}

    try:
        logger.bind(exception_type=exc_type).exception(f"已處理例外: {exc}\nTraceback:\n{tb_str}\nLocals: {local_vars}")
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
