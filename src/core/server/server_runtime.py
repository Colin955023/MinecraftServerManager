"""Minecraft 伺服器行程生命週期的唯一 owner"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from PySide6 import QtCore

from src.core import ServerInspector
from src.models import (
    ServerConfig,
    ServerInspection,
    ServerInspectionIntent,
    ServerOperationResult,
    ServerRuntimeEvent,
    ServerRuntimeEventKind,
    ServerRuntimeSnapshot,
    ServerRuntimeState,
)
from src.utils import (
    ServerCommands,
    SubprocessUtils,
    SystemUtils,
    bytes_to_mb,
    get_logger,
    is_path_within,
)

logger = get_logger().bind(component="ServerRuntime")

type RuntimeIntent = Literal["run", "initialize"]
type ProcessFactory = Callable[[list[str], str], Any]


@dataclass(slots=True)
class _RuntimeRecord:
    """Runtime 內部唯一可變狀態；不得透過公開介面洩漏"""

    name: str
    path: Path
    config: ServerConfig
    intent: RuntimeIntent
    process: Any
    pid: int
    created_at: float
    state: ServerRuntimeState = "starting"
    sequence: int = 0
    events: deque[ServerRuntimeEvent] = field(default_factory=lambda: deque(maxlen=2000))
    pending_output: str = ""
    java_pid: int | None = None


class ServerRuntime:
    """統一啟動、觀察、命令、停止與關閉 Minecraft 伺服器"""

    STARTUP_CHECK_DELAY = 0.1

    def __init__(
        self,
        server_crud: Any,
        *,
        process_factory: ProcessFactory | None = None,
        server_inspector: ServerInspector | None = None,
    ):
        self.server_crud = server_crud
        self.server_inspector = server_inspector or ServerInspector()
        self._process_factory = process_factory or self._create_qprocess
        self._records: dict[str, _RuntimeRecord] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _create_qprocess(command: list[str], cwd: str) -> QtCore.QProcess:
        return SubprocessUtils.create_qprocess_checked(command, cwd=cwd)

    @staticmethod
    def _startup_script_command(script_path: Path) -> list[str]:
        if os.name == "nt" and script_path.suffix.lower() in {".bat", ".cmd"}:
            return ["cmd.exe", "/d", "/c", script_path.name]
        return [str(script_path)]

    @staticmethod
    def _process_is_running(process: Any) -> bool:
        if process is None:
            return False
        if isinstance(process, QtCore.QProcess):
            return process.state() != QtCore.QProcess.ProcessState.NotRunning
        return process.poll() is None

    @staticmethod
    def _process_pid(process: Any) -> int:
        if process is None:
            return 0
        if isinstance(process, QtCore.QProcess):
            return int(process.processId())
        return int(process.pid)

    @staticmethod
    def _process_returncode(process: Any) -> int | None:
        if process is None:
            return None
        if isinstance(process, QtCore.QProcess):
            if process.state() != QtCore.QProcess.ProcessState.NotRunning:
                return None
            return int(process.exitCode())
        return process.poll()

    @staticmethod
    def _decode_output(process: Any) -> str:
        if isinstance(process, QtCore.QProcess):
            data = process.readAllStandardOutput()
            return bytes(cast(Any, data)).decode("utf-8", errors="replace")
        stream = getattr(process, "stdout", None)
        if stream is None:
            return ""
        data = stream.read()
        return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data or "")

    @staticmethod
    def _write_command(process: Any, command: str) -> bool:
        payload = f"{command}\n"
        if isinstance(process, QtCore.QProcess):
            if process.state() == QtCore.QProcess.ProcessState.NotRunning:
                return False
            process.write(payload.encode("utf-8"))
            return bool(process.waitForBytesWritten(1000))
        stdin = getattr(process, "stdin", None)
        if stdin is None:
            return False
        stdin.write(payload)
        stdin.flush()
        return True

    @classmethod
    def _wait_for_exit(cls, process: Any, timeout_seconds: float) -> bool:
        if isinstance(process, QtCore.QProcess):
            if timeout_seconds <= 0:
                return not cls._process_is_running(process)
            return process.waitForFinished(max(1, int(timeout_seconds * 1000)))
        if timeout_seconds <= 0:
            return not cls._process_is_running(process)
        try:
            process.wait(timeout=timeout_seconds)
            return True
        except SubprocessUtils.TimeoutExpired:
            return False

    def start(self, server_name: str, intent: RuntimeIntent = "run") -> ServerOperationResult:
        """
        啟動伺服器；一般執行與首次初始化共用同一生命週期

        Args:
            server_name: 伺服器名稱
            intent: 啟動意圖，"run" 為一般執行，"initialize" 為首次初始化，初始化完成後會自動停止伺服器

        Returns:
            啟動結果，包含成功與否、訊息、伺服器名稱
        """
        if intent not in {"run", "initialize"}:
            return ServerOperationResult(
                success=False, title="啟動失敗", message=f"不支援的啟動意圖: {intent}", server_name=server_name
            )
        if server_name not in self.server_crud.servers:
            return ServerOperationResult(
                success=False, title="伺服器未找到", message=f"找不到伺服器: {server_name}", server_name=server_name
            )
        config = self.server_crud.servers[server_name]
        server_path, validation = self._validate_server_runtime_path(config)
        if validation is not None:
            return validation
        if server_path is None:
            return ServerOperationResult(
                success=False, title="啟動失敗", message=f"無法解析伺服器路徑: {server_name}", server_name=server_name
            )

        with self._lock:
            existing = self._records.get(server_name)
            if existing is not None and (self._record_is_running(existing) or existing.state == "starting"):
                return ServerOperationResult(
                    success=False,
                    title="伺服器已在執行",
                    message=f"伺服器 {server_name} 已在執行或啟動中",
                    server_name=server_name,
                )
            self._records[server_name] = _RuntimeRecord(
                name=server_name,
                path=server_path,
                config=config,
                intent=intent,
                process=None,
                pid=0,
                created_at=time.time(),
                state="starting",
            )

        process: Any | None = None
        try:
            inspection = self._inspect_server(config, server_path)
            if not inspection.launchable:
                self._cleanup_failed_process(server_name, server_path, None)
                missing = ", ".join(inspection.missing_files) or inspection.error or "可執行的啟動目標"
                return ServerOperationResult(
                    success=False,
                    title="啟動命令未找到",
                    message=f"伺服器尚不可啟動：{missing}",
                    server_name=server_name,
                )
            command, prepared = self._build_command(config, server_path, inspection)
            if not command:
                self._cleanup_failed_process(server_name, server_path, None)
                return ServerOperationResult(
                    success=False,
                    title="啟動命令未找到",
                    message="找不到或無法建立伺服器啟動命令",
                    server_name=server_name,
                )
            current = self._inspect_server(config, server_path)
            if current.revision != prepared.revision:
                self._cleanup_failed_process(server_name, server_path, None)
                return ServerOperationResult(
                    success=False, title="伺服器內容已變更", message="啟動前內容已變更，請重試", server_name=server_name
                )
            process = self._process_factory(command, str(server_path.resolve()))
            process.start()
            if hasattr(process, "waitForStarted") and not process.waitForStarted(3000):
                self._cleanup_failed_process(server_name, server_path, process)
                return ServerOperationResult(
                    success=False,
                    title="啟動失敗",
                    message=f"伺服器行程無法啟動：{process.errorString()}",
                    server_name=server_name,
                )
            pid = self._process_pid(process)
            record = _RuntimeRecord(
                name=server_name,
                path=server_path,
                config=config,
                intent=intent,
                process=process,
                pid=pid,
                created_at=time.time(),
                state="running",
            )
            with self._lock:
                self._records[server_name] = record
                self._emit(record, "started", f"PID: {pid}")
            SystemUtils.register_managed_process(server_path, pid)
            self._connect_process(record)
            if self._wait_for_exit(process, self.STARTUP_CHECK_DELAY):
                self._drain_output(record)
                self._finish_record(record, self._process_returncode(process) or 0)
                return ServerOperationResult(
                    success=False,
                    title="啟動失敗",
                    message=f"伺服器行程立即結束，結束代碼: {self._process_returncode(process)}\n請檢查日誌了解詳細資訊",
                    server_name=server_name,
                )
            logger.info(f"伺服器 {server_name} 啟動成功，PID: {pid}, intent={intent}")
            return ServerOperationResult(
                success=True, message=f"伺服器 {server_name} 啟動成功，PID: {pid}", server_name=server_name
            )
        except FileNotFoundError as exc:
            logger.exception(f"檔案路徑錯誤: {exc}")
            return ServerOperationResult(
                success=False, title="啟動失敗", message=f"找不到啟動所需檔案: {exc}", server_name=server_name
            )
        except Exception as exc:
            self._cleanup_failed_process(server_name, server_path, process)
            logger.exception(f"啟動伺服器 {server_name} 失敗: {exc}")
            return ServerOperationResult(
                success=False,
                title="啟動失敗",
                message=f"無法啟動伺服器 {server_name}\n錯誤: {exc}",
                server_name=server_name,
            )

    def observe(self, server_name: str, *, after_sequence: int = 0) -> ServerRuntimeSnapshot:
        """
        取得不可變狀態與指定序號之後的事件，不暴露 process 或內部 registry

        Args:
            server_name: 伺服器名稱
            after_sequence: 事件序號，僅回傳大於此序號的
        Returns:
            伺服器狀態快照，包含狀態、PID、記憶體使用量、運行時間、事件序號與事件
        """
        with self._lock:
            record = self._records.get(server_name)
            if record is None:
                return ServerRuntimeSnapshot(server_name=server_name)
            if (
                record.process is not None
                and not self._record_is_running(record)
                and record.state
                not in {
                    "stopped",
                    "failed",
                }
            ):
                self._finish_record(record, self._process_returncode(record.process) or 0)
            events = tuple(event for event in record.events if event.sequence > after_sequence)
            pid = record.java_pid or record.pid or None
            memory_mb = 0.0
            if record.state in {"starting", "running", "ready", "stopping"} and pid:
                if record.java_pid is None:
                    record.java_pid = SystemUtils.find_java_process(record.pid) or None
                    pid = record.java_pid or record.pid
                memory_mb = float(bytes_to_mb(SystemUtils.get_process_memory_usage(pid)))
            uptime = "00:00:00"
            if record.state in {"starting", "running", "ready", "stopping"}:
                uptime = self._format_uptime(record.created_at)
            return ServerRuntimeSnapshot(
                server_name=server_name,
                state=record.state,
                pid=pid,
                memory_mb=memory_mb,
                uptime=uptime,
                sequence=record.sequence,
                events=events,
            )

    def send_command(self, server_name: str, command: str) -> bool:
        """
        向執行中伺服器發送控制台命令

        Args:
            server_name: 伺服器名稱
            command: 控制台命令字串

        Returns:
            成功送出命令回傳 True，失敗回傳 False
        """
        with self._lock:
            record = self._records.get(server_name)
            if record is None or not self._record_is_running(record):
                return False
            return self._write_command(record.process, command)

    def stop(self, server_name: str) -> bool:
        """
        先送出 stop，再依序 terminate/kill，最後清除 OS 管理登錄

        Args:
            server_name: 伺服器名稱

        Returns:
            成功停止伺服器回傳 True，失敗回傳 False
        """
        with self._lock:
            record = self._records.get(server_name)
        if record is None:
            return False
        if not self._record_is_running(record):
            self._finish_record(record, self._process_returncode(record.process) or 0)
            return True
        record.state = "stopping"
        self._emit(record, "stopping", "已送出停止要求")
        try:
            self._write_command(record.process, "stop")
            if self._wait_for_exit(record.process, 5):
                return True
            record.process.terminate()
            if self._wait_for_exit(record.process, 5):
                return True
            pid = self._process_pid(record.process) or record.pid
            if pid:
                SystemUtils.kill_process_tree(pid)
            if isinstance(record.process, QtCore.QProcess):
                record.process.kill()
                record.process.waitForFinished(1000)
            elif hasattr(record.process, "kill"):
                record.process.kill()
            return not self._record_is_running(record)
        except (OSError, BrokenPipeError, SubprocessUtils.TimeoutExpired) as exc:
            logger.warning(f"停止伺服器 {server_name} 時改用強制終止: {exc}")
            SystemUtils.kill_process_tree(record.pid)
            return not self._record_is_running(record)
        finally:
            if not self._record_is_running(record):
                self._finish_record(record, self._process_returncode(record.process) or 0)

    def shutdown(self) -> None:
        """停止所有仍受管理的行程並清空 runtime 狀態"""
        with self._lock:
            names = tuple(self._records)
        for server_name in names:
            with suppress(Exception):
                self.stop(server_name)
        with self._lock:
            self._records.clear()

    def _connect_process(self, record: _RuntimeRecord) -> None:
        process = record.process
        ready_signal = getattr(process, "readyReadStandardOutput", None)
        finished_signal = getattr(process, "finished", None)
        error_signal = getattr(process, "errorOccurred", None)
        if ready_signal is not None:
            ready_signal.connect(lambda: self._drain_output(record))
        if finished_signal is not None:
            finished_signal.connect(lambda exit_code, _status=None: self._finish_record(record, int(exit_code)))
        if error_signal is not None:
            error_signal.connect(lambda _error: self._mark_failed(record, process.errorString()))

    def _drain_output(self, record: _RuntimeRecord) -> None:
        text = self._decode_output(record.process)
        if not text:
            return
        with self._lock:
            record.pending_output += text
            lines = record.pending_output.splitlines()
            if record.pending_output.endswith(("\n", "\r")):
                record.pending_output = ""
            else:
                record.pending_output = lines.pop() if lines else record.pending_output
            for line in lines:
                self._emit(record, "output", line)
                if "Done (" in line and 'For help, type "help"' in line and record.state != "ready":
                    record.state = "ready"
                    self._emit(record, "ready", "伺服器已完成啟動")
                    if record.intent == "initialize" and self._write_command(record.process, "stop"):
                        record.state = "stopping"
                        self._emit(record, "stopping", "初始化完成，正在關閉伺服器")

    def _finish_record(self, record: _RuntimeRecord, exit_code: int) -> None:
        with self._lock:
            if record.state in {"stopped", "failed"}:
                return
            self._drain_output(record)
            if record.pending_output:
                self._emit(record, "output", record.pending_output)
                record.pending_output = ""
            expected = record.state == "stopping"
            record.state = "stopped" if expected or exit_code == 0 else "failed"
            kind: ServerRuntimeEventKind = "stopped" if record.state == "stopped" else "failed"
            self._emit(record, kind, f"Exit code: {exit_code}")
            process = record.process
            record.process = None
        with suppress(Exception):
            SystemUtils.unregister_managed_process(record.path, record.pid)
        if process is not None:
            with suppress(Exception):
                process.deleteLater()

    def _mark_failed(self, record: _RuntimeRecord, message: str) -> None:
        with self._lock:
            if record.state not in {"stopped", "failed"}:
                record.state = "failed"
                self._emit(record, "failed", message)

    def _emit(self, record: _RuntimeRecord, kind: ServerRuntimeEventKind, message: str) -> None:
        record.sequence += 1
        record.events.append(ServerRuntimeEvent(sequence=record.sequence, kind=kind, message=message))

    def _record_is_running(self, record: _RuntimeRecord) -> bool:
        return record.process is not None and self._process_is_running(record.process)

    @staticmethod
    def _format_uptime(created_at: float) -> str:
        seconds = max(0, int(time.time() - created_at))
        return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"

    def _inspect_server(self, config: ServerConfig, server_path: Path) -> ServerInspection:
        return self.server_inspector.inspect(
            server_path,
            ServerInspectionIntent(
                purpose="launch",
                expected_loader_type=config.loader_type,
                expected_minecraft_version=config.minecraft_version,
                expected_loader_version=config.loader_version,
            ),
        )

    def _build_command(
        self,
        config: ServerConfig,
        server_path: Path,
        inspection: ServerInspection,
    ) -> tuple[list[str] | None, ServerInspection]:
        if (
            str(config.loader_type or "").lower() in ("forge", "neoforge")
            and (server_path / "user_jvm_args.txt").exists()
        ):
            ServerCommands.update_forge_user_jvm_args(server_path, config)
        if inspection.launch_target.kind == "script":
            ServerCommands.repair_startup_script_java_command(
                server_path / inspection.launch_target.value,
                config,
            )
        else:
            if not self.server_crud.create_launch_script(
                config,
                launch_target=inspection.launch_target.value,
            ):
                logger.error(f"建立啟動腳本失敗: {server_path}")
                return None, inspection
        refreshed = self._inspect_server(config, server_path)
        if refreshed.launch_target.kind != "script":
            return None, refreshed
        script_path = server_path / refreshed.launch_target.value
        return self._startup_script_command(script_path.resolve()), refreshed

    def _validate_server_runtime_path(self, config: ServerConfig) -> tuple[Path | None, ServerOperationResult | None]:
        try:
            server_path = Path(config.path).resolve(strict=False)
        except Exception as exc:
            return None, ServerOperationResult(
                success=False, title="伺服器路徑無效", message=f"伺服器路徑無效: {exc}", server_name=config.name
            )
        if not is_path_within(self.server_crud.servers_root, server_path, strict=False):
            return None, ServerOperationResult(
                success=False,
                title="伺服器路徑無效",
                message=f"伺服器路徑必須位於伺服器資料夾內: {server_path}",
                server_name=config.name,
            )
        if not server_path.exists():
            return None, ServerOperationResult(
                success=False,
                title="伺服器路徑不存在",
                message=f"伺服器路徑不存在: {server_path}",
                server_name=config.name,
            )
        if not server_path.is_dir():
            return None, ServerOperationResult(
                success=False,
                title="伺服器路徑無效",
                message=f"伺服器路徑不是資料夾: {server_path}",
                server_name=config.name,
            )
        return server_path, None

    def _cleanup_failed_process(self, server_name: str, server_path: Path, process: Any | None) -> None:
        if process is not None:
            with suppress(Exception):
                pid = self._process_pid(process)
                if self._process_is_running(process):
                    process.kill()
                    SystemUtils.kill_process_tree(pid)
                SystemUtils.unregister_managed_process(server_path, pid)
        with suppress(Exception):
            SystemUtils.kill_java_processes_in_path(server_path)
        with self._lock:
            self._records.pop(server_name, None)


__all__ = ["ServerRuntime"]
