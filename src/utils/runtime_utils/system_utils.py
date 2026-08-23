"""
系統工具模組
提供系統資訊查詢與行程管理功能，使用 psutil 進行高可靠跨平台與 Windows 行程管理
"""

from __future__ import annotations

import threading
from contextlib import suppress
from pathlib import Path
from typing import ClassVar

import psutil

from src.utils import (
    JavaUtils,
    SubprocessUtils,
    get_logger,
)

logger = get_logger().bind(component="SystemUtils")

_PSUTIL_PROCESS_LOOKUP_ERRORS = (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess)


class SystemUtils:
    """系統工具類別"""

    _managed_processes_by_path: ClassVar[dict[str, set[int]]] = {}
    _managed_processes_lock: ClassVar[threading.RLock] = threading.RLock()

    @staticmethod
    def _normalize_managed_path(path: Path | str) -> str:
        try:
            return str(Path(path).resolve(strict=False)).casefold()
        except Exception:
            return str(path or "").casefold()

    @classmethod
    def register_managed_process(cls, path: Path | str, pid: int) -> None:
        """
        記錄由本程式啟動、可安全清理的行程

        Args:
            path: 行程所屬的伺服器或安裝工作目錄
            pid: 行程 ID
        """
        try:
            normalized_path = cls._normalize_managed_path(path)
            if not normalized_path:
                return
            with cls._managed_processes_lock:
                cls._managed_processes_by_path.setdefault(normalized_path, set()).add(int(pid))
        except Exception as exc:
            logger.debug(f"記錄受管理行程失敗: {exc}")

    @classmethod
    def unregister_managed_process(cls, path: Path | str, pid: int) -> None:
        """
        移除已結束或已清理的受管理行程

        Args:
            path: 行程所屬的伺服器或安裝工作目錄
            pid: 行程 ID
        """
        normalized_path = cls._normalize_managed_path(path)
        with cls._managed_processes_lock:
            pids = cls._managed_processes_by_path.get(normalized_path)
            if not pids:
                return
            pids.discard(int(pid))
            if not pids:
                cls._managed_processes_by_path.pop(normalized_path, None)

    @staticmethod
    def kill_java_processes_in_path(path: Path | str) -> bool:
        """
        終止本程式在指定路徑啟動過的 Java/啟動腳本行程樹

        Args:
            path: 目標資料夾

        Returns:
            至少有一個行程被終止則回傳 True
        """
        killed = False
        try:
            normalized_path = SystemUtils._normalize_managed_path(path)
            with SystemUtils._managed_processes_lock:
                tracked_pids = set(SystemUtils._managed_processes_by_path.get(normalized_path, set()))
            for pid in tracked_pids:
                if not SystemUtils.is_process_running(pid):
                    SystemUtils.unregister_managed_process(path, pid)
                    continue
                if SystemUtils.kill_process_tree(pid):
                    killed = True
                SystemUtils.unregister_managed_process(path, pid)
        except Exception as e:
            logger.error(f"kill_java_processes_in_path 失敗: {e}")
        return killed

    @staticmethod
    def get_total_memory_mb() -> int:
        """
        取得系統總實體記憶體

        Returns:
            系統總實體記憶體（MB）
        """
        try:
            return int(psutil.virtual_memory().total // (1024 * 1024))
        except Exception as e:
            logger.error(f"取得記憶體資訊失敗: {e}")
            return 4096

    @staticmethod
    def get_process_name(pid: int) -> str:
        """
        取得指定 PID 的行程名稱

        Args:
            pid: 行程 ID

        Returns:
            行程名稱；找不到時回傳空字串
        """
        try:
            return psutil.Process(pid).name()
        except Exception:
            return ""

    @staticmethod
    def get_process_children(pid_root: int) -> list[tuple[int, str]]:
        """
        取得子行程列表 [(pid, name), ...]

        Args:
            pid_root: 父行程 ID

        Returns:
            子行程清單
        """
        children: list[tuple[int, str]] = []
        try:
            parent = psutil.Process(pid_root)
            for child in parent.children(recursive=True):
                try:
                    children.append((child.pid, child.name()))
                except _PSUTIL_PROCESS_LOOKUP_ERRORS:
                    continue
        except Exception as e:
            logger.debug(f"取得子行程失敗: {e}")
        return children

    @staticmethod
    def get_process_memory_usage(pid: int) -> int:
        """
        獲取進程實體記憶體使用量 Working Set / RSS（bytes）
        與 Windows 工作管理員的記憶體欄位數值完全一致

        Args:
            pid: 進程 ID

        Returns:
            進程記憶體使用量（位元組）
        """
        try:
            proc = psutil.Process(pid)
            mem_info = proc.memory_info()
            return int(mem_info.rss)
        except Exception:
            return 0

    @staticmethod
    def find_java_process(parent_pid: int) -> int | None:
        """
        從父行程查找 Java 子行程 PID

        Args:
            parent_pid: 父行程 ID

        Returns:
            Java 子行程 PID；找不到時回傳 None
        """
        try:
            parent_name = SystemUtils.get_process_name(parent_pid)
            if parent_name and parent_name.lower() in JavaUtils.JAVA_EXECUTABLE_NAMES:
                return parent_pid
            children = SystemUtils.get_process_children(parent_pid)
            for pid, name in children:
                if name.lower() in JavaUtils.JAVA_EXECUTABLE_NAMES:
                    return pid
            return None
        except Exception:
            return None

    @staticmethod
    def kill_process_tree(pid: int) -> bool:
        """
        強制結束行程樹

        Args:
            pid: 要結束的行程 ID

        Returns:
            成功結束時回傳 True
        """
        try:
            if not psutil.pid_exists(pid):
                return True
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                with suppress(*_PSUTIL_PROCESS_LOOKUP_ERRORS):
                    child.kill()
            with suppress(*_PSUTIL_PROCESS_LOOKUP_ERRORS):
                parent.kill()
            all_procs = [*children, parent]
            psutil.wait_procs(all_procs, timeout=3.0)
            return True
        except _PSUTIL_PROCESS_LOOKUP_ERRORS:
            return True
        except Exception as e:
            logger.debug(f"psutil kill_process_tree 回退至 taskkill: {e}")
            try:
                cmd = ["taskkill", "/PID", str(pid), "/T", "/F"]
                SubprocessUtils.run_checked(cmd, stdout=SubprocessUtils.DEVNULL, stderr=SubprocessUtils.DEVNULL)
                return True
            except Exception as e2:
                logger.error(f"無法結束行程樹 {pid}: {e2}")
                return False

    @staticmethod
    def is_process_running(pid: int) -> bool:
        """
        檢查行程是否執行中

        Args:
            pid: 行程 ID

        Returns:
            行程仍在執行時回傳 True
        """
        try:
            if not psutil.pid_exists(pid):
                return False
            proc = psutil.Process(pid)
            return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
        except _PSUTIL_PROCESS_LOOKUP_ERRORS:
            return False
        except Exception:
            return False


__all__ = ["SystemUtils"]
