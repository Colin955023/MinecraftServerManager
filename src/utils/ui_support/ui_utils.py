"""UI 工具函數
提供常用的界面元件和工具函數，避免重複程式碼。
"""

import os
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...ui import DialogUtils, FontManager
from .. import Colors, PathUtils, SubprocessUtils, get_logger
from . import qt_widgets as qt
from .qt_runtime import QtCore, QtWidgets, cancel_timer, invoke_later, is_qobject_alive, run_on_ui_thread

logger = get_logger().bind(component="UIUtils")


def _is_ui_thread() -> bool:
    app = QtWidgets.QApplication.instance()
    return app is None or QtCore.QThread.currentThread() is app.thread()


def get_button_style(button_type: str = "primary") -> dict[str, tuple[str, str]]:
    """取得按鈕樣式配置

    Args:
        button_type: 按鈕類型 ("primary", "secondary", "warning", "danger")

    Returns:
        包含 fg_color 和 hover_color 的字典
    """
    styles = {
        "primary": {"fg_color": Colors.BUTTON_PRIMARY, "hover_color": Colors.BUTTON_PRIMARY_HOVER},
        "secondary": {"fg_color": Colors.BUTTON_SECONDARY, "hover_color": Colors.BUTTON_SECONDARY_HOVER},
        "warning": {"fg_color": Colors.BUTTON_WARNING, "hover_color": Colors.BUTTON_WARNING_HOVER},
        "danger": {"fg_color": Colors.BUTTON_DANGER, "hover_color": Colors.BUTTON_DANGER_HOVER},
    }
    return styles.get(button_type, styles["primary"])


