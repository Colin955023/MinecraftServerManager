"""模組管理頁面主框架"""

from __future__ import annotations

import queue
import re
import traceback
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QScrollBar,
    QSizePolicy,
    QStackedWidget,
    QTreeWidget,
    QVBoxLayout,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    Pivot,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    RadioButton,
    RoundMenu,
    SubtitleLabel,
    TextEdit,
    TitleLabel,
)

from src.core import LoaderManager, ModManager
from src.models import (
    ModStatus,
    ServerConfig,
)
from src.ui import (
    HostBound,
    LocalModListPresenter,
    ModManagementInstallExecutor,
    ModManagementQueueOps,
    ModManagementReviewOps,
    ModManagementSession,
    ModManagementTreeSyncOps,
    OnlineBrowsePresenter,
)
from src.ui import mod_management_logger as logger
from src.utils import (
    AppException,
    Colors,
    FloatState,
    PathUtils,
    ScrollableComboBox,
    Sizes,
    Spacing,
    TextState,
    UIUtils,
    UIWorkScope,
    apply_table_header_style,
    resolve_color,
)


def _is_alive(obj: Any) -> bool:
    if obj is None:
        return False
    if hasattr(obj, "is_alive"):
        return obj.is_alive()
    with suppress(ImportError):
        import shiboken6

        if isinstance(obj, QObject):
            return shiboken6.isValid(obj)
    return True


