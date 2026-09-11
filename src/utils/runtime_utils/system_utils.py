"""
系統工具模組
提供系統資訊查詢與 Windows 行程管理功能，使用 psutil 進行高可靠行程管理
"""

from __future__ import annotations

import threading
from contextlib import suppress
from pathlib import Path
from typing import ClassVar

import psutil

from src.utils import (
    JavaUtils,
    get_logger,
)

logger = get_logger().bind(component="SystemUtils")

_PSUTIL_PROCESS_LOOKUP_ERRORS = (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess)
_PSUTIL_PROCESS_GONE_ERRORS = (psutil.NoSuchProcess, psutil.ZombieProcess)


class SystemUtils:
    """系統工具類別"""

    _managed_processes_by_path: ClassVar[dict[str, set[psutil.Process]]] = {}
    _managed_processes_lock: ClassVar[threading.RLock] = threading.RLock()

    @staticmethod
    def _normalize_managed_path(path: Path | str) -> str:
        try:
            return str(Path(path).resolve(strict=False)).casefold()
        except Exception:
            return str(path or "").casefold()

    @classmethod
    def register_managed_process(cls, path: Path | str, pid: int) -> psutil.Process | None:
        """
        記錄由本程式啟動、可安全清理的行程

        Args:
            path: 行程所屬的伺服器或安裝工作目錄
            pid: 已啟動程序的作業系統 PID

        Returns:
            帶有 psutil 行程身分的清理 token；無法取得身分時回傳 None
        """
        try:
            normalized_path = cls._normalize_managed_path(path)
            if not normalized_path:
                return None
            normalized_pid = int(pid)
            if normalized_pid <= 0:
                return None
            managed_process = psutil.Process(normalized_pid)
            with cls._managed_processes_lock:
                cls._managed_processes_by_path.setdefault(normalized_path, set()).add(managed_process)
            return managed_process
        except Exception as e:
            logger.debug(f"記錄受管理行程失敗: {e}")
            return None

    @classmethod
    def unregister_managed_process(cls, path: Path | str, process: psutil.Process | None) -> None:
        """
        移除已結束或已清理的受管理行程

        Args:
            path: 行程所屬的伺服器或安裝工作目錄
            process: register_managed_process 回傳的清理 token
        """
        if process is None:
            return
        normalized_path = cls._normalize_managed_path(path)
        with cls._managed_processes_lock:
            processes = cls._managed_processes_by_path.get(normalized_path)
            if not processes:
                return
            processes.discard(process)
            if not processes:
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
        normalized_path = SystemUtils._normalize_managed_path(path)
        with SystemUtils._managed_processes_lock:
            tracked_processes = tuple(SystemUtils._managed_processes_by_path.get(normalized_path, set()))
        for process in tracked_processes:
            completed = False
            try:
                if process.is_running() and SystemUtils.kill_process_tree(process):
                    killed = True
                    completed = True
                elif not process.is_running():
                    completed = True
            except _PSUTIL_PROCESS_GONE_ERRORS:
                completed = True
            except psutil.AccessDenied:
                logger.warning("無權清理受管理行程，保留追蹤狀態")
            except Exception as e:
                logger.error(f"清理受管理行程失敗: {e}")
            if completed:
                SystemUtils.unregister_managed_process(path, process)
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
    def get_free_disk_bytes(path: Path | str) -> int:
        """
        取得指定路徑所在磁碟的可用空間

        Args:
            path: 目標路徑或其父目錄

        Returns:
            可用空間的位元組數
        """
        return int(psutil.disk_usage(str(path)).free)

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
        取得行程實體記憶體使用量（bytes）

        Args:
            pid: 行程 ID

        Returns:
            行程記憶體使用量（位元組）
        """
        try:
            proc = psutil.Process(pid)
            if hasattr(proc, "memory_full_info"):
                with suppress(Exception):
                    full_info = proc.memory_full_info()
                    if hasattr(full_info, "uss") and full_info.uss > 0:
                        return int(full_info.uss)
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
    def kill_process_tree(process: psutil.Process, *, timeout: float = 3.0) -> bool:
        """
        強制結束行程樹

        Args:
            process: 帶有建立時間身分的 psutil 行程物件
            timeout: 等待程序結束的秒數；UI 關閉輪詢使用零避免阻塞

        Returns:
            成功結束時回傳 True
        """
        try:
            if not process.is_running():
                return True
            children = process.children(recursive=True)
            for child in children:
                with suppress(*_PSUTIL_PROCESS_LOOKUP_ERRORS):
                    child.kill()
            with suppress(*_PSUTIL_PROCESS_LOOKUP_ERRORS):
                process.kill()
            all_procs = [*children, process]
            wait_result = psutil.wait_procs(all_procs, timeout=timeout)
            _gone, alive = wait_result
            return not alive
        except _PSUTIL_PROCESS_GONE_ERRORS:
            return True
        except psutil.AccessDenied:
            logger.warning("無權結束受管理行程樹")
            return False
        except Exception as e:
            logger.error(f"無法結束受管理行程樹: {e}")
            return False


__all__ = ["SystemUtils"]
