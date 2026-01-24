#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日誌工具模組 (已遷移至 loguru)
提供統一的日誌記錄功能（包含控制台輸出與檔案記錄）
Logging Utilities Module (Migrated to loguru)
Provides unified logging functionality (including console output and file logging)
"""

import traceback
from typing import Optional

from .logger import get_logger


class LogUtils:
    """
    統一的日誌工具類別 (基於 loguru 的兼容層)
    Unified logging utility class (Compatibility layer based on loguru)
    """

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
        """
        logger = get_logger()
        if component:
            logger.bind(component=component).error(message)
        else:
            logger.bind(component="").error(message)

    @staticmethod
    def error_exc(
        message: str, component: str = "", exc: Optional[BaseException] = None
    ) -> None:
        """
        以統一格式輸出錯誤並附上 traceback（同時寫入檔案）
        Output error with traceback in unified format (write to file as well)

        Args:
            message (str): 錯誤訊息內容
            component (str): 可選的組件名稱，用於標識訊息來源
            exc (Optional[BaseException]): 可選的例外物件
        """
        if exc is not None:
            trace = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
        else:
            trace = traceback.format_exc()
        
        LogUtils.error(f"{message}\n{trace}", component)

    @staticmethod
    def info(message: str, component: str = "") -> None:
        """
        列印資訊訊息到控制台和檔案
        Print info message to console and file

        Args:
            message (str): 資訊訊息內容
            component (str): 可選的組件名稱，用於標識訊息來源
        """
        logger = get_logger()
        if component:
            logger.bind(component=component).info(message)
        else:
            logger.bind(component="").info(message)

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
        """
        logger = get_logger()
        if component:
            logger.bind(component=component).warning(message)
        else:
            logger.bind(component="").warning(message)

    @staticmethod
    def debug(message: str, component: str = "") -> None:
        """
        列印調試訊息到控制台和檔案，受設定檔控制是否顯示
        Print debug message to console and file, controlled by settings configuration

        Args:
            message (str): 調試訊息內容
            component (str): 可選的組件名稱，用於標識訊息來源
        """
        logger = get_logger()
        if component:
            logger.bind(component=component).debug(message)
        else:
            logger.bind(component="").debug(message)

    @staticmethod
    def debug_window_state(message: str) -> None:
        """
        列印視窗狀態調試訊息到控制台和檔案，使用統一的調試輸出判斷
        Print window state debug message to console and file, using unified debug output check

        Args:
            message (str): 視窗狀態調試訊息內容
        """
        logger = get_logger()
        logger.bind(component="WindowState").debug(message)
