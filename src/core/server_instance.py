"""伺服器實例封裝。

封裝單一伺服器的基礎屬性與基本 process 管理，供逐步遷移用。
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..utils.subprocess_utils import SubprocessUtils, get_logger

if TYPE_CHECKING:
    # 僅在型別檢查時引入以避免執行時依賴循環
    from ..models import ServerConfig
else:
    ServerConfig = Any

logger = get_logger().bind(component="ServerInstance")


@dataclass
class ServerInstance:
    """代表單一伺服器的輕量實例封裝。

    屬性皆為公開以利逐步遷移；方法提供最小的 process 管理介面。
    """

    id: str
    name: str
    path: Path
    config: ServerConfig | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    process: Any | None = field(default=None, init=False, repr=False)
    _output_buffer: deque[str] | None = field(default=None, init=False, repr=False)
    _output_lock: threading.Lock | None = field(default=None, init=False, repr=False)

    def attach_process(self, process: Any) -> Any:
        """綁定新的執行中的 process。

        Args:
            process: 要綁定的執行中程序。

        Returns:
            成功綁定後回傳傳入的 process。
        """
        with self._lock:
            if self.process is not None:
                raise RuntimeError("伺服器已在執行中")
            self.process = process
            return process

    def clear_process(self) -> None:
        """清除目前的 process 參考。"""
        with self._lock:
            self.process = None

    def attach_output_buffer(self, max_size: int) -> None:
        """建立或重設伺服器輸出緩衝。

        Args:
            max_size: 緩衝區最大行數。
        """
        with self._lock:
            self._output_buffer = deque(maxlen=max_size)
            self._output_lock = threading.Lock()

    def clear_output_buffer(self) -> None:
        """清除伺服器輸出緩衝。"""
        with self._lock:
            self._output_buffer = None
            self._output_lock = None

    def append_output_line(self, line: str) -> None:
        """將一行伺服器輸出寫入緩衝。

        Args:
            line: 伺服器輸出內容。
        """
        with self._lock:
            output_buffer = self._output_buffer
            output_lock = self._output_lock
        if output_buffer is None or output_lock is None:
            return
        with output_lock:
            output_buffer.append(line.rstrip("\r\n"))

    def consume_output_lines(self) -> list[str]:
        """取出並清空目前的伺服器輸出緩衝。

        Returns:
            目前累積的輸出行清單。
        """
        with self._lock:
            output_buffer = self._output_buffer
            output_lock = self._output_lock
        if output_buffer is None or output_lock is None:
            return []
        with output_lock:
            lines = list(output_buffer)
            output_buffer.clear()
        return lines

    def get_process(self) -> Any | None:
        """取得目前的 process。

        Returns:
            目前綁定的程序物件，若尚未啟動則回傳 None。
        """
        with self._lock:
            return self.process

    def start(self, cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> Any:
        """啟動伺服器，回傳 subprocess.Popen 物件。

        注意：此方法為同步呼叫（會立即 return Popen），若需非同步監控請使用 BackgroundTask。

        Args:
            cmd: 要執行的命令列。
            cwd: 啟動時的工作目錄。
            env: 額外的環境變數。

        Returns:
            啟動後的 subprocess.Popen 物件。
        """
        with self._lock:
            if self.process is not None:
                raise RuntimeError("伺服器已在執行中")
            cwd = cwd or self.path
            proc = SubprocessUtils.popen_checked(
                cmd, cwd=str(cwd), env=env, stdout=SubprocessUtils.PIPE, stderr=SubprocessUtils.PIPE
            )
            return self.attach_process(proc)

    def stop(self, timeout: float = 5.0) -> bool:
        """嘗試優雅停止伺服器，若逾時則強制終止。

        Args:
            timeout: 等待程序優雅結束的秒數。

        Returns:
            成功處理停止流程時回傳 True。
        """
        with self._lock:
            if self.process is None:
                return True
            try:
                self.process.terminate()
                self.process.wait(timeout=timeout)
            except SubprocessUtils.TimeoutExpired:
                # 逾時，嘗試強制終止
                try:
                    self.process.kill()
                    self.process.wait(timeout=1)
                except (SubprocessUtils.TimeoutExpired, OSError):
                    logger.warning(
                        "強制終止超時伺服器進程失敗 (id=%s, name=%s).",
                        getattr(self, "id", None),
                        getattr(self, "name", None),
                        exc_info=True,
                    )
            except OSError:
                # I/O 相關錯誤（例如管線已關閉），嘗試強制終止以確保資源清理
                try:
                    self.process.kill()
                    self.process.wait(timeout=1)
                except (SubprocessUtils.TimeoutExpired, OSError):
                    logger.warning(
                        "強制終止伺服器進程失敗 (id=%s, name=%s).",
                        getattr(self, "id", None),
                        getattr(self, "name", None),
                        exc_info=True,
                    )
            finally:
                self.clear_process()
            return True

    def is_running(self) -> bool:
        """回傳是否有正在執行的 process。"""
        process = self.get_process()
        return process is not None and process.poll() is None

    def to_dict(self) -> dict[str, Any]:
        """序列化不含 process 的 instance 資料，用於儲存或 UI 顯示。

        Returns:
            可序列化的 instance 資料字典。
        """
        return {"id": self.id, "name": self.name, "path": str(self.path), "metadata": dict(self.metadata)}
