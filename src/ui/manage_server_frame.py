"""
管理伺服器頁面
負責管理現有 Minecraft 伺服器的使用者介面
"""

import contextlib
import queue
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core import ServerBackup, ServerDetectionUtils, ServerOperations, ServerRepository, ServerStartup
from ..models import ServerConfig
from ..utils import (
    Colors,
    FontManager,
    FontSize,
    MemoryUtils,
    PathUtils,
    QtCore,
    QtGui,
    Sizes,
    Spacing,
    TaskUtils,
    TreeItemRecycler,
    TreeUtils,
    UIUtils,
    get_logger,
    get_settings_manager,
    is_qobject_alive,
)
from ..utils.ui_support import qt_widgets as qt
from . import (
    ManageServerService,
    ServerListViewModel,
    ServerMonitorWindow,
    ServerPropertiesDialog,
    ServerRefreshPayload,
)

logger = get_logger().bind(component="ManageServerFrame")


@dataclass(frozen=True)
class ServerRefreshContext:
    """開始新一輪 UI refresh 時使用的上下文。"""

    refresh_token: int
    previous_selection: str | None


@dataclass(frozen=True)
class ServerRefreshExecutionPlan:
    """refresh callback 決策結果：是否套用與對應輪次上下文。"""

    should_apply: bool
    refresh_context: ServerRefreshContext | None = None


@dataclass(frozen=True)
class ServerTreeDiffPreparation:
    """套用 Treeview diff 前的既有列更新結果。"""

    rows_snapshot: dict[str, tuple[Any, ...]]
    pending_insert: list[tuple[str, tuple[Any, ...]]]


