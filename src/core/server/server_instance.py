"""
伺服器實例封裝

單一伺服器執行期狀態的唯一 owner
"""

from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6 import QtCore

from src.models import ServerConfig
from src.utils import SubprocessUtils, SystemUtils, get_logger

logger = get_logger().bind(component="ServerInstance")


@dataclass
class ServerInstance:
    """代表單一伺服器的輕量實例封裝"""

    id: str
    name: str
    path: Path
    config: ServerConfig | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    process: Any | None = field(default=None, init=False, repr=False)
    _output_buffer: deque[str] | None = field(default=None, init=False, repr=False)
    _output_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _output_pending: str = field(default="", init=False, repr=False)

    @staticmethod
    def process_pid(process: Any) -> int:
        """
        取得 QProcess 或 subprocess 類物件的 PID

        Args:
            process: 要讀取 PID 的程序物件

        Returns:
            程序 PID；無法取得時回傳 0
        """
        if isinstance(process, QtCore.QProcess):
            stored_pid = process.property("_msm_pid")
            if stored_pid:
                return int(stored_pid)
            return int(process.processId())
        return int(getattr(process, "pid", 0) or 0)

    @staticmethod
    def process_is_running(process: Any) -> bool:
        """
        判斷 QProcess 或 subprocess 類物件是否仍在執行

        Args:
            process: 要檢查狀態的程序物件

        Returns:
            程序尚未結束時回傳 True
        """
        if isinstance(process, QtCore.QProcess):
            return process.state() != QtCore.QProcess.ProcessState.NotRunning
        return process.poll() is None

    @staticmethod
    def process_returncode(process: Any) -> int | None:
        """
        取得 QProcess 或 subprocess 類物件的結束代碼

        Args:
            process: 要讀取結束代碼的程序物件

        Returns:
            程序仍在執行時回傳 None；已結束時回傳 exit code
        """
        if isinstance(process, QtCore.QProcess):
            if ServerInstance.process_is_running(process):
                return None
            return int(process.exitCode())
        return process.poll()

    def attach_process(self, process: Any) -> Any:
        """
        綁定新的執行中的 process

        Args:
            process: 要綁定的執行中程序

        Returns:
            成功綁定後回傳傳入的 process
        """
        with self._lock:
            if self.process is not None:
                raise RuntimeError("伺服器已在執行中")
            self.process = process
            return process

    def clear_process(self) -> None:
        """清除目前的 process 參考"""
        with self._lock:
            self.process = None

    def is_running(self) -> bool:
        """
        目前是否綁定仍在執行的 process

        Returns:
            若伺服器正在執行中則回傳 True
        """
        with self._lock:
            process = self.process
        if process is None:
            return False
        try:
            return self.process_is_running(process)
        except Exception:
            return False

    def get_process(self) -> Any | None:
        """
        取得目前綁定的 process

        Returns:
            目前綁定的 process；若無則回傳 None
        """
        with self._lock:
            return self.process

    def release_runtime(self) -> None:
        """釋放執行期資源：process 參考與輸出緩衝（不負責 kill）"""
        self.clear_process()
        self.clear_output_buffer()

    def attach_output_buffer(self, max_size: int) -> None:
        """
        建立或重設伺服器輸出緩衝

        Args:
            max_size: 緩衝區最大行數
        """
        with self._output_lock:
            self._output_buffer = deque(maxlen=max_size)
            self._output_pending = ""

    def clear_output_buffer(self) -> None:
        """清除伺服器輸出緩衝"""
        with self._output_lock:
            self._output_buffer = None
            self._output_pending = ""

    def append_output_text(self, text: str) -> None:
        """
        將 QProcess stdout/stderr 文字片段拆成行並寫入緩衝

        Args:
            text: 來自 QProcess signal 的輸出文字片段
        """
        if not text:
            return
        with self._output_lock:
            if self._output_buffer is None:
                return
            combined = self._output_pending + text
            lines = combined.splitlines()
            if combined and not combined.endswith(("\n", "\r")):
                self._output_pending = lines.pop() if lines else combined
            else:
                self._output_pending = ""
            for line in lines:
                self._output_buffer.append(line.rstrip("\r\n"))

    def flush_output_pending(self) -> None:
        """把尚未換行的輸出片段送入緩衝"""
        with self._output_lock:
            if self._output_buffer is not None and self._output_pending:
                self._output_buffer.append(self._output_pending.rstrip("\r\n"))
                self._output_pending = ""

    def consume_output_lines(self) -> list[str]:
        """
        取出並清空目前的伺服器輸出緩衝

        Returns:
            目前累積的輸出行清單
        """
        with self._output_lock:
            if self._output_buffer is None:
                return []
            lines = list(self._output_buffer)
            self._output_buffer.clear()
            return lines

    def start(self, cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> Any:
        """
        啟動伺服器，回傳 QProcess 物件

        注意：此方法只負責啟動與綁定；輸出處理應由呼叫端接 QProcess signal

        Args:
            cmd: 要執行的命令列
            cwd: 啟動時的工作目錄
            env: 額外的環境變數

        Returns:
            啟動後的 QProcess 物件
        """
        with self._lock:
            if self.process is not None:
                raise RuntimeError("伺服器已在執行中")
            cwd = cwd or self.path
            proc = SubprocessUtils.create_qprocess_checked(cmd, cwd=str(cwd))
            if env:
                process_env = QtCore.QProcessEnvironment.systemEnvironment()
                for key, value in env.items():
                    process_env.insert(str(key), str(value))
                proc.setProcessEnvironment(process_env)
            proc.start()
            if not proc.waitForStarted(10000):
                raise RuntimeError(proc.errorString() or "QProcess 啟動失敗")
            pid = int(proc.processId())
            proc.setProperty("_msm_pid", pid)
            proc.setProperty("_msm_create_time", time.time())
            SystemUtils.register_managed_process(cwd, pid)
            return self.attach_process(proc)

    def stop(self, timeout: float = 5.0) -> bool:
        """
        嘗試優雅停止伺服器，若逾時則強制終止

        Args:
            timeout: 等待程序優雅結束的秒數

        Returns:
            成功處理停止流程時回傳 True
        """
        with self._lock:
            if self.process is None:
                return True
            process = self.process
            try:
                if isinstance(process, QtCore.QProcess):
                    if process.state() != QtCore.QProcess.ProcessState.NotRunning:
                        process.write(b"stop\n")
                        process.waitForBytesWritten(1000)
                        if not process.waitForFinished(max(1, int(timeout * 1000))):
                            process.terminate()
                        if process.state() != QtCore.QProcess.ProcessState.NotRunning and not process.waitForFinished(
                            1000
                        ):
                            process.kill()
                            process.waitForFinished(1000)
                else:
                    process.terminate()
                    process.wait(timeout=timeout)
            except SubprocessUtils.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=1)
                except (SubprocessUtils.TimeoutExpired, OSError) as e:
                    logger.warning(
                        "強制終止逾時伺服器行程失敗 (id=%s, name=%s): %s",
                        getattr(self, "id", None),
                        getattr(self, "name", None),
                        e,
                        exc_info=True,
                    )
            except OSError:
                try:
                    process.kill()
                    process.wait(timeout=1)
                except (SubprocessUtils.TimeoutExpired, OSError) as e:
                    logger.warning(
                        "強制終止伺服器行程失敗 (id=%s, name=%s): %s",
                        getattr(self, "id", None),
                        getattr(self, "name", None),
                        e,
                        exc_info=True,
                    )
            finally:
                with suppress(Exception):
                    SystemUtils.unregister_managed_process(self.path, self.process_pid(process))
                self.clear_process()
            return True


__all__ = ["ServerInstance"]