class _ModManagementSignals(QObject):
    progress_requested = Signal(float)

    def __init__(
        self,
        progress_callback: Callable[[float], None],
        drain_callback: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._progress_callback = progress_callback
        self._drain_callback = drain_callback
        self.progress_requested.connect(self._dispatch_progress)

    @Slot(float)
    def _dispatch_progress(self, value: float) -> None:
        self._progress_callback(value)

    @Slot()
    def drain(self) -> None:
        self._drain_callback()


class ModManagementFrame:
    """模組管理主畫面"""

    def __init__(
        self,
        parent,
        server_manager,
        on_server_selected_callback: Callable | None = None,
        loader_manager: LoaderManager = None,
    ):
        self.parent = parent
        self.server_manager = server_manager
        self.on_server_selected = on_server_selected_callback
        self.loader_manager = loader_manager
        self.mod_session = ModManagementSession()
        self.mod_manager: ModManager | None = None
        self.versions: list = []
        self.release_versions: list = []
        self.all_selected = False
        self.VERSION_PATTERN = re.compile("-([\\dv.]+)(?:\\.jar(?:\\.disabled)?)?$")
        self.main_frame: QFrame | None = None
        self.main_layout: QVBoxLayout | None = None
        self.notebook: QStackedWidget | None = None
        self.pivot: Pivot | None = None
        self.local_tab: QFrame | None = None
        self.browse_tab: QFrame | None = None
        self.browse_tree: QTreeWidget | None = None
        self.browse_filter_label: SubtitleLabel | None = None
        self.browse_results_label: SubtitleLabel | None = None
        self.local_tree: QTreeWidget | None = None
        self.local_v_scrollbar: QScrollBar | None = None
        self.local_h_scrollbar: QScrollBar | None = None
        self._local_filter_job: Any | None = None
        self.local_mod_list_presenter = LocalModListPresenter(self)
        self.online_browse_presenter = OnlineBrowsePresenter(self)
        self._online_mod_by_row_key: dict[str, Any] = {}
        self._status_update_job = None
        self.ui_queue: queue.Queue[Callable[[], Any]] = queue.Queue()

        self.create_widgets()

        host = self.main_frame if _is_alive(self.main_frame) else self.parent
        signal_parent = host if isinstance(host, QObject) and _is_alive(host) else None
        self._signals = _ModManagementSignals(self._apply_progress_value, self._drain_ui_queue, signal_parent)
        self._ui_queue_timer = QTimer(self._signals)
        self._ui_queue_timer.timeout.connect(self._signals.drain)
        self._ui_queue_timer.start(25)
        scope_parent = (
            self.main_frame if isinstance(self.main_frame, QObject) and _is_alive(self.main_frame) else self._signals
        )
        self.scope = UIWorkScope(scope_parent)
        self._ops = (
            ModManagementQueueOps(self),
            ModManagementReviewOps(self),
            ModManagementInstallExecutor(self),
            ModManagementTreeSyncOps(self),
        )
        self.load_servers()
        if self.mod_session.server and self.mod_manager:
            self.local_mod_list_presenter.refresh_mod_list_force()

    def _drain_ui_queue(self) -> None:
        for _ in range(100):
            try:
                callback = self.ui_queue.get_nowait()
            except queue.Empty:
                return
            try:
                callback()
            except Exception:
                logger.error("執行模組管理 UI 工作失敗\n" + traceback.format_exc())

    def showEvent(self, event) -> None:
        """
        當元件顯示時，強制刷新列表以解決隱藏時更新導致的繪製問題

        Args:
            event: 顯示事件
        """
        _showEvent = getattr(super(), "showEvent", None)
        if callable(_showEvent):
            _showEvent(event)

        if hasattr(self, "server_manager") and hasattr(self.server_manager, "load_servers_config"):
            self.server_manager.load_servers_config()

        self.load_servers()
        if hasattr(self, "notebook") and self.notebook:
            current_tab = self.notebook.currentIndex()
            if current_tab == 0:
                self.local_mod_list_presenter.load_local_mods()
            elif current_tab == 1:
                self.refresh_browse_list()

    def update_status(self, message: str) -> None:
        """
        更新狀態列顯示的訊息

        Args:
            message: 要顯示的狀態訊息
        """
        self.mod_session.set_status(message)
        try:
            if hasattr(self, "status_label") and _is_alive(self.status_label):
                if _is_alive(getattr(self, "parent", None)):
                    UIUtils.schedule_coalesced_idle(
                        self.parent, "_status_update_job", self._apply_status_label_update, owner=self
                    )
                else:
                    self._apply_status_label_update()
        except (AttributeError, RuntimeError) as e:
            logger.warning(f"更新狀態遇到暫時性問題: {e}")
        except AppException as e:
            logger.info(f"更新狀態被應用例外攔截: {e}")
            self.update_status_safe(str(e))
        except Exception:
            logger.error("更新狀態失敗: 未知錯誤\n" + traceback.format_exc())

    def update_status_safe(self, message: str) -> None:
        """
        透過 UI 佇列安全地更新狀態訊息，適用於非主執行緒呼叫

        Args:
            message: 要顯示的狀態訊息
        """
        self.ui_queue.put(lambda: self.update_status(message))

    def update_progress_safe(self, value: float) -> None:
        """
        透過 UI 佇列安全地更新進度條數值

        Args:
            value: 進度數值 (0.0 到 1.0)
        """
        signals = getattr(self, "_signals", None)
        if signals is not None:
            signals.progress_requested.emit(float(value))
            return
        self.ui_queue.put(lambda: self._apply_progress_value(float(value)))

    def create_widgets(self) -> None:
        """建立模組管理頁面的所有 UI 元件"""
        self.main_frame = QFrame(self.parent)
        self.main_layout = QVBoxLayout(self.main_frame)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        side_nav_layout = getattr(self, "side_nav_layout", None)
        side_nav = getattr(self, "side_nav", None)
        if self.parent and hasattr(self.parent, "layout") and side_nav_layout and side_nav:
            side_nav_layout.addWidget(side_nav)

        self.create_header()
        self.create_server_selection()
        self.create_notebook()
        self.create_status_bar()

    def create_server_selection(self) -> None:
        """建立伺服器選擇下拉選單與重新整理按鈕"""
        if not self.main_layout:
            return
        server_frame = QFrame(self.main_frame)
        self.main_layout.addWidget(server_frame)

        server_layout = QHBoxLayout(server_frame)
        server_layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, Spacing.SMALL_PLUS)

        inner_frame = QFrame(server_frame)
        inner_layout = QHBoxLayout(inner_frame)
        inner_layout.setContentsMargins(Spacing.LARGE, Spacing.SMALL_PLUS, Spacing.LARGE, Spacing.SMALL_PLUS)
        server_layout.addWidget(inner_frame)

        lbl = SubtitleLabel("📁 伺服器:", inner_frame)
        inner_layout.addWidget(lbl)

        self.server_var = TextState()
        self.server_combo = ScrollableComboBox(inner_frame)
        self.server_combo.addItems(["載入中..."])

        def _handle_server_changed(*_args: Any) -> None:
            self.server_var.set(self.server_combo.currentText())
            self.on_server_changed()

        self.server_combo.currentIndexChanged.connect(_handle_server_changed)
        self.server_combo.setMinimumWidth(Sizes.DROPDOWN_COMPACT_WIDTH)
        self.server_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        inner_layout.addWidget(self.server_combo, 1)

        refresh_btn = PushButton("🔄 重新整理", inner_frame)
        refresh_btn.clicked.connect(self.load_servers)
        refresh_btn.setMinimumWidth(Sizes.BUTTON_WIDTH_SECONDARY)
        inner_layout.addWidget(refresh_btn)

    def create_header(self) -> None:
        """建立頁面頂部的標題與描述區域"""
        if not self.main_layout:
            return
        header_frame = QFrame(self.main_frame)
        self.main_layout.addWidget(header_frame)

        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(Spacing.XL, Spacing.XL, Spacing.XL, Spacing.SMALL_PLUS)

        self.title_label = TitleLabel("🧩 模組管理", header_frame)
        header_layout.addWidget(self.title_label)

        self.description_label = BodyLabel("參考 Prism Launcher 的模組管理流程", header_frame)
        header_layout.addWidget(self.description_label)
        header_layout.addStretch(1)

    def create_local_mods_tab(self) -> None:
        """建立本地模組管理分頁"""
        if not self.notebook or not self.pivot:
            return
        self.local_tab = QFrame()
        tab_layout = QVBoxLayout(self.local_tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        self.notebook.addWidget(self.local_tab)
        self.pivot.addItem(
            self.local_tab.objectName() or "local_tab",
            "📁 本地模組",
            lambda: self.notebook.setCurrentWidget(self.local_tab),
        )

        self.local_mod_list_presenter.create_local_toolbar()
        self.local_mod_list_presenter.create_local_mod_list()

    def create_browse_mods_tab(self) -> None:
        """建立線上瀏覽模組分頁"""
        if not self.notebook or not self.pivot:
            return
        self.browse_tab = QFrame()
        tab_layout = QVBoxLayout(self.browse_tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        self.notebook.addWidget(self.browse_tab)
        self.pivot.addItem(
            self.browse_tab.objectName() or "browse_tab",
            "🌐 瀏覽模組",
            lambda: self.notebook.setCurrentWidget(self.browse_tab),
        )

        self.online_browse_presenter.create_browse_search()
        self.online_browse_presenter.create_browse_mod_list()

    def create_notebook(self) -> None:
        """建立分頁導航 (Pivot) 與內容切換區域 (StackedWidget)"""
        if not self.main_layout:
            return
        self.pivot = Pivot(self.main_frame)
        self.main_layout.addWidget(self.pivot, 0, Qt.AlignmentFlag.AlignLeft)

        self.notebook = QStackedWidget(self.main_frame)
        self.main_layout.addWidget(self.notebook, 1)

        self.create_local_mods_tab()
        self.create_browse_mods_tab()

        self.notebook.currentChanged.connect(self.on_tab_changed)
        if self.notebook.count() > 0 and self.pivot and self.local_tab:
            self.pivot.setCurrentItem(self.local_tab.objectName() or "local_tab")
            self.notebook.setCurrentIndex(0)

    def apply_theme_styles(self) -> None:
        """套用 Fluent 主題樣式至模組管理介面"""
        if hasattr(self, "status_frame") and self.status_frame:
            self._apply_status_bar_style()
        for tree in (getattr(self, "local_tree", None), getattr(self, "browse_tree", None)):
            if tree:
                apply_table_header_style(tree)
                if hasattr(tree, "apply_theme_style"):
                    tree.apply_theme_style()
        if getattr(self, "local_tree", None):
            self.local_mod_list_presenter.apply_local_tree_theme()
        if getattr(self, "browse_tree", None):
            self.online_browse_presenter.apply_browse_tree_theme()

    def on_tab_changed(self, _event=None) -> None:
        """
        處理分頁切換事件，觸發對應列表的重新整理

        Args:
            _event: 分頁切換事件
        """
        try:
            if not self.notebook:
                return
            current_tab = self.notebook.currentIndex()
            if current_tab == 0:
                self.refresh_local_list()
            elif current_tab == 1:
                self._refresh_online_filter_hint()
                self._load_online_mods(show_warning=False)
        except Exception as e:
            logger.error(f"處理頁籤切換事件失敗: {e}\n{traceback.format_exc()}")

    def export_mod_list_dialog(self) -> None:
        """開啟模組列表匯出對話框"""
        if not self.mod_manager or not self.mod_session.server:
            UIUtils.show_message("錯誤", "請先選擇伺服器以匯出模組列表", self.parent, message_level="error")
            return
        try:
            dialog = QDialog(self.parent)
            dialog.setWindowTitle("匯出模組列表")
            dialog.resize(Sizes.DIALOG_LARGE_WIDTH, Sizes.DIALOG_LARGE_HEIGHT)
            dialog.setMinimumSize(Sizes.DIALOG_LARGE_WIDTH, Sizes.DIALOG_LARGE_HEIGHT)
            bg_color = resolve_color(Colors.BG_PRIMARY)
            dialog.setStyleSheet(f"QDialog {{ background-color: {bg_color}; }}")

            dialog_layout = QVBoxLayout(dialog)
            dialog_layout.setContentsMargins(0, 0, 0, 0)

            main_frame = QFrame(dialog)
            main_frame.setStyleSheet(f"QFrame {{ background-color: {bg_color}; }}")
            dialog_layout.addWidget(main_frame)
            main_layout = QVBoxLayout(main_frame)
            main_layout.setContentsMargins(Spacing.XL, Spacing.XL, Spacing.XL, Spacing.XL)

            title_label = TitleLabel("匯出模組列表", main_frame)
            title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            main_layout.addWidget(title_label)

            fmt_frame = QFrame(main_frame)
            main_layout.addWidget(fmt_frame)
            fmt_layout = QHBoxLayout(fmt_frame)

            fmt_inner = QFrame(fmt_frame)
            fmt_layout.addWidget(fmt_inner)
            inner_layout = QHBoxLayout(fmt_inner)

            lbl = SubtitleLabel("選擇匯出格式:", fmt_inner)
            inner_layout.addWidget(lbl)

            self.fmt_var = TextState(value="text")

            text_radio = RadioButton("純文字", fmt_inner)
            text_radio.setChecked(True)
            text_radio.toggled.connect(lambda c: self.fmt_var.set("text") if c else None)
            inner_layout.addWidget(text_radio)

            json_radio = RadioButton("JSON", fmt_inner)
            json_radio.toggled.connect(lambda c: self.fmt_var.set("json") if c else None)
            inner_layout.addWidget(json_radio)

            html_radio = RadioButton("HTML", fmt_inner)
            html_radio.toggled.connect(lambda c: self.fmt_var.set("html") if c else None)
            inner_layout.addWidget(html_radio)

            csv_radio = RadioButton("Excel (.xlsx)", fmt_inner)
            csv_radio.toggled.connect(lambda c: self.fmt_var.set("xlsx") if c else None)
            inner_layout.addWidget(csv_radio)
            inner_layout.addStretch(1)

            preview_frame = QFrame(main_frame)
            main_layout.addWidget(preview_frame, 1)
            preview_layout = QVBoxLayout(preview_frame)

            preview_label = SubtitleLabel("預覽:", preview_frame)
            preview_layout.addWidget(preview_label)

            text_widget = TextEdit(preview_frame)
            text_widget.setMinimumHeight(Sizes.PREVIEW_TEXTBOX_HEIGHT)
            preview_layout.addWidget(text_widget, 1)

            def update_preview(*_):
                manager = self.mod_manager
                if manager is None:
                    text_widget.clear()
                    text_widget.setPlainText("模組管理器尚未初始化，無法匯出列表")
                    return
                export_text = manager.export_mod_list(self.fmt_var.get())
                text_widget.clear()
                if isinstance(export_text, bytes):
                    text_widget.setPlainText(
                        f"這是二進位 Excel 檔案，無法在此預覽。檔案大小：{len(export_text)} 位元組"
                    )
                else:
                    text_widget.setPlainText(export_text)

            self.fmt_var.trace_add("write", update_preview)
            update_preview()

            btn_frame = QFrame(main_frame)
            main_layout.addWidget(btn_frame)
            btn_layout = QHBoxLayout(btn_frame)

            def do_save():
                manager = self.mod_manager
                if manager is None:
                    UIUtils.show_message("錯誤", "模組管理器未初始化", dialog, message_level="error")
                    return
                fmt = self.fmt_var.get()
                ext = {"text": "txt", "json": "json", "html": "html", "xlsx": "xlsx"}[fmt]
                server_name = getattr(self.mod_session.server, "name", "server")
                default_name = f"{server_name}_模組列表.{ext}"
                server_path = (
                    Path(self.mod_session.server.path)
                    if self.mod_session.server and getattr(self.mod_session.server, "path", None)
                    else Path.home()
                )
                initial_path = str(server_path / default_name)
                file_path, _ = QFileDialog.getSaveFileName(
                    dialog,
                    "儲存模組列表",
                    initial_path,
                    "所有檔案 (*.*);;純文字 (*.txt);;JSON (*.json);;HTML (*.html);;Excel 試算表 (*.xlsx)",
                )
                if file_path:
                    try:
                        export_text = manager.export_mod_list(fmt)
                        if isinstance(export_text, bytes):
                            Path(file_path).write_bytes(export_text)
                        else:
                            if not PathUtils.write_text_file(Path(file_path), export_text):
                                UIUtils.show_message(
                                    "儲存失敗", f"無法寫入檔案: {file_path}", dialog, message_level="error"
                                )
                                return
                    except Exception as e:
                        logger.error(f"匯出模組列表失敗: {e}\n{traceback.format_exc()}")
                        UIUtils.show_message("匯出失敗", f"產生匯出內容時發生錯誤: {e}", dialog, message_level="error")
                        return

                    try:
                        result = UIUtils.ask_yes_no_cancel(
                            "匯出成功",
                            f"已儲存: {file_path}\n\n是否要立即開啟匯出的檔案？",
                            parent=dialog,
                            show_cancel=False,
                        )
                        if result:
                            UIUtils.open_external(file_path)
                    except Exception as e:
                        logger.error(f"開啟檔案失敗: {e}\n{traceback.format_exc()}")
                        UIUtils.show_message("開啟檔案失敗", f"無法開啟檔案: {e}", parent=dialog, message_level="error")

            save_btn = PrimaryPushButton("儲存到檔案", btn_frame)
            save_btn.clicked.connect(do_save)
            save_btn.setMinimumWidth(Sizes.MOD_EXPORT_SAVE_BUTTON_WIDTH)
            save_btn.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)
            btn_layout.addWidget(save_btn)

            close_btn = PushButton("關閉", btn_frame)
            close_btn.clicked.connect(dialog.close)
            close_btn.setMinimumWidth(Sizes.MOD_EXPORT_CLOSE_BUTTON_WIDTH)
            close_btn.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)
            btn_layout.addWidget(close_btn)
            btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            dialog.show()

        except Exception as e:
            logger.error(f"匯出對話框錯誤: {e}\n{traceback.format_exc()}")
            UIUtils.show_message("匯出對話框錯誤", str(e), self.parent, message_level="error")

    def create_status_bar(self) -> None:
        """建立頁面底部的狀態列與進度條"""
        if not self.main_layout:
            return
        self.status_frame = QFrame(self.main_frame)
        self.main_layout.addWidget(self.status_frame)

        status_layout = QHBoxLayout(self.status_frame)
        status_layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, Spacing.XL)

        self._apply_status_bar_style()

        self.status_label = SubtitleLabel("請選擇伺服器開始管理模組", self.status_frame)
        status_layout.addWidget(self.status_label)

        status_layout.addStretch(1)

        self.progress_label = BodyLabel("進度:", self.status_frame)
        status_layout.addWidget(self.progress_label)

        self.progress_var = FloatState()
        self.progress_bar = ProgressBar(self.status_frame)
        self.progress_bar.setMinimumWidth(Sizes.INPUT_WIDTH)
        self.progress_bar.setFixedHeight(Sizes.MOD_PROGRESS_HEIGHT)
        status_layout.addWidget(self.progress_bar)

    def load_servers(self) -> None:
        """從伺服器管理器載入所有伺服器名稱至下拉選單"""
        try:
            prev_selected = self.server_var.get()
            servers = list(self.server_manager.servers.values())
            servers = [s for s in servers if (s.loader_type or "").lower() != "vanilla"]
            server_names = [server.name for server in servers]
            if not server_names:
                self.server_combo.blockSignals(True)
                self.server_combo.clear()
                self.server_combo.addItems([""])
                self.server_combo.setCurrentIndex(0)
                self.server_combo.blockSignals(False)
                self.server_var.set("")
                self.mod_session.invalidate()
                self.mod_session = ModManagementSession()
                self.mod_manager = None
                self.refresh_local_list()
                self._refresh_online_queue_button()
                self._refresh_online_filter_hint()
            else:
                target_server = prev_selected if prev_selected in server_names else server_names[0]
                self.server_combo.blockSignals(True)
                self.server_combo.clear()
                self.server_combo.addItems(server_names)
                self.server_combo.setCurrentText(target_server)
                self.server_combo.blockSignals(False)
                self.server_var.set(target_server)
                self.on_server_changed()
        except Exception as e:
            logger.error(f"載入伺服器列表失敗: {e}\n{traceback.format_exc()}")
            UIUtils.show_message("錯誤", f"載入伺服器列表失敗: {e}", self.parent, message_level="error")

    def on_server_changed(self, _current_server: ServerConfig | None = None) -> None:
        """
        處理伺服器切換事件，初始化對應的模組管理器並重新載入列表

        Args:
            _current_server: 選中的伺服器設定，可選
        """
        if getattr(self, "_is_changing_server", False):
            return
        self._is_changing_server = True
        try:
            server_name = self.server_var.get()
            if not server_name:
                return
            servers = list(self.server_manager.servers.values())
            selected_server = None
            for server in servers:
                if server.name == server_name:
                    selected_server = server
                    break
            if not selected_server:
                return
            if not self.mod_session.matches_server(selected_server):
                self.mod_session.invalidate()
                self.mod_session = ModManagementSession(selected_server)
            self.mod_manager = ModManager(selected_server.path, selected_server)
            self._refresh_online_filter_hint()
            self._refresh_online_queue_button()
            self.local_mod_list_presenter.load_local_mods()
            if hasattr(self, "_is_browse_tab_active") and self._is_browse_tab_active():
                self._load_online_mods(force=True, show_warning=False)
            if self.on_server_selected and getattr(self, "_last_notified_server", None) != server_name:
                self._last_notified_server = server_name
                self.on_server_selected(server_name)
        except Exception as e:
            logger.error(f"切換伺服器失敗: {e}\n{traceback.format_exc()}")
            UIUtils.show_message("錯誤", f"切換伺服器失敗: {e}", self.parent, message_level="error")
        finally:
            self._is_changing_server = False

    def show_local_context_menu(self, event) -> None:
        """
        在本地模組列表上顯示右鍵上下文選單

        Args:
            event: 觸發選單的事件物件 (QPoint)
        """
        if not self.local_tree:
            return
        if hasattr(event, "x") and self.local_tree is not None:
            item = self.local_tree.itemAt(event)
            if item is not None:
                self.local_tree.setCurrentItem(item)
                item.setSelected(True)

        selected_items = self.local_tree.selectedItems()
        if not selected_items:
            return

        menu = RoundMenu(parent=self.local_tree)

        action_toggle = Action("🔄 切換啟用狀態", menu)
        action_toggle.triggered.connect(self.local_mod_list_presenter.toggle_local_mod)
        menu.addAction(action_toggle)
        menu.addSeparator()

        action_copy = Action("📋 複製模組資訊", menu)
        action_copy.triggered.connect(self.copy_mod_info)
        menu.addAction(action_copy)

        action_show = Action("📁 在檔案總管中顯示", menu)
        action_show.triggered.connect(self.show_in_explorer)
        menu.addAction(action_show)
        menu.addSeparator()

        action_delete = Action("🗑️ 刪除模組", menu)
        action_delete.triggered.connect(self.delete_local_mod)
        menu.addAction(action_delete)

        menu.exec(QCursor.pos())

    def import_mod_file(self) -> None:
        """開啟檔案選擇對話框以匯入新的模組 JAR 檔"""
        if not self.mod_session.server:
            UIUtils.show_message("警告", "請先選擇伺服器", self.main_frame, message_level="warning")
            return
        filename, _ = QFileDialog.getOpenFileName(
            self.main_frame, "選擇模組檔案", "", "JAR files (*.jar);;All files (*.*)"
        )
        if filename:
            if not self.mod_manager:
                UIUtils.show_message("錯誤", "模組管理器未初始化", self.main_frame, message_level="error")
                return
            result = self.mod_manager.import_local_mod_file_result(filename)
            if result.completed:
                UIUtils.show_message(
                    "成功",
                    result.message or f"模組已匯入: {Path(filename).name}",
                    self.main_frame,
                    message_level="info",
                )
                self.local_mod_list_presenter.load_local_mods()
            else:
                UIUtils.show_message(
                    result.title or "錯誤", result.message or "匯入模組失敗", self.main_frame, message_level="error"
                )

    def open_mods_folder(self) -> None:
        """在檔案總管中開啟目前伺服器的 mods 資料夾"""
        if not self.mod_session.server:
            UIUtils.show_message("警告", "請先選擇伺服器", self.parent, message_level="warning")
            return
        mods_dir = Path(self.mod_session.server.path) / "mods"
        if mods_dir.exists():
            try:
                UIUtils.open_external(mods_dir)
            except Exception as e:
                logger.error(f"開啟模組資料夾失敗: {e}")
        else:
            UIUtils.show_message("警告", "模組資料夾不存在", self.parent, message_level="warning")

    def copy_mod_info(self) -> None:
        """將選中模組的詳細資訊複製到剪貼簿"""
        if not self.local_tree:
            return
        tree = self.local_tree

        selection = tree.selectedItems()
        if not selection:
            return
        try:
            item = selection[0]
            status = item.text(0).strip()
            name_text = item.text(1).strip()
            version = item.text(2).strip()
            author = item.text(3).strip()
            loader = item.text(4).strip()
            size = item.text(5).strip()
            mtime = item.text(6).strip()
            desc = item.text(7).strip()

            lines = [f"模組名稱: {name_text}"]
            if version:
                lines.append(f"版本: {version}")
            if status:
                lines.append(f"狀態: {status}")
            if author:
                lines.append(f"作者: {author}")
            if loader:
                lines.append(f"載入器: {loader}")
            if size:
                lines.append(f"檔案大小: {size}")
            if mtime:
                lines.append(f"修改時間: {mtime}")
            if desc:
                lines.append(f"描述: {desc}")

            info = "\n".join(lines)
            QApplication.clipboard().setText(info)
            if hasattr(self, "status_label") and _is_alive(self.status_label):
                self.update_status("模組詳細資訊已複製到剪貼簿")
        except Exception as e:
            logger.error(f"複製模組資訊失敗: {e}\n{traceback.format_exc()}")

    def show_in_explorer(self) -> None:
        """在檔案總管中定位並選中目前選中的模組檔案"""
        if not self.local_tree:
            return
        tree = self.local_tree
        selection = tree.selectedItems()
        if not selection or not self.mod_session.server:
            return
        item = selection[0]
        mod_filename = item.data(0, Qt.ItemDataRole.UserRole)

        if mod_filename:
            if not self.mod_session.server:
                if hasattr(self, "status_label") and _is_alive(self.status_label):
                    self.status_label.setText("未選擇伺服器，無法定位模組檔案")
                return
            try:
                mods_dir = Path(self.mod_session.server.path) / "mods"
                mod_file = None
                for ext in [".jar", ".jar.disabled"]:
                    potential_file = mods_dir / (mod_filename + ext)
                    if potential_file.exists():
                        mod_file = potential_file
                        break
                if mod_file and mod_file.exists():
                    try:
                        UIUtils.reveal_in_explorer(mod_file)
                    except Exception as e:
                        logger.error(f"無法打開檔案總管顯示檔案: {e}")
                    if hasattr(self, "status_label") and _is_alive(self.status_label):
                        self.status_label.setText(f"已在檔案總管中顯示: {mod_file.name}")
                elif hasattr(self, "status_label") and _is_alive(self.status_label):
                    self.status_label.setText("找不到要顯示的模組檔案")
            except Exception as e:
                logger.error(f"開啟檔案總管失敗: {e}\n{traceback.format_exc()}")
                if hasattr(self, "status_label") and _is_alive(self.status_label):
                    self.status_label.setText(f"開啟檔案總管失敗: {e}")

    def delete_local_mod(self) -> None:
        """刪除選中的本地模組檔案"""
        if not self.local_tree:
            return
        tree = self.local_tree
        selected_mods = []
        seen_mod_ids = set()
        selection = tree.selectedItems()
        if not selection or not self.mod_session.server:
            return
        for item in selection:
            mod_id = item.data(0, Qt.ItemDataRole.UserRole)
            if not mod_id:
                continue

            mod_name = item.text(1) or str(mod_id)

            if mod_id in seen_mod_ids:
                continue
            seen_mod_ids.add(mod_id)
            selected_mods.append((mod_id, mod_name))

        if not selected_mods:
            return
        mod_count = len(selected_mods)
        mod_label = selected_mods[0][1] if mod_count == 1 else f"這 {mod_count} 個模組"
        confirm = UIUtils.ask_yes_no_cancel(
            "確認刪除", f"確定要刪除 {mod_label} 嗎？\n此操作無法復原", parent=self.parent, show_cancel=False
        )
        if not confirm:
            return
        if not self.mod_manager:
            UIUtils.show_message("錯誤", "模組管理器未初始化", self.parent, message_level="error")
            return
        mod_name_by_id = dict(selected_mods)
        result = self.mod_manager.delete_local_mods_result([mod_id for mod_id, _ in selected_mods])
        deleted_count = result.affected_count
        missing_names = [mod_name_by_id.get(mod_id, mod_id) for mod_id in result.missing_ids]
        if deleted_count > 0:
            self.local_mod_list_presenter.load_local_mods()
            if hasattr(self, "status_label") and _is_alive(self.status_label):
                self.status_label.setText(f"已刪除 {deleted_count} 個模組")
            if result.completed and len(selected_mods) == 1:
                UIUtils.show_message("成功", f"模組 '{selected_mods[0][1]}' 已刪除", self.parent, message_level="info")
            else:
                summary = result.message or f"已刪除 {deleted_count} 個模組"
                if missing_names:
                    summary += f"\n找不到檔案：{', '.join(missing_names)}"
                if result.partial:
                    UIUtils.show_message(result.title or "部分成功", summary, self.parent, message_level="warning")
                else:
                    UIUtils.show_message("成功", summary, self.parent, message_level="info")
        else:
            if hasattr(self, "status_label") and _is_alive(self.status_label):
                self.status_label.setText(result.message or "刪除失敗")
            UIUtils.show_message(
                result.title or "提示", result.message or "沒有成功刪除任何模組", self.parent, message_level="warning"
            )

    def _ensure_ops(self) -> tuple[Any, ...]:
        """確保 host-bound ops 已綁定"""
        ops = object.__getattribute__(self, "__dict__").get("_ops")
        if ops:
            return ops
        ops = (
            ModManagementQueueOps(self),
            ModManagementReviewOps(self),
            ModManagementInstallExecutor(self),
            ModManagementTreeSyncOps(self),
        )
        object.__setattr__(self, "_ops", ops)
        return ops

    def __getattr__(self, name: str) -> Any:
        """委派至 host-bound ops"""
        ops = self._ensure_ops()
        for op in ops:
            typ = type(op)
            if name in HostBound.__dict__:
                continue
            if any(name in b.__dict__ for b in typ.__mro__ if b not in (object, HostBound)):
                return getattr(op, name)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    def get_frame(self) -> QFrame | None:
        if hasattr(self, "main_frame") and self.main_frame:
            return self.main_frame
        logger.debug("主框架未初始化")
        return None

    def _apply_status_label_update(self) -> None:
        self._status_update_job = None
        if hasattr(self, "status_label") and self.status_label and _is_alive(self.status_label):
            self.status_label.setText(self.mod_session.snapshot().status_message)

    @Slot(float)
    def _apply_progress_value(self, value: float) -> None:
        if hasattr(self, "progress_var") and self.progress_var:
            try:
                self.progress_var.set(value)
                if hasattr(self, "progress_bar") and _is_alive(self.progress_bar):
                    clamped = max(0, min(100, round(value * 100 if value <= 1.0 else value)))
                    self.progress_bar.setValue(clamped)
            except (AttributeError, RuntimeError) as e:
                logger.warning(f"更新進度遇到暫時性問題: {e}")
            except AppException as e:
                logger.info(f"更新進度被應用例外攔截: {e}")
            except Exception:
                logger.error("更新進度失敗: 未知錯誤\n" + traceback.format_exc())

    def _apply_local_toggle_success(
        self,
        *,
        tree: QTreeWidget | None,
        item_id: str,
        _mod_id: str,
        mod_obj: Any,
        new_status: ModStatus,
        new_filename: str,
        old_filename: str,
        old_file_path: str,
    ) -> None:
        mod_obj.status = new_status
        mod_obj.filename = new_filename
        if old_file_path:
            try:
                mod_obj.file_path = str(Path(old_file_path).with_name(new_filename))
            except Exception:
                mod_obj.file_path = old_file_path.replace(old_filename, new_filename)
        try:
            mod_obj._cached_mtime = Path(mod_obj.file_path).stat().st_mtime
        except Exception:
            mod_obj._cached_mtime = None
        self.mod_session.rename_provider_cache_key(old_filename, new_filename)
        if not tree or not _is_alive(tree):
            return

        try:
            if isinstance(item_id, int):
                row = item_id
                if hasattr(tree, "topLevelItem"):
                    item = tree.topLevelItem(row)
                    if item:
                        item.setText(0, "✅ 已啟用" if new_status == ModStatus.ENABLED else "❌ 已停用")

                        color = QColor(
                            resolve_color(
                                Colors.TEXT_MUTED if new_status == ModStatus.DISABLED else Colors.TEXT_PRIMARY
                            )
                        )
                        brush = QBrush(color)
                        for col in range(tree.columnCount()):
                            item.setForeground(col, brush)
        except Exception as e:
            logger.error(f"Failed to update table item: {e}")

    def _apply_status_bar_style(self) -> None:
        if not getattr(self, "status_frame", None):
            return
        bg = resolve_color((Colors.BG_LISTBOX_LIGHT, Colors.BG_LISTBOX_DARK))
        fg = resolve_color(Colors.TEXT_PRIMARY)
        border = resolve_color(Colors.BORDER_LIGHT)
        stylesheet = (
            f"QFrame {{background: {bg}; color: {fg}; border: 1px solid {border}; border-radius: 3px; }} "
            f"QLabel {{color: {fg}; background: transparent; border: 0; }} "
        )
        if self.status_frame.styleSheet() != stylesheet:
            self.status_frame.setStyleSheet(stylesheet)


__all__ = ["ModManagementFrame"]
