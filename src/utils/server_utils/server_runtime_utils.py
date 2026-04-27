"""伺服器執行時工具
集中啟停操作與 Java 命令建構。
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from .. import JavaUtils, PathUtils, get_logger
from .server_constants import (
    MANAGED_STARTUP_SCRIPT_NAME as DEFAULT_MANAGED_STARTUP_SCRIPT_NAME,
)
from .server_constants import (
    STARTUP_SCRIPT_CANDIDATES as DEFAULT_STARTUP_SCRIPT_CANDIDATES,
)

logger = get_logger().bind(component="ServerRuntimeUtils")
__all__ = ["JvmOptionPolicy", "ServerCommands", "ServerOperations"]


@dataclass(slots=True)
class StartupScriptCommand:
    """從既有啟動腳本擷取出的 Java 啟動命令。"""

    command_line: str = ""
    memory_max_mb: int | None = None
    memory_min_mb: int | None = None

    @property
    def has_java_command(self) -> bool:
        return bool(self.command_line)


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

    MANAGED_STARTUP_SCRIPT_NAME: ClassVar[str] = DEFAULT_MANAGED_STARTUP_SCRIPT_NAME
    STARTUP_SCRIPT_CANDIDATES: ClassVar[tuple[str, ...]] = DEFAULT_STARTUP_SCRIPT_CANDIDATES

    @staticmethod
    def _quote_windows_arg(arg: str) -> str:
        normalized = str(arg)
        if normalized.startswith('"') and normalized.endswith('"'):
            return normalized
        return f'"{normalized}"' if any(char.isspace() for char in normalized) else normalized

    @staticmethod
    def _strip_wrapping_quotes(arg: str) -> str:
        normalized = str(arg)
        if len(normalized) >= 2 and normalized.startswith('"') and normalized.endswith('"'):
            return normalized[1:-1]
        return normalized

    @staticmethod
    def _is_full_java_path(java_exe: str) -> bool:
        normalized = str(java_exe or "").strip().strip('"')
        if not normalized:
            return False
        if normalized.lower() in {"java", "java.exe", "javaw", "javaw.exe"}:
            return False
        return bool(
            Path(normalized).is_absolute() or re.match(r"^[A-Za-z]:[\\/]", normalized) or normalized.startswith("\\\\")
        )

    @staticmethod
    def to_console_java_executable(java_path: str | None) -> str | None:
        """將 `javaw.exe` 路徑轉為適合伺服器 console 使用的 `java.exe`。

        Args:
            java_path: 偵測到的 Java 執行檔路徑。

        Returns:
            對應的 console Java 路徑；無輸入時回傳 None。
        """
        if not java_path:
            return None
        java_exe = Path(str(java_path))
        if java_exe.name.lower() == "javaw.exe":
            return str(java_exe.with_name("java.exe"))
        return str(java_exe)

    @staticmethod
    def resolve_java_executable(server_config, fallback: str = "java") -> str:
        """依伺服器 Minecraft 版本解析應使用的 Java console 執行檔。

        Args:
            server_config: 伺服器設定物件。
            fallback: 找不到符合版本 Java 時使用的備援命令。

        Returns:
            完整 `java.exe` 路徑；找不到時回傳 fallback。
        """
        mc_version = str(getattr(server_config, "minecraft_version", "") or "").strip()
        if not mc_version or mc_version.lower() == "unknown":
            return fallback
        required_major = getattr(server_config, "java_major", None) or getattr(
            server_config, "java_major_version", None
        )
        try:
            java_path = JavaUtils.get_best_java_path(
                mc_version,
                required_major=int(required_major) if required_major else None,
                ask_download=False,
            )
        except Exception as exc:
            logger.warning(f"無法依 Minecraft {mc_version} 解析 Java 執行檔，將使用 {fallback}: {exc}")
            return fallback
        java_exe = ServerCommands.to_console_java_executable(java_path)
        return java_exe or fallback

    @staticmethod
    def split_windows_command_line(command_line: str) -> list[str]:
        """將 Windows bat 中的一行命令切成 `subprocess` 可用參數。

        Args:
            command_line: bat 檔中的單行命令。

        Returns:
            命令參數清單；解析失敗時回退到空白切分。
        """
        try:
            return [
                ServerCommands._strip_wrapping_quotes(arg)
                for arg in shlex.split(str(command_line), posix=False)
                if str(arg).strip()
            ]
        except ValueError:
            return [arg for arg in str(command_line).split() if arg]

    @staticmethod
    def _is_java_command_token(token: str) -> bool:
        normalized = ServerCommands._strip_wrapping_quotes(str(token or "").strip()).lower()
        if not normalized:
            return False
        token_path = Path(normalized)
        return normalized in {"java", "java.exe", "javaw", "javaw.exe"} or token_path.name in {
            "java",
            "java.exe",
            "javaw",
            "javaw.exe",
        }

    @staticmethod
    def _java_command_tokens_from_line(line: str) -> list[str]:
        body, _newline = ServerCommands._split_line_ending(line)
        stripped = body.strip()
        if not stripped:
            return []
        lower = stripped.lower()
        if lower.startswith(("rem ", "::", "echo ", "set ", "title ", "chcp ")):
            return []
        tokens = ServerCommands.split_windows_command_line(stripped)
        if tokens and str(tokens[0]).lower() == "call":
            tokens = tokens[1:]
        if not tokens:
            return []
        if not ServerCommands._is_java_command_token(tokens[0]):
            return []
        return tokens

    @staticmethod
    def extract_startup_script_command(script_path: Path) -> StartupScriptCommand:
        """讀取既有啟動腳本中的 Java 啟動命令。

        Args:
            script_path: 要讀取的啟動腳本路徑。

        Returns:
            擷取到的 Java 啟動命令與記憶體設定；找不到時回傳空命令。
        """
        from .server_memory_utils import MemoryUtils

        content = PathUtils.read_text_file(script_path, encoding="utf-8", errors="replace") or ""
        startup_command = StartupScriptCommand()
        if content.startswith("\ufeff"):
            content = content.removeprefix("\ufeff")
        for line in content.splitlines():
            tokens = ServerCommands._java_command_tokens_from_line(line)
            if not tokens:
                continue
            startup_command.command_line = line.strip()
            startup_command.memory_max_mb = MemoryUtils.parse_memory_setting(line, "Xmx")
            startup_command.memory_min_mb = MemoryUtils.parse_memory_setting(line, "Xms")
            break
        return startup_command

    @staticmethod
    def _split_line_ending(line: str) -> tuple[str, str]:
        for newline in ("\r\n", "\n", "\r"):
            if line.endswith(newline):
                return line[: -len(newline)], newline
        return line, ""

    @staticmethod
    def replace_java_command_line(line: str, java_exe: str) -> tuple[str, bool]:
        """替換單行 bat 命令開頭的 Java 執行檔。

        Args:
            line: 原始 bat 單行內容。
            java_exe: 要替換成的 Java 執行檔路徑。

        Returns:
            `(新行內容, 是否修改)`。
        """
        body, newline = ServerCommands._split_line_ending(line)
        stripped = body.strip()
        if not stripped:
            return (line, False)
        lower = stripped.lower()
        if lower.startswith(("rem ", "::", "echo ", "set ")):
            return (line, False)
        match = re.match(
            r'^(?P<prefix>\s*@?\s*(?:call\s+)?)(?P<java>"[^"]*(?:java|javaw)(?:\.exe)?"|[^\s"]*(?:java|javaw)(?:\.exe)?)(?P<suffix>(?:\s+.*)?)$',
            body,
            re.IGNORECASE,
        )
        if not match:
            return (line, False)
        replacement = (
            f"{match.group('prefix')}{ServerCommands._quote_windows_arg(java_exe)}{match.group('suffix')}{newline}"
        )
        return (replacement, replacement != line)

    @staticmethod
    def replace_bare_java_command_line(line: str, java_exe: str) -> tuple[str, bool]:
        """向後相容舊呼叫；目前也會替換完整 Java 路徑。

        Args:
            line: 原始 bat 單行內容。
            java_exe: 要替換成的 Java 執行檔路徑。

        Returns:
            `(新行內容, 是否修改)`。
        """
        return ServerCommands.replace_java_command_line(line, java_exe)

    @staticmethod
    def replace_startup_command_java_path(command_line: str, server_config) -> str:
        """將匯入啟動命令的 Java 執行檔替換為版本相符路徑。

        Args:
            command_line: 原始 Java 啟動命令。
            server_config: 伺服器設定物件。

        Returns:
            替換後的啟動命令；無法解析完整 Java 路徑時保留原命令。
        """
        java_exe = ServerCommands.resolve_java_executable(server_config)
        if not ServerCommands._is_full_java_path(java_exe):
            return command_line.strip()
        replaced_line, _changed = ServerCommands.replace_java_command_line(command_line.strip(), java_exe)
        return replaced_line.strip()

    @staticmethod
    def repair_startup_script_java_command(script_path: Path, server_config) -> bool:
        """將啟動腳本中的裸 `java` 改為符合 Minecraft 版本的完整 Java 路徑。

        Args:
            script_path: 要檢查的 bat 啟動腳本。
            server_config: 伺服器設定物件。

        Returns:
            腳本有被修改時回傳 True。
        """
        java_exe = ServerCommands.resolve_java_executable(server_config)
        if not ServerCommands._is_full_java_path(java_exe):
            logger.warning(
                f"找不到符合 {getattr(server_config, 'minecraft_version', '')} 的完整 Java 路徑，略過修補 {script_path.name}"
            )
            return False
        content = PathUtils.read_text_file(script_path, encoding="utf-8", errors="replace")
        if not content:
            return False
        changed = content.startswith("\ufeff")
        if changed:
            content = content.removeprefix("\ufeff")
        new_lines = []
        for line in content.splitlines(keepends=True):
            new_line, line_changed = ServerCommands.replace_bare_java_command_line(line, java_exe)
            changed = changed or line_changed
            new_lines.append(new_line)
        if not changed:
            return False
        if not PathUtils.write_text_file(script_path, "".join(new_lines), encoding="utf-8", errors="replace"):
            logger.error(f"無法寫入修補後的啟動腳本: {script_path}")
            return False
        logger.info(f"已修補啟動腳本 Java 路徑: {script_path}")
        return True

    @staticmethod
    def repair_startup_scripts_java_commands(server_path: Path, server_config) -> list[Path]:
        """檢查並修補伺服器資料夾中的已知 bat 啟動腳本。

        Args:
            server_path: 伺服器資料夾路徑。
            server_config: 伺服器設定物件。

        Returns:
            已被修改的啟動腳本路徑清單。
        """
        repaired: list[Path] = []
        for script_name in ServerCommands.STARTUP_SCRIPT_CANDIDATES:
            script_path = server_path / script_name
            if script_path.exists() and ServerCommands.repair_startup_script_java_command(script_path, server_config):
                repaired.append(script_path)
        return repaired

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
        java_exe = ServerCommands.resolve_java_executable(server_config)
        main_jar = ServerDetectionUtils.find_main_jar(server_path, loader_type, server_config)
        if loader_type in ("forge", "neoforge") and main_jar.startswith("@"):
            cmd_list = [java_exe, *jvm_args, main_jar, "nogui"]
            result_cmd = " ".join([ServerCommands._quote_windows_arg(java_exe), *jvm_args, main_jar, "nogui"])
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
