"""
Minecraft 伺服器管理器主程式

提供 Minecraft 伺服器的建立、管理和監控功能的主要入口點
"""

from __future__ import annotations

import ctypes
import sys
import traceback
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.ui import run_application
from src.utils import HTTPClient, get_logger, shutdown_shared_manager

logger = get_logger().bind(component="Main")


def main() -> int:
    """
    應用程式入口點，處理啟動過程中的例外

    Returns:
        正常結束回傳 0；啟動或執行失敗回傳 1
    """

    mutex_name = "MinecraftServerManagerMutex"
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW(None, False, mutex_name)
        run_application()
    except Exception as e:
        logger.critical(f"應用程式啟動失敗: {e}\n{traceback.format_exc()}")
        return 1
    finally:
        shutdown_shared_manager(wait=False)
        HTTPClient.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
