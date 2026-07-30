"""Minecraft 伺服器管理器主程式入口點"""

import contextlib
import ctypes
import sys
import traceback
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def _register_mutex() -> None:
    """註冊 Mutex 供 Inno Setup 偵測執行狀態（非 Windows 環境忽略）"""
    with contextlib.suppress(AttributeError):
        ctypes.windll.kernel32.CreateMutexW(None, False, "MinecraftServerManagerMutex")


def main() -> None:
    _register_mutex()
    try:
        from src.ui import run

        run()
    except Exception:
        msg = traceback.format_exc()
        with contextlib.suppress(AttributeError):
            ctypes.windll.user32.MessageBoxW(0, msg, "執行錯誤", 0x10)
        sys.exit(1)


if __name__ == "__main__":
    main()
