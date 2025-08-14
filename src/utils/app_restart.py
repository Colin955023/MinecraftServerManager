#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
應用程式重啟工具模組
提供安全的應用程式重啟功能，支援打包執行檔和 Python 腳本模式
Application Restart Utilities Module
Provides safe application restart functionality for both packaged executables and Python script modes
"""
# ====== 標準函式庫 ======
from pathlib import Path
from typing import Optional
import os
import subprocess
import sys
import threading
import time
import traceback

# ====== 執行檔資訊檢測 ======

# 取得當前執行檔的詳細資訊
def _get_executable_info() -> tuple[list[str], bool, Optional[Path]]:
    """
    取得當前應用程式的執行檔資訊，區分打包檔案和 Python 腳本
    Get current application executable information, distinguishing between packaged files and Python scripts
    
    Args:
        None
        
    Returns:
        tuple: (執行命令列表, 是否為打包檔案, 腳本路徑)
    """
    is_frozen = getattr(sys, 'frozen', False)
    if is_frozen:
        return [sys.executable], True, None
    else:
        script_path = Path(__file__).parent.parent.parent / "minecraft_server_manager.py"
        return [sys.executable, str(script_path)], False, script_path

# ====== 重啟功能檢測 ======

# 檢查應用程式是否具備重啟能力
def can_restart() -> bool:
    """
    檢查當前環境是否支援應用程式重啟功能
    Check if current environment supports application restart functionality
    
    Args:
        None
        
    Returns:
        bool: 支援重啟返回 True，否則返回 False
    """
    try:
        executable_path, is_frozen, script_path = _get_executable_info()

        if is_frozen:
            return os.path.exists(executable_path)
        else:
            # 直接檢查腳本路徑是否存在 / Directly check if script path exists
            return script_path is not None and script_path.exists()
    except Exception:
        return False

# ====== 重啟執行功能 ======

# 重啟應用程式主要函數
def restart_application(delay: float = 1.0) -> bool:
    """
    重啟應用程式，支援延遲啟動和狀態檢測
    Restart the application with delayed start and status detection support
    
    Args:
        delay (float): 重啟前的延遲時間（秒）
        
    Returns:
        bool: 重啟程序啟動成功返回 True，失敗返回 False
    """
    try:
        executable_cmd, is_frozen, script_path = _get_executable_info()

        # 使用事件來同步重啟狀態 / Use event to synchronize restart status
        restart_success = threading.Event()
        restart_error = threading.Event()

        def delayed_restart():
            """延遲重啟函數 / Delayed restart function"""
            try:
                time.sleep(delay)

                # Windows 平台隱藏命令提示字元視窗
                if sys.platform == "win32":
                    # 使用 CREATE_NO_WINDOW 標誌隱藏命令提示字元視窗
                    creation_flags = subprocess.CREATE_NO_WINDOW
                else:
                    creation_flags = 0

                if is_frozen:
                    # PyInstaller 打包的執行檔 / PyInstaller packed executable
                    process = subprocess.Popen(
                        executable_cmd, cwd=os.path.dirname(executable_cmd[0]), creationflags=creation_flags
                    )
                else:
                    # Python 腳本 / Python script
                    process = subprocess.Popen(
                        executable_cmd, cwd=os.getcwd(), creationflags=creation_flags
                    )

                # 等待一小段時間確保新程序啟動成功 / Wait briefly to ensure new process starts
                time.sleep(0.5)

                # 檢查新程序是否仍在運行 / Check if new process is still running
                if process.poll() is None:
                    restart_success.set()
                else:
                    restart_error.set()

            except Exception as e:
                print(f"重啟失敗 / Restart failed: {e}")
                restart_error.set()

        # 在背景執行緒中執行延遲重啟 / Execute delayed restart in background thread
        restart_thread = threading.Thread(target=delayed_restart, daemon=False)
        restart_thread.start()

        # 等待重啟結果，最多等待 delay + 2 秒 / Wait for restart result, max delay + 2 seconds
        max_wait_time = delay + 2.0
        if restart_success.wait(timeout=max_wait_time):
            return True
        elif restart_error.is_set():
            return False
        else:
            # 超時情況下仍然返回 True，假設重啟會成功 / Return True on timeout, assume restart will succeed
            return True

    except Exception as e:
        print(f"準備重啟時發生錯誤 / Error preparing restart: {e}")
        return False

# 安排重啟並退出當前應用程式
def schedule_restart_and_exit(parent_window=None, delay: float = 1.0) -> None:
    """
    安排應用程式重啟並安全關閉當前實例，包含 GUI 視窗處理
    Schedule application restart and safely close current instance with GUI window handling
    
    Args:
        parent_window: 父視窗物件，用於正確關閉 GUI
        delay (float): 重啟前的延遲時間（秒）
        
    Returns:
        None
    """
    try:
        # 首先嘗試啟動重啟程序 / First attempt to start restart process
        restart_initiated = restart_application(delay)

        if restart_initiated:
            print("重啟程序已啟動，準備關閉當前應用程式 / Restart initiated, preparing to close current application")

            # 給重啟程序一些時間來準備 / Give restart process some time to prepare
            time.sleep(0.2)

            # 關閉當前應用程式 / Close current application
            if parent_window:
                try:
                    # 使用 after 方法延遲關閉，確保 UI 操作完成 / Use after method to delay closure
                    def delayed_close():
                        try:
                            parent_window.quit()  # 停止主事件迴圈 / Stop main event loop
                            parent_window.destroy()  # 銷毀視窗 / Destroy window
                        except Exception as e:
                            print(f"關閉視窗時發生錯誤 / Error closing window: {e}")

                        # 延遲退出以確保新程序有時間啟動 / Delay exit to ensure new process has time to start
                        time.sleep(0.5)
                        sys.exit(0)

                    # 在主線程中安排延遲關閉 / Schedule delayed closure in main thread
                    parent_window.after(100, delayed_close)

                except Exception as e:
                    print(f"安排視窗關閉時發生錯誤 / Error scheduling window closure: {e}")
                    # 如果無法使用 after 方法，直接關閉 / If after method fails, close directly
                    try:
                        parent_window.quit()
                        parent_window.destroy()
                    except Exception:
                        pass
                    time.sleep(0.5)
                    sys.exit(0)
            else:
                # 沒有父視窗，直接延遲退出 / No parent window, exit with delay
                time.sleep(0.5)
                sys.exit(0)
        else:
            print("重啟失敗，程式將繼續運行 / Restart failed, application will continue")

    except Exception as e:
        print(f"重啟程序失敗 / Restart process failed: {e}")
        traceback.print_exc()


