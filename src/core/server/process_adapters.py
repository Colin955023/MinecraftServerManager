"""伺服器子程序的最小生命週期介面"""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol

from src.utils import SubprocessUtils


class ProcessPort(Protocol):
    """ServerRuntime 使用的子程序介面"""

    @property
    def pid(self) -> int: ...

    def start(self) -> None: ...
    def wait_for_started(self, timeout_ms: int) -> bool: ...
    def is_running(self) -> bool: ...
    def returncode(self) -> int | None: ...
    def read_output(self, max_bytes: int) -> str: ...
    def write_line(self, line: str) -> bool: ...
    def wait(self, timeout_seconds: float) -> bool: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    def connect(
        self, on_output: Callable[[], None], on_finished: Callable[[int], None], on_error: Callable[[str], None]
    ) -> None: ...
    def close(self) -> None: ...


class SubprocessProcessAdapter:
    """以安全的 SubprocessUtils 管理伺服器子程序"""

    def __init__(self, command: list[str], cwd: str) -> None:
        self._command = command
        self._cwd = cwd
        self._process: Any | None = None
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._on_output: Callable[[], None] | None = None
        self._on_finished: Callable[[int], None] | None = None
        self._on_error: Callable[[str], None] | None = None
        self._reader: threading.Thread | None = None

    @property
    def pid(self) -> int:
        return int(self._process.pid) if self._process is not None else 0

    def start(self) -> None:
        """啟動子程序，並開始讀取輸出"""
        if self._process is not None:
            return
        self._process = SubprocessUtils.popen_checked(
            self._command,
            cwd=str(Path(self._cwd)),
            stdin=SubprocessUtils.PIPE,
            stdout=SubprocessUtils.PIPE,
            stderr=SubprocessUtils.STDOUT,
            bufsize=0,
        )
        self._reader = threading.Thread(target=self._read_loop, name=f"MSM-server-{self.pid}", daemon=True)
        self._reader.start()

    def wait_for_started(self, _timeout_ms: int) -> bool:
        """
        等待子程序啟動完成

        Args:
            _timeout_ms: 最長等待時間，單位為毫秒

        Returns:
            True 表示子程序已啟動，False 表示超時或子程序已退出
        """
        return self._process is not None and self._process.poll() is None

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def returncode(self) -> int | None:
        """
        返回子程序的退出碼

        Returns:
            子程序的退出碼，如果子程序尚未退出則返回 None
        """
        return None if self._process is None else self._process.poll()

    def read_output(self, max_bytes: int) -> str:
        """
        讀取子程序的輸出

        Args:
            max_bytes: 最多讀取的位元組數

        Returns:
            讀取到的輸出文字
        """
        with self._lock:
            data = bytes(self._buffer[: max(0, int(max_bytes))])
            del self._buffer[: len(data)]
        return data.decode("utf-8", errors="replace")

    def write_line(self, line: str) -> bool:
        """
        寫入一行到子程序的標準輸入

        Args:
            line: 要寫入的文字行，不需要包含換行符號

        Returns:
            True 表示寫入成功，False 表示子程序已退出或寫入失敗
        """
        process = self._process
        if process is None or process.stdin is None or not self.is_running():
            return False
        try:
            process.stdin.write((line.rstrip("\r\n") + "\n").encode("utf-8"))
            process.stdin.flush()
            return True
        except OSError:
            return False

    def wait(self, timeout_seconds: float) -> bool:
        """
        等待子程序退出

        Args:
            timeout_seconds: 最長等待時間，單位為秒

        Returns:
            True 表示子程序已退出，False 表示超時
        """
        process = self._process
        if process is None:
            return True
        try:
            process.wait(timeout=max(0.0, float(timeout_seconds)))
            return True
        except SubprocessUtils.TimeoutExpired:
            return False

    def terminate(self) -> None:
        """嘗試終止子程序"""
        if self._process is not None and self.is_running():
            self._process.terminate()

    def kill(self) -> None:
        """強制殺死子程序"""
        if self._process is not None and self.is_running():
            self._process.kill()

    def connect(
        self,
        on_output: Callable[[], None],
        on_finished: Callable[[int], None],
        on_error: Callable[[str], None],
    ) -> None:
        """
        連接事件回呼函式，當子程序有輸出、退出或發生錯誤時會呼叫對應的函式

        Args:
            on_output: 當子程序有輸出時呼叫，無參數
            on_finished: 當子程序退出時呼叫，參數為退出碼
            on_error: 當子程序讀取輸出發生錯誤時呼叫，參數為錯誤訊息
        """
        self._on_output = on_output
        self._on_finished = on_finished
        self._on_error = on_error

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                with suppress(OSError):
                    stream.close()
        self._process = None

    def _read_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while chunk := process.stdout.read(64 * 1024):
                with self._lock:
                    self._buffer.extend(chunk)
                if self._on_output is not None:
                    self._on_output()
            code = process.wait()
            if self._on_finished is not None:
                self._on_finished(int(code))
        except Exception as exc:
            if self._on_error is not None:
                self._on_error(str(exc))


__all__ = ["ProcessPort", "SubprocessProcessAdapter"]
