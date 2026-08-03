"""
Minecraft 伺服器管理器主程式

提供 Minecraft 伺服器的建立、管理和監控功能的主要入口點
"""

import contextlib
import ctypes
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.ui import run_application


def main():
    """應用程式入口點，處理啟動過程中的例外"""
    # 註冊 Mutex 供 Inno Setup 偵測應用程式程式執行狀態
    mutex_name = "MinecraftServerManagerMutex"
    with contextlib.suppress(Exception):
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW(None, False, mutex_name)
        run_application()


if __name__ == "__main__":
    main()
