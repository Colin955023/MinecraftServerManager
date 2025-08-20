#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
伺服器操作工具模組
提供伺服器管理的常用操作函數，包含路徑處理、伺服器狀態管理等功能
Server Operations Utility Module
Provides common operations for server management including path handling, server status management
"""
# ====== 標準函式庫 ======
from pathlib import Path
from typing import Union

# ====== 路徑處理工具類別 ======
class PathUtils:
    """
    路徑處理工具類別，提供專案路徑管理和安全路徑操作
    Path utilities class for project path management and safe path operations
    """
    # 取得專案根目錄路徑
    @staticmethod
    def get_project_root() -> Path:
        """
        獲取專案根目錄路徑
        Get project root directory path

        Args:
            None

        Returns:
            Path: 專案根目錄路徑物件
        """
        return Path(__file__).parent.parent.parent

    # 取得資源目錄路徑
    @staticmethod
    def get_assets_path() -> Path:
        """
        獲取 assets 目錄路徑
        Get assets directory path

        Args:
            None

        Returns:
            Path: assets 目錄路徑物件
        """
        return PathUtils.get_project_root() / "assets"


class ServerOperations:
    """伺服器操作工具類別"""

    @staticmethod
    def get_status_text(is_running: bool) -> tuple:
        """獲取狀態文字和顏色"""
        if is_running:
            return "🟢 狀態: 運行中", "green"
        else:
            return "🔴 狀態: 已停止", "red"

    @staticmethod
    def graceful_stop_server(server_manager, server_name: str) -> bool:
        """優雅停止伺服器（先嘗試 stop 命令，失敗則強制停止）"""
        from src.utils.log_utils import LogUtils
        try:
            # 先嘗試使用 stop 命令
            command_success = server_manager.send_command(server_name, "stop")
            if command_success:
                return True
            else:
                # 如果命令失敗，使用強制停止
                return server_manager.stop_server(server_name)
        except Exception as e:
            LogUtils.error(f"停止伺服器失敗: {e}", "ServerOperations")
            return False

class ServerCommands:
    """伺服器指令"""

    @staticmethod
    def build_java_command(self, server_config, return_list=False) -> Union[list, str]:
        """
        構建 Java 啟動命令（統一邏輯）
        Build Java launch command (unified logic)

        Args:
            server_config: 伺服器配置對象
            return_list: 是否返回列表格式 (True) 或字符串格式 (False)

        Returns:
            list or str: Java 啟動命令
        """
        server_path = Path(server_config.path)
        loader_type = str(server_config.loader_type or "").lower()
        memory_min = max(512, getattr(server_config, "memory_min_mb", 1024))
        memory_max = max(memory_min, getattr(server_config, "memory_max_mb", 2048))
        # 延遲導入避免循環導入錯誤
        from . import java_utils

        # Java 執行檔自動偵測
        java_exe = (
            java_utils.get_best_java_path(
                getattr(server_config, "minecraft_version", None)
            )
            or "java"
        )

        # 偵測主 JAR 檔案（延遲匯入打破循環依賴）
        from src.core.server_detection import ServerDetectionUtils
        main_jar = ServerDetectionUtils.detect_main_jar_file(server_path, loader_type)

        # 構建命令
        cmd_list = [java_exe, f"-Xms{memory_min}M", f"-Xmx{memory_max}M", "-jar", main_jar, "nogui"]

        if return_list:
            return cmd_list
        else:
            # 處理包含空格的路徑
            if " " in java_exe and not (java_exe.startswith('"') and java_exe.endswith('"')):
                java_exe = f'"{java_exe}"'
            return f'{java_exe} -Xms{memory_min}M -Xmx{memory_max}M -jar "{main_jar}" nogui'
