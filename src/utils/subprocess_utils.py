#!/usr/bin/env python3
"""
安全的 subprocess 包裝器
提供驗證可執行檔存在或可在 PATH 中找到的 run/popen 包裝函式，強制使用 shell=False。
"""

from __future__ import annotations

import logging
import os
import subprocess  # nosec: B404
from collections.abc import Iterable
from pathlib import Path

from .path_utils import PathUtils

logger = logging.getLogger("msm.subprocess_utils")


class SubprocessUtils:
    PIPE = subprocess.PIPE
    STDOUT = subprocess.STDOUT
    DEVNULL = subprocess.DEVNULL
    CalledProcessError = subprocess.CalledProcessError
    TimeoutExpired = subprocess.TimeoutExpired

    STARTUPINFO = getattr(subprocess, "STARTUPINFO", None)
    STARTF_USESHOWWINDOW = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    SW_HIDE = 0
    CREATE_NO_WINDOW = 0x08000000

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
        # 如果 exe 是路徑（包含分隔符），則要求該執行檔存在
        p = Path(exe)
        if p.is_absolute() or (os.sep in exe) or ("/" in exe and os.sep != "/"):
            if not p.exists():
                raise FileNotFoundError(f"執行檔路徑不存在: {exe}")
            return cmd_list

        # 否則在 PATH 中查找執行檔
        which = PathUtils.find_executable(exe)
        if which is None:
            raise FileNotFoundError(f"無法在 PATH 找到執行檔: {exe}")
        # 使用 which 回傳的絕對路徑取代，以避免 PATH 帶來的意外
        cmd_list[0] = which
        return cmd_list

    @staticmethod
    def run_checked(cmd: Iterable[str], **kwargs) -> subprocess.CompletedProcess:
        """像 subprocess.run，但先驗證 cmd 並強制 shell=False。"""
        kwargs = dict(kwargs)
        if kwargs.get("shell", False):
            logger.debug("忽略 shell=True，強制使用 shell=False for safety")
        kwargs["shell"] = False

        cmd_list = SubprocessUtils._validate_cmd(cmd)
        return subprocess.run(cmd_list, **kwargs)  # nosec: B603

    @staticmethod
    def popen_checked(cmd: Iterable[str], **kwargs) -> subprocess.Popen:
        """像 subprocess.Popen，但先驗證 cmd 並強制 shell=False。回傳 Popen 物件。"""
        kwargs = dict(kwargs)
        if kwargs.get("shell", False):
            logger.debug("忽略 shell=True，強制使用 shell=False for safety")
        kwargs["shell"] = False

        cmd_list = SubprocessUtils._validate_cmd(cmd)
        return subprocess.Popen(cmd_list, **kwargs)  # nosec: B603

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
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
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
