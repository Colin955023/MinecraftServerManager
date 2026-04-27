"""伺服器執行時工具
集中啟停操作與 Java 命令建構。
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from .. import JavaUtils, get_logger

logger = get_logger().bind(component="ServerRuntimeUtils")
__all__ = ["JvmOptionPolicy", "ServerCommands", "ServerOperations"]


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


class JvmOptionPolicy:
    """集中產生 Minecraft 伺服器 JVM 啟動參數建議。"""

    GC_OPTION_PREFIX = "-XX:+Use"
    LOW_LATENCY_PROFILE = "low_latency"

    @staticmethod
    def normalize_jvm_args(raw_args: Any) -> list[str]:
        """將使用者自訂 JVM 參數正規化為清單。

        Args:
            raw_args: 字串、序列或其他可忽略值。

        Returns:
            正規化後的 JVM 參數清單。
        """

        if raw_args is None:
            return []
        if isinstance(raw_args, str):
            try:
                return [arg for arg in shlex.split(raw_args) if arg]
            except ValueError:
                return [arg for arg in raw_args.split() if arg]
        if isinstance(raw_args, (list, tuple)):
            return [str(arg).strip() for arg in raw_args if str(arg).strip()]
        return []

    @staticmethod
    def has_gc_option(args: list[str]) -> bool:
        """檢查參數中是否已包含 GC 選項。"""

        return any(arg.startswith(JvmOptionPolicy.GC_OPTION_PREFIX) and arg.endswith("GC") for arg in args)

    @staticmethod
    def recommend_gc_args(
        *,
        memory_max_mb: int,
        java_major: int | None = None,
        performance_profile: str = "",
        existing_args: list[str] | None = None,
    ) -> list[str]:
        """依記憶體與 Java 版本產生 GC 建議。

        Args:
            memory_max_mb: 最大記憶體，單位 MB。
            java_major: Java major 版本；未知時可為 None。
            performance_profile: 效能設定檔，`low_latency` 表示偏低延遲。
            existing_args: 既有 JVM 參數；若已有 GC 參數則不覆蓋。

        Returns:
            建議加入的 JVM 參數清單。
        """

        normalized_existing_args = list(existing_args or [])
        if JvmOptionPolicy.has_gc_option(normalized_existing_args):
            return []
        normalized_profile = str(performance_profile or "").strip().lower()
        if normalized_profile == JvmOptionPolicy.LOW_LATENCY_PROFILE and java_major and java_major >= 17:
            return ["-XX:+UseZGC"]
        if int(memory_max_mb or 0) > 4096:
            return ["-XX:+UseG1GC"]
        return []


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
        custom_jvm_args = JvmOptionPolicy.normalize_jvm_args(getattr(server_config, "jvm_args", []))
        java_major = getattr(server_config, "java_major", None) or getattr(server_config, "java_major_version", None)
        performance_profile = str(getattr(server_config, "performance_profile", "") or "")
        recommended_jvm_args = JvmOptionPolicy.recommend_gc_args(
            memory_max_mb=int(memory_max),
            java_major=int(java_major) if java_major else None,
            performance_profile=performance_profile,
            existing_args=custom_jvm_args,
        )
        jvm_args = [*recommended_jvm_args, *custom_jvm_args]
        java_exe = (
            JavaUtils.get_best_java_path(
                str(getattr(server_config, "minecraft_version", "")),
                ask_download=False,
            )
            or "java"
        )
        java_exe = java_exe.replace("javaw.exe", "java.exe")
        main_jar = ServerDetectionUtils.find_main_jar(server_path, loader_type, server_config)
        if loader_type == "forge" and main_jar.startswith("@"):
            cmd_list = [java_exe, *jvm_args, main_jar, "nogui"]
            result_cmd = " ".join([java_exe, *jvm_args, main_jar, "nogui"])
        else:
            cmd_list = [java_exe, *jvm_args]
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
            jvm_arg_text = " ".join(jvm_args)
            if jvm_arg_text:
                result_cmd = f"{java_exe_quoted} {jvm_arg_text} {memory_args} -jar {main_jar_quoted} nogui"
            else:
                result_cmd = f"{java_exe_quoted} {memory_args} -jar {main_jar_quoted} nogui"
        if return_list:
            return cmd_list
        return result_cmd
