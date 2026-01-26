#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日誌工具模組
提供統一的日誌記錄功能 (使用標準 logging 庫替代 loguru 以減少依賴與體積)
"""
import logging
import sys
import os
from pathlib import Path
from datetime import datetime

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
                    except (IndexError, ValueError, KeyError):
                        pass

                if args:
                    _ = msg % args
            except TypeError:
                pass
                # 這通常是原始代碼多傳了參數 (例如 component)，我們將其附加在後方顯示
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

        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(fmt)
        ch.setLevel(logging.INFO)
        root.addHandler(ch)

        try:
            localappdata = os.environ.get(
                "LOCALAPPDATA", str(Path.home() / "AppData" / "Local")
            )
            log_dir = Path(localappdata) / "Programs" / "MinecraftServerManager" / "log"
            log_dir.mkdir(parents=True, exist_ok=True)

            logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime)
            while len(logs) >= 10:
                try:
                    logs.pop(0).unlink()
                except Exception:
                    pass

            log_file = log_dir / datetime.now().strftime("%Y-%m-%d-%H-%M.log")
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(fmt)
            fh.setLevel(logging.DEBUG)
            root.addHandler(fh)
        except Exception:
            pass

        LoggerConfig._initialized = True

    @staticmethod
    def get_logger():
        LoggerConfig.initialize()
        return LoguruShim(logging.getLogger("MSM"))

_logger = LoggerConfig.get_logger()

def get_logger():
    return _logger

def info(message: str, component: str = ""):
    _logger.bind(component=component).info(message)

def warning(message: str, component: str = ""):
    _logger.bind(component=component).warning(message)

def error(message: str, component: str = ""):
    _logger.bind(component=component).error(message)

def debug(message: str, component: str = ""):
    _logger.bind(component=component).debug(message)

def error_with_exception(message: str, component: str = "", exc: Exception = None):
    _logger.bind(component=component).exception(
        message if not exc else f"{message}: {exc}"
    )
