"""
伺服器監控視窗
提供即時的伺服器狀態監控、控制台輸出和資源使用情況
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from typing import Any, cast

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    LineEdit,
    ListWidget,
    MSFluentWindow,
    PlainTextEdit,
    PushButton,
    SubtitleLabel,
    TitleLabel,
    qconfig,
)

from src.ui import (
    Colors,
    FontSize,
    Sizes,
    Spacing,
    StatusPushButton,
    UIUtils,
    UIWorkScope,
    WorkOutcome,
    apply_window_icon,
    center_window,
    resolve_color,
    themed_surface_stylesheet,
)
from src.utils import MemoryUtils, get_logger

from .server_monitor_parsing import (
    clean_text,
    find_latest_player_line,
    get_status_text,
    parse_player_list_line,
    parse_player_presence_event,
)

logger = get_logger().bind(component="ServerMonitorWindow")
_CONSOLE_MAX_BUFFER_LINES = 2000
_CONSOLE_MAX_BUFFER_CHARS = 2 * 1024 * 1024
_CONSOLE_MAX_LINE_CHARS = 64 * 1024
_CONSOLE_MAX_DOCUMENT_BLOCKS = 5000


class ServerMonitorWindow(MSFluentWindow):
    """伺服器監控視窗"""

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

    def __init__(self, parent, server_runtime, server_name: str, server_crud=None, server_properties=None):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._owner_window = parent
        self.server_runtime = server_runtime
        self.server_crud = server_crud
        self.server_properties = server_properties
        self.server_name = server_name
        self.scope = UIWorkScope(self)
        apply_window_icon(self)
        self.setMicaEffectEnabled(False)
        self.setCustomBackgroundColor(*Colors.BG_PRIMARY)
        self.navigationInterface.hide()
        self.stackedWidget.setStyleSheet("background-color: transparent; border: none;")

        self.widget = QWidget(self)
        self.widget.setObjectName("MonitorMainWidget")
        self.stackedWidget.addWidget(self.widget)
        self.stackedWidget.setCurrentWidget(self.widget)
        self.viewLayout = QVBoxLayout(self.widget)
        self.viewLayout.setContentsMargins(20, 20, 20, 20)
        self.viewLayout.setSpacing(12)

        self._auto_refresh_id: int | None = None
        self.is_monitoring = False
        self._last_player_count: int | None = None
        self._last_max_players: int | None = None
        self._last_player_names: tuple[str, ...] | None = None
        self._server_ready_notified = True
        self._last_ui_state: dict[str, str] = {}
        self._last_status_running = False
        self._console_buffer: deque[str] = deque()
        self._console_buffer_chars = 0
        self._console_flush_interval_ms = 100
        self._refresh_log_max_lines = 2500
        self._refresh_log_max_bytes = 2 * 1024 * 1024
        self._command_history: list[str] = []
        self._history_index: int = -1
        self._current_typed: str = ""
        self._last_monitor_status_update = 0.0
        self._last_monitor_output_check = 0.0
        self._runtime_sequence = 0
        qconfig.themeChangedFinished.connect(self.apply_theme_styles)
        self.apply_theme_styles()

    def apply_theme_styles(self) -> None:
        """依目前主題重新套用監控視窗中以色彩 token 建立的樣式"""
        if not getattr(self, "widget", None):
            return
        self.setCustomBackgroundColor(*Colors.BG_PRIMARY)
        self.widget.setStyleSheet(themed_surface_stylesheet("MonitorMainWidget"))
        border = resolve_color(Colors.BORDER)
        if hasattr(self, "status_label"):
            _status_text, status_color = get_status_text(self._last_status_running)
            self.status_label.setStyleSheet(
                f"color: {status_color if status_color != 'red' else resolve_color(Colors.TEXT_ERROR)};"
                " background: transparent;"
            )
        if hasattr(self, "players_listbox"):
            self.players_listbox.setStyleSheet(
                f"ListWidget {{ background-color: transparent; border: 1px solid {border}; "
                f"color: {resolve_color(Colors.TEXT_PRIMARY)}; }}"
            )
        if hasattr(self, "console_text"):
            self.console_text.setStyleSheet(
                "PlainTextEdit { background-color: transparent; "
                f"color: {resolve_color(Colors.TEXT_PRIMARY)}; border: 1px solid {border}; }}"
            )
        self.update()

    def start_auto_refresh(self) -> None:
        """啟動伺服器狀態的自動刷新機制"""
        if self._auto_refresh_id:
            return
        self._schedule_auto_refresh_tick(delay_ms=1000)

    def stop_auto_refresh(self) -> None:
        """停止伺服器狀態的自動刷新機制"""
        if self.isVisible():
            UIUtils.cancel_scheduled_job(self, "_auto_refresh_id", owner=self)
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
        self.apply_theme_styles()

        try:
            current_width = self.width()
            current_height = self.height()
            _, _, final_width, final_height = self._fit_initial_size(
                current_width, current_height, available_width, available_height
            )

            self.resize(final_width, final_height)
            self.update_status()
        except Exception:
            logger.exception("視窗置中失敗")

    def create_control_panel(self, parent_layout) -> None:
        """
        建立伺服器控制面板，包含啟動/停止按鈕與資源監控標籤

        Args:
            parent_layout: 父層佈局，控制面板將加入此佈局中
        """
        control_frame = CardWidget(self)
        c_layout = QVBoxLayout(control_frame)
        c_layout.setContentsMargins(Spacing.LARGE, Spacing.LARGE, Spacing.LARGE, Spacing.LARGE)

        h1 = QHBoxLayout()
        lbl_control = SubtitleLabel("🎮 伺服器控制", control_frame)
        h1.addWidget(lbl_control)

        status_text_value, status_color = get_status_text(False)
        self.status_label = TitleLabel(status_text_value, control_frame)
        self.status_label.setStyleSheet(
            f"color: {status_color if status_color != 'red' else resolve_color(Colors.TEXT_ERROR)}; background: transparent;"
        )
        h1.addWidget(self.status_label)

        h1.addStretch(1)

        self.start_button = PushButton("🚀 啟動", control_frame)
        self.start_button.clicked.connect(self.start_server)
        self.start_button.setEnabled(False)
        self.start_button.setFixedSize(Sizes.BUTTON_WIDTH_SECONDARY, Sizes.BUTTON_HEIGHT_LARGE)
        h1.addWidget(self.start_button)

        self.stop_button = StatusPushButton("⏹️ 停止", control_frame)
        self.stop_button.set_status("danger")
        self.stop_button.clicked.connect(self.stop_server)
        self.stop_button.setEnabled(False)
        self.stop_button.setFixedSize(Sizes.BUTTON_WIDTH_SECONDARY, Sizes.BUTTON_HEIGHT_LARGE)
        h1.addWidget(self.stop_button)

        self.refresh_button = PushButton("🔄 刷新", control_frame)
        self.refresh_button.clicked.connect(self.refresh_status)
        self.refresh_button.setFixedSize(Sizes.BUTTON_WIDTH_SECONDARY, Sizes.BUTTON_HEIGHT_LARGE)
        h1.addWidget(self.refresh_button)

        c_layout.addLayout(h1)

        lbl_resource = SubtitleLabel("📈 系統資源", control_frame)
        c_layout.addWidget(lbl_resource)

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

        players_frame = CardWidget(self)
        p_layout = QVBoxLayout(players_frame)
        lbl_players = SubtitleLabel("👥 線上玩家", players_frame)
        p_layout.addWidget(lbl_players)

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
        console_frame = CardWidget(self)
        c_layout = QVBoxLayout(console_frame)
        c_layout.setContentsMargins(Spacing.LARGE, Spacing.LARGE, Spacing.LARGE, Spacing.LARGE)

        lbl_console = SubtitleLabel("📜 控制台輸出", console_frame)
        c_layout.addWidget(lbl_console)

        self.console_text = PlainTextEdit(console_frame)
        self.console_text.setReadOnly(True)
        self.console_text.document().setMaximumBlockCount(_CONSOLE_MAX_DOCUMENT_BLOCKS)

        font = self.console_text.font()
        font.setFamily("Consolas")
        font.setPointSize(FontSize.NORMAL_PLUS)
        self.console_text.setFont(font)

        c_layout.addWidget(self.console_text, 1)

        h_cmd = QHBoxLayout()
        lbl_cmd = BodyLabel("指令:", console_frame)
        h_cmd.addWidget(lbl_cmd)

        self.command_entry = LineEdit(console_frame)
        self.command_entry.setPlaceholderText("輸入指令...")
        font = self.command_entry.font()
        font.setFamily("Consolas")
        self.command_entry.setFont(font)
        self.command_entry.returnPressed.connect(self.send_command)
        self.command_entry.installEventFilter(self)

        h_cmd.addWidget(self.command_entry, 1)

        self.send_button = PushButton("發送", console_frame)
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.send_command)
        h_cmd.addWidget(self.send_button)

        c_layout.addLayout(h_cmd)

        parent_layout.addWidget(console_frame, 1)

    def start_monitoring(self) -> None:
        """啟動伺服器監控迴圈，開始追蹤狀態、輸出與玩家資訊"""
        if not self.is_monitoring:
            self.is_monitoring = True
            self._last_monitor_status_update = 0.0
            self._last_monitor_output_check = 0.0
            self._schedule_window_job("_monitor_start_refresh_job", 0, self.refresh_status)
            self.start_auto_refresh()
            self._schedule_monitor_loop_tick(0)

    def stop_monitoring(self) -> None:
        """停止所有監控活動並取消相關的排程工作"""
        self.is_monitoring = False
        self.stop_auto_refresh()
        UIUtils.cancel_scheduled_job(self, "_console_flush_job", owner=self)
        UIUtils.cancel_scheduled_job(self, "_monitor_loop_job", owner=self)
        UIUtils.cancel_scheduled_job(self, "_delayed_player_list_job", owner=self)
        self._cancel_window_jobs()

    def monitor_loop(self) -> None:
        """監控主迴圈，定期觸發狀態更新與輸出讀取"""
        if not self.is_monitoring:
            return
        try:
            current_time = time.monotonic()
            if current_time - self._last_monitor_status_update >= 1.5:
                if self.isVisible():
                    self.update_status()
                self._last_monitor_status_update = current_time
            if current_time - self._last_monitor_output_check >= 0.1:
                with suppress(Exception):
                    self.read_server_output()
                self._last_monitor_output_check = current_time
        except Exception:
            logger.exception("監控更新錯誤")
            self._schedule_monitor_loop_tick(500)
            return
        self._schedule_monitor_loop_tick(100)

    def read_server_output(self) -> None:
        """讀取伺服器最新輸出，解析狀態與玩家資訊"""
        try:
            snapshot = self.server_runtime.observe(
                self.server_name,
                after_sequence=self._runtime_sequence,
            )
            self._runtime_sequence = snapshot.sequence
            if not snapshot.output_lines:
                return

            for line in snapshot.output_lines:
                clean_line = clean_text(line)
                if not clean_line:
                    continue

                self.add_console_message(clean_line)

                if (
                    (
                        ("Done (" in clean_line and "For help, type" in clean_line)
                        or "Done (" in clean_line
                        or "Server started" in clean_line
                    )
                    and self.server_runtime.observe(self.server_name).is_running
                    and not self._server_ready_notified
                ):
                    self.handle_server_ready()

                snapshot = parse_player_list_line(clean_line)
                if snapshot:
                    self._apply_player_snapshot(*snapshot)
                    continue

                presence_event = parse_player_presence_event(clean_line)
                if presence_event:
                    self._apply_player_presence_event(*presence_event)
                    self.update_player_count()
        except Exception:
            logger.exception("讀取伺服器輸出錯誤")

    def update_player_count(self) -> None:
        """向伺服器發送 'list' 指令以更新目前的線上玩家數量"""
        try:
            success = self.server_runtime.send_command(self.server_name, "list")
            if success and self.isVisible():
                UIUtils.schedule_debounce(
                    self,
                    "_delayed_player_list_job",
                    800,
                    self.read_player_list,
                    owner=self,
                )
        except Exception:
            logger.exception("更新玩家數量錯誤")

    def read_player_list(self, line=None) -> None:
        """
        解析伺服器輸出中的玩家列表行

        Args:
            line: 可選的單行輸出，若為 None 則讀取伺服器最新輸出
        """
        try:
            if line is None:
                self.read_server_output()
                return
            lines = [line]
            for line in lines:
                snapshot = parse_player_list_line(line)
                if snapshot:
                    self._apply_player_snapshot(*snapshot)
                    break
        except Exception:
            logger.exception("讀取玩家列表時發生錯誤")

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
        except Exception:
            logger.exception("更新玩家列表錯誤")

    def update_status(self) -> None:
        """取得伺服器最新資訊並更新 UI 狀態標籤"""
        try:
            runtime_snapshot = self.server_runtime.observe(self.server_name)
            config = self.server_crud.snapshot().get(self.server_name) if self.server_crud else None
            properties_snapshot = self.server_properties.describe(self.server_name) if self.server_properties else None
            properties = properties_snapshot.properties if properties_snapshot and properties_snapshot.readable else {}
            max_players = int(properties.get("max-players", 0) or 0)
            version = "N/A"
            if config is not None:
                version = f"{config.minecraft_version}({config.loader_type})"
            info = {
                "is_running": runtime_snapshot.is_running,
                "pid": runtime_snapshot.pid,
                "memory": runtime_snapshot.memory_mb,
                "uptime": runtime_snapshot.uptime,
                "players": self._last_player_count or 0,
                "max_players": max_players,
                "version": version,
            }
            self._update_ui(info)
        except Exception:
            logger.exception("更新狀態失敗")

    def arm_server_ready_notification(self) -> None:
        """為一次新的啟動流程重設輸出游標，確保能偵測 ready 並只通知一次"""
        self._server_ready_notified = False
        self._runtime_sequence = 0

    def start_server(self) -> None:
        """執行伺服器啟動操作"""
        self.console_text.clear()
        self.arm_server_ready_notification()

        def _on_started(outcome: WorkOutcome) -> None:
            start_result = outcome.value if outcome.is_succeeded else None
            if start_result is not None and start_result.success:
                self.add_console_message(f"✅ 伺服器 {self.server_name} 啟動中...")
                self._schedule_window_job("_start_status_job", 500, self.update_status)
                if not self.is_monitoring:
                    self.start_monitoring()
                return
            message = getattr(start_result, "message", "") or f"啟動伺服器 {self.server_name} 失敗"
            self.add_console_message(f"❌ {message}")
            UIUtils.show_message(
                getattr(start_result, "title", "") or "啟動失敗",
                message,
                self,
                message_level="error",
            )

        self.scope.submit(
            lambda: self.server_runtime.start(self.server_name),
            on_done=_on_started,
            key="monitor_runtime",
            critical=True,
        )

    def stop_server(self) -> None:
        """執行伺服器停止操作（正常停止）"""

        def _on_stopped(outcome: WorkOutcome) -> None:
            if outcome.is_succeeded and outcome.value:
                self.add_console_message(f"⏹️ 伺服器 {self.server_name} 已停止")
                self._schedule_window_job("_stop_refresh_after_job", 0, self.refresh_after_stop)
            else:
                self.add_console_message(f"❌ 停止伺服器 {self.server_name} 失敗")
            self._schedule_window_job("_stop_status_job", 0, self.update_status)

        self.scope.submit(
            lambda: self.server_runtime.stop(self.server_name),
            on_done=_on_stopped,
            key="monitor_runtime",
            critical=True,
        )

    def refresh_after_stop(self) -> None:
        """在停止伺服器後定期檢查直到伺服器完全關閉，然後刷新狀態"""
        if self.server_runtime.observe(self.server_name).is_running:
            self._schedule_window_job("_stop_refresh_after_job", 500, self.refresh_after_stop)
        else:
            self.refresh_status()
            self.update_status()
            self.add_console_message("✅ 伺服器已確認停止")
            self.update_player_list([])

    def refresh_status(self) -> None:
        """手動刷新控制台日誌與伺服器狀態"""
        self.console_text.clear()
        last_player_line = None
        try:
            history = self.server_runtime.read_output_history(
                self.server_name,
                max_lines=self._refresh_log_max_lines,
                max_bytes=self._refresh_log_max_bytes,
            )
            self._runtime_sequence = history.sequence
            if history.lines:
                out_lines = list(history.lines)
                last_player_line = find_latest_player_line(out_lines)
                self.console_text.appendPlainText("\n".join(out_lines))
                self.add_console_message("✅ 日誌載入完成")
                if history.truncated:
                    self.add_console_message(
                        f"ℹ️ 日誌過大，僅顯示最新 {len(out_lines)} 行（上限 {self._refresh_log_max_lines} 行）"
                    )
                if last_player_line:
                    self.read_player_list(line=last_player_line)
                elif self.server_runtime.observe(self.server_name).is_running:
                    self.update_player_count()
                else:
                    self.update_player_list([])
            else:
                self.add_console_message("⚠️ 未找到日誌輸出")
        except Exception as e:
            logger.exception("載入日誌失敗")
            self.add_console_message(f"❌ 載入日誌失敗: {e}")
        self.update_status()
        self.add_console_message("🔄 狀態和控制台已刷新")

    def send_command(self) -> None:
        """
        將輸入框中的指令發送到伺服器控制台

        """
        command = self.command_entry.text().strip()
        if not command:
            return
        if not self._command_history or self._command_history[-1] != command:
            self._command_history.append(command)
        self._history_index = -1
        self._current_typed = ""
        self.command_entry.clear()
        self.add_console_message(f"> {command}")
        success = self.server_runtime.send_command(self.server_name, command)
        if success:
            self.add_console_message(f"✅ 指令已發送: {command}")
            if command.lower() in ["stop", "end", "exit"]:
                self._schedule_window_job("_command_status_job", 1000, self.update_status)
        else:
            self.add_console_message(f"❌ 指令發送失敗: {command}")

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """
        過濾指令輸入框事件以支援方向鍵切換歷史指令

        Args:
            watched: 被監視的 QObject 元件
            event: 傳遞的事件物件

        Returns:
            若已攔截並處理該事件則傳回 True，否則傳回 False
        """
        if watched == getattr(self, "command_entry", None) and event.type() == QEvent.Type.KeyPress:
            key_event = cast(QKeyEvent, event)
            key = key_event.key()
            if key == Qt.Key.Key_Up:
                if self._command_history:
                    if self._history_index == -1:
                        self._current_typed = self.command_entry.text()
                        self._history_index = len(self._command_history) - 1
                    elif self._history_index > 0:
                        self._history_index -= 1
                    self.command_entry.setText(self._command_history[self._history_index])
                return True
            if key == Qt.Key.Key_Down:
                if self._command_history and self._history_index != -1:
                    if self._history_index < len(self._command_history) - 1:
                        self._history_index += 1
                        self.command_entry.setText(self._command_history[self._history_index])
                    else:
                        self._history_index = -1
                        self.command_entry.setText(self._current_typed)
                return True
        return super().eventFilter(watched, event)

    def add_console_message(self, message: str) -> None:
        """
        將訊息添加到控制台緩衝區並觸發刷新

        Args:
            message: 要顯示的訊息
        """
        line = str(message or "")[:_CONSOLE_MAX_LINE_CHARS] + "\n"
        self._console_buffer.append(line)
        self._console_buffer_chars += len(line)
        while self._console_buffer and (
            len(self._console_buffer) > _CONSOLE_MAX_BUFFER_LINES
            or self._console_buffer_chars > _CONSOLE_MAX_BUFFER_CHARS
        ):
            self._console_buffer_chars -= len(self._console_buffer.popleft())
        self._schedule_console_flush()

    def _queue_surface_refresh(self) -> None:
        """在 Windows Show Desktop/還原後排程正常 paint，不強制改動 frameless geometry"""
        if not self.isVisible() or self.isMinimized():
            return
        self.update()
        if getattr(self, "titleBar", None) is not None:
            self.titleBar.update()
        if getattr(self, "stackedWidget", None) is not None:
            self.stackedWidget.update()

    def changeEvent(self, event: QEvent) -> None:
        """
        重新取得焦點或視窗狀態改變時，以非同步 repaint 更新 frameless surface

        Args:
            event: QEvent 事件物件
        """
        super().changeEvent(event)
        if event.type() in (QEvent.Type.WindowStateChange, QEvent.Type.ActivationChange):
            QTimer.singleShot(0, self._queue_surface_refresh)

    def closeEvent(self, event) -> None:
        """
        視窗關閉事件處理，確保在關閉時停止監控

        Args:
            event: QCloseEvent 事件物件
        """
        self.stop_monitoring()
        with suppress(Exception):
            qconfig.themeChangedFinished.disconnect(self.apply_theme_styles)
        super().closeEvent(event)

    def show(self) -> None:
        """建立並顯示監控視窗，啟動相關監控服務"""
        was_visible = self.isVisible()
        if getattr(self, "_is_created", False) is False:
            self.create_window()
            self._is_created = True
        if not was_visible and not self.isMaximized() and not self.isMinimized():
            center_window(self, self._owner_window if isinstance(self._owner_window, QWidget) else None)
        super().show()
        if self.isVisible() and not self.is_monitoring:
            self.start_monitoring()
            self._schedule_console_flush()

    def handle_server_ready(self):
        """當偵測到伺服器啟動完成時，顯示包含 IP 與連接埠的通知"""
        try:
            if self._server_ready_notified:
                return
            self._server_ready_notified = True
            properties_snapshot = self.server_properties.describe(self.server_name) if self.server_properties else None
            properties = properties_snapshot.properties if properties_snapshot and properties_snapshot.readable else {}
            server_ip = str(properties.get("server-ip", "") or "").strip()
            server_port = str(properties.get("server-port", "") or "").strip()
            if not server_port:
                server_port = "25565"
            if server_ip:
                msg = f"伺服器 {self.server_name} 啟動完成！\n已在 {server_ip}:{server_port} 開啟服務"
            else:
                msg = f"伺服器 {self.server_name} 啟動完成！\n已在連接埠 {server_port} 開啟服務"
            UIUtils.show_message("伺服器啟動成功", msg, self, message_level="info")
        except Exception:
            logger.exception("handle_server_ready 執行錯誤")

    def _schedule_auto_refresh_tick(self, delay_ms: int = 1000) -> None:
        if not self.isVisible():
            self._auto_refresh_id = None
            return

        def _refresh_once() -> None:
            self._auto_refresh_id = None
            if not self.isVisible():
                return
            self.update_status()
            self._schedule_auto_refresh_tick(delay_ms=1000)

        UIUtils.schedule_debounce(self, "_auto_refresh_id", max(1, int(delay_ms)), _refresh_once, owner=self)

    def _schedule_window_job(self, job_attr: str, delay_ms: int, callback: Callable[[], Any]) -> None:
        if not self.isVisible():
            setattr(self, job_attr, None)
            return
        UIUtils.schedule_debounce(self, job_attr, max(0, int(delay_ms)), callback, owner=self)

    def _cancel_window_jobs(self) -> None:
        job_attrs = (
            "_monitor_start_refresh_job",
            "_start_status_job",
            "_stop_status_job",
            "_stop_refresh_after_job",
            "_command_status_job",
        )
        if not self.isVisible():
            for job_attr in job_attrs:
                setattr(self, job_attr, None)
            return
        for job_attr in job_attrs:
            UIUtils.cancel_scheduled_job(self, job_attr, owner=self)

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

    def _flush_console_buffer(self) -> None:
        if not self._console_buffer:
            return
        try:
            if self.isVisible() and hasattr(self, "console_text"):
                text = "".join(self._console_buffer)
                self._console_buffer.clear()
                self._console_buffer_chars = 0
                sb = self.console_text.verticalScrollBar()
                auto_scroll = sb.value() >= (sb.maximum() - 20)
                self.console_text.appendPlainText(text.strip())
                if auto_scroll:
                    sb.setValue(sb.maximum())
        except Exception:
            logger.exception("刷新控制台失敗")

    def _schedule_console_flush(self, *, force: bool = False) -> None:
        if not self.isVisible():
            return
        interval = max(1, int(getattr(self, "_console_flush_interval_ms", 100)))
        if force:
            UIUtils.schedule_debounce(self, "_console_flush_job", 0, self._flush_console_buffer, owner=self)
            return
        UIUtils.schedule_throttle(
            self,
            "_console_flush_job",
            interval,
            self._flush_console_buffer,
            owner=self,
            trailing=True,
            last_run_attr="_console_flush_last_run_ms",
        )

    def _schedule_monitor_loop_tick(self, delay_ms: int = 100) -> None:
        if not self.is_monitoring or not self.isVisible():
            return
        UIUtils.schedule_debounce(
            self,
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

            status_text, status_color = get_status_text(is_running)
            self._last_status_running = is_running
            if self._last_ui_state.get("status_text") != status_text:
                self.status_label.setText(status_text)
                self.status_label.setStyleSheet(
                    f"color: {status_color if status_color != 'red' else resolve_color(Colors.TEXT_ERROR)};"
                    " background: transparent;"
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

        except Exception:
            logger.exception("_update_ui 更新 UI 狀態失敗")


__all__ = ["ServerMonitorWindow"]
