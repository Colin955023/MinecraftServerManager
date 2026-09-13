"""
管理伺服器頁面
負責管理現有 Minecraft 伺服器的使用者介面
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CardWidget,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    RoundMenu,
    SubtitleLabel,
    TitleLabel,
    TreeWidget,
)

from src.core import ServerConfigChangeSet, ServerCRUD, ServerImportService, ServerPropertiesStore, ServerRuntime
from src.models import ProgressEvent, ServerConfig, ServerDiscoveryReport, ServerImportBatchResult
from src.ui import (
    ManageServerService,
    ProgressDialog,
    RestoreBackupDialog,
    ServerMemoryDialog,
    ServerMonitorWindow,
    ServerPropertiesDialog,
    ServerRenderPlan,
    Sizes,
    Spacing,
    StatusPushButton,
    UIUtils,
    UIWorkScope,
    WorkOutcome,
    apply_table_header_style,
    is_qobject_alive,
)
from src.utils import (
    MemoryUtils,
    get_logger,
    is_path_within,
    resolve_stable_directory,
)

logger = get_logger().bind(component="ManageServerFrame")


class ManageServerFrame(QWidget):
    """管理伺服器頁面"""

    def __init__(
        self,
        parent,
        server_crud: ServerCRUD,
        server_runtime: ServerRuntime,
        server_properties: ServerPropertiesStore,
        server_backup: Any,
        server_import: ServerImportService,
        callback: Callable,
        on_navigate_callback: Callable | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("ManageServerFrame")
        self.server_crud = server_crud
        self.server_runtime = server_runtime
        self.server_properties = server_properties
        self.server_backup = server_backup
        self.server_import = server_import
        self.callback = callback
        self.on_navigate_callback = on_navigate_callback
        self.selected_server: str | None = None
        self.service = ManageServerService(
            server_crud,
            server_runtime,
            server_backup,
            server_inspector=server_import.server_inspector,
        )
        self.scope = UIWorkScope(self)
        self._widgets_created = False
        self.server_tree: TreeWidget | None = None
        self.action_buttons: dict[str, Any] = {}

        self._auto_refresh_enabled = True
        self._auto_refresh_interval_ms = 10000
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(self._auto_refresh_interval_ms)
        self._auto_refresh_timer.timeout.connect(self._on_auto_refresh_tick)

        self.create_widgets()
        self.refresh_servers()
        self.apply_theme_styles()
        self._auto_refresh_timer.start()

    @staticmethod
    def _show_existing_monitor_window(window: Any, *, bring_to_front: bool) -> None:
        if bring_to_front:
            is_minimized = getattr(window, "isMinimized", None)
            if callable(is_minimized) and is_minimized():
                is_max_fn = getattr(window, "isMaximized", None)
                is_maximized = bool(is_max_fn()) if callable(is_max_fn) else False
                if is_maximized:
                    show_max = getattr(window, "showMaximized", None)
                    if callable(show_max):
                        with suppress(Exception):
                            show_max()
                else:
                    show_normal = getattr(window, "showNormal", None)
                    if callable(show_normal):
                        with suppress(Exception):
                            show_normal()
            else:
                with suppress(Exception):
                    window.show()
            for method_name in ("raise_", "activateWindow", "setFocus"):
                method = getattr(window, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception as e:
                        logger.debug(f"帶出監控視窗失敗 method={method_name}: {e}")
            return

        window.show()

    def create_widgets(self) -> None:
        """建立介面元件"""
        if getattr(self, "_widgets_created", False):
            return
        self._widgets_created = True

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(Spacing.LARGE, Spacing.LARGE, Spacing.LARGE, Spacing.LARGE)
        main_layout.setSpacing(Spacing.XL)

        title_label = TitleLabel("⚙️ 管理伺服器", self)
        main_layout.addWidget(title_label)

        self.create_controls(main_layout)
        self.create_server_list(main_layout)
        self.create_actions(main_layout)

    def apply_theme_styles(self) -> None:
        """重新套用目前主題到管理伺服器頁面"""
        server_tree = getattr(self, "server_tree", None)
        if server_tree is not None:
            apply_table_header_style(server_tree)
            server_tree.viewport().update()

    def create_controls(self, main_layout) -> None:
        """
        建立控制區

        Args:
            主版面配置
        """
        control_frame = QWidget(self)
        control_layout = QVBoxLayout(control_frame)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(Spacing.SMALL_PLUS)

        path_frame = QWidget(control_frame)
        path_layout = QHBoxLayout(path_frame)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(Spacing.SMALL_PLUS)

        path_layout.addWidget(BodyLabel("偵測路徑:", path_frame))

        self.detect_path_entry = LineEdit(path_frame)
        self.detect_path_entry.setText(str(self.server_crud.servers_root))
        self.detect_path_entry.setReadOnly(True)
        path_layout.addWidget(self.detect_path_entry, 1)

        control_layout.addWidget(path_frame)

        button_frame = QWidget(control_frame)
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(Spacing.TINY)
        button_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        detect_button = PushButton("🔍 偵測現有伺服器", button_frame)
        detect_button.setMinimumHeight(32)
        detect_button.clicked.connect(self._detect_servers_from_button)
        button_layout.addWidget(detect_button)

        add_button = PushButton("➕ 手動新增", button_frame)
        add_button.setMinimumHeight(32)
        add_button.clicked.connect(self.add_server)
        button_layout.addWidget(add_button)

        refresh_button = PushButton("🔄 重新整理", button_frame)
        refresh_button.setMinimumHeight(32)
        refresh_button.clicked.connect(self.refresh_servers)
        button_layout.addWidget(refresh_button)

        control_layout.addWidget(button_frame)
        main_layout.addWidget(control_frame)

    def _detect_servers_from_button(self) -> None:
        """由偵測按鈕觸發掃描並顯示結果"""
        self.detect_servers(show_message=True)

    def create_server_list(self, main_layout) -> None:
        """
        建立伺服器列表

        Args:
            主版面配置
        """
        list_card = CardWidget(self)
        list_layout = QVBoxLayout(list_card)

        list_layout.addWidget(SubtitleLabel("伺服器列表", list_card))

        self.server_tree = TreeWidget(list_card)
        self.server_tree.setColumnCount(7)
        self.server_tree.setHeaderLabels(["名稱", "版本", "載入器", "狀態", "伺服器大小", "備份狀態", "路徑"])
        apply_table_header_style(self.server_tree)
        header = self.server_tree.header()
        if header is not None:
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.server_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.server_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.server_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        self.server_tree.itemSelectionChanged.connect(self.on_server_select)
        self.server_tree.doubleClicked.connect(self.on_server_double_click)
        self.server_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.server_tree.customContextMenuRequested.connect(self.show_server_context_menu)

        list_layout.addWidget(self.server_tree)
        main_layout.addWidget(list_card, 1)

    def show_server_context_menu(self, pos: QPoint) -> None:
        """
        顯示右鍵選單

        Args:
            pos: 滑鼠位置
        """
        if not self.server_tree:
            return
        item = self.server_tree.itemAt(pos)
        if item is not None:
            self.server_tree.setCurrentItem(item)
        items = self.server_tree.selectedItems()
        if not items:
            return

        menu = RoundMenu(parent=self)

        edit_memory_action = Action("🧠 修改記憶體設定")
        edit_memory_action.triggered.connect(self.edit_server_memory)
        menu.addAction(edit_memory_action)

        recheck_action = Action("🔄 重新檢測伺服器")
        recheck_action.triggered.connect(self.recheck_selected_server)
        menu.addAction(recheck_action)

        menu.addSeparator()

        open_backup_action = Action("📂 開啟備份資料夾")
        open_backup_action.triggered.connect(self.open_backup_folder)
        menu.addAction(open_backup_action)

        menu.exec(self.server_tree.mapToGlobal(pos), ani=False)

    def edit_server_memory(self) -> None:
        """開啟選中伺服器的記憶體設定對話框"""
        config = self._get_selected_server_config()
        if not config:
            return

        dialog = ServerMemoryDialog(config, self.server_crud, parent=self.window())
        if dialog.exec():
            self.refresh_servers()

    def recheck_selected_server(self) -> None:
        """重新檢測選中伺服器"""
        config = self._get_selected_server_config(show_warning=False)
        if not config:
            return
        server_name = config.name

        def task():
            try:
                inspection = self.server_import.inspect_registered(server_name)
                result = self.server_import.execute(inspection)
                return result, None
            except Exception as e:
                return None, str(e)

        def on_done(outcome: WorkOutcome) -> None:
            if not outcome.is_succeeded or outcome.value is None:
                err = outcome.error or "未知錯誤"
                UIUtils.show_message("重新偵測失敗", f"重新偵測失敗: {err}", self.window(), message_level="error")
                return

            result, error_message = outcome.value
            if result is None or not result.completed or result.config is None:
                message = error_message if result is None else result.message
                UIUtils.show_message("重新偵測失敗", message, self.window(), message_level="error")
                return

            self.refresh_servers()
            updated = result.config
            evidence_items = []
            raw_evidence = getattr(result, "evidence", ())
            if isinstance(raw_evidence, (tuple, list)):
                for item in raw_evidence:
                    if isinstance(item, (tuple, list)) and len(item) == 2:
                        evidence_items.append(f"{item[0]}: {item[1]}")
                    elif item:
                        evidence_items.append(str(item))
            evidence_text = "\n".join(evidence_items) if evidence_items else "伺服器資料夾結構與 JAR 特徵"
            UIUtils.show_message(
                "完成",
                f"已重新檢測伺服器：{server_name}\n"
                f"Minecraft 版本：{updated.minecraft_version or '未知'}\n"
                f"載入器類型：{updated.loader_type or '未知'}\n"
                f"載入器版本：{updated.loader_version or '未知'}\n"
                f"檢測依據：{evidence_text}",
                self.window(),
                message_level="info",
            )

        self.scope.submit(task, on_done=on_done, key="recheck_server", replace=True)

    def open_backup_folder(self) -> None:
        """開啟選中伺服器的備份資料夾"""
        config = self._get_selected_server_config()
        if not config:
            return

        backup_path = str(config.backup_path or "").strip()
        if not backup_path:
            UIUtils.show_message("沒有備份", "此伺服器尚未設定外部備份資料夾", self.window(), message_level="info")
            return
        try:
            backup_dir = resolve_stable_directory(Path(backup_path))
        except OSError as e:
            UIUtils.show_message("備份資料夾無效", str(e), self.window(), message_level="warning")
            return

        try:
            UIUtils.open_external(str(backup_dir))
        except Exception as e:
            logger.exception("無法開啟備份資料夾")
            UIUtils.show_message("錯誤", f"無法開啟備份資料夾: {e}", self.window(), message_level="error")

    def create_actions(self, main_layout) -> None:
        """
        建立操作區

        Args:
            主版面配置
        """
        action_frame = QWidget(self)
        action_layout = QVBoxLayout(action_frame)
        action_layout.setContentsMargins(0, 0, 0, 0)

        action_layout.addWidget(SubtitleLabel("操作", action_frame))

        self.info_label = BodyLabel("選擇一個伺服器以查看詳細資訊", action_frame)
        action_layout.addWidget(self.info_label)

        button_frame = QWidget(action_frame)
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(Spacing.SMALL)
        button_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        buttons = [
            ("🚀", "啟動", self.start_server, "start_stop"),
            ("📊", "監控", self.monitor_server, "monitor"),
            ("⚙️", "設定", self.configure_server, "configure"),
            ("📂", "開啟資料夾", self.open_server_folder, "open_folder"),
            ("💾", "備份伺服器", self.backup_server, "backup"),
            ("⏪", "還原備份", self.show_restore_dialog, "restore"),
            ("🗑️", "刪除", self.delete_server, "delete"),
        ]
        self.action_buttons = {}
        for emoji, text, command, fixed_key in buttons:
            btn_text = f"{emoji} {text}"
            if fixed_key == "start_stop":
                btn = PrimaryPushButton(btn_text, button_frame)
            elif fixed_key == "delete":
                btn = StatusPushButton(btn_text, button_frame)
                btn.set_status("danger")
            else:
                btn = PushButton(btn_text, button_frame)
            btn.setFixedWidth(Sizes.BUTTON_WIDTH_ACTION)
            btn.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)

            btn.clicked.connect(command)
            btn.setDisabled(True)
            button_layout.addWidget(btn)
            key = fixed_key if fixed_key else f"{emoji} {text}"
            self.action_buttons[key] = btn

        action_layout.addWidget(button_frame)
        main_layout.addWidget(action_frame)

    def detect_servers(self, show_message: bool = True) -> None:
        """
        偵測現有伺服器

        Args:
            show_message: 是否顯示偵測結果訊息
        """

        def task() -> tuple[ServerDiscoveryReport, ServerImportBatchResult]:
            report = self.server_import.discover()
            result = self.server_import.execute_batch(report.candidates)
            for issue in report.issues:
                logger.warning(f"略過無法檢查的伺服器候選 {issue.path}: {issue.message}")
            return report, result

        def on_done(outcome: WorkOutcome) -> None:
            if outcome.is_succeeded and outcome.value is not None:
                report, batch = outcome.value
                self._detect_servers_callback(report, batch, show_message)
            elif outcome.is_failed and outcome.error is not None:
                logger.error(f"偵測失敗: {outcome.error}")
                UIUtils.show_message("錯誤", f"偵測失敗: {outcome.error}", self.window(), message_level="error")

        self.scope.submit(task, on_done=on_done, key="detect_servers", replace=True)

    def add_server(self) -> None:
        """手動新增伺服器 - 跳轉到建立伺服器頁面"""
        if self.on_navigate_callback:
            self.on_navigate_callback()

    def refresh_servers(self) -> None:
        """
        重新整理伺服器列表：只更新 UI，不自動偵測

        Args:
            reload_config: 是否重新讀取伺服器設定
        """

        def task():
            gen = self.service.begin_refresh()
            payload = self.service.collect_facts()
            return gen, payload

        def on_done(outcome: WorkOutcome) -> None:
            if outcome.is_succeeded and outcome.value is not None:
                gen, payload = outcome.value
                self._apply_refresh_result(gen, payload)
            elif outcome.is_failed and outcome.error is not None:
                logger.error(f"重新整理伺服器列表失敗: {outcome.error}")

        self.scope.submit(task, on_done=on_done, key="server_refresh", replace=True)

    def select_server_by_name(self, server_name: str | None) -> None:
        """
        根據名稱選取伺服器

        Args:
            server_name: 要選取的伺服器名稱
        """
        if not self.server_tree or not server_name:
            if self.server_tree:
                self.server_tree.clearSelection()
            return
        found = False
        for i in range(self.server_tree.topLevelItemCount()):
            item = self.server_tree.topLevelItem(i)
            if item and item.text(0) == server_name:
                self.server_tree.clearSelection()
                item.setSelected(True)
                self.server_tree.scrollToItem(item)
                found = True
                break
        if not found:
            self.server_tree.clearSelection()

    def on_server_select(self) -> None:
        """伺服器選擇事件"""
        if not self.server_tree:
            return
        items = self.server_tree.selectedItems()
        if items:
            name = items[0].text(0)
            if name:
                self.selected_server = name
                self.callback(self.selected_server)
        else:
            self.selected_server = None
        self.update_selection()

    def on_server_double_click(self) -> None:
        """
        伺服器雙擊事件

        """
        if self.server_tree and self.selected_server:
            self.configure_server()

    def update_selection(self) -> None:
        """更新選擇狀態"""
        registry = self.server_crud.snapshot()
        if self.selected_server and self.selected_server not in registry:
            self.selected_server = None

        has_selection = self.selected_server is not None
        if has_selection and self.selected_server:
            is_running = self.server_runtime.observe(self.selected_server).is_running
            start_stop_key = "start_stop"
            if is_running:
                if start_stop_key in self.action_buttons:
                    self.action_buttons[start_stop_key].setText("🛑 停止")
                    self.action_buttons[start_stop_key].setEnabled(True)
            elif start_stop_key in self.action_buttons:
                self.action_buttons[start_stop_key].setText("🚀 啟動")
                self.action_buttons[start_stop_key].setEnabled(True)
            for key, btn in self.action_buttons.items():
                if key != start_stop_key:
                    if key in {"backup", "restore", "delete"} and is_running:
                        btn.setEnabled(False)
                    else:
                        btn.setEnabled(True)
        else:
            for btn in self.action_buttons.values():
                btn.setEnabled(False)
            start_stop_key = "start_stop"
            if start_stop_key in self.action_buttons:
                self.action_buttons[start_stop_key].setText("🚀 啟動")

        if has_selection and self.selected_server and self.selected_server in registry:
            config = registry.get(self.selected_server)
            if config is None:
                return
            is_running = self.server_runtime.observe(self.selected_server).is_running
            status_emoji = "🟢" if is_running else "🔴"
            status_text = "執行中" if is_running else "已停止"
            memory_info = ""
            if config.memory_max_mb:
                max_mem_str = MemoryUtils.format_memory_mb(config.memory_max_mb)
                if config.memory_min_mb:
                    min_mem_str = MemoryUtils.format_memory_mb(config.memory_min_mb)
                    memory_info = f"記憶體: {min_mem_str}-{max_mem_str}"
                else:
                    memory_info = f"最大記憶體: {max_mem_str}"
            else:
                memory_info = "記憶體: 未設定"
            loader_type = (config.loader_type or "").lower()
            loader_version = (config.loader_version or "").lower()
            if loader_type == "vanilla":
                loader_info = "原版"
            elif loader_type == "unknown" or not loader_type:
                loader_info = "未知"
            else:
                loader_info = loader_type.capitalize()
                if loader_version and loader_version != "unknown":
                    loader_info = f"{loader_info} v{config.loader_version}"
            info_text = f"{config.name} | {status_emoji} {status_text} | MC {(config.minecraft_version if config.minecraft_version and config.minecraft_version.lower() != 'unknown' else '未知')} | {loader_info} | {memory_info}"
            self.info_label.setText(info_text)
        else:
            self.info_label.setText("✨ 選擇一個伺服器以查看詳細資訊")

    def start_server(self) -> None:
        """啟動/停止伺服器"""
        if not self.selected_server:
            return
        server_name = self.selected_server
        is_running = self.server_runtime.observe(server_name).is_running
        start_button = self.action_buttons.get("start_stop")
        if start_button is not None:
            start_button.setEnabled(False)
        if is_running:

            def _on_stopped(outcome: WorkOutcome) -> None:
                if outcome.is_succeeded and outcome.value:
                    UIUtils.show_message("成功", f"伺服器 {server_name} 已停止", self.window(), message_level="info")
                else:
                    UIUtils.show_message("錯誤", f"停止伺服器 {server_name} 失敗", self.window(), message_level="error")
                self._schedule_post_action_updates(0, 1000)

            self.scope.submit(
                lambda: self.server_runtime.stop(server_name),
                on_done=_on_stopped,
                key=f"server_runtime:{server_name}",
                critical=True,
            )
        else:

            def _on_started(outcome: WorkOutcome) -> None:
                if outcome.is_succeeded and outcome.value.success:
                    if self.selected_server == server_name:
                        self.monitor_server(bring_to_front=False, notify_when_ready=True)
                else:
                    result = outcome.value if outcome.is_succeeded else None
                    UIUtils.show_message(
                        getattr(result, "title", "") or "錯誤",
                        getattr(result, "message", "") or f"啟動伺服器 {server_name} 失敗",
                        self.window(),
                        message_level="error",
                    )
                self._schedule_post_action_updates(0, 1000)

            self.scope.submit(
                lambda: self.server_runtime.start(server_name),
                on_done=_on_started,
                key=f"server_runtime:{server_name}",
                critical=True,
            )

    def monitor_server(self, *, bring_to_front: bool = True, notify_when_ready: bool = False) -> None:
        """
        監控伺服器

        Args:
            bring_to_front: 是否將監控視窗帶至前景
            notify_when_ready: 是否為本次新啟動流程啟用 ready 通知
        """
        if not self.selected_server:
            return

        if not hasattr(self, "_monitor_windows"):
            self._monitor_windows: dict[str, ServerMonitorWindow] = {}

        if self.selected_server in self._monitor_windows:
            old_win = self._monitor_windows[self.selected_server]
            if old_win and is_qobject_alive(old_win):
                if notify_when_ready:
                    old_win.arm_server_ready_notification()
                self._show_existing_monitor_window(old_win, bring_to_front=bring_to_front)
                return

        monitor_window = ServerMonitorWindow(
            self.window(),
            self.server_runtime,
            self.selected_server,
            self.server_crud,
            self.server_properties,
        )
        self._monitor_windows[self.selected_server] = monitor_window
        if notify_when_ready:
            monitor_window.arm_server_ready_notification()
        monitor_window.show()

    def configure_server(self) -> None:
        """設定伺服器"""
        if not self.selected_server:
            return
        config = self.server_crud.snapshot().get(self.selected_server)
        if config is None:
            UIUtils.show_message("錯誤", "找不到選取的伺服器設定", self.window(), message_level="error")
            return
        dialog = ServerPropertiesDialog(self.window(), config, self.server_properties)
        if dialog.exec():
            self.refresh_servers()

    def open_server_folder(self) -> None:
        """開啟伺服器資料夾"""
        if not self.selected_server:
            return
        config = self.server_crud.snapshot().get(self.selected_server)
        if config is None:
            return
        path = config.path
        try:
            UIUtils.open_external(path)
        except Exception as e:
            logger.exception("無法開啟資料夾")
            UIUtils.show_message("錯誤", f"無法開啟資料夾: {e}", self.window(), message_level="error")

    def delete_server(self) -> None:
        """刪除伺服器"""
        if not self.selected_server:
            return
        server_name = self.selected_server
        if self.server_runtime.observe(self.selected_server).is_running:
            UIUtils.show_message(
                "警告",
                f"伺服器「{self.selected_server}」正在執行中，請先停止伺服器再刪除",
                self.window(),
                message_level="warning",
            )
            return
        config = self.server_crud.snapshot().get(server_name)
        backups = self.server_backup.list_backups(server_name) if config and config.backup_path else []
        result = UIUtils.ask_yes_no_cancel(
            "確認刪除",
            f"確定要刪除伺服器 '{server_name}' 嗎？\n\n" + "⚠️ 這將永久刪除伺服器檔案，無法復原！",
            self.window(),
            show_cancel=False,
        )
        if not result:
            return

        delete_backups = False
        backup_dir = Path(config.backup_path) if config else None
        if backups:
            delete_backups = UIUtils.ask_yes_no_cancel(
                "刪除外部備份",
                f"找到 {len(backups)} 個外部備份檔案，是否一併永久刪除？",
                self.window(),
                show_cancel=False,
            )

        for button in self.action_buttons.values():
            button.setEnabled(False)

        def _on_progress(event: ProgressEvent) -> None:
            if event.phase == "delete_committed":
                self.scope.schedule(0, self.refresh_servers, key=f"delete_refresh:{server_name}")

        def _on_deleted(outcome: WorkOutcome) -> None:
            delete_result, backups_deleted = outcome.value if outcome.is_succeeded else (None, False)
            if delete_result is not None and delete_result.success:
                UIUtils.show_message("成功", f"伺服器 {server_name} 已刪除", self.window(), message_level="info")
                if delete_backups and not backups_deleted:
                    UIUtils.show_message(
                        "部分完成",
                        "伺服器已刪除，但無法刪除全部外部備份檔案",
                        self.window(),
                        message_level="warning",
                    )
                self.refresh_servers()
            else:
                UIUtils.show_message(
                    getattr(delete_result, "title", "") or "錯誤",
                    getattr(delete_result, "message", "") or f"刪除伺服器 {server_name} 失敗",
                    self.window(),
                    message_level="error",
                )
                self.update_selection()

        def _delete_task():
            delete_result = self.server_crud.delete_server_result(
                server_name,
                server_runtime=self.server_runtime,
                progress_callback=_on_progress,
            )
            backups_deleted = not delete_backups
            if delete_result.success and delete_backups and backup_dir is not None:
                backups_deleted = self.server_backup.delete_backups(server_name, backup_dir)
            return delete_result, backups_deleted

        self.scope.submit(
            _delete_task,
            on_done=_on_deleted,
            key=f"delete_server:{server_name}",
            critical=True,
        )

    def backup_server(self) -> None:
        """備份伺服器檔案"""
        if not self.selected_server:
            return
        if self.server_runtime.observe(self.selected_server).is_running:
            UIUtils.show_message(
                "警告",
                f"伺服器「{self.selected_server}」正在執行中，請先停止伺服器再備份",
                self.window(),
                message_level="warning",
            )
            return

        if not UIUtils.ask_yes_no_cancel(
            "確認備份",
            "備份會包含 server.properties，其中可能含 RCON 密碼與管理伺服器密鑰。\n"
            "請妥善保管且不要直接分享未加密備份。是否繼續？",
            self.window(),
            show_cancel=False,
        ):
            return

        server_name = self.selected_server
        baseline = self.server_crud.snapshot()
        config = baseline.get(server_name)
        if config is None:
            UIUtils.show_message("錯誤", "找不到選取的伺服器設定", self.window(), message_level="error")
            return
        backup_path = str(config.backup_path or "").strip()
        should_save_backup_path = not backup_path
        if should_save_backup_path:
            backup_path = UIUtils.get_existing_directory(
                self.window(),
                "選擇外部備份資料夾",
                "",
            )
            if not backup_path:
                return
        try:
            backup_dir = resolve_stable_directory(Path(backup_path))
            server_path = resolve_stable_directory(Path(config.path))
            if backup_dir == server_path or is_path_within(server_path, backup_dir, strict=False):
                raise ValueError("備份資料夾不得位於伺服器資料夾內")
        except (OSError, ValueError) as e:
            UIUtils.show_message("備份位置無效", str(e), self.window(), message_level="warning")
            return

        if should_save_backup_path:
            config.backup_path = str(backup_dir)
            commit_result = self.server_crud.commit(
                ServerConfigChangeSet(upserts=(config,)),
                expected_revision=baseline.revision,
            )
            if not commit_result.success:
                UIUtils.show_message(
                    "備份位置未儲存",
                    commit_result.message or "無法寫入伺服器設定檔",
                    self.window(),
                    message_level="error",
                )
                return

        dialog = ProgressDialog(self.window(), title="備份伺服器", show_cancel=False)
        dialog.update_progress(0, "準備備份中...")

        def _backup_task() -> bool:
            return self.server_backup.backup_server(server_name, progress_callback=dialog.update_progress)

        def _on_done(outcome: WorkOutcome) -> None:
            dialog.close()
            if outcome.is_succeeded and outcome.value:
                UIUtils.show_message("備份成功", "備份完成！", self.window(), message_level="info")
                self.refresh_servers()
            else:
                UIUtils.show_message(
                    "備份失敗", "備份失敗，請查看日誌以取得詳細資訊", self.window(), message_level="error"
                )

        self.scope.submit(_backup_task, on_done=_on_done, key="backup_server", critical=True)
        dialog.exec()

    def show_restore_dialog(self) -> None:
        """顯示還原備份對話框"""
        if not self.selected_server:
            return
        if self.server_runtime.observe(self.selected_server).is_running:
            UIUtils.show_message(
                "警告",
                f"伺服器「{self.selected_server}」正在執行中，無法還原備份請先停止伺服器",
                self.window(),
                message_level="warning",
            )
            return
        dialog = RestoreBackupDialog(self.window(), self.selected_server, self.server_backup, self.server_crud)
        dialog.exec_dialog()
        if hasattr(self, "service") and self.service:
            self.service.clear_cache()
        self.refresh_servers()

    def _on_auto_refresh_tick(self) -> None:
        """自動重新整理槽函式"""
        if getattr(self, "_auto_refresh_enabled", True) and self.isVisible():
            self.refresh_servers()

    def _schedule_post_action_updates(self, immediate_delay_ms: int, delayed_delay_ms: int) -> None:
        UIUtils.schedule_debounce(self, "_post_action_immediate_job", immediate_delay_ms, self._immediate_update)
        UIUtils.schedule_debounce(self, "_post_action_delayed_job", delayed_delay_ms, self._delayed_update)

    def _get_selected_server_config(self, show_warning: bool = True) -> ServerConfig | None:
        """取得目前選取的伺服器設定"""
        if not self.server_tree:
            return None
        items = self.server_tree.selectedItems()
        if not items:
            if show_warning:
                UIUtils.show_message("提示", "請先選擇伺服器", self.window(), message_level="warning")
            return None
        server_name = items[0].text(0)

        config = self.server_crud.snapshot().get(server_name)
        if not config:
            if show_warning:
                UIUtils.show_message("錯誤", f"找不到伺服器設定: {server_name}", self.window(), message_level="error")
            return None
        return config

    def _detect_servers_callback(
        self,
        report: ServerDiscoveryReport,
        batch: ServerImportBatchResult,
        show_message: bool,
    ) -> None:
        if show_message:
            failure_count = batch.failed_count + len(report.issues)
            found_count = report.managed_count + len(report.candidates)
            UIUtils.show_message(
                "完成",
                f"找到 {found_count} 個現有伺服器；新匯入 {batch.completed_count} 個；"
                f"已管理 {report.managed_count} 個；略過 {batch.skipped_count} 個；失敗 {failure_count} 個",
                self.window(),
                message_level="info" if failure_count == 0 else "warning",
            )
        self.refresh_servers()
        if self.server_tree:
            self.server_tree.viewport().update()

    def _apply_refresh_result(self, generation: int, payload: Any) -> None:
        if self.server_tree is None:
            return

        render_plan = self.service.accept_projection(generation, payload, getattr(self, "selected_server", None))
        if render_plan is None or not render_plan.has_changes:
            if render_plan is not None:
                self.selected_server = render_plan.projection.selected_server
            self.update_selection()
            return

        self._apply_server_render_plan(render_plan)

    def _apply_server_render_plan(self, render_plan: ServerRenderPlan) -> None:
        if not self.server_tree:
            return

        projection = render_plan.projection
        current_order = [
            item.text(0)
            for i in range(self.server_tree.topLevelItemCount())
            if (item := self.server_tree.topLevelItem(i)) is not None
        ]
        if current_order != list(projection.server_order):
            self.server_tree.clear()
            items = [
                QTreeWidgetItem([str(v) for v in projection.server_rows[name]]) for name in projection.server_order
            ]
            if items:
                self.server_tree.addTopLevelItems(items)
        else:
            self.server_tree.setUpdatesEnabled(False)
            try:
                for row, name in enumerate(projection.server_order):
                    item = self.server_tree.topLevelItem(row)
                    if item is not None:
                        for column, value in enumerate(projection.server_rows[name]):
                            text = str(value)
                            if item.text(column) != text:
                                item.setText(column, text)
            finally:
                self.server_tree.setUpdatesEnabled(True)

        self.selected_server = projection.selected_server
        if self.selected_server:
            self.select_server_by_name(self.selected_server)
        else:
            self.server_tree.clearSelection()
        self.update_selection()

    def _immediate_update(self) -> None:
        self.refresh_servers()
        self.update_selection()

    def _delayed_update(self) -> None:
        self.update_selection()
        self.refresh_servers()


__all__ = ["ManageServerFrame"]
