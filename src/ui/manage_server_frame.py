"""
管理伺服器頁面
負責管理現有 Minecraft 伺服器的使用者介面
"""

import traceback
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
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

from ..core import ServerCRUD, ServerStartup
from ..models import ServerConfig
from ..utils import (
    Colors,
    MemoryUtils,
    ServerDetectionUtils,
    ServerOperations,
    Spacing,
    TaskUtils,
    UIUtils,
    get_logger,
    get_settings_manager,
    resolve_color,
    run_in_background,
    run_on_ui_thread,
)
from . import (
    ManageServerService,
    RestoreBackupDialog,
    ServerMonitorWindow,
    ServerPropertiesDialog,
    ServerRefreshContext,
    ServerRefreshPayload,
)
from .progress_dialog import ProgressDialog

logger = get_logger().bind(component="ManageServerFrame")


class ManageServerFrame(QWidget):
    """管理伺服器頁面"""

    def __init__(
        self,
        parent,
        server_crud: ServerCRUD,
        server_startup: ServerStartup,
        server_backup: Any,
        callback: Callable,
        on_navigate_callback: Callable | None = None,
        set_servers_root=None,
    ):
        super().__init__(parent)
        self.server_crud = server_crud
        self.server_startup = server_startup
        self.server_backup = server_backup
        self.callback = callback
        self.on_navigate_callback = on_navigate_callback
        self.set_servers_root = set_servers_root
        self.selected_server: str | None = None
        self.service = ManageServerService(server_crud, server_startup, server_backup)
        self._widgets_created = False
        self.server_tree: TreeWidget | None = None
        self.action_buttons: dict[str, Any] = {}
        self._post_action_immediate_job = None
        self._post_action_delayed_job = None
        self.tree_refresh_worker = None

        self._auto_refresh_enabled = True
        self._auto_refresh_interval_ms = 10000
        self._auto_refresh_job = None

        self._server_refresh_token = 0

        self.create_widgets()
        self.refresh_servers()
        self._auto_refresh_loop()

    @staticmethod
    def _show_existing_monitor_window(window: Any, *, bring_to_front: bool) -> None:
        if bring_to_front:
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

    def set_auto_refresh_enabled(self, enabled: bool, *, refresh_now: bool = False) -> None:
        self._auto_refresh_enabled = bool(enabled)
        if refresh_now and self._auto_refresh_enabled:
            self.refresh_servers()

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

    def create_controls(self, main_layout) -> None:
        """建立控制區

        Args:
            main_layout: 主版面配置
        """
        control_frame = QFrame(self)
        control_layout = QVBoxLayout(control_frame)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(Spacing.SMALL_PLUS)

        path_frame = QFrame(control_frame)
        path_layout = QHBoxLayout(path_frame)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(Spacing.SMALL_PLUS)

        path_layout.addWidget(BodyLabel("偵測路徑:", path_frame))

        self.detect_path_entry = LineEdit(path_frame)
        self.detect_path_entry.setText(str(self.server_crud.servers_root))
        path_layout.addWidget(self.detect_path_entry, 1)

        browse_button = PushButton("瀏覽", path_frame)
        browse_button.clicked.connect(self.browse_path)
        path_layout.addWidget(browse_button)

        control_layout.addWidget(path_frame)

        button_frame = QFrame(control_frame)
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(Spacing.TINY)
        button_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        detect_button = PushButton("🔍 偵測現有伺服器", button_frame)
        detect_button.setMinimumHeight(32)
        detect_button.clicked.connect(lambda _checked=False: self.detect_servers(show_message=True))
        button_layout.addWidget(detect_button)

        add_button = PushButton("➕ 手動新增", button_frame)
        add_button.setMinimumHeight(32)
        add_button.clicked.connect(self.add_server)
        button_layout.addWidget(add_button)

        refresh_button = PushButton("🔄 重新整理", button_frame)
        refresh_button.setMinimumHeight(32)
        refresh_button.clicked.connect(lambda _=False: self.refresh_servers(True))
        button_layout.addWidget(refresh_button)

        control_layout.addWidget(button_frame)
        main_layout.addWidget(control_frame)

    def create_server_list(self, main_layout) -> None:
        """建立伺服器列表

        Args:
            main_layout: 主版面配置
        """
        list_card = CardWidget(self)
        list_layout = QVBoxLayout(list_card)

        list_layout.addWidget(SubtitleLabel("伺服器列表", list_card))

        self.server_tree = TreeWidget(list_card)
        self.server_tree.setColumnCount(6)
        self.server_tree.setHeaderLabels(["名稱", "版本", "載入器", "狀態", "備份狀態", "路徑"])
        self.server_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.server_tree.header().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
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
        """顯示右鍵選單

        Args:
            pos: 滑鼠位置
        """
        if not self.server_tree:
            return
        items = self.server_tree.selectedItems()
        if not items:
            return

        menu = RoundMenu(parent=self)

        recheck_action = Action("🔄 重新檢測伺服器")
        recheck_action.triggered.connect(self.recheck_selected_server)
        menu.addAction(recheck_action)

        menu.addSeparator()

        open_backup_action = Action("📂 開啟備份資料夾")
        open_backup_action.triggered.connect(self.open_backup_folder)
        menu.addAction(open_backup_action)

        menu.exec(self.server_tree.mapToGlobal(pos))

    def recheck_selected_server(self) -> None:
        """重新檢測選中伺服器"""
        config = self._get_selected_server_config(show_warning=False)
        if not config:
            return
        server_name = config.name

        ServerDetectionUtils.detect_server_type(Path(config.path), config)
        self.server_crud.write_servers_config()
        self.refresh_servers()
        UIUtils.show_message("完成", f"已重新檢測伺服器：{server_name}", self.window(), message_level="info")

    def open_backup_folder(self) -> None:
        """開啟選中伺服器的備份資料夾"""
        config = self._get_selected_server_config()
        if not config:
            return

        backup_dir = Path(config.path) / "backups"
        if not backup_dir.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)

        try:
            UIUtils.open_external(str(backup_dir))
        except Exception as e:
            logger.bind(component="").error(f"無法開啟備份資料夾: {e}\n{traceback.format_exc()}", "ManageServerFrame")
            UIUtils.show_message("錯誤", f"無法開啟備份資料夾: {e}", self.window(), message_level="error")

    def create_actions(self, main_layout) -> None:
        """建立操作區

        Args:
            main_layout: 主版面配置
        """
        action_frame = QFrame(self)
        action_layout = QVBoxLayout(action_frame)
        action_layout.setContentsMargins(0, 0, 0, 0)

        action_layout.addWidget(SubtitleLabel("操作", action_frame))

        self.info_label = BodyLabel("選擇一個伺服器以查看詳細資訊", action_frame)
        action_layout.addWidget(self.info_label)

        button_frame = QFrame(action_frame)
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(Spacing.SMALL)
        button_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        buttons = [
            ("🚀", "啟動", self.start_server, "start_stop"),
            ("📊", "監控", self.monitor_server, "monitor"),
            ("⚙️", "設定", self.configure_server, "configure"),
            ("📂", "開啟資料夾", self.open_server_folder, "open_folder"),
            ("💾", "備份地圖檔", self.backup_server, "backup"),
            ("⏪", "還原備份", self.show_restore_dialog, "restore"),
            ("🗑️", "刪除", self.delete_server, "delete"),
        ]
        self.action_buttons = {}
        for emoji, text, command, fixed_key in buttons:
            btn_text = f"{emoji} {text}"
            if fixed_key == "start_stop":
                btn = PrimaryPushButton(btn_text, button_frame)
            else:
                btn = PushButton(btn_text, button_frame)

            if fixed_key == "delete":
                btn.setStyleSheet(f"QPushButton {{ color: {resolve_color(Colors.BUTTON_DANGER)}; }}")

            btn.clicked.connect(command)
            btn.setDisabled(True)
            button_layout.addWidget(btn)
            key = fixed_key if fixed_key else f"{emoji} {text}"
            self.action_buttons[key] = btn

        action_layout.addWidget(button_frame)
        main_layout.addWidget(action_frame)

    def browse_path(self) -> None:
        """瀏覽路徑"""
        path = QFileDialog.getExistingDirectory(self, "選擇伺服器目錄")
        if path:
            abs_path = Path(path).resolve()
            base_dir = str(abs_path)
            servers_root: str | None = None
            if self.set_servers_root:
                try:
                    servers_root = self.set_servers_root(base_dir)
                except Exception as e:
                    logger.bind(component="").error(
                        f"寫入伺服器路徑設定失敗: {e}\n{traceback.format_exc()}", "ManageServerFrame"
                    )
                    UIUtils.show_message("錯誤", f"無法寫入設定: {e}", self.window(), message_level="error")
                    return
                if not servers_root:
                    return
            else:
                try:
                    settings = get_settings_manager()
                    settings.set_servers_root(base_dir)
                    servers_root = str(settings.get_validated_servers_root_path(create=True))
                except Exception as e:
                    logger.bind(component="").error(
                        f"寫入伺服器路徑設定失敗: {e}\n{traceback.format_exc()}", "ManageServerFrame"
                    )
                    UIUtils.show_message("錯誤", f"無法寫入設定: {e}", self.window(), message_level="error")
                    return
            if servers_root is None:
                return
            self.detect_path_entry.setText(servers_root)
            self.server_crud.servers_root = Path(servers_root)
            self.refresh_servers()

    def detect_servers(self, show_message: bool = True) -> None:
        """偵測現有伺服器

        Args:
            show_message: 是否顯示偵測結果訊息
        """
        path = self.detect_path_entry.text()
        if not path or not Path(path).exists():
            if show_message:
                UIUtils.show_message("錯誤", "請選擇有效的路徑", self.window(), message_level="error")
            return

        def task():
            try:
                count = self._detect_servers_task(path)
                TaskUtils.call_on_ui(self, lambda: self._detect_servers_callback(count, show_message))
            except Exception as error:
                logger.error(f"偵測失敗: {error}\n{traceback.format_exc()}")
                error_msg = str(error)
                TaskUtils.call_on_ui(
                    self,
                    lambda: UIUtils.show_message(
                        "錯誤", f"偵測失敗: {error_msg}", self.window(), message_level="error"
                    ),
                )

        TaskUtils.run_async(task)

    def add_server(self) -> None:
        """手動新增伺服器 - 跳轉到建立伺服器頁面"""
        if self.on_navigate_callback:
            self.on_navigate_callback()

    def refresh_servers(self, reload_config: bool = True) -> None:
        """重新整理伺服器列表：只更新 UI，不自動偵測

        Args:
            reload_config: 是否重新讀取伺服器設定
        """
        self.service._last_server_data_hash = None

        def task():
            try:
                payload = self.service.refresh_servers_task(reload_config)
                TaskUtils.call_on_ui(self, lambda: self._refresh_servers_callback(payload))
            except Exception as e:
                logger.bind(component="").error(
                    f"重新整理伺服器列表失敗: {e}\n{traceback.format_exc()}", "ManageServerFrame"
                )

        TaskUtils.run_async(task)

    def select_server_by_name(self, server_name: str | None) -> None:
        """
        根據名稱選取伺服器

        Args:
            server_name: 要選取的伺服器名稱
        """
        if not self.server_tree or not server_name:
            return
        for i in range(self.server_tree.topLevelItemCount()):
            item = self.server_tree.topLevelItem(i)
            if item and item.text(0) == server_name:
                self.server_tree.clearSelection()
                item.setSelected(True)
                self.server_tree.scrollToItem(item)
                break

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
        """伺服器雙擊事件"""
        if self.server_tree and self.selected_server:
            self.configure_server()

    def update_selection(self) -> None:
        """更新選擇狀態"""
        has_selection = self.selected_server is not None
        if has_selection:
            is_running = self.server_startup.is_server_running(self.selected_server)
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
                    btn.setEnabled(True)
        else:
            for btn in self.action_buttons.values():
                btn.setEnabled(False)
            start_stop_key = "start_stop"
            if start_stop_key in self.action_buttons:
                self.action_buttons[start_stop_key].setText("🚀 啟動")

        if has_selection and self.selected_server in self.server_crud.servers:
            config = self.server_crud.servers[self.selected_server]
            is_running = self.server_startup.is_server_running(self.selected_server)
            status_emoji = "🟢" if is_running else "🔴"
            status_text = "運行中" if is_running else "已停止"
            memory_info = ""
            if hasattr(config, "memory_max_mb") and config.memory_max_mb:
                max_mem_str = MemoryUtils.format_memory_mb(config.memory_max_mb)
                if hasattr(config, "memory_min_mb") and config.memory_min_mb:
                    min_mem_str = MemoryUtils.format_memory_mb(config.memory_min_mb)
                    memory_info = f"記憶體: {min_mem_str}-{max_mem_str}"
                else:
                    memory_info = f"最大記憶體: {max_mem_str}"
            elif hasattr(config, "memory_mb") and config.memory_mb:
                memory_info = f"記憶體: {MemoryUtils.format_memory_mb(config.memory_mb)}"
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
        is_running = self.server_startup.is_server_running(self.selected_server)
        if is_running:
            success = ServerOperations.graceful_stop_server(self.server_startup, self.selected_server)
            if success:
                UIUtils.show_message(
                    "成功", f"伺服器 {self.selected_server} 停止命令已發送", self.window(), message_level="info"
                )
            else:
                UIUtils.show_message(
                    "錯誤", f"停止伺服器 {self.selected_server} 失敗", self.window(), message_level="error"
                )
            self._schedule_post_action_updates(100, 2000)
        else:
            start_result = self.server_startup.start_server_result(self.selected_server)
            if start_result.success:
                self.monitor_server(bring_to_front=False)
            else:
                UIUtils.show_message(
                    start_result.title or "錯誤",
                    start_result.message or f"啟動伺服器 {self.selected_server} 失敗",
                    self.window(),
                    message_level="error",
                )
            self._schedule_post_action_updates(100, 1500)

    def monitor_server(self, *, bring_to_front: bool = True) -> None:
        """監控伺服器

        Args:
            bring_to_front: 是否將監控視窗帶至前景
        """
        if not self.selected_server:
            return

        if not hasattr(self, "_monitor_windows"):
            self._monitor_windows: dict[str, ServerMonitorWindow] = {}

        if self.selected_server in self._monitor_windows:
            old_win = self._monitor_windows[self.selected_server]
            if old_win and hasattr(old_win, "window") and old_win.window and old_win.window.is_alive():
                self._show_existing_monitor_window(old_win.window, bring_to_front=bring_to_front)
                return

        monitor_window = ServerMonitorWindow(self.window(), self.server_startup, self.selected_server, self.server_crud)
        self._monitor_windows[self.selected_server] = monitor_window
        monitor_window.show()

    def configure_server(self) -> None:
        """設定伺服器"""
        if not self.selected_server:
            return
        config = self.server_crud.servers[self.selected_server]
        dialog = ServerPropertiesDialog(self.window(), config, self.server_crud)
        if dialog.result:
            self.server_crud.servers[self.selected_server] = dialog.result
            self.server_crud.write_servers_config()
            self.refresh_servers()
            UIUtils.show_message("成功", "伺服器設定已更新", self.window(), message_level="info")

    def open_server_folder(self) -> None:
        """開啟伺服器資料夾"""
        if not self.selected_server:
            return
        config = self.server_crud.servers[self.selected_server]
        path = config.path
        try:
            UIUtils.open_external(path)
        except Exception as e:
            logger.error(f"無法開啟資料夾: {e}\n{traceback.format_exc()}")
            UIUtils.show_message("錯誤", f"無法開啟資料夾: {e}", self.window(), message_level="error")

    def delete_server(self) -> None:
        """刪除伺服器"""
        if not self.selected_server:
            return
        result = UIUtils.ask_yes_no_cancel(
            "確認刪除",
            f"確定要刪除伺服器 '{self.selected_server}' 嗎？\n\n"
            + "⚠️ 這將永久刪除伺服器檔案與其所有的備份檔案，無法復原！",
            self.window(),
            show_cancel=False,
        )
        if not result:
            return

        delete_result = self.server_crud.delete_server_result(self.selected_server)
        if delete_result.success:
            UIUtils.show_message("成功", f"伺服器 {self.selected_server} 已刪除", self.window(), message_level="info")
            self.refresh_servers()
        else:
            UIUtils.show_message(
                delete_result.title or "錯誤",
                delete_result.message or f"刪除伺服器 {self.selected_server} 失敗",
                self.window(),
                message_level="error",
            )

    def backup_server(self) -> None:
        """備份伺服器檔案"""
        if not self.selected_server:
            return

        dialog = ProgressDialog(self.window(), title="備份伺服器", show_cancel=False)
        dialog.update_progress(0, "準備備份中...")

        def _backup_task() -> bool:
            return self.server_backup.backup_server(self.selected_server, progress_callback=dialog.update_progress)

        def _on_done(success: bool) -> None:
            def _ui_done():
                dialog.close()
                if success:
                    UIUtils.show_message("備份成功", "備份完成！", self.window(), message_level="info")
                    self.refresh_servers()
                else:
                    UIUtils.show_message(
                        "備份失敗", "備份失敗，請查看日誌以獲取詳細資訊", self.window(), message_level="error"
                    )

            run_on_ui_thread(_ui_done)

        run_in_background(_backup_task, callback=_on_done)
        dialog.exec_dialog()

    def show_restore_dialog(self) -> None:
        """顯示還原備份對話框"""
        if not self.selected_server:
            return
        dialog = RestoreBackupDialog(self.window(), self.selected_server, self.server_backup, self.server_crud)
        dialog.exec_dialog()

    def _auto_refresh_loop(self) -> None:
        """自動重新整理循環"""
        if getattr(self, "_auto_refresh_enabled", True):
            self.refresh_servers()
        UIUtils.schedule_debounce(self, "_auto_refresh_job", self._auto_refresh_interval_ms, self._auto_refresh_loop)

    def _schedule_post_action_updates(self, immediate_delay_ms: int, delayed_delay_ms: int) -> None:
        UIUtils.schedule_debounce(self, "_post_action_immediate_job", immediate_delay_ms, self._immediate_update)
        UIUtils.schedule_debounce(self, "_post_action_delayed_job", delayed_delay_ms, self._delayed_update)

    def _schedule_refresh(self, delay_ms: int) -> None:
        UIUtils.schedule_debounce(self, "_delayed_refresh_job", delay_ms, self.refresh_servers)

    def _get_selected_server_config(self, show_warning: bool = True) -> ServerConfig | None:
        """獲取當前選中的伺服器配置"""
        if not self.server_tree:
            return None
        items = self.server_tree.selectedItems()
        if not items:
            if show_warning:
                UIUtils.show_message("提示", "請先選擇伺服器", self.window(), message_level="warning")
            return None
        server_name = items[0].text(0)

        config = self.server_crud.servers.get(server_name)
        if not config:
            if show_warning:
                UIUtils.show_message("錯誤", f"找不到伺服器設定: {server_name}", self.window(), message_level="error")
            return None
        return config

    def _detect_servers_task(self, path):
        count = 0
        path_obj = Path(path)

        for item_path_obj in path_obj.iterdir():
            if item_path_obj.is_dir():
                item = item_path_obj.name
                item_path = str(item_path_obj)
                if ServerDetectionUtils.is_valid_server_folder(item_path_obj):
                    if item in self.server_crud.servers:
                        config = self.server_crud.servers[item]
                        config.path = str(item_path)
                    else:
                        config = ServerConfig(
                            name=item,
                            minecraft_version="Unknown",
                            loader_type="Unknown",
                            loader_version="Unknown",
                            memory_max_mb=2048,
                            path=item_path,
                        )
                    ServerDetectionUtils.detect_server_type(item_path_obj, config)
                    if item in self.server_crud.servers:
                        self.server_crud._prepare_imported_startup_scripts(config)
                        self.server_crud.write_servers_config()
                        count += 1
                    elif self.server_crud.add_server(config):
                        count += 1
        return count

    def _detect_servers_callback(self, count, show_message):
        if show_message:
            UIUtils.show_message("完成", f"成功偵測/更新 {count} 個伺服器", self.window(), message_level="info")
        self.refresh_servers()
        if self.server_tree:
            self.server_tree.viewport().update()

    def _refresh_servers_callback(self, payload: ServerRefreshPayload):
        if self.server_tree is None:
            return

        self._server_refresh_token += 1
        ServerRefreshContext(refresh_token=self._server_refresh_token, previous_selection=self.selected_server)

        execution_plan = self.service.build_server_refresh_execution_plan(
            payload, getattr(self, "_server_refresh_token", 0), getattr(self, "selected_server", None)
        )
        if not execution_plan.should_apply or execution_plan.refresh_context is None:
            self.update_selection()
            return

        self._apply_server_refresh_payload(payload, execution_plan.refresh_context)

    def _apply_server_refresh_payload(
        self, payload: ServerRefreshPayload, refresh_context: ServerRefreshContext
    ) -> None:
        if not self.server_tree:
            return

        selected_name = refresh_context.previous_selection
        self.server_tree.clear()
        items = []
        for name in payload.server_order:
            values = payload.server_rows[name]
            item = QTreeWidgetItem([str(v) for v in values])
            items.append(item)
        if items:
            self.server_tree.addTopLevelItems(items)

        self.selected_server = selected_name
        self.select_server_by_name(selected_name)
        self.update_selection()

    def _immediate_update(self) -> None:
        self.refresh_servers()
        self.update_selection()

    def _delayed_update(self) -> None:
        self.update_selection()
        self.refresh_servers()
