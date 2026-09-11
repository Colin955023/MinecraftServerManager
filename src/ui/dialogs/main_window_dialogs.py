"""主視窗使用的匯入、輸入與伺服器初始化對話框"""

from __future__ import annotations

import time
from contextlib import suppress
from typing import Any

from PySide6 import QtCore
from PySide6.QtWidgets import QWidget
from qfluentwidgets import BodyLabel, LineEdit, PushButton, SubtitleLabel, TextEdit, TitleLabel

from src.models import ServerConfig
from src.ui import (
    Colors,
    FontManager,
    FontSize,
    StatusPushButton,
    UIUtils,
    UIWorkScope,
    WorkOutcome,
    center_window,
)
from src.utils import get_logger

from .modal_msfluent_window import ModalMSFluentWindow

logger = get_logger().bind(component="MainWindowDialogs")


class ImportDialog(ModalMSFluentWindow):
    """匯入伺服器對話框"""

    def __init__(self, parent):
        super().__init__(parent, is_modal=True, show_buttons=False)
        self.setWindowTitle("匯入伺服器")
        self.setFixedSize(520, 340)

        if hasattr(self, "titleBar"):
            if hasattr(self.titleBar, "minBtn"):
                self.titleBar.minBtn.hide()
            if hasattr(self.titleBar, "maxBtn"):
                self.titleBar.maxBtn.hide()

        self.choice = None

        title_lbl = TitleLabel("匯入伺服器", self.widget)
        title_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(title_lbl)

        info_label = SubtitleLabel("請選擇要匯入的伺服器類型:", self.widget)
        info_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(info_label)
        self.viewLayout.addStretch(1)

        folder_btn = PushButton("📁 匯入資料夾", self.widget)
        folder_btn.clicked.connect(lambda: self._set_choice("folder"))
        self.viewLayout.addWidget(folder_btn)

        archive_btn = PushButton("📦 匯入壓縮檔", self.widget)
        archive_btn.clicked.connect(lambda: self._set_choice("archive"))
        self.viewLayout.addWidget(archive_btn)

        cancel_btn = PushButton("❌ 取消", self.widget)
        cancel_btn.clicked.connect(lambda: self._set_choice("cancel"))
        self.viewLayout.addWidget(cancel_btn)

    def _set_choice(self, value: str) -> None:
        self.choice = value
        self.accept()


class FluentInputDialog(ModalMSFluentWindow):
    """現代化輸入對話框"""

    def __init__(self, parent, title: str, content: str, default_text: str = ""):
        super().__init__(parent, is_modal=True, show_buttons=False)
        self.setWindowTitle(title)
        self.setFixedSize(520, 300)

        if hasattr(self, "titleBar"):
            if hasattr(self.titleBar, "minBtn"):
                self.titleBar.minBtn.hide()
            if hasattr(self.titleBar, "maxBtn"):
                self.titleBar.maxBtn.hide()

        title_lbl = TitleLabel(title, self.widget)
        title_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(title_lbl)
        info_label = SubtitleLabel(content, self.widget)
        info_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(info_label)

        self.lineEdit = LineEdit(self.widget)
        self.lineEdit.setText(default_text)
        self.lineEdit.setClearButtonEnabled(True)
        self.viewLayout.addWidget(self.lineEdit)
        self.viewLayout.addStretch(1)

        self.yesButton.setText("確定")
        self.yesButton.clicked.connect(self._accept_input)
        self.cancelButton.setText("取消")
        self.cancelButton.clicked.connect(self.reject)
        self.buttonGroup.show()

        self.textValue = ""

    def _accept_input(self) -> None:
        self.validate()
        self.accept()

    def validate(self) -> bool:
        """
        驗證輸入並保存輸入值

        Returns:
            輸入有效時回傳 True
        """
        self.textValue = self.lineEdit.text()
        return True


