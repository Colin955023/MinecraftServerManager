"""
伺服器管理器

負責建立、管理與配置 Minecraft 伺服器
"""

import os
import time
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from PySide6 import QtCore

from ...models import ServerConfig, ServerOperationResult
from ...utils import (
    ExceptionUtils,
    PathUtils,
    ServerCommands,
    ServerDetectionUtils,
    SubprocessUtils,
    SystemUtils,
    bytes_to_mb,
    get_logger,
)
from .. import ServerCRUD, ServerInstance

logger = get_logger().bind(component="ServerManager")


class ServerStartup:
    """負責建立、管理和配置 Minecraft 伺服器"""

    STARTUP_CHECK_DELAY = 0.1
    STOP_CHECK_INTERVAL = 0.1
    STOP_TIMEOUT_SECONDS = 5
    OUTPUT_QUEUE_MAX_SIZE = 1000

    def __init__(self, server_crud):
        if isinstance(server_crud, (str, Path)):
            self.server_crud = ServerCRUD(str(server_crud))
        else:
            self.server_crud = server_crud
        self.running_servers = {}

    @staticmethod
    def _success_result(msg: str = "", *, server_name: str = "") -> ServerOperationResult:
        """建立成功結果"""
        return ServerOperationResult(success=True, message=msg, server_name=server_name)

    @staticmethod
    def _failure_result(err_title: str, err_msg: str, *, server_name: str = "") -> ServerOperationResult:
        """建立失敗結果"""
        return ServerOperationResult(success=False, title=err_title, message=err_msg, server_name=server_name)

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
        with suppress(Exception):
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
        """在指定期限內等待 process 結束"""
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

    def start_server_result(self, server_name: str) -> ServerOperationResult:
        """
        啟動伺服器

        Args:
            server_name: 目標伺服器名稱

        Returns:
            啟動流程結果
        """
        process = None
        try:
            if server_name not in self.server_crud.servers:
                return self._failure_result("伺服器未找到", f"找不到伺服器: {server_name}", server_name=server_name)
            config = self.server_crud.servers[server_name]
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
                    poll_result = ServerInstance.process_returncode(process)
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
                    with suppress(Exception):
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
                server_path = Path(getattr(self.server_crud.servers.get(server_name), "path", ""))
            except Exception:
                server_path = None
            cleaned = self._cleanup_failed_runtime_process(server_name, server_path, process)
            ExceptionUtils.record_and_mark(
                e, marker_path=server_path, reason="啟動伺服器失敗", details={"server": server_name}
            )
            cleanup_note = "已嘗試清理殘留進程" if cleaned else "未偵測到可清理的殘留進程"
            return self._failure_result(
                "啟動失敗",
                f"無法啟動伺服器 {server_name}{cleanup_note}\n錯誤: {e}",
                server_name=server_name,
            )

    def is_server_running(self, server_name: str) -> bool:
        """
        檢查伺服器是否正在運行

        Args:
            server_name: 伺服器名稱

        Returns:
            正在運行時回傳 True，否則回傳 False
        """
        return self._get_running_instance(server_name) is not None

    def stop_server(self, server_name: str) -> bool:
        """
        停止伺服器

        Args:
            server_name: 目標伺服器名稱

        Returns:
            成功停止或已處於停止狀態時回傳 True
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
                is_running = ServerInstance.process_is_running(process)
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
                    SystemUtils.kill_process_tree(ServerInstance.process_pid(process))
                    with suppress(SubprocessUtils.TimeoutExpired):
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
            with suppress(Exception):
                ExceptionUtils.record_and_mark(e, reason="stop_server_failed", details={"server": server_name})
            logger.exception(f"停止伺服器失敗: {e}")
            return False
        finally:
            self._cleanup_running_server_state(server_name)

    def get_server_info(self, server_name: str) -> dict | None:
        """
        獲取伺服器資訊，包括運行狀態和資源使用，補齊 UI 需要的欄位

        Args:
            server_name: 目標伺服器名稱

        Returns:
            伺服器資訊字典；找不到伺服器時回傳 None
        """
        try:
            if server_name not in self.server_crud.servers:
                return None
            config = self.server_crud.servers[server_name]
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
                properties = self.server_crud.load_server_properties(server_name)
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
                pid = ServerInstance.process_pid(process)
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
                info["memory"] = bytes_to_mb(mem_bytes)
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
            with suppress(Exception):
                ExceptionUtils.record_and_mark(e, reason="get_server_info_failed", details={"server": server_name})
            logger.exception(f"獲取伺服器資訊失敗: {e}")
            return None

    def send_command(self, server_name: str, command: str) -> bool:
        """
        向運行中的伺服器發送命令

        Args:
            server_name: 目標伺服器名稱
            command: 要送出的控制台指令

        Returns:
            成功送出時回傳 True，失敗時回傳 False
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
            logger.error(f"無法向伺服器 {server_name} 發送命令：stdin 不可用")
            return False
        except Exception as e:
            with suppress(Exception):
                ExceptionUtils.record_and_mark(
                    e, reason="send_command_failed", details={"server": server_name, "command": command}
                )
            logger.exception(f"發送命令失敗: {e}")
            return False

    def read_server_output(self, server_name: str) -> list[str]:
        """
        讀取伺服器輸出

        Args:
            server_name: 目標伺服器名稱

        Returns:
            目前緩衝中的輸出行清單
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
                with suppress(Exception):
                    instance.append_output_text(self._decode_process_output(process))
            if not ServerInstance.process_is_running(process):
                instance.flush_output_pending()
                lines = instance.consume_output_lines()
                self._cleanup_running_server_state(server_name)
                return lines
            return instance.consume_output_lines()
        except Exception as e:
            with suppress(Exception):
                ExceptionUtils.record_and_mark(e, reason="read_server_output_failed", details={"server": server_name})
            logger.exception(f"讀取伺服器輸出失敗: {e}")
            return []

    def get_server_log_file(self, server_name: str) -> Path | None:
        """
        獲取伺服器日誌檔案路徑

        Args:
            server_name: 目標伺服器名稱

        Returns:
            找到的日誌檔案路徑；找不到時回傳 None
        """
        try:
            if server_name not in self.server_crud.servers:
                return None
            server_config = self.server_crud.servers[server_name]
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
            with suppress(Exception):
                ExceptionUtils.record_and_mark(e, reason="get_server_log_file_failed", details={"server": server_name})
            logger.exception(f"獲取伺服器日誌檔案失敗: {e}")
            return None

    def _cleanup_running_server_state(self, server_name: str) -> None:
        """清除執行中伺服器的 runtime 狀態"""
        instance = self.running_servers.pop(server_name, None)
        if instance is not None:
            process = instance.get_process()
            if process is not None:
                SystemUtils.unregister_managed_process(instance.path, ServerInstance.process_pid(process))
            instance.clear_process()
            instance.clear_output_buffer()

    def _cleanup_failed_runtime_process(self, server_name: str, server_path: Path | None, process: Any | None) -> bool:
        """在建立/啟動流程異常時清理殘留進程"""
        cleaned = False
        if process is not None:
            try:
                pid = ServerInstance.process_pid(process)
                if ServerInstance.process_is_running(process):
                    with suppress(Exception):
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
        """取得仍在執行中的 instance；若已過期則自動清理"""
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

    def _validate_server_runtime_path(self, config: ServerConfig) -> tuple[Path | None, ServerOperationResult | None]:
        """在啟動前驗證伺服器路徑是否安全且可用"""
        try:
            server_path = Path(config.path).resolve(strict=False)
        except Exception as e:
            return (
                None,
                self._failure_result("伺服器路徑無效", f"伺服器路徑無效: {e}", server_name=getattr(config, "name", "")),
            )
        if not PathUtils.is_path_within(self.server_crud.servers_root, server_path, strict=False):
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

    def _resolve_startup_script_for_run(self, config: ServerConfig, server_path: Path) -> Path | None:
        """啟動前取得實際要執行的啟動腳本"""
        script_path = ServerDetectionUtils.find_startup_script(server_path)
        if script_path is not None:
            logger.debug(f"使用既有啟動腳本，啟動前確認 Java 路徑: {script_path}")
            ServerCommands.repair_startup_script_java_command(script_path, config)
            return script_path
        if not self.server_crud.create_launch_script(config):
            logger.error(f"建立啟動腳本失敗: {server_path}")
            return None
        return ServerDetectionUtils.find_startup_script(server_path)
