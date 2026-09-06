"""
Minecraft 伺服器管理器主程式

提供 Minecraft 伺服器的建立、管理和監控功能的主要入口點
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.ui import run_application
from src.utils import APP_VERSION, HTTPClient, RuntimePaths, get_logger, shutdown_shared_manager

logger = get_logger().bind(component="Main")


def main() -> int:
    """
    應用程式入口點，處理啟動過程中的例外

    Returns:
        正常結束回傳 0；啟動或執行失敗回傳 1
    """

    mutex_name = "MinecraftServerManagerMutex"
    error_already_exists = 183
    mutex_handle = None
    kernel32 = getattr(ctypes.windll, "kernel32", None)
    try:
        if kernel32 is not None:
            mutex_handle = kernel32.CreateMutexW(None, False, mutex_name)
            get_last_error = getattr(kernel32, "GetLastError", None)
            if get_last_error is not None and get_last_error() == error_already_exists:
                logger.warning("偵測到已有執行中的應用程式實例，略過重複啟動")
                return 0
        run_application()
        RuntimePaths.cleanup_old_onefile_caches(APP_VERSION)
    except Exception:
        logger.critical("應用程式啟動失敗", exc_info=True)
        return 1
    finally:
        try:
            if kernel32 is not None and mutex_handle:
                close_handle = getattr(kernel32, "CloseHandle", None)
                if close_handle is not None:
                    close_handle(mutex_handle)
        finally:
            try:
                shutdown_shared_manager(wait=True)
            finally:
                HTTPClient.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
