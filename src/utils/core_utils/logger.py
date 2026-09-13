"""專案共用日誌工具"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from src.utils import RuntimePaths

from .filesystem_utils import delete_within, list_bounded_directory, move_within, resolve_stable_directory

_LOGGER_NAME = "MinecraftServerManager"
_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(component)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_LOG_BYTES = 10 * 1024 * 1024
_MAX_LOG_FILES = 10
_INITIALIZED = False


class _ComponentLogger(logging.LoggerAdapter):
    """提供可附加元件內容的輕量 logger adapter"""

    def __init__(self, logger: logging.Logger, extra: dict[str, Any] | None = None) -> None:
        self._context: dict[str, Any] = {"component": "Global"} if extra is None else extra.copy()
        super().__init__(logger, self._context, merge_extra=True)

    def bind(self, **kwargs: Any) -> _ComponentLogger:
        """
        回傳帶有額外 context 的 logger adapter

        Args:
            kwargs: 要附加到日誌記錄的欄位

        Returns:
            帶有合併後 context 的 logger adapter
        """
        context = self._context.copy()
        context.update(kwargs)
        return _ComponentLogger(self.logger, context)


def _log_files(log_dir: Path) -> list[Path]:
    """依修改時間由舊到新列出 MSM 日誌檔"""
    files: list[Path] = []
    try:
        entries = list_bounded_directory(log_dir)
    except OSError:
        return files
    for path in entries:
        if not (path.name.endswith(".log") or ".log." in path.name):
            continue
        try:
            if path.is_file():
                files.append(path)
        except OSError:
            continue

    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    return sorted(files, key=_mtime)


def _prune_logs(log_dir: Path, keep: int) -> None:
    """僅保留指定數量的最新日誌，清理失敗不影響程式啟動"""
    logs = _log_files(log_dir)
    limit = max(0, keep)
    for old in logs[: max(0, len(logs) - limit)]:
        delete_within(log_dir, old)


class _RetentionFileHandler(RotatingFileHandler):
    """10 MiB 輪替並限制整個日誌目錄中的歷史檔案數量"""

    def __init__(self, filename: Path, log_dir: Path) -> None:
        self._log_dir = log_dir
        super().__init__(
            filename,
            maxBytes=_MAX_LOG_BYTES,
            backupCount=_MAX_LOG_FILES - 1,
            encoding="utf-8",
            errors="backslashreplace",
            delay=True,
        )

    def doRollover(self) -> None:
        """
        以受限搬移輪替日誌檔並清理過量歷史檔案

        此方法不接受額外參數，也不回傳資料
        """
        if self.stream:
            self.stream.close()
            self.stream = None
        base_path = Path(self.baseFilename)
        if self.backupCount > 0:
            for index in range(self.backupCount - 1, 0, -1):
                source = Path(self.rotation_filename(f"{self.baseFilename}.{index}"))
                target = Path(self.rotation_filename(f"{self.baseFilename}.{index + 1}"))
                if source.exists() and not move_within(self._log_dir, source, target):
                    raise OSError(f"無法安全輪替日誌檔：{source}")
            rollover_target = Path(self.rotation_filename(f"{self.baseFilename}.1"))
            if base_path.exists() and not move_within(self._log_dir, base_path, rollover_target):
                raise OSError(f"無法安全輪替日誌檔：{base_path}")
        if not self.delay:
            self.stream = self._open()
        _prune_logs(self._log_dir, _MAX_LOG_FILES)


def _should_log_to_stderr() -> bool:
    """判斷目前 stderr 是否應作為可見的 console/debug 輸出"""
    if sys.stderr is None:
        return False

    if not RuntimePaths.is_packaged():
        return True

    try:
        return bool(ctypes.windll.kernel32.GetConsoleCP())
    except AttributeError, OSError:
        return False


def _setup() -> logging.Logger:
    """初始化專案專用 logger，不修改 root logger"""
    global _INITIALIZED

    base = logging.getLogger(_LOGGER_NAME)
    if _INITIALIZED:
        return base

    _INITIALIZED = True
    base.setLevel(logging.DEBUG)
    base.propagate = False
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    stderr = sys.stderr
    if stderr is not None and _should_log_to_stderr():
        console = logging.StreamHandler(stderr)
        console.set_name("msm_console")
        console.setLevel(logging.INFO)
        console.setFormatter(formatter)
        base.addHandler(console)

    try:
        log_dir = resolve_stable_directory(RuntimePaths.get_log_dir(), create=True)
        _prune_logs(log_dir, _MAX_LOG_FILES - 1)

        log_file = log_dir / datetime.now().strftime(f"%Y-%m-%d-%H-%M-%S-p{os.getpid()}.log")
        file_handler = _RetentionFileHandler(log_file, log_dir)
        file_handler.set_name("msm_file")
        file_handler.setLevel(logging.DEBUG if RuntimePaths.is_development_environment() else logging.INFO)
        file_handler.setFormatter(formatter)
        base.addHandler(file_handler)
    except Exception as exc:
        fallback = _ComponentLogger(base, {"component": "Logger"})
        fallback.warning("初始化檔案日誌處理器失敗: %s", exc)

    return base


_logger = _ComponentLogger(_setup())


def get_logger() -> _ComponentLogger:
    """
    取得全域 logger adapter

    此 adapter 支援以 bind 附加元件欄位
    """
    return _logger


__all__ = ["get_logger"]
