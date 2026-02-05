#!/usr/bin/env python3
"""日誌工具模組
提供統一的日誌記錄功能 (使用標準 logging 庫替代 loguru 以減少依賴與體積)
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from . import RuntimePaths


def _get_log_dir() -> Path:
    """取得日誌目錄路徑"""
    # 使用 runtime_paths 提供的 exe 目錄判斷
    exe_dir = RuntimePaths.get_exe_dir()

    portable_marker = exe_dir / ".portable"
    config_dir = exe_dir / ".config"

    if portable_marker.exists() or config_dir.exists():
        # 便攜模式：使用相對於可執行檔的 .log 資料夾
        return exe_dir / ".log"
    # 安裝模式：使用 %LOCALAPPDATA%\Programs\MinecraftServerManager\log
    localappdata = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return Path(localappdata) / "Programs" / "MinecraftServerManager" / "log"


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
                    except Exception:
                        pass

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

    def debug(self, msg, *args, **kwargs):
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self._log(logging.CRITICAL, msg, *args, **kwargs)

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
            return

        fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(fmt)
        ch.setLevel(logging.INFO)
        root.addHandler(ch)

        try:
            log_dir = _get_log_dir()
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
