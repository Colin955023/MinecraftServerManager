#!/usr/bin/env python3
"""系統工具模組
提供系統資訊查詢與進程管理功能，使用原生 Windows API 取代 psutil 依賴
System Utilities Module
Provides system information query and process management functions, using native Windows APIs to replace the psutil dependency
"""

import ctypes
from ctypes import wintypes

from . import SubprocessUtils, get_logger

logger = get_logger().bind(component="SystemUtils")


# Windows API Constants & Structures
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259

_windll = getattr(ctypes, "windll", None)
_kernel32 = _windll.kernel32 if _windll else None
_user32 = _windll.user32 if _windll and hasattr(_windll, "user32") else None
_psapi = _windll.psapi if _windll and hasattr(_windll, "psapi") else None

Structure = ctypes.Structure
byref = ctypes.byref
c_size_t = ctypes.c_size_t
c_uint64 = ctypes.c_uint64
c_void_p = ctypes.c_void_p
sizeof = ctypes.sizeof


class MEMORYSTATUSEX(Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", c_uint64),
        ("ullAvailPhys", c_uint64),
        ("ullTotalPageFile", c_uint64),
        ("ullAvailPageFile", c_uint64),
        ("ullTotalVirtual", c_uint64),
        ("ullAvailVirtual", c_uint64),
        ("ullAvailExtendedVirtual", c_uint64),
    ]


class PROCESSENTRY32(Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.CHAR * 260),
    ]


class PROCESS_MEMORY_COUNTERS_EX(Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", c_size_t),
        ("WorkingSetSize", c_size_t),
        ("QuotaPeakPagedPoolUsage", c_size_t),
        ("QuotaPagedPoolUsage", c_size_t),
        ("QuotaPeakNonPagedPoolUsage", c_size_t),
        ("QuotaNonPagedPoolUsage", c_size_t),
        ("PagefileUsage", c_size_t),
        ("PeakPagefileUsage", c_size_t),
        ("PrivateUsage", c_size_t),
    ]


class SystemUtils:
    """系統工具類別"""

    @staticmethod
    def _iterate_process_snapshot() -> list[PROCESSENTRY32]:
        """回傳當前系統進程快照"""
        if _kernel32 is None:
            return []

        snapshot: list[PROCESSENTRY32] = []
        h_snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if h_snap == -1:
            return snapshot

        try:
            pe32 = PROCESSENTRY32()
            pe32.dwSize = sizeof(PROCESSENTRY32)

            if _kernel32.Process32First(h_snap, byref(pe32)):
                while True:
                    current = PROCESSENTRY32()
                    ctypes.memmove(byref(current), byref(pe32), sizeof(PROCESSENTRY32))
                    snapshot.append(current)
                    if not _kernel32.Process32Next(h_snap, byref(pe32)):
                        break
        finally:
            _kernel32.CloseHandle(h_snap)

        return snapshot

    @staticmethod
    def _decode_process_name(entry: PROCESSENTRY32) -> str:
        try:
            return entry.szExeFile.decode("mbcs")
        except Exception:
            return str(entry.szExeFile)

    @staticmethod
    def get_total_memory_mb() -> int:
        """獲取系統總實體記憶體"""
        try:
            if _kernel32 is None:
                return 4096

            stat = MEMORYSTATUSEX()
            stat.dwLength = sizeof(stat)
            if not _kernel32.GlobalMemoryStatusEx(byref(stat)):
                return 4096
            return int(stat.ullTotalPhys / (1024 * 1024))
        except Exception as e:
            logger.error(f"獲取記憶體資訊失敗: {e}")
            return 4096

    @staticmethod
    def get_process_name(pid: int) -> str:
        """獲取指定 PID 的進程名稱"""
        try:
            for entry in SystemUtils._iterate_process_snapshot():
                if entry.th32ProcessID == pid:
                    return SystemUtils._decode_process_name(entry)
        except Exception as e:
            logger.error(f"獲取進程名稱失敗: {e}")
        return ""

    @staticmethod
    def get_process_children(pid_root: int) -> list[tuple[int, str]]:
        """獲取子進程列表 [(pid, name), ...]"""
        children: list[tuple[int, str]] = []
        try:
            snapshot = SystemUtils._iterate_process_snapshot()
            if not snapshot:
                return children

            by_parent: dict[int, list[PROCESSENTRY32]] = {}
            for entry in snapshot:
                by_parent.setdefault(int(entry.th32ParentProcessID), []).append(entry)

            queue = [pid_root]
            while queue:
                parent_pid = queue.pop()
                for child in by_parent.get(parent_pid, []):
                    child_pid = int(child.th32ProcessID)
                    children.append((child_pid, SystemUtils._decode_process_name(child)))
                    queue.append(child_pid)
        except Exception as e:
            logger.error(f"獲取子進程失敗: {e}")
        return children

    @staticmethod
    def get_process_memory_usage(pid: int) -> int:
        """獲取進程記憶體使用量 (bytes)"""
        if _kernel32 is None or _psapi is None:
            return 0

        h_process = 0
        try:
            h_process = _kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
            if not h_process:
                return 0

            mem_counters = PROCESS_MEMORY_COUNTERS_EX()
            mem_counters.cb = sizeof(PROCESS_MEMORY_COUNTERS_EX)
            if _psapi.GetProcessMemoryInfo(h_process, byref(mem_counters), sizeof(mem_counters)):
                return int(mem_counters.WorkingSetSize)
            return 0
        except Exception as e:
            logger.error(f"獲取進程 {pid} 記憶體失敗: {e}")
            return 0
        finally:
            if h_process:
                _kernel32.CloseHandle(h_process)

    @staticmethod
    def find_java_process(parent_pid: int) -> int | None:
        """從父進程查找 Java 子進程 PID"""
        try:
            # 檢查父進程本身（如果是直接執行 java）
            parent_name = SystemUtils.get_process_name(parent_pid)
            if parent_name and parent_name.lower() in ("java.exe", "javaw.exe"):
                return parent_pid

            children = SystemUtils.get_process_children(parent_pid)
            for pid, name in children:
                if name.lower() in ("java.exe", "javaw.exe"):
                    return pid
            return None
        except Exception:
            return None

    @staticmethod
    def kill_process_tree(pid: int) -> bool:
        """強制結束進程樹"""
        try:
            cmd = ["taskkill", "/PID", str(pid), "/T", "/F"]
            SubprocessUtils.run_checked(cmd, stdout=SubprocessUtils.DEVNULL, stderr=SubprocessUtils.DEVNULL)
            return True
        except Exception as e:
            logger.error(f"無法結束進程樹 {pid}: {e}")
            return False

    @staticmethod
    def is_process_running(pid: int) -> bool:
        """檢查進程是否運行中"""
        if _kernel32 is None:
            return False

        h_process = 0
        try:
            h_process = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h_process:
                return False

            exit_code = wintypes.DWORD()
            ok = _kernel32.GetExitCodeProcess(h_process, byref(exit_code))
            if not ok:
                return False
            return exit_code.value == STILL_ACTIVE
        except Exception:
            return False
        finally:
            if h_process:
                _kernel32.CloseHandle(h_process)

    @staticmethod
    def set_process_dpi_aware() -> None:
        """設定進程 DPI 感知"""
        try:
            if _user32 is not None:
                _user32.SetProcessDPIAware()
        except Exception as e:
            logger.error(f"設定進程 DPI 感知失敗: {e}")

    @staticmethod
    def get_system_metrics(index: int) -> int:
        """獲取系統指標"""
        try:
            if _user32 is not None:
                return _user32.GetSystemMetrics(index)
            return 0
        except Exception:
            return 0