class ServerInitializationDialog(ModalMSFluentWindow):
    """伺服器初始化對話框"""

    def __init__(self, parent: QWidget, server_runtime: Any, server_config: ServerConfig, completion_callback=None):
        super().__init__(parent, is_modal=True, show_buttons=False)
        self.parent_widget = parent
        self.server_runtime = server_runtime
        self.server_config = server_config
        self.completion_callback = completion_callback
        self._completion_scheduled = False
        self.done_detected = False
        self._started_confirmed = False
        self._runtime_sequence = 0
        self.scope = UIWorkScope(self)
        self._pending_console: list[str] = []
        self._start_time = 0.0
        self._last_activity_time = 0.0

        self.setWindowTitle(f"初始化伺服器 - {self.server_config.name}")
        self.setMinimumSize(600, 450)

        self.title_label = TitleLabel(f"正在初始化伺服器: {self.server_config.name}", self.widget)
        self.title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(self.title_label)

        self.info_label = SubtitleLabel(
            "伺服器正在首次啟動，請等待初始化完成...\n系統會自動在完成後關閉伺服器", self.widget
        )
        self.info_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(self.info_label)

        self.console_text = TextEdit(self.widget)
        self.console_text.setReadOnly(True)
        self.console_text.document().setMaximumBlockCount(2000)
        self.console_text.setFont(FontManager.get_font(family="Consolas", size=FontSize.TINY))
        self.console_text.setStyleSheet(
            f"TextEdit {{ background-color: {Colors.BG_CONSOLE}; color: {Colors.CONSOLE_TEXT}; border: 1px solid #333333; }}"
        )
        self.viewLayout.addWidget(self.console_text, 1)

        self.progress_label = BodyLabel("狀態: 準備啟動...", self.widget)
        self.progress_label.setFont(FontManager.get_font(size=FontSize.MEDIUM, weight="bold"))
        self.progress_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(self.progress_label)

        self.close_button = StatusPushButton("取消初始化", self.widget)
        self.close_button.set_status("danger")
        self.close_button.clicked.connect(self._close_initialization)

        self.cancelButton.hide()
        self.yesButton.hide()
        self.buttonLayout.insertWidget(3, self.close_button)
        self.buttonGroup.show()

        self._timeout_timer = QtCore.QTimer(self)
        self._timeout_timer.timeout.connect(self._timeout_force_close)
        self._runtime_timer = QtCore.QTimer(self)
        self._runtime_timer.timeout.connect(self._poll_runtime)
        self._console_timer = QtCore.QTimer(self)
        self._console_timer.setInterval(50)
        self._console_timer.timeout.connect(self._flush_console)

    def start_initialization(self) -> None:
        """啟動初始化對話框流程"""
        self._start_time = time.monotonic()
        self._last_activity_time = time.monotonic()
        self._started_confirmed = False
        self._timeout_timer.start(5000)
        self._runtime_timer.start(100)
        self._console_timer.start()
        center_window(self, self.parentWidget())
        self.show()
        self._start_initialization()

    def _start_initialization(self) -> None:
        """透過唯一 ServerRuntime 啟動初始化流程"""
        self.progress_label.setText("狀態: 正在啟動伺服器...")
        self._update_console("正在啟動 Minecraft 伺服器...\n")

        def _on_started(outcome: WorkOutcome) -> None:
            if outcome.is_failed:
                self._handle_server_error(str(outcome.error or "啟動伺服器失敗"))
            elif outcome.is_succeeded and outcome.value.failed:
                self._handle_server_error(outcome.value.message)

        self.scope.submit(
            lambda: self.server_runtime.start(self.server_config.name, intent="initialize"),
            on_done=_on_started,
            key="initialize_server",
            critical=True,
        )

    def _poll_runtime(self) -> None:
        """讀取 runtime 快照並將事件投影到初始化 UI"""
        snapshot = self.server_runtime.observe(self.server_config.name, after_sequence=self._runtime_sequence)
        self._runtime_sequence = snapshot.sequence
        if snapshot.events or snapshot.state in {"starting", "running"}:
            self._started_confirmed = True
        for event in snapshot.events:
            if event.kind == "output":
                self._last_activity_time = time.monotonic()
                self._update_console(f"{event.message}\n")
                self._process_server_output(event.message)
            elif event.kind == "ready":
                self.done_detected = True
                self.progress_label.setText("狀態: 伺服器完全啟動，正在關閉...")
                self._update_console("\n[系統] 所有模組載入完成，正在關閉伺服器...\n")
                self.close_button.setText("完成初始化")
                self.close_button.set_status("success")
            elif event.kind == "failed":
                self._handle_server_error(event.message)
        if not self._started_confirmed and snapshot.state == "stopped" and not snapshot.events:
            return
        if snapshot.state in {"stopped", "failed"}:
            self._runtime_timer.stop()
            if snapshot.state == "stopped":
                self._handle_server_completion()

    def _close_initialization(self) -> None:
        """關閉初始化伺服器"""
        if hasattr(self, "_countdown_timer"):
            self._countdown_timer.stop()
        if self.done_detected:
            self._timeout_timer.stop()
            self._runtime_timer.stop()
            self._console_timer.stop()
            self._flush_console()
            if self.completion_callback and not self._completion_scheduled:
                self._completion_scheduled = True
                self.completion_callback(self.server_config, self)
            else:
                self.reject()
        else:
            self._stop_initialization()
            self._timeout_timer.stop()
            self._runtime_timer.stop()
            self._console_timer.stop()
            self._flush_console()
            UIUtils.show_message(
                "強制關閉",
                "伺服器初始化未完成，已強制關閉請檢查伺服器日誌",
                self.parent_widget,
                message_level="warning",
            )
            self.reject()

    def _stop_initialization(self) -> None:
        """要求 runtime 終止初始化伺服器"""

        def _on_stopped(outcome: WorkOutcome) -> None:
            if outcome.is_failed:
                logger.error(f"終止伺服器程式失敗: {outcome.error}")

        self.scope.submit(
            lambda: self.server_runtime.stop(self.server_config.name),
            on_done=_on_stopped,
            key="stop_initialization",
            critical=True,
        )

    def _timeout_force_close(self) -> None:
        """超時強制關閉"""
        if self.done_detected:
            return
        now = time.monotonic()
        if now - self._start_time > 600 or (now - self._last_activity_time > 180 and now - self._start_time > 120):
            self._close_initialization()

    def _update_console(self, text: str) -> None:
        """更新控制台輸出"""
        self._pending_console.append(text)

    def _flush_console(self) -> None:
        """批次更新控制台輸出"""
        if not self._pending_console:
            return
        try:
            if self.console_text:
                text = "".join(self._pending_console)
                self._pending_console.clear()
                self.console_text.insertPlainText(text)
                scrollbar = self.console_text.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
        except Exception:
            logger.exception("更新控制台輸出失敗")

    def _process_server_output(self, output: str) -> None:
        """處理伺服器輸出"""
        if not self.isVisible():
            return
        if "Loading dimension" in output or "Preparing spawn area" in output:
            with suppress(Exception):
                self.progress_label.setText("狀態: 準備世界...")
        elif "Preparing level" in output:
            with suppress(Exception):
                self.progress_label.setText("狀態: 載入世界...")

    def _handle_server_completion(self) -> None:
        """處理伺服器完成狀態"""
        if not self.isVisible():
            return
        if self.done_detected:
            self._update_console("[系統] 伺服器初始化完成！\n")
            if self.progress_label:
                self.progress_label.setText("狀態: 初始化完成")
            self.close_button.setText("完成初始化")
            self.close_button.set_status("success")
            if self.completion_callback and not self._completion_scheduled:
                self._completion_scheduled = True
                QtCore.QTimer.singleShot(2000, lambda: self.completion_callback(self.server_config, self))
        else:
            self._update_console("[系統] 伺服器啟動可能有問題，請檢查輸出\n")
            if self.progress_label:
                self.progress_label.setText("狀態: 啟動錯誤")
            self._start_failure_countdown(60)

    def _handle_server_error(self, err_msg: str) -> None:
        """處理伺服器錯誤並啟動倒數計時強制終止"""
        if not self.isVisible():
            return
        self._update_console(f"[錯誤] 啟動失敗: {err_msg}\n")
        self._start_failure_countdown(60)

    def _start_failure_countdown(self, seconds: int = 60) -> None:
        """啟動失敗倒數計時"""
        self._failure_countdown = seconds
        self._update_failure_countdown_ui()
        if not hasattr(self, "_countdown_timer"):
            self._countdown_timer = QtCore.QTimer(self)
            self._countdown_timer.timeout.connect(self._on_countdown_tick)
        self._countdown_timer.start(1000)

    def _update_failure_countdown_ui(self) -> None:
        if self.progress_label:
            self.progress_label.setText(f"狀態: 啟動失敗\n將於 {self._failure_countdown} 秒後強制終止")

    def _on_countdown_tick(self) -> None:
        self._failure_countdown -= 1
        if self._failure_countdown <= 0:
            if hasattr(self, "_countdown_timer"):
                self._countdown_timer.stop()
            self._close_initialization()
        else:
            self._update_failure_countdown_ui()


__all__ = ["FluentInputDialog", "ImportDialog", "ServerInitializationDialog"]