def compute_adaptive_pool_limit(
    *,
    current: int,
    min_size: int,
    cap_size: int,
    step: int,
    pool_len: int,
    hit_rate: float,
    low_hit_threshold: float = 35.0,
    high_hit_threshold: float = 90.0,
    idle_divisor: int = 4,
) -> int:
    """依命中率與池使用狀態，回傳建議的 recycle pool 上限。

    Args:
        current: 目前池大小。
        min_size: 最小池大小。
        cap_size: 最大池大小。
        step: 每次調整的步進值。
        pool_len: 目前池中元素數量。
        hit_rate: 命中率百分比。
        low_hit_threshold: 低命中率門檻。
        high_hit_threshold: 高命中率門檻。
        idle_divisor: 低使用率時的縮減比例。

    Returns:
        建議的池上限值。
    """
    current = max(1, int(current))
    min_size = max(1, int(min_size))
    cap_size = max(min_size, int(cap_size))
    step = max(1, int(step))
    pool_len = max(0, int(pool_len))
    idle_divisor = max(1, int(idle_divisor))
    new_size = current
    if hit_rate < low_hit_threshold and current < cap_size:
        new_size = min(cap_size, current + step)
    elif hit_rate > high_hit_threshold and pool_len < max(1, current // idle_divisor) and (current > min_size):
        new_size = max(min_size, current - step)
    return new_size


def compute_exponential_moving_average(*, previous: float | None, current: float, alpha: float = 0.35) -> float:
    """計算 EMA（Exponential Moving Average）並限制 alpha 於 [0, 1]。

    Args:
        previous: 前一筆 EMA 值。
        current: 目前樣本值。
        alpha: 平滑係數。

    Returns:
        更新後的 EMA 值。
    """
    clamped_alpha = max(0.0, min(1.0, float(alpha)))
    current_value = float(current)
    if previous is None:
        return current_value
    return clamped_alpha * current_value + (1.0 - clamped_alpha) * float(previous)


class UIUtils:
    """UI 共用工具與對話框包裝。"""

    @staticmethod
    def pack_main_frame(frame, padx: int | None = None, pady: int | None = None) -> None:
        """統一的主框架布局方法。

        Args:
            frame: 要配置的主框架。
            padx: 水平邊距。
            pady: 垂直邊距。
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
        frame.attach(fill="both", expand=True, padx=padx, pady=pady)

    @staticmethod
    def get_mousewheel_units(delta: int) -> int:
        """將原生 MouseWheel 的 delta 轉為視窗滾動單位。

        回傳值符合清單滾動介面的單位格式。
        """
        if delta == 0:
            return 0
        units = int(-delta / 120)
        if units == 0:
            return -1 if delta > 0 else 1
        return units

    @staticmethod
    def cancel_scheduled_job(widget, job_attr: str, *, owner: Any | None = None) -> None:
        """取消指定的排程工作。

        Args:
            widget: 排程所在的 widget。
            job_attr: 用來保存 job id 的屬性名稱。
            owner: 自訂 job holder 物件。
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
        """以 debounce 方式排程：新的呼叫會覆蓋尚未執行的舊工作。

        Args:
            widget: 排程所在的 widget。
            job_attr: 用來保存 job id 的屬性名稱。
            delay_ms: 延遲毫秒數。
            callback: 要執行的回呼。
            owner: 自訂 job holder 物件。

        Returns:
            建立的 job id，失敗時回傳 None。
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
        """合併多次請求為單次 `schedule_idle` 執行。

        Args:
            widget: 排程所在的 widget。
            job_attr: 用來保存 job id 的屬性名稱。
            callback: 要執行的回呼。
            owner: 自訂 job holder 物件。

        Returns:
            建立的 job id，失敗時回傳 None。
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
        """節流排程：限制 callback 執行頻率，必要時保留尾端一次執行。

        Args:
            widget: 排程所在的 widget。
            job_attr: 用來保存 job id 的屬性名稱。
            interval_ms: 最小執行間隔毫秒數。
            callback: 要執行的回呼。
            owner: 自訂 job holder 物件。
            trailing: 是否在節流期間保留尾端執行。
            last_run_attr: 保存上次執行時間的屬性名稱。

        Returns:
            若 callback 立即執行則回傳 True，否則回傳 False。
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
    def attach_tooltip(
        widget,
        text: str,
        *,
        bg: str = "#2b2b2b",
        fg: str = "white",
        font=None,
        padx: int = 4,
        pady: int = 2,
        wraplength: int | None = None,
        justify: str = "left",
        borderwidth: int = 0,
        relief: str = "flat",
        offset_x: int = 5,
        offset_y: int = 5,
        show_delay_ms: int = 0,
        auto_hide_ms: int | None = None,
    ) -> None:
        """替 widget 綁定原生 Qt tooltip。

        Args:
            widget: 要綁定提示的 widget。
            text: 提示文字。
            bg: 背景色。
            fg: 文字顏色。
            font: 字型設定。
            padx: 內距水平值。
            pady: 內距垂直值。
            wraplength: 換行寬度。
            justify: 文字對齊方式。
            borderwidth: 邊框寬度。
            relief: 邊框樣式。
            offset_x: 水平偏移量。
            offset_y: 垂直偏移量。
            show_delay_ms: 顯示延遲毫秒數。
            auto_hide_ms: 自動隱藏毫秒數。
        """
        _ = (bg, fg, font, padx, pady, wraplength, justify, borderwidth, relief, offset_x, offset_y, show_delay_ms)
        if not widget:
            return
        try:
            if hasattr(widget, "setToolTip"):
                widget.setToolTip(text or "")
                if auto_hide_ms and hasattr(widget, "setToolTipDuration"):
                    widget.setToolTipDuration(int(auto_hide_ms))
                return
            widget._tooltip_text = text or ""
        except Exception as e:
            logger.exception(f"綁定 tooltip 事件失敗: {e}")

    @staticmethod
    def show_error(title: str = "錯誤", message: str = "發生未知錯誤", parent=None, topmost: bool = False) -> None:
        """顯示錯誤訊息對話框。

        Args:
            title: 對話框標題。
            message: 錯誤訊息。
            parent: 父視窗。
            topmost: 是否置頂。
        """
        if _is_ui_thread():
            DialogUtils.show_error(title, message, parent, topmost)
            return
        run_on_ui_thread(lambda: DialogUtils.show_error(title, message, parent, topmost), timeout=None)

    @staticmethod
    def show_warning(title: str = "警告", message: str = "警告訊息", parent=None, topmost: bool = False) -> None:
        """顯示警告訊息對話框。

        Args:
            title: 對話框標題。
            message: 警告訊息。
            parent: 父視窗。
            topmost: 是否置頂。
        """
        if _is_ui_thread():
            DialogUtils.show_warning(title, message, parent, topmost)
            return
        run_on_ui_thread(lambda: DialogUtils.show_warning(title, message, parent, topmost), timeout=None)

    @staticmethod
    def show_info(title: str = "資訊", message: str = "資訊訊息", parent=None, topmost: bool = False) -> None:
        """顯示資訊對話框。

        Args:
            title: 對話框標題。
            message: 資訊訊息。
            parent: 父視窗。
            topmost: 是否置頂。
        """
        if _is_ui_thread():
            DialogUtils.show_info(title, message, parent, topmost)
            return
        run_on_ui_thread(lambda: DialogUtils.show_info(title, message, parent, topmost), timeout=None)

    @staticmethod
    def reveal_in_explorer(target) -> None:
        """在檔案總管中顯示。

        Args:
            target: 要顯示的檔案或資料夾路徑。
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
        """檢查 Windows 指令列參數是否含有危險控制字元。"""
        if not path_text:
            return False
        return all(ch not in path_text for ch in ('"', "\x00", "\r", "\n"))

    @staticmethod
    def open_external(target) -> None:
        """使用系統預設程式開啟。

        Args:
            target: 要開啟的檔案、資料夾或 URL。
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

    @staticmethod
    def ask_yes_no_cancel(
        title: str = "確認", message: str = "請選擇操作", parent=None, show_cancel: bool = True, topmost: bool = False
    ) -> bool | None:
        """顯示確認對話框，支援是/否/取消選項。

        Args:
            title: 對話框標題。
            message: 提示訊息。
            parent: 父視窗。
            show_cancel: 是否顯示取消按鈕。
            topmost: 是否置頂。

        Returns:
            使用者選擇結果，或在無法判斷時回傳 None。
        """
        if _is_ui_thread():
            return DialogUtils.ask_yes_no_cancel(title, message, parent, show_cancel, topmost)
        return run_on_ui_thread(
            lambda: DialogUtils.ask_yes_no_cancel(title, message, parent, show_cancel, topmost), timeout=None
        )

    @staticmethod
    def sync_bool_string_state(bool_var, string_var) -> None:
        """建立 BoolState 與 TextState 的雙向綁定（用於 server.properties 等場景）

        Args:
            bool_var: qt.BoolState 布林變數
            string_var: qt.TextState 字串變數（"true"/"false"）
        """
        in_sync = False

        def update_string_var(*_args):
            """當布林變數改變時，更新字串變數"""
            nonlocal in_sync
            if in_sync:
                return
            in_sync = True
            try:
                new_value = "true" if bool_var.get() else "false"
                if string_var.get() != new_value:
                    string_var.set(new_value)
            finally:
                in_sync = False

        def update_bool_var(*_args):
            """當字串變數改變時，更新布林變數"""
            nonlocal in_sync
            if in_sync:
                return
            in_sync = True
            try:
                current = string_var.get().strip().lower()
                if current in ("true", "1", "yes", "on"):
                    normalized = "true"
                    new_bool = True
                else:
                    normalized = "false"
                    new_bool = False
                if string_var.get() != normalized:
                    string_var.set(normalized)
                if bool_var.get() != new_bool:
                    bool_var.set(new_bool)
            finally:
                in_sync = False

        bool_var.trace_add("write", update_string_var)
        string_var.trace_add("write", update_bool_var)

    @staticmethod
    def create_styled_button(parent, text, command, button_type="secondary", **kwargs) -> qt.Button:
        """建立統一樣式的按鈕。

        Args:
            parent: 父容器。
            text: 按鈕文字。
            command: 按鈕點擊回呼。
            button_type: 按鈕樣式類型。
            **kwargs: 額外的 `QtButton` 參數。

        Returns:
            建立完成的 `QtButton`。
        """
        if button_type == "primary":
            button_style = {
                "fg_color": ("#1f4e79", "#0f2a44"),
                "hover_color": ("#0f2a44", "#071925"),
                "text_color": ("#ffffff", "#ffffff"),
                "font": FontManager.get_font(family="Microsoft JhengHei", size=14, weight="bold"),
                "width": 135,
                "height": 45,
            }
        elif button_type == "secondary":
            button_style = {
                "fg_color": ("#2d3748", "#1a202c"),
                "hover_color": ("#1a202c", "#0d1117"),
                "text_color": ("#ffffff", "#ffffff"),
                "font": FontManager.get_font(family="Microsoft JhengHei", size=14),
                "width": 90,
                "height": 32,
            }
        elif button_type == "small":
            button_style = {
                "fg_color": ("#4a5568", "#2d3748"),
                "hover_color": ("#2d3748", "#1a202c"),
                "text_color": ("#ffffff", "#ffffff"),
                "font": FontManager.get_font(family="Microsoft JhengHei", size=14),
                "width": 60,
                "height": 23,
            }
        elif button_type == "cancel":
            button_style = {
                "fg_color": ("#dc2626", "#991b1b"),
                "hover_color": ("#991b1b", "#7f1d1d"),
                "text_color": ("#ffffff", "#ffffff"),
                "font": FontManager.get_font(family="Microsoft JhengHei", size=14),
                "width": 90,
                "height": 36,
            }
        else:
            button_style = {}
        final_style = {**button_style, **kwargs}
        return qt.Button(parent, text=text, command=command, **final_style)
