"""伺服器執行時工具
集中啟停操作與 Java 命令建構。
"""

from __future__ import annotations
from pathlib import Path
from .. import JavaUtils
from .. import get_logger

logger = get_logger().bind(component="ServerRuntimeUtils")
__all__ = ["ServerCommands", "ServerOperations"]


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
        from .server_detection_utils import ServerDetectionUtils

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
