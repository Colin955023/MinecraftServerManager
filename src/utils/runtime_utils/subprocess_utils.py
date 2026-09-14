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
from typing import Any, ClassVar

from src.utils import get_logger, is_reparse_point

logger = get_logger().bind(component="SubprocessUtils")


class SubprocessUtils:
    """提供安全的 subprocess 包裝，強制使用 shell=False"""

    PIPE = subprocess.PIPE
    STDOUT = subprocess.STDOUT
    DEVNULL = subprocess.DEVNULL
    CalledProcessError = subprocess.CalledProcessError
    TimeoutExpired = subprocess.TimeoutExpired
    STARTUPINFO = subprocess.STARTUPINFO
    STARTF_USESHOWWINDOW = subprocess.STARTF_USESHOWWINDOW
    SW_HIDE = subprocess.SW_HIDE
    CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW
    CREATE_NEW_CONSOLE = subprocess.CREATE_NEW_CONSOLE
    _windows_apps_dir: ClassVar[Path | None] = None
    _windows_apps_dir_resolved: ClassVar[bool] = False

    @classmethod
    def _get_windows_apps_dir(cls) -> Path | None:
        if not cls._windows_apps_dir_resolved:
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            if local_app_data:
                try:
                    cls._windows_apps_dir = (Path(local_app_data) / "Microsoft" / "WindowsApps").resolve()
                except OSError:
                    cls._windows_apps_dir = None
            cls._windows_apps_dir_resolved = True
        return cls._windows_apps_dir

    @staticmethod
    def get_hidden_windows_kwargs() -> dict:
        """
        回傳 Windows 隱藏視窗所需參數

        Returns:
            Windows 隱藏視窗所需參數
        """
        startupinfo = SubprocessUtils.STARTUPINFO()
        startupinfo.dwFlags |= SubprocessUtils.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = SubprocessUtils.SW_HIDE
        hidden_kwargs: dict[str, Any] = {
            "creationflags": SubprocessUtils.CREATE_NO_WINDOW,
            "startupinfo": startupinfo,
        }
        return hidden_kwargs

    @staticmethod
    def _is_trusted_windows_app_alias(path: Path) -> bool:
        """
        判斷是否為受信任的 WindowsApps 執行別名 (如 winget.exe)
        """
        if path.name.lower() not in {"winget.exe"}:
            return False
        windows_apps = SubprocessUtils._get_windows_apps_dir()
        if windows_apps is None:
            return False
        try:
            parent = path.parent.resolve()
            return os.path.normcase(str(parent)) == os.path.normcase(str(windows_apps))
        except OSError:
            return False

    @staticmethod
    def _validate_cmd(cmd: Iterable[str]) -> list[str]:
        if not isinstance(cmd, (list, tuple)):
            raise TypeError("cmd 必須是由字串組成的 list 或 tuple")
        cmd_list = [str(x) for x in cmd]
        if not cmd_list:
            raise ValueError("cmd 不得為空")
        exe = cmd_list[0]
        if not exe.strip():
            raise ValueError("cmd[0] 不得為空")
        p = Path(exe)
        if p.is_absolute() or os.sep in exe or (os.altsep is not None and os.altsep in exe):
            if not p.is_file() or (is_reparse_point(p) and not SubprocessUtils._is_trusted_windows_app_alias(p)):
                raise FileNotFoundError(f"執行檔路徑不是安全的一般檔案: {exe}")
            return cmd_list
        which = shutil.which(exe)
        if which is None and exe.lower() in ("winget", "winget.exe"):
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            if local_app_data:
                winget_path = Path(local_app_data).resolve() / "Microsoft" / "WindowsApps" / "winget.exe"
                which = str(winget_path) if winget_path.is_file() else None

        if which is None:
            raise FileNotFoundError(f"無法在 PATH 找到執行檔: {exe}")
        which_path = Path(which)
        if not which_path.is_file() or (
            is_reparse_point(which_path) and not SubprocessUtils._is_trusted_windows_app_alias(which_path)
        ):
            raise FileNotFoundError(f"PATH 執行檔不是安全的一般檔案: {which}")
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
        raw_kwargs: dict[str, Any] = {
            "cwd": str(cwd) if cwd else None,
            "env": env,
            "creationflags": SubprocessUtils.CREATE_NEW_CONSOLE,
        }
        kwargs = SubprocessUtils._normalize_subprocess_kwargs(raw_kwargs)
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
    def popen_detached(cmd: Iterable[str], cwd: str | None = None) -> subprocess.Popen:
        """
        啟動分離的子行程，隔離 I/O 和生命週期，不顯示控制台視窗

        用於重新啟動/更新等場景，避免主行程結束時留下孤兒行程
        Windows 下自動隱藏控制台視窗，避免出現額外的命令提示字元視窗
        自動設定 DEVNULL、close_fds 和 Windows 分離旗標

        Args:
            cmd: 命令列表
            cwd: 工作目錄（可選）

        Returns:
            Popen 物件
        """
        hidden_kwargs = SubprocessUtils.get_hidden_windows_kwargs()
        creation_flags = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | hidden_kwargs.pop("creationflags", 0)
        )
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
