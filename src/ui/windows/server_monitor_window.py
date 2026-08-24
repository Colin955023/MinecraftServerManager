"""
伺服器監控視窗
提供即時的伺服器狀態監控、控制台輸出和資源使用情況
"""

from __future__ import annotations

import queue
import re
import time
import traceback
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    LineEdit,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TextEdit,
    TitleLabel,
)

from src.ui import ModalMSFluentWindow
from src.utils import (
    Colors,
    FontSize,
    MemoryUtils,
    ServerOperations,
    Sizes,
    Spacing,
    UIUtils,
    center_window,
    get_logger,
    resolve_color,
)

logger = get_logger().bind(component="ServerMonitorWindow")


class ServerMonitorWindow(ModalMSFluentWindow):
    """伺服器監控視窗"""

    _ansi_escape_pattern = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

    @staticmethod
    def _fit_initial_size(
        current_width: int,
        current_height: int,
        available_width: int,
        available_height: int,
        requested_min_width: int = 1350,
        requested_min_height: int = 900,
    ) -> tuple[int, int, int, int]:
        """將監控視窗最小尺寸與初始尺寸限制在螢幕可用範圍內"""
        available_width = max(1, available_width)
        available_height = max(1, available_height)
        min_width = min(max(1, requested_min_width), available_width)
        min_height = min(max(1, requested_min_height), available_height)
        width = min(max(current_width, min_width), available_width)
        height = min(max(current_height, min_height), available_height)
        return min_width, min_height, width, height

    def __init__(self, parent, server_manager, server_name: str, server_crud=None):
        super().__init__(None, is_modal=False, show_buttons=False)
        self.parent = parent
        self.server_manager = server_manager
        self.server_crud = server_crud
        self.server_name = server_name
        self.window = self
        self.setParent(None)
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowCloseButtonHint
        )
        self._auto_refresh_id: int | None = None
        self.is_monitoring = False
        self._last_player_count: int | None = None
        self._last_max_players: int | None = None
        self._last_player_names: tuple[str, ...] | None = None
        self._server_ready_notified = False
        self._last_ui_state: dict[str, str] = {}
        self._console_buffer: list[str] = []
        self._console_flush_job = None
        self._console_flush_interval_ms = 100
        self._refresh_log_max_lines = 2500
        self._refresh_log_max_bytes = 2 * 1024 * 1024
        self._command_history: list[str] = []
        self._monitor_loop_job = None
        self._delayed_player_list_job = None
        self._last_monitor_status_update = 0.0
        self._last_monitor_output_check = 0.0
        self._last_log_mtime = 0.0
        self._log_file_offset: int = 0
        self._recent_lines_cache: set[str] = set()
        self.ui_queue: queue.Queue[Callable[[], Any]] = queue.Queue()
        self._ui_queue_timer = QTimer(self)
        self._ui_queue_timer.timeout.connect(self._drain_ui_queue)

    def _drain_ui_queue(self) -> None:
        for _ in range(100):
            try:
                callback = self.ui_queue.get_nowait()
            except queue.Empty:
                return
            try:
                callback()
            except Exception:
                logger.error("執行監控 UI 工作失敗\n" + traceback.format_exc())

    @classmethod
    def _clean_text(cls, line: str) -> str:
        return cls._ansi_escape_pattern.sub("", line).strip()

    @classmethod
    def _parse_player_list_line(cls, line: str) -> tuple[int, int, tuple[str, ...]] | None:
        clean = cls._clean_text(line)
        idx = clean.find("There are ")
        if idx != -1:
            clean = clean[idx:]
        match = re.search(r"There are\s+(\d+)\s+of a max of\s+(\d+)\s+players online:?\s*(.*)$", clean)
        if not match:
            return None
        current_players = int(match.group(1))
        max_players = int(match.group(2))
        players_str = (match.group(3) or "").strip()
        player_names = tuple(name.strip() for name in players_str.split(",") if name and name.strip())
        return (current_players, max_players, player_names)

    @classmethod
    def _parse_player_presence_event(cls, line: str) -> tuple[str, bool] | None:
        clean = cls._clean_text(line)
        message = clean.rsplit("]:", 1)[-1].strip() if "]:" in clean else clean
        match = re.search(r"\b([A-Za-z0-9_]{1,16}) joined the game\b", message)
        if match:
            return (match.group(1), True)
        match = re.search(r"\b([A-Za-z0-9_]{1,16}) left the game\b", message)
        if match:
            return (match.group(1), False)
        return None

    def start_auto_refresh(self) -> None:
        """啟動伺服器狀態的自動刷新機制"""
        if self._auto_refresh_id:
            return
        self._schedule_auto_refresh_tick(delay_ms=1000)

    def stop_auto_refresh(self) -> None:
        """停止伺服器狀態的自動刷新機制"""
        if self.window and self.window.isVisible():
            UIUtils.cancel_scheduled_job(self.window, "_auto_refresh_id", owner=self)
        else:
            self._auto_refresh_id = None

    def create_window(self) -> None:
        """創建伺服器監控視窗"""
        self.setWindowTitle(f"伺服器監控 - {self.server_name}")

        screen = self.screen() or QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        available_width = available.width() if available is not None else 1350
        available_height = available.height() if available is not None else 900
        physical_min_width, physical_min_height, _, _ = self._fit_initial_size(
            self.width(), self.height(), available_width, available_height
        )
        self.setMinimumSize(physical_min_width, physical_min_height)

        self.create_control_panel(self.viewLayout)
        self.create_console_panel(self.viewLayout)

        try:
            current_width = self.window.width()
            current_height = self.window.height()
            _, _, final_width, final_height = self._fit_initial_size(
                current_width, current_height, available_width, available_height
            )

            self.window.resize(final_width, final_height)
            self.update_status()
        except Exception as e:
            logger.error(f"視窗置中失敗: {e}\n{traceback.format_exc()}")

    def create_control_panel(self, parent_layout) -> None:
        """
        建立伺服器控制面板，包含啟動/停止按鈕與資源監控標籤

        Args:
            parent_layout: 父層佈局，控制面板將加入此佈局中
        """
        control_frame = CardWidget(self.window)
        c_layout = QVBoxLayout(control_frame)
        c_layout.setContentsMargins(Spacing.LARGE, Spacing.LARGE, Spacing.LARGE, Spacing.LARGE)

        h1 = QHBoxLayout()
        h1.addWidget(SubtitleLabel("🎮 伺服器控制", control_frame))

        status_text, status_color = ServerOperations.get_status_text(False)
        self.status_label = TitleLabel(status_text, control_frame)
        self.status_label.setStyleSheet(
            f"color: {status_color if status_color != 'red' else resolve_color(Colors.TEXT_ERROR)};"
        )
        h1.addWidget(self.status_label)

        h1.addStretch(1)

        self.start_button = PushButton("🚀 啟動", control_frame)
        self.start_button.clicked.connect(self.start_server)
        self.start_button.setEnabled(False)
        self.start_button.setFixedSize(Sizes.BUTTON_WIDTH_SECONDARY, Sizes.BUTTON_HEIGHT_LARGE)
        h1.addWidget(self.start_button)

        self.stop_button = PrimaryPushButton("⏹️ 停止", control_frame)
        self.stop_button.clicked.connect(self.stop_server)
        self.stop_button.setEnabled(False)
        self.stop_button.setFixedSize(Sizes.BUTTON_WIDTH_SECONDARY, Sizes.BUTTON_HEIGHT_LARGE)
        self.stop_button.setStyleSheet(f"background-color: {resolve_color(Colors.BUTTON_DANGER)};")
        h1.addWidget(self.stop_button)

        self.refresh_button = PushButton("🔄 刷新", control_frame)
        self.refresh_button.clicked.connect(self.refresh_status)
        self.refresh_button.setFixedSize(Sizes.BUTTON_WIDTH_SECONDARY, Sizes.BUTTON_HEIGHT_LARGE)
        h1.addWidget(self.refresh_button)

        c_layout.addLayout(h1)

        c_layout.addWidget(SubtitleLabel("📈 系統資源", control_frame))

        h2 = QHBoxLayout()
        v_left = QVBoxLayout()
        v_mid = QVBoxLayout()
        v_right = QVBoxLayout()

        self.pid_label = BodyLabel("🆔 PID: N/A", control_frame)
        self.memory_label = BodyLabel("🧠 記憶體使用: 0 MB", control_frame)
        v_left.addWidget(self.pid_label)
        v_left.addWidget(self.memory_label)

        self.uptime_label = BodyLabel("⏱️ 執行時間: 00:00:00", control_frame)
        self.players_label = BodyLabel("👥 玩家數量: 0/20", control_frame)
        v_mid.addWidget(self.uptime_label)
        v_mid.addWidget(self.players_label)

        self.version_label = BodyLabel("📦 版本: N/A", control_frame)
        v_right.addWidget(self.version_label)
        v_right.addStretch(1)

        h2.addLayout(v_left)
        h2.addLayout(v_mid)
        h2.addLayout(v_right)
        c_layout.addLayout(h2)

        parent_layout.addWidget(control_frame)

        players_frame = CardWidget(self.window)
        p_layout = QVBoxLayout(players_frame)
        p_layout.addWidget(SubtitleLabel("👥 線上玩家", players_frame))

        self.players_listbox = ListWidget(players_frame)
        self.players_listbox.addItem("無玩家在線")
        self.players_listbox.itemClicked.connect(self._on_player_click)
        p_layout.addWidget(self.players_listbox)

        parent_layout.addWidget(players_frame)

    def create_console_panel(self, parent_layout) -> None:
        """
        建立控制台輸出面板，包含日誌顯示區域與指令輸入框

        Args:
            parent_layout: 父層佈局，控制台面板將加入此佈局中
        """
        console_frame = CardWidget(self.window)
        c_layout = QVBoxLayout(console_frame)
        c_layout.setContentsMargins(Spacing.LARGE, Spacing.LARGE, Spacing.LARGE, Spacing.LARGE)

        c_layout.addWidget(SubtitleLabel("📜 控制台輸出", console_frame))

        self.console_text = TextEdit(console_frame)
        self.console_text.setReadOnly(True)

        font = self.console_text.font()
        font.setFamily("Consolas")
        font.setPointSize(FontSize.NORMAL_PLUS)
        self.console_text.setFont(font)

        c_layout.addWidget(self.console_text, 1)

        h_cmd = QHBoxLayout()
        h_cmd.addWidget(BodyLabel("指令:", console_frame))

        self.command_entry = LineEdit(console_frame)
        self.command_entry.setPlaceholderText("輸入指令...")
        font = self.command_entry.font()
        font.setFamily("Consolas")
        self.command_entry.setFont(font)
        self.command_entry.returnPressed.connect(self.send_command)

        h_cmd.addWidget(self.command_entry, 1)

        self.send_button = PushButton("發送", console_frame)
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.send_command)
        h_cmd.addWidget(self.send_button)

        c_layout.addLayout(h_cmd)

        parent_layout.addWidget(console_frame, 1)

    def start_console_flusher(self) -> None:
        """啟動控制台緩衝區的定期刷新機制"""
        self._schedule_console_flush(force=True)

    def start_monitoring(self) -> None:
        """啟動伺服器監控循環，開始追蹤狀態、輸出與玩家資訊"""
        if not self.is_monitoring:
            self.is_monitoring = True
            self._last_monitor_status_update = 0.0
            self._last_monitor_output_check = 0.0
            self._last_log_mtime = 0.0
            self._schedule_window_job("_monitor_start_refresh_job", 0, self.refresh_status)
            self.start_auto_refresh()
            self._schedule_monitor_loop_tick(0)

    def stop_monitoring(self) -> None:
        """停止所有監控活動並取消相關的排程工作"""
        self.is_monitoring = False
        self.stop_auto_refresh()
        if self.window:
            UIUtils.cancel_scheduled_job(self.window, "_console_flush_job", owner=self)
            UIUtils.cancel_scheduled_job(self.window, "_monitor_loop_job", owner=self)
            UIUtils.cancel_scheduled_job(self.window, "_delayed_player_list_job", owner=self)
        self._cancel_window_jobs()

    def monitor_loop(self) -> None:
        """監控主循環，定期觸發狀態更新與輸出讀取"""
        if not self.is_monitoring:
            return
        try:
            current_time = time.monotonic()
            if current_time - self._last_monitor_status_update >= 1.5:
                if self.window and self.window.isVisible():
                    self.ui_queue.put(self.update_status)
                self._last_monitor_status_update = current_time
            if current_time - self._last_monitor_output_check >= 0.1:
                with suppress(Exception):
                    self.read_server_output()
                with suppress(Exception):
                    log_file = self.server_manager.get_server_log_file(self.server_name)
                    if log_file and log_file.exists():
                        current_mtime = log_file.stat().st_mtime
                        if current_mtime > self._last_log_mtime:
                            self._last_log_mtime = current_mtime
                self._last_monitor_output_check = current_time
        except Exception as e:
            logger.error(f"監控更新錯誤: {e}\n{traceback.format_exc()}")
            self._schedule_monitor_loop_tick(500)
            return
        self._schedule_monitor_loop_tick(100)

    def read_server_output(self) -> None:
        """讀取伺服器最新輸出，解析狀態與玩家資訊"""
        try:
            raw_lines: list[str] = []

            if hasattr(self.server_manager, "read_server_output"):
                proc_lines = self.server_manager.read_server_output(self.server_name)
                if proc_lines:
                    raw_lines.extend(proc_lines)

            log_file = self.server_manager.get_server_log_file(self.server_name)
            if log_file and log_file.exists():
                try:
                    file_size = log_file.stat().st_size
                    if file_size < self._log_file_offset:
                        self._log_file_offset = 0
                    if file_size > self._log_file_offset:
                        with log_file.open("rb") as fh:
                            fh.seek(self._log_file_offset)
                            new_bytes = fh.read()
                            self._log_file_offset = fh.tell()
                        new_text = new_bytes.decode("utf-8", errors="ignore")
                        for line in new_text.splitlines():
                            clean = line.strip()
                            if clean:
                                raw_lines.append(clean)
                except Exception as log_err:
                    logger.debug(f"增量讀取日誌失敗: {log_err}")

            if not raw_lines:
                return

            for line in raw_lines:
                clean_line = self._clean_text(line)
                if not clean_line:
                    continue

                if clean_line in self._recent_lines_cache:
                    continue
                self._recent_lines_cache.add(clean_line)
                if len(self._recent_lines_cache) > 2000:
                    self._recent_lines_cache.clear()

                self.add_console_message(clean_line)

                if (
                    ("Done (" in clean_line and "For help, type" in clean_line)
                    or "Done (" in clean_line
                    or "Server started" in clean_line
                ):
                    self.ui_queue.put(self.handle_server_ready)

                snapshot = self._parse_player_list_line(clean_line)
                if snapshot:
                    self._queue_player_snapshot(snapshot)
                    continue

                presence_event = self._parse_player_presence_event(clean_line)
                if presence_event:
                    self._queue_player_presence_event(presence_event)
                    self.update_player_count()
        except Exception as e:
            logger.error(f"讀取伺服器輸出錯誤: {e}\n{traceback.format_exc()}")

    def update_player_count(self) -> None:
        """向伺服器發送 'list' 指令以更新目前的線上玩家數量"""
        try:
            success = self.server_manager.send_command(self.server_name, "list")
            if success and self.window and self.window.isVisible():
                UIUtils.schedule_debounce(
                    self.window,
                    "_delayed_player_list_job",
                    800,
                    self.read_player_list,
                    owner=self,
                )
        except Exception as e:
            logger.error(f"更新玩家數量錯誤: {e}\n{traceback.format_exc()}")

    def read_player_list(self, line=None) -> None:
        """
        解析伺服器輸出中的玩家列表行

        Args:
            line: 可選的單行輸出，若為 None 則讀取伺服器最新輸出
        """
        try:
            lines = [line] if line is not None else self.server_manager.read_server_output(self.server_name)
            for line in lines:
                snapshot = self._parse_player_list_line(line)
                if snapshot:
                    self._queue_player_snapshot(snapshot)
                    break
        except Exception as e:
            logger.error(f"讀取玩家列表時發生錯誤: {e}\n{traceback.format_exc()}")

    def update_player_list(self, players: list[str]) -> None:
        """
        更新玩家列表 UI 顯示

        Args:
            players: 玩家名稱列表
        """
        try:
            players_tuple = tuple(players or [])
            if self._last_player_names == players_tuple:
                return
            self._last_player_names = players_tuple
            self.players_listbox.clear()
            if players:
                for player in players:
                    if player:
                        self.players_listbox.addItem(player)
            else:
                self.players_listbox.addItem("無玩家在線")
        except Exception as e:
            logger.error(f"更新玩家列表錯誤: {e}\n{traceback.format_exc()}")

    def update_status(self) -> None:
        """取得伺服器最新資訊並更新 UI 狀態標籤"""
        try:
            if not self.window:
                return
            info = self.server_manager.get_server_info(self.server_name)
            if not info:
                return
            self._update_ui(info)
        except Exception as e:
            logger.error(f"更新狀態失敗: {e}\n{traceback.format_exc()}")

    def start_server(self) -> None:
        """執行伺服器啟動操作"""
        self.console_text.clear()
        self._server_ready_notified = False
        self._recent_lines_cache.clear()
        log_file = self.server_manager.get_server_log_file(self.server_name)
        if log_file and log_file.exists():
            with suppress(Exception):
                self._log_file_offset = log_file.stat().st_size
        else:
            self._log_file_offset = 0

        start_result = self.server_manager.start_server_result(self.server_name)
        if start_result.success:
            self.add_console_message(f"✅ 伺服器 {self.server_name} 啟動中...")
            self._schedule_window_job("_start_status_job", 500, self.update_status)
            if not self.is_monitoring:
                self.start_monitoring()
        else:
            self.add_console_message(f"❌ {start_result.message or f'啟動伺服器 {self.server_name} 失敗'}")
            UIUtils.show_message(
                start_result.title or "啟動失敗",
                start_result.message or f"啟動伺服器 {self.server_name} 失敗",
                self.window,
                message_level="error",
            )

    def stop_server(self) -> None:
        """執行伺服器停止操作（優雅停止）"""
        success = ServerOperations.graceful_stop_server(self.server_manager, self.server_name)
        if success:
            self.add_console_message(f"⏹️ 伺服器 {self.server_name} 停止指令已發送")
            self._schedule_window_job("_stop_refresh_after_job", 2000, self.refresh_after_stop)
        else:
            self.add_console_message(f"❌ 停止伺服器 {self.server_name} 失敗")
        self._schedule_window_job("_stop_status_job", 100, self.update_status)

    def refresh_after_stop(self) -> None:
        """在停止伺服器後定期檢查直到伺服器完全關閉，然後刷新狀態"""
        if self.server_manager.is_server_running(self.server_name):
            self._schedule_window_job("_stop_refresh_after_job", 500, self.refresh_after_stop)
        else:
            self.refresh_status()
            self.update_status()
            self.add_console_message("✅ 伺服器已確認停止")
            self.update_player_list([])

    def refresh_status(self) -> None:
        """手動刷新控制台日誌與伺服器狀態"""
        self.console_text.clear()
        self._recent_lines_cache.clear()
        last_player_line = None
        try:
            log_file = self.server_manager.get_server_log_file(self.server_name)
            if log_file and log_file.exists():
                with suppress(Exception):
                    self._log_file_offset = log_file.stat().st_size
                out_lines, truncated = self._read_recent_log_lines(log_file)
                last_player_line = self._find_latest_player_line(out_lines)
                if out_lines:
                    self.console_text.append("\n".join(out_lines))
                self.add_console_message("✅ 日誌載入完成")
                if truncated:
                    self.add_console_message(
                        f"ℹ️ 日誌過大，僅顯示最新 {len(out_lines)} 行（上限 {self._refresh_log_max_lines} 行）"
                    )
                if last_player_line:
                    self.read_player_list(line=last_player_line)
                else:
                    if self.server_manager.is_server_running(self.server_name):
                        self.update_player_count()
                    else:
                        self.update_player_list([])
            else:
                self.add_console_message("⚠️ 未找到日誌檔案")
        except Exception as e:
            logger.error(f"載入日誌失敗: {e}\n{traceback.format_exc()}")
            self.add_console_message(f"❌ 載入日誌失敗: {e}")
        self.update_status()
        self.add_console_message("🔄 狀態和控制台已刷新")

    def send_command(self, _event=None) -> None:
        """
        將輸入框中的指令發送到伺服器控制台

        Args:
            _event: 事件物件（未使用）
        """
        command = self.command_entry.text().strip()
        if not command:
            return
        if not self._command_history or self._command_history[-1] != command:
            self._command_history.append(command)
        self.command_entry.clear()
        self.add_console_message(f"> {command}")
        success = self.server_manager.send_command(self.server_name, command)
        if success:
            self.add_console_message(f"✅ 指令已發送: {command}")
            if command.lower() in ["stop", "end", "exit"]:
                self._schedule_window_job("_command_status_job", 1000, self.update_status)
        else:
            self.add_console_message(f"❌ 指令發送失敗: {command}")

    def add_console_message(self, message: str) -> None:
        """
        將訊息添加到控制台緩衝區並觸發刷新

        Args:
            message: 要顯示的訊息
        """
        self._console_buffer.append(message + "\n")
        self._schedule_console_flush()

    def on_closing(self) -> None:
        """處理視窗關閉事件，停止所有監控活動"""
        self.stop_monitoring()

    def closeEvent(self, event) -> None:
        """
        視窗關閉事件處理，確保在關閉時停止監控

        Args:
            event: QCloseEvent 事件物件
        """
        self.on_closing()
        self._ui_queue_timer.stop()
        super().closeEvent(event)

    def show(self) -> None:
        """建立並顯示監控視窗，啟動相關監控服務"""
        if getattr(self, "_is_created", False) is False:
            self.create_window()
            self._is_created = True
        center_window(self, self.parentWidget())
        super().show()
        if self.isVisible() and not self.is_monitoring:
            self.start_monitoring()
            self.start_console_flusher()
            self._ui_queue_timer.start(50)

    def handle_server_ready(self):
        """當偵測到伺服器啟動完成時，顯示包含 IP 與連接埠的通知"""
        try:
            if self._server_ready_notified:
                return
            self._server_ready_notified = True
            properties = (
                self.server_crud.load_server_properties(self.server_name)
                if hasattr(self.server_crud, "load_server_properties")
                else {}
            )
            server_ip = str(properties.get("server-ip", "") or "").strip()
            server_port = str(properties.get("server-port", "") or "").strip()
            if not server_port:
                server_port = "25565"
            if server_ip:
                msg = f"伺服器 {self.server_name} 啟動完成！\n已在 {server_ip}:{server_port} 開啟服務。"
            else:
                msg = f"伺服器 {self.server_name} 啟動完成！\n已在連接埠 {server_port} 開啟服務。"
            UIUtils.show_message("伺服器啟動成功", msg, self.window, message_level="info")
        except Exception as e:
            logger.error(f"handle_server_ready 執行錯誤: {e}\n{traceback.format_exc()}")

    def _schedule_auto_refresh_tick(self, delay_ms: int = 1000) -> None:
        if not self.window or not self.window.isVisible():
            self._auto_refresh_id = None
            return

        def _refresh_once() -> None:
            self._auto_refresh_id = None
            if not self.window or not self.window.isVisible():
                return
            self.update_status()
            self._schedule_auto_refresh_tick(delay_ms=1000)

        UIUtils.schedule_debounce(self.window, "_auto_refresh_id", max(1, int(delay_ms)), _refresh_once, owner=self)

    def _schedule_window_job(self, job_attr: str, delay_ms: int, callback: Callable[[], Any]) -> None:
        if not self.window or not self.window.isVisible():
            setattr(self, job_attr, None)
            return
        UIUtils.schedule_debounce(self.window, job_attr, max(0, int(delay_ms)), callback, owner=self)

    def _cancel_window_jobs(self) -> None:
        job_attrs = (
            "_monitor_start_refresh_job",
            "_start_status_job",
            "_stop_status_job",
            "_stop_refresh_after_job",
            "_command_status_job",
        )
        if not self.window or not self.window.isVisible():
            for job_attr in job_attrs:
                setattr(self, job_attr, None)
            return
        for job_attr in job_attrs:
            UIUtils.cancel_scheduled_job(self.window, job_attr, owner=self)

    def _on_player_click(self, item) -> None:
        try:
            if not item:
                return
            name = item.text()
            if not name or "無玩家在線" in name:
                return
            app = QApplication.instance()
            if app is not None:
                clipboard = QGuiApplication.clipboard()
                if clipboard:
                    clipboard.setText(name)
                    app.processEvents()
            logger.info(f"已複製玩家名稱: {name}")
        except Exception as e:
            logger.error(f"複製玩家名稱失敗: {e}")

    def _apply_player_snapshot(self, current_players: int, max_players: int, player_names: tuple[str, ...]) -> None:
        self._last_player_count = current_players
        self._last_max_players = max_players
        players_text = f"👥 玩家數量: {current_players}/{max_players}"
        self._last_ui_state["players_text"] = players_text
        try:
            self.players_label.setText(players_text)
        except Exception:
            logger.error("更新玩家數量 label 失敗")
        self.update_player_list(list(player_names))

    def _queue_player_snapshot(self, snapshot: tuple[int, int, tuple[str, ...]]) -> None:
        def _apply(snapshot: tuple[int, int, tuple[str, ...]] = snapshot) -> None:
            self._apply_player_snapshot(*snapshot)

        self.ui_queue.put(_apply)

    def _apply_player_presence_event(self, player_name: str, joined: bool) -> None:
        if self._last_player_names is None and not joined:
            return
        current_names: list[str] = [
            str(name) for name in (self._last_player_names or ()) if name and name != "無玩家在線"
        ]
        if joined:
            if player_name not in current_names:
                current_names.append(player_name)
        else:
            current_names = [name for name in current_names if name != player_name]
        self._last_player_count = len(current_names)
        if self._last_max_players is not None:
            players_text = f"👥 玩家數量: {self._last_player_count}/{self._last_max_players}"
            self._last_ui_state["players_text"] = players_text
            with suppress(Exception):
                self.players_label.setText(players_text)
        self.update_player_list(current_names)

    def _queue_player_presence_event(self, event: tuple[str, bool]) -> None:
        def _apply(event: tuple[str, bool] = event) -> None:
            self._apply_player_presence_event(*event)

        self.ui_queue.put(_apply)

    def _flush_console_buffer(self) -> None:
        if not self._console_buffer:
            return
        try:
            if self.window and self.window.isVisible() and hasattr(self, "console_text"):
                text = "".join(self._console_buffer)
                self._console_buffer = []
                self.console_text.append(text.strip())

                sb = self.console_text.verticalScrollBar()
                sb.setValue(sb.maximum())
        except Exception as e:
            logger.error(f"刷新控制台失敗: {e}\n{traceback.format_exc()}")

    def _schedule_console_flush(self, *, force: bool = False) -> None:
        if not self.window or not self.window.isVisible():
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

    def _schedule_monitor_loop_tick(self, delay_ms: int = 100) -> None:
        if not self.is_monitoring or not self.window or not self.window.isVisible():
            return
        UIUtils.schedule_debounce(
            self.window,
            "_monitor_loop_job",
            max(1, int(delay_ms)),
            self.monitor_loop,
            owner=self,
        )

    def _update_ui(self, info) -> None:
        try:
            is_running = info.get("is_running", False)
            pid = info.get("pid", "N/A")
            memory = info.get("memory", 0)
            uptime = info.get("uptime", "00:00:00")
            players = info.get("players", 0)
            max_players = info.get("max_players", 0)
            version = info.get("version", "N/A")

            status_text, status_color = ServerOperations.get_status_text(is_running)
            if self._last_ui_state.get("status_text") != status_text:
                self.status_label.setText(status_text)
                self.status_label.setStyleSheet(
                    f"color: {status_color if status_color != 'red' else resolve_color(Colors.TEXT_ERROR)};"
                )
                self._last_ui_state["status_text"] = status_text

            pid_text = f"🆔 PID: {pid}"
            if self._last_ui_state.get("pid_text") != pid_text:
                self.pid_label.setText(pid_text)
                self._last_ui_state["pid_text"] = pid_text

            mem_str = MemoryUtils.format_memory_mb(memory, compact=False)
            mem_text = f"🧠 記憶體使用: {mem_str}"
            if self._last_ui_state.get("mem_text") != mem_text:
                self.memory_label.setText(mem_text)
                self._last_ui_state["mem_text"] = mem_text

            uptime_text = f"⏱️ 執行時間: {uptime}"
            if self._last_ui_state.get("uptime_text") != uptime_text:
                self.uptime_label.setText(uptime_text)
                self._last_ui_state["uptime_text"] = uptime_text

            if not is_running:
                players_text = "👥 玩家數量: 0/0"
                if self._last_ui_state.get("players_text") != players_text:
                    self._last_player_count = None
                    self._last_max_players = None
                    self._last_player_names = None
                    self.players_label.setText(players_text)

                    self.players_listbox.clear()
                    self.players_listbox.addItem("無玩家在線")

                    self._last_ui_state["players_text"] = players_text
            else:
                if self._last_player_count is not None and self._last_max_players is not None:
                    players_text = f"👥 玩家數量: {self._last_player_count}/{self._last_max_players}"
                else:
                    players_text = f"👥 玩家數量: {players}/{max_players}"
                if self._last_ui_state.get("players_text") != players_text:
                    self.players_label.setText(players_text)
                    self._last_ui_state["players_text"] = players_text

            version_text = f"📦 版本: {version}"
            if self._last_ui_state.get("version_text") != version_text:
                self.version_label.setText(version_text)
                self._last_ui_state["version_text"] = version_text

            self.start_button.setEnabled(not is_running)
            self.stop_button.setEnabled(is_running)
            self.send_button.setEnabled(is_running)

        except Exception as e:
            logger.error(f"_update_ui 更新 UI 狀態失敗: {e}\n{traceback.format_exc()}")

    def _read_recent_log_lines(self, log_file) -> tuple[list[str], bool]:
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
        except Exception:
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
        for line in reversed(lines):
            if self._parse_player_list_line(line):
                return line
        return None


__all__ = ["ServerMonitorWindow"]
