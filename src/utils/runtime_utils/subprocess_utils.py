"""
安全的 subprocess 包裝器
提供驗證可執行檔存在或可在 PATH 中找到的 run/popen 包裝函式，強制使用 shell=False
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PySide6 import QtCore

from src.utils import get_logger

logger = get_logger().bind(component="SubprocessUtils")


class SubprocessUtils:
    """提供安全的 subprocess 包裝，強制使用 shell=False"""

    PIPE = subprocess.PIPE
    STDOUT = subprocess.STDOUT
    DEVNULL = subprocess.DEVNULL
    CalledProcessError = subprocess.CalledProcessError
    TimeoutExpired = subprocess.TimeoutExpired
    STARTUPINFO = getattr(subprocess, "STARTUPINFO", None)
    STARTF_USESHOWWINDOW = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    SW_HIDE = 0
    CREATE_NO_WINDOW = 134217728
    CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)

    @staticmethod
    def get_hidden_windows_kwargs() -> dict:
        """
        回傳 Windows 隱藏視窗所需參數；非 Windows 平台回傳空 dict

        Returns:
            Windows 隱藏視窗所需參數，非 Windows 平台回傳空 dict
        """
        if os.name != "nt":
            return {}
        hidden_kwargs: dict = {"creationflags": SubprocessUtils.CREATE_NO_WINDOW}
        if SubprocessUtils.STARTUPINFO is not None:
            startupinfo = SubprocessUtils.STARTUPINFO()
            startupinfo.dwFlags |= SubprocessUtils.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = SubprocessUtils.SW_HIDE
            hidden_kwargs["startupinfo"] = startupinfo
        return hidden_kwargs

    @staticmethod
    def _validate_cmd(cmd: Iterable[str]) -> list[str]:
        if not isinstance(cmd, (list, tuple)):
            raise TypeError("cmd 必須是由字串組成的 list 或 tuple")
        cmd_list = [str(x) for x in cmd]
        if len(cmd_list) == 0:
            raise ValueError("cmd 不得為空")
        exe = cmd_list[0]
        if not exe.strip():
            raise ValueError("cmd[0] 不得為空")
        p = Path(exe)
        if p.is_absolute() or os.sep in exe or ("/" in exe and os.sep != "/"):
            if not p.exists():
                raise FileNotFoundError(f"執行檔路徑不存在: {exe}")
            return cmd_list
        which = shutil.which(exe)
        if which is None and os.name == "nt" and exe.lower() == "winget":
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            if local_app_data:
                winget_path = Path(local_app_data).resolve() / "Microsoft" / "WindowsApps" / "winget.exe"
                which = str(winget_path) if getattr(winget_path, "exists", lambda: False)() else None

        if which is None:
            raise FileNotFoundError(f"無法在 PATH 找到執行檔: {exe}")
        cmd_list[0] = which
        return cmd_list

    @staticmethod
    def _normalize_subprocess_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
        normalized_kwargs = dict(kwargs)
        if normalized_kwargs.get("shell", False):
            logger.debug("忽略 shell=True，基於安全考量強制使用 shell=False")
        normalized_kwargs["shell"] = False
        if (normalized_kwargs.get("text") or normalized_kwargs.get("universal_newlines")) and normalized_kwargs.get(
            "errors"
        ) is None:
            normalized_kwargs["errors"] = "replace"
        if normalized_kwargs.get("executable") is not None:
            raise ValueError("不允許覆寫 executable；請將可執行檔放在 cmd[0]")
        return normalized_kwargs

    @staticmethod
    def run_checked(cmd: Iterable[str], **kwargs) -> subprocess.CompletedProcess:
        """
        像 subprocess.run，但先驗證 cmd 並強制 shell=False

        Args:
            cmd: 命令列參數序列
            **kwargs: 傳遞給 subprocess.run 的其他參數

        Returns:
            subprocess.run 的執行結果
        """
        kwargs = SubprocessUtils._normalize_subprocess_kwargs(kwargs)
        cmd_list = SubprocessUtils._validate_cmd(cmd)
        # Bandit B603: argv 已先驗證，且 wrapper 會強制 shell=False
        return subprocess.run(cmd_list, **kwargs)  # nosec B603

    @staticmethod
    def popen_checked(cmd: Iterable[str], **kwargs) -> subprocess.Popen:
        """
        像 subprocess.Popen，但先驗證 cmd 並強制 shell=False

        Args:
            cmd: 命令列參數序列
            **kwargs: 傳遞給 subprocess.Popen 的其他參數

        Returns:
            建立完成的 subprocess.Popen 物件
        """
        kwargs = SubprocessUtils._normalize_subprocess_kwargs(kwargs)
        cmd_list = SubprocessUtils._validate_cmd(cmd)
        # Bandit B603: argv 已先驗證，且 wrapper 會強制 shell=False
        return subprocess.Popen(cmd_list, **kwargs)  # nosec B603

    @staticmethod
    def create_console_process(
        cmd: Iterable[str],
        *,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen:
        """
        在獨立控制台視窗中啟動子行程 (Windows CREATE_NEW_CONSOLE)

        Args:
            cmd: 要執行的命令清單
            cwd: 工作目錄
            env: 環境變數

        Returns:
            subprocess.Popen 實例
        """
        resolved_cmd = SubprocessUtils._validate_cmd(cmd)
        kwargs: dict[str, Any] = {
            "cwd": str(cwd) if cwd else None,
            "env": env,
        }
        if os.name == "nt":
            kwargs["creationflags"] = SubprocessUtils.CREATE_NEW_CONSOLE
        return subprocess.Popen(resolved_cmd, **kwargs)  # nosec B603

    @staticmethod
    def run_winget_interactive(args: list[str]) -> int:
        """
        在獨立終端機視窗中執行 winget 指令，並等待其結束回傳結束代碼

        Args:
            args: winget 參數清單

        Returns:
            行程結束代碼
        """
        proc = SubprocessUtils.create_console_process(["winget", *args])
        return proc.wait()

    @staticmethod
    def create_qprocess_checked(
        cmd: Iterable[str],
        *,
        cwd: str | None = None,
        merged_channels: bool = True,
        parent: QtCore.QObject | None = None,
    ) -> QtCore.QProcess:
        """
        建立已驗證 argv 的 QProcess

        Args:
            cmd: 命令列參數序列
            cwd: 工作目錄；未提供時沿用目前程序工作目錄
            merged_channels: 是否合併 stdout/stderr
            parent: QProcess 的 Qt parent

        Returns:
            已設定 program、arguments 與 channel mode 的 QProcess
        """

        cmd_list = SubprocessUtils._validate_cmd(cmd)
        process = QtCore.QProcess(parent)
        process.setProgram(cmd_list[0])
        process.setArguments(cmd_list[1:])
        if cwd:
            process.setWorkingDirectory(str(cwd))
        if merged_channels:
            process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        return process

    @staticmethod
    def popen_detached(cmd: Iterable[str], cwd: str | None = None) -> subprocess.Popen:
        """
        啟動分離的子行程，隔離 I/O 和生命週期，不顯示控制台視窗

        用於重新啟動/更新等場景，避免主行程結束時留下孤兒行程
        Windows 下自動隱藏控制台視窗，避免出現額外的命令提示字元視窗
        自動設定 DEVNULL、close_fds 和平台相關的分離旗標

        Args:
            cmd: 命令列表
            cwd: 工作目錄（可選）

        Returns:
            Popen 物件
        """
        DETACHED_PROCESS = 8
        CREATE_NEW_PROCESS_GROUP = 512
        hidden_kwargs = SubprocessUtils.get_hidden_windows_kwargs()
        creation_flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | hidden_kwargs.pop("creationflags", 0)
        return SubprocessUtils.popen_checked(
            cmd,
            cwd=cwd,
            stdin=SubprocessUtils.DEVNULL,
            stdout=SubprocessUtils.DEVNULL,
            stderr=SubprocessUtils.DEVNULL,
            close_fds=True,
            creationflags=creation_flags,
            **hidden_kwargs,
        )

    @staticmethod
    def create_no_window_process(cmd: Iterable[str], cwd: str | None = None) -> subprocess.Popen:
        """
        建立背景執行且不顯示控制台視窗的 Popen 行程

        Args:
            cmd: 命令列表
            cwd: 工作目錄（可選）

        Returns:
            Popen 物件
        """
        hidden_kwargs = SubprocessUtils.get_hidden_windows_kwargs()
        return SubprocessUtils.popen_checked(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=SubprocessUtils.DEVNULL,
            **hidden_kwargs,
        )


__all__ = ["SubprocessUtils"]
