"""
安全的 subprocess 包裝器
提供驗證可執行檔存在或可在 PATH 中找到的 run/popen 包裝函式，強制使用 shell=False。
"""

from __future__ import annotations

import os
import subprocess  # nosec B404
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .. import PathUtils, get_logger

logger = get_logger().bind(component="SubprocessUtils")


class SubprocessUtils:
    """提供安全的 subprocess 包裝，強制使用 shell=False。"""

    PIPE = subprocess.PIPE
    STDOUT = subprocess.STDOUT
    DEVNULL = subprocess.DEVNULL
    CalledProcessError = subprocess.CalledProcessError
    TimeoutExpired = subprocess.TimeoutExpired
    STARTUPINFO = getattr(subprocess, "STARTUPINFO", None)
    STARTF_USESHOWWINDOW = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    SW_HIDE = 0
    CREATE_NO_WINDOW = 134217728

    @staticmethod
    def get_hidden_windows_kwargs() -> dict:
        """回傳 Windows 隱藏視窗所需參數；非 Windows 平台回傳空 dict。"""
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
        which = PathUtils.find_executable(exe)
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
            logger.debug("忽略 shell=True，強制使用 shell=False for safety")
        normalized_kwargs["shell"] = False
        if normalized_kwargs.get("executable") is not None:
            raise ValueError("不允許覆寫 executable；請將可執行檔放在 cmd[0]")
        return normalized_kwargs

    @staticmethod
    def run_checked(cmd: Iterable[str], **kwargs) -> subprocess.CompletedProcess:
        """像 subprocess.run，但先驗證 `cmd` 並強制 `shell=False`。

        Args:
            cmd: 命令列參數序列。
            **kwargs: 傳遞給 `subprocess.run` 的其他參數。

        Returns:
            `subprocess.run` 的執行結果。
        """
        kwargs = SubprocessUtils._normalize_subprocess_kwargs(kwargs)
        cmd_list = SubprocessUtils._validate_cmd(cmd)
        # Bandit B603: argv 已先驗證，且 wrapper 會強制 shell=False。
        return subprocess.run(cmd_list, **kwargs)  # nosec B603

    @staticmethod
    def popen_checked(cmd: Iterable[str], **kwargs) -> subprocess.Popen:
        """像 `subprocess.Popen`，但先驗證 `cmd` 並強制 `shell=False`。

        Args:
            cmd: 命令列參數序列。
            **kwargs: 傳遞給 `subprocess.Popen` 的其他參數。

        Returns:
            建立完成的 `subprocess.Popen` 物件。
        """
        kwargs = SubprocessUtils._normalize_subprocess_kwargs(kwargs)
        cmd_list = SubprocessUtils._validate_cmd(cmd)
        # Bandit B603: argv 已先驗證，且 wrapper 會強制 shell=False。
        return subprocess.Popen(cmd_list, **kwargs)  # nosec B603

    @staticmethod
    def popen_detached(cmd: Iterable[str], cwd: str | None = None) -> subprocess.Popen:
        """
        啟動分離的子進程，隔離 I/O 和生命周期，不顯示控制台視窗。

        用於重啟/更新等場景，避免主進程退出時留下孤兒進程。
        Windows 下自動隱藏控制台視窗，避免出現額外的命令提示字元視窗。
        自動配置 DEVNULL、close_fds 和平台相關的分離旗標。

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
