#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日誌工具模組 (基於 loguru)
提供統一的日誌記錄功能
Logging Utilities Module (Based on loguru)
Provides unified logging functionality using loguru
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger
from .constants import MB


class LoggerConfig:
    """Loguru 日誌配置管理"""
    
    _initialized = False
    _log_dir: Optional[Path] = None
    _max_folder_size_mb = 10
    _target_cleanup_size_mb = 8  # 當超過限制時，刪除相當於 8MB 的舊日誌
    _settings_manager = None  # 快取 settings manager
    
    @classmethod
    def initialize(cls) -> None:
        """
        初始化 loguru 日誌系統
        Initialize loguru logging system
        """
        if cls._initialized:
            return
        
        try:
            # 移除預設的 stderr handler
            logger.remove()
            
            # 取得日誌目錄路徑
            cls._log_dir = cls._get_log_directory()
            cls._log_dir.mkdir(parents=True, exist_ok=True)
            
            # 清理超過大小限制的舊日誌
            cls._cleanup_old_logs_if_needed()
            
            # 建立日誌檔案名稱（格式：年-月-日-時-分.log）
            log_filename = datetime.now().strftime("%Y-%m-%d-%H-%M.log")
            log_file_path = cls._log_dir / log_filename
            
            # 添加檔案 handler
            logger.add(
                log_file_path,
                format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[component]: <15} | {message}",
                level="DEBUG",
                encoding="utf-8",
                enqueue=True,  # 執行緒安全
            )
            
            # 添加控制台 handler（根據設定決定是否顯示）
            logger.add(
                sys.stderr,
                format="<level>{level: <8}</level> | <cyan>{extra[component]: <15}</cyan> | <level>{message}</level>",
                level="DEBUG",
                colorize=True,
                filter=cls._console_filter,
            )
            
            cls._initialized = True
            logger.bind(component="Logger").info(f"日誌系統初始化完成，日誌檔案：{log_file_path}")
            
        except Exception as e:
            # 如果初始化失敗，添加一個基本的 stderr handler
            logger.add(sys.stderr, level="ERROR")
            logger.bind(component="Logger").error(f"日誌系統初始化失敗: {e}")
            cls._initialized = True
    
    @classmethod
    def _get_log_directory(cls) -> Path:
        """
        取得日誌目錄路徑
        Get log directory path
        
        Returns:
            Path: 日誌目錄路徑 (%LOCALAPPDATA%/Programs/MinecraftServerManager/log)
        """
        localappdata = os.environ.get("LOCALAPPDATA")
        if not localappdata:
            localappdata = str(Path.home() / "AppData" / "Local")
        
        return Path(localappdata) / "Programs" / "MinecraftServerManager" / "log"
    
    @classmethod
    def _get_folder_size_mb(cls, folder: Path) -> float:
        """
        計算資料夾大小（MB）
        Calculate folder size in MB
        
        Args:
            folder (Path): 資料夾路徑
            
        Returns:
            float: 資料夾大小（MB）
        """
        total_size = 0
        try:
            for file in folder.glob("*.log"):
                if file.is_file():
                    total_size += file.stat().st_size
        except Exception:
            pass
        
        return total_size / MB
    
    @classmethod
    def _cleanup_old_logs_if_needed(cls) -> None:
        """
        檢查日誌資料夾大小，如果超過 10MB 則刪除相當於 8MB 的舊日誌
        Check log folder size, delete logs worth 8MB if exceeds 10MB
        """
        if cls._log_dir is None:
            return
        
        try:
            folder_size = cls._get_folder_size_mb(cls._log_dir)
            
            if folder_size > cls._max_folder_size_mb:
                # 取得所有日誌檔案並按修改時間排序（最舊的在前）
                log_files = sorted(
                    cls._log_dir.glob("*.log"),
                    key=lambda f: f.stat().st_mtime
                )
                
                # 刪除舊日誌直到釋放 8MB 空間
                deleted_size_mb = 0.0
                files_deleted = 0
                target_mb = cls._target_cleanup_size_mb
                
                for log_file in log_files:
                    if deleted_size_mb >= target_mb:
                        break
                    
                    try:
                        # 取得檔案大小（MB）
                        file_size_mb = log_file.stat().st_size / MB
                        log_file.unlink()
                        deleted_size_mb += file_size_mb
                        files_deleted += 1
                    except Exception:
                        pass
                
                if files_deleted > 0:
                    logger.bind(component="Logger").info(
                        f"日誌資料夾大小超過 {cls._max_folder_size_mb}MB，已刪除 {files_deleted} 個舊日誌檔案（釋放 {deleted_size_mb:.2f}MB）"
                    )
        except Exception as e:
            logger.bind(component="Logger").warning(f"清理舊日誌時發生錯誤: {e}")
    
    @classmethod
    def _console_filter(cls, record) -> bool:
        """
        控制台輸出過濾器
        Console output filter based on settings
        
        Args:
            record: loguru 日誌記錄
            
        Returns:
            bool: True 表示應該輸出，False 表示不輸出
        """
        level = record["level"].name
        
        # ERROR 和 WARNING 一律輸出
        if level in ("ERROR", "WARNING", "CRITICAL"):
            return True
        
        # DEBUG 和 INFO 根據設定決定
        try:
            # 使用快取的 settings manager
            if cls._settings_manager is None:
                from .settings_manager import get_settings_manager
                cls._settings_manager = get_settings_manager()
            return cls._settings_manager.is_debug_logging_enabled()
        except Exception:
            # 如果無法取得設定，DEBUG 不輸出，INFO 輸出
            return level == "INFO"
    
    @classmethod
    def get_logger(cls):
        """
        取得 logger 實例
        Get logger instance
        
        Returns:
            logger: loguru logger 實例
        """
        if not cls._initialized:
            cls.initialize()
        return logger


# 初始化並取得 logger
_logger = LoggerConfig.get_logger()


def get_logger():
    """取得全域 logger 實例"""
    return _logger


# 便捷函數，直接使用 loguru（不需要 component 參數時的簡化版本）
def info(message: str, component: str = ""):
    """記錄 INFO 級別訊息"""
    _logger.bind(component=component or "").info(message)


def warning(message: str, component: str = ""):
    """記錄 WARNING 級別訊息"""
    _logger.bind(component=component or "").warning(message)


def error(message: str, component: str = ""):
    """記錄 ERROR 級別訊息"""
    _logger.bind(component=component or "").error(message)


def debug(message: str, component: str = ""):
    """記錄 DEBUG 級別訊息"""
    _logger.bind(component=component or "").debug(message)


def error_with_exception(message: str, component: str = "", exc: Exception = None):
    """記錄錯誤並附上 traceback"""
    import traceback
    if exc is not None:
        trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    else:
        trace = traceback.format_exc()
    error(f"{message}\n{trace}", component)
