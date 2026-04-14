"""日誌工具模組
提供統一的日誌記錄功能 (使用標準 logging 庫替代 loguru 以減少依賴與體積)
"""

import logging
import os
import sys
from datetime import datetime
from functools import partialmethod

from .. import RuntimePaths


class LoguruShim:
    """以標準 logging 模擬常用的 loguru 介面。"""

    def __init__(self, logger_impl, extra=None):
        self.logger = logger_impl
        self.extra = extra or {"component": "Global"}

    def bind(self, **kwargs):
        """回傳綁定額外上下文的 logger 包裝。

        Args:
            **kwargs: 要合併的額外上下文。

        Returns:
            綁定後的 LoguruShim 實例。
        """

        new_extra = self.extra.copy()
        new_extra.update(kwargs)
        return LoguruShim(self.logger, new_extra)

    def _log(self, level, msg, *args, **kwargs):
        comp = self.extra.get("component")
        if comp:
            msg = str(msg)
            msg = f"[{comp}] {msg}"
        if args:
            try:
                if isinstance(msg, str) and "{" in msg and ("}" in msg):
                    try:
                        formatted_msg = msg.format(*args)
                        msg = formatted_msg
                        args = ()
                    except Exception as format_error:
                        msg = f"{msg} (format_error: {format_error})"
                if args:
                    _ = msg % args
            except TypeError:
                msg = f"{msg} " + " ".join(map(str, args))
                args = ()
            except Exception:
                msg = f"{msg} (args: {args})"
                args = ()
        self.logger.log(level, msg, *args, **kwargs)

    debug = partialmethod(_log, logging.DEBUG)
    info = partialmethod(_log, logging.INFO)
    warning = partialmethod(_log, logging.WARNING)
    error = partialmethod(_log, logging.ERROR)
    critical = partialmethod(_log, logging.CRITICAL)

    def exception(self, msg, *args, **kwargs):
        """以 error 等級記錄例外並自動帶入 exc_info。

        Args:
            msg: 日誌訊息。
            *args: 訊息格式化參數。
            **kwargs: 額外關鍵字參數。
        """

        kwargs["exc_info"] = True
        self._log(logging.ERROR, msg, *args, **kwargs)


class LoggerConfig:
    """初始化並管理專案共用的標準 logging 設定。"""

    _initialized = False
    _CONSOLE_HANDLER_NAME = "msm_console"
    _FILE_HANDLER_NAME = "msm_file"

    @staticmethod
    def _has_handler(root: logging.Logger, handler_name: str) -> bool:
        return any(getattr(handler, "name", "") == handler_name for handler in root.handlers)

    @staticmethod
    def initialize() -> None:
        """建立 root logger 的 console 與檔案 handler。"""

        if LoggerConfig._initialized:
            return
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        if not LoggerConfig._has_handler(root, LoggerConfig._CONSOLE_HANDLER_NAME):
            ch = logging.StreamHandler(sys.stderr)
            ch.set_name(LoggerConfig._CONSOLE_HANDLER_NAME)
            ch.setFormatter(fmt)
            ch.setLevel(logging.INFO)
            root.addHandler(ch)
        if not LoggerConfig._has_handler(root, LoggerConfig._FILE_HANDLER_NAME):
            try:
                log_dir = RuntimePaths.get_log_dir()
                log_dir.mkdir(parents=True, exist_ok=True)
                logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime)
                while len(logs) >= 10:
                    try:
                        logs.pop(0).unlink()
                    except Exception as cleanup_error:
                        root.warning(f"移除舊日誌檔案失敗: {cleanup_error}")
                log_file = log_dir / datetime.now().strftime(f"%Y-%m-%d-%H-%M-%S-p{os.getpid()}.log")
                fh = logging.FileHandler(log_file, encoding="utf-8")
                fh.set_name(LoggerConfig._FILE_HANDLER_NAME)
                fh.setFormatter(fmt)
                fh.setLevel(logging.DEBUG)
                root.addHandler(fh)
            except Exception as log_error:
                root.warning(f"初始化檔案日誌處理器失敗: {log_error}")
        LoggerConfig._initialized = True

    @staticmethod
    def get_logger() -> LoguruShim:
        """取得包裝後的專案 logger。"""

        LoggerConfig.initialize()
        return LoguruShim(logging.getLogger("MSM"))


_logger = LoggerConfig.get_logger()


def get_logger():
    """獲取全局 logger 實例"""
    return _logger


def shutdown_logging() -> None:
    """關閉 logging 系統，確保所有 handler 已刷新並關閉。"""
    logging.shutdown()
