"""
Minecraft 伺服器管理器主程式

提供 Minecraft 伺服器的建立、管理和監控功能的主要入口點
"""

import ctypes
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.ui import run_application
from src.utils import get_logger

logger = get_logger().bind(component="Main")


def main():
    """應用程式入口點，處理啟動過程中的例外"""

    mutex_name = "MinecraftServerManagerMutex"
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW(None, False, mutex_name)
        run_application()
    except Exception as exc:
        logger.critical(f"應用程式啟動失敗: {exc}")


if __name__ == "__main__":
    main()
