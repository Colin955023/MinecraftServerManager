"""
管理伺服器頁面
負責管理現有 Minecraft 伺服器的使用者介面
"""

import contextlib
import queue
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core import ServerCRUD, ServerStartup
from ..models import ServerConfig
from ..utils import (
    Colors,
    FontManager,
    FontSize,
    MemoryUtils,
    PathUtils,
    ServerDetectionUtils,
    ServerOperations,
    Sizes,
    Spacing,
    TaskUtils,
    TreeUtils,
    UIUtils,
    compute_adaptive_pool_limit,
    compute_exponential_moving_average,
    get_logger,
    get_settings_manager,
)
from ..utils.ui_support import qt_widgets as qt
from . import (
    ManageServerService,
    RestoreBackupDialog,
    ServerMonitorWindow,
    ServerPropertiesDialog,
    ServerRefreshContext,
    ServerRefreshPayload,
    ServerTreeDiffPreparation,
)

logger = get_logger().bind(component="ManageServerFrame")


class ManageServerFrame:
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
        self._qt_widget = qt.Frame(parent)
        self.server_crud = server_crud
        self.server_startup = server_startup
        self.server_backup = server_backup
        self.callback = callback
        self.on_navigate_callback = on_navigate_callback
        self.set_servers_root = set_servers_root
        self.selected_server: str | None = None
        self.service = ManageServerService(server_crud, server_startup, server_backup)
        self._widgets_created = False
        self.server_tree: qt.Treeview | None = None
        self.action_buttons: dict[str, Any] = {}
        self._server_refresh_job: str | None = None
        self._server_refresh_token = 0
        self._server_tree_render_locked = False
        self._server_item_by_name: dict[str, str] = {}
        self._server_rows_snapshot: dict[str, tuple[Any, ...]] = {}
        self._server_recycled_item_ids: list[str] = []
        self._server_recycle_pool_max = 300
        self._server_recycle_hits = 0
        self._server_recycle_misses = 0
        self._server_recycle_drops = 0
        self._server_recycle_log_every = 200
        self._server_recycle_pool_min = 150
        self._server_recycle_pool_cap = 1200
        self._server_recycle_tune_step = 50
        self._server_recycle_hit_rate_ema: float | None = None
        self._server_recycle_ema_alpha = 0.35
        self._server_insert_batch_base = 30
        self._server_insert_batch_max = 100
        self._server_insert_batch_divisor = 8
        self.ui_queue: queue.Queue = queue.Queue()
        self.create_widgets()
        TaskUtils.start_ui_queue_pump(self._qt_widget, self.ui_queue)
        self._post_action_immediate_job = None
        self._post_action_delayed_job = None
        self._delayed_refresh_job = None
        self._auto_refresh_enabled = True
        self._auto_refresh_interval_ms = 10000
        self._auto_refresh_job = None
        self._auto_refresh_loop()

    def __getattr__(self, name: str):
        qt = self.__dict__.get("_qt_widget", None)
        if qt is None:
            raise AttributeError(name)
        return getattr(qt, name)

    def _auto_refresh_loop(self) -> None:
        """自動重新整理循環"""
        if self.is_alive():
            if getattr(self, "_auto_refresh_enabled", True):
                self.refresh_servers()
            self._auto_refresh_job = self.schedule(self._auto_refresh_interval_ms, self._auto_refresh_loop)

    def set_auto_refresh_enabled(self, enabled: bool, *, refresh_now: bool = False) -> None:
        """
        啟用或停用此管理頁面的背景自動重新整理。

        此方法主要供外層 UI（例如分頁/頁籤容器）在切換顯示狀態時呼叫，用途如下：
        - 本頁不在前景時停用自動重新整理，降低 CPU 與 I/O 負擔。
        - 避免使用者瀏覽其他頁籤時，背景 TreeView 持續更新造成 UI 抖動。
        - 回到本頁時再啟用自動重新整理，必要時可立即重新整理一次。

        Args:
            enabled: True 啟用自動重新整理（允許 `_auto_refresh_loop` 週期性呼叫
                :meth:`refresh_servers`）；False 停用背景自動重新整理。
            refresh_now: 當 `enabled=True` 時，若此值也為 True，會立刻呼叫
                :meth:`refresh_servers`，確保頁面重新顯示時狀態立即更新。
        """
        self._auto_refresh_enabled = bool(enabled)
        if refresh_now and self._auto_refresh_enabled:
            self.refresh_servers()

    def _schedule_post_action_updates(self, immediate_delay_ms: int, delayed_delay_ms: int) -> None:
        UIUtils.schedule_debounce(self, "_post_action_immediate_job", immediate_delay_ms, self._immediate_update)
        UIUtils.schedule_debounce(self, "_post_action_delayed_job", delayed_delay_ms, self._delayed_update)

    def _schedule_refresh(self, delay_ms: int) -> None:
        UIUtils.schedule_debounce(self, "_delayed_refresh_job", delay_ms, self.refresh_servers)

    def create_widgets(self) -> None:
        """建立介面元件"""
        if getattr(self, "_widgets_created", False):
            return
        self._widgets_created = True
        main_container = qt.Frame(self, fg_color="transparent")
        main_container.attach(fill="both", expand=True, padx=Spacing.LARGE, pady=Spacing.LARGE)

        title_label = qt.Label(
            main_container,
            text="⚙️ 管理伺服器",
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
        )
        title_label.attach(pady=(0, Spacing.XL))
        self.create_controls(main_container)
        self.create_server_list(main_container)
        self.create_actions(main_container)

    def apply_theme_styles(self) -> None:
        """重新套用目前主題到管理伺服器頁面。"""
        try:
            self._qt_widget.setStyleSheet("QFrame { background: transparent; border: 0; }")
            if self.server_tree and hasattr(self.server_tree, "apply_theme_style"):
                self.server_tree.apply_theme_style()
                TreeUtils.refresh_treeview_alternating_rows(self.server_tree)
            if hasattr(self, "info_label") and self.info_label:
                self.info_label.configure(text_color=Colors.TEXT_PRIMARY)
        except Exception as e:
            logger.debug(f"套用管理伺服器頁面主題失敗: {e}")

    def create_controls(self, parent) -> None:
        """
        建立控制區。

        Args:
            parent: 控制區的父容器。

        Returns:
            None。
        """
        control_frame = qt.Frame(parent, fg_color="transparent")
        control_frame.attach(fill="x", pady=(0, Spacing.XL))

        path_frame = qt.Frame(control_frame, fg_color="transparent")
        path_frame.attach(fill="x", padx=Spacing.LARGE_MINUS, pady=(0, Spacing.SMALL_PLUS))
        qt.Label(path_frame, text="偵測路徑:", font=FontManager.get_font(size=FontSize.NORMAL)).attach(side="left")
        self.detect_path_var = qt.TextState(value=str(self.server_crud.servers_root))
        self.detect_path_entry = qt.Entry(
            path_frame, textvariable=self.detect_path_var, font=FontManager.get_font(size=FontSize.SMALL)
        )
        self.detect_path_entry.attach(side="left", fill="x", expand=True, padx=(Spacing.SMALL_PLUS, 0))
        browse_button = UIUtils.create_styled_button(
            path_frame, text="瀏覽", command=self.browse_path, button_type="small"
        )
        browse_button.attach(side="left", padx=(Spacing.TINY, 0))

        button_frame = qt.Frame(control_frame, fg_color="transparent")
        button_frame.attach(pady=(0, Spacing.LARGE_MINUS))
        detect_button = UIUtils.create_styled_button(
            button_frame,
            text="🔍 偵測現有伺服器",
            command=lambda: self.detect_servers(show_message=True),
            button_type="secondary",
        )
        detect_button.attach(side="left", padx=Spacing.TINY)
        add_button = UIUtils.create_styled_button(
            button_frame, text="➕ 手動新增", command=self.add_server, button_type="secondary"
        )
        add_button.attach(side="left", padx=Spacing.TINY)
        refresh_button = UIUtils.create_styled_button(
            button_frame, text="🔄 重新整理", command=self.refresh_servers, button_type="secondary"
        )
        refresh_button.attach(side="left", padx=Spacing.TINY)

    def create_server_list(self, parent) -> None:
        """
        建立伺服器列表。

        Args:
            parent: 父容器。
        """
        list_frame = qt.LabelFrame(parent, text="伺服器列表", padding=5)
        list_frame.attach(fill="both", expand=True, pady=(0, Spacing.XL))
        columns = ("名稱", "版本", "載入器", "狀態", "備份狀態", "路徑")
        self.server_tree = qt.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")
        self.server_tree.heading("名稱", text="名稱")
        self.server_tree.heading("版本", text="版本")
        self.server_tree.heading("載入器", text="載入器")
        self.server_tree.heading("狀態", text="狀態")
        self.server_tree.heading("備份狀態", text="備份狀態")
        self.server_tree.heading("路徑", text="路徑")
        self._apply_server_tree_columns_layout()
        self.server_tree.connect_event("selection_changed", self.on_server_select)
        TreeUtils.bind_treeview_header_auto_fit(
            self.server_tree,
            on_row_double_click=self.on_server_double_click,
            heading_font=FontManager.get_font("Microsoft JhengHei", FontSize.HEADING_SMALL_PLUS, "bold"),
            body_font=FontManager.get_font("Microsoft JhengHei", FontSize.LARGE),
            stretch_columns={"路徑"},
        )
        self.server_tree.connect_event("mouse_right_press", self.show_server_context_menu)
        scrollbar = qt.Scrollbar(list_frame, orient="vertical", command=self.server_tree.yview)
        h_scrollbar = qt.Scrollbar(list_frame, orient="horizontal", command=self.server_tree.xview)
        self.server_tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=h_scrollbar.set)

        self.server_tree.attach_matrix(row=0, column=0, sticky="nsew")
        scrollbar.attach_matrix(row=0, column=1, sticky="ns")
        h_scrollbar.attach_matrix(row=1, column=0, sticky="ew")
        list_frame.set_grid_row_stretch(0, weight=1)
        list_frame.set_grid_column_stretch(0, weight=1)

    def _server_tree_display_columns(self) -> tuple[str, ...]:
        return ("名稱", "版本", "載入器", "狀態", "備份狀態", "路徑")

    def _apply_server_tree_columns_layout(self) -> None:
        """套用伺服器 Tree 欄位配置（除路徑欄外皆固定寬）。"""
        if not self.server_tree:
            return
        tree = self.server_tree
        tree.configure(displaycolumns=self._server_tree_display_columns())
        name_width = Sizes.SERVER_TREE_COL_NAME
        version_width = Sizes.SERVER_TREE_COL_VERSION
        loader_width = Sizes.SERVER_TREE_COL_LOADER
        status_width = Sizes.SERVER_TREE_COL_STATUS
        backup_width = Sizes.SERVER_TREE_COL_BACKUP
        path_width = Sizes.SERVER_TREE_COL_PATH
        tree.column("名稱", width=name_width, minwidth=name_width, stretch=False, anchor="w")
        tree.column("版本", width=version_width, minwidth=version_width, stretch=False, anchor="w")
        tree.column("載入器", width=loader_width, minwidth=loader_width, stretch=False, anchor="w")
        tree.column("狀態", width=status_width, minwidth=status_width, stretch=False, anchor="w")
        tree.column("備份狀態", width=backup_width, minwidth=backup_width, stretch=False, anchor="w")
        tree.column("路徑", width=path_width, minwidth=path_width, stretch=True, anchor="w")

    def _get_server_tree_column_from_x(self, x: int) -> str | None:
        """依滑鼠 x 座標回傳對應欄位名稱。"""
        tree = self.server_tree
        if not tree:
            return None
        col_ref = tree.identify_column(x)
        if not col_ref or col_ref == "#0":
            return None
        try:
            column_idx = int(str(col_ref).lstrip("#")) - 1
        except (TypeError, ValueError) as _:
            return None
        columns = self._server_tree_display_columns()
        if column_idx < 0 or column_idx >= len(columns):
            return None
        return columns[column_idx]

    def _get_server_tree_separator_column_from_x(self, x: int) -> str | None:
        """依滑鼠 x 座標偵測是否靠近欄位分隔線，並回傳左側欄位。"""
        tree = self.server_tree
        if not tree:
            return None
        columns = self._server_tree_display_columns()
        if not columns:
            return None
        widths = [int(tree.column(col, "width")) for col in columns]
        total_width = sum(widths)
        xview_start = 0.0
        try:
            xview = tree.xview()
            if xview and len(xview) >= 1:
                xview_start = float(xview[0])
        except Exception:
            xview_start = 0.0
        logical_x = int(x + xview_start * total_width)
        threshold = 5
        boundary = 0
        for idx, width in enumerate(widths):
            boundary += width
            if abs(logical_x - boundary) <= threshold:
                return columns[idx]
        return None

    def _auto_fit_server_tree_column(self, column_id: str) -> None:
        """將指定欄位寬度調整為目前內容最寬值。"""
        tree = self.server_tree
        if not tree:
            return
        heading_font = qt.Font(font=FontManager.get_font("Microsoft JhengHei", FontSize.HEADING_SMALL_PLUS, "bold"))
        body_font = qt.Font(font=FontManager.get_font("Microsoft JhengHei", FontSize.LARGE))
        padding = 11
        safety_min_width = 9
        heading_text = str(tree.heading(column_id, "text") or column_id)
        max_width = heading_font.measure(heading_text)
        try:
            column_index = self._server_tree_display_columns().index(column_id)
        except ValueError:
            return
        for item_id in tree.get_children():
            values = tree.item(item_id, "values") or ()
            if column_index >= len(values):
                continue
            max_width = max(max_width, body_font.measure(str(values[column_index])))
        computed_width = max(safety_min_width, int(max_width + padding))
        tree.column(column_id, width=computed_width, minwidth=safety_min_width, stretch=column_id == "路徑", anchor="w")

    def show_server_context_menu(self, event) -> None:
        """
        顯示右鍵選單。

        Args:
            event: 滑鼠右鍵事件。
        """
        if not self.server_tree:
            return
        selection = self.server_tree.selection()
        if not selection:
            return
        menu = qt.PopupMenu(self, tearoff=0, font=FontManager.get_font("Microsoft JhengHei", FontSize.LARGE))
        menu.add_command(label="🔄 重新檢測伺服器", command=self.recheck_selected_server)
        menu.add_separator()
        menu.add_command(label="📁 重新設定備份路徑", command=self.reset_backup_path)
        menu.add_command(label="📂 開啟備份資料夾", command=self.open_backup_folder)
        try:
            menu.popup_at(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _get_selected_server_config(self, show_warning: bool = True) -> ServerConfig | None:
        """獲取當前選中的伺服器配置"""
        if not self.server_tree:
            return None
        selection = self.server_tree.selection()
        if not selection:
            if show_warning:
                UIUtils.show_warning("提示", "請先選擇伺服器", self.top_level_widget())
            return None
        item = self.server_tree.item(selection[0])
        values = item["values"]
        if not values or len(values) < 1:
            if show_warning:
                UIUtils.show_warning("提示", "無法取得伺服器名稱", self.top_level_widget())
            return None
        server_name = values[0]
        config = self.server_crud.servers.get(server_name)
        if not config:
            if show_warning:
                UIUtils.show_error("錯誤", f"找不到伺服器設定: {server_name}", self.top_level_widget())
            return None
        return config

    def recheck_selected_server(self) -> None:
        """重新檢測選中伺服器"""
        config = self._get_selected_server_config(show_warning=False)
        if not config:
            return
        server_name = config.name

        ServerDetectionUtils.detect_server_type(Path(config.path), config)
        self.server_crud.write_servers_config()
        self.refresh_servers()
        UIUtils.show_info("完成", f"已重新檢測伺服器：{server_name}", self.top_level_widget())

    def reset_backup_path(self) -> None:
        """重新設定選中伺服器的備份路徑"""
        config = self._get_selected_server_config()
        if not config:
            return
        server_name = config.name
        parent_backup_path = qt.get_existing_directory(
            title=f"重新設定 {server_name} 的備份路徑", initialdir=str(Path.home())
        )
        if parent_backup_path:
            backup_folder_name = f"{server_name}_backup"
            new_backup_path = str(Path(parent_backup_path) / backup_folder_name)
            try:
                Path(new_backup_path).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.bind(component="").error(
                    f"無法建立備份資料夾: {e}\n{traceback.format_exc()}", "ManageServerFrame"
                )
                UIUtils.show_error("錯誤", f"無法建立備份資料夾: {e}", self.top_level_widget())
                return
            config.backup_path = new_backup_path
            self.server_crud.write_servers_config()
            logger.bind(component="BackupServer").info(
                f"伺服器 {server_name} 的備份路徑已更新為: {new_backup_path}",
                extra={"server_name": server_name, "backup_path": new_backup_path, "operation": "write_servers_config"},
            )
            UIUtils.show_info(
                "成功", f"已將伺服器 {server_name} 的備份路徑設定為：\n{new_backup_path}", self.top_level_widget()
            )
            self.refresh_servers()
        else:
            UIUtils.show_info("取消", "未更改備份路徑設定", self.top_level_widget())

    def open_backup_folder(self) -> None:
        """開啟選中伺服器的備份資料夾"""
        if self.server_tree is None:
            return
        selection = self.server_tree.selection()
        if not selection:
            UIUtils.show_warning("提示", "請先選擇要開啟備份資料夾的伺服器", self.top_level_widget())
            return
        item = self.server_tree.item(selection[0])
        values = item["values"]
        if not values or len(values) < 1:
            UIUtils.show_warning("提示", "無法取得伺服器名稱", self.top_level_widget())
            return
        server_name = values[0]
        config = self.server_crud.servers.get(server_name)
        if not config:
            UIUtils.show_error("錯誤", f"找不到伺服器設定: {server_name}", self.top_level_widget())
            return
        if not hasattr(config, "backup_path") or not config.backup_path:
            UIUtils.show_warning(
                "提示",
                f"伺服器 {server_name} 尚未設定備份路徑\n請先執行一次備份來設定備份路徑",
                self.top_level_widget(),
            )
            return
        if not Path(config.backup_path).exists():
            UIUtils.show_error(
                "錯誤", f"備份路徑不存在：\n{config.backup_path}\n\n請重新設定備份路徑", self.top_level_widget()
            )
            return
        try:
            UIUtils.open_external(config.backup_path)
        except Exception as e:
            logger.bind(component="").error(f"無法開啟備份資料夾: {e}\n{traceback.format_exc()}", "ManageServerFrame")
            UIUtils.show_error("錯誤", f"無法開啟備份資料夾: {e}", self.top_level_widget())

    def create_actions(self, parent) -> None:
        """
        建立操作區。

        Args:
            parent: 父容器。
        """
        action_frame = qt.Frame(parent)
        action_frame.attach(fill="x")
        action_title = qt.Label(
            action_frame, text="操作", font=FontManager.get_font(size=FontSize.MEDIUM, weight="bold")
        )
        action_title.attach(anchor="w", pady=(Spacing.TINY, 0), padx=(Spacing.LARGE_MINUS, 0))
        info_frame = qt.Frame(action_frame, fg_color="transparent")
        info_frame.attach(fill="x", padx=Spacing.LARGE_MINUS, pady=(Spacing.TINY, Spacing.TINY))
        self.info_label = qt.Label(
            info_frame, text="選擇一個伺服器以查看詳細資訊", font=FontManager.get_font(size=FontSize.MEDIUM)
        )
        self.info_label.attach(anchor="w")
        button_frame = qt.Frame(action_frame, fg_color="transparent")
        button_frame.attach(anchor="w", padx=Spacing.SMALL, pady=(0, Spacing.SMALL_PLUS))
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
            btn = UIUtils.create_styled_button(
                button_frame, text=btn_text, command=command, button_type="secondary", state="disabled"
            )
            btn.attach(side="left", padx=(0, Spacing.XS))
            key = fixed_key if fixed_key else f"{emoji} {text}"
            self.action_buttons[key] = btn

    def browse_path(self) -> None:
        """瀏覽路徑，並自動正規化、寫入設定、建立 servers 子資料夾、重新整理清單"""
        path = qt.get_existing_directory(title="選擇伺服器目錄")
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
                    UIUtils.show_error("錯誤", f"無法寫入設定: {e}", self.top_level_widget())
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
                    UIUtils.show_error("錯誤", f"無法寫入設定: {e}", self.top_level_widget())
                    return
            if servers_root is None:
                return
            self.detect_path_var.set(servers_root)
            self.server_crud.servers_root = Path(servers_root)
            self.refresh_servers()

    def detect_servers(self, show_message: bool = True) -> None:
        """
        偵測現有伺服器，無論新建或覆蓋都會呼叫 `detect_server_type`。

        Args:
            show_message: 是否在完成後顯示提示訊息。
        """
        path = self.detect_path_var.get()
        if not path or not Path(path).exists():
            if show_message:
                UIUtils.show_error("錯誤", "請選擇有效的路徑", self.top_level_widget())
            return

        def task():
            """執行背景任務的工作內容。"""
            try:
                count = self._detect_servers_task(path)
                self.ui_queue.put(lambda: self._detect_servers_callback(count, show_message))
            except Exception as error:
                logger.error(f"偵測失敗: {error}\n{traceback.format_exc()}")
                error_msg = str(error)
                self.ui_queue.put(lambda: UIUtils.show_error("錯誤", f"偵測失敗: {error_msg}", self.top_level_widget()))

        TaskUtils.run_async(task)

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
            UIUtils.show_info("完成", f"成功偵測/更新 {count} 個伺服器", self.top_level_widget())
        self.refresh_servers()

    def add_server(self) -> None:
        """手動新增伺服器 - 跳轉到建立伺服器頁面"""
        if self.on_navigate_callback:
            self.on_navigate_callback()

    def _cancel_server_refresh_job(self) -> None:
        """
        取消尚未完成的列表插入工作（共用排程 helper）。

        在新一輪重新整理開始前呼叫，立即終止舊輪次尚未執行的 after 批次工作。
        """
        tree = self.server_tree
        if not tree:
            self._server_refresh_job = None
            return
        UIUtils.cancel_scheduled_job(tree, "_server_refresh_job", owner=self)

    def _set_server_tree_render_lock(self, locked: bool) -> None:
        """大量重新整理 Treeview 前後鎖住父容器幾何，減少重排閃爍。"""
        if not self.server_tree:
            return
        parent = self.server_tree.master
        if locked:
            if getattr(self, "_server_tree_render_locked", False):
                return
            try:
                parent.set_box_layout_propagation(False)
                self._server_tree_render_locked = True
            except Exception as e:
                logger.debug(f"鎖定 server tree 佈局失敗: {e}", "ManageServerFrame")
            return
        if not getattr(self, "_server_tree_render_locked", False):
            logger.warning("收到解除 server tree 佈局鎖要求，但目前未鎖定。")
            return
        try:
            parent.set_box_layout_propagation(True)
        except Exception as e:
            logger.debug(f"解除 server tree 佈局鎖失敗: {e}", "ManageServerFrame")
        finally:
            self._server_tree_render_locked = False

    def _begin_server_refresh_cycle(self) -> ServerRefreshContext:
        """建立新一輪 refresh 狀態，並使舊輪次失效。"""
        self._cancel_server_refresh_job()
        self._server_refresh_token += 1
        return ServerRefreshContext(refresh_token=self._server_refresh_token, previous_selection=self.selected_server)

    def _recycle_server_item(self, item_id: str) -> None:
        """將不再顯示的 Tree item 先 detach 進重用池，降低後續 insert 成本。"""
        if not self.server_tree or not item_id:
            return
        try:
            if not self.server_tree.exists(item_id):
                return
            self.server_tree.detach(item_id)
            pool = self._server_recycled_item_ids
            pool.append(item_id)
            max_size = max(0, int(getattr(self, "_server_recycle_pool_max", 300)))
            if len(pool) > max_size:
                stale_id = pool.pop(0)
                self._server_recycle_drops += 1
                with contextlib.suppress(Exception):
                    if self.server_tree.exists(stale_id):
                        self.server_tree.delete(stale_id)
                self._maybe_log_server_recycle_stats()
        except Exception as e:
            logger.debug(f"回收 server tree item 失敗 item_id={item_id}: {e}", "ManageServerFrame")

    def _acquire_recycled_server_item(self) -> str | None:
        """從重用池取回可用的 Tree item。"""
        tree = self.server_tree
        if not tree:
            return None
        pool = self._server_recycled_item_ids
        while pool:
            candidate = pool.pop()
            with contextlib.suppress(Exception):
                if tree.exists(candidate):
                    self._server_recycle_hits += 1
                    self._maybe_log_server_recycle_stats()
                    return candidate
        self._server_recycle_misses += 1
        self._maybe_log_server_recycle_stats()
        return None

    def _maybe_log_server_recycle_stats(self) -> None:
        """定期輸出重用池命中統計（debug），用於調整池大小。"""
        interval = max(1, int(getattr(self, "_server_recycle_log_every", 200)))
        total = int(getattr(self, "_server_recycle_hits", 0)) + int(getattr(self, "_server_recycle_misses", 0))
        if total <= 0 or total % interval != 0:
            return
        raw_hit_rate = self._server_recycle_hits / total * 100.0
        smoothed_hit_rate = compute_exponential_moving_average(
            previous=getattr(self, "_server_recycle_hit_rate_ema", None),
            current=raw_hit_rate,
            alpha=float(getattr(self, "_server_recycle_ema_alpha", 0.35)),
        )
        self._server_recycle_hit_rate_ema = smoothed_hit_rate
        self._auto_tune_server_recycle_pool(smoothed_hit_rate)
        message = f"server recycle stats pool={len(self._server_recycled_item_ids)} hits={self._server_recycle_hits} misses={self._server_recycle_misses} drops={self._server_recycle_drops} hit_rate={raw_hit_rate:.1f}% ema={smoothed_hit_rate:.1f}%"
        logger.debug(message, "ManageServerFrame")

    def _auto_tune_server_recycle_pool(self, hit_rate: float) -> None:
        """依命中率自動微調 recycle pool 上限。"""
        current = max(1, int(getattr(self, "_server_recycle_pool_max", 300)))
        min_size = max(1, int(getattr(self, "_server_recycle_pool_min", 150)))
        cap_size = max(min_size, int(getattr(self, "_server_recycle_pool_cap", 1200)))
        step = max(1, int(getattr(self, "_server_recycle_tune_step", 50)))
        pool_len = len(self._server_recycled_item_ids)
        new_size = compute_adaptive_pool_limit(
            current=current, min_size=min_size, cap_size=cap_size, step=step, pool_len=pool_len, hit_rate=hit_rate
        )
        if new_size != current:
            self._server_recycle_pool_max = new_size
            logger.debug(
                f"自動調整 server recycle pool 上限: {current} -> {new_size} (hit_rate={hit_rate:.1f}%)",
                "ManageServerFrame",
            )

    def _get_server_insert_batch_size(self, pending_count: int) -> int:
        """依待插入筆數動態計算批次大小，兼顧小清單與大清單流暢度。"""
        if pending_count <= 0:
            return 1
        base = max(1, int(getattr(self, "_server_insert_batch_base", 30)))
        max_size = max(base, int(getattr(self, "_server_insert_batch_max", 100)))
        divisor = max(1, int(getattr(self, "_server_insert_batch_divisor", 8)))
        dynamic_size = max(base, pending_count // divisor)
        dynamic_size = min(dynamic_size, max_size)
        return min(dynamic_size, pending_count)

    def _restore_server_selection(self, previous_selection: str | None) -> None:
        """盡量還原重新整理前選取列。"""
        if not self.server_tree:
            return
        self.selected_server = None
        if previous_selection:
            item_id = self._server_item_by_name.get(previous_selection)
            if item_id:
                try:
                    self.server_tree.selection_set(item_id)
                    self.server_tree.see(item_id)
                    self.selected_server = previous_selection
                except Exception as e:
                    logger.debug(f"還原伺服器選取失敗: {e}", "ManageServerFrame")

    def _finalize_server_refresh(
        self, *, refresh_token: int, previous_selection: str | None, rows_snapshot: dict[str, tuple[Any, ...]]
    ) -> None:
        """重新整理收尾：避免過期任務覆寫新狀態。"""
        if refresh_token != self._server_refresh_token:
            return
        self._server_refresh_job = None
        self._server_rows_snapshot = rows_snapshot
        if self.server_tree and self.server_tree.is_alive():
            TreeUtils.refresh_treeview_alternating_rows(self.server_tree)
        self._restore_server_selection(previous_selection)
        self.update_selection()
        self._set_server_tree_render_lock(False)

    def _prepare_server_tree_diff(
        self, *, tree: Any, server_order: list[str], server_rows: dict[str, tuple[Any, ...]]
    ) -> ServerTreeDiffPreparation:
        """更新既有列並回傳待插入資料與最新 snapshot。"""
        rows_snapshot: dict[str, tuple[Any, ...]] = {}
        pending_insert: list[tuple[str, tuple[Any, ...]]] = []
        previous_snapshot = getattr(self, "_server_rows_snapshot", {})
        for name in server_order:
            values = server_rows[name]
            item_id = self._server_item_by_name.get(name)
            if item_id:
                try:
                    if previous_snapshot.get(name) != values:
                        tree.item(item_id, values=values)
                    rows_snapshot[name] = values
                    continue
                except Exception as e:
                    logger.debug(f"更新伺服器列失敗 name={name}: {e}", "ManageServerFrame")
                    self._recycle_server_item(item_id)
                    self._server_item_by_name.pop(name, None)
            pending_insert.append((name, values))
        return ServerTreeDiffPreparation(rows_snapshot=rows_snapshot, pending_insert=pending_insert)

    def _remove_stale_server_items(self, server_rows: dict[str, tuple[Any, ...]]) -> None:
        """回收不在 ``server_rows`` 中的過期伺服器項目。"""
        for name, stale_item_id in list(self._server_item_by_name.items()):
            if name not in server_rows:
                self._recycle_server_item(stale_item_id)
                self._server_item_by_name.pop(name, None)

    def _apply_server_tree_diff(
        self,
        *,
        server_order: list[str],
        server_rows: dict[str, tuple[Any, ...]],
        refresh_token: int,
        previous_selection: str | None,
    ) -> None:
        """以差異更新 Treeview，減少 delete/insert 造成的卡頓。"""
        tree = getattr(self, "server_tree", None)
        if not tree or not tree.is_alive():
            self._set_server_tree_render_lock(False)
            return

        # 1. 將舊輪次資料中，這次不再存在的項目清掉
        self._remove_stale_server_items(server_rows)

        # 2. 透過 Service 比對差異
        diff_preparation = self.service.prepare_server_tree_diff(
            server_order=server_order,
            server_rows=server_rows,
            server_item_by_name=self._server_item_by_name,
            previous_snapshot=getattr(self, "_server_rows_snapshot", {}),
        )

        rows_snapshot = diff_preparation.rows_snapshot
        pending_update = diff_preparation.pending_update
        pending_insert = diff_preparation.pending_insert

        # 3. 先更新既有的 (不會改變長度，也不需要 async batch)
        for entry in pending_update:
            # 支援過去的 (name, item_id, values) 及現在的 (item_id, values) 兩種格式
            if len(entry) == 3:
                name, item_id, values = entry
            else:
                item_id, values = entry
                # 透過反查取得對應名稱（若找不到則為 None）
                name = next((k for k, v in self._server_item_by_name.items() if v == item_id), None)
            try:
                tree.item(item_id, values=values)
            except Exception as e:
                logger.debug(f"更新伺服器列失敗 name={name}: {e}", "ManageServerFrame")
                self._recycle_server_item(item_id)
                if name:
                    self._server_item_by_name.pop(name, None)
                pending_insert.append((name or "", values))

        if not server_order:
            self._server_item_by_name.clear()
            self._finalize_server_refresh(
                refresh_token=refresh_token, previous_selection=previous_selection, rows_snapshot={}
            )
            return

        batch_size = self._get_server_insert_batch_size(len(pending_insert))

        def _update_recycled(item_id: str, entry: tuple) -> None:
            tree.item(item_id, values=entry[1])
            tree.reattach(item_id, "", "end")

        def _finalize() -> None:
            self._finalize_server_refresh(
                refresh_token=refresh_token, previous_selection=previous_selection, rows_snapshot=rows_snapshot
            )

        insert_batch = TreeUtils.make_tree_insert_batch(
            tree=tree,
            pending_insert=pending_insert,
            batch_size=batch_size,
            is_refresh_token_valid=lambda: refresh_token == self._server_refresh_token,
            acquire_recycled=lambda _entry: self._acquire_recycled_server_item(),
            update_recycled=_update_recycled,
            insert_new=lambda _idx, entry: tree.insert("", "end", values=entry[1]),
            set_mapping=lambda key, item_id: self._server_item_by_name.__setitem__(key, item_id),
            mapping_get=lambda key: self._server_item_by_name.get(key),
            get_key=lambda entry: entry[0],
            set_row_snapshot=lambda key, values: rows_snapshot.__setitem__(key, values),
            get_order=lambda: server_order,
            _get_rows=lambda key: server_rows.get(key),
            finalize_cb=_finalize,
            set_refresh_job=lambda v: setattr(self, "_server_refresh_job", v),
            move_item=lambda item_id, idx: tree.move(item_id, "", idx),
            logger_name="ManageServerFrame",
        )
        if pending_insert:
            insert_batch(0, None)
            return
        try:
            for order_index, name in enumerate(server_order):
                item_id = self._server_item_by_name.get(name)
                if item_id:
                    tree.move(item_id, "", order_index)
                    rows_snapshot[name] = server_rows[name]
        except Exception as e:
            logger.debug(f"重排伺服器列表失敗: {e}", "ManageServerFrame")
        self._finalize_server_refresh(
            refresh_token=refresh_token, previous_selection=previous_selection, rows_snapshot=rows_snapshot
        )

    def refresh_servers(self, reload_config: bool = True) -> None:
        """
        重新整理伺服器列表：只更新 UI，不自動偵測。

        Args:
            reload_config: 是否重新載入伺服器設定。
        """

        def task():
            """執行背景任務的工作內容。"""
            try:
                payload = self.service.refresh_servers_task(reload_config)
                self.ui_queue.put(lambda: self._refresh_servers_callback(payload))
            except Exception as e:
                logger.bind(component="").error(
                    f"重新整理伺服器列表失敗: {e}\n{traceback.format_exc()}", "ManageServerFrame"
                )

        TaskUtils.run_async(task)

    def _refresh_servers_callback(self, payload: ServerRefreshPayload):
        """UI 更新回調"""
        if self.server_tree is None:
            return
        execution_plan = self.service.build_server_refresh_execution_plan(
            payload, getattr(self, "_server_refresh_token", 0), getattr(self, "selected_server", None)
        )
        if not execution_plan.should_apply or execution_plan.refresh_context is None:
            self.update_selection()
            return

        self._cancel_server_refresh_job()
        self._server_refresh_token = execution_plan.refresh_context.refresh_token
        self._apply_server_refresh_payload(payload, execution_plan.refresh_context)

    def _apply_server_refresh_payload(
        self, payload: ServerRefreshPayload, refresh_context: ServerRefreshContext
    ) -> None:
        """將 payload 套用到 UI Treeview。"""
        self._set_server_tree_render_lock(True)
        lock_handed_off = False
        try:
            self._apply_server_tree_diff(
                server_order=payload.server_order,
                server_rows=payload.server_rows,
                refresh_token=refresh_context.refresh_token,
                previous_selection=refresh_context.previous_selection,
            )
            lock_handed_off = True
        finally:
            if not lock_handed_off:
                self._set_server_tree_render_lock(False)

    def on_server_select(self, _event) -> None:
        """
        伺服器選擇事件。

        Args:
            _event: 事件物件。
        """
        if not self.server_tree:
            return
        selection = self.server_tree.selection()
        if selection:
            item = self.server_tree.item(selection[0])
            self.selected_server = item["values"][0]
            self.callback(self.selected_server)
        else:
            self.selected_server = None
        self.update_selection()

    def on_server_tree_double_click(self, event) -> str | None:
        """
        Treeview 雙擊事件：欄位分隔線自動調寬，列雙擊開啟設定。

        Args:
            event: 滑鼠事件。

        Returns:
            若攔截事件則回傳 `break`，否則回傳 None。
        """
        tree = self.server_tree
        if not tree:
            return None
        region = tree.identify_region(event.x, event.y)
        if region in ("separator", "heading"):
            if region == "heading":
                column_id = self._get_server_tree_column_from_x(event.x)
            else:
                column_id = self._get_server_tree_separator_column_from_x(event.x)
                if not column_id:
                    column_id = self._get_server_tree_column_from_x(event.x)
            if column_id:
                self._auto_fit_server_tree_column(column_id)
                return "break"
            return None
        self.on_server_double_click(event)
        return None

    def on_server_double_click(self, event) -> None:
        """
        伺服器雙擊事件。

        Args:
            event: 滑鼠事件。
        """
        if self.server_tree and self.server_tree.identify_row(event.y) and self.selected_server:
            self.configure_server()

    def update_selection(self) -> None:
        """更新選擇狀態"""
        has_selection = self.selected_server is not None
        if has_selection:
            is_running = self.server_startup.is_server_running(self.selected_server)
            start_stop_key = "start_stop"
            if is_running:
                if start_stop_key in self.action_buttons:
                    self.action_buttons[start_stop_key].configure(text="🛑 停止", state="normal")
            elif start_stop_key in self.action_buttons:
                self.action_buttons[start_stop_key].configure(text="🚀 啟動", state="normal")
            for key, btn in self.action_buttons.items():
                if key != start_stop_key:
                    btn.configure(state="normal")
        else:
            for btn in self.action_buttons.values():
                btn.configure(state="disabled")
            start_stop_key = "start_stop"
            if start_stop_key in self.action_buttons:
                self.action_buttons[start_stop_key].configure(text="🚀 啟動")
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
            self.info_label.configure(text=info_text)
        else:
            self.info_label.configure(text="✨ 選擇一個伺服器以查看詳細資訊")

    @staticmethod
    def _show_existing_monitor_window(window: Any, *, bring_to_front: bool) -> None:
        """顯示已存在的監控視窗，並選擇性地帶出到前面。"""
        if bring_to_front:
            show_normal = getattr(window, "showNormal", None)
            if callable(show_normal):
                with contextlib.suppress(Exception):
                    show_normal()
            else:
                with contextlib.suppress(Exception):
                    window.show()
            for method_name in ("raise_", "activateWindow", "setFocus"):
                method = getattr(window, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception as e:
                        logger.debug(f"帶出監控視窗失敗 method={method_name}: {e}", "ManageServerFrame")
            return

        window.show()

    def start_server(self) -> None:
        """啟動/停止伺服器"""
        if not self.selected_server:
            return
        is_running = self.server_startup.is_server_running(self.selected_server)
        if is_running:
            success = ServerOperations.graceful_stop_server(self.server_startup, self.selected_server)
            if success:
                UIUtils.show_info("成功", f"伺服器 {self.selected_server} 停止命令已發送", self.top_level_widget())
            else:
                UIUtils.show_error("錯誤", f"停止伺服器 {self.selected_server} 失敗", self.top_level_widget())
            self._schedule_post_action_updates(100, 2000)
        else:
            start_result = self.server_startup.start_server_result(self.selected_server)
            if start_result.success:
                self.monitor_server(bring_to_front=False)
            else:
                UIUtils.show_error(
                    start_result.title or "錯誤",
                    start_result.message or f"啟動伺服器 {self.selected_server} 失敗",
                    self.top_level_widget(),
                )
            self._schedule_post_action_updates(100, 1500)

    def _immediate_update(self) -> None:
        """立即更新狀態"""
        self.refresh_servers()
        self.update_selection()

    def _delayed_update(self) -> None:
        """延遲更新，確保狀態正確"""
        self.update_selection()
        self.refresh_servers()

    def monitor_server(self, *, bring_to_front: bool = True) -> None:
        """
        監控伺服器

        Args:
            bring_to_front: 是否將監控視窗帶到前面。
        """
        if not self.selected_server:
            return

        if not hasattr(self, "_monitor_windows"):
            self._monitor_windows: dict[str, ServerMonitorWindow] = {}

        # 關閉或移除無效的視窗參照
        if self.selected_server in self._monitor_windows:
            old_win = self._monitor_windows[self.selected_server]
            if old_win and hasattr(old_win, "window") and old_win.window and old_win.window.is_alive():
                self._show_existing_monitor_window(old_win.window, bring_to_front=bring_to_front)
                return

        monitor_window = ServerMonitorWindow(self.top_level_widget(), self.server_startup, self.selected_server)
        self._monitor_windows[self.selected_server] = monitor_window
        monitor_window.show()

    def configure_server(self) -> None:
        """設定伺服器"""
        if not self.selected_server:
            return
        config = self.server_crud.servers[self.selected_server]
        dialog = ServerPropertiesDialog(self.top_level_widget(), config, self.server_crud)
        if dialog.result:
            self.server_crud.servers[self.selected_server] = dialog.result
            self.server_crud.write_servers_config()
            self.refresh_servers()
            UIUtils.show_info("成功", "伺服器設定已更新", self.top_level_widget())

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
            UIUtils.show_error("錯誤", f"無法開啟資料夾: {e}", self.top_level_widget())

    def delete_server(self) -> None:
        """刪除伺服器"""
        if not self.selected_server:
            return
        config = self.server_crud.servers[self.selected_server]
        has_backup = False
        backup_path = None
        if hasattr(config, "backup_path") and config.backup_path and Path(config.backup_path).exists():
            backup_path = config.backup_path
            has_backup = True
        result = UIUtils.ask_yes_no_cancel(
            "確認刪除",
            f"確定要刪除伺服器 '{self.selected_server}' 嗎？\n\n" + "⚠️ 這將永久刪除伺服器檔案，無法復原！",
            self.top_level_widget(),
            show_cancel=False,
        )
        if not result:
            return
        delete_backup = False
        if has_backup:
            backup_result = UIUtils.ask_yes_no_cancel(
                "刪除備份",
                f"偵測到伺服器 '{self.selected_server}' 有備份檔案：\n{backup_path}\n\n是否要一起刪除備份？\n\n• 點擊「是」：刪除伺服器和備份\n• 點擊「否」：只刪除伺服器，保留備份\n• 點擊「取消」：取消整個刪除操作",
                self.top_level_widget(),
            )
            if backup_result is None:
                return
            delete_backup = backup_result
        delete_result = self.server_crud.delete_server_result(self.selected_server)
        if delete_result.success:
            if delete_backup and backup_path:
                try:
                    PathUtils.delete_path(backup_path)
                    UIUtils.show_info("成功", f"伺服器 {self.selected_server} 和其備份已刪除", self.top_level_widget())
                except Exception as e:
                    logger.bind(component="").error(f"刪除備份失敗: {e}\n{traceback.format_exc()}", "ManageServerFrame")
                    UIUtils.show_warning(
                        "部分成功",
                        f"伺服器 {self.selected_server} 已刪除，但備份刪除失敗：\n{e}\n\n備份位置：{backup_path}",
                        self.top_level_widget(),
                    )
            elif has_backup:
                UIUtils.show_info(
                    "成功",
                    f"伺服器 {self.selected_server} 已刪除\n\n備份已保留於：{backup_path}",
                    self.top_level_widget(),
                )
            else:
                UIUtils.show_info("成功", f"伺服器 {self.selected_server} 已刪除", self.top_level_widget())
            self.refresh_servers()
        else:
            UIUtils.show_error(
                delete_result.title or "錯誤",
                delete_result.message or f"刪除伺服器 {self.selected_server} 失敗",
                self.top_level_widget(),
            )

    def backup_server(self) -> None:
        """備份伺服器檔案"""
        if not self.selected_server:
            return
        UIUtils.show_info("備份開始", "備份進行中，請稍候...", self.top_level_widget())
        success = self.server_backup.backup_server(self.selected_server)
        if success:
            UIUtils.show_info("備份成功", "備份完成！", self.top_level_widget())
            self.refresh_servers()
        else:
            UIUtils.show_error("備份失敗", "備份失敗，請查看日誌以獲取詳細資訊。", self.top_level_widget())

    def show_restore_dialog(self) -> None:
        if not self.selected_server:
            return
        dialog = RestoreBackupDialog(
            self.top_level_widget(), self.selected_server, self.server_backup, self.server_crud
        )
        dialog.setup_ui()
        dialog.show_modal()
