"""Minecraft 伺服器行程生命週期的唯一 owner"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.models import (
    ServerConfig,
    ServerInspection,
    ServerInspectionIntent,
    ServerOperationResult,
)
from src.utils import (
    ServerCommands,
    SystemUtils,
    bytes_to_mb,
    get_logger,
    is_path_within,
    is_reparse_point,
)

from .process_adapters import ProcessPort, SubprocessProcessAdapter
from .server_inspector import ServerInspector
from .server_output_history import ServerOutputHistory, read_server_output_history

logger = get_logger().bind(component="ServerRuntime")

type RuntimeIntent = Literal["run", "initialize"]
_RUNTIME_OUTPUT_READ_MAX_BYTES = 1024 * 1024
_RUNTIME_PENDING_OUTPUT_MAX_CHARS = 1024 * 1024
_RUNTIME_EVENT_LINE_MAX_CHARS = 64 * 1024
_RUNTIME_HISTORY_MAX_CHARS = 2 * 1024 * 1024

ServerRuntimeState = Literal["starting", "running", "ready", "stopping", "stopped", "failed"]
ServerRuntimeEventKind = Literal["started", "output", "ready", "stopping", "stopped", "failed"]


@dataclass(frozen=True, slots=True)
class ServerRuntimeEvent:
    """伺服器 runtime 對外發布的不可變事件"""

    sequence: int
    kind: ServerRuntimeEventKind
    message: str = ""


@dataclass(frozen=True, slots=True)
class ServerRuntimeSnapshot:
    """單一伺服器在查詢時刻的不可變 runtime 快照"""

    server_name: str
    state: ServerRuntimeState = "stopped"
    pid: int | None = None
    memory_mb: float = 0.0
    uptime: str = "00:00:00"
    sequence: int = 0
    events: tuple[ServerRuntimeEvent, ...] = ()

    @property
    def is_running(self) -> bool:
        return self.state in {"starting", "running", "ready", "stopping"}

    @property
    def output_lines(self) -> tuple[str, ...]:
        return tuple(event.message for event in self.events if event.kind == "output")


@dataclass(slots=True)
class _RuntimeRecord:
    """Runtime 內部唯一可變狀態；不得透過公開介面洩漏"""

    name: str
    path: Path
    config: ServerConfig
    intent: RuntimeIntent
    process_port: ProcessPort | None
    pid: int
    created_at: float
    state: ServerRuntimeState = "starting"
    sequence: int = 0
    events: deque[ServerRuntimeEvent] = field(default_factory=lambda: deque(maxlen=2000))
    event_chars: int = 0
    memory_mb: float = 0.0
    sampled_at: float = 0.0
    pending_output: str = ""
    java_pid: int | None = None
    managed_process: Any | None = None


class ServerRuntime:
    """統一啟動、觀察、命令、停止與關閉 Minecraft 伺服器"""

    STARTUP_CHECK_DELAY = 0.1

    def __init__(
        self,
        server_crud: Any,
        *,
        process_factory: Callable[[list[str], str], ProcessPort] | None = None,
        server_inspector: ServerInspector | None = None,
    ):
        self.server_crud = server_crud
        self.server_inspector = server_inspector or ServerInspector()
        self._process_port_factory = process_factory or SubprocessProcessAdapter
        self._records: dict[str, _RuntimeRecord] = {}
        self._maintenance_servers: set[str] = set()
        self._lock = threading.RLock()
        self._closing = False
        self._shutdown_stages: dict[str, tuple[int, float]] = {}

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
        config = self.server_crud.snapshot().get(server_name)
        if config is None:
            return ServerOperationResult(
                success=False, title="伺服器未找到", message=f"找不到伺服器: {server_name}", server_name=server_name
            )
        server_path, validation = self._validate_server_runtime_path(config)
        if validation is not None:
            return validation
        if server_path is None:
            return ServerOperationResult(
                success=False, title="啟動失敗", message=f"無法解析伺服器路徑: {server_name}", server_name=server_name
            )

        with self._lock:
            if self._closing:
                return ServerOperationResult(
                    success=False, title="程式正在關閉", message="已停止接受啟動要求", server_name=server_name
                )
            if server_name in self._maintenance_servers:
                return ServerOperationResult(
                    success=False,
                    title="伺服器正在維護",
                    message=f"伺服器 {server_name} 正在進行備份、還原或其他維護操作，請稍後再試",
                    server_name=server_name,
                )
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
                process_port=None,
                pid=0,
                created_at=time.time(),
                state="starting",
            )

        process: ProcessPort | None = None
        managed_process: Any | None = None
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
            command = self._build_command(config, server_path, inspection)
            if not command:
                self._cleanup_failed_process(server_name, server_path, None)
                return ServerOperationResult(
                    success=False,
                    title="啟動命令未找到",
                    message="找不到或無法建立伺服器啟動命令",
                    server_name=server_name,
                )
            if not self._validate_command_inputs(server_path, command):
                self._cleanup_failed_process(server_name, server_path, None)
                return ServerOperationResult(
                    success=False,
                    title="啟動輸入無效",
                    message="啟動命令引用的檔案不存在或不安全",
                    server_name=server_name,
                )
            process = self._process_port_factory(command, str(server_path.resolve()))
            process.start()
            if not process.is_running():
                self._cleanup_failed_process(server_name, server_path, process, managed_process)
                return ServerOperationResult(
                    success=False,
                    title="啟動失敗",
                    message="伺服器行程無法啟動",
                    server_name=server_name,
                )
            pid = process.pid
            record = _RuntimeRecord(
                name=server_name,
                path=server_path,
                config=config,
                intent=intent,
                process_port=process,
                pid=pid,
                created_at=time.time(),
                state="running",
            )
            with self._lock:
                self._records[server_name] = record
                self._emit(record, "started", f"PID: {pid}")
            record.managed_process = SystemUtils.register_managed_process(server_path, pid)
            managed_process = record.managed_process
            self._connect_process(record)
            if process.wait(self.STARTUP_CHECK_DELAY):
                self._drain_output(record)
                self._finish_record(record, process.returncode() or 0)
                return ServerOperationResult(
                    success=False,
                    title="啟動失敗",
                    message=f"伺服器行程立即結束，結束代碼: {process.returncode()}\n請檢查日誌了解詳細資訊",
                    server_name=server_name,
                )
            logger.info(f"伺服器 {server_name} 啟動成功，PID: {pid}, intent={intent}")
            return ServerOperationResult(
                success=True, message=f"伺服器 {server_name} 啟動成功，PID: {pid}", server_name=server_name
            )
        except FileNotFoundError as e:
            self._cleanup_failed_process(server_name, server_path, process, managed_process)
            logger.exception(f"檔案路徑錯誤: {e}")
            return ServerOperationResult(
                success=False, title="啟動失敗", message=f"找不到啟動所需檔案: {e}", server_name=server_name
            )
        except Exception as e:
            self._cleanup_failed_process(server_name, server_path, process, managed_process)
            logger.exception(f"啟動伺服器 {server_name} 失敗: {e}")
            return ServerOperationResult(
                success=False,
                title="啟動失敗",
                message=f"無法啟動伺服器 {server_name}\n錯誤: {e}",
                server_name=server_name,
            )

    def begin_maintenance(self, server_name: str) -> bool:
        """
        保留伺服器維護時段，防止維護期間啟動同一伺服器

        Args:
            server_name: 伺服器名稱

        Returns:
            成功保留維護時段回傳 True，若伺服器正在執行或已被保留維護時段則回傳 False
        """
        with self._lock:
            if server_name in self._maintenance_servers:
                return False
            record = self._records.get(server_name)
            if record is not None and record.state in {"starting", "running", "ready", "stopping"}:
                return False
            self._maintenance_servers.add(server_name)
            return True

    def end_maintenance(self, server_name: str) -> None:
        """
        結束先前取得的伺服器維護時段

        Args:
            server_name: 伺服器名稱
        """
        with self._lock:
            self._maintenance_servers.discard(server_name)

    def prepare_maintenance(self, server_name: str, server_path: Path) -> bool:
        """
        確認受管行程與輸出資源已完全釋放

        Args:
            server_name: 伺服器名稱
            server_path: 伺服器根目錄

        Returns:
            維護操作可安全開始時回傳 True
        """
        with self._lock:
            record = self._records.get(server_name)
            if record is not None and self._record_is_running(record):
                return False
            if record is not None and record.process_port is not None:
                self._finish_record(record, self._exit_code(record.process_port))
        SystemUtils.kill_java_processes_in_path(server_path)
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            with self._lock:
                record = self._records.get(server_name)
                if record is None or (record.process_port is None and record.managed_process is None):
                    return True
            time.sleep(0.05)
        return False

    def observe(self, server_name: str, *, after_sequence: int | None = 0) -> ServerRuntimeSnapshot:
        """
        取得不可變狀態與指定序號之後的事件，不暴露 process 或內部 registry

        Args:
            server_name: 伺服器名稱
            after_sequence: 事件序號，僅回傳大於此序號的；None 表示只取得狀態
        Returns:
            伺服器狀態快照，包含狀態、PID、記憶體使用量、運作時間、事件序號與事件
        """
        with self._lock:
            record = self._records.get(server_name)
            if record is None:
                return ServerRuntimeSnapshot(server_name=server_name)
            if (
                record.process_port is not None
                and not self._record_is_running(record)
                and record.state
                not in {
                    "stopped",
                    "failed",
                }
            ):
                self._finish_record(record, self._exit_code(record.process_port))
            events = (
                ()
                if after_sequence is None
                else tuple(event for event in record.events if event.sequence > after_sequence)
            )
            pid = record.java_pid or record.pid or None
            memory_mb = 0.0
            if record.state in {"starting", "running", "ready", "stopping"} and pid:
                if record.java_pid is None:
                    record.java_pid = SystemUtils.find_java_process(record.pid) or None
                    pid = record.java_pid or record.pid
                now = time.monotonic()
                if not record.sampled_at or now - record.sampled_at >= 1.0:
                    record.memory_mb = float(bytes_to_mb(SystemUtils.get_process_memory_usage(pid)))
                    record.sampled_at = now
                memory_mb = record.memory_mb
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

    def read_output_history(
        self,
        server_name: str,
        *,
        max_lines: int = 2500,
        max_bytes: int = 2 * 1024 * 1024,
    ) -> ServerOutputHistory:
        """
        讀取受管理伺服器的歷史輸出尾端

        Args:
            server_name: 伺服器名稱
            max_lines: 最多回傳行數
            max_bytes: 最多讀取的尾端位元組數

        Returns:
            歷史輸出快照
        """
        with self._lock:
            record = self._records.get(server_name)
            if record is not None:
                output_lines = tuple(event.message for event in record.events if event.kind == "output")
                if output_lines:
                    return ServerOutputHistory(
                        lines=output_lines[-max(200, int(max_lines)) :],
                        truncated=len(output_lines) > max(200, int(max_lines)),
                        sequence=record.sequence,
                    )
                sequence = record.sequence
            else:
                sequence = 0
        config = self.server_crud.snapshot().get(server_name)
        log_file = self.server_crud.get_server_log_file(server_name)
        if config is None or log_file is None or not log_file.exists():
            return ServerOutputHistory()
        try:
            history = read_server_output_history(
                log_file,
                allowed_root=Path(config.path),
                max_lines=max_lines,
                max_bytes=max_bytes,
            )
            return ServerOutputHistory(lines=history.lines, truncated=history.truncated, sequence=sequence)
        except (OSError, ValueError) as e:
            logger.debug(f"讀取伺服器歷史輸出失敗: {e}")
            return ServerOutputHistory()

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
            return record.process_port is not None and record.process_port.write_line(command)

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
            self._finish_record(record, self._exit_code(record.process_port))
            return True
        record.state = "stopping"
        self._emit(record, "stopping", "已送出停止要求")
        try:
            process = record.process_port
            if process is None:
                return False
            process.write_line("stop")
            if process.wait(5):
                return True
            process.terminate()
            if process.wait(5):
                return True
            if record.managed_process is not None:
                SystemUtils.kill_process_tree(record.managed_process)
            SystemUtils.kill_java_processes_in_path(record.path)
            process.kill()
            process.wait(1)
            return not self._record_is_running(record)
        except OSError as e:
            logger.warning(f"停止伺服器 {server_name} 時改用強制終止: {e}")
            if record.managed_process is not None:
                SystemUtils.kill_process_tree(record.managed_process)
            SystemUtils.kill_java_processes_in_path(record.path)
            return not self._record_is_running(record)
        finally:
            if not self._record_is_running(record):
                self._finish_record(record, self._exit_code(record.process_port))

    def shutdown(self, *, wait: bool = True) -> bool:
        """
        停止所有受管程序；非阻塞模式由 UI 計時器持續推進至全部結束

        Args:
            wait: True 表示等待所有程序停止，False 表示立即返回

        Returns:
            所有程序都已停止回傳 True，否則回傳 False
        """
        with self._lock:
            self._closing = True
            records = tuple(self._records.values())
        if wait:
            for record in records:
                self.stop(record.name)
        else:
            now = time.monotonic()
            for record in records:
                process = record.process_port
                if process is None or not self._record_is_running(record):
                    continue
                phase, deadline = self._shutdown_stages.get(record.name, (0, 0.0))
                if now < deadline:
                    continue
                if phase == 0:
                    record.state = "stopping"
                    self._emit(record, "stopping", "程式關閉，正在停止伺服器")
                    process.write_line("stop")
                elif phase == 1:
                    process.terminate()
                else:
                    if record.managed_process is not None:
                        SystemUtils.kill_process_tree(record.managed_process, timeout=0.0)
                    process.kill()
                self._shutdown_stages[record.name] = (phase + 1, now + (5.0 if phase < 2 else 1.0))
        if any(self._record_is_running(record) for record in records):
            return False
        for record in records:
            self._finish_record(record, self._exit_code(record.process_port))
        with self._lock:
            self._records.clear()
            self._shutdown_stages.clear()
        return True

    def _connect_process(self, record: _RuntimeRecord) -> None:
        process = record.process_port
        if process is None:
            return
        process.connect(
            lambda: self._drain_output(record),
            lambda exit_code: self._finish_record(record, int(exit_code)),
            lambda message: self._mark_failed(record, message),
        )

    def _drain_output(self, record: _RuntimeRecord) -> None:
        if record.process_port is None:
            return
        text = record.process_port.read_output(_RUNTIME_OUTPUT_READ_MAX_BYTES)
        if not text:
            return
        with self._lock:
            record.pending_output += text
            if len(record.pending_output) > _RUNTIME_PENDING_OUTPUT_MAX_CHARS:
                record.pending_output = record.pending_output[-_RUNTIME_PENDING_OUTPUT_MAX_CHARS:]
                self._emit(record, "output", "[伺服器輸出過長，已截斷待處理內容]")
            lines = record.pending_output.splitlines()
            if record.pending_output.endswith(("\n", "\r")):
                record.pending_output = ""
            else:
                record.pending_output = lines.pop() if lines else record.pending_output
            for line in lines:
                if len(line) > _RUNTIME_EVENT_LINE_MAX_CHARS:
                    line = line[:_RUNTIME_EVENT_LINE_MAX_CHARS] + "…[已截斷]"
                self._emit(record, "output", line)
                if ("Done (" in line or "Done in " in line) and record.state != "ready":
                    record.state = "ready"
                    self._emit(record, "ready", "伺服器已完成啟動")
                    process = record.process_port
                    if record.intent == "initialize" and process is not None:
                        record.state = "stopping"
                        self._emit(record, "stopping", "初始化完成，正在關閉伺服器")
                        process.write_line("stop")

    def _finish_record(self, record: _RuntimeRecord, exit_code: int) -> None:
        with self._lock:
            if record.state in {"stopped", "failed"}:
                return
            self._drain_output(record)
            if record.pending_output:
                pending_output = record.pending_output[:_RUNTIME_EVENT_LINE_MAX_CHARS]
                if len(record.pending_output) > _RUNTIME_EVENT_LINE_MAX_CHARS:
                    pending_output += "…[已截斷]"
                self._emit(record, "output", pending_output)
                record.pending_output = ""
            expected = record.state == "stopping"
            record.state = "stopped" if expected or exit_code == 0 else "failed"
            kind: ServerRuntimeEventKind = "stopped" if record.state == "stopped" else "failed"
            self._emit(record, kind, f"Exit code: {exit_code}")
            process = record.process_port
            record.process_port = None
        with suppress(Exception):
            SystemUtils.unregister_managed_process(record.path, record.managed_process)
            record.managed_process = None
        if process is not None:
            with suppress(Exception):
                process.close()

    def _mark_failed(self, record: _RuntimeRecord, message: str) -> None:
        with self._lock:
            if record.state not in {"stopped", "failed"}:
                if self._record_is_running(record):
                    self._emit(record, "output", f"[輸出讀取錯誤] {message}")
                    return
                record.state = "failed"
                self._emit(record, "failed", message)

    def _emit(self, record: _RuntimeRecord, kind: ServerRuntimeEventKind, message: str) -> None:
        while record.events and (
            len(record.events) == record.events.maxlen or record.event_chars + len(message) > _RUNTIME_HISTORY_MAX_CHARS
        ):
            record.event_chars -= len(record.events.popleft().message)
        record.sequence += 1
        record.events.append(ServerRuntimeEvent(sequence=record.sequence, kind=kind, message=message))
        record.event_chars += len(message)

    def _record_is_running(self, record: _RuntimeRecord) -> bool:
        return record.process_port is not None and record.process_port.is_running()

    @staticmethod
    def _exit_code(process: ProcessPort | None) -> int:
        if process is None:
            return 0
        return int(process.returncode() or 0)

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
    ) -> list[str] | None:
        if inspection.launch_target.kind == "script":
            parsed = ServerCommands.parse_safe_java_command_line(inspection.launch_target.command)
            command = parsed[1] if parsed is not None else None
        else:
            if not self.server_crud.create_launch_script(
                config,
                launch_target=inspection.launch_target.value,
            ):
                logger.error(f"建立啟動腳本失敗: {server_path}")
                return None
            built = ServerCommands.build_java_command(
                config,
                return_list=True,
                launch_target=inspection.launch_target.value,
            )
            command = built if isinstance(built, list) else None
        if not command:
            logger.error("拒絕執行無法解析的伺服器 Java 命令")
            return None
        java_exe = ServerCommands.resolve_java_executable(config, fallback="")
        if not ServerCommands.is_full_java_path(java_exe):
            logger.error("找不到可信的完整 Java 執行檔，拒絕啟動伺服器")
            return None
        java_path = Path(java_exe)
        try:
            if is_reparse_point(java_path) or not java_path.is_file():
                raise OSError("Java 執行檔不是安全的一般檔案")
            java_exe = str(java_path.resolve(strict=True))
        except OSError as e:
            logger.error(f"拒絕執行不安全的 Java 執行檔: {e}")
            return None
        command[0] = java_exe
        return command

    @staticmethod
    def _validate_command_inputs(server_path: Path, command: list[str]) -> bool:
        """在啟動前驗證命令引用的 JAR 與參數檔"""
        relative_inputs: list[str] = []
        for index, argument in enumerate(command[1:], start=1):
            if argument.startswith("@") and len(argument) > 1:
                relative_inputs.append(argument[1:])
            elif index > 0 and command[index - 1] == "-jar":
                relative_inputs.append(argument)
        for value in relative_inputs:
            candidate = (server_path / value).resolve(strict=False)
            try:
                if (
                    not is_path_within(server_path, candidate, strict=False)
                    or is_reparse_point(candidate)
                    or not candidate.is_file()
                ):
                    return False
            except OSError:
                return False
        return True

    def _validate_server_runtime_path(self, config: ServerConfig) -> tuple[Path | None, ServerOperationResult | None]:
        try:
            raw_server_path = Path(config.path)
            if is_reparse_point(raw_server_path):
                raise ValueError("伺服器路徑不可為符號連結或 reparse point")
            server_path = raw_server_path.resolve(strict=False)
        except Exception as e:
            return None, ServerOperationResult(
                success=False, title="伺服器路徑無效", message=f"伺服器路徑無效: {e}", server_name=config.name
            )
        if not is_path_within(self.server_crud.servers_root, server_path, strict=False):
            return None, ServerOperationResult(
                success=False,
                title="伺服器路徑無效",
                message=f"伺服器路徑必須位於伺服器資料夾內: {server_path}",
                server_name=config.name,
            )
        servers_root = Path(self.server_crud.servers_root).resolve(strict=True)
        if server_path.parent != servers_root or server_path.name.casefold() != str(config.name).casefold():
            return None, ServerOperationResult(
                success=False,
                title="伺服器路徑無效",
                message="伺服器路徑必須是與名稱一致的 root 直接子目錄",
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

    def _cleanup_failed_process(
        self,
        server_name: str,
        server_path: Path,
        process: ProcessPort | None,
        managed_process: Any | None = None,
    ) -> None:
        if process is not None:
            with suppress(Exception):
                if process.is_running():
                    if managed_process is not None:
                        SystemUtils.kill_process_tree(managed_process)
                    else:
                        process.kill()
                SystemUtils.unregister_managed_process(server_path, managed_process)
        with suppress(Exception):
            SystemUtils.kill_java_processes_in_path(server_path)
        with self._lock:
            self._records.pop(server_name, None)


__all__ = ["ServerRuntime"]
