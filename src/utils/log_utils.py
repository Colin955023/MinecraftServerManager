#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日誌工具模組
提供統一的日誌記錄功能
Logging Utilities Module
Provides unified logging functionality
"""
# ====== 日誌工具類別 ======
class LogUtils:
    """
    統一的日誌工具類別
    Unified logging utility class for consistent message output with color coding
    """
    
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

    # 輸出錯誤訊息到控制台
    @staticmethod
    def error(message: str, component: str = ""):
        """
        列印錯誤訊息到控制台，使用紅色標記
        錯誤訊息一律輸出，不受調試設定控制
        Print error message to console with red color marking
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
            
    # 輸出資訊訊息到控制台
    @staticmethod
    def info(message: str, component: str = ""):
        """
        列印資訊訊息到控制台
        Print info message to console

        Args:
            message (str): 資訊訊息內容
            component (str): 可選的組件名稱，用於標識訊息來源
            
        Returns:
            None
        """
        if not LogUtils._should_show_debug_output():
            return

        if component:
            print(f"[INFO][{component}] {message}")
        else:
            print(f"[INFO] {message}")

    # 輸出警告訊息到控制台
    @staticmethod
    def warning(message: str, component: str = ""):
        """
        列印警告訊息到控制台，使用黃色標記
        警告訊息一律輸出，不受調試設定控制
        Print warning message to console with yellow color marking
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

    # 輸出調試訊息到控制台（受設定控制）
    @staticmethod
    def debug(message: str, component: str = ""):
        """
        列印調試訊息到控制台，受設定檔控制是否顯示
        Print debug message to console, controlled by settings configuration
        
        Args:
            message (str): 調試訊息內容
            component (str): 可選的組件名稱，用於標識訊息來源
            
        Returns:
            None
        """
        if not LogUtils._should_show_debug_output():
            return

        if component:
            print(f"\033[94m[DEBUG][{component}] {message}\033[0m")
        else:
            print(f"\033[94m[DEBUG] {message}\033[0m")

    # 輸出視窗狀態調試訊息
    @staticmethod
    def debug_window_state(message: str):
        """
        列印視窗狀態調試訊息，使用統一的調試輸出判斷
        Print window state debug message, using unified debug output check
        
        Args:
            message (str): 視窗狀態調試訊息內容
            
        Returns:
            None
        """
        if not LogUtils._should_show_debug_output():
            return

        print(f"\033[94m[DEBUG] {message}\033[0m")
