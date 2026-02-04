#!/usr/bin/env python3
"""
安全的 subprocess 包裝器
提供驗證可執行檔存在或可在 PATH 中找到的 run/popen 包裝函式，強制使用 shell=False。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess  # nosec: B404
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger("msm.subprocess_utils")


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
    which = shutil.which(exe)
    if which is None:
        raise FileNotFoundError(f"無法在 PATH 找到執行檔: {exe}")
    # 使用 which 回傳的絕對路徑取代，以避免 PATH 帶來的意外
    cmd_list[0] = which
    return cmd_list


def run_checked(cmd: Iterable[str], **kwargs) -> subprocess.CompletedProcess:
    """像 subprocess.run，但先驗證 cmd 並強制 shell=False。"""
    kwargs = dict(kwargs)
    if kwargs.get("shell", False):
        logger.debug("忽略 shell=True，強制使用 shell=False for safety")
    kwargs["shell"] = False

    cmd_list = _validate_cmd(cmd)
    return subprocess.run(cmd_list, **kwargs)  # nosec: B603


def popen_checked(cmd: Iterable[str], **kwargs) -> subprocess.Popen:
    """像 subprocess.Popen，但先驗證 cmd 並強制 shell=False。回傳 Popen 物件。"""
    kwargs = dict(kwargs)
    if kwargs.get("shell", False):
        logger.debug("忽略 shell=True，強制使用 shell=False for safety")
    kwargs["shell"] = False

    cmd_list = _validate_cmd(cmd)
    return subprocess.Popen(cmd_list, **kwargs)  # nosec: B603
