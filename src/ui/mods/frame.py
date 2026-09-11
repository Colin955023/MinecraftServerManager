"""模組管理頁面主框架"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QSignalBlocker, Qt, Slot
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
)
from src.ui import (
    Colors,
    FloatState,
    ScrollableComboBox,
    Sizes,
    Spacing,
    TextState,
    UIUtils,
    UIWorkScope,
    WorkOutcome,
    apply_table_header_style,
    resolve_color,
)
from src.utils import AppException

from .constants import logger
from .feature_contexts import ModManagementFeatureContext
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


class ModManagementFrame:
    """模組管理主畫面"""

    def __init__(
        self,
        parent,
        server_manager,
        mod_planning: ModPlanning,
        mod_provider,
        on_server_selected_callback: Callable | None = None,
        loader_manager: LoaderManager = None,
    ):
        self.parent = parent
        self.server_manager = server_manager
        self.mod_planning = mod_planning
        self.mod_provider = mod_provider
        self.on_server_selected = on_server_selected_callback
        self.loader_manager = loader_manager
        self.mod_session = ModManagementSession()
        self.mod_manager: ModManager | None = None
        self.feature_context = ModManagementFeatureContext(
            parent=parent,
            server_manager=server_manager,
            mod_planning=mod_planning,
            mod_provider=self.mod_provider,
            loader_manager=loader_manager,
            mod_session=self.mod_session,
            status_sink=self.update_status,
            status_async_sink=self.update_status_safe,
            progress_sink=self.update_progress_safe,
            toggle_success_sink=self._apply_local_toggle_success,
        )
        self.versions: list = []
        self.release_versions: list = []
        self.main_frame: QWidget | None = None
        self.main_layout: QVBoxLayout | None = None
        self.notebook: PopUpAniStackedWidget | None = None
        self.pivot: Pivot | None = None
        self.local_tab: QWidget | None = None
        self.browse_tab: QWidget | None = None
        self.local_mod_list_presenter = LocalModListPresenter(self.feature_context)
        self.online_browse_presenter = OnlineBrowsePresenter(self.feature_context)
        self.queue_ops = ModManagementQueueOps(self.feature_context)
        self.review_ops = ModManagementReviewOps(self.feature_context)
        self.install_executor = ModManagementInstallExecutor(self.feature_context)
        self.tree_sync = ModManagementTreeSyncOps(self.feature_context)
        self.feature_context.local_mod_list_presenter = self.local_mod_list_presenter
        self.feature_context.online_browse_presenter = self.online_browse_presenter
        self.feature_context.queue_ops = self.queue_ops
        self.feature_context.review_ops = self.review_ops
        self.feature_context.install_executor = self.install_executor
        self.feature_context.tree_sync = self.tree_sync
        self.feature_context.refresh_online_queue = self.queue_ops.refresh_online_queue
        self.feature_context.refresh_online_filter_hint = self.queue_ops.refresh_online_filter_hint
        self.feature_context.refresh_online_results_summary = self.queue_ops.refresh_online_results_summary
        self.feature_context.clear_online_results = self.tree_sync.clear_online_results
        self.feature_context.format_online_environment = self.tree_sync.format_online_environment_text
        self.feature_context.open_project_page = self.review_ops.open_project_page
        self.feature_context.capture_selected_mod_ids = self.tree_sync.capture_selected_mod_ids
        self.feature_context.get_current_modrinth_context = self.queue_ops.get_current_modrinth_context

        self.create_widgets()

        scope_parent = (
            self.main_frame if isinstance(self.main_frame, QObject) and _is_alive(self.main_frame) else self.parent
        )
        if not isinstance(scope_parent, QObject):
            raise TypeError("ModManagementFrame 需要 QObject parent 或 main_frame")
        self.scope = UIWorkScope(scope_parent)
        self.feature_context.scope = self.scope
        self._active_server_identity: tuple[str, str, str, str] | None = None
        self.load_servers()

    def on_page_shown(self) -> None:
        """
        當頁面顯示時重新載入伺服器與列表
        """
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
            logger.warning(f"更新狀態被應用例外攔截: {e}")
            self.update_status_safe(str(e))
        except Exception:
            logger.exception("更新狀態失敗: 未知錯誤")

    def update_status_safe(self, message: str) -> None:
        """
        透過 UI 佇列安全地更新狀態訊息，適用於非主執行緒呼叫

        Args:
            message: 要顯示的狀態訊息
        """
        self.scope.schedule(0, lambda: self.update_status(message))

    def update_progress_safe(self, value: float) -> None:
        """
        透過 UI 佇列安全地更新進度條數值

        Args:
            value: 進度數值 (0.0 到 1.0)
        """
        self.scope.schedule(0, lambda: self._apply_progress_value(float(value)))

    def create_widgets(self) -> None:
        """建立模組管理頁面的所有 UI 元件"""
        self.main_frame = QWidget(self.parent)
        self.feature_context.main_frame = self.main_frame
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

        def _handle_server_changed() -> None:
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
        self.feature_context.local_tab = self.local_tab
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
        self.feature_context.browse_tab = self.browse_tab
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
        self.feature_context.notebook = self.notebook
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

    def on_tab_changed(self) -> None:
        """
        處理分頁切換事件，觸發對應列表的重新整理

        """
        try:
            if not self.notebook:
                return
            current_tab = self.notebook.currentIndex()
            if current_tab == 0:
                self.tree_sync.refresh_local_list()
            elif current_tab == 1:
                self.queue_ops.refresh_online_filter_hint()
                self.queue_ops._load_online_mods(show_warning=False)
        except Exception:
            logger.exception("處理頁籤切換事件失敗")

    def create_status_bar(self) -> None:
        """建立頁面底部的狀態列與進度條"""
        if not self.main_layout:
            return
        self.status_frame = CardWidget(self.main_frame)
        self.main_layout.addWidget(self.status_frame)

        status_layout = QHBoxLayout(self.status_frame)
        status_layout.setContentsMargins(Spacing.XL, 0, Spacing.XL, Spacing.XL)

        self.status_label = SubtitleLabel("請選擇伺服器開始管理模組", self.status_frame)
        self.feature_context.status_label = self.status_label
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
            servers = list(self.server_manager.snapshot().values())
            servers = [s for s in servers if (s.loader_type or "").lower() != "vanilla"]
            server_names = [server.name for server in servers]
            if not server_names:
                with QSignalBlocker(self.server_combo):
                    self.server_combo.clear()
                    self.server_combo.addItems([""])
                    self.server_combo.setCurrentIndex(0)
                self.server_var.set("")
                self.mod_session.invalidate()
                self.mod_session = ModManagementSession()
                self.mod_manager = None
                self.feature_context.mod_session = self.mod_session
                self.feature_context.mod_manager = None
                self.tree_sync.refresh_local_list()
                self.queue_ops.refresh_online_queue()
                self.queue_ops.refresh_online_filter_hint()
            else:
                target_server = prev_selected if prev_selected in server_names else server_names[0]
                with QSignalBlocker(self.server_combo):
                    self.server_combo.clear()
                    self.server_combo.addItems(server_names)
                    self.server_combo.setCurrentText(target_server)
                self.server_var.set(target_server)
                self.on_server_changed()
        except Exception as e:
            logger.exception("載入伺服器列表失敗")
            UIUtils.show_message("錯誤", f"載入伺服器列表失敗: {e}", self.parent, message_level="error")

    def on_server_changed(self) -> None:
        """
        處理伺服器切換事件，初始化對應的模組管理器並重新載入列表

        """
        if getattr(self, "_is_changing_server", False):
            return
        self._is_changing_server = True
        try:
            server_name = self.server_var.get()
            if not server_name:
                return
            servers = list(self.server_manager.snapshot().values())
            selected_server = None
            for server in servers:
                if server.name == server_name:
                    selected_server = server
                    break
            if not selected_server:
                return
            identity = (
                str(Path(selected_server.path).resolve(strict=False)).casefold(),
                str(selected_server.loader_type or "").casefold(),
                str(selected_server.minecraft_version or ""),
                str(selected_server.loader_version or ""),
            )
            if self.mod_manager is not None and identity == self._active_server_identity:
                return
            if not self.mod_session.matches_server(selected_server):
                self.mod_session.invalidate()
                self.mod_session = ModManagementSession(selected_server)
                self.feature_context.mod_session = self.mod_session
            session = self.mod_session
            self.mod_manager = None
            self.feature_context.mod_manager = None
            self._active_server_identity = None
            self.update_status("正在準備模組列表...")

            def _on_manager_ready(outcome: WorkOutcome) -> None:
                if not session.matches_server(selected_server) or self.mod_session is not session:
                    return
                if not outcome.is_succeeded:
                    self.update_status(f"載入模組管理器失敗: {outcome.error}")
                    return
                self.mod_manager = outcome.value
                self.feature_context.mod_manager = outcome.value
                self._active_server_identity = identity
                self.queue_ops.refresh_online_filter_hint()
                self.queue_ops.refresh_online_queue()
                self.local_mod_list_presenter.load_local_mods()
                if self.queue_ops._is_browse_tab_active():
                    self.queue_ops._load_online_mods(force=True, show_warning=False)

            self.scope.submit(
                lambda: ModManager(
                    selected_server.path,
                    selected_server,
                    provider_catalog=self.mod_provider,
                ),
                on_done=_on_manager_ready,
                key="mod_manager_init",
                replace=True,
            )
            if self.on_server_selected and getattr(self, "_last_notified_server", None) != server_name:
                self._last_notified_server = server_name
                self.on_server_selected(server_name)
        except Exception as e:
            logger.exception("切換伺服器失敗")
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
                logger.warning(f"更新進度被應用例外攔截: {e}")
            except Exception:
                logger.exception("更新進度失敗: 未知錯誤")

    def _apply_local_toggle_success(
        self,
        *,
        tree: TreeWidget | None,
        item_id: str,
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
            mod_obj.file_mtime = Path(mod_obj.file_path).stat().st_mtime
        except OSError:
            mod_obj.file_mtime = 0.0
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
