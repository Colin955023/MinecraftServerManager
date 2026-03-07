#!/usr/bin/env python3
"""模組管理頁面
參考 Prism Launcher 設計，支援線上模組查詢與下載
"""

import contextlib
import queue
import re
import time
import tkinter as tk
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

import customtkinter as ctk

from ..core import MinecraftVersionManager, ModManager, ModStatus
from ..utils import (
    Colors,
    FontManager,
    FontSize,
    PathUtils,
    Sizes,
    UIUtils,
    compute_adaptive_pool_limit,
    compute_exponential_moving_average,
    get_logger,
)
from . import CustomDropdown, enhance_local_mod

logger = get_logger().bind(component="ModManagement")


class ModManagementFrame:
    def __init__(
        self,
        parent,
        server_manager,
        on_server_selected_callback: Callable | None = None,
        version_manager: MinecraftVersionManager = None,
    ):
        self.parent = parent
        self.server_manager = server_manager
        self.on_server_selected = on_server_selected_callback
        self.version_manager = version_manager

        # 目前選中的伺服器
        self.current_server = None
        self.mod_manager: ModManager | None = None

        # 版本相關變數
        self.versions: list = []
        self.release_versions: list = []

        # 多選狀態管理
        self.all_selected = False
        self.selected_mods: set[str] = set()  # 儲存選中的模組 ID

        # 預編譯正則表達式（效能優化：避免每次 refresh 都重新編譯）
        self.VERSION_PATTERN = re.compile(r"-([\dv.]+)(?:\.jar(?:\.disabled)?)?$")

        # UI 元件
        self.main_frame: ctk.CTkFrame | None = None
        self.notebook: ttk.Notebook | None = None
        self.local_tab: ctk.CTkFrame | None = None
        self.browse_tab: ctk.CTkFrame | None = None

        # 本地模組頁面
        self.local_tree: ttk.Treeview | None = None
        self.local_v_scrollbar: ttk.Scrollbar | None = None
        self.local_h_scrollbar: ttk.Scrollbar | None = None
        self._local_refresh_job: str | None = None
        self._local_refresh_token = 0
        self._local_filter_job = None
        self._local_tree_render_locked = False
        self._local_item_by_mod_id: dict[str, str] = {}
        self._local_rows_snapshot: dict[str, tuple[tuple[Any, ...], tuple[str, ...]]] = {}
        self._local_recycled_item_ids: list[str] = []
        self._local_recycle_pool_max = 500
        # 重用池觀測指標（debug）：用於調整 pool 上限與命中率。
        self._local_recycle_hits = 0
        self._local_recycle_misses = 0
        self._local_recycle_drops = 0
        self._local_recycle_log_every = 200
        self._local_recycle_pool_min = 250
        self._local_recycle_pool_cap = 1600
        self._local_recycle_tune_step = 80
        self._local_recycle_hit_rate_ema: float | None = None
        self._local_recycle_ema_alpha = 0.35
        self._local_insert_batch_base = 60
        self._local_insert_batch_max = 180
        self._local_insert_batch_divisor = 8

        # 狀態
        self.local_mods: list[Any] = []
        self.enhanced_mods_cache: dict[str, Any] = {}
        self._last_mods_dir: str | None = None
        self._last_mods_dir_mtime: float | None = None
        self._status_update_job = None
        self._pending_status_message: str = ""

        self.ui_queue: queue.Queue = queue.Queue()

        self.create_widgets()
        host = self.main_frame if (self.main_frame and self.main_frame.winfo_exists()) else self.parent
        UIUtils.start_ui_queue_pump(host, self.ui_queue)
        self.load_servers()

    def update_status(self, message: str) -> None:
        """安全地更新狀態標籤（合併 idle 更新，避免高頻重繪）。"""
        self._pending_status_message = str(message)
        try:
            if hasattr(self, "status_label") and self.status_label and self.status_label.winfo_exists():
                if hasattr(self, "parent") and self.parent and self.parent.winfo_exists():
                    UIUtils.schedule_coalesced_idle(
                        self.parent,
                        "_status_update_job",
                        self._apply_status_label_update,
                        owner=self,
                    )
                else:
                    self._apply_status_label_update()
        except Exception as e:
            logger.error(f"更新狀態失敗: {e}\n{traceback.format_exc()}")

    def _apply_status_label_update(self) -> None:
        """套用合併後的狀態文字。"""
        self._status_update_job = None
        if hasattr(self, "status_label") and self.status_label and self.status_label.winfo_exists():
            self.status_label.configure(text=self._pending_status_message)

    def update_status_safe(self, message: str) -> None:
        """更安全的狀態更新，使用佇列"""
        self.ui_queue.put(lambda: self.update_status(message))

    def update_progress_safe(self, value: float) -> None:
        """更安全的進度更新，使用佇列"""

        def _update():
            if hasattr(self, "progress_var") and self.progress_var:
                self.progress_var.set(value)

        self.ui_queue.put(_update)

    def create_widgets(self) -> None:
        """建立 UI 元件"""
        # 主框架
        self.main_frame = ctk.CTkFrame(self.parent)

        # 標題區域
        self.create_header()

        # 伺服器選擇區域
        self.create_server_selection()

        # 狀態列
        self.create_status_bar()

        # 頁籤介面
        self.create_notebook()

    def create_server_selection(self) -> None:
        """建立伺服器選擇區域"""
        server_frame = ctk.CTkFrame(self.main_frame)
        server_frame.pack(fill="x", padx=20, pady=(0, 10))

        inner_frame = ctk.CTkFrame(server_frame, fg_color="transparent")
        inner_frame.pack(fill="x", padx=15, pady=10)

        # 伺服器選擇
        ctk.CTkLabel(
            inner_frame,
            text="📁 伺服器:",
            font=FontManager.get_font(size=FontSize.NORMAL_PLUS, weight="bold"),
        ).pack(side="left")

        self.server_var = tk.StringVar()
        self.server_combo = CustomDropdown(
            inner_frame,
            variable=self.server_var,
            values=["載入中..."],
            command=self.on_server_changed,
            width=FontManager.get_dpi_scaled_size(200),
        )
        self.server_combo.pack(side="left", padx=(10, 0))

        # 重新整理按鈕
        refresh_btn = ctk.CTkButton(
            inner_frame,
            text="🔄 重新整理",
            font=FontManager.get_font(size=FontSize.MEDIUM),
            command=self.load_servers,
            width=Sizes.BUTTON_WIDTH_SECONDARY,
            height=Sizes.INPUT_HEIGHT,
        )
        refresh_btn.pack(side="left", padx=(10, 0))

    def create_header(self) -> None:
        """建立標題區域"""
        header_frame = ctk.CTkFrame(self.main_frame)
        header_frame.pack(fill="x", padx=20, pady=(20, 10))

        # 創建標題
        title_label = ctk.CTkLabel(
            header_frame,
            text="🧩 模組管理",
            font=FontManager.get_font(size=FontSize.HEADING_XLARGE, weight="bold"),
        )
        title_label.pack(side="left", padx=15, pady=15)

        desc_label = ctk.CTkLabel(
            header_frame,
            text="參考 Prism launcher 功能設計，提供模組管理體驗",
            font=FontManager.get_font(size=FontSize.NORMAL_PLUS),
            text_color=Colors.TEXT_SECONDARY,
        )
        desc_label.pack(side="left", padx=(15, 15), pady=15)

    def create_local_mods_tab(self) -> None:
        """建立本地模組頁面"""
        if not self.notebook:
            return
        self.local_tab = ctk.CTkFrame(self.notebook)
        self.notebook.add(self.local_tab, text="📁 本地模組")
        # 工具列
        self.create_local_toolbar()

        # 模組列表
        self.create_local_mod_list()

    def create_browse_mods_tab(self) -> None:
        """建立線上瀏覽頁面（暫停開發，僅顯示通知）"""
        if not self.notebook:
            return
        self.browse_tab = ctk.CTkFrame(self.notebook)
        self.notebook.add(self.browse_tab, text="🌐 瀏覽模組")
        notice = ctk.CTkLabel(
            self.browse_tab,
            text="目前瀏覽模組功能暫停開發，請手動下載模組。",
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
            text_color=Colors.TEXT_SECONDARY,
        )
        notice.pack(expand=True, fill="both", pady=80)

    def create_notebook(self) -> None:
        """建立頁籤介面"""
        # 使用 ttk.Notebook
        self.notebook = ttk.Notebook(self.main_frame)

        # 設置頁籤字體使用DPI縮放
        style = ttk.Style()
        style.configure("Tab", font=FontManager.get_font("Microsoft JhengHei", FontSize.LARGE, "bold"))

        self.notebook.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        # 本地模組頁面
        self.create_local_mods_tab()

        # 線上瀏覽頁面
        self.create_browse_mods_tab()

        # 綁定頁籤切換事件
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

    def on_tab_changed(self, _event=None) -> None:
        """頁籤切換事件"""
        try:
            if not self.notebook:
                return
            current_tab = self.notebook.index(self.notebook.select())
            if current_tab == 0:  # 本地模組頁面
                self.refresh_local_list()
            elif current_tab == 1:  # 線上瀏覽頁面
                pass  # 線上頁面不需要自動重新整理
        except Exception as e:
            logger.error(f"處理頁籤切換事件失敗: {e}\n{traceback.format_exc()}")

    def create_local_toolbar(self) -> None:
        """建立本地模組工具列"""
        toolbar_frame = ctk.CTkFrame(self.local_tab)
        toolbar_frame.pack(fill="x", padx=14, pady=14)

        # 左側按鈕
        left_frame = ctk.CTkFrame(toolbar_frame, fg_color="transparent")
        left_frame.pack(side="left", padx=7)

        # 建立統一樣式的按鈕（使用與 manage_server_frame 相同的風格）

        # 匯入模組
        import_btn = ctk.CTkButton(
            left_frame,
            text="📁 匯入模組",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.import_mod_file,
            fg_color=Colors.BUTTON_SUCCESS,
            hover_color=Colors.BUTTON_SUCCESS_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        import_btn.pack(side="left", padx=(0, FontManager.get_dpi_scaled_size(15)))

        # 重新整理（強制掃描）
        refresh_mod_list_btn = ctk.CTkButton(
            left_frame,
            text="🔄 重新整理",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.refresh_mod_list_force,
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        refresh_mod_list_btn.pack(side="left", padx=(0, FontManager.get_dpi_scaled_size(15)))

        # 檢查更新
        update_btn = ctk.CTkButton(
            left_frame,
            text="🔄 檢查更新",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=lambda: UIUtils.show_info("提示", "目前檢查更新功能暫停開發，請手動檢查模組更新。", self.parent),
            fg_color=Colors.BUTTON_PRIMARY,
            hover_color=Colors.BUTTON_PRIMARY_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        update_btn.pack(side="left", padx=(0, FontManager.get_dpi_scaled_size(15)))

        # 全選/取消全選
        self.select_all_btn = ctk.CTkButton(
            left_frame,
            text="☑️ 全選",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.toggle_select_all,
            fg_color=Colors.BUTTON_WARNING,
            hover_color=Colors.BUTTON_WARNING_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        self.select_all_btn.pack(side="left", padx=(0, FontManager.get_dpi_scaled_size(15)))

        # 批量啟用/停用
        self.batch_toggle_btn = ctk.CTkButton(
            left_frame,
            text="🔄 批量切換",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.batch_toggle_selected,
            fg_color=Colors.BUTTON_PURPLE,
            hover_color=Colors.BUTTON_PURPLE_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        self.batch_toggle_btn.pack(side="left", padx=(0, FontManager.get_dpi_scaled_size(15)))

        # 開啟模組資料夾
        folder_btn = ctk.CTkButton(
            left_frame,
            text="📂 開啟資料夾",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.open_mods_folder,
            fg_color=Colors.BUTTON_PURPLE_DARK,
            hover_color=Colors.BUTTON_PURPLE_DARK_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        folder_btn.pack(side="left")

        # 右側篩選
        right_frame = ctk.CTkFrame(toolbar_frame, fg_color="transparent")
        right_frame.pack(side="right", padx=15)

        # 搜尋框
        search_frame = ctk.CTkFrame(right_frame, fg_color="transparent")
        search_frame.pack(side="left", padx=(0, 15))

        # 搜尋圖示
        search_label = ctk.CTkLabel(
            search_frame,
            text="🔍",
            font=FontManager.get_font(size=FontSize.HEADING_MEDIUM),
        )
        search_label.pack(side="left")

        self.local_search_var = tk.StringVar()
        search_entry = ctk.CTkEntry(
            search_frame,
            textvariable=self.local_search_var,
            font=FontManager.get_font(size=FontSize.MEDIUM),
            width=Sizes.DROPDOWN_COMPACT_WIDTH,
            height=Sizes.INPUT_HEIGHT,
        )
        search_entry.pack(side="left", padx=(FontManager.get_dpi_scaled_size(8), 0))
        self.local_search_var.trace("w", self.filter_local_mods)

        # 狀態篩選
        self.local_filter_var = tk.StringVar(value="所有")
        filter_combo = CustomDropdown(
            right_frame,
            variable=self.local_filter_var,
            values=["所有", "啟用", "停用"],
            command=self.on_filter_changed,
            width=Sizes.DROPDOWN_FILTER_WIDTH,
            height=Sizes.INPUT_HEIGHT,
        )
        filter_combo.pack(side="left")

    def on_filter_changed(self, _value: str) -> None:
        """篩選變更回調"""
        self.filter_local_mods()

    def refresh_mod_list_force(self) -> None:
        """強制重新掃描本地模組並重繪列表"""
        if self.mod_manager:
            manager = self.mod_manager

            def load_thread():
                try:
                    self.update_status_safe("正在強制重新掃描本地模組...")
                    mods = manager.scan_mods()
                    self.local_mods = mods
                    self.enhanced_mods_cache = {}
                    self.enhance_local_mods()
                    self.update_status_safe(f"找到 {len(mods)} 個本地模組 (已重新整理)")
                except Exception as e:
                    logger.bind(component="").error(
                        f"強制掃描失敗: {e}\n{traceback.format_exc()}",
                        "ModManagementFrame",
                    )
                    self.update_status_safe(f"強制掃描失敗: {e}")

            UIUtils.run_async(load_thread)

    def create_local_mod_list(self) -> None:
        """建立本地模組列表"""
        list_frame = ctk.CTkFrame(self.local_tab)
        list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 匯出模組按鈕
        export_btn = ctk.CTkButton(
            list_frame,
            text="匯出模組列表",
            font=FontManager.get_font(size=FontSize.HEADING_SMALL, weight="bold"),
            fg_color=Colors.BUTTON_PRIMARY,
            hover_color=Colors.BUTTON_PRIMARY_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            command=self.export_mod_list_dialog,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT_EXPORT,
        )
        export_btn.pack(anchor="ne", pady=(10, 5), padx=10)

        # 建立包含 Treeview 和滾動條的容器
        tree_container = ctk.CTkFrame(list_frame)
        tree_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        style = ttk.Style()
        style.configure(
            "ModList.Treeview",
            font=FontManager.get_font(size=FontSize.INPUT),
            rowheight=int(25 * FontManager.get_scale_factor()),
        )
        style.configure(
            "ModList.Treeview.Heading",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
        )

        # 建立 Treeview
        columns = (
            "status",
            "name",
            "version",
            "author",
            "loader",
            "size",
            "mtime",
            "description",
        )
        self.local_tree = ttk.Treeview(
            tree_container,
            columns=columns,
            show="headings",
            height=Sizes.TREEVIEW_VISIBLE_ROWS,
            selectmode="extended",  # 支援多選
            style="ModList.Treeview",
        )

        column_config = {
            "status": ("狀態", 80),
            "name": ("模組名稱", 200),
            "version": ("版本", 100),
            "author": ("作者", 120),
            "loader": ("載入器", 80),
            "size": ("檔案大小", 100),
            "mtime": ("修改時間", 120),
            "description": ("描述", 300),
        }
        for col, (text, width) in column_config.items():
            self.local_tree.heading(col, text=text, anchor="w")
            self.local_tree.column(col, width=width, minwidth=50)

        # 滾動條
        v_scrollbar = ttk.Scrollbar(tree_container, orient="vertical", command=self.local_tree.yview)
        h_scrollbar = ttk.Scrollbar(tree_container, orient="horizontal", command=self.local_tree.xview)
        self.local_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        self.local_v_scrollbar = v_scrollbar
        self.local_h_scrollbar = h_scrollbar

        # 使用 grid 佈局確保滾動條在正確位置
        self.local_tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        is_dark = ctk.get_appearance_mode() == "Dark"
        bg_odd = Colors.BG_LISTBOX_DARK if is_dark else Colors.BG_PRIMARY[0]
        bg_even = Colors.BG_LISTBOX_ALT_DARK if is_dark else Colors.BG_ROW_SOFT_LIGHT

        self.local_tree.tag_configure("odd", background=bg_odd)
        self.local_tree.tag_configure("even", background=bg_even)

        # 配置 grid 權重
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        # 綁定事件
        self.local_tree.bind("<Double-1>", self.toggle_local_mod)
        self.local_tree.bind("<Button-3>", self.show_local_context_menu)
        self.local_tree.bind("<<TreeviewSelect>>", self.on_tree_selection_changed)

    def export_mod_list_dialog(self) -> None:
        """支援格式選擇(txt/json/html)與直接存檔，檔名自動帶入伺服器名稱"""
        if not self.mod_manager or not self.current_server:
            UIUtils.show_error("錯誤", "請先選擇伺服器以匯出模組列表。", self.parent)
            return
        try:
            dialog = UIUtils.create_toplevel_dialog(
                self.parent,
                "匯出模組列表",
                width=Sizes.DIALOG_LARGE_WIDTH,
                height=Sizes.DIALOG_LARGE_HEIGHT,
                delay_ms=250,  # 使用稍長延遲確保圖示綁定成功
            )

            # 主容器
            main_frame = ctk.CTkFrame(dialog)
            main_frame.pack(fill="both", expand=True, padx=20, pady=20)

            # 標題
            title_label = ctk.CTkLabel(
                main_frame,
                text="匯出模組列表",
                font=FontManager.get_font(size=FontSize.HEADING_XLARGE, weight="bold"),
            )
            title_label.pack(pady=(10, 20))

            # 格式選擇區域
            fmt_frame = ctk.CTkFrame(main_frame)
            fmt_frame.pack(fill="x", pady=(0, 15))

            fmt_inner = ctk.CTkFrame(fmt_frame, fg_color="transparent")
            fmt_inner.pack(fill="x", padx=20, pady=15)

            ctk.CTkLabel(
                fmt_inner,
                text="選擇匯出格式:",
                font=FontManager.get_font(size=FontSize.HEADING_MEDIUM, weight="bold"),
            ).pack(
                side="left",
                padx=(0, 15),
            )

            fmt_var = tk.StringVar(value="text")

            # 使用 CTK 選項按鈕
            text_radio = ctk.CTkRadioButton(
                fmt_inner,
                text="純文字",
                variable=fmt_var,
                value="text",
                font=FontManager.get_font(size=FontSize.LARGE),
            )
            text_radio.pack(side="left", padx=5)

            json_radio = ctk.CTkRadioButton(
                fmt_inner,
                text="JSON",
                variable=fmt_var,
                value="json",
                font=FontManager.get_font(size=FontSize.LARGE),
            )
            json_radio.pack(side="left", padx=5)

            html_radio = ctk.CTkRadioButton(
                fmt_inner,
                text="HTML",
                variable=fmt_var,
                value="html",
                font=FontManager.get_font(size=FontSize.LARGE),
            )
            html_radio.pack(side="left", padx=5)

            # 預覽區域
            preview_frame = ctk.CTkFrame(main_frame)
            preview_frame.pack(fill="both", expand=True, pady=(0, 15))

            preview_label = ctk.CTkLabel(
                preview_frame,
                text="預覽:",
                font=FontManager.get_font(size=FontSize.HEADING_MEDIUM, weight="bold"),
            )
            preview_label.pack(anchor="w", padx=15, pady=(15, 5))

            text_widget = ctk.CTkTextbox(
                preview_frame,
                font=FontManager.get_font(size=FontSize.LARGE),
                height=Sizes.PREVIEW_TEXTBOX_HEIGHT,
                wrap="word",
            )
            text_widget.pack(fill="both", expand=True, padx=15, pady=(0, 15))

            def update_preview(*_):
                export_text = self.mod_manager.export_mod_list(fmt_var.get())
                text_widget.delete("1.0", "end")
                text_widget.insert("1.0", export_text)

            fmt_var.trace_add("write", update_preview)
            update_preview()

            # 按鈕區域
            btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
            btn_frame.pack(pady=(0, 10))

            def do_save():
                fmt = fmt_var.get()
                ext = {"text": "txt", "json": "json", "html": "html"}[fmt]
                server_name = getattr(self.current_server, "name", "server")
                default_name = f"{server_name}_模組列表.{ext}"
                file_path = filedialog.asksaveasfilename(
                    title="儲存模組列表",
                    defaultextension=f".{ext}",
                    filetypes=[
                        ("所有檔案", "*.*"),
                        ("純文字", "*.txt"),
                        ("JSON", "*.json"),
                        ("HTML", "*.html"),
                    ],
                    initialfile=default_name,
                )
                if file_path:
                    export_text = self.mod_manager.export_mod_list(fmt)
                    PathUtils.write_text_file(Path(file_path), export_text)
                    try:
                        result = UIUtils.ask_yes_no_cancel(
                            "匯出成功",
                            f"已儲存: {file_path}\n\n是否要立即開啟匯出的檔案？",
                            parent=dialog,  # 傳遞正確的父視窗
                            show_cancel=False,
                        )
                        if result:
                            UIUtils.open_external(file_path)
                    except Exception as e:
                        logger.bind(component="").error(
                            f"開啟檔案失敗: {e}\n{traceback.format_exc()}",
                            "ModManagementFrame",
                        )
                        UIUtils.show_error("開啟檔案失敗", f"無法開啟檔案: {e}", parent=dialog)

            save_btn = ctk.CTkButton(
                btn_frame,
                text="儲存到檔案",
                command=do_save,
                font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
                fg_color=Colors.BUTTON_PRIMARY,
                hover_color=Colors.BUTTON_PRIMARY_HOVER,
                width=FontManager.get_dpi_scaled_size(180),
                height=int(40 * FontManager.get_scale_factor()),
            )
            save_btn.pack(side="left", padx=(0, 10))

            close_btn = ctk.CTkButton(
                btn_frame,
                text="關閉",
                command=dialog.destroy,
                font=FontManager.get_font(size=FontSize.LARGE),
                fg_color=Colors.BUTTON_SECONDARY,
                hover_color=Colors.BUTTON_SECONDARY_HOVER,
                width=FontManager.get_dpi_scaled_size(150),
                height=int(40 * FontManager.get_scale_factor()),
            )
            close_btn.pack(side="left")
            dialog.bind("<Escape>", lambda _e: dialog.destroy())

        except Exception as e:
            logger.error(f"匯出對話框錯誤: {e}\n{traceback.format_exc()}")
            UIUtils.show_error("匯出對話框錯誤", str(e), self.parent)

    def create_status_bar(self) -> None:
        """建立狀態列"""
        status_frame = ctk.CTkFrame(self.main_frame, height=int(40 * FontManager.get_scale_factor()))
        status_frame.pack(side="bottom", fill="x", padx=20, pady=(0, 20))
        status_frame.pack_propagate(False)

        # 狀態標籤
        self.status_label = ctk.CTkLabel(
            status_frame,
            text="請選擇伺服器開始管理模組",
            font=FontManager.get_font(size=FontSize.HEADING_MEDIUM),
            text_color=Colors.TEXT_SECONDARY,
        )
        self.status_label.pack(side="left", padx=10, pady=int(6 * FontManager.get_scale_factor()))

        # 進度條（亮綠色，使用 CTK）
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ctk.CTkProgressBar(
            status_frame,
            variable=self.progress_var,
            width=FontManager.get_dpi_scaled_size(300),
            height=int(20 * FontManager.get_scale_factor()),
            progress_color=Colors.PROGRESS_ACCENT,
            fg_color=Colors.PROGRESS_TRACK,
        )
        self.progress_bar.pack(side="right", padx=10, pady=int(6 * FontManager.get_scale_factor()))

    def load_servers(self) -> None:
        """載入伺服器列表"""
        try:
            servers = list(self.server_manager.servers.values())
            server_names = [server.name for server in servers]

            # 若列表為空，顯示一個空白選項
            if not server_names:
                self.server_combo.configure(values=[""])
                self.server_var.set("")
                self.current_server = None
                if hasattr(self, "local_mods"):
                    self.local_mods = []
                if hasattr(self, "refresh_local_list"):
                    self.refresh_local_list()
            else:
                self.server_combo.configure(values=server_names)
                if server_names:
                    self.server_var.set(server_names[0])
                self.on_server_changed()

        except Exception as e:
            logger.bind(component="").error(
                f"載入伺服器列表失敗: {e}\n{traceback.format_exc()}",
                "ModManagementFrame",
            )
            UIUtils.show_error("錯誤", f"載入伺服器列表失敗: {e}", self.parent)

    def on_server_changed(self, _event=None) -> None:
        """伺服器選擇改變時的處理"""
        server_name = self.server_var.get()
        if not server_name:
            return

        try:
            # 獲取伺服器資訊
            servers = list(self.server_manager.servers.values())
            selected_server = None

            for server in servers:
                if server.name == server_name:
                    selected_server = server
                    break

            if not selected_server:
                return

            self.current_server = selected_server

            self.mod_manager = ModManager(selected_server.path)

            # 載入本地模組
            self.load_local_mods()

            # 更新狀態
            if self.on_server_selected:
                self.on_server_selected(server_name)

        except Exception as e:
            logger.error(f"切換伺服器失敗: {e}\n{traceback.format_exc()}")
            UIUtils.show_error("錯誤", f"切換伺服器失敗: {e}", self.parent)

    def load_local_mods(self) -> None:
        """載入本地模組，並同步清空增強 cache，確保顯示一致，並顯示進度條"""
        if not self.mod_manager:
            return

        manager = self.mod_manager
        mods_dir = Path(self.current_server.path) / "mods" if self.current_server else None
        mods_dir_key = str(mods_dir.resolve()) if mods_dir else ""
        mods_dir_mtime: float | None
        try:
            mods_dir_mtime = mods_dir.stat().st_mtime if mods_dir and mods_dir.exists() else None
        except Exception:
            mods_dir_mtime = None

        if (
            mods_dir_key
            and mods_dir_key == getattr(self, "_last_mods_dir", None)
            and mods_dir_mtime == getattr(self, "_last_mods_dir_mtime", None)
            and self.local_mods
        ):
            self.update_status_safe(f"找到 {len(self.local_mods)} 個本地模組")
            self.ui_queue.put(self.refresh_local_list)
            return

        def load_thread():
            try:
                self.update_status_safe("正在掃描本地模組...")
                mods = list(manager.scan_mods())

                # 去重：同一個 base_name 同時存在 .jar 與 .jar.disabled 時，只保留一筆（優先 enabled）
                dedup: dict[str, Any] = {}
                for mod in mods:
                    base_name = mod.filename.replace(".jar.disabled", "").replace(".jar", "")
                    existing = dedup.get(base_name)
                    if existing is None or mod.status == ModStatus.ENABLED:
                        dedup[base_name] = mod
                mods = list(dedup.values())

                total = len(mods)
                self.local_mods = []
                self.enhanced_mods_cache = {}
                last_percent = -1
                for idx, mod in enumerate(mods):
                    # 預先在背景執行緒計算 mtime，避免 UI 執行緒大量 stat() 卡頓
                    try:
                        mod._cached_mtime = Path(mod.file_path).stat().st_mtime
                    except Exception:
                        mod._cached_mtime = None
                    self.local_mods.append(mod)
                    percent = (idx + 1) / total * 100 if total else 0
                    rounded_percent = int(percent)
                    if rounded_percent != last_percent:
                        last_percent = rounded_percent
                        self.update_progress_safe(percent)

                # 更新快取快照
                self._last_mods_dir = mods_dir_key
                try:
                    self._last_mods_dir_mtime = mods_dir.stat().st_mtime if mods_dir and mods_dir.exists() else None
                except Exception:
                    self._last_mods_dir_mtime = mods_dir_mtime

                self.enhance_local_mods()
                self.update_status_safe(f"找到 {len(mods)} 個本地模組")
            except Exception as e:
                logger.error(f"掃描失敗: {e}\n{traceback.format_exc()}")
                self.update_progress_safe(0)
                self.update_status_safe(f"掃描失敗: {e}")

        UIUtils.run_async(load_thread)

    def enhance_local_mods(self) -> None:
        """本地模組增強資訊，查詢完自動刷新列表（可選）"""

        def enhance_single(mod):
            try:
                if mod.filename in self.enhanced_mods_cache:
                    return

                enhanced = enhance_local_mod(mod.filename)
                if enhanced:
                    self.enhanced_mods_cache[mod.filename] = enhanced
                    time.sleep(0.05)  # 50ms 延遲
            except Exception as e:
                logger.bind(component="").error(
                    f"模組 {mod.filename} 資訊失敗: {e}\n{traceback.format_exc()}",
                    "ModManagementFrame",
                )

        def enhance_thread():
            with ThreadPoolExecutor(max_workers=3) as executor:
                executor.map(enhance_single, self.local_mods)

            # 使用佇列更新 UI
            self.ui_queue.put(self.refresh_local_list)

        UIUtils.run_async(enhance_thread)

    def _get_enhanced_attr(self, enhanced, attr: str, fallback):
        """屬性值或後備值"""
        if enhanced:
            value = getattr(enhanced, attr, None)
            if value:
                return value
        return fallback

    def _cancel_local_refresh_job(self) -> None:
        """取消尚未完成的本地模組列表批次插入（共用排程 helper）。"""
        tree = self.local_tree
        if not tree:
            self._local_refresh_job = None
            return
        UIUtils.cancel_scheduled_job(tree, "_local_refresh_job", owner=self)

    def _recycle_local_item(self, item_id: str) -> None:
        """回收不再顯示的 local Tree item，後續可重用。"""
        if not self.local_tree or not item_id:
            return
        try:
            if not self.local_tree.exists(item_id):
                return
            self.local_tree.detach(item_id)
            pool = self._local_recycled_item_ids
            pool.append(item_id)
            max_size = max(0, int(getattr(self, "_local_recycle_pool_max", 500)))
            if len(pool) > max_size:
                stale_id = pool.pop(0)
                self._local_recycle_drops += 1
                with contextlib.suppress(Exception):
                    if self.local_tree.exists(stale_id):
                        self.local_tree.delete(stale_id)
                self._maybe_log_local_recycle_stats()
        except Exception as e:
            logger.debug(f"回收 local tree item 失敗 item_id={item_id}: {e}", "ModManagement")

    def _acquire_recycled_local_item(self) -> str | None:
        """從 local 重用池取回可用 item。"""
        tree = self.local_tree
        if not tree:
            return None
        pool = self._local_recycled_item_ids
        while pool:
            candidate = pool.pop()
            with contextlib.suppress(Exception):
                if tree.exists(candidate):
                    self._local_recycle_hits += 1
                    self._maybe_log_local_recycle_stats()
                    return candidate
        self._local_recycle_misses += 1
        self._maybe_log_local_recycle_stats()
        return None

    def _maybe_log_local_recycle_stats(self) -> None:
        """定期輸出 local 重用池命中統計（debug），用於調整池大小。"""
        interval = max(1, int(getattr(self, "_local_recycle_log_every", 200)))
        total = int(getattr(self, "_local_recycle_hits", 0)) + int(getattr(self, "_local_recycle_misses", 0))
        if total <= 0 or (total % interval) != 0:
            return
        raw_hit_rate = (self._local_recycle_hits / total) * 100.0
        smoothed_hit_rate = compute_exponential_moving_average(
            previous=getattr(self, "_local_recycle_hit_rate_ema", None),
            current=raw_hit_rate,
            alpha=float(getattr(self, "_local_recycle_ema_alpha", 0.35)),
        )
        self._local_recycle_hit_rate_ema = smoothed_hit_rate
        self._auto_tune_local_recycle_pool(smoothed_hit_rate)
        message = (
            f"local recycle stats pool={len(self._local_recycled_item_ids)} "
            f"hits={self._local_recycle_hits} misses={self._local_recycle_misses} "
            f"drops={self._local_recycle_drops} hit_rate={raw_hit_rate:.1f}% ema={smoothed_hit_rate:.1f}%"
        )
        logger.debug(message, "ModManagement")

    def _auto_tune_local_recycle_pool(self, hit_rate: float) -> None:
        """依命中率自動微調 local recycle pool 上限。"""
        current = max(1, int(getattr(self, "_local_recycle_pool_max", 500)))
        min_size = max(1, int(getattr(self, "_local_recycle_pool_min", 250)))
        cap_size = max(min_size, int(getattr(self, "_local_recycle_pool_cap", 1600)))
        step = max(1, int(getattr(self, "_local_recycle_tune_step", 80)))
        pool_len = len(self._local_recycled_item_ids)
        tune_args = {
            "current": current,
            "min_size": min_size,
            "cap_size": cap_size,
            "step": step,
            "pool_len": pool_len,
            "hit_rate": hit_rate,
        }
        new_size = compute_adaptive_pool_limit(**tune_args)
        if new_size == current:
            return

        self._local_recycle_pool_max = new_size
        logger.debug(
            f"自動調整 local recycle pool 上限: {current} -> {new_size} (hit_rate={hit_rate:.1f}%)",
            "ModManagement",
        )

    def _set_local_tree_render_lock(self, locked: bool) -> None:
        """大量刷新前後鎖住 Treeview 父容器幾何，減少 layout 抖動。"""
        if not self.local_tree:
            return

        parent = self.local_tree.master
        if locked:
            if getattr(self, "_local_tree_render_locked", False):
                return
            try:
                parent.grid_propagate(False)
                self._local_tree_render_locked = True
            except Exception as e:
                logger.debug(f"鎖定 local tree 渲染失敗: {e}", "ModManagement")
            return

        if not getattr(self, "_local_tree_render_locked", False):
            return
        try:
            parent.grid_propagate(True)
        except Exception as e:
            logger.debug(f"解除 local tree 渲染鎖失敗: {e}", "ModManagement")
        finally:
            self._local_tree_render_locked = False

    def _get_local_insert_batch_size(self, pending_count: int) -> int:
        """依待插入筆數動態計算 local list 批次大小。"""
        if pending_count <= 0:
            return 1
        base = max(1, int(getattr(self, "_local_insert_batch_base", 60)))
        max_size = max(base, int(getattr(self, "_local_insert_batch_max", 180)))
        divisor = max(1, int(getattr(self, "_local_insert_batch_divisor", 8)))
        dynamic_size = max(base, pending_count // divisor)
        dynamic_size = min(dynamic_size, max_size)
        return min(dynamic_size, pending_count)

    def _capture_selected_mod_ids(self) -> set[str]:
        """擷取目前選取列對應的 mod id（Treeview tag[0]）。"""
        if not self.local_tree:
            return set()

        selected_mod_ids: set[str] = set()
        for item_id in self.local_tree.selection():
            tags = self.local_tree.item(item_id, "tags")
            if tags:
                selected_mod_ids.add(str(tags[0]))
        return selected_mod_ids

    def _restore_local_selection(self, selected_mod_ids: set[str]) -> None:
        """刷新後回復多選狀態。"""
        if not self.local_tree:
            return

        selected_items = [
            item_id for mod_id in selected_mod_ids for item_id in [self._local_item_by_mod_id.get(mod_id)] if item_id
        ]
        if selected_items:
            with contextlib.suppress(Exception):
                self.local_tree.selection_set(selected_items)
                self.local_tree.see(selected_items[0])

    def _finalize_local_refresh(
        self,
        *,
        refresh_token: int,
        rows_snapshot: dict[str, tuple[tuple[Any, ...], tuple[str, ...]]],
        selected_mod_ids: set[str],
    ) -> None:
        """刷新收尾：只接受最新 token，避免舊任務覆蓋。"""
        if refresh_token != self._local_refresh_token:
            return
        self._local_refresh_job = None
        self._local_rows_snapshot = rows_snapshot
        self._restore_local_selection(selected_mod_ids)
        self.on_tree_selection_changed()
        self._set_local_tree_render_lock(False)

    def _apply_local_tree_diff(
        self,
        *,
        mod_order: list[str],
        mod_rows: dict[str, tuple[tuple[Any, ...], tuple[str, ...]]],
        refresh_token: int,
        selected_mod_ids: set[str],
    ) -> None:
        """以差異更新本地模組 Treeview，避免整棵重建。"""
        tree = self.local_tree
        if not tree or not tree.winfo_exists():
            self._set_local_tree_render_lock(False)
            return

        # 先刪除不存在的 row
        for mod_id, stale_item_id in list(self._local_item_by_mod_id.items()):
            if mod_id in mod_rows:
                continue
            self._recycle_local_item(stale_item_id)
            self._local_item_by_mod_id.pop(mod_id, None)

        rows_snapshot: dict[str, tuple[tuple[Any, ...], tuple[str, ...]]] = {}
        pending_insert: list[tuple[str, tuple[Any, ...], tuple[str, ...]]] = []
        previous_snapshot = getattr(self, "_local_rows_snapshot", {})

        for mod_id in mod_order:
            values, tags = mod_rows[mod_id]
            item_id = self._local_item_by_mod_id.get(mod_id)
            if item_id:
                try:
                    if previous_snapshot.get(mod_id) != (values, tags):
                        tree.item(item_id, values=values, tags=tags)
                    rows_snapshot[mod_id] = (values, tags)
                    continue
                except Exception as e:
                    logger.debug(f"更新 local row 失敗 mod_id={mod_id}: {e}", "ModManagement")
                    self._recycle_local_item(item_id)
                    self._local_item_by_mod_id.pop(mod_id, None)
            pending_insert.append((mod_id, values, tags))

        if not mod_order:
            self._local_item_by_mod_id.clear()
            self._finalize_local_refresh(
                refresh_token=refresh_token,
                rows_snapshot={},
                selected_mod_ids=set(),
            )
            return

        batch_size = self._get_local_insert_batch_size(len(pending_insert))

        def insert_batch(start_index: int, current_job_id: str | None = None) -> None:
            if current_job_id and self._local_refresh_job == current_job_id:
                self._local_refresh_job = None
            if refresh_token != self._local_refresh_token:
                if current_job_id and self._local_refresh_job == current_job_id:
                    self._local_refresh_job = None
                return
            if not self.local_tree or not self.local_tree.winfo_exists():
                if current_job_id and self._local_refresh_job == current_job_id:
                    self._local_refresh_job = None
                return

            try:
                end_index = min(start_index + batch_size, len(pending_insert))
                for idx in range(start_index, end_index):
                    mod_id, values, tags = pending_insert[idx]
                    recycled_item_id = self._acquire_recycled_local_item()
                    if recycled_item_id:
                        self.local_tree.item(recycled_item_id, values=values, tags=tags)
                        self.local_tree.reattach(recycled_item_id, "", "end")
                        inserted_item_id = recycled_item_id
                    else:
                        inserted_item_id = self.local_tree.insert("", "end", values=values, tags=tags)
                    self._local_item_by_mod_id[mod_id] = inserted_item_id
                    rows_snapshot[mod_id] = (values, tags)

                if end_index < len(pending_insert):
                    next_job_id: str | None = None

                    def _run_next() -> None:
                        insert_batch(end_index, current_job_id=next_job_id)

                    next_job_id = self.local_tree.after(1, _run_next)
                    self._local_refresh_job = next_job_id
                    return

                for order_index, mod_id in enumerate(mod_order):
                    item_id = self._local_item_by_mod_id.get(mod_id)
                    if item_id:
                        self.local_tree.move(item_id, "", order_index)
                        if mod_id not in rows_snapshot:
                            rows_snapshot[mod_id] = mod_rows[mod_id]

                self._finalize_local_refresh(
                    refresh_token=refresh_token,
                    rows_snapshot=rows_snapshot,
                    selected_mod_ids=selected_mod_ids,
                )
            except Exception as e:
                logger.debug(f"差異插入 local mods 批次失敗: {e}", "ModManagement")
                self._local_refresh_job = None
                self._set_local_tree_render_lock(False)

        if pending_insert:
            insert_batch(0)
            return

        try:
            for order_index, mod_id in enumerate(mod_order):
                item_id = self._local_item_by_mod_id.get(mod_id)
                if item_id:
                    tree.move(item_id, "", order_index)
                    rows_snapshot[mod_id] = mod_rows[mod_id]
        except Exception as e:
            logger.debug(f"重排 local mods 失敗: {e}", "ModManagement")

        self._finalize_local_refresh(
            refresh_token=refresh_token,
            rows_snapshot=rows_snapshot,
            selected_mod_ids=selected_mod_ids,
        )

    def refresh_local_list(self) -> None:
        """重新整理本地模組列表（差異更新，避免整棵重建）。"""
        if not hasattr(self, "local_tree") or not self.local_tree:
            return

        self._cancel_local_refresh_job()
        self._local_refresh_token += 1
        refresh_token = self._local_refresh_token
        selected_mod_ids = self._capture_selected_mod_ids()

        # 鎖住幾何，避免刷新期間多次 re-layout
        self._set_local_tree_render_lock(True)

        # 準備資料
        search_text = self.local_search_var.get().lower() if hasattr(self, "local_search_var") else ""
        filter_status = self.local_filter_var.get() if hasattr(self, "local_filter_var") else "所有"
        # 使用預編譯的正則表達式（效能優化）
        version_pattern = self.VERSION_PATTERN

        mod_order: list[str] = []
        mod_rows: dict[str, tuple[tuple[Any, ...], tuple[str, ...]]] = {}

        for mod in self.local_mods:
            # 應用篩選 Apply filters
            mod_name_lower = str(getattr(mod, "name", "") or "").lower()
            if search_text and search_text not in mod_name_lower:
                continue
            if filter_status != "所有" and (
                (filter_status == "啟用" and mod.status != ModStatus.ENABLED)
                or (filter_status == "停用" and mod.status != ModStatus.DISABLED)
            ):
                continue

            # 獲取增強資訊 Get enhanced info
            enhanced = self.enhanced_mods_cache.get(mod.filename)

            # 解析版本 Parse version
            parsed_version = "未知"
            m = version_pattern.search(mod.filename)
            if m:
                parsed_version = m.group(1)

            # 使用輔助方法取得增強屬性（效能優化：減少 hasattr 呼叫）
            display_name = self._get_enhanced_attr(enhanced, "name", mod.name)
            display_author = self._get_enhanced_attr(enhanced, "author", mod.author or "Unknown")

            # 版本顯示優先順序 Version display priority
            if mod.version and mod.version not in ("", "未知"):
                display_version = mod.version
            elif enhanced:
                enhanced_version = getattr(enhanced, "version", None)
                enhanced_versions = getattr(enhanced, "versions", None)
                if enhanced_version:
                    display_version = enhanced_version
                elif enhanced_versions:
                    display_version = (
                        enhanced_versions[0]
                        if isinstance(enhanced_versions, list) and enhanced_versions
                        else str(enhanced_versions)
                    )
                elif parsed_version and parsed_version not in ("", "未知"):
                    display_version = parsed_version
                else:
                    display_version = "未知"
            elif parsed_version and parsed_version not in ("", "未知"):
                display_version = parsed_version
            else:
                display_version = "未知"

            display_description = self._get_enhanced_attr(enhanced, "description", mod.description or "")

            status_text = "✅ 已啟用" if mod.status == ModStatus.ENABLED else "❌ 已停用"
            mod_base_name = mod.filename.replace(".jar.disabled", "").replace(".jar", "")

            # 檔案大小顯示 File size display
            size_val = getattr(mod, "file_size", 0)
            if size_val >= 1024 * 1024:
                display_size = f"{size_val / 1024 / 1024:.1f} MB"
            elif size_val >= 1024:
                display_size = f"{size_val / 1024:.1f} KB"
            else:
                display_size = f"{size_val} B"

            # 修改時間顯示 Modification time display
            mtime_val = getattr(mod, "_cached_mtime", None)
            if mtime_val is None:
                try:
                    mtime_val = Path(mod.file_path).stat().st_mtime
                    mod._cached_mtime = mtime_val
                except Exception:
                    mtime_val = None

            display_mtime = datetime.fromtimestamp(mtime_val).strftime("%Y-%m-%d %H:%M") if mtime_val else "未知"
            parity_tag = "odd" if len(mod_order) % 2 == 0 else "even"
            values: tuple[Any, ...] = (
                status_text,
                display_name,
                display_version,
                display_author,
                mod.loader_type,
                display_size,
                display_mtime,
                (display_description[:50] + "..." if len(display_description) > 50 else display_description),
            )
            tags = (mod_base_name, parity_tag)
            mod_order.append(mod_base_name)
            mod_rows[mod_base_name] = (values, tags)

        self._apply_local_tree_diff(
            mod_order=mod_order,
            mod_rows=mod_rows,
            refresh_token=refresh_token,
            selected_mod_ids=selected_mod_ids,
        )

    def _set_bulk_controls_enabled(self, enabled: bool) -> None:
        """設定批量操作控制元件的啟用/停用狀態

        Args:
            enabled: True 表示啟用，False 表示停用
        """
        state = "normal" if enabled else "disabled"
        try:
            if hasattr(self, "select_all_btn") and self.select_all_btn:
                self.select_all_btn.configure(state=state)
        except Exception as e:
            logger.debug(f"設定全選按鈕狀態失敗: {e}", "ModManagement")
        try:
            if hasattr(self, "batch_toggle_btn") and self.batch_toggle_btn:
                self.batch_toggle_btn.configure(state=state)
        except Exception as e:
            logger.debug(f"設定批量切換按鈕狀態失敗: {e}", "ModManagement")

    def toggle_local_mod(self, _event=None) -> None:
        """雙擊切換本地模組啟用/停用狀態 - 參考 Prism Launcher"""
        if not self.local_tree:
            return

        selection = self.local_tree.selection()
        if not selection:
            return

        # 獲取選中的項目
        item = selection[0]
        values = self.local_tree.item(item, "values")

        if not values or len(values) < 2:
            return

        mod_name = values[1]  # 模組名稱在第二欄

        if not self.mod_manager:
            UIUtils.show_error("錯誤", "模組管理器未初始化", self.parent)
            return

        try:
            # 優先使用 tags 中的 base_name
            tags = self.local_tree.item(item, "tags")
            mod_id = tags[0] if tags and len(tags) > 0 else None
            if not mod_id:
                if hasattr(self, "status_label") and self.status_label.winfo_exists():
                    self.update_status(f"無法識別模組: {mod_name}")
                return

            # 快速路徑：用已載入的 local_mods 定位，不再每次 scan_mods
            mods_by_base_name: dict[str, Any] = {}
            for m in getattr(self, "local_mods", []) or []:
                base_name = m.filename.replace(".jar.disabled", "").replace(".jar", "")
                existing = mods_by_base_name.get(base_name)
                if existing is None or m.status == ModStatus.ENABLED:
                    mods_by_base_name[base_name] = m

            found_mod = mods_by_base_name.get(mod_id)
            if not found_mod:
                if hasattr(self, "status_label") and self.status_label.winfo_exists():
                    self.update_status(f"找不到模組檔案: {mod_id}")
                return

            manager = self.mod_manager
            tree = self.local_tree

            # 切換狀態（背景執行 rename），成功後僅更新該列顯示
            def do_toggle() -> None:
                self.ui_queue.put(lambda: self._set_bulk_controls_enabled(False))
                if not manager:
                    return

                old_filename = found_mod.filename
                old_file_path = getattr(found_mod, "file_path", "")
                action = "停用" if found_mod.status == ModStatus.ENABLED else "啟用"
                if found_mod.status == ModStatus.ENABLED:
                    ok = manager.set_mod_state(mod_id, False)
                    new_status = ModStatus.DISABLED
                    new_filename = f"{mod_id}.jar.disabled"
                else:
                    ok = manager.set_mod_state(mod_id, True)
                    new_status = ModStatus.ENABLED
                    new_filename = f"{mod_id}.jar"

                def apply_ui_update() -> None:
                    try:
                        if ok:
                            found_mod.status = new_status
                            found_mod.filename = new_filename
                            if old_file_path:
                                found_mod.file_path = old_file_path.replace(old_filename, new_filename)
                            try:
                                found_mod._cached_mtime = Path(found_mod.file_path).stat().st_mtime
                            except Exception:
                                found_mod._cached_mtime = None

                            # 移動 enhanced cache key，避免切換後顯示資訊消失
                            if (
                                hasattr(self, "enhanced_mods_cache")
                                and isinstance(self.enhanced_mods_cache, dict)
                                and old_filename in self.enhanced_mods_cache
                                and new_filename not in self.enhanced_mods_cache
                            ):
                                self.enhanced_mods_cache[new_filename] = self.enhanced_mods_cache[old_filename]

                            # 更新該列的 status 與 mtime（其他欄位保持不動）
                            if not tree or not tree.winfo_exists():
                                return

                            row_values = list(tree.item(item, "values") or [])
                            if row_values:
                                row_values[0] = "✅ 已啟用" if new_status == ModStatus.ENABLED else "❌ 已停用"
                                mtime_val = getattr(found_mod, "_cached_mtime", None)
                                row_values[6] = (
                                    datetime.fromtimestamp(mtime_val).strftime("%Y-%m-%d %H:%M")
                                    if mtime_val
                                    else "未知"
                                )
                                tree.item(item, values=tuple(row_values), tags=(mod_id,))

                            if hasattr(self, "status_label") and self.status_label.winfo_exists():
                                self.update_status(f"已{action}模組: {mod_name}")
                        elif hasattr(self, "status_label") and self.status_label.winfo_exists():
                            self.update_status(f"{action}模組失敗: {mod_name}")
                    finally:
                        self._set_bulk_controls_enabled(True)
                        self.update_selection_status()

                self.ui_queue.put(apply_ui_update)

            UIUtils.run_async(do_toggle)

        except Exception as e:
            if hasattr(self, "status_label") and self.status_label.winfo_exists():
                self.update_status(f"操作失敗: {e}")
            logger.error(f"切換模組狀態錯誤: {e}\n{traceback.format_exc()}")

    def filter_local_mods(self, *_args) -> None:
        """篩選本地模組（debounce，避免連續重建 Treeview）。"""
        UIUtils.schedule_debounce(
            self.parent,
            "_local_filter_job",
            120,
            self._run_debounced_local_filter_refresh,
            owner=self,
        )

    def _run_debounced_local_filter_refresh(self) -> None:
        self._local_filter_job = None
        self.refresh_local_list()

    def show_local_context_menu(self, event) -> None:
        """顯示本地模組右鍵選單"""
        if not self.local_tree:
            return

        tree = self.local_tree
        selection = tree.selection()
        if not selection:
            return

        menu = tk.Menu(
            self.parent,
            tearoff=0,
            font=FontManager.get_font("Microsoft JhengHei", FontSize.LARGE),
        )
        menu.add_command(label="🔄 切換啟用狀態", command=self.toggle_local_mod)
        menu.add_separator()
        menu.add_command(label="📋 複製模組資訊", command=self.copy_mod_info)
        menu.add_command(label="📁 在檔案總管中顯示", command=self.show_in_explorer)
        menu.add_separator()
        menu.add_command(label="🗑️ 刪除模組", command=self.delete_local_mod)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def import_mod_file(self) -> None:
        """匯入模組檔案"""
        if not self.current_server:
            UIUtils.show_warning("警告", "請先選擇伺服器", self.parent)
            return

        filetypes = [("JAR files", "*.jar"), ("All files", "*.*")]
        filename = filedialog.askopenfilename(filetypes=filetypes)

        if filename:
            try:
                mods_dir = Path(self.current_server.path) / "mods"
                mods_dir.mkdir(exist_ok=True)

                target_path = mods_dir / Path(filename).name
                # 複製檔案（修正：之前缺少實際複製檔案的操作）
                PathUtils.copy_file(Path(filename), target_path)
                UIUtils.show_info("成功", f"模組已匯入: {Path(filename).name}", self.parent)
                self.load_local_mods()

            except Exception as e:
                logger.error(f"匯入模組失敗: {e}\n{traceback.format_exc()}")
                UIUtils.show_error("錯誤", f"匯入模組失敗: {e}", self.parent)

    def open_mods_folder(self) -> None:
        """開啟模組資料夾"""
        if not self.current_server:
            UIUtils.show_warning("警告", "請先選擇伺服器", self.parent)
            return

        mods_dir = Path(self.current_server.path) / "mods"
        if mods_dir.exists():
            try:
                UIUtils.open_external(mods_dir)
            except Exception as e:
                logger.error(f"開啟模組資料夾失敗: {e}")
        else:
            UIUtils.show_warning("警告", "模組資料夾不存在", self.parent)

    def copy_mod_info(self) -> None:
        """複製模組資訊"""
        if not self.local_tree:
            return

        tree = self.local_tree
        selection = tree.selection()
        if not selection:
            return

        try:
            item = selection[0]
            values = tree.item(item, "values")

            if values and len(values) >= 4:
                info = f"模組名稱: {values[1]}\n版本: {values[2]}\n狀態: {values[0]}\n檔案: {values[3] if len(values) > 3 else 'N/A'}"

                # 複製到剪貼板
                self.parent.clipboard_clear()
                self.parent.clipboard_append(info)
                if hasattr(self, "status_label") and self.status_label.winfo_exists():
                    self.update_status("模組資訊已複製到剪貼板")
        except Exception as e:
            logger.error(f"複製模組資訊失敗: {e}\n{traceback.format_exc()}")
            if hasattr(self, "status_label") and self.status_label.winfo_exists():
                self.status_label.configure(text=f"複製失敗: {e}")

    def show_in_explorer(self) -> None:
        """在檔案總管中顯示模組"""
        if not self.local_tree:
            return

        tree = self.local_tree
        selection = tree.selection()
        if not selection or not self.current_server:
            return

        try:
            item = selection[0]
            tags = tree.item(item, "tags")

            if tags and len(tags) > 0:
                mod_filename = tags[0]
                mods_dir = Path(self.current_server.path) / "mods"

                # 尋找實際檔案
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

                    if hasattr(self, "status_label") and self.status_label.winfo_exists():
                        self.status_label.configure(text=f"已在檔案總管中顯示: {mod_file.name}")
                elif hasattr(self, "status_label") and self.status_label.winfo_exists():
                    self.status_label.configure(text="找不到要顯示的模組檔案")
            elif hasattr(self, "status_label") and self.status_label.winfo_exists():
                self.status_label.configure(text="無法識別模組檔案")

        except Exception as e:
            logger.error(f"開啟檔案總管失敗: {e}\n{traceback.format_exc()}")
            if hasattr(self, "status_label") and self.status_label.winfo_exists():
                self.status_label.configure(text=f"開啟檔案總管失敗: {e}")

    def delete_local_mod(self) -> None:
        if not self.local_tree:
            return

        tree = self.local_tree
        selection = tree.selection()
        if not selection or not self.current_server:
            return

        try:
            item = selection[0]
            values = tree.item(item, "values")
            tags = tree.item(item, "tags")

            if not values or len(values) < 2:
                return

            mod_name = values[1]

            # 確認刪除
            result = UIUtils.ask_yes_no_cancel(
                "確認刪除",
                f"確定要刪除模組 '{mod_name}' 嗎？\n此操作無法復原。",
                parent=self.parent,
                show_cancel=False,
            )

            if not result:
                return

            if tags and len(tags) > 0:
                mod_filename = tags[0]
                mods_dir = Path(self.current_server.path) / "mods"

                # 尋找並刪除實際檔案
                deleted = False
                for ext in [".jar", ".jar.disabled"]:
                    mod_file = mods_dir / (mod_filename + ext)
                    if mod_file.exists():
                        mod_file.unlink()  # 刪除檔案
                        deleted = True
                        break

                if deleted:
                    # 重新載入和刷新模組列表
                    self.load_local_mods()
                    if hasattr(self, "status_label") and self.status_label.winfo_exists():
                        self.status_label.configure(text=f"已刪除模組: {mod_name}")
                    UIUtils.show_info("成功", f"模組 '{mod_name}' 已刪除", self.parent)
                elif hasattr(self, "status_label") and self.status_label.winfo_exists():
                    self.status_label.configure(text="刪除失敗")
            elif hasattr(self, "status_label") and self.status_label.winfo_exists():
                self.status_label.configure(text="無法識別要刪除的模組")

        except Exception as e:
            logger.error(f"刪除模組失敗: {e}\n{traceback.format_exc()}")
            if hasattr(self, "status_label") and self.status_label.winfo_exists():
                self.status_label.configure(text=f"刪除失敗: {e}")
            UIUtils.show_error("錯誤", f"刪除模組失敗: {e}", self.parent)

    def get_frame(self) -> ctk.CTkFrame | None:
        """獲取主框架"""
        if hasattr(self, "main_frame") and self.main_frame:
            return self.main_frame
        logger.debug("主框架未初始化")
        return None

    def toggle_select_all(self) -> None:
        """切換全選/取消全選"""
        try:
            if not self.local_tree:
                return

            items = self.local_tree.get_children()
            if not items:
                return

            if self.all_selected:
                # 取消全選
                self.local_tree.selection_remove(*items)
                self.selected_mods.clear()
                self.all_selected = False
                try:
                    # 嘗試更新按鈕文字，考慮到可能有圖片
                    if hasattr(self.select_all_btn, "configure"):
                        self.select_all_btn.configure(text="☑️ 全選")
                except Exception as e:
                    logger.exception(f"更新全選按鈕文字失敗: {e}")
            else:
                # 全選
                self.local_tree.selection_set(*items)
                # 更新選中的模組集合
                self.selected_mods.clear()
                for item in items:
                    values = self.local_tree.item(item, "values")
                    if values and len(values) >= 2:
                        mod_name = values[1]  # 模組名稱
                        self.selected_mods.add(mod_name)

                self.all_selected = True
                try:
                    # 嘗試更新按鈕文字，考慮到可能有圖片
                    if hasattr(self.select_all_btn, "configure"):
                        self.select_all_btn.configure(text="❌ 取消全選")
                except Exception as e:
                    logger.exception(f"更新全選按鈕文字失敗: {e}")
            # 更新狀態顯示
            self.update_selection_status()

        except Exception as e:
            logger.error(f"切換全選失敗: {e}\n{traceback.format_exc()}")

    def batch_toggle_selected(self) -> None:
        """批量切換選中模組的啟用/停用狀態"""
        try:
            if not self.mod_manager:
                UIUtils.show_error("錯誤", "模組管理器未初始化", self.parent)
                return
            if not self.local_tree:
                return

            selected_items = self.local_tree.selection()
            if not selected_items:
                UIUtils.show_warning("提示", "請先選擇要操作的模組", self.parent)
                return

            # 用已載入的 local_mods 建索引，避免在主執行緒反覆 scan_mods 造成 UI 凍結
            mods_by_base_name: dict[str, Any] = {}
            for mod in getattr(self, "local_mods", []) or []:
                base_name = mod.filename.replace(".jar.disabled", "").replace(".jar", "")
                existing = mods_by_base_name.get(base_name)
                if existing is None or mod.status == ModStatus.ENABLED:
                    mods_by_base_name[base_name] = mod

            selected_pairs = []  # (base_name, tree_item_id)
            seen = set()
            for tree_item_id in selected_items:
                tags = self.local_tree.item(tree_item_id, "tags")
                if tags and len(tags) > 0:
                    base_name = tags[0]
                    if base_name and base_name not in seen:
                        seen.add(base_name)
                        selected_pairs.append((base_name, tree_item_id))

            selected_pairs = [(b, tid) for (b, tid) in selected_pairs if b in mods_by_base_name]
            if not selected_pairs:
                UIUtils.show_warning("提示", "找不到對應的模組檔案", self.parent)
                return

            manager = self.mod_manager

            def do_batch():
                total = len(selected_pairs)
                success_count = 0
                last_percent: float = -1

                self.ui_queue.put(lambda: self._set_bulk_controls_enabled(False))
                self.update_status_safe(f"正在批量切換 {total} 個模組狀態...")

                for idx, (base_name, tree_item_id) in enumerate(selected_pairs, start=1):
                    mod = mods_by_base_name.get(base_name)
                    if not mod:
                        continue

                    old_filename = getattr(mod, "filename", "")
                    old_file_path = getattr(mod, "file_path", "")

                    if mod.status == ModStatus.ENABLED:
                        ok = manager.set_mod_state(base_name, False)
                        new_status = ModStatus.DISABLED
                        new_filename = f"{base_name}.jar.disabled"
                        action = "停用"
                    else:
                        ok = manager.set_mod_state(base_name, True)
                        new_status = ModStatus.ENABLED
                        new_filename = f"{base_name}.jar"
                        action = "啟用"

                    if ok:
                        success_count += 1

                        # 更新記憶體中的 mod 物件與 cache（不做全量重掃）
                        mod.status = new_status
                        mod.filename = new_filename
                        if old_file_path:
                            try:
                                mod.file_path = str(Path(old_file_path).with_name(new_filename))
                            except Exception:
                                mod.file_path = old_file_path.replace(old_filename, new_filename)
                        try:
                            mod._cached_mtime = Path(mod.file_path).stat().st_mtime
                        except Exception:
                            mod._cached_mtime = None

                        if (
                            hasattr(self, "enhanced_mods_cache")
                            and isinstance(self.enhanced_mods_cache, dict)
                            and old_filename in self.enhanced_mods_cache
                            and new_filename not in self.enhanced_mods_cache
                        ):
                            self.enhanced_mods_cache[new_filename] = self.enhanced_mods_cache[old_filename]

                        # 局部更新該列（狀態/mtime），避免整頁重繪
                        def apply_row_update(
                            item_id=tree_item_id,
                            status=new_status,
                            mod_obj=mod,
                            mod_id=base_name,
                        ) -> None:
                            try:
                                if not (
                                    hasattr(self, "local_tree") and self.local_tree and self.local_tree.winfo_exists()
                                ):
                                    return
                                row_values = list(self.local_tree.item(item_id, "values") or [])
                                if row_values:
                                    row_values[0] = "✅ 已啟用" if status == ModStatus.ENABLED else "❌ 已停用"
                                    mtime_val = getattr(mod_obj, "_cached_mtime", None)
                                    row_values[6] = (
                                        datetime.fromtimestamp(mtime_val).strftime("%Y-%m-%d %H:%M")
                                        if mtime_val
                                        else "未知"
                                    )
                                    self.local_tree.item(
                                        item_id,
                                        values=tuple(row_values),
                                        tags=(mod_id,),
                                    )
                            except Exception as e:
                                # 批量過程中 UI 更新失敗不阻塞主流程
                                logger.debug(f"批量更新 UI row 失敗: {e}", "ModManagement")

                        self.ui_queue.put(apply_row_update)
                    else:
                        # 失敗就只更新狀態列（不彈窗、不重掃）
                        self.update_status_safe(f"{action}模組失敗: {base_name}")

                    percent = (idx / total) * 100 if total else 0
                    # 保留進度條行為，但節流 UI 更新頻率
                    if int(percent) != int(last_percent):
                        last_percent = percent
                        self.update_progress_safe(percent)

                # Reset progress + final status (保留原本進度條收尾動作)
                self.update_progress_safe(0)
                self.update_status_safe(f"已切換 {success_count}/{total} 個模組狀態")
                self.ui_queue.put(self.update_selection_status)
                self.ui_queue.put(lambda: self._set_bulk_controls_enabled(True))

            UIUtils.run_async(do_batch)
        except Exception as e:
            logger.error(f"批量操作失敗: {e}\n{traceback.format_exc()}")
            self.update_progress_safe(0)
            UIUtils.show_error("錯誤", f"批量操作失敗: {e}", self.parent)

    def update_selection_status(self) -> None:
        """更新選擇狀態顯示"""
        if not self.local_tree:
            return

        try:
            selected_count = len(self.local_tree.selection())
            total_count = len(self.local_tree.get_children())

            if selected_count > 0:
                status_text = f"已選擇 {selected_count}/{total_count} 個模組"
            else:
                status_text = f"找到 {total_count} 個模組"

            if hasattr(self, "status_label"):
                self.status_label.configure(text=status_text)

        except Exception as e:
            logger.error(f"更新選擇狀態失敗: {e}\n{traceback.format_exc()}")

    def on_tree_selection_changed(self, _event=None) -> None:
        """樹狀檢視選擇變化事件"""
        if not self.local_tree:
            return

        try:
            # 更新選擇狀態
            self.update_selection_status()

            # 更新選中的模組集合
            self.selected_mods.clear()
            selected_items = self.local_tree.selection()

            for item in selected_items:
                values = self.local_tree.item(item, "values")
                if values and len(values) >= 2:
                    mod_name = values[1]
                    self.selected_mods.add(mod_name)

            # 更新全選按鈕狀態
            total_items = len(self.local_tree.get_children())
            selected_items_count = len(selected_items)

            if selected_items_count == 0:
                self.all_selected = False
                try:
                    if hasattr(self.select_all_btn, "configure"):
                        self.select_all_btn.configure(text="☑️ 全選")
                except Exception as e:
                    logger.exception(f"更新全選按鈕文字失敗: {e}")
            elif selected_items_count == total_items:
                self.all_selected = True
                try:
                    if hasattr(self.select_all_btn, "configure"):
                        self.select_all_btn.configure(text="❌ 取消全選")
                except Exception as e:
                    logger.exception(f"更新全選按鈕文字失敗: {e}")

        except Exception as e:
            logger.error(f"處理選擇變化失敗: {e}\n{traceback.format_exc()}")

    def pack(self, **kwargs) -> None:
        """讓框架可以被 pack"""
        if hasattr(self, "main_frame") and self.main_frame:
            self.main_frame.pack(**kwargs)
        else:
            logger.debug("主框架未初始化，無法打包", "ModManagementFrame")

    def grid(self, **kwargs) -> None:
        """讓框架可以被 grid"""
        if hasattr(self, "main_frame") and self.main_frame:
            self.main_frame.grid(**kwargs)
        else:
            logger.debug("主框架未初始化，無法佈局", "ModManagementFrame")
