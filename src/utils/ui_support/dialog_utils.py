"""對話框與視窗生命週期工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import (
    NativeQtStyle,
    QtCore,
    QtWidgets,
    Sizes,
    Spacing,
    WindowManager,
    ensure_application,
    get_logger,
    invoke_later,
    is_qobject_alive,
    run_on_ui_thread,
    set_modal,
    set_topmost,
    show_window,
)
from ..ui_support import qt_widgets as qt

logger = get_logger().bind(component="DialogUtils")


class _NativeDialog(QtWidgets.QDialog):
    """原生 QDialog，補上專案共用的關閉與鍵盤事件管理。"""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._exists = True
        self._force_destroy = False
        self._close_callback = None
        self._event_handlers: dict[str, Any] = {}
        self.setWindowFlag(QtCore.Qt.WindowType.WindowSystemMenuHint, True)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowCloseButtonHint, True)
        self.installEventFilter(self)

    def set_close_callback(self, callback) -> None:
        self._close_callback = callback

    def closeEvent(self, event) -> None:
        """處理 Qt 視窗關閉事件。"""
        if self._force_destroy:
            self._exists = False
            event.accept()
            return
        callback = self._close_callback
        if callback is None:
            self._exists = False
            event.accept()
            return
        result = callback()
        if result is False:
            event.ignore()
            return
        if not self._force_destroy and self.isVisible():
            event.ignore()
            return
        self._exists = False
        event.accept()

    def destroy(self, *_args, **_kwargs) -> None:
        """銷毀元件並清理底層 Qt 資源。"""
        self._force_destroy = True
        self._exists = False
        self.close()
        self.deleteLater()

    def is_alive(self) -> bool:
        return bool(self._exists) and is_qobject_alive(self)

    def configure(self, **kwargs: Any) -> None:
        """更新元件設定並套用到實際 Qt widget。"""
        bg = kwargs.get("bg") or kwargs.get("background") or kwargs.get("fg_color")
        if bg is not None:
            if isinstance(bg, tuple):
                index = 1 if qt.is_dark_color_scheme() and len(bg) > 1 else 0
                bg = bg[index]
            self.setStyleSheet(f"QDialog {{ background: {bg}; }}{NativeQtStyle.dialog_controls}")

    config = configure

    def connect_event(self, event_name: str, callback, *, append: bool = False) -> str:
        if append and event_name in self._event_handlers:
            previous = self._event_handlers[event_name]

            def chained(event) -> Any:
                """串接事件處理器並保留原有事件流程。"""
                previous(event)
                return callback(event)

            self._event_handlers[event_name] = chained
            return str(id(chained))
        self._event_handlers[event_name] = callback
        return str(id(callback))

    def eventFilter(self, watched, event) -> bool:
        """攔截 Qt 事件並依目前元件狀態處理。"""
        if watched is not self or event.type() != QtCore.QEvent.Type.KeyPress:
            return False
        event_name = ""
        if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            event_name = "return_pressed"
        elif event.key() == QtCore.Qt.Key.Key_Escape:
            event_name = "escape_pressed"
        callback = self._event_handlers.get(event_name)
        if callback is None:
            return False
        return callback(event) == "break"

    def clipboard_clear(self) -> None:
        ensure_application().clipboard().clear()

    def clipboard_append(self, text: str) -> None:
        ensure_application().clipboard().setText(str(text))


@dataclass(frozen=True)
class _DialogWindowOptions:
    width: int | None
    height: int | None
    bind_icon: bool
    center_on_parent: bool
    make_modal: bool
    delay_ms: int
    topmost: bool
    autosize_to_content: bool
    min_width: int | None
    min_height: int | None
    start_maximized: bool
    reveal_after_setup: bool


class DialogUtils:
    """集中管理對話框建立、置中與顯示流程。"""

    @staticmethod
    def apply_standard_dialog_style(window: QtWidgets.QWidget) -> None:
        """
        套用新視窗共用控制項樣式。

        Args:
            window: 要套用對話框共用樣式的 Qt 視窗。
        """
        try:
            window.setStyleSheet(NativeQtStyle.generic_dialog)
        except Exception as e:
            logger.debug(f"套用對話框共用樣式失敗: {e}", "DialogUtils")

    @staticmethod
    def _setup_dialog_geometry(window: Any, parent: Any, options: _DialogWindowOptions) -> tuple[int, int]:
        WindowManager.setup_dialog_window(
            window,
            parent=parent,
            width=options.width,
            height=options.height,
            center_on_parent=options.center_on_parent,
        )
        return (
            int(options.min_width) if options.min_width else 0,
            int(options.min_height) if options.min_height else 0,
        )

    @staticmethod
    def setup_window_properties(
        window,
        parent=None,
        width=None,
        height=None,
        bind_icon=True,
        center_on_parent=True,
        make_modal=True,
        delay_ms=200,
        topmost: bool = False,
        autosize_to_content: bool = False,
        min_width: int | None = None,
        min_height: int | None = None,
        start_maximized: bool = False,
        reveal_after_setup: bool = True,
    ) -> None:
        """
        統一的視窗屬性設定函數，整合圖示綁定、視窗置中、模態設定三個功能。

        Args:
            window: 要設定的視窗。
            parent: 父視窗。
            width: 初始寬度。
            height: 初始高度。
            其他參數: 控制圖示、模態、最大尺寸與顯示行為。
        """
        options = _DialogWindowOptions(
            width=width,
            height=height,
            bind_icon=bind_icon,
            center_on_parent=center_on_parent,
            make_modal=make_modal,
            delay_ms=delay_ms,
            topmost=topmost,
            autosize_to_content=autosize_to_content,
            min_width=min_width,
            min_height=min_height,
            start_maximized=start_maximized,
            reveal_after_setup=reveal_after_setup,
        )
        if not isinstance(window, QtWidgets.QWidget):
            logger.debug("略過非 Qt widget 的視窗屬性設定", "DialogUtils")
            return
        DialogUtils._setup_native_window_properties(window=window, parent=parent, options=options)

    @staticmethod
    def _setup_native_window_properties(
        *,
        window: QtWidgets.QWidget,
        parent=None,
        options: _DialogWindowOptions,
    ) -> None:
        """設定原生 Qt 視窗屬性。"""
        # 為所有視窗類型設定視窗控制按鈕
        window.setWindowFlag(QtCore.Qt.WindowType.WindowSystemMenuHint, True)
        window.setWindowFlag(QtCore.Qt.WindowType.WindowMinimizeButtonHint, True)
        window.setWindowFlag(QtCore.Qt.WindowType.WindowMaximizeButtonHint, True)
        window.setWindowFlag(QtCore.Qt.WindowType.WindowCloseButtonHint, True)

        scaled_min_width, scaled_min_height = DialogUtils._setup_dialog_geometry(window, parent, options)
        if scaled_min_width or scaled_min_height:
            window.setMinimumSize(max(1, scaled_min_width), max(1, scaled_min_height))
        if options.make_modal and isinstance(window, QtWidgets.QDialog):
            set_modal(window, parent if isinstance(parent, QtWidgets.QWidget) else None)
        set_topmost(window, options.topmost)
        if options.bind_icon:
            from ..ui_support.icon_utils import IconUtils

            IconUtils.set_window_icon(window, options.delay_ms)
        if options.autosize_to_content:
            invoke_later(
                0,
                lambda: DialogUtils.autosize_toplevel_to_content(
                    window,
                    min_width=int(options.min_width or options.width or 0),
                    min_height=int(options.min_height or options.height or 0),
                    parent=parent,
                ),
                parent=window,
            )
        if options.start_maximized:
            invoke_later(max(0, int(options.delay_ms)), lambda: DialogUtils.maximize_window(window), parent=window)
        if options.reveal_after_setup:
            invoke_later(0, lambda: show_window(window), parent=window)

    @staticmethod
    def maximize_window(window) -> None:
        """
        將對話框最大化，並兼容不同視窗管理器的行為。

        Args:
            window: 要最大化的視窗。
        """

        if not window:
            return
        if isinstance(window, QtWidgets.QWidget):
            window.showMaximized()

    @staticmethod
    def create_toplevel_dialog(
        parent,
        title: str,
        *,
        width: int | None = None,
        height: int | None = None,
        resizable: bool = True,
        bind_icon: bool = True,
        center_on_parent: bool = True,
        make_modal: bool = True,
        delay_ms: int = 200,
        topmost: bool = False,
        autosize_to_content: bool = False,
        min_width: int | None = None,
        min_height: int | None = None,
        reveal_after_setup: bool = True,
        start_maximized: bool = False,
    ) -> Any:
        """
        建立並套用專案一致的 dialog 視窗屬性。

        Args:
            parent: 父視窗。
            title: 視窗標題。
            其他參數: 控制尺寸、模態、圖示與顯示行為。

        Returns:
            建立好的對話框視窗物件。
        """
        dialog: Any = _NativeDialog(parent if isinstance(parent, QtWidgets.QWidget) else None)
        if reveal_after_setup:
            try:
                dialog.hide()
            except Exception as e:
                logger.debug(f"建立對話框時預先隱藏失敗: {e}", "DialogUtils")
        dialog.setWindowTitle(title)
        dialog.setWindowFlag(QtCore.Qt.WindowType.WindowMinimizeButtonHint, True)
        dialog.setWindowFlag(QtCore.Qt.WindowType.WindowMaximizeButtonHint, resizable)
        dialog.setWindowFlag(QtCore.Qt.WindowType.WindowCloseButtonHint, True)
        DialogUtils.apply_standard_dialog_style(dialog)
        size_policy = QtWidgets.QSizePolicy.Policy.Expanding if resizable else QtWidgets.QSizePolicy.Policy.Fixed
        dialog.setSizePolicy(size_policy, size_policy)
        DialogUtils.setup_window_properties(
            window=dialog,
            parent=parent,
            width=width,
            height=height,
            bind_icon=bind_icon,
            center_on_parent=center_on_parent,
            make_modal=make_modal,
            delay_ms=delay_ms,
            topmost=topmost,
            autosize_to_content=autosize_to_content,
            min_width=min_width,
            min_height=min_height,
            start_maximized=start_maximized,
            reveal_after_setup=reveal_after_setup,
        )
        return dialog

    @staticmethod
    def schedule_toplevel_layout_refresh(
        dialog,
        *,
        min_width: int = 0,
        min_height: int = 0,
        parent=None,
        delays_ms: tuple[int, ...] = (0, 120),
        preserve_current_size: bool = True,
    ) -> None:
        """
        在內容建構完成後重新整理對話框尺寸，降低初次開啟時被裁切的機率。

        Args:
            dialog: 要重新整理的對話框。
            min_width: 最小寬度。
            min_height: 最小高度。
            parent: 父視窗。
            delays_ms: 要排程的延遲時間序列。
            preserve_current_size: 是否保留目前大小。
        """
        if not dialog:
            return
        for delay_ms in delays_ms:
            invoke_later(
                max(0, int(delay_ms)),
                lambda: DialogUtils.autosize_toplevel_to_content(
                    dialog,
                    min_width=min_width,
                    min_height=min_height,
                    parent=parent,
                    preserve_current_size=preserve_current_size,
                ),
                parent=dialog if isinstance(dialog, QtWidgets.QWidget) else None,
            )

    @staticmethod
    def autosize_toplevel_to_content(
        dialog,
        *,
        min_width: int = 0,
        min_height: int = 0,
        parent=None,
        preserve_current_size: bool = True,
    ) -> None:
        """
        依內容實際需求調整對話框大小，避免初次開啟時過小。

        Args:
            dialog: 要調整大小的對話框。
            min_width: 最小寬度。
            min_height: 最小高度。
            parent: 父視窗。
            preserve_current_size: 是否保留目前大小。
        """
        if not dialog:
            return
        if not isinstance(dialog, QtWidgets.QWidget):
            return
        hint = dialog.sizeHint()
        current = dialog.size()
        target_width = max(int(min_width), hint.width())
        target_height = max(int(min_height), hint.height())
        if preserve_current_size:
            target_width = max(target_width, current.width())
            target_height = max(target_height, current.height())
        WindowManager.setup_dialog_window(
            dialog, parent=parent, width=target_width, height=target_height, center_on_parent=True
        )

    @staticmethod
    def _show_qt_messagebox(
        title: str,
        message: str,
        parent=None,
        topmost: bool = False,
        log_level: str = "error",
    ) -> None:
        """Qt 專用的訊息對話框顯示方法。"""
        log_msg = f"{title}: {message}"
        if log_level == "error":
            logger.error(log_msg)
        elif log_level == "warning":
            logger.warning(log_msg)
        else:
            logger.debug(log_msg)

        def _show() -> None:
            try:
                icon = {
                    "error": QtWidgets.QMessageBox.Icon.Critical,
                    "warning": QtWidgets.QMessageBox.Icon.Warning,
                }.get(log_level, QtWidgets.QMessageBox.Icon.Information)
                parent_widget = parent if isinstance(parent, QtWidgets.QWidget) and is_qobject_alive(parent) else None
                box = QtWidgets.QMessageBox(parent_widget)
                box.setWindowTitle(title)
                box.setText(message)
                box.setIcon(icon)
                box.setStyleSheet(NativeQtStyle.message_box)
                if topmost:
                    box.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
                from ..ui_support.icon_utils import IconUtils

                IconUtils.set_window_icon(box, 25)
                box.exec()
            except Exception as e:
                logger.exception(f"顯示訊息對話框失敗: {e}")
                if log_level == "error":
                    logger.error(f"錯誤: {title} - {message}")
                elif log_level == "warning":
                    logger.warning(f"警告: {title} - {message}")

        try:
            app = ensure_application()
            if QtCore.QThread.currentThread() != app.thread():
                invoke_later(0, _show, parent=parent if isinstance(parent, QtWidgets.QWidget) else None)
                return
            _show()
        except Exception:
            try:
                _show()
            except Exception as e:
                logger.exception(f"顯示訊息對話框失敗(備援): {e}")

    @staticmethod
    def show_error(title: str = "錯誤", message: str = "發生未知錯誤", parent=None, topmost: bool = False) -> None:
        """
        顯示錯誤訊息對話框。

        Args:
            title: 對話框標題。
            message: 要顯示的訊息。
            parent: 父視窗。
            topmost: 是否置頂。
        """
        DialogUtils._show_qt_messagebox(title, message, parent, topmost, "error")

    @staticmethod
    def show_warning(title: str = "警告", message: str = "警告訊息", parent=None, topmost: bool = False) -> None:
        """
        顯示警告訊息對話框。

        Args:
            title: 對話框標題。
            message: 要顯示的訊息。
            parent: 父視窗。
            topmost: 是否置頂。
        """
        DialogUtils._show_qt_messagebox(title, message, parent, topmost, "warning")

    @staticmethod
    def show_info(title: str = "資訊", message: str = "資訊訊息", parent=None, topmost: bool = False) -> None:
        """
        顯示資訊對話框。

        Args:
            title: 對話框標題。
            message: 要顯示的訊息。
            parent: 父視窗。
            topmost: 是否置頂。
        """
        DialogUtils._show_qt_messagebox(title, message, parent, topmost, "info")

    @staticmethod
    def ask_yes_no_cancel(
        title: str = "確認", message: str = "請選擇操作", parent=None, show_cancel: bool = True, topmost: bool = False
    ) -> bool | None:
        """
        顯示確認對話框，支援是/否/取消選項。

        Args:
            title: 對話框標題。
            message: 要顯示的訊息。
            parent: 父視窗。
            show_cancel: 是否顯示取消按鈕。
            topmost: 是否置頂。

        Returns:
            使用者選擇結果；是/否 對應 True/False，取消時回傳 None。
        """

        def _ask() -> bool | None:
            try:
                parent_widget = parent if isinstance(parent, QtWidgets.QWidget) and is_qobject_alive(parent) else None
                buttons = QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
                if show_cancel:
                    buttons |= QtWidgets.QMessageBox.StandardButton.Cancel
                box = QtWidgets.QMessageBox(parent_widget)
                box.setWindowTitle(title)
                box.setText(message)
                box.setIcon(QtWidgets.QMessageBox.Icon.Question)
                box.setStandardButtons(buttons)
                box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Yes)
                box.setStyleSheet(NativeQtStyle.message_box)
                if topmost:
                    box.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
                from ..ui_support.icon_utils import IconUtils

                IconUtils.set_window_icon(box, 25)
                result = box.exec()
                if result == QtWidgets.QMessageBox.StandardButton.Yes:
                    return True
                if result == QtWidgets.QMessageBox.StandardButton.No:
                    return False
                return None
            except Exception as e:
                logger.exception(f"顯示確認對話框失敗: {e}")
                return False if not show_cancel else None

        try:
            app = ensure_application()
            if QtCore.QThread.currentThread() != app.thread():
                return run_on_ui_thread(_ask)
            return _ask()
        except Exception:
            try:
                return _ask()
            except Exception:
                return False if not show_cancel else None

    @staticmethod
    def show_manual_restart_dialog(parent, details: str | None) -> None:
        """
        顯示需要手動重啟的對話框，並提供複製診斷按鈕。

        Args:
            parent: 父視窗。
            details: 要顯示的診斷內容。
        """
        try:
            dialog = DialogUtils.create_toplevel_dialog(
                parent,
                "需要手動重啟",
                width=Sizes.DIALOG_MEDIUM_WIDTH,
                height=Sizes.DIALOG_SMALL_HEIGHT,
                make_modal=True,
            )
            qt.Label(dialog, text="設定已變更，但需要手動重新啟動應用程式。", anchor="w").attach(
                fill="x", padx=Spacing.MEDIUM, pady=(Spacing.MEDIUM, Spacing.TINY)
            )
            text_box = qt.TextBox(dialog, wrap="word", height=Spacing.MEDIUM)
            text_box.attach(fill="both", expand=True, padx=Spacing.MEDIUM, pady=(0, Spacing.SMALL))
            text_box.insert("1.0", details or "")
            text_box.setReadOnly(True)

            def _copy() -> None:
                try:
                    app = qt.ensure_app()
                    if app is not None:
                        with qt.context_suppress():
                            app.clipboard().setText(details or "")
                            app.processEvents()
                except Exception as exc:
                    logger.debug(f"複製診斷內容失敗: {exc}")

            button_frame = qt.Frame(dialog)
            button_frame.attach(fill="x", padx=Spacing.MEDIUM, pady=(0, Spacing.MEDIUM))
            qt.Button(button_frame, text="複製診斷", command=_copy).attach(side="left")
            qt.Button(button_frame, text="我會手動重啟", command=dialog.destroy).attach(side="right")
        except Exception:
            DialogUtils.show_info("需要手動重啟", f"設定已變更，但自動重啟失敗。\n\n診斷：\n{details}", parent=parent)


__all__ = ["DialogUtils"]
