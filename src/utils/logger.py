#!/usr/bin/env python3
"""日誌工具模組
提供統一的日誌記錄功能 (使用標準 logging 庫替代 loguru 以減少依賴與體積)
"""

import logging
import sys
from datetime import datetime
from functools import partialmethod

from . import RuntimePaths


class LoguruShim:
    def __init__(self, logger_impl, extra=None):
        self.logger = logger_impl
        self.extra = extra or {"component": "Global"}

    def bind(self, **kwargs):
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
                if isinstance(msg, str) and "{" in msg and "}" in msg:
                    try:
                        formatted_msg = msg.format(*args)
                        msg = formatted_msg
                        args = ()
                    except Exception as format_error:
                        msg = f"{msg} (format_error: {format_error})"

                if args:
                    _ = msg % args
            except TypeError:
                # 這通常是原始程式碼多傳了參數 (例如 component)，我們將其附加在後方顯示
                msg = f"{msg} " + " ".join(map(str, args))
                args = ()
            except Exception:
                # 其他格式化錯誤，安全起見清除 args 避免 logging 內部崩潰
                msg = f"{msg} (args: {args})"
                args = ()

        self.logger.log(level, msg, *args, **kwargs)

    # 使用 partialmethod 簡化等級方法定義
    debug = partialmethod(_log, logging.DEBUG)
    info = partialmethod(_log, logging.INFO)
    warning = partialmethod(_log, logging.WARNING)
    error = partialmethod(_log, logging.ERROR)
    critical = partialmethod(_log, logging.CRITICAL)

    def exception(self, msg, *args, **kwargs):
        kwargs["exc_info"] = True
        self._log(logging.ERROR, msg, *args, **kwargs)

    def add(self, *args, **kwargs):
        pass

    def remove(self, *args, **kwargs):
        pass


class LoggerConfig:
    _initialized = False

    @staticmethod
    def initialize():
        if LoggerConfig._initialized:
            return

        root = logging.getLogger()
        root.setLevel(logging.DEBUG)

        if root.handlers:
            LoggerConfig._initialized = True
            return

        fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(fmt)
        ch.setLevel(logging.INFO)
        root.addHandler(ch)

        try:
            log_dir = RuntimePaths.get_log_dir()
            log_dir.mkdir(parents=True, exist_ok=True)

            logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime)
            while len(logs) >= 10:
                try:
                    logs.pop(0).unlink()
                except Exception as cleanup_error:
                    root.warning(f"移除舊日誌檔案失敗: {cleanup_error}")

            log_file = log_dir / datetime.now().strftime("%Y-%m-%d-%H-%M.log")
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(fmt)
            fh.setLevel(logging.DEBUG)
            root.addHandler(fh)
        except Exception as log_error:
            root.warning(f"初始化檔案日誌處理器失敗: {log_error}")

        LoggerConfig._initialized = True

    @staticmethod
    def get_logger():
        LoggerConfig.initialize()
        return LoguruShim(logging.getLogger("MSM"))


_logger = LoggerConfig.get_logger()


def get_logger():
    """獲取全局 logger 實例"""
    return _logger
