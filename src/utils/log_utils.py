#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日誌工具模組
提供統一的日誌記錄功能（包含控制台輸出與檔案記錄）
Logging Utilities Module
Provides unified logging functionality (including console output and file logging)
"""
# ====== 標準函式庫 ======
from datetime import datetime
from pathlib import Path
from typing import Optional
import traceback
import threading

# ====== 日誌工具類別 ======
class LogUtils:
    """
    統一的日誌工具類別
    Unified logging utility class for consistent message output with color coding and file logging
    """

    # 類別層級的日誌檔案配置
    _log_file = None
    _log_lock = threading.Lock()
    _max_log_size = 10 * 1024 * 1024  # 10 MB
    _log_initialized = False

    @staticmethod
    def _initialize_log_file() -> None:
        """
        初始化日誌檔案（延遲初始化，避免在模組載入時就建立檔案）
        Initialize log file (lazy initialization to avoid creating files during module load)
        """
        if LogUtils._log_initialized:
            return

        try:
            # 取得日誌目錄路徑
            from .runtime_paths import get_user_data_dir

            log_dir = Path(get_user_data_dir()) / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)

            # 建立日誌檔案名稱（使用日期）
            log_filename = (
                f"minecraft_server_manager_{datetime.now().strftime('%Y%m%d')}.log"
            )
            LogUtils._log_file = log_dir / log_filename

            # 檢查日誌檔案大小，如果過大則輪轉
            if (
                LogUtils._log_file.exists()
                and LogUtils._log_file.stat().st_size > LogUtils._max_log_size
            ):
                # 重命名舊檔案
                backup_name = f"minecraft_server_manager_{datetime.now().strftime('%Y%m%d_%H%M%S')}_backup.log"
                backup_file = log_dir / backup_name
                LogUtils._log_file.rename(backup_file)

            # 清理超過 7 天的舊日誌檔案
            LogUtils._clean_old_logs(log_dir, days=7)

            LogUtils._log_initialized = True
        except Exception as e:
            # 如果初始化失敗，只輸出到控制台，不影響程式運行
            print(f"[WARNING] 日誌檔案初始化失敗: {e}")
            LogUtils._log_file = None
            LogUtils._log_initialized = True  # 標記為已初始化，避免重複嘗試

    @staticmethod
    def _clean_old_logs(log_dir: Path, days: int = 7) -> None:
        """
        清理超過指定天數的舊日誌檔案
        Clean up old log files older than specified days

        Args:
            log_dir (Path): 日誌目錄
            days (int): 保留天數
        """
        try:
            from datetime import timedelta

            cutoff_time = datetime.now() - timedelta(days=days)

            for log_file in log_dir.glob("*.log"):
                try:
                    if log_file.stat().st_mtime < cutoff_time.timestamp():
                        log_file.unlink()
                except Exception:
                    pass  # 忽略單個檔案的刪除錯誤
        except Exception:
            pass  # 忽略清理錯誤

    @staticmethod
    def _write_to_file(level: str, message: str, component: str = "") -> None:
        """
        將日誌訊息寫入檔案
        Write log message to file

        Args:
            level (str): 日誌級別
            message (str): 訊息內容
            component (str): 組件名稱
        """
        if not LogUtils._log_initialized:
            LogUtils._initialize_log_file()

        if LogUtils._log_file is None:
            return

        try:
            with LogUtils._log_lock:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                component_str = f"[{component}]" if component else ""
                log_line = f"[{timestamp}][{level}]{component_str} {message}\n"

                with open(LogUtils._log_file, "a", encoding="utf-8") as f:
                    f.write(log_line)
        except Exception:
            # 檔案寫入失敗時靜默忽略，不影響程式運行
            pass

    @staticmethod
    def _should_show_debug_output() -> bool:
        """
        檢查是否應該顯示調試輸出
        Check if debug output should be shown

        Returns:
            bool: True 表示應該顯示調試輸出，False 表示不顯示
        """
        try:
            # 在需要時才導入設定管理器以避免循環導入
            from .settings_manager import get_settings_manager

            settings = get_settings_manager()
            return settings.is_debug_logging_enabled()
        except Exception:
            # 如果無法取得設定，預設不顯示調試輸出
            return False

    # 輸出錯誤訊息到控制台和檔案
    @staticmethod
    def error(message: str, component: str = "") -> None:
        """
        列印錯誤訊息到控制台和檔案，使用紅色標記
        錯誤訊息一律輸出，不受調試設定控制
        Print error message to console and file with red color marking
        Error messages are always output regardless of debug settings

        Args:
            message (str): 錯誤訊息內容
            component (str): 可選的組件名稱，用於標識訊息來源

        Returns:
            None
        """
        if component:
            print(f"\033[91m[ERROR][{component}] {message}\033[0m")
        else:
            print(f"\033[91m[ERROR] {message}\033[0m")

        # 寫入檔案
        LogUtils._write_to_file("ERROR", message, component)

    @staticmethod
    def error_exc(
        message: str, component: str = "", exc: Optional[BaseException] = None
    ) -> None:
        """以統一格式輸出錯誤並附上 traceback（同時寫入檔案）。

        - 若提供 exc，使用該例外的 traceback（適合跨執行緒傳遞）。
        - 否則使用當前 except 區塊的 traceback.format_exc()。
        """
        if exc is not None:
            trace = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
        else:
            trace = traceback.format_exc()
        LogUtils.error(f"{message}\n{trace}", component)

    # 輸出資訊訊息到控制台和檔案
    @staticmethod
    def info(message: str, component: str = "") -> None:
        """
        列印資訊訊息到控制台和檔案
        Print info message to console and file

        Args:
            message (str): 資訊訊息內容
            component (str): 可選的組件名稱，用於標識訊息來源

        Returns:
            None
        """
        if not LogUtils._should_show_debug_output():
            # 即使不顯示，也要寫入檔案
            LogUtils._write_to_file("INFO", message, component)
            return

        if component:
            print(f"[INFO][{component}] {message}")
        else:
            print(f"[INFO] {message}")

        # 寫入檔案
        LogUtils._write_to_file("INFO", message, component)

    # 輸出警告訊息到控制台和檔案
    @staticmethod
    def warning(message: str, component: str = "") -> None:
        """
        列印警告訊息到控制台和檔案，使用黃色標記
        警告訊息一律輸出，不受調試設定控制
        Print warning message to console and file with yellow color marking
        Warning messages are always output regardless of debug settings

        Args:
            message (str): 警告訊息內容
            component (str): 可選的組件名稱，用於標識訊息來源

        Returns:
            None
        """
        if component:
            print(f"\033[93m[WARNING][{component}] {message}\033[0m")
        else:
            print(f"\033[93m[WARNING] {message}\033[0m")

        # 寫入檔案
        LogUtils._write_to_file("WARNING", message, component)

    # 輸出調試訊息到控制台和檔案（受設定控制）
    @staticmethod
    def debug(message: str, component: str = "") -> None:
        """
        列印調試訊息到控制台和檔案，受設定檔控制是否顯示
        Print debug message to console and file, controlled by settings configuration

        Args:
            message (str): 調試訊息內容
            component (str): 可選的組件名稱，用於標識訊息來源

        Returns:
            None
        """
        # 寫入檔案（即使不顯示也要記錄）
        LogUtils._write_to_file("DEBUG", message, component)

        if not LogUtils._should_show_debug_output():
            return

        if component:
            print(f"\033[94m[DEBUG][{component}] {message}\033[0m")
        else:
            print(f"\033[94m[DEBUG] {message}\033[0m")

    # 輸出視窗狀態調試訊息
    @staticmethod
    def debug_window_state(message: str) -> None:
        """
        列印視窗狀態調試訊息到控制台和檔案，使用統一的調試輸出判斷
        Print window state debug message to console and file, using unified debug output check

        Args:
            message (str): 視窗狀態調試訊息內容

        Returns:
            None
        """
        # 寫入檔案
        LogUtils._write_to_file("DEBUG", message, "WindowState")

        if not LogUtils._should_show_debug_output():
            return

        print(f"\033[94m[DEBUG] {message}\033[0m")
