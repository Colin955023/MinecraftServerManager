"""伺服器管理器
負責建立、管理與配置 Minecraft 伺服器。
"""

import contextlib
import os
import threading
import time
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, cast

from PySide6 import QtCore

from ..models import ServerConfig
from ..utils import (
    PathUtils,
    ServerCommands,
    ServerDetectionUtils,
    ServerPropertiesHelper,
    SubprocessUtils,
    SystemUtils,
    atomic_write_json,
    get_logger,
    record_and_mark,
)
from . import ServerInstance

logger = get_logger().bind(component="ServerManager")


@dataclass(slots=True)
class ServerOperationResult:
    """描述伺服器操作結果，供 UI 層決定如何呈現。"""

    success: bool
    title: str = ""
    message: str = ""
    server_name: str = ""

    @property
    def failed(self) -> bool:
        return not self.success


class ServerManager:
    """負責建立、管理和配置 Minecraft 伺服器"""

    STARTUP_CHECK_DELAY = 0.1
    STOP_CHECK_INTERVAL = 0.1
    STOP_TIMEOUT_SECONDS = 5
    OUTPUT_QUEUE_MAX_SIZE = 1000

    def __init__(self, servers_root: str | None = None):
        if not servers_root:
            raise ValueError("ServerManager 必須指定 servers_root 路徑，且不可為空。請於 UI 層先處理。")
        self.servers_root = Path(servers_root).resolve()
        self.servers_root.mkdir(parents=True, exist_ok=True)
        self.config_file = self.servers_root / "servers_config.json"
        self.servers: dict[str, ServerConfig] = {}
        self.running_servers: dict[str, ServerInstance] = {}
        self._properties_cache: dict[str, Any] = {}
        self._config_lock = threading.Lock()
        self.load_servers_config()
        if not self.config_file.exists():
            self.write_servers_config()

    @staticmethod
    def _success_result(message: str = "", *, server_name: str = "") -> ServerOperationResult:
        """建立成功結果。"""
        return ServerOperationResult(success=True, message=message, server_name=server_name)

    @staticmethod
    def _failure_result(title: str, message: str, *, server_name: str = "") -> ServerOperationResult:
        """建立失敗結果。"""
        return ServerOperationResult(success=False, title=title, message=message, server_name=server_name)

    def _cleanup_running_server_state(self, server_name: str) -> None:
        """清除執行中伺服器的 runtime 狀態。"""
        instance = self.running_servers.pop(server_name, None)
        if instance is not None:
            process = instance.get_process()
            if process is not None:
                SystemUtils.unregister_managed_process(instance.path, self._process_pid(process))
            instance.clear_process()
            instance.clear_output_buffer()

    def _cleanup_failed_runtime_process(self, server_name: str, server_path: Path | None, process: Any | None) -> bool:
        """在建立/啟動流程異常時清理殘留進程。"""
        cleaned = False
        if process is not None:
            try:
                pid = self._process_pid(process)
                if self._process_is_running(process):
                    with contextlib.suppress(Exception):
                        process.kill()
                    cleaned = bool(SystemUtils.kill_process_tree(pid)) or cleaned
                if server_path is not None:
                    SystemUtils.unregister_managed_process(server_path, pid)
            except Exception as e:
                logger.warning(f"清理伺服器進程樹失敗: {server_name} | {e}")
        try:
            if server_path and server_path.exists():
                cleaned = bool(SystemUtils.kill_java_processes_in_path(server_path)) or cleaned
        except Exception as e:
            logger.warning(f"清理伺服器資料夾下 Java 進程失敗: {server_name} | {e}")
        if cleaned:
            logger.warning(f"流程失敗後已清理伺服器殘留進程: {server_name}")
        return cleaned

    def _get_running_instance(self, server_name: str) -> ServerInstance | None:
        """取得仍在執行中的 instance；若已過期則自動清理。"""
        instance = self.running_servers.get(server_name)
        if instance is None:
            return None
        try:
            if instance.is_running():
                return instance
        except Exception as e:
            logger.error(f"檢查伺服器狀態時發生錯誤: {e}")
        process = instance.get_process()
        if process is None:
            self._cleanup_running_server_state(server_name)
            return None
        self._cleanup_running_server_state(server_name)
        return None

    @staticmethod
    def _process_pid(process: Any) -> int:
        return ServerInstance.process_pid(process)

    @staticmethod
    def _process_is_running(process: Any) -> bool:
        return ServerInstance.process_is_running(process)

    @staticmethod
    def _process_returncode(process: Any) -> int | None:
        return ServerInstance.process_returncode(process)

    @staticmethod
    def _get_process_metadata(process: Any, key: str, default: Any = None) -> Any:
        if isinstance(process, QtCore.QObject):
            value = process.property(key)
            return default if value is None else value
        return getattr(process, key.removeprefix("_msm_"), default)

    @staticmethod
    def _set_process_metadata(process: Any, key: str, value: Any) -> None:
        if isinstance(process, QtCore.QObject):
            process.setProperty(key, value)
        with contextlib.suppress(Exception):
            setattr(process, key.removeprefix("_msm_"), value)

    @staticmethod
    def _startup_script_command(script_path: Path) -> list[str]:
        if os.name == "nt" and script_path.suffix.lower() in {".bat", ".cmd"}:
            return ["cmd.exe", "/d", "/s", "/c", str(script_path)]
        return [str(script_path)]

    @staticmethod
    def _decode_process_output(process: QtCore.QProcess) -> str:
        data = process.readAllStandardOutput()
        return bytes(cast(Any, data)).decode("utf-8", errors="replace")

    @staticmethod
    def _write_process_command(process: Any, command: str) -> bool:
        payload = f"{command}\n"
        if isinstance(process, QtCore.QProcess):
            if process.state() == QtCore.QProcess.ProcessState.NotRunning:
                return False
            process.write(payload.encode("utf-8"))
            return bool(process.waitForBytesWritten(1000))
        if process.stdin:
            process.stdin.write(payload)
            process.stdin.flush()
            return True
        return False

    @staticmethod
    def _wait_for_process_exit(process: Any, timeout_seconds: float, interval_seconds: float | None = None) -> bool:
        """在指定期限內等待 process 結束。"""
        if isinstance(process, QtCore.QProcess):
            if timeout_seconds <= 0:
                return process.state() == QtCore.QProcess.ProcessState.NotRunning
            return process.waitForFinished(max(1, int(timeout_seconds * 1000)))
        if timeout_seconds <= 0:
            return process.poll() is not None
        wait_interval = interval_seconds if interval_seconds and interval_seconds > 0 else timeout_seconds
        deadline = time.monotonic() + timeout_seconds
        while True:
            if process.poll() is not None:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return process.poll() is not None
            time.sleep(min(wait_interval, remaining))

    def _validate_server_runtime_path(self, config: ServerConfig) -> tuple[Path | None, ServerOperationResult | None]:
        """在啟動前驗證伺服器路徑是否安全且可用。"""
        try:
            server_path = Path(config.path).resolve(strict=False)
        except Exception as e:
            return (
                None,
                self._failure_result("伺服器路徑無效", f"伺服器路徑無效: {e}", server_name=getattr(config, "name", "")),
            )
        if not PathUtils.is_path_within(self.servers_root, server_path, strict=False):
            return (
                None,
                self._failure_result(
                    "伺服器路徑無效",
                    f"伺服器路徑必須位於伺服器資料夾內: {server_path}",
                    server_name=getattr(config, "name", ""),
                ),
            )
        if not server_path.exists():
            return (
                None,
                self._failure_result(
                    "伺服器路徑不存在",
                    f"伺服器路徑不存在: {server_path}",
                    server_name=getattr(config, "name", ""),
                ),
            )
        if not server_path.is_dir():
            return (
                None,
                self._failure_result(
                    "伺服器路徑無效",
                    f"伺服器路徑不是資料夾: {server_path}",
                    server_name=getattr(config, "name", ""),
                ),
            )
        return (server_path, None)

    def create_server_result(
        self, config: ServerConfig, properties: dict[str, str] | None = None
    ) -> ServerOperationResult:
        """建立新伺服器並初始化設定。

        Args:
            config: 要建立的伺服器設定。
            properties: 要寫入 server.properties 的初始屬性。

        Returns:
            建立流程結果，供 UI 或呼叫端決定後續呈現。
        """
        server_path: Path | None = None
        previous_config = self.servers.get(config.name)
        added_server_entry = False
        created_server_dir = False
        try:
            server_path = (self.servers_root / config.name).resolve()
            if not PathUtils.is_path_within(self.servers_root, server_path, strict=False):
                raise ValueError(f"無效的伺服器名稱 (路徑遍歷偵測): {config.name}")
            if server_path.exists():
                raise FileExistsError(f"伺服器資料夾已存在: {server_path}")
            server_path.mkdir()
            created_server_dir = True
            config.path = str(server_path)
            need_detect = (
                not config.loader_type
                or config.loader_type == "unknown"
                or (not config.minecraft_version)
                or (config.minecraft_version == "unknown")
                or (
                    config.loader_type
                    and config.loader_type.lower() in ["forge", "fabric"]
                    and (not config.loader_version or config.loader_version == "unknown")
                )
            )
            if need_detect:
                try:
                    ServerDetectionUtils.detect_server_type(server_path, config)
                    if not config.loader_type or config.loader_type == "unknown":
                        raise Exception(
                            f"偵測失敗：loader_type 無法判斷，name={config.name}, path={config.path}, loader_type={config.loader_type}, minecraft_version={config.minecraft_version}, loader_version={config.loader_version}"
                        )
                    if not config.minecraft_version or config.minecraft_version == "unknown":
                        raise Exception(
                            f"偵測失敗：minecraft_version 無法判斷，name={config.name}, path={config.path}, loader_type={config.loader_type}, minecraft_version={config.minecraft_version}, loader_version={config.loader_version}"
                        )
                    if config.loader_type.lower() in ["forge", "fabric"] and (
                        not config.loader_version or config.loader_version == "unknown"
                    ):
                        raise Exception(
                            f"偵測失敗：loader_version 無法判斷，name={config.name}, path={config.path}, loader_type={config.loader_type}, minecraft_version={config.minecraft_version}, loader_version={config.loader_version}"
                        )
                except Exception as e:
                    logger.error(f"自動偵測伺服器類型失敗: {e}")
                    raise
            if not self._create_eula_file(server_path):
                raise RuntimeError(f"建立 EULA 檔案失敗: {server_path}")
            config.eula_accepted = True
            self._create_server_structure(Path(config.path), config.loader_type)
            properties_file = server_path / "server.properties"
            if properties is None:
                properties = self.get_default_server_properties()
            properties = dict(properties)
            properties["motd"] = f"Minecraft 伺服器 - {config.name}"
            if not ServerPropertiesHelper.save_properties(properties_file, properties):
                raise RuntimeError(f"儲存 server.properties 失敗: {properties_file}")
            config.properties = properties
            if not self.create_launch_script(config):
                raise RuntimeError(f"建立啟動腳本失敗: {server_path}")
            self.servers[config.name] = config
            added_server_entry = True
            if not self.write_servers_config():
                raise RuntimeError(f"儲存伺服器設定失敗: {config.name}")
            return self._success_result(f"伺服器 {config.name} 已建立", server_name=config.name)
        except Exception as e:
            if added_server_entry:
                if previous_config is not None:
                    self.servers[config.name] = previous_config
                else:
                    self.servers.pop(config.name, None)
            try:
                if created_server_dir and server_path and server_path.exists():
                    # 回滾時只移除本次建立的伺服器資料夾，避免殘留半成品。
                    PathUtils.delete_within(self.servers_root, server_path)
            except Exception:
                server_path = server_path
            # 嘗試終止殘留 Java 進程
            try:
                killed = False
                if server_path and server_path.exists():
                    # 掃描該資料夾下的 java 進程
                    killed = SystemUtils.kill_java_processes_in_path(server_path)
                    if killed:
                        logger.warning(f"異常建立失敗，自動終止殘留 Java 進程於: {server_path}")
            except Exception as kill_exc:
                logger.error(f"自動終止殘留 Java 進程失敗: {kill_exc}")
            record_and_mark(
                e, marker_path=server_path, reason="建立伺服器失敗", details={"server": getattr(config, "name", None)}
            )
            return self._failure_result(
                "建立失敗",
                f"建立過程發生錯誤，已嘗試清理殘留 Java 進程。請檢查日誌與 .issues 目錄。\n錯誤: {e}",
                server_name=getattr(config, "name", ""),
            )

    def create_server(self, config: ServerConfig, properties: dict[str, str] | None = None) -> bool:
        """建立新伺服器並初始化設定。

        Args:
            config: 要建立的伺服器設定。
            properties: 建立後要額外寫入的 `server.properties` 內容。

        Returns:
            建立成功時回傳 True，否則回傳 False。
        """

        return self.create_server_result(config, properties).success

    def _create_eula_file(self, server_path: Path) -> bool:
        """建立並同意 EULA 檔案。"""
        eula_content = "eula=true"
        return PathUtils.write_text_file(server_path / "eula.txt", eula_content)

    def _create_server_structure(self, path: Path, loader_type: str) -> None:
        """建立伺服器檔案結構"""
        if loader_type.lower() == "vanilla":
            directories = ["world", "logs"]
        elif loader_type.lower() in ["forge", "fabric"]:
            directories = ["world", "plugins", "mods", "config", "logs"]
        else:
            directories = ["world", "logs"]
            logger.warning(f"未知 loader_type: {loader_type}，使用預設目錄結構")
        for directory in directories:
            (path / directory).mkdir(exist_ok=True)

    def create_launch_script(self, config: ServerConfig, java_command_override: str | None = None) -> bool:
        """建立伺服器啟動腳本。

        Args:
            config: 伺服器設定與啟動參數來源。
            java_command_override: 匯入既有伺服器時保留的原始 Java 啟動命令。

        Returns:
            啟動腳本寫入成功時回傳 True，失敗時回傳 False。
        """
        server_path = Path(config.path)
        if java_command_override:
            java_command_str = java_command_override.strip()
        else:
            java_cmd_list = ServerCommands.build_java_command(config, return_list=True)
            logger.debug(f"Java 命令列表: {java_cmd_list}")
            java_exe = java_cmd_list[0]
            if " " in java_exe and (not (java_exe.startswith('"') and java_exe.endswith('"'))):
                java_exe = f'"{java_exe}"'
            uses_args_file = len(java_cmd_list) >= 2 and java_cmd_list[1].startswith("@")
            if uses_args_file:
                args_spec = java_cmd_list[1]
                args_rel_path = args_spec[1:]
                args_path = server_path / args_rel_path
                if args_path.exists():
                    java_command_str = f"{java_exe} {args_spec} nogui"
                else:
                    logger.warning(f"參數檔案不存在: {args_path}")
                    java_command_str = f"{java_exe} {args_spec} nogui"
            else:
                cmd_parts = [java_exe]
                i = 1
                while i < len(java_cmd_list):
                    arg = java_cmd_list[i]
                    if arg == "-jar" and i + 1 < len(java_cmd_list):
                        cmd_parts.append(arg)
                        jar_spec = java_cmd_list[i + 1]
                        jar_path = server_path / jar_spec
                        if jar_path.exists():
                            cmd_parts.append(f'"{jar_path.resolve()}"')
                        else:
                            cmd_parts.append(f'"{jar_spec}"')
                        i += 2
                    else:
                        cmd_parts.append(arg)
                        i += 1
                java_command_str = " ".join(cmd_parts)
        bat_lines = [
            "@echo off",
            "chcp 65001 >nul",
            'cd /d "%~dp0"',
            "",
            java_command_str,
        ]
        bat_content = "\n".join(bat_lines)
        start_script_path = server_path / "start_server.bat"
        try:
            if start_script_path.exists():
                existing_bytes = start_script_path.read_bytes()
                existing_has_bom = existing_bytes.startswith(b"\xef\xbb\xbf")
                existing_content = existing_bytes.decode("utf-8-sig", errors="ignore")
                if existing_content == bat_content and not existing_has_bom:
                    logger.debug("啟動腳本內容未變更，跳過寫入")
                    return True
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(
                    e,
                    marker_path=start_script_path,
                    reason="compare_start_script_failed",
                    details={"server": getattr(config, "name", None)},
                )
            logger.debug(f"比較啟動腳本時發生錯誤 (將強制覆寫): {e}")
        return PathUtils.write_text_file(start_script_path, bat_content, encoding="utf-8", errors="replace")

    def update_server_properties(self, server_name: str, properties: dict[str, str]) -> bool:
        """更新 server.properties，只覆蓋有變動的欄位，其餘欄位保留原值。

        Args:
            server_name: 目標伺服器名稱。
            properties: 要合併寫入的屬性。

        Returns:
            成功時回傳 True，失敗時回傳 False。
        """
        try:
            config = self.servers.get(server_name)
            if not config:
                logger.error(f"update_server_properties 找不到伺服器設定: {server_name}")
                return False
            server_path = getattr(config, "path", None) or getattr(config, "server_path", None)
            if not server_path:
                logger.error(f"找不到伺服器路徑，無法儲存 server.properties。config={config}")
                return False
            properties_path = Path(server_path) / "server.properties"
            original = ServerPropertiesHelper.load_properties(properties_path)
            merged = {**original, **properties}
            changed_keys = sorted((key for key, value in merged.items() if original.get(key) != value))
            logger.info(
                f"準備儲存 server.properties: server={server_name}, path={properties_path}, changed_keys={len(changed_keys)}"
            )
            if not ServerPropertiesHelper.save_properties(properties_path, merged):
                logger.error(f"儲存 server.properties 失敗: server={server_name}, path={properties_path}")
                return False
            try:
                mtime = properties_path.stat().st_mtime
            except OSError:
                mtime = time.time()
            self._properties_cache[server_name] = (mtime, dict(merged))
            config.properties = merged
            if not self.write_servers_config():
                logger.error(f"儲存 servers_config.json 失敗: server={server_name}")
                return False
            logger.info(
                f"server.properties 與 servers_config.json 已同步保存: server={server_name}, changed_keys={changed_keys}"
            )
            return True
        except Exception as e:
            try:
                properties_path = Path(getattr(self.servers.get(server_name), "path", "")) / "server.properties"
            except Exception:
                properties_path = None
            record_and_mark(
                e,
                marker_path=properties_path,
                reason="update_server_properties 儲存失敗",
                details={"server": server_name},
            )
            return False

    def _resolve_startup_script_for_run(self, config: ServerConfig, server_path: Path) -> Path | None:
        """啟動前取得實際要執行的啟動腳本。"""
        script_path = ServerDetectionUtils.find_startup_script(server_path)
        if script_path is not None:
            logger.debug(f"使用既有啟動腳本，啟動前確認 Java 路徑: {script_path}")
            ServerCommands.repair_startup_script_java_command(script_path, config)
            return script_path
        if not self.create_launch_script(config):
            logger.error(f"建立啟動腳本失敗: {server_path}")
            return None
        return ServerDetectionUtils.find_startup_script(server_path)

    def start_server_result(self, server_name: str) -> ServerOperationResult:
        """啟動伺服器。

        Args:
            server_name: 目標伺服器名稱。

        Returns:
            啟動流程結果。
        """
        process = None
        try:
            if server_name not in self.servers:
                return self._failure_result("伺服器未找到", f"找不到伺服器: {server_name}", server_name=server_name)
            config = self.servers[server_name]
            server_path, validation_result = self._validate_server_runtime_path(config)
            if validation_result is not None:
                return validation_result
            if server_path is None:
                return self._failure_result("啟動失敗", f"無法解析伺服器路徑: {server_name}", server_name=server_name)
            script_path = self._resolve_startup_script_for_run(config, server_path)
            if script_path:
                logger.info(f"找到啟動腳本: {script_path}")
            else:
                return self._failure_result(
                    "啟動腳本未找到",
                    "找不到啟動腳本 (run.bat, start.bat, server.bat, start_server.bat)",
                    server_name=server_name,
                )
            logger.debug(f"準備啟動伺服器: {server_name}")
            logger.debug(f"腳本路徑: {script_path}")
            logger.debug(f"工作目錄: {server_path}")
            try:
                abs_script_path = script_path.resolve()
                abs_server_path = server_path.resolve()
                cmd = self._startup_script_command(abs_script_path)
                logger.debug(f"執行命令: {cmd}")
                logger.debug(f"工作目錄: {abs_server_path}")
                process = SubprocessUtils.create_qprocess_checked(cmd, cwd=str(abs_server_path))
                process.start()
                if not process.waitForStarted(10000):
                    return self._failure_result(
                        "啟動失敗",
                        f"伺服器進程無法啟動：{process.errorString()}",
                        server_name=server_name,
                    )
                pid = int(process.processId())
                self._set_process_metadata(process, "_msm_pid", pid)
                self._set_process_metadata(process, "_msm_create_time", time.time())
                SystemUtils.register_managed_process(abs_server_path, pid)
                if self._wait_for_process_exit(process, self.STARTUP_CHECK_DELAY):
                    poll_result = self._process_returncode(process)
                    logger.error(f"進程立即結束，返回碼: {poll_result}")
                    try:
                        stdout = self._decode_process_output(process)
                        if stdout:
                            logger.error(f"程式輸出: {stdout}")
                    except Exception as e:
                        logger.exception(f"無法讀取程式輸出: {e}")
                    script_content = PathUtils.read_text_file(script_path)
                    if script_content is not None:
                        logger.debug(f"啟動腳本內容:\n{script_content}")
                    else:
                        logger.error(f"無法讀取啟動腳本: {script_path}")
                    return self._failure_result(
                        "啟動失敗",
                        f"伺服器進程立即結束，返回碼: {poll_result}\n請檢查日誌了解詳細資訊",
                        server_name=server_name,
                    )
                instance = ServerInstance(id=server_name, name=server_name, path=server_path, config=config)
                instance.attach_process(process)
                instance.attach_output_buffer(self.OUTPUT_QUEUE_MAX_SIZE)
                self.running_servers[server_name] = instance

                def _drain_output() -> None:
                    try:
                        instance.append_output_text(self._decode_process_output(process))
                    except Exception as e:
                        get_logger().bind(component="server_process_output").exception(f"{server_name} 讀取錯誤: {e}")

                def _on_finished(exit_code: int, _status: QtCore.QProcess.ExitStatus) -> None:
                    _drain_output()
                    instance.flush_output_pending()
                    with contextlib.suppress(Exception):
                        SystemUtils.unregister_managed_process(abs_server_path, pid)
                    logger.info(f"伺服器 {server_name} 已停止 (Exit code: {exit_code})")

                process.readyReadStandardOutput.connect(_drain_output)
                process.finished.connect(_on_finished)
                logger.info(f"伺服器 {server_name} 啟動成功，PID: {pid}")
                return self._success_result(f"伺服器 {server_name} 啟動成功，PID: {pid}", server_name=server_name)
            except FileNotFoundError as e:
                logger.exception(f"檔案路徑錯誤: {e}")
                return self._failure_result("啟動失敗", f"找不到啟動所需檔案: {e}", server_name=server_name)
        except Exception as e:
            try:
                server_path = Path(getattr(self.servers.get(server_name), "path", ""))
            except Exception:
                server_path = None
            cleaned = self._cleanup_failed_runtime_process(server_name, server_path, process)
            record_and_mark(e, marker_path=server_path, reason="啟動伺服器失敗", details={"server": server_name})
            cleanup_note = "已嘗試清理殘留進程。" if cleaned else "未偵測到可清理的殘留進程。"
            return self._failure_result(
                "啟動失敗",
                f"無法啟動伺服器 {server_name}。{cleanup_note}\n錯誤: {e}",
                server_name=server_name,
            )

    def start_server(self, server_name: str) -> bool:
        """啟動伺服器。

        Args:
            server_name: 目標伺服器名稱。

        Returns:
            啟動成功時回傳 True，否則回傳 False。
        """

        return self.start_server_result(server_name).success

    def delete_server_result(self, server_name: str) -> ServerOperationResult:
        """刪除伺服器。

        Args:
            server_name: 要刪除的伺服器名稱。

        Returns:
            刪除流程結果。
        """
        try:
            if server_name not in self.servers:
                return self._failure_result("刪除失敗", f"找不到伺服器: {server_name}", server_name=server_name)
            config = self.servers[server_name]
            server_path = Path(config.path).resolve(strict=False)
            if not PathUtils.is_path_within(self.servers_root, server_path, strict=False):
                logger.error(f"拒絕刪除不在 servers_root 之下的路徑: {server_path}")
                return self._failure_result(
                    "刪除失敗",
                    f"拒絕刪除不在伺服器根目錄下的路徑: {server_path}",
                    server_name=server_name,
                )
            removed_config = self.servers[server_name]
            del self.servers[server_name]
            if not self.write_servers_config():
                self.servers[server_name] = removed_config
                return self._failure_result(
                    "刪除失敗", f"無法保存刪除後的伺服器配置: {server_name}", server_name=server_name
                )
            if not PathUtils.delete_within(self.servers_root, server_path):
                self.servers[server_name] = removed_config
                if not self.write_servers_config():
                    logger.error(f"回滾刪除失敗時，無法恢復伺服器配置: {server_name}")
                return self._failure_result("刪除失敗", f"無法刪除伺服器資料夾: {server_path}", server_name=server_name)
            return self._success_result(f"伺服器 {server_name} 已刪除", server_name=server_name)
        except Exception as e:
            try:
                server_path = Path(getattr(self.servers.get(server_name), "path", ""))
            except Exception:
                server_path = None
            record_and_mark(e, marker_path=server_path, reason="刪除伺服器失敗", details={"server": server_name})
            return self._failure_result("刪除失敗", f"無法刪除伺服器 {server_name}。錯誤: {e}", server_name=server_name)

    def delete_server(self, server_name: str) -> bool:
        """刪除伺服器。

        Args:
            server_name: 要刪除的伺服器名稱。

        Returns:
            刪除成功時回傳 True，否則回傳 False。
        """

        return self.delete_server_result(server_name).success

    def load_servers_config(self) -> None:
        """載入伺服器配置"""
        with self._config_lock:
            try:
                data = PathUtils.load_json(self.config_file)
                if data is not None:
                    self.servers.clear()
                    for name, config_data in data.items():
                        self.servers[name] = ServerConfig(**config_data)
                else:
                    logger.warning("伺服器配置文件為空或無法解析")
            except Exception as e:
                with contextlib.suppress(Exception):
                    record_and_mark(e, marker_path=self.config_file, reason="load_servers_config_failed")

    def write_servers_config(self) -> bool:
        """實際執行保存伺服器配置到 servers_config.json。

        Returns:
            成功寫入時回傳 True，失敗時回傳 False。
        """
        with self._config_lock:
            try:
                data: dict[str, dict[str, Any]] = {}
                for name, config in self.servers.items():
                    if is_dataclass(config) and not isinstance(config, type):
                        data[name] = asdict(config)
                    elif isinstance(config, dict):
                        data[name] = config
                    else:
                        logger.error(f"保存伺服器配置失敗: 無法序列化類型 {type(config).__name__} ({name})")
                        return False
                logger.debug(f"寫入 servers_config.json: path={self.config_file}, server_count={len(data)}")
                if not atomic_write_json(self.config_file, data):
                    logger.error("保存伺服器配置失敗: 無法寫入文件")
                    return False
                logger.info("伺服器配置已保存到 servers_config.json")
                return True
            except Exception as e:
                with contextlib.suppress(Exception):
                    record_and_mark(e, marker_path=self.config_file, reason="write_servers_config_failed")
                logger.exception(f"保存伺服器配置失敗: {e}")
                return False

    def get_default_server_properties(self) -> dict[str, str]:
        """獲取預設伺服器屬性"""
        return {
            "accepts-transfers": "false",
            "allow-flight": "false",
            "broadcast-console-to-ops": "true",
            "broadcast-rcon-to-ops": "true",
            "bug-report-link": "",
            "difficulty": "easy",
            "enable-code-of-conduct": "false",
            "enable-jmx-monitoring": "false",
            "enable-query": "false",
            "enable-rcon": "false",
            "enable-status": "true",
            "enforce-secure-profile": "true",
            "enforce-whitelist": "false",
            "entity-broadcast-range-percentage": "100",
            "force-gamemode": "false",
            "function-permission-level": "2",
            "gamemode": "survival",
            "generate-structures": "true",
            "generator-settings": "{}",
            "hardcore": "false",
            "hide-online-players": "false",
            "initial-disabled-packs": "",
            "initial-enabled-packs": "vanilla",
            "level-name": "world",
            "level-seed": "",
            "level-type": "minecraft:normal",
            "log-ips": "true",
            "management-server-allowed-origins": "",
            "management-server-enabled": "false",
            "management-server-host": "localhost",
            "management-server-port": "0",
            "management-server-secret": "",
            "management-server-tls-enabled": "true",
            "management-server-tls-keystore": "",
            "management-server-tls-keystore-password": "",
            "max-chained-neighbor-updates": "1000000",
            "max-players": "20",
            "max-tick-time": "60000",
            "max-world-size": "29999984",
            "motd": "A Minecraft Server",
            "network-compression-threshold": "256",
            "online-mode": "true",
            "op-permission-level": "4",
            "pause-when-empty-seconds": "60",
            "player-idle-timeout": "0",
            "prevent-proxy-connections": "false",
            "query.port": "25565",
            "rate-limit": "0",
            "rcon.password": "",
            "rcon.port": "25575",
            "region-file-compression": "deflate",
            "require-resource-pack": "false",
            "resource-pack": "",
            "resource-pack-id": "",
            "resource-pack-prompt": "",
            "resource-pack-sha1": "",
            "server-ip": "",
            "server-port": "25565",
            "simulation-distance": "10",
            "spawn-protection": "16",
            "status-heartbeat-interval": "0",
            "sync-chunk-writes": "true",
            "text-filtering-config": "",
            "text-filtering-version": "0",
            "use-native-transport": "true",
            "view-distance": "10",
            "white-list": "false",
        }

    def server_exists(self, name: str) -> bool:
        """檢查伺服器是否已存在。

        Args:
            name: 伺服器名稱。

        Returns:
            若伺服器存在則回傳 True。
        """
        return name in self.servers

    @staticmethod
    def _collect_imported_startup_scripts(server_path: Path) -> list[Path]:
        server_root = server_path.resolve(strict=False)
        managed_name = ServerCommands.MANAGED_STARTUP_SCRIPT_NAME.lower()
        scripts: list[Path] = []
        seen: set[Path] = set()

        def append_script(script_path: Path) -> None:
            resolved_path = script_path.resolve(strict=False)
            if resolved_path in seen or resolved_path.parent != server_root or not script_path.is_file():
                return
            scripts.append(script_path)
            seen.add(resolved_path)

        for script_name in ServerCommands.STARTUP_SCRIPT_CANDIDATES:
            if script_name.lower() == managed_name:
                continue
            append_script(server_path / script_name)

        for script_path in sorted(server_path.glob("*.bat")):
            if script_path.name.lower() == managed_name:
                continue
            resolved_path = script_path.resolve(strict=False)
            if resolved_path in seen:
                continue
            startup_command = ServerCommands.extract_startup_script_command(script_path)
            if startup_command.has_java_command:
                append_script(script_path)
        return scripts

    @staticmethod
    def _extract_imported_startup_command(config: ServerConfig, script_path: Path) -> str | None:
        startup_command = ServerCommands.extract_startup_script_command(script_path)
        if not startup_command.has_java_command:
            return None
        if startup_command.memory_max_mb is not None:
            config.memory_max_mb = startup_command.memory_max_mb
        if startup_command.memory_min_mb is not None:
            config.memory_min_mb = startup_command.memory_min_mb
        return ServerCommands.replace_startup_command_java_path(startup_command.command_line, config)

    @staticmethod
    def _delete_root_startup_script(server_path: Path, script_path: Path) -> bool:
        server_root = server_path.resolve(strict=False)
        resolved_path = script_path.resolve(strict=False)
        if resolved_path.parent != server_root or not script_path.is_file():
            return False
        script_path.unlink()
        return True

    def _prepare_imported_startup_scripts(self, config: ServerConfig) -> None:
        """匯入伺服器時轉移原始腳本設定，並只留下程式管理的標準啟動腳本。"""
        server_path = Path(config.path)
        managed_script = server_path / ServerCommands.MANAGED_STARTUP_SCRIPT_NAME
        try:
            imported_scripts = self._collect_imported_startup_scripts(server_path)
            setting_sources = imported_scripts or ([managed_script] if managed_script.is_file() else [])
            java_command_override = None
            command_source = ""
            for script_path in setting_sources:
                java_command_override = self._extract_imported_startup_command(config, script_path)
                if java_command_override:
                    command_source = script_path.name
                    break
            if command_source:
                logger.info(f"已從匯入啟動腳本保留啟動命令: {command_source}")

            removed_scripts: list[str] = []
            for script_path in [*imported_scripts, managed_script]:
                if not script_path.exists():
                    continue
                try:
                    if self._delete_root_startup_script(server_path, script_path):
                        removed_scripts.append(script_path.name)
                except Exception as exc:
                    logger.warning(f"無法刪除匯入啟動腳本 {script_path.name}: {exc}")
            if removed_scripts:
                logger.info("已移除匯入啟動腳本: " + ", ".join(removed_scripts))

            if not self.create_launch_script(config, java_command_override=java_command_override):
                raise RuntimeError(f"匯入伺服器啟動腳本建立失敗: {config.name}")
            logger.info(f"匯入伺服器已建立/更新標準啟動腳本 start_server.bat: {config.name}")
        except Exception as exc:
            logger.warning(f"匯入伺服器啟動腳本整理失敗，保留原始檔案: {exc}")
            raise

    def add_server(self, config: ServerConfig) -> bool:
        """添加伺服器配置（用於匯入）。

        Args:
            config: 要加入的伺服器設定。

        Returns:
            成功寫入設定時回傳 True，失敗時回傳 False。
        """
        previous_config = self.servers.get(config.name)
        try:
            self._prepare_imported_startup_scripts(config)
            self.servers[config.name] = config
            if not self.write_servers_config():
                raise RuntimeError(f"保存伺服器配置失敗: {config.name}")
            return True
        except Exception as e:
            if previous_config is not None:
                self.servers[config.name] = previous_config
            else:
                self.servers.pop(config.name, None)
            logger.exception(f"添加伺服器失敗: {e}")
            return False

    def load_server_properties(self, server_name: str) -> dict[str, str]:
        """載入伺服器的 server.properties 檔案內容（附帶快取機制）。

        Args:
            server_name: 伺服器名稱。

        Returns:
            讀取到的屬性字典；找不到或失敗時回傳空字典。
        """
        try:
            if server_name not in self.servers:
                return {}
            config = self.servers[server_name]
            server_path = Path(config.path)
            properties_file = server_path / "server.properties"
            if not properties_file.exists():
                return {}
            try:
                mtime = properties_file.stat().st_mtime
            except OSError:
                return {}
            cached_mtime, cached_props = self._properties_cache.get(server_name, (0, None))
            if cached_props is not None and mtime == cached_mtime:
                return cached_props
            properties = ServerPropertiesHelper.load_properties(properties_file)
            self._properties_cache[server_name] = (mtime, properties)
            logger.debug(
                f"重新載入 server.properties: server={server_name}, path={properties_file}, property_count={len(properties)}"
            )
            existing_properties = dict(getattr(config, "properties", {}) or {})
            if existing_properties != properties:
                config.properties = dict(properties)
                if not self.write_servers_config():
                    logger.warning(f"同步 server.properties 到 servers_config.json 失敗: server={server_name}")
            return properties
        except Exception as e:
            logger.exception(f"讀取 server.properties 失敗: {e}")
            return {}

    def invalidate_server_properties_cache(self, server_name: str | None = None) -> None:
        """清除 server.properties 快取。

        傳入 server_name 時僅清除單一伺服器，否則清除全部。

        Args:
            server_name: 要清除快取的伺服器名稱；為 None 時清除全部。
        """
        if server_name is None:
            self._properties_cache.clear()
            return
        self._properties_cache.pop(server_name, None)

    def is_server_running(self, server_name: str) -> bool:
        """檢查伺服器是否正在運行"""
        return self._get_running_instance(server_name) is not None

    def stop_server(self, server_name: str) -> bool:
        """停止伺服器。

        Args:
            server_name: 目標伺服器名稱。

        Returns:
            成功停止或已處於停止狀態時回傳 True。
        """
        try:
            instance = self.running_servers.get(server_name)
            if instance is None:
                logger.info(f"伺服器 {server_name} 未在運行")
                return False
            process = instance.get_process()
            if process is None:
                logger.info(f"伺服器 {server_name} 已停止")
                return True
            try:
                is_running = self._process_is_running(process)
            except Exception:
                is_running = False
            if not is_running:
                logger.info(f"伺服器 {server_name} 已停止")
                return True
            try:
                self._write_process_command(process, "stop")
                if isinstance(process, QtCore.QProcess):
                    if not process.waitForFinished(5000):
                        process.terminate()
                else:
                    process.wait(timeout=5)
            except (SubprocessUtils.TimeoutExpired, OSError, BrokenPipeError) as _:
                try:
                    process.terminate()
                    if isinstance(process, QtCore.QProcess):
                        process.waitForFinished(5000)
                    else:
                        process.wait(timeout=5)
                except SubprocessUtils.TimeoutExpired:
                    SystemUtils.kill_process_tree(self._process_pid(process))
                    with contextlib.suppress(SubprocessUtils.TimeoutExpired):
                        if isinstance(process, QtCore.QProcess):
                            process.waitForFinished(1000)
                        else:
                            process.wait(timeout=1)
            if isinstance(process, QtCore.QProcess) and process.state() != QtCore.QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(1000)
            logger.info(f"伺服器 {server_name} 已停止")
            return True
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(e, reason="stop_server_failed", details={"server": server_name})
            logger.exception(f"停止伺服器失敗: {e}")
            return False
        finally:
            self._cleanup_running_server_state(server_name)

    def get_server_info(self, server_name: str) -> dict | None:
        """獲取伺服器資訊，包括運行狀態和資源使用，補齊 UI 需要的欄位。

        Args:
            server_name: 目標伺服器名稱。

        Returns:
            伺服器資訊字典；找不到伺服器時回傳 None。
        """
        try:
            if server_name not in self.servers:
                return None
            config = self.servers[server_name]
            info = {
                "name": server_name,
                "config": asdict(config),
                "is_running": self.is_server_running(server_name),
                "pid": None,
                "cpu_percent": 0.0,
                "memory_mb": 0.0,
                "memory": 0,
                "uptime": "00:00:00",
                "players": 0,
                "max_players": 0,
                "version": "N/A",
            }
            try:
                properties = self.load_server_properties(server_name)
                if properties:
                    max_players = properties.get("max-players") or properties.get("max_players")
                    if max_players:
                        try:
                            info["max_players"] = int(max_players)
                        except (ValueError, TypeError) as exc:
                            logger.debug(f"解析 max_players 失敗: {exc}")
                            info["max_players"] = 0
                    mc_version = getattr(config, "minecraft_version", None)
                    loader_type = getattr(config, "loader_type", None)
                    if mc_version and loader_type:
                        info["version"] = f"{mc_version}({loader_type})"
                    elif mc_version:
                        info["version"] = str(mc_version)
                    elif "version" in properties:
                        info["version"] = str(properties["version"])
            except Exception as e:
                logger.exception(f"讀取 server.properties 失敗: {e}")
            instance = self._get_running_instance(server_name)
            if instance is not None:
                process = instance.get_process()
                if process is None:
                    return info
                pid = self._process_pid(process)
                info["pid"] = pid
                if not pid or not SystemUtils.is_process_running(pid):
                    info["is_running"] = False
                    self._cleanup_running_server_state(server_name)
                    return info
                info["is_running"] = True
                java_pid = self._get_process_metadata(process, "_msm_java_pid")
                if not java_pid:
                    java_pid = SystemUtils.find_java_process(pid)
                    if java_pid:
                        self._set_process_metadata(process, "_msm_java_pid", java_pid)
                target_pid = java_pid if java_pid else pid
                if java_pid:
                    info["pid"] = java_pid
                mem_bytes = SystemUtils.get_process_memory_usage(target_pid)
                info["memory"] = mem_bytes / (1024 * 1024)
                info["memory_mb"] = info["memory"]
                try:
                    create_time = self._get_process_metadata(process, "_msm_create_time")
                    if create_time:
                        uptime_seconds = int(time.time() - create_time)
                        hours = uptime_seconds // 3600
                        minutes = uptime_seconds % 3600 // 60
                        seconds = uptime_seconds % 60
                        info["uptime"] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                except Exception as e:
                    logger.exception(f"計算伺服器運行時間失敗: {e}")
            return info
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(e, reason="get_server_info_failed", details={"server": server_name})
            logger.exception(f"獲取伺服器資訊失敗: {e}")
            return None

    def send_command(self, server_name: str, command: str) -> bool:
        """向運行中的伺服器發送命令。

        Args:
            server_name: 目標伺服器名稱。
            command: 要送出的控制台指令。

        Returns:
            成功送出時回傳 True，失敗時回傳 False。
        """
        try:
            instance = self._get_running_instance(server_name)
            if instance is None:
                logger.info(f"伺服器 {server_name} 未在運行")
                return False
            process = instance.get_process()
            if process is None:
                logger.info(f"伺服器 {server_name} 程式已結束")
                return False
            if self._write_process_command(process, command):
                logger.debug(f"已向伺服器 {server_name} 發送命令: {command}")
                return True
            logger.error(f"無法向伺服器 {server_name} 發送命令：stdin 不可用", "ServerManager")
            return False
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(e, reason="send_command_failed", details={"server": server_name, "command": command})
            logger.exception(f"發送命令失敗: {e}")
            return False

    def read_server_output(self, server_name: str, _timeout: float = 0.1) -> list[str]:
        """讀取伺服器輸出。

        Args:
            server_name: 目標伺服器名稱。
            _timeout: 保留的相容參數，現階段未使用。

        Returns:
            目前緩衝中的輸出行清單。
        """
        try:
            instance = self.running_servers.get(server_name)
            if instance is None:
                return []
            process = instance.get_process()
            if process is None:
                self._cleanup_running_server_state(server_name)
                return []
            if isinstance(process, QtCore.QProcess):
                with contextlib.suppress(Exception):
                    instance.append_output_text(self._decode_process_output(process))
            if not self._process_is_running(process):
                instance.flush_output_pending()
                lines = instance.consume_output_lines()
                self._cleanup_running_server_state(server_name)
                return lines
            return instance.consume_output_lines()
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(e, reason="read_server_output_failed", details={"server": server_name})
            logger.exception(f"讀取伺服器輸出失敗: {e}")
            return []

    def get_server_log_file(self, server_name: str) -> Path | None:
        """獲取伺服器日誌檔案路徑。

        Args:
            server_name: 目標伺服器名稱。

        Returns:
            找到的日誌檔案路徑；找不到時回傳 None。
        """
        try:
            if server_name not in self.servers:
                return None
            server_config = self.servers[server_name]
            server_path = Path(server_config.path)
            log_files = [
                server_path / "logs" / "latest.log",
                server_path / "server.log",
                server_path / "logs" / "server.log",
            ]
            for log_file in log_files:
                if log_file.exists():
                    return log_file
            return None
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(e, reason="get_server_log_file_failed", details={"server": server_name})
            logger.exception(f"獲取伺服器日誌檔案失敗: {e}")
            return None
