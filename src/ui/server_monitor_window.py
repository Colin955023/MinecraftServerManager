#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
伺服器監控視窗
提供即時的伺服器狀態監控、控制台輸出和資源使用情況
"""
# ====== 標準函式庫 ======
from typing import Callable
import re
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
import customtkinter as ctk
# ====== 專案內部模組 ======
from ..utils.font_manager import font_manager, get_dpi_scaled_size, get_font
from ..utils.server_utils import ServerOperations
from ..utils.memory_utils import MemoryUtils
from ..utils.ui_utils import UIUtils
from ..utils.log_utils import LogUtils

class ServerMonitorWindow:
    """
    伺服器監控視窗
    Server Monitor Window
    """
    def start_auto_refresh(self) -> None:
        """
        啟動每秒自動刷新狀態
        Start automatic status refresh every second
        """
        if hasattr(self, "_auto_refresh_id") and self._auto_refresh_id:
            return  # 已經有定時器

        def _refresh():
            if self.window and self.window.winfo_exists():
                self.update_status()
                self._auto_refresh_id = self.window.after(1000, _refresh)
            else:
                self._auto_refresh_id = None

        self._auto_refresh_id = self.window.after(1000, _refresh)

    def stop_auto_refresh(self) -> None:
        """
        停止自動刷新狀態
        Stop automatic status refresh
        """
        if hasattr(self, "_auto_refresh_id") and self._auto_refresh_id:
            try:
                self.window.after_cancel(self._auto_refresh_id)
            except Exception:
                pass
            self._auto_refresh_id = None

    def __init__(self, parent, server_manager, server_name: str):
        self.parent = parent
        self.server_manager = server_manager
        self.server_name = server_name
        self.window = None
        self.is_monitoring = False
        self.monitor_thread = None
        # 即時玩家數量快取
        self._last_player_count = None
        self._last_max_players = None

        # 線程池執行器，用於執行非阻塞任務
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ServerMonitor")
        self.create_window()
        self.start_monitoring()

    def safe_update_widget(self, widget_name: str, update_func: Callable, *args, **kwargs) -> None:
        """
        安全地更新 widget，檢查 widget 是否存在
        Safely update widget, checking if widget exists
        """
        try:
            if hasattr(self, widget_name):
                widget = getattr(self, widget_name)
                if widget and widget.winfo_exists():
                    update_func(widget, *args, **kwargs)
        except Exception as e:
            LogUtils.error(f"更新 {widget_name} 失敗: {e}", "ServerMonitorWindow")

    def safe_config_widget(self, widget_name: str, **config) -> None:
        """
        安全地配置 widget
        Safely configure widget
        """
        self.safe_update_widget(widget_name, lambda w, **cfg: w.configure(**cfg), **config)

    def create_window(self) -> None:
        """
        創建監控視窗
        Create monitor window
        """

        self.window = tk.Toplevel(self.parent)
        self.window.title(f"伺服器監控 - {self.server_name}")
        self.window.state("normal")

        min_width = int(1200 * font_manager.get_scale_factor())  # 1200 * DPI
        min_height = int(900 * font_manager.get_scale_factor())  # 900 * DPI
        self.window.minsize(min_width, min_height)
        self.window.resizable(True, True)

        # 監控視窗為獨立視窗，僅需要綁定圖示和置中，不需要模態
        UIUtils.setup_window_properties(
            window=self.window,
            parent=self.parent,
            width=min_width,
            height=min_height,
            bind_icon=True,
            center_on_parent=True,
            make_modal=False,
            delay_ms=250,  # 使用稍長延遲確保圖示綁定成功
        )

        # 當視窗關閉時停止監控
        self.window.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 創建主要框架
        main_frame = ctk.CTkFrame(self.window)
        main_frame.pack(fill="both", expand=True, padx=get_dpi_scaled_size(15), pady=get_dpi_scaled_size(15))

        # 頂部控制區（含狀態/按鈕/資源/玩家）
        self.create_control_panel(main_frame)
        # 底部控制台輸出區
        self.create_console_panel(main_frame)

    def create_control_panel(self, parent) -> None:
        """
        創建控制面板
        Create control panel
        """
        control_frame = ctk.CTkFrame(parent)
        control_frame.pack(fill="x", pady=(0, int(10 * font_manager.get_scale_factor())))

        # 標題標籤
        title_label = ctk.CTkLabel(control_frame, text="🎮 伺服器控制", font=get_font(size=21, weight="bold"))  # 21px
        title_label.pack(pady=(get_dpi_scaled_size(15), get_dpi_scaled_size(8)))

        # 伺服器狀態
        # 狀態標籤（統一用 get_status_text）
        status_text, status_color = ServerOperations.get_status_text(False)
        self.status_label = ctk.CTkLabel(
            control_frame,
            text=status_text,
            font=get_font(size=20, weight="bold"),  # 20px
            text_color=status_color if status_color != "red" else "#e53e3e",
        )
        self.status_label.pack(side="left", padx=get_dpi_scaled_size(15))

        # 控制按鈕
        button_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        button_frame.pack(side="right", padx=10)

        self.start_button = ctk.CTkButton(
            button_frame, text="🚀 啟動", command=self.start_server, state="disabled", font=get_font(size=18), width=80
        )
        self.start_button.pack(side="left", padx=(0, 5))

        self.stop_button = ctk.CTkButton(
            button_frame,
            text="⏹️ 停止",
            command=self.stop_server,
            state="disabled",
            font=get_font(size=18),
            width=80,
            fg_color=("#e53e3e", "#dc2626"),
            hover_color=("#dc2626", "#b91c1c"),
        )
        self.stop_button.pack(side="left", padx=(0, 5))

        self.refresh_button = ctk.CTkButton(
            button_frame, text="🔄 刷新", command=self.refresh_status, font=get_font(size=18), width=80
        )
        self.refresh_button.pack(side="left")

        # 狀態顯示區（左/中/右）
        status_frame = ctk.CTkFrame(parent)
        status_frame.pack(fill="x", pady=(0, 10))

        # 標題標籤
        status_title_label = ctk.CTkLabel(status_frame, text="📈 系統資源", font=get_font(size=21, weight="bold"))
        status_title_label.pack(pady=(10, 5))

        # 內容框架
        status_content_frame = ctk.CTkFrame(status_frame, fg_color="transparent")
        status_content_frame.pack(fill="x", padx=10, pady=10)

        left_frame = ctk.CTkFrame(status_content_frame, fg_color="transparent")
        left_frame.pack(side="left", fill="both", expand=True)
        middle_frame = ctk.CTkFrame(status_content_frame, fg_color="transparent")
        middle_frame.pack(side="left", fill="both", expand=True)
        right_frame = ctk.CTkFrame(status_content_frame, fg_color="transparent")
        right_frame.pack(side="right", fill="both", expand=True)

        self.pid_label = ctk.CTkLabel(left_frame, text="🆔 PID: N/A", font=get_font(size=18), anchor="w")
        self.pid_label.pack(anchor="w", pady=2)

        self.memory_label = ctk.CTkLabel(left_frame, text="🧠 記憶體使用: 0 MB", font=get_font(size=18), anchor="w")
        self.memory_label.pack(anchor="w", pady=2)

        self.uptime_label = ctk.CTkLabel(middle_frame, text="⏱️ 運行時間: 00:00:00", font=get_font(size=18), anchor="w")
        self.uptime_label.pack(anchor="w", pady=2)

        self.players_label = ctk.CTkLabel(middle_frame, text="👥 玩家數量: 0/20", font=get_font(size=18), anchor="w")
        self.players_label.pack(anchor="w", pady=2)

        self.version_label = ctk.CTkLabel(right_frame, text="📦 版本: N/A", font=get_font(size=18), anchor="w")
        LogUtils.debug("初始化 ServerMonitorWindow，預設版本顯示 N/A", "ServerMonitorWindow")
        self.version_label.pack(anchor="w", pady=2)

        # 玩家列表面板
        players_frame = ctk.CTkFrame(parent)
        players_frame.pack(fill="x", pady=(0, 10))

        # 標題標籤
        players_title_label = ctk.CTkLabel(players_frame, text="👥 線上玩家", font=get_font(size=21, weight="bold"))
        players_title_label.pack(pady=(10, 5))

        # 玩家列表
        self.players_listbox = tk.Listbox(
            players_frame,
            height=5,
            font=get_font("Microsoft JhengHei", 18),
            bg="#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#f8fafc",
            fg="#ffffff" if ctk.get_appearance_mode() == "Dark" else "#000000",
            selectbackground="#1f538d",
            selectforeground="white",
            borderwidth=0,
            highlightthickness=0,
        )
        self.players_listbox.pack(fill="x", padx=10, pady=(0, 10))

        # 添加一個空的佔位項目
        self.players_listbox.insert(tk.END, "無玩家在線")

    def create_console_panel(self, parent) -> None:
        """
        創建控制台面板
        Create console panel with black background and green text
        """
        console_frame = ctk.CTkFrame(parent)
        console_frame.pack(fill="both", expand=True)

        # 標題標籤
        console_title_label = ctk.CTkLabel(
            console_frame, text="📜 控制台輸出", font=get_font(size=21, weight="bold")  # 21px
        )
        console_title_label.pack(pady=(10, 5))

        # 控制台文字區域
        self.console_text = ctk.CTkTextbox(
            console_frame,
            height=240,
            font=get_font(family="Consolas", size=15),
            wrap="word",
            fg_color="#000000",  # 黑色背景
            text_color="#00ff00",  # 綠色文字
            scrollbar_button_color="#333333",  # 滾動條按鈕顏色
            scrollbar_button_hover_color="#555555",  # 滾動條按鈕懸停顏色
        )
        self.console_text.pack(fill="both", expand=True, padx=get_dpi_scaled_size(15))

        # 命令輸入區
        command_frame = ctk.CTkFrame(console_frame, fg_color="transparent")
        command_frame.pack(fill="x", padx=get_dpi_scaled_size(15), pady=(5, 10))

        command_label = ctk.CTkLabel(command_frame, text="命令:", font=get_font(size=18))  # 18px
        command_label.pack(side="left", padx=(0, 10))

        self.command_entry = ctk.CTkEntry(
            command_frame,
            font=get_font(family="Consolas", size=14),
            placeholder_text="輸入指令...",
        )
        self.command_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.command_entry.bind("<Return>", self.send_command)

        self.send_button = ctk.CTkButton(
            command_frame, text="發送", command=self.send_command, state="disabled", font=get_font(size=18), width=80
        )
        self.send_button.pack(side="right")

    def start_monitoring(self) -> None:
        """
        開始監控，啟動時自動讀取現有日誌內容，避免橫幅遺漏
        Start monitoring and automatically read existing log content to avoid banner omission
        """
        if not self.is_monitoring:
            self.is_monitoring = True
            # 啟動時先讀取現有日誌內容
            self.window.after(0, self.refresh_status)
            # 啟動每秒自動刷新
            self.start_auto_refresh()
            # 使用線程池執行監控任務
            self.monitor_future = self.executor.submit(self.monitor_loop)

    def stop_monitoring(self) -> None:
        """
        停止監控
        Stop monitoring
        """
        self.is_monitoring = False
        self.stop_auto_refresh()
        # 關閉線程池
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=False)
        # 等待監控線程結束
        if hasattr(self, "monitor_future"):
            try:
                self.monitor_future.result(timeout=1)
            except Exception:
                pass
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=1)

    def monitor_loop(self) -> None:
        """
        改良的監控循環
        Improved monitoring loop
        """
        last_output_check = 0
        last_status_update = 0
        # 記錄上次日誌檔案修改時間，用於檢測新輸出
        last_log_mtime = 0

        while self.is_monitoring:
            try:
                current_time = time.time()
                # 每 1.5 秒更新一次狀態信息
                if current_time - last_status_update >= 1.5:
                    if self.window and self.window.winfo_exists():
                        self.window.after_idle(self.update_status)
                    last_status_update = current_time

                # 每 0.5 秒檢查一次是否有新的伺服器輸出
                if current_time - last_output_check >= 0.5:
                    # 只有當日誌檔案有新內容時才讀取輸出
                    try:
                        log_file = self.server_manager.get_server_log_file(self.server_name)
                        if log_file and log_file.exists():
                            current_mtime = log_file.stat().st_mtime
                            if current_mtime > last_log_mtime:
                                last_log_mtime = current_mtime
                                self.read_server_output()
                    except Exception:
                        pass
                    last_output_check = current_time

                # 適度休眠，減少 CPU 使用
                time.sleep(0.1)
            except Exception as e:
                LogUtils.error(f"監控更新錯誤: {e}", "ServerMonitorWindow")
                time.sleep(0.5)

    def read_server_output(self) -> None:
        """
        讀取伺服器輸出並顯示在控制台，並即時解析玩家數量/名單與啟動完成通知
        Read server output and display it in the console, and parse player count/list and startup completion notification in real-time
        """
        try:
            output_lines = self.server_manager.read_server_output(self.server_name, timeout=0.1)
            for line in output_lines:
                if line.strip():  # 只顯示非空行
                    self.window.after(0, self.add_console_message, line)
                    # 檢查玩家加入/離開訊息並更新玩家數量
                    self.window.after(0, self.check_player_events, line)

                    # 檢查伺服器啟動完成訊息（常見關鍵字）
                    if ("Done (" in line and "For help, type" in line) or "Server started" in line:
                        self.window.after(0, self.handle_server_ready)

                    # --- 新增：即時解析玩家數量與名單 ---
                    idx = line.find("There are ")
                    if idx != -1:
                        player_line = line[idx:]
                        self.read_player_list(line=player_line)
        except Exception as e:
            LogUtils.error(f"讀取伺服器輸出錯誤: {e}", "ServerMonitorWindow")

    def _update_ui(self, info) -> None:
        """
        根據 info 更新 UI 狀態顯示
        Update UI status display based on info

        Args:
            info (dict): 伺服器狀態資訊
        """
        try:
            is_running = info.get("is_running", False)
            pid = info.get("pid", "N/A")
            memory = info.get("memory", 0)
            uptime = info.get("uptime", "00:00:00")
            players = info.get("players", 0)
            max_players = info.get("max_players", 0)
            version = info.get("version", "N/A")

            # 狀態標籤（統一 get_status_text）
            if hasattr(self, "status_label") and self.status_label.winfo_exists():
                status_text, status_color = ServerOperations.get_status_text(is_running)
                self.status_label.configure(text=status_text, text_color=status_color)

            # PID
            self.safe_config_widget("pid_label", text=f"🆔 PID: {pid}")

            # 記憶體
            memory_bytes = memory * 1024 * 1024  # Convert MB to bytes
            mem_str = MemoryUtils.format_memory(memory_bytes)
            self.safe_config_widget("memory_label", text=f"🧠 記憶體使用: {mem_str}")

            # 運行時間
            self.safe_config_widget("uptime_label", text=f"⏱️ 運行時間: {uptime}")

            # 玩家數量與列表
            if not is_running:
                # 伺服器已停止，清空玩家數量與列表
                self._last_player_count = None
                self._last_max_players = None
                self.safe_config_widget("players_label", text="👥 玩家數量: 0/0")
                self.safe_update_widget(
                    "players_listbox", lambda w: [w.delete(0, tk.END), w.insert(tk.END, "無玩家在線")]
                )
            else:
                # 玩家數量（永遠優先顯示即時解析快取值）
                if self._last_player_count is not None and self._last_max_players is not None:
                    self.safe_config_widget(
                        "players_label", text=f"👥 玩家數量: {self._last_player_count}/{self._last_max_players}"
                    )
                else:
                    self.safe_config_widget("players_label", text=f"👥 玩家數量: {players}/{max_players}")

            # 版本
            self.safe_config_widget("version_label", text=f"📦 版本: {version}")

            # 按鈕狀態自動切換
            self.safe_config_widget("start_button", state="disabled" if is_running else "normal")
            self.safe_config_widget("stop_button", state="normal" if is_running else "disabled")
            self.safe_config_widget("send_button", state="normal" if is_running else "disabled")

        except Exception as e:
            LogUtils.error(f"_update_ui 更新 UI 狀態失敗: {e}", "ServerMonitorWindow")

    def check_player_events(self, line) -> None:
        """
        檢查玩家事件並更新玩家數量
        Check player events and update player count

        Args:
            line (str): 伺服器輸出行
        """
        try:
            # 檢查玩家加入訊息
            if "joined the game" in line:
                self.update_player_count()
            elif "left the game" in line:
                self.update_player_count()
        except Exception as e:
            LogUtils.error(f"檢查玩家事件錯誤: {e}", "ServerMonitorWindow")

    def update_player_count(self) -> None:
        """
        更新玩家數量
        Update player count
        """
        try:
            success = self.server_manager.send_command(self.server_name, "list")
            if success:
                self.window.after(800, self.read_player_list)
        except Exception as e:
            LogUtils.error(f"更新玩家數量錯誤: {e}", "ServerMonitorWindow")

    def read_player_list(self, line=None) -> None:
        """
        讀取玩家列表
        Read player list

        Args:
            line (str): 伺服器輸出行
        """
        try:
            if line is not None:
                lines = [line]
            else:
                lines = self.server_manager.read_server_output(self.server_name, timeout=1.2)
            found = False
            for line in lines:
                idx = line.find("There are ")
                if idx != -1:
                    line = line[idx:]
                m = re.search(r"There are (\d+) of a max of (\d+) players online:? ?(.*)", line)
                if m:
                    current_players = m.group(1)
                    max_players = m.group(2)
                    players_str = m.group(3).strip()
                    # 只要有 list 指令回應就更新快取與 UI（即使人數為 0）
                    self._last_player_count = int(current_players)
                    self._last_max_players = int(max_players)
                    self.players_label.configure(text=f"👥 玩家數量: {current_players}/{max_players}")
                    if players_str:
                        player_names = [name.strip() for name in players_str.split(",") if name.strip()]
                        self.update_player_list(player_names)
                    else:
                        self.update_player_list([])
                    found = True
                    break
            if not found:
                # 僅當真的沒抓到任何玩家列表才不動作
                pass
        except Exception as e:
            LogUtils.error(f"讀取玩家列表時發生錯誤: {e}", "ServerMonitorWindow")
            # 不主動清空列表，避免閃爍

    def update_player_list(self, players: list) -> None:
        """
        更新玩家列表顯示
        Update player list display

        Args:
            players (list): 玩家名稱列表
        """
        try:
            # 清空現有列表
            self.players_listbox.delete(0, tk.END)
            if players:
                for player in players:
                    if player:  # 確保玩家名稱不為空
                        self.players_listbox.insert(tk.END, f"🎮 {player}")
            else:
                self.players_listbox.insert(tk.END, "無玩家在線")
        except Exception as e:
            LogUtils.error(f"更新玩家列表錯誤: {e}", "ServerMonitorWindow")

    def update_status(self) -> None:
        """
        更新狀態顯示
        Update status display
        """
        try:
            # 檢查視窗是否還存在
            if not self.window or not self.window.winfo_exists():
                return
            info = self.server_manager.get_server_info(self.server_name)
            if not info:
                return
            # 在主線程中更新 UI
            self._update_ui(info)
        except Exception as e:
            LogUtils.error(f"更新狀態失敗: {e}", "ServerMonitorWindow")

    def start_server(self) -> None:
        """
        啟動伺服器
        Start the server
        """
        # 清空之前的控制台輸出
        self.console_text.delete("0.0", "end")

        success = self.server_manager.start_server(self.server_name, parent=self.window)
        if success:
            self.add_console_message(f"✅ 伺服器 {self.server_name} 啟動中...")
            # 立即更新狀態
            self.window.after(500, self.update_status)
        else:
            self.add_console_message(f"❌ 啟動伺服器 {self.server_name} 失敗")

    def stop_server(self) -> None:
        """
        停止伺服器
        Stop the server
        """
        success = ServerOperations.graceful_stop_server(self.server_manager, self.server_name)
        if success:
            self.add_console_message(f"⏹️ 伺服器 {self.server_name} 停止命令已發送")
            # 立即更新按鈕狀態和UI
            self.window.after(0, self.update_status)
            # 延遲檢查停止狀態
            self.window.after(2000, self.refresh_after_stop)
        else:
            self.add_console_message(f"❌ 停止伺服器 {self.server_name} 失敗")

        # 立即更新狀態
        try:
            if self.window and self.window.winfo_exists():
                self.window.after(100, self.update_status)
        except Exception as e:
            LogUtils.error(f"安全 after 調用錯誤: {e}", "ServerMonitorWindow")

    def refresh_after_stop(self) -> None:
        """
        停止後刷新狀態，直到伺服器完全結束才停止輪詢
        Refresh status after stopping, polling until the server is completely stopped
        """
        if self.server_manager.is_server_running(self.server_name):
            self.window.after(500, self.refresh_after_stop)
        else:
            self.refresh_status()
            self.update_status()  # 強制刷新按鈕與標籤
            self.add_console_message("✅ 伺服器已確認停止")
            self.update_player_list([])

    def refresh_status(self) -> None:
        """
        手動刷新狀態和控制台輸出
        Manually refresh status and console output
        """
        # 清空當前控制台內容
        self.console_text.delete("0.0", "end")

        # 玩家資訊暫存
        last_player_line = None

        # 獲取伺服器的完整日誌
        try:
            log_file = self.server_manager.get_server_log_file(self.server_name)
            if log_file and log_file.exists():
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    for line in lines:
                        if line.strip():
                            # 直接插入原始 log，不加任何前綴
                            self.console_text.insert("end", line.rstrip() + "\n")
                            # 若遇到玩家列表行，暫存
                            idx = line.find("There are ")
                            if idx != -1:
                                last_player_line = line[idx:]
                    # 滾動到底部
                    self.console_text.see(tk.END)
                    self.add_console_message("✅ 日誌載入完成")
                    # 若有玩家列表行，主動解析並更新玩家數量/名單
                    if last_player_line:
                        self.read_player_list(line=last_player_line)
                    else:
                        self.update_player_list([])
            else:
                self.add_console_message("⚠️ 未找到日誌檔案")
        except Exception as e:
            self.add_console_message(f"❌ 載入日誌失敗: {e}")

        # 更新狀態
        self.update_status()
        self.add_console_message("🔄 狀態和控制台已刷新")

    def send_command(self, event=None) -> None:
        """
        發送命令到伺服器
        Send command to the server
        """
        command = self.command_entry.get().strip()
        if not command:
            return

        self.command_entry.delete(0, "end")
        self.add_console_message(f"> {command}")

        # 發送命令到伺服器
        success = self.server_manager.send_command(self.server_name, command)
        if success:
            self.add_console_message(f"✅ 命令已發送: {command}")

            # 如果是停止命令，立即更新一次狀態
            if command.lower() in ["stop", "end", "exit"]:
                self.window.after(1000, self.update_status)  # 1秒後更新狀態

        else:
            self.add_console_message(f"❌ 命令發送失敗: {command}")

    def add_console_message(self, message: str) -> None:
        """
        添加控制台訊息，智能處理自動滾動
        Add console message with smart auto-scrolling
        """
        try:
            # 檢查視窗和控制台文字區域是否還存在
            if not self.window or not self.window.winfo_exists():
                return
            if not hasattr(self, "console_text") or not self.console_text.winfo_exists():
                return

            # 檢查使用者是否正在查看舊內容（不在底部）
            # CTkTextbox 沒有直接的 yview 方法，我們使用一個簡單的策略：
            # 記錄插入前的行數，如果使用者一直在底部，則繼續自動滾動

            # 插入新訊息
            self.console_text.insert("end", message + "\n")

            # 智能滾動：只有在伺服器運行時且使用者沒有主動滾動時才自動滾動到底部
            # 對於重要的伺服器狀態變化（如啟動、停止），強制滾動到底部
            should_auto_scroll = (
                # 伺服器正在運行時的新輸出
                (hasattr(self, "server_manager") and self.server_manager.is_server_running(self.server_name))
                or
                # 重要訊息（包含特定關鍵字）
                any(
                    keyword in message
                    for keyword in ["✅", "❌", "⏹️", "🔄", "啟動", "停止", "失敗", "成功", "載入完成"]
                )
            )

            if should_auto_scroll:
                # 延遲一點再滾動，確保內容已經插入
                self.window.after(10, lambda: self._scroll_to_bottom())

        except tk.TclError:
            # 視窗已被銷毀，忽略錯誤
            pass
        except Exception as e:
            LogUtils.error(f"添加控制台訊息錯誤: {e}", "ServerMonitorWindow")

    def _scroll_to_bottom(self) -> None:
        """
        安全地滾動到底部
        Safely scroll to bottom
        """
        try:
            if hasattr(self, "console_text") and self.console_text.winfo_exists():
                # 使用 see 方法滾動到最後一行
                self.console_text.see("end")
        except Exception as e:
            LogUtils.error(f"滾動到底部失敗: {e}", "ServerMonitorWindow")

    def on_closing(self) -> None:
        """
        視窗關閉時的處理
        Handle window closing
        """
        self.stop_monitoring()
        if self.window and self.window.winfo_exists():
            self.window.destroy()
        self.window = None

    def show(self) -> None:
        """
        顯示視窗
        Show window
        """
        if self.window:
            self.window.lift()
            self.window.focus_set()

    def handle_server_ready(self):
        """
        伺服器啟動完成後的 UI 處理
        Handle UI after server is ready
        """
        # 只做狀態刷新或顯示一次啟動完成訊息
        try:
            # 只顯示一次啟動完成訊息
            if hasattr(self, "_server_ready_notified") and self._server_ready_notified:
                return
            self._server_ready_notified = True
            # 讀取 server.properties
            properties = (
                self.server_manager.load_server_properties(self.server_name)
                if hasattr(self.server_manager, "load_server_properties")
                else {}
            )
            server_ip = properties.get("server-ip", "").strip()
            server_port = properties.get("server-port", "").strip()
            if not server_port:
                server_port = "25565"  # 預設值
            if server_ip:
                msg = f"伺服器啟動成功\n已在 {server_ip}:{server_port} 上開放"
            else:
                msg = f"伺服器啟動成功\n已在 {server_port} 埠口上開放"
            # 彈窗通知
            UIUtils.show_info("伺服器啟動成功", msg, self.window)
            # 額外 debug log
        except Exception as e:
            LogUtils.error(f"handle_server_ready 執行錯誤: {e}", "ServerMonitorWindow")
