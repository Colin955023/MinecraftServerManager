#!/usr/bin/env python3
"""伺服器監控視窗
提供即時的伺服器狀態監控、控制台輸出和資源使用情況
"""

import queue
import re
import threading
import time
import tkinter as tk
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import customtkinter as ctk

from ..utils import (
    MemoryUtils,
    ServerOperations,
    UIUtils,
    WindowManager,
    font_manager,
    get_dpi_scaled_size,
    get_font,
    get_logger,
    pack_main_frame,
)

logger = get_logger().bind(component="ServerMonitorWindow")


class ServerMonitorWindow:
    """伺服器監控視窗
    Server Monitor Window
    """

    def __init__(self, parent, server_manager, server_name: str):
        self.parent = parent
        self.server_manager = server_manager
        self.server_name = server_name
        self.window: tk.Toplevel | None = None
        self._auto_refresh_id: str | None = None
        self.is_monitoring = False
        self.monitor_thread = None
        # 即時玩家數量快取
        self._last_player_count: int | None = None
        self._last_max_players: int | None = None
        self._last_player_names: tuple[str, ...] | None = None
        self._history_index: int | None = None
        self._server_ready_notified: bool = False

        # UI 狀態快取，減少重繪
        self._last_ui_state: dict[str, Any] = {}
        # 控制台訊息緩衝區
        self._console_buffer: list[str] = []
        self._console_flush_job: str | None = None

        # 指令歷史紀錄
        self._command_history: list[str] = []

        self._monitor_stop_event = threading.Event()

        # 線程池執行器，用於執行非阻塞任務
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ServerMonitor")

        # 初始化 UI 更新佇列 Initialize UI update queue
        self.ui_queue: queue.Queue[Callable[[], Any]] = queue.Queue()

    def start_auto_refresh(self) -> None:
        """啟動每秒自動刷新狀態
        Start automatic status refresh every second
        """
        if self._auto_refresh_id:
            return  # 已經有定時器

        if not self.window:
            return

        def _refresh() -> None:
            if self.window and self.window.winfo_exists():
                self.update_status()
                self._auto_refresh_id = self.window.after(1000, _refresh)
            else:
                self._auto_refresh_id = None

        self._auto_refresh_id = self.window.after(1000, _refresh)

    def stop_auto_refresh(self) -> None:
        """停止自動刷新狀態
        Stop automatic status refresh
        """
        if self._auto_refresh_id:
            try:
                if self.window:
                    self.window.after_cancel(self._auto_refresh_id)
            except Exception as e:
                logger.exception(f"停止自動刷新時取消 after 失敗（視窗可能已關閉）: {e}")
            self._auto_refresh_id = None

    def safe_update_widget(self, widget_name: str, update_func: Callable, *args, **kwargs) -> None:
        """安全地更新 widget，檢查 widget 是否存在
        Safely update widget, checking if widget exists
        """
        try:
            if hasattr(self, widget_name):
                widget = getattr(self, widget_name)
                UIUtils.safe_update_widget(widget, update_func, *args, **kwargs)
        except Exception as e:
            logger.error(f"更新 {widget_name} 失敗: {e}\n{traceback.format_exc()}")

    def safe_config_widget(self, widget_name: str, **config) -> None:
        """安全地配置 widget
        Safely configure widget
        """
        self.safe_update_widget(widget_name, lambda w, **cfg: w.configure(**cfg), **config)

    def create_window(self) -> None:
        """創建監控視窗
        Create monitor window
        """
        self.window = tk.Toplevel(self.parent)
        self.window.withdraw()  # 先隱藏
        self.window.title(f"伺服器監控 - {self.server_name}")
        self.window.state("normal")

        base_width = 1000
        base_height = 950

        scale = font_manager.get_scale_factor()
        physical_min_width = int(base_width * scale)
        physical_min_height = int(base_height * scale)

        self.window.minsize(physical_min_width, physical_min_height)
        self.window.resizable(True, True)

        UIUtils.setup_window_properties(
            window=self.window,
            parent=self.parent,
            width=base_width,
            height=base_height,
            bind_icon=True,
            center_on_parent=False,
            make_modal=False,
            delay_ms=250,
        )
        self.window.deiconify()  # 顯示

        self.window.protocol("WM_DELETE_WINDOW", self.on_closing)

        main_frame = ctk.CTkFrame(self.window)
        pack_main_frame(main_frame)

        self.create_control_panel(main_frame)
        self.create_console_panel(main_frame)

        self.window.update_idletasks()
        try:
            current_width = self.window.winfo_width()
            current_height = self.window.winfo_height()

            final_width = max(current_width, physical_min_width)
            final_height = max(current_height, physical_min_height)

            x = 0
            y = 0

            screen_info = WindowManager.get_screen_info(self.window)

            if self.parent and self.parent.winfo_exists():
                # 相對於父視窗置中
                parent_x = self.parent.winfo_rootx()
                parent_y = self.parent.winfo_rooty()
                parent_w = self.parent.winfo_width()
                parent_h = self.parent.winfo_height()

                x = parent_x + (parent_w - final_width) // 2
                y = parent_y + (parent_h - final_height) // 2
            else:
                # 螢幕置中
                x = (screen_info["width"] - final_width) // 2
                y = (screen_info["usable_height"] - final_height) // 2

            # 確保視窗不會超出螢幕邊界或變成負座標
            x = max(0, min(x, screen_info["width"] - final_width))
            y = max(0, min(y, screen_info["height"] - final_height))

            # 應用最終幾何設定
            self.window.geometry(f"{final_width}x{final_height}+{int(x)}+{int(y)}")
            logger.debug(f"監控視窗最終設定: {final_width}x{final_height}+{int(x)}+{int(y)}")

        except Exception as e:
            logger.error(f"視窗置中失敗: {e}\n{traceback.format_exc()}")

    def create_control_panel(self, parent) -> None:
        """創建控制面板
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
            button_frame,
            text="🚀 啟動",
            command=self.start_server,
            state="disabled",
            font=get_font(size=18),
            width=80,
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
            button_frame,
            text="🔄 刷新",
            command=self.refresh_status,
            font=get_font(size=18),
            width=80,
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

        self.uptime_label = ctk.CTkLabel(
            middle_frame,
            text="⏱️ 運行時間: 00:00:00",
            font=get_font(size=18),
            anchor="w",
        )
        self.uptime_label.pack(anchor="w", pady=2)

        self.players_label = ctk.CTkLabel(middle_frame, text="👥 玩家數量: 0/20", font=get_font(size=18), anchor="w")
        self.players_label.pack(anchor="w", pady=2)

        self.version_label = ctk.CTkLabel(right_frame, text="📦 版本: N/A", font=get_font(size=18), anchor="w")
        logger.debug("初始化 ServerMonitorWindow，預設版本顯示 N/A")
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
        self.players_listbox.bind("<ButtonRelease-1>", self._on_player_click)

    def _on_player_click(self, _event) -> None:
        """點擊玩家列表時複製名稱"""
        try:
            selection = self.players_listbox.curselection()
            if not selection:
                return

            index = selection[0]
            name = self.players_listbox.get(index)

            # 排除無效名稱或提示訊息
            if not name or "無玩家在線" in name:
                return

            if self.window:
                self.window.clipboard_clear()
                self.window.clipboard_append(name)
                self.window.update()  # 確保剪貼簿更新生效
            logger.info(f"已複製玩家名稱: {name}")
        except Exception as e:
            logger.error(f"複製玩家名稱失敗: {e}")

    def create_console_panel(self, parent) -> None:
        """創建控制台面板
        Create console panel with black background and green text
        """
        console_frame = ctk.CTkFrame(parent)
        console_frame.pack(fill="both", expand=True)

        # 標題標籤
        console_title_label = ctk.CTkLabel(
            console_frame,
            text="📜 控制台輸出",
            font=get_font(size=21, weight="bold"),  # 21px
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
        self.command_entry.bind("<Up>", self._on_history_up)
        self.command_entry.bind("<Down>", self._on_history_down)

        self.send_button = ctk.CTkButton(
            command_frame,
            text="發送",
            command=self.send_command,
            state="disabled",
            font=get_font(size=18),
            width=80,
        )
        self.send_button.pack(side="right")

    def start_console_flusher(self) -> None:
        """啟動控制台訊息緩衝區刷新器"""

        def _flush():
            if self._console_buffer:
                try:
                    if (
                        self.window
                        and self.window.winfo_exists()
                        and hasattr(self, "console_text")
                        and self.console_text.winfo_exists()
                    ):
                        # 合併訊息
                        text = "".join(self._console_buffer)
                        self._console_buffer = []

                        self.console_text.insert("end", text)
                        self.console_text.see("end")
                except Exception as e:
                    logger.error(
                        f"刷新控制台失敗: {e}\n{traceback.format_exc()}",
                        "ServerMonitorWindow",
                    )

            if self.window and self.window.winfo_exists():
                job_id: str = self.window.after(100, _flush)
                self._console_flush_job = job_id
            else:
                self._console_flush_job = None

        _flush()

    def start_monitoring(self) -> None:
        """開始監控，啟動時自動讀取現有日誌內容，避免橫幅遺漏
        Start monitoring and automatically read existing log content to avoid banner omission
        """
        if not self.is_monitoring:
            self._monitor_stop_event.clear()
            self.is_monitoring = True
            # 啟動時先讀取現有日誌內容
            if self.window:
                self.window.after(0, self.refresh_status)
            # 啟動每秒自動刷新
            self.start_auto_refresh()
            # 使用線程池執行監控任務
            self.monitor_future = self.executor.submit(self.monitor_loop)

    def stop_monitoring(self) -> None:
        """停止監控
        Stop monitoring
        """
        self.is_monitoring = False
        self._monitor_stop_event.set()
        self.stop_auto_refresh()

        if self._console_flush_job:
            try:
                if self.window:
                    self.window.after_cancel(self._console_flush_job)
            except Exception as e:
                logger.exception(
                    f"停止監控時取消 console flush job 失敗（視窗可能已關閉）: {e}",
                    "ServerMonitorWindow",
                    e,
                )
            self._console_flush_job = None

        # 關閉線程池
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=False)
        # 等待監控線程結束
        if hasattr(self, "monitor_future"):
            try:
                self.monitor_future.result(timeout=1)
            except Exception as e:
                logger.exception(
                    f"等待監控 future 結束超時/失敗（忽略）: {e}",
                    "ServerMonitorWindow",
                    e,
                )
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=1)

    def monitor_loop(self) -> None:
        """改良的監控循環
        Improved monitoring loop
        """
        last_output_check = 0.0
        last_status_update = 0.0
        # 記錄上次日誌檔案修改時間，用於檢測新輸出
        last_log_mtime = 0

        while self.is_monitoring and not self._monitor_stop_event.is_set():
            try:
                current_time = time.monotonic()
                # 每 1.5 秒更新一次狀態信息
                if current_time - last_status_update >= 1.5:
                    if self.window and self.window.winfo_exists():
                        self.ui_queue.put(self.update_status)
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
                    except Exception as e:
                        logger.debug(
                            f"檢查日誌檔案變更時發生例外（忽略）: {e}",
                            "ServerMonitorWindow",
                        )
                    last_output_check = current_time

                # 適度休眠，減少 CPU 使用
                self._monitor_stop_event.wait(0.1)
            except Exception as e:
                logger.error(
                    f"監控更新錯誤: {e}\n{traceback.format_exc()}",
                    "ServerMonitorWindow",
                )
                self._monitor_stop_event.wait(0.5)

    def read_server_output(self) -> None:
        """讀取伺服器輸出並顯示在控制台，並即時解析玩家數量/名單與啟動完成通知
        Read server output and display it in the console, and parse player count/list and startup completion notification in real-time
        """
        try:
            output_lines = self.server_manager.read_server_output(self.server_name, _timeout=0.1)
            for line in output_lines:
                if line.strip():  # 只顯示非空行
                    # 控制台輸出：每行只排一個 UI 任務
                    def _add_line(msg: str = line) -> None:
                        self.add_console_message(msg)

                    self.ui_queue.put(_add_line)

                    # 玩家加入/離開：背景執行緒直接觸發 list 指令（避免 UI thread 多工排程）
                    if "joined the game" in line or "left the game" in line:
                        self.update_player_count()

                    # 伺服器啟動完成
                    if ("Done (" in line and "For help, type" in line) or "Server started" in line:
                        self.ui_queue.put(self.handle_server_ready)

                    # 即時解析玩家數量與名單（只排一次 UI 更新）
                    idx = line.find("There are ")
                    if idx != -1:
                        player_line = line[idx:]
                        m = re.search(
                            r"There are (\d+) of a max of (\d+) players online:? ?(.*)",
                            player_line,
                        )
                        if m:
                            current_players = int(m.group(1))
                            max_players = int(m.group(2))
                            players_str = (m.group(3) or "").strip()
                            if players_str:
                                player_names = tuple(
                                    name.strip() for name in players_str.split(",") if name and name.strip()
                                )
                            else:
                                player_names = ()

                            def _apply_players():
                                self._last_player_count = current_players
                                self._last_max_players = max_players
                                try:
                                    if hasattr(self, "players_label") and self.players_label.winfo_exists():
                                        self.players_label.configure(
                                            text=f"👥 玩家數量: {current_players}/{max_players}",
                                        )
                                except Exception:
                                    logger.error(
                                        "更新玩家數量 label 失敗（可能視窗已關閉）",
                                        "ServerMonitorWindow",
                                    )
                                self.update_player_list(list(player_names))

                            self.ui_queue.put(_apply_players)
        except Exception as e:
            logger.error(
                f"讀取伺服器輸出錯誤: {e}\n{traceback.format_exc()}",
                "ServerMonitorWindow",
            )

    def _update_ui(self, info) -> None:
        """根據 info 更新 UI 狀態顯示
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

            # 狀態標籤
            if hasattr(self, "status_label") and self.status_label.winfo_exists():
                status_text, status_color = ServerOperations.get_status_text(is_running)
                if self._last_ui_state.get("status_text") != status_text:
                    self.status_label.configure(text=status_text, text_color=status_color)
                    self._last_ui_state["status_text"] = status_text

            # PID
            pid_text = f"🆔 PID: {pid}"
            if self._last_ui_state.get("pid_text") != pid_text:
                self.safe_config_widget("pid_label", text=pid_text)
                self._last_ui_state["pid_text"] = pid_text

            # 記憶體
            memory_bytes = memory * 1024 * 1024
            mem_str = MemoryUtils.format_memory(memory_bytes)
            mem_text = f"🧠 記憶體使用: {mem_str}"
            if self._last_ui_state.get("mem_text") != mem_text:
                self.safe_config_widget("memory_label", text=mem_text)
                self._last_ui_state["mem_text"] = mem_text

            # 運行時間
            uptime_text = f"⏱️ 運行時間: {uptime}"
            if self._last_ui_state.get("uptime_text") != uptime_text:
                self.safe_config_widget("uptime_label", text=uptime_text)
                self._last_ui_state["uptime_text"] = uptime_text

            # 玩家數量
            if not is_running:
                players_text = "👥 玩家數量: 0/0"
                if self._last_ui_state.get("players_text") != players_text:
                    self._last_player_count = None
                    self._last_max_players = None
                    self.safe_config_widget("players_label", text=players_text)
                    self.safe_update_widget(
                        "players_listbox",
                        lambda w: [w.delete(0, tk.END), w.insert(tk.END, "無玩家在線")],
                    )
                    self._last_ui_state["players_text"] = players_text
            else:
                if self._last_player_count is not None and self._last_max_players is not None:
                    players_text = f"👥 玩家數量: {self._last_player_count}/{self._last_max_players}"
                else:
                    players_text = f"👥 玩家數量: {players}/{max_players}"

                if self._last_ui_state.get("players_text") != players_text:
                    self.safe_config_widget("players_label", text=players_text)
                    self._last_ui_state["players_text"] = players_text

            # 版本
            version_text = f"📦 版本: {version}"
            if self._last_ui_state.get("version_text") != version_text:
                self.safe_config_widget("version_label", text=version_text)
                self._last_ui_state["version_text"] = version_text

            # 按鈕狀態
            btn_state_start = "disabled" if is_running else "normal"
            if self._last_ui_state.get("btn_state_start") != btn_state_start:
                self.safe_config_widget("start_button", state=btn_state_start)
                self._last_ui_state["btn_state_start"] = btn_state_start

            btn_state_stop = "normal" if is_running else "disabled"
            if self._last_ui_state.get("btn_state_stop") != btn_state_stop:
                self.safe_config_widget("stop_button", state=btn_state_stop)
                self.safe_config_widget("send_button", state=btn_state_stop)
                self._last_ui_state["btn_state_stop"] = btn_state_stop

        except Exception as e:
            logger.error(
                f"_update_ui 更新 UI 狀態失敗: {e}\n{traceback.format_exc()}",
                "ServerMonitorWindow",
            )

    def update_player_count(self) -> None:
        """更新玩家數量
        Update player count
        """
        try:
            success = self.server_manager.send_command(self.server_name, "list")
            if success:
                self.executor.submit(self._delayed_read_player_list)
        except Exception as e:
            logger.error(
                f"更新玩家數量錯誤: {e}\n{traceback.format_exc()}",
                "ServerMonitorWindow",
            )

    def _delayed_read_player_list(self):
        self._monitor_stop_event.wait(0.8)
        self.read_player_list()

    def read_player_list(self, line=None) -> None:
        """讀取玩家列表
        Read player list

        Args:
            line (str): 伺服器輸出行

        """
        try:
            if line is not None:
                lines = [line]
            else:
                lines = self.server_manager.read_server_output(self.server_name, _timeout=1.2)
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

                    def update_ui():
                        # 只要有 list 指令回應就更新快取與 UI（即使人數為 0）
                        self._last_player_count = int(current_players)
                        self._last_max_players = int(max_players)
                        self.players_label.configure(text=f"👥 玩家數量: {current_players}/{max_players}")
                        if players_str:
                            player_names = [name.strip() for name in players_str.split(",") if name.strip()]
                            self.update_player_list(player_names)
                        else:
                            self.update_player_list([])

                    self.ui_queue.put(update_ui)
                    found = True
                    break
            if not found:
                # 僅當真的沒抓到任何玩家列表才不動作
                pass
        except Exception as e:
            logger.error(
                f"讀取玩家列表時發生錯誤: {e}\n{traceback.format_exc()}",
                "ServerMonitorWindow",
            )
            # 不主動清空列表，避免閃爍

    def update_player_list(self, players: list) -> None:
        """更新玩家列表顯示（支援條紋交替顏色）
        Update player list display (supports alternating striped colors)

        Args:
            players (list): 玩家名稱列表

        """
        try:
            players_tuple = tuple(players or [])
            if self._last_player_names == players_tuple:
                return
            self._last_player_names = players_tuple

            self.players_listbox.delete(0, tk.END)
            is_dark = ctk.get_appearance_mode() == "Dark"
            bg_odd = "#2b2b2b" if is_dark else "#f8fafc"
            bg_even = "#363636" if is_dark else "#e2e8f0"

            if players:
                for i, player in enumerate(players):
                    if player:  # 確保玩家名稱不為空
                        self.players_listbox.insert(tk.END, player)
                        bg_color = bg_odd if i % 2 == 0 else bg_even
                        self.players_listbox.itemconfigure(i, {"bg": bg_color})
            else:
                self.players_listbox.insert(tk.END, "無玩家在線")
                self.players_listbox.itemconfigure(0, {"bg": bg_odd})
        except Exception as e:
            logger.error(
                f"更新玩家列表錯誤: {e}\n{traceback.format_exc()}",
                "ServerMonitorWindow",
            )

    def update_status(self) -> None:
        """更新狀態顯示
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
            logger.error(f"更新狀態失敗: {e}\n{traceback.format_exc()}")

    def start_server(self) -> None:
        """啟動伺服器
        Start the server
        """
        # 清空之前的控制台輸出
        self.console_text.delete("0.0", "end")

        success = self.server_manager.start_server(self.server_name, parent=self.window)
        if success:
            self.add_console_message(f"✅ 伺服器 {self.server_name} 啟動中...")
            # 立即更新狀態
            if self.window:
                self.window.after(500, self.update_status)
        else:
            self.add_console_message(f"❌ 啟動伺服器 {self.server_name} 失敗")

    def stop_server(self) -> None:
        """停止伺服器
        Stop the server
        """
        success = ServerOperations.graceful_stop_server(self.server_manager, self.server_name)
        if success:
            self.add_console_message(f"⏹️ 伺服器 {self.server_name} 停止命令已發送")
            if self.window:
                self.window.after(0, self.update_status)
            # 延遲檢查停止狀態
            if self.window:
                # 延遲檢查停止狀態
                self.window.after(2000, self.refresh_after_stop)
        else:
            self.add_console_message(f"❌ 停止伺服器 {self.server_name} 失敗")

        # 立即更新狀態
        try:
            if self.window and self.window.winfo_exists():
                self.window.after(100, self.update_status)
        except Exception as e:
            logger.error(
                f"安全 after 調用錯誤: {e}\n{traceback.format_exc()}",
                "ServerMonitorWindow",
            )

    def refresh_after_stop(self) -> None:
        """停止後刷新狀態，直到伺服器完全結束才停止輪詢
        Refresh status after stopping, polling until the server is completely stopped
        """
        if self.server_manager.is_server_running(self.server_name):
            if self.window:
                self.window.after(500, self.refresh_after_stop)
        else:
            self.refresh_status()
            self.update_status()  # 強制刷新按鈕與標籤
            self.add_console_message("✅ 伺服器已確認停止")
            self.update_player_list([])

    def refresh_status(self) -> None:
        """手動刷新狀態和控制台輸出
        Manually refresh status and console output
        """
        # 清空當前控制台內容
        self.console_text.delete("0.0", "end")

        # 玩家資訊暫存
        last_player_line = None

        # 獲取伺服器的完整日誌（一次插入，避免大量 insert 造成卡頓/撕裂）
        try:
            log_file = self.server_manager.get_server_log_file(self.server_name)
            if log_file and log_file.exists():
                with open(log_file, encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()

                out_lines = []
                for line in lines:
                    if not line.strip():
                        continue

                    # 若遇到玩家列表行，暫存
                    idx = line.find("There are ")
                    if idx != -1:
                        last_player_line = line[idx:]

                    out_lines.append(line.rstrip("\n").rstrip("\r"))

                if out_lines:
                    self.console_text.insert("end", "\n".join(out_lines) + "\n")
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
            logger.error(f"載入日誌失敗: {e}\n{traceback.format_exc()}")
            self.add_console_message(f"❌ 載入日誌失敗: {e}")

        # 更新狀態
        self.update_status()
        self.add_console_message("🔄 狀態和控制台已刷新")

    def _on_history_up(self, _event) -> None:
        """顯示上一條歷史指令"""
        if not self._command_history:
            return

        if self._history_index is None:
            self._history_index = len(self._command_history) - 1
        else:
            self._history_index = max(0, self._history_index - 1)

        self._update_command_entry_from_history()

    def _on_history_down(self, _event) -> None:
        """顯示下一條歷史指令"""
        if not self._command_history or self._history_index is None:
            return

        self._history_index += 1

        if self._history_index >= len(self._command_history):
            self._history_index = None
            if hasattr(self, "command_entry") and self.command_entry:
                self.command_entry.delete(0, "end")
        else:
            self._update_command_entry_from_history()

    def _update_command_entry_from_history(self) -> None:
        """根據目前 history_index 更新輸入框"""
        if self._history_index is not None and 0 <= self._history_index < len(self._command_history):
            cmd = self._command_history[self._history_index]
            self.command_entry.delete(0, "end")
            self.command_entry.insert(0, cmd)

    def send_command(self, _event=None) -> None:
        """發送命令到伺服器
        Send command to the server
        """
        command = self.command_entry.get().strip()
        if not command:
            return

        # 只有當命令不為空且與上一條命令不同時才加入歷史
        if not self._command_history or self._command_history[-1] != command:
            self._command_history.append(command)
        self._history_index = None

        self.command_entry.delete(0, "end")
        self.add_console_message(f"> {command}")

        # 發送命令到伺服器
        success = self.server_manager.send_command(self.server_name, command)
        if success:
            self.add_console_message(f"✅ 命令已發送: {command}")

            # 如果是停止命令，立即更新一次狀態
            if command.lower() in ["stop", "end", "exit"] and self.window:
                self.window.after(1000, self.update_status)  # 1秒後更新狀態

        else:
            self.add_console_message(f"❌ 命令發送失敗: {command}")

    def add_console_message(self, message: str) -> None:
        """添加控制台訊息 (緩衝處理)
        Add console message (buffered)
        """
        self._console_buffer.append(message + "\n")

    def on_closing(self) -> None:
        """視窗關閉時的處理
        Handle window closing
        """
        self.stop_monitoring()
        if self.window and self.window.winfo_exists():
            self.window.destroy()
        self.window = None

    def show(self) -> None:
        """顯示視窗
        Show window
        """
        if not self.window:
            self.create_window()
            UIUtils.start_ui_queue_pump(self.window, self.ui_queue)
            self.start_monitoring()
            self.start_console_flusher()
        if self.window:
            self.window.lift()
            self.window.focus_set()

    def handle_server_ready(self):
        """伺服器啟動完成後的 UI 處理
        Handle UI after server is ready
        """
        # 只做狀態刷新或顯示一次啟動完成訊息
        try:
            # 只顯示一次啟動完成訊息
            if self._server_ready_notified:
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
            UIUtils.show_info("伺服器啟動成功", msg, self.window)
            # 額外 debug log
        except Exception as e:
            logger.error(
                f"handle_server_ready 執行錯誤: {e}\n{traceback.format_exc()}",
                "ServerMonitorWindow",
            )