class ManageServerFrame(qt.Frame):
    """管理伺服器頁面"""

    def __init__(
        self,
        parent,
        repository: ServerRepository,
        server_startup: ServerStartup,
        server_backup: ServerBackup,
        callback: Callable,
        on_navigate_callback: Callable | None = None,
        set_servers_root=None,
    ):
        super().__init__(parent)
        self.repository = repository
        self.server_startup = server_startup
        self.server_backup = server_backup
        self.callback = callback
        self.on_navigate_callback = on_navigate_callback
        self.set_servers_root = set_servers_root
        self.selected_server: str | None = None
        self._jar_search_cache: dict[str, Any] = {}
        self._jar_cache_timeout = 60
        self._widgets_created = False
        self.server_tree: qt.Treeview | None = None
        self.action_buttons: dict[str, Any] = {}
        self._server_refresh_job: str | None = None
        self._server_refresh_token = 0
        self._server_tree_render_locked = False
        self._server_item_by_name: dict[str, str] = {}
        self._server_rows_snapshot: dict[str, tuple[Any, ...]] = {}
        self._server_insert_batch_base = 30
        self._server_insert_batch_max = 100
        self._server_insert_batch_divisor = 8
        self.ui_queue: queue.Queue = queue.Queue()
        self._first_show = True
        self.create_widgets()

        self.tree_item_recycler = TreeItemRecycler(self.server_tree)
        self.view_model = ServerListViewModel(self.repository, self.server_startup, self.get_backup_status)
        self.view_model.add_callback(self._on_server_list_updated)

        TaskUtils.start_ui_queue_pump(self, self.ui_queue)
        self._post_action_immediate_job = None
        self._post_action_delayed_job = None
        self._delayed_refresh_job = None
        self.view_model.set_auto_refresh_enabled(True)
        # 初次載入時自動偵測現有伺服器（延遲執行，等待 UI 完全初始化）
        UIUtils.schedule_debounce(
            self, "_initial_detect_job", 500, lambda: self.detect_servers(show_message=False), owner=self
        )

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        """
        首次顯示時強制更新幾何佈局

        Args:
            event: 顯示事件。
        """
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            self.schedule(50, self._on_first_show)

    def _on_first_show(self) -> None:
        """首次顯示後強制重新整理佈局與伺服器列表。"""
        self.updateGeometry()
        layout = self.layout()
        if layout is not None:
            layout.update()
            layout.activate()
        tree = self.server_tree
        tree_size_str = f"{tree.width()}x{tree.height()}" if tree else "None"
        logger.info(
            f"ManageServerFrame 首次顯示: size={self.width()}x{self.height()}, server_tree size={tree_size_str}",
            "ManageServerFrame",
        )

    def set_auto_refresh_enabled(self, enabled: bool, *, refresh_now: bool = False) -> None:
        """
        啟用或停用此管理頁面的背景自動重新整理。
        """
        self.view_model.set_auto_refresh_enabled(enabled, refresh_now=refresh_now)

    def refresh_servers(self, reload_config: bool = True) -> None:
        """重新整理伺服器列表。

        Args:
            reload_config: 是否重新載入伺服器設定檔，預設為 True。
        """
        self.view_model.refresh_servers(reload_config=reload_config)

    def _on_server_list_updated(self, payload: ServerRefreshPayload) -> None:
        """接收 ViewModel 的狀態更新，推入 UI Queue 確保於主執行緒執行。"""
        self.ui_queue.put(lambda: self._refresh_servers_callback(payload))

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
            text="管理伺服器",
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
        )
        title_label.attach(pady=(0, Spacing.XL))
        self.create_controls(main_container)
        self.create_server_list(main_container)
        self.create_actions(main_container)

    def apply_theme_styles(self) -> None:
        """重新套用目前主題到管理伺服器頁面。"""
        try:
            self.configure(fg_color="transparent")
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
        self.detect_path_var = qt.TextState(value=str(self.repository.servers_root))
        self.detect_path_entry = qt.Entry(
            path_frame, textvariable=self.detect_path_var, font=FontManager.get_font(size=FontSize.SMALL)
        )
        self.detect_path_entry.setText(str(self.repository.servers_root))
        self.detect_path_entry.attach(side="left", fill="x", expand=True, padx=(Spacing.SMALL_PLUS, 0))
        browse_button = UIUtils.create_styled_button(
            path_frame, text="瀏覽", command=self.browse_path, button_type="secondary"
        )
        browse_button.configure(width=Sizes.BUTTON_WIDTH_SMALL)
        browse_button.attach(side="left", padx=(Spacing.TINY, 0))

        # 建立右側按鈕容器，確保所有操作按鈕靠右對齊。
        button_frame = qt.Frame(control_frame, fg_color="transparent")
        button_frame.attach(pady=(0, Spacing.LARGE_MINUS))
        # 偵測現有伺服器按鈕
        detect_button = UIUtils.create_styled_button(
            button_frame,
            text="🔍 偵測現有伺服器",
            command=lambda: self.detect_servers(show_message=True),
            button_type="primary",
            width=Sizes.DETECT_BUTTON_WIDTH,
            height=Sizes.BUTTON_HEIGHT,
        )
        detect_button.attach(side="right", padx=Spacing.TINY)
        # 手動新增按鈕
        add_button = UIUtils.create_styled_button(
            button_frame, text="➕ 手動新增", command=self.add_server, button_type="secondary"
        )
        add_button.configure(width=Sizes.BUTTON_WIDTH_TOOLBAR)
        add_button.attach(side="right", padx=Spacing.TINY)
        # 重新整理按鈕
        refresh_button = UIUtils.create_styled_button(
            button_frame, text="🔄 重新整理", command=self.refresh_servers, button_type="secondary"
        )
        refresh_button.configure(width=Sizes.BUTTON_WIDTH_TOOLBAR)
        refresh_button.attach(side="right", padx=Spacing.TINY)

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
        self.server_tree.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.server_tree.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.server_tree.attach_matrix(row=0, column=0, sticky="nsew")
        list_frame.set_grid_row_stretch(0, weight=1)
        list_frame.set_grid_column_stretch(0, weight=1)
        logger.info(
            f"create_server_list 完成: server_tree 已建立, "
            f"columns={columns}, "
            f"list_frame layout={type(list_frame.layout()).__name__ if list_frame.layout() else 'None'}, "
            f"server_tree visible={self.server_tree.isVisible()}, "
            f"server_tree size={self.server_tree.width()}x{self.server_tree.height()}, "
            f"list_frame size={list_frame.width()}x{list_frame.height()}",
            "ManageServerFrame",
        )

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

        try:
            item_id = self.server_tree.identify_row(event.y, x=getattr(event, "x", None))
        except TypeError:
            item_id = self.server_tree.identify_row(event.y)
        if item_id:
            self.server_tree.selection_set(item_id)
            # 強制觸發 selection_changed 以更新狀態
            self.on_server_select(None)

        selection = self.server_tree.selection()
        if not selection:
            return
        menu = qt.PopupMenu(self, _tearoff=0, font=FontManager.get_font("Microsoft JhengHei", FontSize.NORMAL))
        menu.add_command(label="🔄 重新檢測伺服器", command=self.recheck_selected_server)
        menu.addSeparator()
        menu.add_command(label="📁 重新設定備份路徑", command=self.reset_backup_path)
        menu.add_command(label="📂 開啟備份資料夾", command=self.open_backup_folder)
        menu.popup_at(event.x_root, event.y_root)

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
        config = self.repository.servers.get(server_name)
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
        self.repository.write_servers_config()
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
            self.repository.write_servers_config()
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
        config = self.repository.servers.get(server_name)
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

    def get_backup_status(self, server_name: str) -> str:
        """
        獲取伺服器的備份狀態文字。

        Args:
            server_name: 伺服器名稱。

        Returns:
            備份狀態字串。
        """
        if not server_name or server_name not in self.repository.servers:
            return "❓ 無法檢查"
        config = self.repository.servers[server_name]
        if not hasattr(config, "backup_path") or not config.backup_path:
            return "⚠️ 未設定"
        if not Path(config.backup_path).exists():
            return "⚠️ 路徑失效"
        try:
            backup_world_path = str(Path(config.backup_path) / "world")
            if Path(backup_world_path).exists():
                backup_time = Path(backup_world_path).stat().st_mtime
                backup_datetime = datetime.fromtimestamp(backup_time)
                now = datetime.now()
                time_diff = now - backup_datetime
                if time_diff.total_seconds() < 0:
                    return "✅ 剛剛"
                if time_diff.days > 0:
                    time_ago = "1天前" if time_diff.days == 1 else f"{time_diff.days}天前"
                    return f"✅ {time_ago}"
                if time_diff.seconds > 3600:
                    hours = time_diff.seconds // 3600
                    return f"✅ {hours}小時前"
                minutes = time_diff.seconds // 60
                time_ago = f"{minutes}分鐘前" if minutes > 0 else "剛剛"
                return f"✅ {time_ago}"
            return "📁 已設定路徑"
        except Exception as e:
            logger.error(f"檢查備份狀態失敗: {e}\n{traceback.format_exc()}")
            return "❓ 檢查失敗"

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
        # 建立右側按鈕容器，確保所有操作按鈕靠右對齊。
        button_frame = qt.Frame(action_frame, fg_color="transparent")
        button_frame.attach(side="right", padx=Spacing.SMALL, pady=(0, Spacing.SMALL_PLUS))
        buttons = [
            ("🚀", "啟動", self.start_server, "start_stop"),
            ("📊", "監控", self.monitor_server, "monitor"),
            ("⚙️", "設定", self.configure_server, "configure"),
            ("📂", "開啟資料夾", self.open_server_folder, "open_folder"),
            ("💾", "備份地圖檔", self.backup_server, "backup"),
            ("🗑️", "刪除", self.delete_server, "delete"),
        ]
        self.action_buttons = {}
        for emoji, text, command, fixed_key in buttons:
            btn_text = f"{emoji} {text}"
            btn = UIUtils.create_styled_button(
                button_frame, text=btn_text, command=command, button_type="secondary", state="disabled"
            )
            btn.configure(width=Sizes.BUTTON_WIDTH_TOOLBAR)
            btn.attach(side="right", padx=Spacing.XS)
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
            self.repository.servers_root = Path(servers_root)
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

    def _detect_servers_task(self, path: str) -> int:
        return ManageServerService.detect_servers_in_path(path, self.repository, self.server_startup.crud)

    def _detect_servers_callback(self, count, show_message):
        logger.debug(
            f"_detect_servers_callback: count={count}, servers={list(self.repository.servers.keys())}",
            "ManageServerFrame",
        )
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

    @staticmethod
    def _make_server_data_signature(server_data: list[list[Any]]) -> tuple[tuple[str, tuple[Any, ...]], ...]:
        """建立可比較簽章，避免每次都重建整個列表。"""
        signature: list[tuple[str, tuple[Any, ...]]] = []
        for row in server_data:
            if not row:
                continue
            name = str(row[0])
            signature.append((name, tuple(row)))
        return tuple(signature)

    @classmethod
    def _build_server_tree_payload(cls, server_data: list[list[Any]]) -> tuple[list[str], dict[str, tuple[Any, ...]]]:
        """將原始 server_data 轉成 Treeview 套用所需的順序與列資料。"""
        server_order: list[str] = []
        server_rows: dict[str, tuple[Any, ...]] = {}
        for row in server_data:
            if not row:
                continue
            name = str(row[0])
            server_order.append(name)
            server_rows[name] = tuple(row)
        return (server_order, server_rows)

    @classmethod
    def _build_server_refresh_payload(cls, server_data: list[list[Any]]) -> ServerRefreshPayload:
        """建立刷新流程使用的簽章、順序與列資料。"""
        signature = cls._make_server_data_signature(server_data)
        server_order, server_rows = cls._build_server_tree_payload(server_data)
        return ServerRefreshPayload(signature=signature, server_order=server_order, server_rows=server_rows)

    @staticmethod
    def _compute_server_payload_hash(payload: ServerRefreshPayload) -> int:
        """計算 payload hash，供 refresh callback 判斷是否需要套用。"""
        try:
            return hash(payload.signature)
        except Exception:
            return hash(time.time())

    def _should_apply_server_refresh(self, payload: ServerRefreshPayload) -> bool:
        """判斷 payload 是否與上次不同，並在變更時更新快取 hash。"""
        current_data_hash = self._compute_server_payload_hash(payload)
        if getattr(self, "_last_server_data_hash", None) == current_data_hash:
            return False
        self._last_server_data_hash = current_data_hash
        return True

    def _begin_server_refresh_cycle(self) -> ServerRefreshContext:
        """建立新一輪 refresh 狀態，並使舊輪次失效。"""
        self._cancel_server_refresh_job()
        self._server_refresh_token += 1
        return ServerRefreshContext(refresh_token=self._server_refresh_token, previous_selection=self.selected_server)

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
        if self.server_tree and is_qobject_alive(self.server_tree):
            TreeUtils.refresh_treeview_alternating_rows(self.server_tree)
            children = self.server_tree.get_children()
            logger.info(
                f"_finalize_server_refresh: tree children={children}, "
                f"tree visible={self.server_tree.isVisible()}, "
                f"tree size={self.server_tree.width()}x{self.server_tree.height()}",
                "ManageServerFrame",
            )
        self._restore_server_selection(previous_selection)
        self.update_selection()
        self._set_server_tree_render_lock(False)

    def _remove_stale_server_items(self, server_rows: dict[str, tuple[Any, ...]]) -> None:
        """移除本輪資料中已不存在的舊 Tree item 對應。"""
        for name, stale_item_id in list(self._server_item_by_name.items()):
            if name in server_rows:
                continue
            self.tree_item_recycler.recycle_item(stale_item_id)
            self._server_item_by_name.pop(name, None)

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
                    self.tree_item_recycler.recycle_item(item_id)
                    self._server_item_by_name.pop(name, None)
            pending_insert.append((name, values))
        return ServerTreeDiffPreparation(rows_snapshot=rows_snapshot, pending_insert=pending_insert)

    def _apply_server_tree_diff(
        self,
        *,
        server_order: list[str],
        server_rows: dict[str, tuple[Any, ...]],
        refresh_token: int,
        previous_selection: str | None,
    ) -> None:
        """
        以差異更新 Treeview，減少 delete/insert 造成的卡頓。

        `refresh_token` 是本輪重新整理的輪次編號。這個方法可能透過 `after` 分批插入資料，
        因此它的執行生命週期可能跨越多次重新整理請求；每個批次都要先檢查 token。
        以避免「慢的舊結果」晚到並覆寫「新的正確結果」。
        """
        tree = getattr(self, "server_tree", None)
        if not tree or not is_qobject_alive(tree):
            self._set_server_tree_render_lock(False)
            logger.debug(f"server_tree 不可用: tree={tree}", "ManageServerFrame")
            return
        logger.info(
            f"_apply_server_tree_diff: server_order={server_order}, pending_insert 計算中...",
            "ManageServerFrame",
        )
        self._remove_stale_server_items(server_rows)
        diff_preparation = self._prepare_server_tree_diff(tree=tree, server_order=server_order, server_rows=server_rows)
        rows_snapshot = diff_preparation.rows_snapshot
        pending_insert = diff_preparation.pending_insert
        logger.info(
            f"_apply_server_tree_diff: pending_insert 數量={len(pending_insert)}, "
            f"server_order 數量={len(server_order)}",
            "ManageServerFrame",
        )
        if not server_order:
            self._server_item_by_name.clear()
            self._finalize_server_refresh(
                refresh_token=refresh_token, previous_selection=previous_selection, rows_snapshot={}
            )
            return
        batch_size = self._get_server_insert_batch_size(len(pending_insert))

        def _update_recycled(item_id: str, entry: tuple) -> None:
            tree.item(item_id, values=entry[1])
            tree.reattach(item_id)

        def _finalize() -> None:
            self._finalize_server_refresh(
                refresh_token=refresh_token, previous_selection=previous_selection, rows_snapshot=rows_snapshot
            )

        insert_batch = TreeUtils.make_tree_insert_batch(
            tree=tree,
            pending_insert=pending_insert,
            batch_size=batch_size,
            is_refresh_token_valid=lambda: refresh_token == self._server_refresh_token,
            acquire_recycled=lambda _entry: self.tree_item_recycler.acquire_item(),
            update_recycled=_update_recycled,
            insert_new=lambda _idx, entry: tree.insert("", entry[1]),
            set_mapping=lambda key, item_id: self._server_item_by_name.__setitem__(key, item_id),
            mapping_get=lambda key: self._server_item_by_name.get(key),
            get_key=lambda entry: entry[0],
            set_row_snapshot=lambda key, values: rows_snapshot.__setitem__(key, values),
            get_order=lambda: server_order,
            _get_rows=lambda key: server_rows.get(key),
            finalize_cb=_finalize,
            set_refresh_job=lambda v: setattr(self, "_server_refresh_job", v),
            move_item=lambda item_id, idx: tree.move_item(item_id, idx),
            logger_name="ManageServerFrame",
        )
        if pending_insert:
            insert_batch(0, None)
            return
        try:
            for order_index, name in enumerate(server_order):
                item_id = self._server_item_by_name.get(name)
                if item_id:
                    tree.move_item(item_id, order_index)
                    rows_snapshot[name] = server_rows[name]
        except Exception as e:
            logger.debug(f"重排伺服器列表失敗: {e}", "ManageServerFrame")
        self._finalize_server_refresh(
            refresh_token=refresh_token, previous_selection=previous_selection, rows_snapshot=rows_snapshot
        )

    def _refresh_servers_callback(self, payload: ServerRefreshPayload):
        """UI 更新回調"""
        logger.debug(
            f"_refresh_servers_callback: server_order={payload.server_order}, tree={self.server_tree}",
            "ManageServerFrame",
        )
        if self.server_tree is None:
            logger.debug("_refresh_servers_callback: server_tree is None, 跳過", "ManageServerFrame")
            return
        execution_plan = self._build_server_refresh_execution_plan(payload)
        if not execution_plan.should_apply or execution_plan.refresh_context is None:
            logger.debug(
                f"_refresh_servers_callback: should_apply={execution_plan.should_apply}，跳過", "ManageServerFrame"
            )
            self.update_selection()
            return
        self._apply_server_refresh_payload(payload, execution_plan.refresh_context)

    def _build_server_refresh_execution_plan(self, payload: ServerRefreshPayload) -> ServerRefreshExecutionPlan:
        """決定本次 refresh callback 是否需要進入 UI 套用階段。"""
        if not self._should_apply_server_refresh(payload):
            return ServerRefreshExecutionPlan(should_apply=False)
        refresh_context = self._begin_server_refresh_cycle()
        return ServerRefreshExecutionPlan(should_apply=True, refresh_context=refresh_context)

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

    def on_server_select(self, _event=None) -> None:
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

    def select_server(self, server_name: str) -> None:
        """依名稱選取伺服器列。

        Args:
            server_name: 要選取的伺服器名稱。
        """
        if not self.server_tree:
            return
        item_id = self._server_item_by_name.get(server_name)
        if item_id:
            try:
                self.server_tree.selection_set(item_id)
                self.server_tree.see(item_id)
                self.selected_server = server_name
                self.update_selection()
            except Exception as e:
                logger.debug(f"select_server 失敗 name={server_name}: {e}", "ManageServerFrame")

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
        if has_selection and self.selected_server in self.repository.servers:
            config = self.repository.servers[self.selected_server]
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
            if old_win and hasattr(old_win, "window") and old_win.window and is_qobject_alive(old_win.window):
                self._show_existing_monitor_window(old_win.window, bring_to_front=bring_to_front)
                return

        monitor_window = ServerMonitorWindow(self.top_level_widget(), self.server_startup, self.selected_server)
        self._monitor_windows[self.selected_server] = monitor_window
        monitor_window.show()

    def configure_server(self) -> None:
        """設定伺服器"""
        if not self.selected_server:
            return
        config = self.repository.servers[self.selected_server]
        dialog = ServerPropertiesDialog(self.top_level_widget(), config, self.repository)
        if dialog.result:
            self.repository.servers[self.selected_server] = dialog.result
            self.repository.write_servers_config()
            self.refresh_servers()
            UIUtils.show_info("成功", "伺服器設定已更新", self.top_level_widget())

    def open_server_folder(self) -> None:
        """開啟伺服器資料夾"""
        if not self.selected_server:
            return
        config = self.repository.servers[self.selected_server]
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
        config = self.repository.servers[self.selected_server]
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
        delete_result = self.server_startup.crud.delete_server_result(self.selected_server)
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
        """備份伺服器世界檔案"""
        if not self.selected_server:
            return
        server_name = self.selected_server
        config = self.repository.servers[server_name]
        server_path = config.path
        world_path = str(Path(server_path) / "world")
        if not Path(world_path).exists():
            UIUtils.show_error("錯誤", f"找不到世界資料夾: {world_path}", self.top_level_widget())
            return
        backup_location = None
        is_new_backup_path = False
        if hasattr(config, "backup_path") and config.backup_path:
            try:
                if not Path(config.backup_path).exists():
                    Path(config.backup_path).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.warning(f"無法建立備份路徑: {e}")
            backup_location = config.backup_path
        if not backup_location:
            was_auto_refresh_enabled = bool(getattr(self, "_auto_refresh_enabled", True))
            if was_auto_refresh_enabled:
                self.set_auto_refresh_enabled(False)
            try:
                parent_backup_location = qt.get_existing_directory(
                    title="選擇備份儲存位置", initialdir=str(Path.home())
                )
            finally:
                if was_auto_refresh_enabled:
                    self.set_auto_refresh_enabled(True)
            if not parent_backup_location:
                return
            config = self.repository.servers.get(server_name)
            if not config:
                UIUtils.show_error("錯誤", f"找不到伺服器設定: {server_name}", self.top_level_widget())
                return
            backup_folder_name = f"{server_name}_backup"
            backup_location = str(Path(parent_backup_location) / backup_folder_name)
            try:
                Path(backup_location).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.bind(component="").error(
                    f"無法建立備份資料夾: {e}\n{traceback.format_exc()}", "ManageServerFrame"
                )
                UIUtils.show_error("錯誤", f"無法建立備份資料夾: {e}", self.top_level_widget())
                return
            config.backup_path = backup_location
            if not self.repository.write_servers_config():
                UIUtils.show_error("錯誤", "寫入備份路徑失敗，請稍後再試。", self.top_level_widget())
                return
            is_new_backup_path = True
            self.refresh_servers(reload_config=False)
        backup_full_path = backup_location
        backup_world_path = str(Path(backup_full_path) / "world")
        world_path = str(Path(world_path))
        backup_full_path = str(Path(backup_full_path))
        backup_world_path = str(Path(backup_world_path))
        bat_content = f'@echo off\n@chcp 65001 > nul\n\nREM 備份 {server_name} 伺服器世界檔案\nREM Backup {server_name} server world files\n\nREM 刪除舊的備份世界資料夾（如果存在）\nREM Remove old backup world folder (if exists)\nIF EXIST "{backup_world_path}" RD /Q /S "{backup_world_path}"\n\nREM 建立世界備份資料夾\nREM Create world backup folder\nMD "{backup_world_path}"\n\nREM 複製世界檔案到備份位置\nREM Copy world files to backup location\nxcopy "{world_path}\\" "{backup_world_path}" /E /Y /K /R /H\n\necho 備份完成！\necho Backup completed!\necho 伺服器: {server_name}\necho Server: {server_name}\necho 來源: {world_path}\necho Source: {world_path}\necho 目標: {backup_world_path}\necho Target: {backup_world_path}\necho.\npause'
        bat_file_path = str(Path(backup_full_path) / f"backup_{server_name}.bat")
        try:
            PathUtils.write_text_file(Path(bat_file_path), bat_content)
            if is_new_backup_path:
                UIUtils.show_info(
                    "備份檔案已建立",
                    f"備份批次檔已建立：\n{bat_file_path}\n\n"
                    f"✅ 備份資料夾已建立：{backup_full_path}\n"
                    f"💡 如需更改備份路徑，請右鍵點擊伺服器選擇「重新設定備份路徑」。\n\n"
                    "系統即將開始執行備份...",
                    self.top_level_widget(),
                )
            try:
                program = bat_file_path
                arguments: list[str] = []
                if Path(bat_file_path).suffix.lower() in {".bat", ".cmd"}:
                    program = "cmd.exe"
                    arguments = ["/d", "/s", "/c", bat_file_path]
                success, _pid = QtCore.QProcess.startDetached(program, arguments, backup_full_path)
                if not success:
                    raise RuntimeError("QProcess 無法啟動備份批次檔")
                UIUtils.show_info(
                    "備份開始", f"備份已開始執行，請稍候...\n備份位置：{backup_full_path}", self.top_level_widget()
                )
                self.refresh_servers()
                self._schedule_refresh(5000)
            except Exception as e:
                logger.bind(component="").error(
                    f"執行備份批次檔失敗: {e}\n{traceback.format_exc()}", "ManageServerFrame"
                )
                UIUtils.show_error("執行錯誤", f"執行備份批次檔失敗：{e}", self.top_level_widget())
        except Exception as e:
            logger.bind(component="").error(f"建立備份批次檔失敗: {e}\n{traceback.format_exc()}", "ManageServerFrame")
            UIUtils.show_error("錯誤", f"建立備份批次檔失敗：{e}", self.top_level_widget())
