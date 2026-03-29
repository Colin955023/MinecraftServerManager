"""例外處理輔助器

提供集中化的例外記錄與非破壞性 marker 建立，以便 hotpath 能統一處理。
"""

from __future__ import annotations
import traceback
from pathlib import Path
from typing import Any
from .path_utils import PathUtils
from .logger import get_logger
import contextlib

logger = get_logger().bind(component="ExceptionUtils")


def record_and_mark(
    exc: BaseException,
    marker_path: Path | str | None = None,
    reason: str | None = None,
    details: Any | None = None,
) -> None:
    """記錄例外並在指定路徑建立 issue marker（非破壞性）。

    - `marker_path`: 若提供，會在同目錄建立 `.{filename}.issue.json` 的 marker。
    - `reason`: marker 中的 reason 欄位；若為 None 則使用 exc 的字串。
    - `details`: 會寫入 marker 的 details 欄位（若為 dict 則會合併）。
    """
    try:
        exc_type = type(exc).__name__
        tb = getattr(exc, "__traceback__", None)
        tb_text = (
            "".join(traceback.format_exception(type(exc), exc, tb))
            if tb is not None
            else "".join(traceback.format_exception_only(type(exc), exc))
        )
    except Exception:
        exc_type = type(exc).__name__ if exc is not None else "Exception"
        tb_text = str(exc)

    try:
        logger.bind(exception_type=exc_type).exception(f"已處理例外: {exc}")
    except Exception:
        with contextlib.suppress(Exception):
            logger.error(f"記錄例外時發生錯誤: {exc}")

    if marker_path is None:
        return
    try:
        p = Path(marker_path)
        # 若 marker_path 為檔案，使用其父目錄與檔名；PathUtils.mark_issue 會產生 marker 的檔名
        PathUtils.mark_issue(
            p, reason or str(exc), details={**(details or {}), "exception_type": exc_type, "traceback_summary": tb_text}
        )
    except Exception:
        with contextlib.suppress(Exception):
            logger.debug(f"建立 marker 失敗: {marker_path}")
