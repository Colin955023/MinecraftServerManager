"""日誌工具模組（loguru）"""

from __future__ import annotations

import os
import sys
from datetime import datetime

from loguru import logger as _base

from src.utils import RuntimePaths

_LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {extra[component]} | {message}"
_INITIALIZED = False


def _setup() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    _base.remove()
    if sys.stderr is not None:
        _base.add(
            sys.stderr,
            level="INFO",
            format=_LOG_FORMAT,
            colorize=False,
            enqueue=True,
        )
    try:
        log_dir = RuntimePaths.get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)

        log_file = log_dir / datetime.now().strftime(f"%Y-%m-%d-%H-%M-%S-p{os.getpid()}.log")
        file_level = "DEBUG" if RuntimePaths.is_development_environment() else "INFO"
        _base.add(
            str(log_file),
            level=file_level,
            format=_LOG_FORMAT,
            encoding="utf-8",
            enqueue=True,
            retention=10,
            rotation="10 MB",
        )
    except Exception as e:
        _base.warning(f"初始化檔案日誌處理器失敗: {e}")


_setup()
_logger = _base.bind(component="Global")


def get_logger():
    """取得全域 logger 實例"""
    return _logger
