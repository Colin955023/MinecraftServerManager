"""伺服器監控視窗
提供即時的伺服器狀態監控、控制台輸出和資源使用情況
Server monitor window for real-time status, console output, and resource usage.
"""

import queue
import re
import threading
import time
import tkinter as tk
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import customtkinter as ctk

from ..utils import (
    Colors,
    FontSize,
    MemoryUtils,
    ServerOperations,
    Sizes,
    Spacing,
    UIUtils,
    WindowManager,
    get_logger,
)
from . import DialogUtils, FontManager, TaskUtils, TreeUtils

logger = get_logger().bind(component="ServerMonitorWindow")


class ServerMonitorWindow:
    """伺服器監控視窗"""

    def __init__(self, parent, server_manager, server_name: str):
        self.parent = parent
        self.server_manager = server_manager
        self.server_name = server_name
        self.window: tk.Toplevel | None = None
        self._auto_refresh_id: str | None = None
        self.is_monitoring = False
        self.monitor_thread = None
        self._last_player_count: int | None = None
        self._last_max_players: int | None = None
        self._last_player_names: tuple[str, ...] | None = None
        self._history_index: int | None = None
        self._server_ready_notified: bool = False
        self._last_ui_state: dict[str, Any] = {}
        self._console_buffer: list[str] = []
        self._console_flush_job: str | None = None
        self._console_flush_interval_ms = 100
        self._refresh_log_max_lines = 2500
        self._refresh_log_max_bytes = 2 * 1024 * 1024
        self._command_history: list[str] = []
        self._monitor_stop_event = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ServerMonitor")
        self.ui_queue: queue.Queue[Callable[[], Any]] = queue.Queue()

    def start_auto_refresh(self) -> None:
        """啟動每秒自動刷新狀態（共用排程 helper）。"""
        if self._auto_refresh_id:
            return
        self._schedule_auto_refresh_tick(delay_ms=1000)

    def _schedule_auto_refresh_tick(self, delay_ms: int = 1000) -> None:
        """排程下一次狀態刷新；只保留一個待執行工作。"""
        if not self.window or not self.window.winfo_exists():
            self._auto_refresh_id = None
            return

        def _refresh_once() -> None:
            self._auto_refresh_id = None
            if not self.window or not self.window.winfo_exists():
                return
            self.update_status()
            self._schedule_auto_refresh_tick(delay_ms=1000)

        UIUtils.schedule_debounce(self.window, "_auto_refresh_id", max(1, int(delay_ms)), _refresh_once, owner=self)

    def stop_auto_refresh(self) -> None:
        """停止自動刷新狀態。"""
        if self.window and self.window.winfo_exists():
            UIUtils.cancel_scheduled_job(self.window, "_auto_refresh_id", owner=self)
        else:
            self._auto_refresh_id = None

    def _schedule_window_job(self, job_attr: str, delay_ms: int, callback: Callable[[], Any]) -> None:
        """統一視窗 after 排程，避免同類任務重複排入。"""
        if not self.window or not self.window.winfo_exists():
            setattr(self, job_attr, None)
            return
        UIUtils.schedule_debounce(self.window, job_attr, max(0, int(delay_ms)), callback, owner=self)

    def _cancel_window_jobs(self) -> None:
        """取消 monitor window 內部短延遲排程。"""
        job_attrs = (
            "_monitor_start_refresh_job",
            "_start_status_job",
            "_stop_status_job",
            "_stop_refresh_after_job",
            "_command_status_job",
        )
        if not self.window or not self.window.winfo_exists():
            for job_attr in job_attrs:
                setattr(self, job_attr, None)
            return
        for job_attr in job_attrs:
            UIUtils.cancel_scheduled_job(self.window, job_attr, owner=self)

    def safe_update_widget(self, widget_name: str, update_func: Callable, *args, **kwargs) -> None:
        """安全地更新 widget，檢查 widget 是否存在。

        Args:
            widget_name: 目標 widget 的屬性名稱。
            update_func: 更新函式。
            *args: 傳遞給更新函式的額外位置參數。
            **kwargs: 傳遞給更新函式的額外關鍵字參數。
        """
        try:
            if hasattr(self, widget_name):
                widget = getattr(self, widget_name)
                TaskUtils.safe_update_widget(widget, update_func, *args, **kwargs)
        except Exception as e:
            logger.error(f"更新 {widget_name} 失敗: {e}\n{traceback.format_exc()}")

    def safe_config_widget(self, widget_name: str, **config) -> None:
        """安全地配置 widget。

        Args:
            widget_name: 目標 widget 的屬性名稱。
            **config: 要套用的 widget 設定。
        """
        self.safe_update_widget(widget_name, lambda w, **cfg: w.configure(**cfg), **config)

    def create_window(self) -> None:
        """創建監控視窗"""
        self.window = DialogUtils.create_toplevel_dialog(
            self.parent,
            f"伺服器監控 - {self.server_name}",
            width=Sizes.DIALOG_LARGE_WIDTH,
            height=Sizes.DIALOG_LARGE_HEIGHT,
            native_window=True,
            center_on_parent=False,
            make_modal=False,
            delay_ms=250,
        )
        self.window.state("normal")
        base_width = 1000
        base_height = 950
        scale = FontManager.get_scale_factor()
        physical_min_width = int(base_width * scale)
        physical_min_height = int(base_height * scale)
        self.window.minsize(physical_min_width, physical_min_height)
        self.window.resizable(True, True)
        self.window.protocol("WM_DELETE_WINDOW", self.on_closing)
        main_frame = ctk.CTkFrame(self.window)
        UIUtils.pack_main_frame(main_frame)
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
                parent_x = self.parent.winfo_rootx()
                parent_y = self.parent.winfo_rooty()
                parent_w = self.parent.winfo_width()
                parent_h = self.parent.winfo_height()
                x = parent_x + (parent_w - final_width) // 2
                y = parent_y + (parent_h - final_height) // 2
            else:
                x = (screen_info["width"] - final_width) // 2
                y = (screen_info["usable_height"] - final_height) // 2
            x = max(0, min(x, screen_info["width"] - final_width))
            y = max(0, min(y, screen_info["height"] - final_height))
            self.window.geometry(f"{final_width}x{final_height}+{int(x)}+{int(y)}")
            logger.debug(f"監控視窗最終設定: {final_width}x{final_height}+{int(x)}+{int(y)}")
        except Exception as e:
            logger.error(f"視窗置中失敗: {e}\n{traceback.format_exc()}")
        finally:
            try:
                self.window.deiconify()
                self.window.lift()
                self.window.focus_set()
            except Exception as e:
                logger.debug(f"顯示監控視窗失敗: {e}", "ServerMonitorWindow")

    def create_control_panel(self, parent) -> None:
        """創建控制面板。

        Args:
            parent: 父容器。
        """
        control_frame = ctk.CTkFrame(parent)
        control_frame.pack(fill="x", pady=(0, int(10 * FontManager.get_scale_factor())))
        title_label = ctk.CTkLabel(
            control_frame, text="🎮 伺服器控制", font=FontManager.get_font(size=FontSize.HEADING_MEDIUM, weight="bold")
        )
        title_label.pack(pady=(FontManager.get_dpi_scaled_size(15), FontManager.get_dpi_scaled_size(8)))
        status_text, status_color = ServerOperations.get_status_text(False)
        self.status_label = ctk.CTkLabel(
            control_frame,
            text=status_text,
            font=FontManager.get_font(size=FontSize.HEADING_SMALL, weight="bold"),
            text_color=status_color if status_color != "red" else Colors.TEXT_ERROR,
        )
        self.status_label.pack(side="left", padx=FontManager.get_dpi_scaled_size(15))
        button_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        button_frame.pack(side="right", padx=Spacing.SMALL_PLUS)
        self.start_button = ctk.CTkButton(
            button_frame,
            text="🚀 啟動",
            command=self.start_server,
            state="disabled",
            font=FontManager.get_font(size=FontSize.LARGE),
            width=Sizes.BUTTON_WIDTH_COMPACT,
        )
        self.start_button.pack(side="left", padx=(0, Spacing.TINY))
        self.stop_button = ctk.CTkButton(
            button_frame,
            text="⏹️ 停止",
            command=self.stop_server,
            state="disabled",
            font=FontManager.get_font(size=FontSize.LARGE),
            width=Sizes.BUTTON_WIDTH_COMPACT,
            fg_color=Colors.BUTTON_DANGER,
            hover_color=Colors.BUTTON_DANGER_HOVER,
        )
        self.stop_button.pack(side="left", padx=(0, Spacing.TINY))
        self.refresh_button = ctk.CTkButton(
            button_frame,
            text="🔄 刷新",
            command=self.refresh_status,
            font=FontManager.get_font(size=FontSize.LARGE),
            width=Sizes.BUTTON_WIDTH_COMPACT,
        )
        self.refresh_button.pack(side="left")
        status_frame = ctk.CTkFrame(parent)
        status_frame.pack(fill="x", pady=(0, Spacing.SMALL_PLUS))
        status_title_label = ctk.CTkLabel(
            status_frame, text="📈 系統資源", font=FontManager.get_font(size=FontSize.HEADING_MEDIUM, weight="bold")
        )
        status_title_label.pack(pady=(Spacing.SMALL_PLUS, Spacing.TINY))
        status_content_frame = ctk.CTkFrame(status_frame, fg_color="transparent")
        status_content_frame.pack(fill="x", padx=Spacing.SMALL_PLUS, pady=Spacing.SMALL_PLUS)
        left_frame = ctk.CTkFrame(status_content_frame, fg_color="transparent")
        left_frame.pack(side="left", fill="both", expand=True)
        middle_frame = ctk.CTkFrame(status_content_frame, fg_color="transparent")
        middle_frame.pack(side="left", fill="both", expand=True)
        right_frame = ctk.CTkFrame(status_content_frame, fg_color="transparent")
        right_frame.pack(side="right", fill="both", expand=True)
        self.pid_label = ctk.CTkLabel(
            left_frame, text="🆔 PID: N/A", font=FontManager.get_font(size=FontSize.LARGE), anchor="w"
        )
        self.pid_label.pack(anchor="w", pady=Spacing.XS)
        self.memory_label = ctk.CTkLabel(
            left_frame, text="🧠 記憶體使用: 0 MB", font=FontManager.get_font(size=FontSize.LARGE), anchor="w"
        )
        self.memory_label.pack(anchor="w", pady=Spacing.XS)
        self.uptime_label = ctk.CTkLabel(
            middle_frame, text="⏱️ 運行時間: 00:00:00", font=FontManager.get_font(size=FontSize.LARGE), anchor="w"
        )
        self.uptime_label.pack(anchor="w", pady=Spacing.XS)
        self.players_label = ctk.CTkLabel(
            middle_frame, text="👥 玩家數量: 0/20", font=FontManager.get_font(size=FontSize.LARGE), anchor="w"
        )
        self.players_label.pack(anchor="w", pady=Spacing.XS)
        self.version_label = ctk.CTkLabel(
            right_frame, text="📦 版本: N/A", font=FontManager.get_font(size=FontSize.LARGE), anchor="w"
        )
        logger.debug("初始化 ServerMonitorWindow，預設版本顯示 N/A")
        self.version_label.pack(anchor="w", pady=Spacing.XS)
        players_frame = ctk.CTkFrame(parent)
        players_frame.pack(fill="x", pady=(0, Spacing.SMALL_PLUS))
        players_title_label = ctk.CTkLabel(
            players_frame, text="👥 線上玩家", font=FontManager.get_font(size=FontSize.HEADING_MEDIUM, weight="bold")
        )
        players_title_label.pack(pady=(Spacing.SMALL_PLUS, Spacing.TINY))
        self.players_listbox = tk.Listbox(
            players_frame,
            height=Spacing.TINY,
            font=FontManager.get_font("Microsoft JhengHei", FontSize.LARGE),
            bg=Colors.BG_LISTBOX_DARK if ctk.get_appearance_mode() == "Dark" else Colors.BG_LISTBOX_LIGHT,
            fg=Colors.TEXT_ON_DARK if ctk.get_appearance_mode() == "Dark" else Colors.TEXT_ON_LIGHT,
            selectbackground=Colors.SELECT_BG,
            selectforeground=Colors.TEXT_ON_DARK,
            borderwidth=0,
            highlightthickness=0,
        )
        self.players_listbox.pack(fill="x", padx=Spacing.SMALL_PLUS, pady=(0, Spacing.SMALL_PLUS))
        self.players_listbox.insert(tk.END, "無玩家在線")
        TreeUtils.apply_listbox_alternating_rows(self.players_listbox, item_count=1)
        self.players_listbox.bind("<ButtonRelease-1>", self._on_player_click)

    def _on_player_click(self, _event) -> None:
        """點擊玩家列表時複製名稱"""
        try:
            selection = self.players_listbox.curselection()
            if not selection:
                return
            index = selection[0]
            name = self.players_listbox.get(index)
            if not name or "無玩家在線" in name:
                return
            if self.window:
                self.window.clipboard_clear()
                self.window.clipboard_append(name)
                self.window.update_idletasks()
            logger.info(f"已複製玩家名稱: {name}")
        except Exception as e:
            logger.error(f"複製玩家名稱失敗: {e}")

    def create_console_panel(self, parent) -> None:
        """創建控制台面板。

        Args:
            parent: 父容器。
        """
        console_frame = ctk.CTkFrame(parent)
        console_frame.pack(fill="both", expand=True)
        console_title_label = ctk.CTkLabel(
            console_frame, text="📜 控制台輸出", font=FontManager.get_font(size=FontSize.HEADING_MEDIUM, weight="bold")
        )
        console_title_label.pack(pady=(Spacing.SMALL_PLUS, Spacing.TINY))
        self.console_text = ctk.CTkTextbox(
            console_frame,
            height=Sizes.CONSOLE_PANEL_HEIGHT,
            font=FontManager.get_font(family="Consolas", size=FontSize.NORMAL_PLUS),
            wrap="word",
            fg_color=Colors.BG_CONSOLE,
            text_color=Colors.CONSOLE_TEXT,
            scrollbar_button_color=Colors.SCROLLBAR_BUTTON,
            scrollbar_button_hover_color=Colors.SCROLLBAR_BUTTON_HOVER,
        )
        self.console_text.pack(fill="both", expand=True, padx=FontManager.get_dpi_scaled_size(15))
        command_frame = ctk.CTkFrame(console_frame, fg_color="transparent")
        command_frame.pack(fill="x", padx=FontManager.get_dpi_scaled_size(15), pady=(Spacing.TINY, Spacing.SMALL_PLUS))
        command_label = ctk.CTkLabel(command_frame, text="命令:", font=FontManager.get_font(size=FontSize.LARGE))
        command_label.pack(side="left", padx=(0, Spacing.SMALL_PLUS))
        self.command_entry = ctk.CTkEntry(
            command_frame,
            font=FontManager.get_font(family="Consolas", size=FontSize.MEDIUM),
            placeholder_text="輸入指令...",
        )
        self.command_entry.pack(side="left", fill="x", expand=True, padx=(0, Spacing.SMALL_PLUS))
        self.command_entry.bind("<Return>", self.send_command)
        self.command_entry.bind("<Up>", self._on_history_up)
        self.command_entry.bind("<Down>", self._on_history_down)
        self.send_button = ctk.CTkButton(
            command_frame,
            text="發送",
            command=self.send_command,
            state="disabled",
            font=FontManager.get_font(size=FontSize.LARGE),
            width=Sizes.BUTTON_WIDTH_COMPACT,
        )
        self.send_button.pack(side="right")

    def start_console_flusher(self) -> None:
        """啟動控制台訊息緩衝區刷新器（節流 + 合併）。"""
        self._schedule_console_flush(force=True)

    def _flush_console_buffer(self) -> None:
        """將緩衝區訊息批次寫入控制台。"""
        if not self._console_buffer:
            return
        try:
            if (
                self.window
                and self.window.winfo_exists()
                and hasattr(self, "console_text")
                and self.console_text.winfo_exists()
            ):
                text = "".join(self._console_buffer)
                self._console_buffer = []
                self.console_text.insert("end", text)
                self.console_text.see("end")
        except Exception as e:
            logger.error(f"刷新控制台失敗: {e}\n{traceback.format_exc()}", "ServerMonitorWindow")

    def _schedule_console_flush(self, *, force: bool = False) -> None:
        """排程控制台刷新；高頻輸入時以 throttle 合併更新。"""
        if not self.window or not self.window.winfo_exists():
            return
        interval = max(1, int(getattr(self, "_console_flush_interval_ms", 100)))
        if force:
            UIUtils.schedule_debounce(self.window, "_console_flush_job", 0, self._flush_console_buffer, owner=self)
            return
        UIUtils.schedule_throttle(
            self.window,
            "_console_flush_job",
            interval,
            self._flush_console_buffer,
            owner=self,
            trailing=True,
            last_run_attr="_console_flush_last_run_ms",
        )

    def start_monitoring(self) -> None:
        """開始監控，啟動時自動讀取現有日誌內容，避免橫幅遺漏"""
        if not self.is_monitoring:
            self._monitor_stop_event.clear()
            self.is_monitoring = True
            self._schedule_window_job("_monitor_start_refresh_job", 0, self.refresh_status)
            self.start_auto_refresh()
            self.monitor_future = self.executor.submit(self.monitor_loop)

    def stop_monitoring(self) -> None:
        """停止監控"""
        self.is_monitoring = False
        self._monitor_stop_event.set()
        self.stop_auto_refresh()
        if self.window:
            UIUtils.cancel_scheduled_job(self.window, "_console_flush_job", owner=self)
        self._cancel_window_jobs()
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=False)
        if hasattr(self, "monitor_future"):
            try:
                self.monitor_future.result(timeout=1)
            except Exception as e:
                logger.exception(f"等待監控 future 結束超時/失敗（忽略）: {e}", "ServerMonitorWindow", e)
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=1)

    def monitor_loop(self) -> None:
        """改良的監控循環"""
        last_output_check = 0.0
        last_status_update = 0.0
        last_log_mtime = 0
        while self.is_monitoring and (not self._monitor_stop_event.is_set()):
            try:
                current_time = time.monotonic()
                if current_time - last_status_update >= 1.5:
                    if self.window and self.window.winfo_exists():
                        self.ui_queue.put(self.update_status)
                    last_status_update = current_time
                if current_time - last_output_check >= 0.1:
                    try:
                        self.read_server_output()
                    except Exception as e:
                        logger.debug(f"從輸出隊列讀取失敗（忽略）: {e}", "ServerMonitorWindow")
                    try:
                        log_file = self.server_manager.get_server_log_file(self.server_name)
                        if log_file and log_file.exists():
                            current_mtime = log_file.stat().st_mtime
                            if current_mtime > last_log_mtime:
                                last_log_mtime = current_mtime
                    except Exception as e:
                        logger.debug(f"檢查日誌檔案變更時發生例外（忽略）: {e}", "ServerMonitorWindow")
                    last_output_check = current_time
                self._monitor_stop_event.wait(0.1)
            except Exception as e:
                logger.error(f"監控更新錯誤: {e}\n{traceback.format_exc()}", "ServerMonitorWindow")
                self._monitor_stop_event.wait(0.5)

    def read_server_output(self) -> None:
        """讀取伺服器輸出並顯示在控制台，並即時解析玩家數量/名單與啟動完成通知"""
        try:
            output_lines = self.server_manager.read_server_output(self.server_name, _timeout=0.1)
            for line in output_lines:
                if line.strip():

                    def _add_line(msg: str = line) -> None:
                        self.add_console_message(msg)

                    self.ui_queue.put(_add_line)
                    if "joined the game" in line or "left the game" in line:
                        self.update_player_count()
                    if ("Done (" in line and "For help, type" in line) or "Server started" in line:
                        self.ui_queue.put(self.handle_server_ready)
                    idx = line.find("There are ")
                    if idx != -1:
                        player_line = line[idx:]
                        m = re.search("There are (\\d+) of a max of (\\d+) players online:? ?(.*)", player_line)
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
                                            text=f"👥 玩家數量: {current_players}/{max_players}"
                                        )
                                except Exception:
                                    logger.error("更新玩家數量 label 失敗（可能視窗已關閉）", "ServerMonitorWindow")
                                self.update_player_list(list(player_names))

                            self.ui_queue.put(_apply_players)
        except Exception as e:
            logger.error(f"讀取伺服器輸出錯誤: {e}\n{traceback.format_exc()}", "ServerMonitorWindow")

    def _update_ui(self, info) -> None:
        """根據 info 更新 UI 狀態顯示"""
        try:
            is_running = info.get("is_running", False)
            pid = info.get("pid", "N/A")
            memory = info.get("memory", 0)
            uptime = info.get("uptime", "00:00:00")
            players = info.get("players", 0)
            max_players = info.get("max_players", 0)
            version = info.get("version", "N/A")
            if hasattr(self, "status_label") and self.status_label.winfo_exists():
                status_text, status_color = ServerOperations.get_status_text(is_running)
                if self._last_ui_state.get("status_text") != status_text:
                    self.status_label.configure(text=status_text, text_color=status_color)
                    self._last_ui_state["status_text"] = status_text
            pid_text = f"🆔 PID: {pid}"
            if self._last_ui_state.get("pid_text") != pid_text:
                self.safe_config_widget("pid_label", text=pid_text)
                self._last_ui_state["pid_text"] = pid_text
            mem_str = MemoryUtils.format_memory_mb(memory, compact=False)
            mem_text = f"🧠 記憶體使用: {mem_str}"
            if self._last_ui_state.get("mem_text") != mem_text:
                self.safe_config_widget("memory_label", text=mem_text)
                self._last_ui_state["mem_text"] = mem_text
            uptime_text = f"⏱️ 運行時間: {uptime}"
            if self._last_ui_state.get("uptime_text") != uptime_text:
                self.safe_config_widget("uptime_label", text=uptime_text)
                self._last_ui_state["uptime_text"] = uptime_text
            if not is_running:
                players_text = "👥 玩家數量: 0/0"
                if self._last_ui_state.get("players_text") != players_text:
                    self._last_player_count = None
                    self._last_max_players = None
                    self.safe_config_widget("players_label", text=players_text)
                    self.safe_update_widget(
                        "players_listbox",
                        lambda w: [
                            w.delete(0, tk.END),
                            w.insert(tk.END, "無玩家在線"),
                            TreeUtils.apply_listbox_alternating_rows(w, item_count=1),
                        ],
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
            version_text = f"📦 版本: {version}"
            if self._last_ui_state.get("version_text") != version_text:
                self.safe_config_widget("version_label", text=version_text)
                self._last_ui_state["version_text"] = version_text
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
            logger.error(f"_update_ui 更新 UI 狀態失敗: {e}\n{traceback.format_exc()}", "ServerMonitorWindow")

    def update_player_count(self) -> None:
        """更新玩家數量"""
        try:
            success = self.server_manager.send_command(self.server_name, "list")
            if success:
                self.executor.submit(self._delayed_read_player_list)
        except Exception as e:
            logger.error(f"更新玩家數量錯誤: {e}\n{traceback.format_exc()}", "ServerMonitorWindow")

    def _delayed_read_player_list(self):
        self._monitor_stop_event.wait(0.8)
        self.read_player_list()

    def read_player_list(self, line=None) -> None:
        """讀取玩家列表。

        Args:
            line: 可選的單行玩家統計字串。
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
                m = re.search("There are (\\d+) of a max of (\\d+) players online:? ?(.*)", line)
                if m:
                    current_players = m.group(1)
                    max_players = m.group(2)
                    players_str = m.group(3).strip()

                    def update_ui():
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
                pass
        except Exception as e:
            logger.error(f"讀取玩家列表時發生錯誤: {e}\n{traceback.format_exc()}", "ServerMonitorWindow")

    def update_player_list(self, players: list) -> None:
        """更新玩家列表顯示（支援條紋交替顏色）。

        Args:
            players: 玩家名稱清單。
        """
        try:
            players_tuple = tuple(players or [])
            if self._last_player_names == players_tuple:
                return
            self._last_player_names = players_tuple
            self.players_listbox.delete(0, tk.END)
            if players:
                for player in players:
                    if player:
                        self.players_listbox.insert(tk.END, player)
            else:
                self.players_listbox.insert(tk.END, "無玩家在線")
            TreeUtils.apply_listbox_alternating_rows(self.players_listbox, item_count=self.players_listbox.size())
        except Exception as e:
            logger.error(f"更新玩家列表錯誤: {e}\n{traceback.format_exc()}", "ServerMonitorWindow")

    def update_status(self) -> None:
        """更新狀態顯示"""
        try:
            if not self.window or not self.window.winfo_exists():
                return
            info = self.server_manager.get_server_info(self.server_name)
            if not info:
                return
            self._update_ui(info)
        except Exception as e:
            logger.error(f"更新狀態失敗: {e}\n{traceback.format_exc()}")

    def start_server(self) -> None:
        """啟動伺服器"""
        self.console_text.delete("0.0", "end")
        success = self.server_manager.start_server(self.server_name, parent=self.window)
        if success:
            self.add_console_message(f"✅ 伺服器 {self.server_name} 啟動中...")
            self._schedule_window_job("_start_status_job", 500, self.update_status)
            if not self.is_monitoring:
                self.start_monitoring()
        else:
            self.add_console_message(f"❌ 啟動伺服器 {self.server_name} 失敗")

    def stop_server(self) -> None:
        """停止伺服器"""
        success = ServerOperations.graceful_stop_server(self.server_manager, self.server_name)
        if success:
            self.add_console_message(f"⏹️ 伺服器 {self.server_name} 停止命令已發送")
            self._schedule_window_job("_stop_refresh_after_job", 2000, self.refresh_after_stop)
        else:
            self.add_console_message(f"❌ 停止伺服器 {self.server_name} 失敗")
        self._schedule_window_job("_stop_status_job", 100, self.update_status)

    def refresh_after_stop(self) -> None:
        """停止後刷新狀態，直到伺服器完全結束才停止輪詢"""
        if self.server_manager.is_server_running(self.server_name):
            self._schedule_window_job("_stop_refresh_after_job", 500, self.refresh_after_stop)
        else:
            self.refresh_status()
            self.update_status()
            self.add_console_message("✅ 伺服器已確認停止")
            self.update_player_list([])

    def _read_recent_log_lines(self, log_file) -> tuple[list[str], bool]:
        """讀取日誌尾端內容，限制載入量以避免大檔案阻塞 UI。"""
        max_bytes = max(64 * 1024, int(getattr(self, "_refresh_log_max_bytes", 2 * 1024 * 1024)))
        max_lines = max(200, int(getattr(self, "_refresh_log_max_lines", 2500)))
        try:
            with log_file.open("rb") as fh:
                fh.seek(0, 2)
                file_size = fh.tell()
                read_size = min(file_size, max_bytes)
                fh.seek(max(0, file_size - read_size))
                tail_bytes = fh.read(read_size)
            tail_text = tail_bytes.decode("utf-8", errors="ignore")
            lines = tail_text.splitlines()
            if read_size < file_size and lines:
                lines = lines[1:]
            compact_lines = [line.rstrip("\n").rstrip("\r") for line in lines if line.strip()]
            truncated = read_size < file_size or len(compact_lines) > max_lines
            if len(compact_lines) > max_lines:
                compact_lines = compact_lines[-max_lines:]
            return (compact_lines, truncated)
        except Exception as e:
            logger.debug(f"尾端讀取日誌失敗，改走完整讀取: {e}", "ServerMonitorWindow")
            try:
                with log_file.open("r", encoding="utf-8", errors="ignore") as fh:
                    full_lines = [line.rstrip("\n").rstrip("\r") for line in fh if line.strip()]
                truncated = len(full_lines) > max_lines
                if truncated:
                    full_lines = full_lines[-max_lines:]
                return (full_lines, truncated)
            except Exception:
                raise

    def _find_latest_player_line(self, lines: list[str]) -> str | None:
        """從日誌片段找到最後一條玩家數量行。"""
        for line in reversed(lines):
            idx = line.find("There are ")
            if idx != -1:
                return line[idx:]
        return None

    def refresh_status(self) -> None:
        """手動刷新狀態和控制台輸出"""
        self.console_text.delete("0.0", "end")
        last_player_line = None
        try:
            log_file = self.server_manager.get_server_log_file(self.server_name)
            if log_file and log_file.exists():
                out_lines, truncated = self._read_recent_log_lines(log_file)
                last_player_line = self._find_latest_player_line(out_lines)
                if out_lines:
                    self.console_text.insert("end", "\n".join(out_lines) + "\n")
                self.console_text.see(tk.END)
                self.add_console_message("✅ 日誌載入完成")
                if truncated:
                    self.add_console_message(
                        f"ℹ️ 日誌過大，僅顯示最新 {len(out_lines)} 行（上限 {self._refresh_log_max_lines} 行）"
                    )
                if last_player_line:
                    self.read_player_list(line=last_player_line)
                else:
                    self.update_player_list([])
            else:
                self.add_console_message("⚠️ 未找到日誌檔案")
        except Exception as e:
            logger.error(f"載入日誌失敗: {e}\n{traceback.format_exc()}")
            self.add_console_message(f"❌ 載入日誌失敗: {e}")
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
        """發送命令到伺服器。

        Args:
            _event: 事件物件，供按鍵綁定使用。
        """
        command = self.command_entry.get().strip()
        if not command:
            return
        if not self._command_history or self._command_history[-1] != command:
            self._command_history.append(command)
        self._history_index = None
        self.command_entry.delete(0, "end")
        self.add_console_message(f"> {command}")
        success = self.server_manager.send_command(self.server_name, command)
        if success:
            self.add_console_message(f"✅ 命令已發送: {command}")
            if command.lower() in ["stop", "end", "exit"]:
                self._schedule_window_job("_command_status_job", 1000, self.update_status)
        else:
            self.add_console_message(f"❌ 命令發送失敗: {command}")

    def add_console_message(self, message: str) -> None:
        """添加控制台訊息（緩衝處理）。

        Args:
            message: 要加入控制台的訊息。
        """
        self._console_buffer.append(message + "\n")
        self._schedule_console_flush()

    def on_closing(self) -> None:
        """視窗關閉時的處理"""
        self.stop_monitoring()
        if self.window and self.window.winfo_exists():
            self.window.destroy()
        self.window = None

    def show(self) -> None:
        """顯示視窗"""
        if not self.window:
            self.create_window()
            TaskUtils.start_ui_queue_pump(self.window, self.ui_queue)
            self.start_monitoring()
            self.start_console_flusher()
        if self.window:
            self.window.lift()
            self.window.focus_set()

    def handle_server_ready(self):
        """伺服器啟動完成後的 UI 處理"""
        try:
            if self._server_ready_notified:
                return
            self._server_ready_notified = True
            properties = (
                self.server_manager.load_server_properties(self.server_name)
                if hasattr(self.server_manager, "load_server_properties")
                else {}
            )
            server_ip = properties.get("server-ip", "").strip()
            server_port = properties.get("server-port", "").strip()
            if not server_port:
                server_port = "25565"
            if server_ip:
                msg = f"伺服器啟動成功\n已在 {server_ip}:{server_port} 上開放"
            else:
                msg = f"伺服器啟動成功\n已在 {server_port} 埠口上開放"
            UIUtils.show_info("伺服器啟動成功", msg, self.window)
        except Exception as e:
            logger.error(f"handle_server_ready 執行錯誤: {e}\n{traceback.format_exc()}", "ServerMonitorWindow")
