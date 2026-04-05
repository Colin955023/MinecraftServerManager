"""伺服器執行時工具
集中記憶體顯示、啟停操作與 Java 命令建構。
"""

from __future__ import annotations
import re
from pathlib import Path
from . import JavaUtils, get_logger

logger = get_logger().bind(component="ServerRuntimeUtils")
__all__ = ["MemoryUtils", "ServerCommands", "ServerOperations"]


class MemoryUtils:
    """記憶體工具類別，提供記憶體相關的解析和格式化功能。"""

    @staticmethod
    def parse_memory_setting(text: str, setting_type: str = "Xmx") -> int | None:
        """解析 Java 記憶體設定，統一處理 -Xmx 和 -Xms 參數。

        Args:
            text: 參數文字。
            setting_type: 設定類型，通常為 Xmx 或 Xms。

        Returns:
            以 MB 表示的記憶體大小；解析失敗時回傳 None。
        """
        if not text or not isinstance(text, str):
            return None
        if not setting_type or setting_type not in ["Xmx", "Xms"]:
            return None
        pattern = f"-{setting_type}(\\d+)([mMgG]?)"
        match = re.search(pattern, text)
        if match:
            val, unit = match.groups()
            try:
                val = int(val)
                if unit and unit.lower() == "g":
                    return val * 1024
                return val
            except ValueError:
                return None
        return None

    @staticmethod
    def format_memory_mb(memory_mb: int, compact: bool = True) -> str:
        """格式化記憶體大小（MB），自動選擇單位顯示。

        Args:
            memory_mb: 以 MB 表示的記憶體數值。
            compact: 是否使用簡寫格式。

        Returns:
            格式化後的字串。
        """
        if compact:
            if memory_mb >= 1024:
                return f"{memory_mb // 1024}G" if memory_mb % 1024 == 0 else f"{memory_mb / 1024:.1f}G"
            return f"{memory_mb}M"
        if memory_mb >= 1024:
            return f"{memory_mb / 1024:.1f} GB"
        return f"{memory_mb:.1f} MB"


class ServerOperations:
    """伺服器操作工具類別。"""

    @staticmethod
    def get_status_text(is_running: bool) -> tuple[str, str]:
        """獲取狀態文字和顏色。"""
        return ("🟢 狀態: 運行中", "green") if is_running else ("🔴 狀態: 已停止", "red")

    @staticmethod
    def graceful_stop_server(server_manager, server_name: str) -> bool:
        """優雅停止伺服器（先嘗試 stop 命令，失敗則強制停止）。

        Args:
            server_manager: 伺服器管理器實例。
            server_name: 目標伺服器名稱。

        Returns:
            成功停止時回傳 True。
        """
        try:
            command_success = server_manager.send_command(server_name, "stop")
            return command_success or server_manager.stop_server(server_name)
        except Exception as e:
            logger.exception(f"停止伺服器失敗: {e}")
            return False


class ServerCommands:
    """伺服器指令工具類別。"""

    @staticmethod
    def build_java_command(server_config, return_list: bool = False) -> list[str] | str:
        """構建 Java 啟動命令，根據伺服器配置自動偵測主要 JAR 和載入器類型。

        Args:
            server_config: 伺服器設定物件。
            return_list: 是否回傳命令列清單。

        Returns:
            Java 啟動命令字串或命令列清單。
        """
        from . import ServerDetectionUtils

        server_path = Path(server_config.path)
        loader_type = str(server_config.loader_type or "").lower()
        memory_min = server_config.memory_min_mb if server_config.memory_min_mb else None
        memory_max = server_config.memory_max_mb if server_config.memory_max_mb else 2048
        if memory_min is not None and (memory_max is None or memory_max < memory_min):
            memory_max = memory_min
        java_exe = JavaUtils.get_best_java_path(str(getattr(server_config, "minecraft_version", ""))) or "java"
        java_exe = java_exe.replace("javaw.exe", "java.exe")
        main_jar = ServerDetectionUtils.find_main_jar(server_path, loader_type, server_config)
        if loader_type == "forge" and main_jar.startswith("@"):
            cmd_list = [java_exe, main_jar, "nogui"]
            result_cmd = f"{java_exe} {main_jar} nogui"
        else:
            cmd_list = [java_exe]
            if memory_min:
                cmd_list.append(f"-Xms{memory_min}M")
            cmd_list.extend([f"-Xmx{memory_max}M", "-jar", main_jar, "nogui"])
            if " " in java_exe and (not (java_exe.startswith('"') and java_exe.endswith('"'))):
                java_exe_quoted = f'"{java_exe}"'
            else:
                java_exe_quoted = java_exe
            if " " in main_jar and (not (main_jar.startswith('"') and main_jar.endswith('"'))):
                main_jar_quoted = f'"{main_jar}"'
            else:
                main_jar_quoted = main_jar
            memory_args = f"-Xms{memory_min}M -Xmx{memory_max}M" if memory_min else f"-Xmx{memory_max}M"
            result_cmd = f"{java_exe_quoted} {memory_args} -jar {main_jar_quoted} nogui"
        if return_list:
            return cmd_list
        return result_cmd
