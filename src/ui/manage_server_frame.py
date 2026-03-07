#!/usr/bin/env python3
"""管理伺服器頁面
負責管理現有 Minecraft 伺服器的使用者介面
"""

import contextlib
import queue
import time
import tkinter as tk
import tkinter.font as tkfont
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

import customtkinter as ctk

from ..core import ServerConfig, ServerManager
from ..utils import (
    FontManager,
    FontSize,
    MemoryUtils,
    PathUtils,
    ServerDetectionUtils,
    ServerOperations,
    Sizes,
    SubprocessUtils,
    UIUtils,
    compute_adaptive_pool_limit,
    compute_exponential_moving_average,
    get_logger,
)
from . import ServerMonitorWindow, ServerPropertiesDialog

logger = get_logger().bind(component="ManageServerFrame")


class ManageServerFrame(ctk.CTkFrame):
    """管理伺服器頁面"""

    def __init__(
        self,
        parent,
        server_manager: ServerManager,
        callback: Callable,
        on_navigate_callback: Callable | None = None,
        set_servers_root=None,
    ):
        super().__init__(parent)

        self.server_manager = server_manager
        self.callback = callback
        self.on_navigate_callback = on_navigate_callback
        self.set_servers_root = set_servers_root
        self.selected_server: str | None = None

        # JAR 檔案搜尋快取
        self._jar_search_cache: dict[str, Any] = {}
        self._jar_cache_timeout = 60

        # 元件初始化旗標與關鍵屬性
        self._widgets_created = False
        self.server_tree: ttk.Treeview | None = None
        self.action_buttons: dict[str, Any] = {}
        self._server_refresh_job: str | None = None
        # Treeview 差異重新整理的競態保護：啟動新輪次先取消舊 `_server_refresh_job`，
        # 並以 `_server_refresh_token` 驗證分批插入/收尾，只允許最新輪次提交結果。
        # `_server_item_by_name` 與 `_server_rows_snapshot` 用於就地更新、重排與變更判斷。
        self._server_refresh_token = 0
        self._server_tree_render_locked = False
        self._server_item_by_name: dict[str, str] = {}
        self._server_rows_snapshot: dict[str, tuple[Any, ...]] = {}
        self._server_recycled_item_ids: list[str] = []
        self._server_recycle_pool_max = 300
        # 重用池觀測指標（debug）：用於調整 pool 上限與命中率。
        self._server_recycle_hits = 0
        self._server_recycle_misses = 0
        self._server_recycle_drops = 0
        self._server_recycle_log_every = 200
        self._server_recycle_pool_min = 150
        self._server_recycle_pool_cap = 1200
        self._server_recycle_tune_step = 50
        self._server_recycle_hit_rate_ema: float | None = None
        self._server_recycle_ema_alpha = 0.35
        # 可調整的批次插入參數：可依實際 UI 反應微調。
        self._server_insert_batch_base = 30
        self._server_insert_batch_max = 100
        # 動態批次分母：使用待插入筆數的 1/divisor 作為動態批次估算。
        self._server_insert_batch_divisor = 8

        self.ui_queue: queue.Queue = queue.Queue()

        self.create_widgets()
        UIUtils.start_ui_queue_pump(self, self.ui_queue)

        self._post_action_immediate_job = None
        self._post_action_delayed_job = None
        self._delayed_refresh_job = None
        self._auto_refresh_enabled = True
        self._auto_refresh_interval_ms = 10000
        self._auto_refresh_job = None
        self._auto_refresh_loop()

    def _auto_refresh_loop(self) -> None:
        """自動重新整理循環"""
        if self.winfo_exists():
            if getattr(self, "_auto_refresh_enabled", True):
                self.refresh_servers()
            self._auto_refresh_job = self.after(self._auto_refresh_interval_ms, self._auto_refresh_loop)

    def set_auto_refresh_enabled(self, enabled: bool, *, refresh_now: bool = False) -> None:
        """啟用或停用此管理頁面的背景自動重新整理。

        此方法主要供外層 UI（例如分頁/頁籤容器）在切換顯示狀態時呼叫，用途如下：
        - 本頁不在前景時停用自動重新整理，降低 CPU 與 I/O 負擔。
        - 避免使用者瀏覽其他頁籤時，背景 TreeView 持續更新造成 UI 抖動。
        - 回到本頁時再啟用自動重新整理，必要時可立即重新整理一次。

        Args:
            enabled: True 啟用自動重新整理（允許 `_auto_refresh_loop` 週期性呼叫
                :meth:`refresh_servers`）；False 停用背景自動重新整理。
            refresh_now: 當 `enabled=True` 時，若此值也為 True，會立刻呼叫
                :meth:`refresh_servers`，確保頁面重新顯示時狀態立即更新。

        範例（與 ttk.Notebook 整合）::

            def on_tab_changed(event):
                notebook = event.widget
                current = notebook.select()

                # 假設 manage_frame 是 ManageServerFrame 的實例
                is_manage_tab = current == manage_tab_id

                # 進入管理頁時啟用背景自動重新整理，並立即重新整理一次
                manage_frame.set_auto_refresh_enabled(
                    is_manage_tab,
                    refresh_now=is_manage_tab,
                )
        """
        self._auto_refresh_enabled = bool(enabled)
        if refresh_now and self._auto_refresh_enabled:
            self.refresh_servers()

    def _schedule_post_action_updates(self, immediate_delay_ms: int, delayed_delay_ms: int) -> None:
        UIUtils.schedule_debounce(
            self,
            "_post_action_immediate_job",
            immediate_delay_ms,
            self._immediate_update,
        )
        UIUtils.schedule_debounce(
            self,
            "_post_action_delayed_job",
            delayed_delay_ms,
            self._delayed_update,
        )

    def _schedule_refresh(self, delay_ms: int) -> None:
        UIUtils.schedule_debounce(
            self,
            "_delayed_refresh_job",
            delay_ms,
            self.refresh_servers,
        )

    def create_widgets(self) -> None:
        """建立介面元件"""
        if getattr(self, "_widgets_created", False):
            return
        self._widgets_created = True

        # 主容器
        main_container = ctk.CTkFrame(self, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=20, pady=20)

        # 標題
        title_label = ctk.CTkLabel(
            main_container,
            text="⚙️ 管理伺服器",
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
        )
        title_label.pack(pady=(0, 20))

        # 上方控制區
        self.create_controls(main_container)

        # 伺服器列表
        self.create_server_list(main_container)

        # 下方操作區
        self.create_actions(main_container)

    def create_controls(self, parent) -> None:
        """建立控制區"""
        control_frame = ctk.CTkFrame(parent)
        control_frame.pack(fill="x", pady=(0, 20))

        # 標題
        control_title = ctk.CTkLabel(
            control_frame,
            text="偵測設定",
            font=FontManager.get_font(size=FontSize.MEDIUM, weight="bold"),
        )
        control_title.pack(anchor="w", pady=(15, 10), padx=(15, 0))

        # 偵測路徑
        path_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        path_frame.pack(fill="x", padx=15, pady=(0, 10))

        ctk.CTkLabel(path_frame, text="偵測路徑:", font=FontManager.get_font(size=FontSize.NORMAL)).pack(side="left")

        self.detect_path_var = tk.StringVar(value=str(self.server_manager.servers_root))
        self.detect_path_entry = ctk.CTkEntry(
            path_frame,
            textvariable=self.detect_path_var,
            font=FontManager.get_font(size=FontSize.SMALL),
        )
        self.detect_path_entry.pack(side="left", fill="x", expand=True, padx=(10, 0))

        browse_button = UIUtils.create_styled_button(
            path_frame,
            text="瀏覽",
            command=self.browse_path,
            button_type="small",
        )
        browse_button.pack(side="left", padx=(5, 0))

        # 按鈕區域
        button_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        button_frame.pack(pady=(0, 15))

        # 偵測按鈕
        detect_button = UIUtils.create_styled_button(
            button_frame,
            text="🔍 偵測現有伺服器",
            command=lambda: self.detect_servers(show_message=True),
            button_type="secondary",
        )
        detect_button.pack(side="left", padx=5)

        # 手動新增按鈕
        add_button = UIUtils.create_styled_button(
            button_frame,
            text="➕ 手動新增",
            command=self.add_server,
            button_type="secondary",
        )
        add_button.pack(side="left", padx=5)

        # 重新整理按鈕
        refresh_button = UIUtils.create_styled_button(
            button_frame,
            text="🔄 重新整理",
            command=lambda: self.refresh_servers(),
            button_type="secondary",
        )
        refresh_button.pack(side="left", padx=5)

    def create_server_list(self, parent) -> None:
        """建立伺服器列表"""
        list_frame = ttk.LabelFrame(parent, text="伺服器列表", padding=10)
        list_frame.pack(fill="both", expand=True, pady=(0, 20))

        style = ttk.Style()
        style.configure(
            "ServerList.TLabelframe.Label",
            font=FontManager.get_font("Microsoft JhengHei", FontSize.LARGE, "bold"),
        )
        list_frame.configure(style="ServerList.TLabelframe")

        # 建立 Treeview
        columns = ("名稱", "版本", "載入器", "狀態", "備份狀態", "路徑")
        self.server_tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")

        # 配置 Treeview 的字體大小
        style.configure("Treeview", font=FontManager.get_font("Microsoft JhengHei", FontSize.LARGE))
        style.configure(
            "Treeview.Heading",
            font=FontManager.get_font("Microsoft JhengHei", FontSize.HEADING_SMALL_PLUS, "bold"),
        )
        # 設定欄位
        self.server_tree.heading("名稱", text="名稱")
        self.server_tree.heading("版本", text="版本")
        self.server_tree.heading("載入器", text="載入器")
        self.server_tree.heading("狀態", text="狀態")
        self.server_tree.heading("備份狀態", text="備份狀態")
        self.server_tree.heading("路徑", text="路徑")

        self._apply_server_tree_columns_layout()

        # 綁定事件
        self.server_tree.bind("<<TreeviewSelect>>", self.on_server_select)
        self.server_tree.bind("<Double-1>", self.on_server_tree_double_click)
        self.server_tree.bind("<Button-3>", self.show_server_context_menu)

        # 加入滾動條
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.server_tree.yview)
        self.server_tree.configure(yscrollcommand=scrollbar.set)

        # 佈局
        self.server_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _server_tree_display_columns(self) -> tuple[str, ...]:
        return ("名稱", "版本", "載入器", "狀態", "備份狀態", "路徑")

    def _apply_server_tree_columns_layout(self) -> None:
        """套用伺服器 Tree 欄位配置（除路徑欄外皆固定寬，並依 DPI 縮放）。"""
        if not self.server_tree:
            return

        tree = self.server_tree
        tree.configure(displaycolumns=self._server_tree_display_columns())
        name_width = FontManager.get_dpi_scaled_size(Sizes.SERVER_TREE_COL_NAME)
        version_width = FontManager.get_dpi_scaled_size(Sizes.SERVER_TREE_COL_VERSION)
        loader_width = FontManager.get_dpi_scaled_size(Sizes.SERVER_TREE_COL_LOADER)
        status_width = FontManager.get_dpi_scaled_size(Sizes.SERVER_TREE_COL_STATUS)
        backup_width = FontManager.get_dpi_scaled_size(Sizes.SERVER_TREE_COL_BACKUP)
        path_width = FontManager.get_dpi_scaled_size(Sizes.SERVER_TREE_COL_PATH)
        path_min_width = max(FontManager.get_dpi_scaled_size(180), path_width // 2)

        tree.column("名稱", width=name_width, minwidth=name_width, stretch=False, anchor="w")
        tree.column("版本", width=version_width, minwidth=version_width, stretch=False, anchor="w")
        tree.column("載入器", width=loader_width, minwidth=loader_width, stretch=False, anchor="w")
        tree.column("狀態", width=status_width, minwidth=status_width, stretch=False, anchor="w")
        tree.column("備份狀態", width=backup_width, minwidth=backup_width, stretch=False, anchor="w")
        tree.column("路徑", width=path_width, minwidth=path_min_width, stretch=True, anchor="w")

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
        except (TypeError, ValueError):
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

        logical_x = int(x + (xview_start * total_width))
        threshold = FontManager.get_dpi_scaled_size(6)
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

        heading_font = tkfont.Font(font=FontManager.get_font("Microsoft JhengHei", FontSize.HEADING_SMALL_PLUS, "bold"))
        body_font = tkfont.Font(font=FontManager.get_font("Microsoft JhengHei", FontSize.LARGE))
        padding = FontManager.get_dpi_scaled_size(14)
        # auto-fit 時覆寫欄位最小寬，避免被初始固定欄位下限卡住。
        safety_min_width = FontManager.get_dpi_scaled_size(12)

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
        tree.column(
            column_id,
            width=computed_width,
            minwidth=safety_min_width,
            stretch=(column_id == "路徑"),
            anchor="w",
        )

    def show_server_context_menu(self, event) -> None:
        """顯示右鍵選單"""
        if not self.server_tree:
            return

        selection = self.server_tree.selection()
        if not selection:
            return
        menu = tk.Menu(self, tearoff=0, font=FontManager.get_font("Microsoft JhengHei", FontSize.LARGE))
        menu.add_command(label="🔄 重新檢測伺服器", command=self.recheck_selected_server)
        menu.add_separator()
        menu.add_command(label="📁 重新設定備份路徑", command=self.reset_backup_path)
        menu.add_command(label="📂 開啟備份資料夾", command=self.open_backup_folder)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _get_selected_server_config(self, show_warning: bool = True) -> ServerConfig | None:
        """獲取當前選中的伺服器配置"""
        if not self.server_tree:
            return None

        selection = self.server_tree.selection()
        if not selection:
            if show_warning:
                UIUtils.show_warning("提示", "請先選擇伺服器", self.winfo_toplevel())
            return None

        item = self.server_tree.item(selection[0])
        values = item["values"]
        if not values or len(values) < 1:
            if show_warning:
                UIUtils.show_warning("提示", "無法取得伺服器名稱", self.winfo_toplevel())
            return None

        server_name = values[0]
        config = self.server_manager.servers.get(server_name)
        if not config:
            if show_warning:
                UIUtils.show_error("錯誤", f"找不到伺服器設定: {server_name}", self.winfo_toplevel())
            return None

        return config

    def recheck_selected_server(self) -> None:
        """重新檢測選中伺服器"""
        config = self._get_selected_server_config(show_warning=False)
        if not config:
            return

        server_name = config.name
        # 呼叫偵測
        ServerDetectionUtils.detect_server_type(Path(config.path), config)
        self.server_manager.write_servers_config()
        self.refresh_servers()
        UIUtils.show_info("完成", f"已重新檢測伺服器：{server_name}", self.winfo_toplevel())

    def reset_backup_path(self) -> None:
        """重新設定選中伺服器的備份路徑"""
        config = self._get_selected_server_config()
        if not config:
            return

        server_name = config.name
        # 詢問使用者選擇新的備份父路徑
        parent_backup_path = filedialog.askdirectory(
            title=f"重新設定 {server_name} 的備份路徑",
            initialdir=str(Path.home()),
        )

        if parent_backup_path:
            # 建立伺服器專用的備份資料夾
            backup_folder_name = f"{server_name}_backup"
            new_backup_path = str(Path(parent_backup_path) / backup_folder_name)

            # 建立備份資料夾（如果不存在）
            try:
                Path(new_backup_path).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.bind(component="").error(
                    f"無法建立備份資料夾: {e}\n{traceback.format_exc()}",
                    "ManageServerFrame",
                )
                UIUtils.show_error("錯誤", f"無法建立備份資料夾: {e}", self.winfo_toplevel())
                return

            # 更新配置
            config.backup_path = new_backup_path
            self.server_manager.write_servers_config()
            # 紀錄備份路徑寫入的詳細訊息
            logger.bind(component="BackupServer").info(
                f"伺服器 {server_name} 的備份路徑已更新為: {new_backup_path}",
                extra={
                    "server_name": server_name,
                    "backup_path": new_backup_path,
                    "operation": "write_servers_config",
                },
            )
            UIUtils.show_info(
                "成功",
                f"已將伺服器 {server_name} 的備份路徑設定為：\n{new_backup_path}",
                self.winfo_toplevel(),
            )
            # 重新整理清單以更新備份狀態顯示
            self.refresh_servers()
        else:
            UIUtils.show_info("取消", "未更改備份路徑設定", self.winfo_toplevel())

    def open_backup_folder(self) -> None:
        """開啟選中伺服器的備份資料夾"""
        if self.server_tree is None:
            return

        selection = self.server_tree.selection()
        if not selection:
            UIUtils.show_warning("提示", "請先選擇要開啟備份資料夾的伺服器", self.winfo_toplevel())
            return

        item = self.server_tree.item(selection[0])
        values = item["values"]
        if not values or len(values) < 1:
            UIUtils.show_warning("提示", "無法取得伺服器名稱", self.winfo_toplevel())
            return

        server_name = values[0]
        config = self.server_manager.servers.get(server_name)
        if not config:
            UIUtils.show_error("錯誤", f"找不到伺服器設定: {server_name}", self.winfo_toplevel())
            return

        # 檢查是否有設定備份路徑
        if not hasattr(config, "backup_path") or not config.backup_path:
            UIUtils.show_warning(
                "提示",
                f"伺服器 {server_name} 尚未設定備份路徑\n請先執行一次備份來設定備份路徑",
                self.winfo_toplevel(),
            )
            return

        # 檢查備份路徑是否存在
        if not Path(config.backup_path).exists():
            UIUtils.show_error(
                "錯誤",
                f"備份路徑不存在：\n{config.backup_path}\n\n請重新設定備份路徑",
                self.winfo_toplevel(),
            )
            return

        try:
            UIUtils.open_external(config.backup_path)
        except Exception as e:
            logger.bind(component="").error(
                f"無法開啟備份資料夾: {e}\n{traceback.format_exc()}",
                "ManageServerFrame",
            )
            UIUtils.show_error("錯誤", f"無法開啟備份資料夾: {e}", self.winfo_toplevel())

    def get_backup_status(self, server_name: str) -> str:
        """獲取伺服器的備份狀態文字"""
        if not server_name or server_name not in self.server_manager.servers:
            return "❓ 無法檢查"

        config = self.server_manager.servers[server_name]

        # 檢查是否有設定備份路徑
        if not hasattr(config, "backup_path") or not config.backup_path:
            return "⚠️ 未設定"

        # 檢查備份路徑是否存在
        if not Path(config.backup_path).exists():
            return "⚠️ 路徑失效"

        try:
            # 檢查備份資料夾中的world資料夾是否存在
            backup_world_path = str(Path(config.backup_path) / "world")

            if Path(backup_world_path).exists():
                # 取得備份world資料夾的修改時間
                backup_time = Path(backup_world_path).stat().st_mtime
                backup_datetime = datetime.fromtimestamp(backup_time)

                # 計算距離現在的時間
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
        """建立操作區"""
        action_frame = ctk.CTkFrame(parent)
        action_frame.pack(fill="x")

        # 操作標題
        action_title = ctk.CTkLabel(
            action_frame,
            text="操作",
            font=FontManager.get_font(size=FontSize.MEDIUM, weight="bold"),
        )
        action_title.pack(anchor="w", pady=(5, 0), padx=(15, 0))

        # 資訊顯示
        info_frame = ctk.CTkFrame(action_frame, fg_color="transparent")
        info_frame.pack(fill="x", padx=15, pady=(5, 5))

        self.info_label = ctk.CTkLabel(
            info_frame,
            text="選擇一個伺服器以查看詳細資訊",
            font=FontManager.get_font(size=FontSize.MEDIUM),
        )
        self.info_label.pack(anchor="w")

        # 按鈕區域（獨立一行）
        button_frame = ctk.CTkFrame(action_frame, fg_color="transparent")
        button_frame.pack(fill="x", padx=15, pady=(0, 15))

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
            # 使用簡單的 emoji 文字按鈕
            btn_text = f"{emoji} {text}"
            btn = UIUtils.create_styled_button(
                button_frame,
                text=btn_text,
                command=command,
                button_type="secondary",
                state="disabled",
            )
            btn.pack(side="left", padx=(0, 5))
            # 使用固定 key 或動態 key
            key = fixed_key if fixed_key else f"{emoji} {text}"
            self.action_buttons[key] = btn

    def browse_path(self) -> None:
        """瀏覽路徑，並自動正規化、寫入設定、建立 servers 子資料夾、重新整理清單"""
        path = filedialog.askdirectory(title="選擇伺服器目錄")
        if path:
            # 強制正規化分隔符與絕對路徑
            abs_path = Path(path).resolve()
            norm_path = str(abs_path)
            base_dir = norm_path

            # 呼叫 main_window 傳入的 set_servers_root：寫入 user_settings.json（儲存 base dir）
            # 並回傳實際 servers_root (= <base>\servers)
            servers_root = None
            if self.set_servers_root:
                try:
                    servers_root = self.set_servers_root(base_dir)
                except Exception as e:
                    logger.bind(component="").error(
                        f"寫入伺服器路徑設定失敗: {e}\n{traceback.format_exc()}",
                        "ManageServerFrame",
                    )
                    UIUtils.show_error("錯誤", f"無法寫入設定: {e}", self.winfo_toplevel())
                    return

            if not servers_root:
                servers_root = str((Path(base_dir) / "servers").resolve())

            servers_root_path = Path(servers_root)
            if not servers_root_path.exists():
                try:
                    servers_root_path.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    logger.bind(component="").error(
                        f"無法建立 servers 資料夾: {e}\n{traceback.format_exc()}",
                        "ManageServerFrame",
                    )
                    UIUtils.show_error("錯誤", f"無法建立 servers 資料夾: {e}", self.winfo_toplevel())
                    return

            # 更新 entry 顯示（顯示實際 servers 子資料夾）
            self.detect_path_var.set(servers_root)

            # 同步 server_manager 的 root
            self.server_manager.servers_root = Path(servers_root)
            # 變更後自動重新整理伺服器清單
            self.refresh_servers()

    def detect_servers(self, show_message: bool = True) -> None:
        """偵測現有伺服器，無論新建或覆蓋都會呼叫 detect_server_type"""
        path = self.detect_path_var.get()
        if not path or not Path(path).exists():
            if show_message:
                UIUtils.show_error("錯誤", "請選擇有效的路徑", self.winfo_toplevel())
            return

        def task():
            try:
                count = self._detect_servers_task(path)
                self.ui_queue.put(lambda: self._detect_servers_callback(count, show_message))
            except Exception as error:
                logger.error(f"偵測失敗: {error}\n{traceback.format_exc()}")
                error_msg = str(error)
                self.ui_queue.put(lambda: UIUtils.show_error("錯誤", f"偵測失敗: {error_msg}", self.winfo_toplevel()))

        UIUtils.run_async(task)

    def _detect_servers_task(self, path):
        count = 0
        path_obj = Path(path)
        for item_path_obj in path_obj.iterdir():
            if item_path_obj.is_dir():
                item = item_path_obj.name
                item_path = str(item_path_obj)
                if ServerDetectionUtils.is_valid_server_folder(item_path_obj):
                    # 先建立 config 物件（無論新建或覆蓋都呼叫偵測）
                    if item in self.server_manager.servers:
                        config = self.server_manager.servers[item]
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
                    # 強制呼叫偵測
                    ServerDetectionUtils.detect_server_type(item_path_obj, config)
                    if item in self.server_manager.servers:
                        self.server_manager.write_servers_config()
                        count += 1
                    elif self.server_manager.create_server(config):
                        count += 1
        return count

    def _detect_servers_callback(self, count, show_message):
        if show_message:
            UIUtils.show_info("完成", f"成功偵測/更新 {count} 個伺服器", self.winfo_toplevel())
        self.refresh_servers()

    def add_server(self) -> None:
        """手動新增伺服器 - 跳轉到建立伺服器頁面"""
        if self.on_navigate_callback:
            self.on_navigate_callback()

    def _get_server_status_text(self, name: str, config: ServerConfig) -> str:
        """獲取伺服器狀態文字"""
        is_running = self.server_manager.is_server_running(name)
        if is_running:
            return "🟢 運行中"

        # 檢查伺服器檔案（使用快取避免重複 glob 操作）
        current_time = time.time()
        cache_key = config.path

        # 檢查快取是否有效
        if cache_key in self._jar_search_cache:
            cached_result, cache_time = self._jar_search_cache[cache_key]
            if current_time - cache_time < self._jar_cache_timeout:
                server_jar_exists = cached_result
            else:
                server_jar_exists = self._check_server_jar_exists(config.path, config.loader_type)
                self._jar_search_cache[cache_key] = (server_jar_exists, current_time)
        else:
            server_jar_exists = self._check_server_jar_exists(config.path, config.loader_type)
            self._jar_search_cache[cache_key] = (server_jar_exists, current_time)

        eula_exists = (Path(config.path) / "eula.txt").exists()
        eula_accepted = getattr(config, "eula_accepted", False)

        if server_jar_exists and eula_exists and eula_accepted:
            return "✅ 已就緒"
        if server_jar_exists and eula_exists and not eula_accepted:
            return "⚠️ 需要接受 EULA"
        if server_jar_exists:
            return "❌ 缺少 EULA"
        missing = ServerDetectionUtils.get_missing_server_files(Path(config.path))
        if missing:
            return f"❌ 未就緒 (缺少: {', '.join(missing)})"
        return "❌ 未就緒"

    def _check_server_jar_exists(self, server_path: str, loader_type: str = "vanilla") -> bool:
        """檢查伺服器 JAR 檔案是否存在（使用 ServerDetectionUtils）

        Args:
            server_path: 伺服器路徑
            loader_type: 載入器類型 (vanilla/forge/fabric)，用於正確判斷啟動檔案
        """
        try:
            server_path_obj = Path(server_path)
            # 使用實際的 loader_type 進行檢測
            result = ServerDetectionUtils.find_main_jar(server_path_obj, loader_type or "vanilla")

            # Forge 可能返回 @win_args.txt 或 @libraries/...，這類檔案存在即表示可啟動
            if result.startswith("@"):
                args_file_path = result[1:]  # 移除 @ 符號
                return (server_path_obj / args_file_path).exists()

            jar_path = server_path_obj / result
            return jar_path.exists()
        except Exception as e:
            logger.debug(f"檢查 JAR 檔案存在失敗: {e}")
            # 退回到簡單的檢查
            return (Path(server_path) / "server.jar").exists()

    def _cancel_server_refresh_job(self) -> None:
        """取消尚未完成的列表插入工作（共用排程 helper）。

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
                parent.pack_propagate(False)
                self._server_tree_render_locked = True
            except Exception as e:
                logger.debug(f"鎖定 server tree 佈局失敗: {e}", "ManageServerFrame")
            return

        if not getattr(self, "_server_tree_render_locked", False):
            logger.warning("收到解除 server tree 佈局鎖要求，但目前未鎖定。")
            return
        try:
            parent.pack_propagate(True)
        except Exception as e:
            logger.debug(f"解除 server tree 佈局鎖失敗: {e}", "ManageServerFrame")
        finally:
            self._server_tree_render_locked = False

    @staticmethod
    def _normalize_server_row(row: list[Any]) -> tuple[Any, ...]:
        """標準化 Treeview 列資料，便於比對差異。"""
        return tuple(row)

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
        if total <= 0 or (total % interval) != 0:
            return
        raw_hit_rate = (self._server_recycle_hits / total) * 100.0
        smoothed_hit_rate = compute_exponential_moving_average(
            previous=getattr(self, "_server_recycle_hit_rate_ema", None),
            current=raw_hit_rate,
            alpha=float(getattr(self, "_server_recycle_ema_alpha", 0.35)),
        )
        self._server_recycle_hit_rate_ema = smoothed_hit_rate
        self._auto_tune_server_recycle_pool(smoothed_hit_rate)
        message = (
            f"server recycle stats pool={len(self._server_recycled_item_ids)} "
            f"hits={self._server_recycle_hits} misses={self._server_recycle_misses} "
            f"drops={self._server_recycle_drops} hit_rate={raw_hit_rate:.1f}% ema={smoothed_hit_rate:.1f}%"
        )
        logger.debug(message, "ManageServerFrame")

    def _auto_tune_server_recycle_pool(self, hit_rate: float) -> None:
        """依命中率自動微調 recycle pool 上限。"""
        current = max(1, int(getattr(self, "_server_recycle_pool_max", 300)))
        min_size = max(1, int(getattr(self, "_server_recycle_pool_min", 150)))
        cap_size = max(min_size, int(getattr(self, "_server_recycle_pool_cap", 1200)))
        step = max(1, int(getattr(self, "_server_recycle_tune_step", 50)))
        pool_len = len(self._server_recycled_item_ids)
        new_size = compute_adaptive_pool_limit(
            current=current,
            min_size=min_size,
            cap_size=cap_size,
            step=step,
            pool_len=pool_len,
            hit_rate=hit_rate,
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

        # 使用約剩餘筆數的 1/divisor 作為動態批次大小，避免一次插入過多造成 UI 僵直。
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
        self,
        *,
        refresh_token: int,
        previous_selection: str | None,
        rows_snapshot: dict[str, tuple[Any, ...]],
    ) -> None:
        """重新整理收尾：避免過期任務覆寫新狀態。"""
        if refresh_token != self._server_refresh_token:
            return
        self._server_refresh_job = None
        self._server_rows_snapshot = rows_snapshot
        self._restore_server_selection(previous_selection)
        self.update_selection()
        self._set_server_tree_render_lock(False)

    def _apply_server_tree_diff(
        self,
        *,
        server_order: list[str],
        server_rows: dict[str, tuple[Any, ...]],
        refresh_token: int,
        previous_selection: str | None,
    ) -> None:
        """以差異更新 Treeview，減少 delete/insert 造成的卡頓。

        `refresh_token` 是本輪重新整理的輪次編號。這個方法可能透過 `after` 分批插入資料，
        因此它的執行生命週期可能跨越多次重新整理請求；每個批次都要先檢查 token。
        一旦偵測到 token 落後，代表已有較新的重新整理接手，舊批次必須立刻退出，
        以避免「慢的舊結果」晚到並覆寫「新的正確結果」。
        """
        tree = self.server_tree
        if not tree or not tree.winfo_exists():
            self._set_server_tree_render_lock(False)
            return

        # 刪除已不存在的伺服器列
        for name, stale_item_id in list(self._server_item_by_name.items()):
            if name in server_rows:
                continue
            self._recycle_server_item(stale_item_id)
            self._server_item_by_name.pop(name, None)

        # 更新既有列，並收集新增列
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

        # 沒有資料時直接收尾
        if not server_order:
            self._server_item_by_name.clear()
            self._finalize_server_refresh(
                refresh_token=refresh_token,
                previous_selection=previous_selection,
                rows_snapshot={},
            )
            return

        batch_size = self._get_server_insert_batch_size(len(pending_insert))

        def insert_batch(start_index: int, current_job_id: str | None = None) -> None:
            # 若本 callback 是由 after 排程進來，且仍持有相同 job id，先清掉工作標記。
            # 這可避免舊 callback 結束時誤清除較新輪次的 job id。
            if current_job_id and self._server_refresh_job == current_job_id:
                self._server_refresh_job = None

            # 每個分批插入都要驗證輪次，避免舊重新整理任務與新重新整理並行時互相覆寫。
            if refresh_token != self._server_refresh_token:
                # 舊輪次的批次插入；不應再繼續，並重置工作狀態。
                if current_job_id and self._server_refresh_job == current_job_id:
                    self._server_refresh_job = None
                return
            if not self.server_tree or not self.server_tree.winfo_exists():
                # 關聯的 Tree 已不存在；中止並重置工作狀態。
                if current_job_id and self._server_refresh_job == current_job_id:
                    self._server_refresh_job = None
                return
            try:
                end_index = min(start_index + batch_size, len(pending_insert))
                for idx in range(start_index, end_index):
                    name, values = pending_insert[idx]
                    recycled_item_id = self._acquire_recycled_server_item()
                    if recycled_item_id:
                        self.server_tree.item(recycled_item_id, values=values)
                        self.server_tree.reattach(recycled_item_id, "", "end")
                        inserted_item_id = recycled_item_id
                    else:
                        inserted_item_id = self.server_tree.insert("", "end", values=values)
                    self._server_item_by_name[name] = inserted_item_id
                    rows_snapshot[name] = values

                if end_index < len(pending_insert):
                    next_job_id: str | None = None

                    def _run_next() -> None:
                        insert_batch(end_index, current_job_id=next_job_id)

                    next_job_id = self.server_tree.after(1, _run_next)
                    self._server_refresh_job = next_job_id
                    return

                # 重新排序到最新順序；使用 move 不重建 row。
                for order_index, name in enumerate(server_order):
                    item_id = self._server_item_by_name.get(name)
                    if item_id:
                        self.server_tree.move(item_id, "", order_index)
                        if name not in rows_snapshot:
                            rows_snapshot[name] = server_rows[name]

                self._finalize_server_refresh(
                    refresh_token=refresh_token,
                    previous_selection=previous_selection,
                    rows_snapshot=rows_snapshot,
                )
            except Exception as e:
                logger.debug(f"差異插入伺服器列表失敗: {e}", "ManageServerFrame")
                self._server_refresh_job = None
                self._set_server_tree_render_lock(False)

        if pending_insert:
            insert_batch(0)
            return

        # 無新增列時，仍需排序並收尾
        try:
            for order_index, name in enumerate(server_order):
                item_id = self._server_item_by_name.get(name)
                if item_id:
                    tree.move(item_id, "", order_index)
                    rows_snapshot[name] = server_rows[name]
        except Exception as e:
            logger.debug(f"重排伺服器列表失敗: {e}", "ManageServerFrame")

        self._finalize_server_refresh(
            refresh_token=refresh_token,
            previous_selection=previous_selection,
            rows_snapshot=rows_snapshot,
        )

    def refresh_servers(self, reload_config: bool = True) -> None:
        """重新整理伺服器列表：只更新 UI，不自動偵測。"""

        def task():
            try:
                server_data = self._refresh_servers_task(reload_config)
                self.ui_queue.put(lambda: self._refresh_servers_callback(server_data))
            except Exception as e:
                logger.bind(component="").error(
                    f"重新整理伺服器列表失敗: {e}\n{traceback.format_exc()}",
                    "ManageServerFrame",
                )

        UIUtils.run_async(task)

    def _refresh_servers_task(self, reload_config: bool = True):
        """後台任務：載入配置並獲取伺服器狀態"""
        # 只有在需要時才強制重載配置
        if reload_config:
            self.server_manager.load_servers_config()

        server_data: list[list[Any]] = []
        if not self.server_manager.servers:
            return server_data

        for name, config in self.server_manager.servers.items():
            status = self._get_server_status_text(name, config)

            loader_type = (config.loader_type or "").lower()
            loader_version = (config.loader_version or "").lower()
            if loader_type == "vanilla":
                loader_col = "原版"
            elif loader_type == "unknown" or not loader_type:
                loader_col = "未知"
            else:
                loader_col = loader_type.capitalize()
                if loader_version and loader_version != "unknown":
                    loader_col = f"{loader_col} v{config.loader_version}"
            mc_version = (
                config.minecraft_version
                if config.minecraft_version and config.minecraft_version.lower() != "unknown"
                else "未知"
            )
            backup_status = self.get_backup_status(name)
            display_path = self._format_server_path_for_display(config.path)
            server_data.append([name, mc_version, loader_col, status, backup_status, display_path])

        return server_data

    def _format_server_path_for_display(self, raw_path: str) -> str:
        r"""將絕對路徑轉為易讀的 `servers\<name>` 形式。"""
        try:
            servers_root = Path(self.server_manager.servers_root).resolve()
            resolved = Path(raw_path).resolve()
            relative = resolved.relative_to(servers_root)
            return f"servers\\{relative}"
        except Exception:
            return str(raw_path)

    def _refresh_servers_callback(self, server_data: list[list[Any]]):
        """UI 更新回調"""
        if self.server_tree is None:
            return

        signature = self._make_server_data_signature(server_data)

        # 檢查資料是否變更（變更才進行差異更新）
        try:
            current_data_hash = hash(signature)
        except Exception:
            current_data_hash = hash(time.time())

        if (
            getattr(self, "_last_server_data_hash", None) is not None
            and getattr(self, "_last_server_data_hash", None) == current_data_hash
        ):
            # 如果資料沒變，只更新選擇狀態
            self.update_selection()
            return

        self._last_server_data_hash = current_data_hash
        # 新一輪重新整理啟動時先取消舊批次工作，避免等待舊批次下次 token 檢查才停止。
        self._cancel_server_refresh_job()
        # 每次啟動新一輪重新整理都遞增 token，使舊輪次排程任務自動失效。
        self._server_refresh_token += 1
        refresh_token = self._server_refresh_token
        previous_selection = self.selected_server

        self._set_server_tree_render_lock(True)
        lock_handed_off = False
        try:
            server_order: list[str] = []
            server_rows: dict[str, tuple[Any, ...]] = {}
            for row in server_data:
                if not row:
                    continue
                name = str(row[0])
                normalized = self._normalize_server_row(row)
                server_order.append(name)
                server_rows[name] = normalized

            self._apply_server_tree_diff(
                server_order=server_order,
                server_rows=server_rows,
                refresh_token=refresh_token,
                previous_selection=previous_selection,
            )
            # _apply_server_tree_diff 會在同步收尾或非同步收尾時自行解鎖。
            lock_handed_off = True
        finally:
            # 例外中斷時保底解鎖，避免後續 UI 佈局持續被鎖住。
            if not lock_handed_off:
                self._set_server_tree_render_lock(False)

    def on_server_select(self, _event) -> None:
        """伺服器選擇事件"""
        if not self.server_tree:
            return

        selection = self.server_tree.selection()
        if selection:
            item = self.server_tree.item(selection[0])
            self.selected_server = item["values"][0]  # 伺服器名稱
            self.callback(self.selected_server)
        else:
            self.selected_server = None

        self.update_selection()

    def on_server_tree_double_click(self, event) -> str | None:
        """Treeview 雙擊事件：欄位分隔線自動調寬，列雙擊開啟設定。"""
        tree = self.server_tree
        if not tree:
            return None

        region = tree.identify_region(event.x, event.y)
        if region in ("separator", "heading"):
            if region == "heading":
                # 標題列雙擊任一位置都可 auto-fit 該欄，提升可用性。
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
        """伺服器雙擊事件"""
        # 確保雙擊的是項目(row)而非空白區域
        if self.server_tree and self.server_tree.identify_row(event.y) and self.selected_server:
            self.configure_server()

    def update_selection(self) -> None:
        """更新選擇狀態"""
        has_selection = self.selected_server is not None

        # 更新按鈕狀態
        if has_selection:
            # 檢查伺服器是否正在運行
            is_running = self.server_manager.is_server_running(self.selected_server)

            # 根據運行狀態設定啟動/停止按鈕（使用固定 key）
            start_stop_key = "start_stop"
            if is_running:
                if start_stop_key in self.action_buttons:
                    self.action_buttons[start_stop_key].configure(text="🛑 停止", state="normal")
            elif start_stop_key in self.action_buttons:
                self.action_buttons[start_stop_key].configure(text="🚀 啟動", state="normal")

            # 其他按鈕
            for key, btn in self.action_buttons.items():
                if key != start_stop_key:
                    btn.configure(state="normal")
        else:
            # 沒有選擇時禁用所有按鈕
            for btn in self.action_buttons.values():
                btn.configure(state="disabled")
            start_stop_key = "start_stop"
            if start_stop_key in self.action_buttons:
                self.action_buttons[start_stop_key].configure(text="🚀 啟動")

        # 更新資訊標籤
        if has_selection and self.selected_server in self.server_manager.servers:
            config = self.server_manager.servers[self.selected_server]
            is_running = self.server_manager.is_server_running(self.selected_server)
            status_emoji = "🟢" if is_running else "🔴"
            status_text = "運行中" if is_running else "已停止"

            # 使用統一的記憶體格式化函數

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

            # 格式化載入器資訊
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
            info_text = f"{config.name} | {status_emoji} {status_text} | MC {config.minecraft_version if config.minecraft_version and config.minecraft_version.lower() != 'unknown' else '未知'} | {loader_info} | {memory_info}"
            self.info_label.configure(text=info_text)
        else:
            self.info_label.configure(text="✨ 選擇一個伺服器以查看詳細資訊")

    def start_server(self) -> None:
        """啟動/停止伺服器"""
        if not self.selected_server:
            return

        is_running = self.server_manager.is_server_running(self.selected_server)

        if is_running:
            # 停止伺服器 - 使用工具函數
            success = ServerOperations.graceful_stop_server(self.server_manager, self.selected_server)
            if success:
                UIUtils.show_info(
                    "成功",
                    f"伺服器 {self.selected_server} 停止命令已發送",
                    self.winfo_toplevel(),
                )
            else:
                UIUtils.show_error(
                    "錯誤",
                    f"停止伺服器 {self.selected_server} 失敗",
                    self.winfo_toplevel(),
                )
            # 立即更新一次，然後延遲再更新
            self._schedule_post_action_updates(100, 2000)
        else:
            # 啟動伺服器
            success = self.server_manager.start_server(self.selected_server, parent=self.master)
            if success:
                # 啟動成功後自動開啟監控視窗，彈窗通知交由監控視窗處理
                self.monitor_server()
            else:
                UIUtils.show_error(
                    "錯誤",
                    f"啟動伺服器 {self.selected_server} 失敗",
                    self.winfo_toplevel(),
                )
            # 立即更新一次，然後延遲再更新
            self._schedule_post_action_updates(100, 1500)

    def _immediate_update(self) -> None:
        """立即更新狀態"""
        self.refresh_servers()
        self.update_selection()

    def _delayed_update(self) -> None:
        """延遲更新，確保狀態正確"""
        self.update_selection()
        self.refresh_servers()

    def monitor_server(self) -> None:
        """監控伺服器"""
        if not self.selected_server:
            return

        # 導入並創建監控視窗
        monitor_window = ServerMonitorWindow(self.winfo_toplevel(), self.server_manager, self.selected_server)
        monitor_window.show()

    def configure_server(self) -> None:
        """設定伺服器"""
        if not self.selected_server:
            return

        config = self.server_manager.servers[self.selected_server]
        dialog = ServerPropertiesDialog(self.winfo_toplevel(), config, self.server_manager)

        if dialog.result:
            # 更新配置
            self.server_manager.servers[self.selected_server] = dialog.result
            self.server_manager.write_servers_config()
            self.refresh_servers()
            UIUtils.show_info("成功", "伺服器設定已更新", self.winfo_toplevel())

    def open_server_folder(self) -> None:
        """開啟伺服器資料夾"""
        if not self.selected_server:
            return

        config = self.server_manager.servers[self.selected_server]
        path = config.path

        try:
            UIUtils.open_external(path)
        except Exception as e:
            logger.error(f"無法開啟資料夾: {e}\n{traceback.format_exc()}")
            UIUtils.show_error("錯誤", f"無法開啟資料夾: {e}", self.winfo_toplevel())

    def delete_server(self) -> None:
        """刪除伺服器"""
        if not self.selected_server:
            return

        config = self.server_manager.servers[self.selected_server]

        # 檢查是否有備份
        has_backup = False
        backup_path = None
        if hasattr(config, "backup_path") and config.backup_path and Path(config.backup_path).exists():
            backup_path = config.backup_path
            has_backup = True

        # 基本刪除確認
        result = UIUtils.ask_yes_no_cancel(
            "確認刪除",
            f"確定要刪除伺服器 '{self.selected_server}' 嗎？\n\n" + "⚠️ 這將永久刪除伺服器檔案，無法復原！",
            self.winfo_toplevel(),
            show_cancel=False,
        )

        if not result:
            return

        # 如果有備份，詢問是否一起刪除
        delete_backup = False
        if has_backup:
            backup_result = UIUtils.ask_yes_no_cancel(
                "刪除備份",
                f"偵測到伺服器 '{self.selected_server}' 有備份檔案：\n{backup_path}\n\n是否要一起刪除備份？\n\n• 點擊「是」：刪除伺服器和備份\n• 點擊「否」：只刪除伺服器，保留備份\n• 點擊「取消」：取消整個刪除操作",
                self.winfo_toplevel(),
            )

            if backup_result is None:  # 使用者點擊取消
                return

            delete_backup = backup_result  # True = 一起刪除，False = 保留備份

        # 執行刪除操作
        success = self.server_manager.delete_server(self.selected_server)
        if success:
            # 如果需要刪除備份
            if delete_backup and backup_path:
                try:
                    PathUtils.delete_path(backup_path)
                    UIUtils.show_info(
                        "成功",
                        f"伺服器 {self.selected_server} 和其備份已刪除",
                        self.winfo_toplevel(),
                    )
                except Exception as e:
                    logger.bind(component="").error(
                        f"刪除備份失敗: {e}\n{traceback.format_exc()}",
                        "ManageServerFrame",
                    )
                    UIUtils.show_warning(
                        "部分成功",
                        f"伺服器 {self.selected_server} 已刪除，但備份刪除失敗：\n{e}\n\n備份位置：{backup_path}",
                        self.winfo_toplevel(),
                    )
            elif has_backup:
                UIUtils.show_info(
                    "成功",
                    f"伺服器 {self.selected_server} 已刪除\n\n備份已保留於：{backup_path}",
                    self.winfo_toplevel(),
                )
            else:
                UIUtils.show_info(
                    "成功",
                    f"伺服器 {self.selected_server} 已刪除",
                    self.winfo_toplevel(),
                )

            self.refresh_servers()
        else:
            UIUtils.show_error("錯誤", f"刪除伺服器 {self.selected_server} 失敗", self.winfo_toplevel())

    def backup_server(self) -> None:
        """備份伺服器世界檔案"""
        if not self.selected_server:
            return

        # 保存伺服器名稱，避免在清單重新整理時被清除
        server_name = self.selected_server
        config = self.server_manager.servers[server_name]
        server_path = config.path
        world_path = str(Path(server_path) / "world")

        # 檢查世界資料夾是否存在
        if not Path(world_path).exists():
            UIUtils.show_error("錯誤", f"找不到世界資料夾: {world_path}", self.winfo_toplevel())
            return

        # 檢查是否已有儲存的備份路徑
        backup_location = None
        is_new_backup_path = False  # 記錄是否是新設定的路徑

        if hasattr(config, "backup_path") and config.backup_path:
            # 嘗試確保備份路徑存在
            try:
                if not Path(config.backup_path).exists():
                    Path(config.backup_path).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.warning(f"無法建立備份路徑: {e}")

            backup_location = config.backup_path

        # 如果沒有備份路徑，詢問使用者
        if not backup_location:
            parent_backup_location = filedialog.askdirectory(title="選擇備份儲存位置", initialdir=str(Path.home()))

            if not parent_backup_location:
                return  # 使用者取消選擇

            # 建立伺服器專用的備份資料夾
            backup_folder_name = f"{server_name}_backup"
            backup_location = str(Path(parent_backup_location) / backup_folder_name)

            # 建立備份資料夾（如果不存在）
            try:
                Path(backup_location).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.bind(component="").error(
                    f"無法建立備份資料夾: {e}\n{traceback.format_exc()}",
                    "ManageServerFrame",
                )
                UIUtils.show_error("錯誤", f"無法建立備份資料夾: {e}", self.winfo_toplevel())
                return

            # 儲存備份路徑到配置檔案（儲存的是伺服器專用資料夾）
            config.backup_path = backup_location
            self.server_manager.write_servers_config()
            is_new_backup_path = True  # 標記為新設定的路徑

            # 立即重新整理一次清單以更新備份狀態（不重新載入配置，因為剛剛才存檔）
            self.refresh_servers(reload_config=False)

        # 建立備份檔案路徑
        backup_full_path = backup_location  # 備份路徑就是伺服器專用資料夾
        backup_world_path = str(Path(backup_full_path) / "world")

        # 轉換路徑為 Windows 格式
        world_path = str(Path(world_path))
        backup_full_path = str(Path(backup_full_path))
        backup_world_path = str(Path(backup_world_path))

        # 生成批次檔內容
        bat_content = f"""@echo off
@chcp 65001 > nul

REM 備份 {server_name} 伺服器世界檔案
REM Backup {server_name} server world files

REM 刪除舊的備份世界資料夾（如果存在）
REM Remove old backup world folder (if exists)
IF EXIST "{backup_world_path}" RD /Q /S "{backup_world_path}"

REM 建立世界備份資料夾
REM Create world backup folder
MD "{backup_world_path}"

REM 複製世界檔案到備份位置
REM Copy world files to backup location
xcopy "{world_path}\\" "{backup_world_path}" /E /Y /K /R /H

echo 備份完成！
echo Backup completed!
echo 伺服器: {server_name}
echo Server: {server_name}
echo 來源: {world_path}
echo Source: {world_path}
echo 目標: {backup_world_path}
echo Target: {backup_world_path}
echo.
pause"""

        # 儲存批次檔到備份資料夾內
        bat_file_path = str(Path(backup_full_path) / f"backup_{server_name}.bat")

        try:
            PathUtils.write_text_file(Path(bat_file_path), bat_content)

            # 如果是新設定的備份路徑，詢問是否立即執行備份
            # 如果已有備份路徑，直接執行備份
            if is_new_backup_path:
                # 詢問是否立即執行備份
                backup_msg = f"備份批次檔已建立：\n{bat_file_path}\n\n"
                backup_msg += (
                    f"✅ 備份資料夾已建立：{backup_full_path}\n"
                    "💡 如需更改備份路徑，請右鍵點擊伺服器選擇「重新設定備份路徑」。\n\n"
                )
                backup_msg += "是否立即執行備份？"

                result = UIUtils.ask_yes_no_cancel(
                    "備份檔案已建立",
                    backup_msg,
                    self.winfo_toplevel(),
                    show_cancel=False,
                )

                if not result:
                    UIUtils.show_info(
                        "備份檔案已建立",
                        f"備份批次檔已儲存至：\n{bat_file_path}\n\n您可以稍後手動執行此檔案來進行備份。",
                        self.winfo_toplevel(),
                    )
                    # 即使不立即執行備份，也要重新整理清單以更新備份狀態（因為建立了備份資料夾）
                    self.refresh_servers()
                    return

            # 執行備份（新路徑詢問後同意，或已有路徑直接執行）
            # 執行批次檔（不顯示命令視窗）
            try:
                # 使用 subprocess 執行，隱藏命令視窗
                startupinfo = SubprocessUtils.STARTUPINFO()
                startupinfo.dwFlags |= SubprocessUtils.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = SubprocessUtils.SW_HIDE

                SubprocessUtils.popen_checked(
                    [bat_file_path],
                    stdin=SubprocessUtils.DEVNULL,
                    stdout=SubprocessUtils.DEVNULL,
                    stderr=SubprocessUtils.DEVNULL,
                    close_fds=True,
                    startupinfo=startupinfo,
                )

                UIUtils.show_info(
                    "備份開始",
                    f"備份已開始執行，請稍候...\n備份位置：{backup_full_path}",
                    self.winfo_toplevel(),
                )

                # 立即重新整理一次清單
                self.refresh_servers()

                # 再次延遲重新整理，確保狀態正確
                self._schedule_refresh(5000)

            except Exception as e:
                logger.bind(component="").error(
                    f"執行備份批次檔失敗: {e}\n{traceback.format_exc()}",
                    "ManageServerFrame",
                )
                UIUtils.show_error("執行錯誤", f"執行備份批次檔失敗：{e}", self.winfo_toplevel())

        except Exception as e:
            logger.bind(component="").error(
                f"建立備份批次檔失敗: {e}\n{traceback.format_exc()}",
                "ManageServerFrame",
            )
            UIUtils.show_error("錯誤", f"建立備份批次檔失敗：{e}", self.winfo_toplevel())
