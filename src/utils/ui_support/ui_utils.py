"""
UI 工具函數
提供常用的界面元件和工具函數，避免重複程式碼
"""

import os
import time
import webbrowser
import winsound
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QApplication
from qfluentwidgets import ComboBox, MessageBox

from .. import (
    Colors,
    PathUtils,
    QtCore,
    QtWidgets,
    SubprocessUtils,
    cancel_timer,
    get_logger,
    invoke_later,
    is_qobject_alive,
    resolve_color,
    run_on_ui_thread,
)

logger = get_logger().bind(component="UIUtils")


def _is_ui_thread() -> bool:
    app = QtWidgets.QApplication.instance()
    return app is None or QtCore.QThread.currentThread() is app.thread()


class UIUtils:
    """UI 共用工具與對話框包裝"""

    _DANGER_BUTTON_STYLE = (
        "QPushButton {{ background-color: {color}; color: white;"
        " border: 1px solid rgba(0, 0, 0, 0.1); border-radius: 5px; padding: 5px 10px; }}"
    )

    @staticmethod
    def apply_danger_style(button: Any) -> None:
        """
        套用危險操作按鈕樣式（紅色背景）

        Args:
            button: 要套用樣式的按鈕元件
        """
        button.setStyleSheet(UIUtils._DANGER_BUTTON_STYLE.format(color=resolve_color(Colors.BUTTON_DANGER)))

    @staticmethod
    def pack_main_frame(frame, padx: int | None = None, pady: int | None = None) -> None:
        """
        統一設定框架的邊距與尺寸策略，使其填滿可用空間

        Args:
            frame: 要設定的框架元件
            padx: 水平邊距，預設 12
            pady: 垂直邊距，預設 12
        """
        if padx is None:
            padx = 12
        if pady is None:
            pady = 12
        if isinstance(frame, QtWidgets.QWidget):
            frame.setContentsMargins(padx, pady, padx, pady)
            frame.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
            if hasattr(frame, "attach"):
                frame.attach(fill="both", expand=True)
            return
        if hasattr(frame, "attach"):
            frame.attach(fill="both", expand=True, padx=padx, pady=pady)

    @staticmethod
    def get_mousewheel_units(delta: int) -> int:
        if delta == 0:
            return 0
        units = int(-delta / 120)
        if units == 0:
            return -1 if delta > 0 else 1
        return units

    @staticmethod
    def cancel_scheduled_job(widget, job_attr: str, *, owner: Any | None = None) -> None:
        """
        取消指定的排程工作並將其屬性設為 None

        Args:
            widget: 關聯的 UI 元件
            job_attr: 儲存 Job ID 的屬性名稱
            owner: Job ID 實際儲存的物件，若為 None 則使用 widget
        """
        holder = owner if owner is not None else widget
        job_id = getattr(holder, job_attr, None)
        if not job_id:
            setattr(holder, job_attr, None)
            return
        try:
            if isinstance(job_id, QtCore.QTimer):
                cancel_timer(job_id)
            elif widget and hasattr(widget, "cancel_schedule"):
                widget.cancel_schedule(job_id)
        except Exception as e:
            logger.debug(f"取消排程失敗 {job_attr}={job_id}: {e}")
        finally:
            setattr(holder, job_attr, None)

    @staticmethod
    def _is_schedulable_widget(widget: Any, holder: Any, job_attr: str) -> bool:
        if not widget:
            return False
        try:
            if isinstance(widget, QtCore.QObject) and not is_qobject_alive(widget):
                setattr(holder, job_attr, None)
                return False
            if hasattr(widget, "is_alive") and not widget.is_alive():
                setattr(holder, job_attr, None)
                return False
        except Exception:
            return False
        return True

    @staticmethod
    def schedule_debounce(
        widget, job_attr: str, delay_ms: int, callback: Callable[[], Any], *, owner: Any | None = None
    ) -> Any | None:
        """
        建立防抖 (Debounce) 排程
        在指定延遲時間內若再次呼叫，將重設計時器，僅在最後一次呼叫後執行

        Args:
            widget: 關聯的 UI 元件，用於生命週期管理
            job_attr: 儲存 job ID 的屬性名稱
            delay_ms: 延遲毫秒數
            callback: 延遲結束後執行的回呼函式
            owner: 持有 job 屬性的物件，若未指定則使用 widget

        Returns:
            Any | None: 建立成功的 Job ID，失敗則回傳 None
        """
        holder = owner if owner is not None else widget
        if not UIUtils._is_schedulable_widget(widget, holder, job_attr):
            return None
        UIUtils.cancel_scheduled_job(widget, job_attr, owner=holder)

        def _runner() -> None:
            setattr(holder, job_attr, None)
            try:
                callback()
            except Exception as e:
                logger.exception(f"執行 debounce callback 失敗 {job_attr}: {e}")

        try:
            if isinstance(widget, QtCore.QObject):
                job_id = invoke_later(max(0, int(delay_ms)), _runner, parent=widget)
            elif hasattr(widget, "schedule"):
                job_id = widget.schedule(max(0, int(delay_ms)), _runner)
            else:
                return None
            setattr(holder, job_attr, job_id)
            return job_id
        except Exception as e:
            logger.debug(f"建立 debounce 排程失敗 {job_attr}: {e}")
            setattr(holder, job_attr, None)
            return None

    @staticmethod
    def schedule_coalesced_idle(
        widget, job_attr: str, callback: Callable[[], Any], *, owner: Any | None = None
    ) -> Any | None:
        """
        建立合併的閒置排程 (Coalesced Idle)
        將任務排在 UI 執行緒的下一次閒置週期執行，避免重複排程

        Args:
            widget: 關聯的 UI 元件，用於生命週期管理
            job_attr: 儲存 job ID 的屬性名稱
            callback: 閒置時執行的回呼函式
            owner: 持有 job 屬性的物件，若未指定則使用 widget

        Returns:
            Any | None: 建立成功的 Job ID，失敗則回傳 None
        """
        holder = owner if owner is not None else widget
        if getattr(holder, job_attr, None):
            return getattr(holder, job_attr, None)
        if not UIUtils._is_schedulable_widget(widget, holder, job_attr):
            return None

        def _runner() -> None:
            setattr(holder, job_attr, None)
            try:
                callback()
            except Exception as e:
                logger.exception(f"執行 idle callback 失敗 {job_attr}: {e}")

        try:
            if isinstance(widget, QtCore.QObject):
                job_id = invoke_later(0, _runner, parent=widget)
            elif hasattr(widget, "schedule_idle"):
                job_id = widget.schedule_idle(_runner)
            elif hasattr(widget, "schedule"):
                job_id = widget.schedule(0, _runner)
            else:
                return None
            setattr(holder, job_attr, job_id)
            return job_id
        except Exception as e:
            logger.debug(f"建立 idle 合併排程失敗 {job_attr}: {e}")
            setattr(holder, job_attr, None)
            return None

    @staticmethod
    def schedule_throttle(
        widget,
        job_attr: str,
        interval_ms: int,
        callback: Callable[[], Any],
        *,
        owner: Any | None = None,
        trailing: bool = True,
        last_run_attr: str | None = None,
    ) -> bool:
        """
        建立節流 (Throttle) 排程
        確保回呼函式在指定時間間隔內最多僅執行一次

        Args:
            widget: 關聯的 UI 元件，用於生命週期管理
            job_attr: 儲存 job ID 的屬性名稱
            interval_ms: 節流間隔毫秒數
            callback: 要執行的回呼函式
            owner: 持有 job 屬性的物件，若未指定則使用 widget
            trailing: 是否在節流結束後執行最後一次呼叫
            last_run_attr: 儲存最後執行時間的屬性名稱

        Returns:
            bool: 是否成功排程或立即執行
        """
        holder = owner if owner is not None else widget
        if not widget:
            return False
        interval_ms = max(1, int(interval_ms))
        if last_run_attr is None:
            last_run_attr = f"{job_attr}_last_run_ms"
        try:
            if isinstance(widget, QtCore.QObject) and not is_qobject_alive(widget):
                return False
            if hasattr(widget, "is_alive") and (not widget.is_alive()):
                return False
        except Exception:
            return False
        now_ms = int(time.monotonic() * 1000)
        last_run_ms = int(getattr(holder, last_run_attr, 0) or 0)
        elapsed = now_ms - last_run_ms

        def _run_now() -> None:
            setattr(holder, last_run_attr, int(time.monotonic() * 1000))
            try:
                callback()
            except Exception as e:
                logger.exception(f"執行 throttle callback 失敗 {job_attr}: {e}")

        if elapsed >= interval_ms:
            UIUtils.cancel_scheduled_job(widget, job_attr, owner=holder)
            _run_now()
            return True
        if trailing and (not getattr(holder, job_attr, None)):
            remaining = max(1, interval_ms - elapsed)

            def _runner() -> None:
                setattr(holder, job_attr, None)
                _run_now()

            try:
                if isinstance(widget, QtCore.QObject):
                    setattr(holder, job_attr, invoke_later(remaining, _runner, parent=widget))
                elif hasattr(widget, "schedule"):
                    setattr(holder, job_attr, widget.schedule(remaining, _runner))
                else:
                    return False
            except Exception as e:
                logger.debug(f"建立 throttle 排程失敗 {job_attr}: {e}")
                setattr(holder, job_attr, None)
                return False
        return False

    @staticmethod
    def _dispatch_dialog(fn: Callable, *args, **kwargs) -> Any:
        if _is_ui_thread():
            return fn(*args, **kwargs)
        return run_on_ui_thread(lambda: fn(*args, **kwargs), timeout=None)

    @staticmethod
    def _play_message_sound(level: str) -> None:
        """根據訊息層級播放對應的系統音效"""
        sound_map = {
            "error": winsound.MB_ICONHAND,
            "warning": winsound.MB_ICONEXCLAMATION,
            "info": winsound.MB_ICONASTERISK,
        }
        flag = sound_map.get(level)
        if flag is not None:
            winsound.MessageBeep(flag)

    @staticmethod
    def show_message(
        title: str,
        message: str,
        parent=None,
        message_level: str = "info",
    ) -> None:
        """
        顯示訊息對話框，並根據層級播放對應的系統音效

        Args:
            title: 對話框標題
            message: 對話框訊息內容
            parent: 父層視窗
            message_level: 訊息層級，'error'、'warning' 或 'info'
        """

        def _show():
            nonlocal parent
            if parent is None:
                parent = QApplication.activeWindow()
            UIUtils._play_message_sound(message_level)
            w = MessageBox(title, message, parent)
            w.yesButton.setText("確定")
            w.cancelButton.hide()
            w.exec()

        UIUtils._dispatch_dialog(_show)

    @staticmethod
    def ask_yes_no_cancel(
        title: str = "確認", message: str = "請選擇操作", parent=None, show_cancel: bool = True
    ) -> bool | None:
        """
        顯示是/否/取消確認對話框

        Args:
            title: 對話框標題
            message: 對話框訊息內容
            parent: 父層視窗
            show_cancel: 是否顯示取消按鈕；若為 False，取消按鈕將顯示為「否」

        Returns:
            bool | None: 是回傳 True，否/取消回傳 False 或 None
        """

        def _show():
            nonlocal parent
            if parent is None:
                parent = QApplication.activeWindow()
            w = MessageBox(title, message, parent)
            w.yesButton.setText("是")
            if show_cancel:
                w.cancelButton.setText("取消")
            else:
                w.cancelButton.setText("否")
            return bool(w.exec())

        return UIUtils._dispatch_dialog(_show)

    @staticmethod
    def reveal_in_explorer(target) -> None:
        """
        在檔案總管中顯示指定路徑

        Args:
            target: 要在檔案總管中顯示的檔案或資料夾路徑
        """
        target_path = Path(target)
        try:
            if target_path.exists():
                target_path = target_path.resolve()
            target_str = str(Path(target_path).expanduser())
            if os.name == "nt" and not UIUtils._is_safe_windows_path_argument(target_str):
                logger.error("在檔案總管中顯示失敗：路徑包含不安全字元")
                return
            explorer = PathUtils.find_executable("explorer") or str(
                Path(os.environ.get("WINDIR", "C:\\Windows")) / "explorer.exe"
            )
            try:
                SubprocessUtils.run_checked([explorer, "/select,", target_str], check=False)
                return
            except Exception as e:
                logger.debug(f"使用 explorer /select 失敗: {e}")
            folder_path = target_path if target_path.is_dir() else target_path.parents[0]
            UIUtils.open_external(str(folder_path))
        except Exception as e:
            logger.exception(f"在檔案總管中顯示失敗: {e}")

    @staticmethod
    def _is_safe_windows_path_argument(path_text: str) -> bool:
        if not path_text:
            return False
        return all(ch not in path_text for ch in ('"', "\x00", "\r", "\n"))

    @staticmethod
    def open_external(target) -> None:
        """
        使用系統預設程式開啟外部資源（網址或檔案路徑）

        Args:
            target: 要開啟的 URL 或檔案路徑
        """
        try:
            target_str = str(target)
            if target_str.startswith(("http://", "https://")):
                webbrowser.open(target_str)
                return
            try:
                target_path = Path(target_str)
                if target_path.exists():
                    target_str = str(target_path.resolve())
                elif not target_str.startswith("http"):
                    logger.error(f"開啟外部資源失敗：路徑不存在 - {target_str}")
                    return
            except Exception as e:
                logger.debug(f"檢查路徑存在性時發生例外: {e}")
            try:
                startfile = getattr(os, "startfile", None)
                if callable(startfile):
                    startfile(target_str)
                    return
            except Exception as e:
                logger.debug(f"os.startfile 失敗，嘗試 subprocess: {e}")
            try:
                explorer = PathUtils.find_executable("explorer") or str(
                    Path(os.environ.get("WINDIR", "C:\\Windows")) / "explorer.exe"
                )
                try:
                    SubprocessUtils.run_checked([explorer, target_str], check=True)
                    return
                except Exception as e:
                    logger.debug(f"使用 explorer 開啟失敗: {e}")
            except Exception as e:
                logger.exception(f"透過系統開啟外部資源失敗: {target_str} - {e}")
        except Exception as e:
            logger.exception(f"開啟外部資源失敗: {e}")


class ScrollableComboBox(ComboBox):
    """支援滾輪切換選項的下拉選單"""

    def wheelEvent(self, event):
        """
        處理滾輪事件以切換下拉選單選項

        Args:
            event: 滾輪事件物件
        """
        delta = event.angleDelta().y()
        if delta == 0:
            return

        step = -1 if delta > 0 else 1
        current_index = self.currentIndex()
        new_index = current_index + step

        if 0 <= new_index < self.count():
            self.setCurrentIndex(new_index)

        event.accept()
