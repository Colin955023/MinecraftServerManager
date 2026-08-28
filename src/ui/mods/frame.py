"""模組管理頁面主框架"""

from __future__ import annotations

import queue
import traceback
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    Pivot,
    PopUpAniStackedWidget,
    ProgressBar,
    PushButton,
    SubtitleLabel,
    TitleLabel,
    TreeWidget,
)

from src.core import LoaderManager, ModManager, ModPlanning
from src.models import (
    ModStatus,
    ServerConfig,
)
from src.utils import (
    AppException,
    Colors,
    FloatState,
    ScrollableComboBox,
    Sizes,
    Spacing,
    TextState,
    UIUtils,
    UIWorkScope,
    apply_table_header_style,
    resolve_color,
)

from .constants import logger
from .install_executor import ModManagementInstallExecutor
from .local_mod_list_presenter import LocalModListPresenter
from .mod_management_session import ModManagementSession
from .online_browse_presenter import OnlineBrowsePresenter
from .online_mod_queue import ModManagementQueueOps
from .review import ModManagementReviewOps
from .tree_sync import ModManagementTreeSyncOps


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
        mod_planning: ModPlanning,
        on_server_selected_callback: Callable | None = None,
        loader_manager: LoaderManager = None,
    ):
        self.parent = parent
        self.server_manager = server_manager
        self.mod_planning = mod_planning
        self.on_server_selected = on_server_selected_callback
        self.loader_manager = loader_manager
        self.mod_session = ModManagementSession()
        self.mod_manager: ModManager | None = None
        self.versions: list = []
        self.release_versions: list = []
        self.main_frame: QWidget | None = None
        self.main_layout: QVBoxLayout | None = None
        self.notebook: PopUpAniStackedWidget | None = None
        self.pivot: Pivot | None = None
        self.local_tab: QWidget | None = None
        self.browse_tab: QWidget | None = None
        self.local_mod_list_presenter = LocalModListPresenter(self)
        self.online_browse_presenter = OnlineBrowsePresenter(self)
        self.ui_queue: queue.Queue[Callable[[], Any]] = queue.Queue()
        self.queue_ops = ModManagementQueueOps(self)
        self.review_ops = ModManagementReviewOps(self)
        self.install_executor = ModManagementInstallExecutor(self)
        self.tree_sync = ModManagementTreeSyncOps(self)

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
                self.tree_sync.refresh_browse_list()

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
        self.main_frame = QWidget(self.parent)
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
        server_frame = QWidget(self.main_frame)
        self.main_layout.addWidget(server_frame)

        server_layout = QHBoxLayout(server_frame)
        server_layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, Spacing.SMALL_PLUS)

        inner_frame = QWidget(server_frame)
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
        header_frame = QWidget(self.main_frame)
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
        self.local_tab = QWidget()
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
        self.browse_tab = QWidget()
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

        self.notebook = PopUpAniStackedWidget(self.main_frame)
        self.main_layout.addWidget(self.notebook, 1)

        self.create_local_mods_tab()
        self.create_browse_mods_tab()

        self.notebook.currentChanged.connect(self.on_tab_changed)
        if self.notebook.count() > 0 and self.pivot and self.local_tab:
            self.pivot.setCurrentItem(self.local_tab.objectName() or "local_tab")
            self.notebook.setCurrentIndex(0)

    def apply_theme_styles(self) -> None:
        """套用 Fluent 主題樣式至模組管理介面"""
        trees = (
            self.local_mod_list_presenter.local_tree,
            self.online_browse_presenter.browse_tree,
        )
        for tree in trees:
            if tree:
                apply_table_header_style(tree)
                if hasattr(tree, "apply_theme_style"):
                    tree.apply_theme_style()
        if self.local_mod_list_presenter.local_tree:
            self.local_mod_list_presenter.apply_local_tree_theme()
        if self.online_browse_presenter.browse_tree:
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
                self.tree_sync.refresh_local_list()
            elif current_tab == 1:
                self.queue_ops._refresh_online_filter_hint()
                self.queue_ops._load_online_mods(show_warning=False)
        except Exception as e:
            logger.error(f"處理頁籤切換事件失敗: {e}\n{traceback.format_exc()}")

    def create_status_bar(self) -> None:
        """建立頁面底部的狀態列與進度條"""
        if not self.main_layout:
            return
        self.status_frame = CardWidget(self.main_frame)
        self.main_layout.addWidget(self.status_frame)

        status_layout = QHBoxLayout(self.status_frame)
        status_layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, Spacing.XL)

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
                self.tree_sync.refresh_local_list()
                self.queue_ops._refresh_online_queue_button()
                self.queue_ops._refresh_online_filter_hint()
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
            self.queue_ops._refresh_online_filter_hint()
            self.queue_ops._refresh_online_queue_button()
            self.local_mod_list_presenter.load_local_mods()
            if self.queue_ops._is_browse_tab_active():
                self.queue_ops._load_online_mods(force=True, show_warning=False)
            if self.on_server_selected and getattr(self, "_last_notified_server", None) != server_name:
                self._last_notified_server = server_name
                self.on_server_selected(server_name)
        except Exception as e:
            logger.error(f"切換伺服器失敗: {e}\n{traceback.format_exc()}")
            UIUtils.show_message("錯誤", f"切換伺服器失敗: {e}", self.parent, message_level="error")
        finally:
            self._is_changing_server = False

    def get_frame(self) -> QWidget | None:
        if hasattr(self, "main_frame") and self.main_frame:
            return self.main_frame
        logger.debug("主框架未初始化")
        return None

    def _apply_status_label_update(self) -> None:
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
        tree: TreeWidget | None,
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


__all__ = ["ModManagementFrame"]
