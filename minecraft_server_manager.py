#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minecraft 伺服器管理器主程式
提供 Minecraft 伺服器的建立、管理和監控功能的主要入口點
Minecraft Server Manager Main Application
Main entry point for creating, managing and monitoring Minecraft servers
"""
# ====== 標準函式庫 ======
import sys
import tkinter as tk
import tkinter.messagebox as msgbox
import traceback
import customtkinter as ctk
# ====== 專案內部模組 ======
from src.core.loader_manager import LoaderManager
from src.core.version_manager import MinecraftVersionManager
from src.ui.main_window import MinecraftServerManager
from src.utils.font_manager import set_ui_scale_factor
from src.utils.settings_manager import get_settings_manager

# ====== 訊息顯示工具 ======

# 顯示訊息對話框
def show_message(title, message, message_type="error"):
    """
    顯示訊息對話框，優先使用 tkinter，備選主控台輸出
    Show message dialog, prefer tkinter with console output fallback
    
    Args:
        title (str): 對話框標題
        message (str): 訊息內容
        message_type (str): 訊息類型
        
    Returns:
        bool: 是否成功顯示 GUI 對話框
    """
    try:
        root = tk.Tk()
        root.withdraw()
        if message_type == "error":
            msgbox.showerror(title, message)
        else:
            msgbox.showinfo(title, message)
        root.destroy()
        return True
    except Exception:
        # 最後備援：主控台輸出（不阻塞）
        icon = "錯誤" if message_type == "error" else "資訊"
        color = {"error": "91", "info": "94"}.get(message_type, "93")  # 91紅,94藍,預設93黃
        print(f"\n\033[{color}m{icon}: {title}\n訊息: {message}\033[0m")
        return False

# ====== 應用程式啟動 ======

# 啟動主應用程式
def start_application():
    """
    啟動主應用程式，初始化管理器並設定 UI 環境
    Start main application, initialize managers and setup UI environment
    
    Args:
        None
        
    Returns:
        None
    """
    _initialize_managers()
    _setup_ui_environment()
    _launch_main_window()

def _initialize_managers():
    """初始化管理器"""
    LoaderManager()
    MinecraftVersionManager()

def _setup_ui_environment():
    """設定 UI 環境"""
    # 應用淺色主題
    ctk.set_appearance_mode("light")
    
    # 從設定中載入UI縮放並應用
    settings = get_settings_manager()
    dpi_scaling = settings.get_dpi_scaling()
    set_ui_scale_factor(dpi_scaling)

def _launch_main_window():
    """啟動主視窗"""
    root = ctk.CTk()
    MinecraftServerManager(root)
    root.mainloop()

def main():
    """主程式入口點，負責整體流程控制（單一頂層錯誤處理）。"""
    try:
        start_application()
    except KeyboardInterrupt:
        show_message("程式中斷", "程式被使用者中斷\n感謝使用 Minecraft 伺服器管理器！", "info")
    except Exception:
        error_message = f"程式執行錯誤：\n\n{traceback.format_exc()}"
        show_message("執行錯誤", error_message, "error")
        sys.exit(1)

if __name__ == "__main__":
    main()
