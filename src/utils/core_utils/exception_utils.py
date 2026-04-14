"""例外處理輔助器

提供集中化的例外記錄與非破壞性 marker 建立，以便 hotpath 能統一處理。
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from .logger import get_logger
from .path_utils import PathUtils

logger = get_logger().bind(component="ExceptionUtils")


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

    try:
        logger.bind(exception_type=exc_type).exception(f"已處理例外: {exc}")
    except Exception:
        with contextlib.suppress(Exception):
            logger.error(f"記錄例外時發生錯誤: {exc}")

    if marker_path is None:
        return
    try:
        p = Path(marker_path)
        marker_details: dict[str, Any]
        if isinstance(details, dict):
            marker_details = dict(details)
        elif details is None:
            marker_details = {}
        else:
            marker_details = {"details": details}
        marker_details["exception_type"] = exc_type
        # 若 marker_path 為檔案，使用其父目錄與檔名；PathUtils.mark_issue 會產生 marker 的檔名
        PathUtils.mark_issue(p, reason or str(exc), details=marker_details)
    except Exception:
        with contextlib.suppress(Exception):
            logger.debug(f"建立 marker 失敗: {marker_path}")
