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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from types import SimpleNamespace
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
from . import (
    CustomDropdown,
    LocalModUpdatePlan,
    analyze_mod_version_compatibility,
    build_local_mod_update_plan,
    build_required_dependency_install_plan,
    enhance_local_mod,
    get_mod_versions,
    resolve_modrinth_project_names,
    search_mods_online,
)

logger = get_logger().bind(component="ModManagement")

SUPPORTED_ONLINE_MOD_LOADERS = {"fabric", "forge"}
MODRINTH_PROJECT_PAGE_BASE_URL = "https://modrinth.com/mod"
ONLINE_CATEGORY_OPTIONS: dict[str, list[str]] = {
    "全部分類": [],
    "效能優化": ["optimization"],
    "API / Library": ["library"],
    "世界生成": ["worldgen"],
    "冒險內容": ["adventure"],
    "裝飾建築": ["decoration"],
    "紅石與科技": ["technology"],
    "工具與實用": ["utility"],
    "交通移動": ["transportation"],
    "儲存整理": ["storage"],
    "魔法內容": ["magic"],
}


@dataclass(slots=True)
class PendingOnlineInstall:
    """待安裝的線上模組項目。"""

    project_id: str
    project_name: str
    version: Any
    report: Any | None = None
    homepage_url: str = ""
    source_url: str = ""
    server_side: str = ""
    client_side: str = ""


@dataclass(slots=True)
class PendingInstallReviewEntry:
    """待安裝項目的最終驗證結果。"""

    pending: PendingOnlineInstall
    report: Any | None
    dependency_plan: Any
    blocking_reasons: list[str] = field(default_factory=list)
    warning_messages: list[str] = field(default_factory=list)
    enabled: bool = True
    provider: str = "modrinth"
    version_type: str = ""
    date_published: str = ""
    changelog: str = ""

    @property
    def actionable(self) -> bool:
        return self.enabled and not self.blocking_reasons

    @property
    def runnable(self) -> bool:
        return not self.blocking_reasons


@dataclass(slots=True)
class LocalUpdateReviewEntry:
    """本地模組更新 review 項目。"""

    candidate: Any
    dependency_plan: Any
    blocking_reasons: list[str] = field(default_factory=list)
    enabled: bool = True
    provider: str = "modrinth"
    version_type: str = ""
    date_published: str = ""
    changelog: str = ""

    @property
    def actionable(self) -> bool:
        return self.enabled and bool(getattr(self.candidate, "actionable", False)) and not self.blocking_reasons

    @property
    def runnable(self) -> bool:
        return bool(getattr(self.candidate, "actionable", False)) and not self.blocking_reasons


@dataclass(slots=True)
class ReviewTaskNode:
    """Review 對話框中的共用 task 節點。"""

    node_id: str
    root_key: str
    group_key: str
    title: str
    values: tuple[str, ...]
    node_kind: str
    parent_id: str | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class OnlineBrowseRequest:
    """線上模組瀏覽/搜尋請求。"""

    query: str
    minecraft_version: str | None
    loader_type: str
    sort_by: str
    categories: tuple[str, ...] = ()

    @property
    def is_browse_mode(self) -> bool:
        return not bool(self.query)


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
        self.browse_tree: ttk.Treeview | None = None
        self.browse_filter_label: ctk.CTkLabel | None = None
        self.browse_results_label: ctk.CTkLabel | None = None

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
        self.online_mods: list[Any] = []
        self._online_mod_index: dict[str, Any] = {}
        self._last_online_request: OnlineBrowseRequest | None = None
        self.pending_online_installs: list[PendingOnlineInstall] = []
        self._latest_local_update_plan = LocalModUpdatePlan()
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

    @staticmethod
    def _get_local_row_palette(is_dark: bool) -> tuple[str, str]:
        """回傳本地模組列表交錯列配色。"""
        if is_dark:
            return Colors.BG_LISTBOX_DARK, Colors.BG_LISTBOX_ALT_DARK
        return Colors.BG_LISTBOX_LIGHT, Colors.BG_LISTBOX_ALT_LIGHT

    @staticmethod
    def _get_parity_tag(index: int) -> str:
        """依列索引回傳交錯底色 tag。"""
        return "odd" if index % 2 == 0 else "even"

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
            text="參考 Prism Launcher 的模組管理流程",
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
        """建立線上瀏覽頁面。"""
        if not self.notebook:
            return
        self.browse_tab = ctk.CTkFrame(self.notebook)
        self.notebook.add(self.browse_tab, text="🌐 瀏覽模組")
        self.create_browse_search()
        self.create_browse_mod_list()

    def create_browse_search(self) -> None:
        """建立線上搜尋區域。"""
        if not self.browse_tab:
            return

        search_frame = ctk.CTkFrame(self.browse_tab)
        search_frame.pack(fill="x", padx=14, pady=14)

        self.search_var = tk.StringVar()
        self.browse_sort_var = tk.StringVar(value="相關性")
        self.browse_category_var = tk.StringVar(value="全部分類")
        self.browse_sort_options = {
            "相關性": "relevance",
            "下載量": "downloads",
            "最新發布": "newest",
            "最近更新": "updated",
            "名稱": "name",
        }

        search_entry = ctk.CTkEntry(
            search_frame,
            textvariable=self.search_var,
            placeholder_text="留空可直接瀏覽，例如 sodium / lithium / worldedit",
            font=FontManager.get_font(size=FontSize.MEDIUM),
            width=FontManager.get_dpi_scaled_size(320),
            height=Sizes.INPUT_HEIGHT,
        )
        search_entry.pack(side="left", padx=(14, 10), pady=14)
        search_entry.bind("<Return>", self.search_online_mods)

        sort_dropdown = CustomDropdown(
            search_frame,
            variable=self.browse_sort_var,
            values=list(self.browse_sort_options.keys()),
            command=self.on_online_browse_filters_changed,
            width=Sizes.DROPDOWN_FILTER_WIDTH,
            height=Sizes.INPUT_HEIGHT,
        )
        sort_dropdown.pack(side="left", padx=(0, 10), pady=14)

        category_dropdown = CustomDropdown(
            search_frame,
            variable=self.browse_category_var,
            values=list(ONLINE_CATEGORY_OPTIONS.keys()),
            command=self.on_online_browse_filters_changed,
            width=FontManager.get_dpi_scaled_size(150),
            height=Sizes.INPUT_HEIGHT,
        )
        category_dropdown.pack(side="left", padx=(0, 10), pady=14)

        search_button = ctk.CTkButton(
            search_frame,
            text="🔍 搜尋 Modrinth",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.search_online_mods,
            fg_color=Colors.BUTTON_PRIMARY,
            hover_color=Colors.BUTTON_PRIMARY_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        search_button.pack(side="left", padx=(0, 10), pady=14)

        install_button = ctk.CTkButton(
            search_frame,
            text="➕ 加入安裝清單",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.install_online_mod,
            fg_color=Colors.BUTTON_SUCCESS,
            hover_color=Colors.BUTTON_SUCCESS_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        install_button.pack(side="left", pady=14)

        self.online_queue_button = ctk.CTkButton(
            search_frame,
            text="🧺 安裝清單 (0)",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            command=self.show_online_install_queue,
            fg_color=Colors.BUTTON_WARNING,
            hover_color=Colors.BUTTON_WARNING_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        self.online_queue_button.pack(side="left", padx=(10, 0), pady=14)

        self.browse_filter_label = ctk.CTkLabel(
            self.browse_tab,
            text="",
            font=FontManager.get_font(size=FontSize.SMALL_PLUS),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=FontManager.get_dpi_scaled_size(980),
        )
        self.browse_filter_label.pack(fill="x", padx=18, pady=(0, 4))

        self.browse_results_label = ctk.CTkLabel(
            self.browse_tab,
            text="",
            font=FontManager.get_font(size=FontSize.SMALL_PLUS),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=FontManager.get_dpi_scaled_size(980),
        )
        self.browse_results_label.pack(fill="x", padx=18, pady=(0, 6))
        self._refresh_online_filter_hint()
        self._refresh_online_results_summary()

    def create_browse_mod_list(self) -> None:
        """建立線上模組列表。"""
        if not self.browse_tab:
            return

        list_frame = ctk.CTkFrame(self.browse_tab)
        list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        tree_container = ctk.CTkFrame(list_frame)
        tree_container.pack(fill="both", expand=True, padx=10, pady=10)

        style = ttk.Style()
        style.configure(
            "BrowseModList.Treeview",
            font=FontManager.get_font(size=FontSize.INPUT),
            rowheight=int(26 * FontManager.get_scale_factor()),
        )
        style.configure(
            "BrowseModList.Treeview.Heading",
            font=FontManager.get_font(size=FontSize.HEADING_SMALL, weight="bold"),
        )

        columns = ("name", "author", "downloads", "description")
        self.browse_tree = ttk.Treeview(
            tree_container,
            columns=columns,
            show="headings",
            height=Sizes.TREEVIEW_VISIBLE_ROWS,
            style="BrowseModList.Treeview",
        )

        column_config = {
            "name": ("模組名稱", 220),
            "author": ("作者", 120),
            "downloads": ("下載數", 100),
            "description": ("描述", 650),
        }
        for col, (text, width) in column_config.items():
            self.browse_tree.heading(col, text=text, anchor="w")
            self.browse_tree.column(
                col,
                width=width,
                minwidth=60,
                anchor="w",
                stretch=(col == "description"),
            )

        v_scrollbar = ttk.Scrollbar(tree_container, orient="vertical", command=self.browse_tree.yview)
        h_scrollbar = ttk.Scrollbar(tree_container, orient="horizontal", command=self.browse_tree.xview)
        self.browse_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        self.browse_tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        UIUtils.bind_treeview_header_auto_fit(
            self.browse_tree,
            on_row_double_click=self.install_online_mod,
            heading_font=FontManager.get_font(size=FontSize.HEADING_SMALL, weight="bold"),
            body_font=FontManager.get_font(size=FontSize.INPUT),
            stretch_columns={"description"},
        )
        self.browse_tree.bind("<Button-3>", self.show_browse_context_menu)

    def _get_current_modrinth_context(self) -> tuple[str | None, str | None, str | None]:
        """依目前選取伺服器取得 Minecraft、loader 與 loader 版本資訊。"""
        if not self.current_server:
            return None, None, None

        minecraft_version = str(getattr(self.current_server, "minecraft_version", "") or "").strip() or None
        loader_type = str(getattr(self.current_server, "loader_type", "") or "").strip() or None
        loader_version = str(getattr(self.current_server, "loader_version", "") or "").strip() or None
        return minecraft_version, loader_type, loader_version

    def _get_current_modrinth_filters(self) -> tuple[str | None, str | None]:
        """依目前選取伺服器取得 Minecraft 版本與 loader 過濾條件。"""
        minecraft_version, loader_type, _ = self._get_current_modrinth_context()
        return minecraft_version, loader_type

    def _get_selected_online_categories(self) -> list[str]:
        if not hasattr(self, "browse_category_var"):
            return []
        selected_label = str(self.browse_category_var.get() or "全部分類").strip() or "全部分類"
        return list(ONLINE_CATEGORY_OPTIONS.get(selected_label, []))

    def _get_online_filter_hint_text(self) -> str:
        """建立線上模組瀏覽/搜尋提示文字。"""
        minecraft_version, loader_type, loader_version = self._get_current_modrinth_context()
        if not self.current_server:
            return "留空可直接瀏覽；僅支援 Fabric / Forge。"

        loader_display = loader_type or "未設定"
        info_parts = [f"MC {minecraft_version or '未設定'}", loader_display]
        if loader_version:
            info_parts.append(loader_version)

        hint = "條件：" + " / ".join(info_parts)
        if not loader_type or loader_type.lower() not in SUPPORTED_ONLINE_MOD_LOADERS:
            return hint + "｜僅支援 Fabric / Forge"
        return hint + "｜留空可直接瀏覽"

    def _get_online_version_dialog_hint_text(self) -> str:
        """建立版本選擇視窗的伺服器條件摘要。"""
        minecraft_version, loader_type, loader_version = self._get_current_modrinth_context()
        if not self.current_server:
            return "會依目前伺服器條件自動分析版本相容性。"

        loader_display = loader_type or "未設定"
        info_parts = [f"MC {minecraft_version or '未設定'}", loader_display]
        if loader_version:
            info_parts.append(loader_version)
        return "相容性條件：" + " / ".join(info_parts)

    def _refresh_online_filter_hint(self) -> None:
        """更新線上模組搜尋提示。"""
        if self.browse_filter_label:
            self.browse_filter_label.configure(text=self._get_online_filter_hint_text())

    def _get_online_sort_label(self) -> str:
        """取得目前線上瀏覽使用的排序顯示文字。"""
        if not hasattr(self, "browse_sort_var"):
            return "相關性"
        return str(self.browse_sort_var.get() or "相關性").strip() or "相關性"

    def _get_online_category_label(self) -> str:
        """取得目前線上瀏覽使用的分類顯示文字。"""
        if not hasattr(self, "browse_category_var"):
            return "全部分類"
        return str(self.browse_category_var.get() or "全部分類").strip() or "全部分類"

    def _format_online_result_description(self, mod: Any) -> str:
        """格式化瀏覽列表描述欄位。"""
        description = str(getattr(mod, "description", "") or "")
        if len(description) > 80:
            return description[:80] + "..."
        return description

    def _build_online_browse_row(self, mod: Any) -> tuple[str, str, str, str]:
        """建立線上瀏覽列表單列顯示內容。"""
        downloads = int(getattr(mod, "download_count", 0) or 0)
        return (
            str(getattr(mod, "name", "未知模組") or "未知模組"),
            str(getattr(mod, "author", "?") or "?"),
            f"{downloads:,}",
            self._format_online_result_description(mod),
        )

    def _build_online_results_summary_text(self) -> str:
        """建立瀏覽/搜尋結果摘要，說明目前條件與結果數量。"""
        query = self._get_online_query_text()
        mode_text = "瀏覽" if not query else f"搜尋 {query}"
        sort_text = self._get_online_sort_label()
        result_count = len(self.online_mods)
        return f"{mode_text}｜{result_count} 筆｜排序 {sort_text}"

    def _refresh_online_results_summary(self) -> None:
        """更新瀏覽結果摘要列。"""
        if self.browse_results_label:
            self.browse_results_label.configure(text=self._build_online_results_summary_text())

    def _clear_online_mods(self) -> None:
        """清空目前線上模組瀏覽結果。"""
        self.online_mods = []
        self._online_mod_index = {}
        self._last_online_request = None
        self.ui_queue.put(self._refresh_online_results_summary)
        self.ui_queue.put(self.refresh_browse_list)

    def _get_online_query_text(self) -> str:
        """取得目前線上模組輸入框文字。"""
        if not hasattr(self, "search_var"):
            return ""
        return str(self.search_var.get() or "").strip()

    def _build_online_browse_request(self) -> tuple[OnlineBrowseRequest | None, str | None]:
        """建立目前的線上瀏覽/搜尋請求。"""
        minecraft_version, _ = self._get_current_modrinth_filters()
        loader_type, warning_message = self._get_supported_online_loader()
        if warning_message or not loader_type:
            return None, warning_message

        sort_by = self.browse_sort_options.get(self.browse_sort_var.get(), "relevance")
        categories = tuple(self._get_selected_online_categories())
        return (
            OnlineBrowseRequest(
                query=self._get_online_query_text(),
                minecraft_version=minecraft_version,
                loader_type=loader_type,
                sort_by=sort_by,
                categories=categories,
            ),
            None,
        )

    def _is_browse_tab_active(self) -> bool:
        """判斷目前是否正在顯示線上瀏覽頁。"""
        if not self.notebook:
            return False
        with contextlib.suppress(Exception):
            return self.notebook.index(self.notebook.select()) == 1
        return False

    def _load_online_mods(self, *, force: bool = False, show_warning: bool = True) -> None:
        """依目前條件載入線上模組，支援瀏覽與關鍵字搜尋兩種模式。"""
        request, warning_message = self._build_online_browse_request()
        if request is None:
            if show_warning and warning_message:
                UIUtils.show_warning("目前不支援", warning_message, self.parent)
            self._clear_online_mods()
            return

        if not force and request == self._last_online_request and self.online_mods:
            return

        def search_task() -> None:
            try:
                filter_hint = self._get_online_filter_hint_text()
                mode_text = "載入可下載模組" if request.is_browse_mode else "搜尋 Modrinth 模組"
                self.update_status_safe(f"正在{mode_text}... {filter_hint}")
                mods = search_mods_online(
                    request.query,
                    minecraft_version=request.minecraft_version,
                    loader=request.loader_type,
                    categories=list(request.categories),
                    sort_by=request.sort_by,
                )
                self.online_mods = mods
                self._online_mod_index = {mod.project_id: mod for mod in mods if getattr(mod, "project_id", "")}
                self._last_online_request = request
                self.ui_queue.put(self.refresh_browse_list)
                if request.is_browse_mode:
                    self.update_status_safe(f"已載入 {len(mods)} 個可下載模組")
                else:
                    self.update_status_safe(f"找到 {len(mods)} 個線上模組")
            except Exception as e:
                logger.error(f"搜尋線上模組失敗: {e}\n{traceback.format_exc()}")
                self.update_status_safe(f"搜尋線上模組失敗: {e}")

        UIUtils.run_async(search_task)

    def on_online_browse_filters_changed(self, _value: str) -> None:
        """線上瀏覽排序或分類變更時立即刷新清單。"""
        self._refresh_online_filter_hint()
        self._refresh_online_results_summary()
        self._load_online_mods(force=True, show_warning=False)

    @staticmethod
    def _get_online_version_status_text(report: Any | None) -> str:
        """將版本分析結果轉成簡短狀態，供列表快速判讀。"""
        if report is None:
            return "未分析"
        if not getattr(report, "compatible", True):
            return "不相容"
        if list(getattr(report, "missing_required_dependencies", []) or []):
            return "可安裝，含依賴"
        if list(getattr(report, "incompatible_installed", []) or []) or list(
            getattr(report, "installed_version_mismatches", []) or []
        ):
            return "可安裝，需注意"
        if list(getattr(report, "warnings", []) or []):
            return "可安裝，需注意"
        return "可安裝"

    def _format_online_version_report(self, version: Any, report: Any | None) -> str:
        """格式化版本相容性與依賴分析結果。"""
        lines = [
            f"版本：{getattr(version, 'display_name', '未知版本')}",
            f"來源：{self._format_review_provider_label(getattr(version, 'provider', 'modrinth'))}",
            f"Minecraft：{', '.join(getattr(version, 'game_versions', []) or []) or '-'}",
            f"Loader：{', '.join(getattr(version, 'loaders', []) or []) or '-'}",
        ]

        version_type = str(getattr(version, "version_type", "") or "").strip()
        if version_type:
            lines.append(f"版本類型：{version_type}")

        published_text = self._format_review_published_at(getattr(version, "date_published", ""))
        if published_text:
            lines.append(f"發布時間：{published_text}")

        changelog_text = self._summarize_review_changelog(getattr(version, "changelog", ""))
        if changelog_text:
            lines.append("")
            lines.append("更新內容：")
            lines.append(changelog_text)

        if report is None:
            return "\n".join(lines)

        lines.insert(0, f"相容性結果：{'可安裝' if getattr(report, 'compatible', True) else '不符合目前伺服器條件'}")

        hard_errors = list(getattr(report, "hard_errors", []) or [])
        if hard_errors:
            lines.append("")
            lines.append("阻擋原因：")
            lines.extend(f"- {item}" for item in self._summarize_review_messages(hard_errors, max_items=3))

        missing_required = list(getattr(report, "missing_required_dependencies", []) or [])
        if missing_required:
            lines.append("")
            lines.append("需要安裝的必要依賴：")
            lines.extend(f"- {item}" for item in self._summarize_review_messages(missing_required, max_items=3))

        incompatible_installed = list(getattr(report, "incompatible_installed", []) or [])
        if incompatible_installed:
            lines.append("")
            lines.append("已安裝但不相容的模組：")
            lines.extend(f"- {item}" for item in self._summarize_review_messages(incompatible_installed, max_items=3))

        installed_version_mismatches = list(getattr(report, "installed_version_mismatches", []) or [])
        if installed_version_mismatches:
            lines.append("")
            lines.append("已安裝但版本不符的依賴：")
            lines.extend(
                f"- {item}" for item in self._summarize_review_messages(installed_version_mismatches, max_items=3)
            )

        optional_dependencies = list(getattr(report, "optional_dependencies", []) or [])
        if optional_dependencies:
            lines.append("")
            lines.append("可選依賴：")
            lines.extend(f"- {item}" for item in self._summarize_review_messages(optional_dependencies, max_items=2))

        already_installed = list(getattr(report, "already_installed", []) or [])
        if already_installed:
            lines.append("")
            lines.append("目前已安裝：")
            lines.extend(f"- {item}" for item in self._summarize_review_messages(already_installed, max_items=2))

        notes = list(getattr(report, "notes", []) or [])
        if notes:
            lines.append("")
            lines.append("補充說明：")
            lines.extend(f"- {item}" for item in self._summarize_review_messages(notes, max_items=2))

        return "\n".join(lines)

    def _build_online_install_warning_message(self, report: Any | None) -> str:
        """整理需要使用者確認的安裝前提醒。"""
        if report is None:
            return ""

        sections: list[str] = []
        already_installed = list(getattr(report, "already_installed", []) or [])
        if already_installed:
            sections.append("已安裝相同模組：\n" + "\n".join(f"- {item}" for item in already_installed))

        missing_required = list(getattr(report, "missing_required_dependencies", []) or [])
        if missing_required:
            sections.append("將自動安裝的必要依賴：\n" + "\n".join(f"- {item}" for item in missing_required))

        incompatible_installed = list(getattr(report, "incompatible_installed", []) or [])
        if incompatible_installed:
            sections.append("已安裝的不相容模組：\n" + "\n".join(f"- {item}" for item in incompatible_installed))

        installed_version_mismatches = list(getattr(report, "installed_version_mismatches", []) or [])
        if installed_version_mismatches:
            sections.append(
                "已安裝但版本不符的依賴：\n" + "\n".join(f"- {item}" for item in installed_version_mismatches)
            )

        return "\n\n".join(sections)

    @staticmethod
    def _format_review_provider_label(provider: str | None) -> str:
        normalized = str(provider or "").strip().lower()
        if normalized == "modrinth":
            return "Modrinth"
        return str(provider or "未知來源").strip() or "未知來源"

    @staticmethod
    def _format_metadata_source_label(source: str | None) -> str:
        normalized = str(source or "").strip().lower()
        if normalized == "hash":
            return "雜湊比對"
        if normalized == "cached_provider":
            return "已快取 metadata"
        if normalized == "lookup":
            return "專案查詢"
        if normalized == "unresolved":
            return "尚未識別"
        return "未知"

    @staticmethod
    def _format_metadata_source_short_label(source: str | None) -> str:
        normalized = str(source or "").strip().lower()
        if normalized == "hash":
            return "雜湊"
        if normalized == "cached_provider":
            return "快取"
        if normalized == "lookup":
            return "查詢"
        if normalized == "unresolved":
            return "待綁定"
        return "未知"

    @staticmethod
    def _build_modrinth_project_page_url(identifier: str | None) -> str:
        normalized = str(identifier or "").strip().strip("/")
        if not normalized:
            return ""
        return f"{MODRINTH_PROJECT_PAGE_BASE_URL}/{normalized}"

    @classmethod
    def _resolve_online_mod_project_page_url(cls, mod: Any) -> str:
        homepage_url = str(getattr(mod, "homepage_url", "") or "").strip()
        if homepage_url:
            return homepage_url

        source_url = str(getattr(mod, "url", "") or "").strip()
        if source_url:
            return source_url

        slug = str(getattr(mod, "slug", "") or "").strip()
        if slug:
            return cls._build_modrinth_project_page_url(slug)

        project_id = str(getattr(mod, "project_id", "") or "").strip()
        return cls._build_modrinth_project_page_url(project_id)

    @classmethod
    def _resolve_pending_install_review_project_page_url(cls, review_entry: PendingInstallReviewEntry) -> str:
        pending = getattr(review_entry, "pending", None)
        if pending is None:
            return ""

        homepage_url = str(getattr(pending, "homepage_url", "") or "").strip()
        if homepage_url:
            return homepage_url

        source_url = str(getattr(pending, "source_url", "") or "").strip()
        if source_url:
            return source_url

        project_id = str(getattr(pending, "project_id", "") or "").strip()
        return cls._build_modrinth_project_page_url(project_id)

    @classmethod
    def _resolve_local_update_review_project_page_url(cls, review_entry: LocalUpdateReviewEntry) -> str:
        candidate = getattr(review_entry, "candidate", None)
        if candidate is None:
            return ""

        local_mod = getattr(candidate, "local_mod", None)
        slug = str(getattr(local_mod, "platform_slug", "") or "").strip()
        if slug:
            return cls._build_modrinth_project_page_url(slug)

        project_id = str(getattr(candidate, "project_id", "") or getattr(local_mod, "platform_id", "") or "").strip()
        return cls._build_modrinth_project_page_url(project_id)

    @staticmethod
    def _format_review_published_at(value: str | None) -> str:
        raw_value = str(value or "").strip()
        if not raw_value:
            return ""
        return raw_value.replace("T", " ").replace("Z", "")[:16]

    def _open_project_page(self, url: str, parent: Any, *, title: str = "沒有可開啟的專案頁面") -> None:
        clean_url = str(url or "").strip()
        if not clean_url:
            UIUtils.show_warning(title, "目前無法判定這個項目的專案頁面。", parent)
            return
        UIUtils.open_external(clean_url)

    @staticmethod
    def _create_review_summary_box(parent: Any, *, height: int) -> ctk.CTkTextbox:
        summary_box = ctk.CTkTextbox(
            parent,
            height=FontManager.get_dpi_scaled_size(height),
            font=FontManager.get_font(size=FontSize.NORMAL_PLUS),
            wrap="word",
        )
        summary_box.pack(fill="x", padx=12, pady=(0, 12))
        summary_box.configure(state="disabled")
        return summary_box

    @staticmethod
    def _get_mousewheel_units(delta: int) -> int:
        if delta == 0:
            return 0
        units = int(-delta / 120)
        if units == 0:
            return -1 if delta > 0 else 1
        return units

    @classmethod
    def _bind_vertical_mousewheel(cls, widget: Any, *, scroll_callback: Callable[..., Any]) -> None:
        try:
            widget.bind(
                "<MouseWheel>",
                lambda event: cls._scroll_widget_vertical(event, scroll_callback=scroll_callback),
                add="+",
            )
        except Exception:
            return

    @classmethod
    def _scroll_widget_vertical(cls, event: Any, *, scroll_callback: Callable[..., Any]) -> str | None:
        units = cls._get_mousewheel_units(int(getattr(event, "delta", 0)))
        if units == 0:
            return None
        scroll_callback(units, "units")
        return "break"

    @staticmethod
    def _select_tree_item_for_context_menu(tree: Any, event: Any) -> str:
        row_id = str(tree.identify_row(int(getattr(event, "y", 0))) or "").strip()
        if not row_id:
            return ""

        selection = set(tree.selection())
        if row_id not in selection:
            tree.selection_set(row_id)
        tree.focus(row_id)
        tree.see(row_id)
        return row_id

    @staticmethod
    def _build_online_install_review_subtitle(actionable_count: int, blocked_count: int) -> str:
        segments = ["已重驗證可安裝性與必要依賴", f"可安裝 {actionable_count} 項"]
        if blocked_count:
            segments.append(f"{blocked_count} 項待處理")
        return "｜".join(segments)

    @staticmethod
    def _build_local_update_review_subtitle(scope_text: str, enabled_count: int, blocked_count: int) -> str:
        segments = [f"範圍：{scope_text}", f"可執行更新 {enabled_count} 項"]
        if blocked_count:
            segments.append(f"{blocked_count} 項待處理")
        return "｜".join(segments)

    def _format_local_update_source_text(self, review_entry: LocalUpdateReviewEntry) -> str:
        provider_label = self._format_review_provider_label(review_entry.provider)
        metadata_source = str(getattr(review_entry.candidate, "metadata_source", "") or "").strip()
        if not metadata_source:
            return provider_label
        return f"{provider_label}｜{self._format_metadata_source_short_label(metadata_source)}"

    def _build_local_update_metadata_detail(self, review_entry: LocalUpdateReviewEntry) -> str:
        candidate = review_entry.candidate
        lines = [f"Metadata 來源：{self._format_metadata_source_label(getattr(candidate, 'metadata_source', ''))}"]

        metadata_note = str(getattr(candidate, "metadata_note", "") or "").strip()
        if metadata_note:
            lines.append(f"Metadata 狀態：{metadata_note}")
        return "\n".join(lines)

    @staticmethod
    def _summarize_review_changelog(value: str | None, max_length: int = 420) -> str:
        raw_value = str(value or "").strip()
        if not raw_value:
            return ""
        normalized = re.sub(r"\s+", " ", raw_value).strip()
        if len(normalized) <= max_length:
            return normalized
        return normalized[: max(0, max_length - 3)].rstrip() + "..."

    @staticmethod
    def _collect_selected_root_keys(tree: ttk.Treeview) -> set[str]:
        return ModManagementFrame._collect_selected_root_keys_from(tree, None)

    @staticmethod
    def _collect_selected_root_keys_from(tree: ttk.Treeview, valid_keys: set[str] | None) -> set[str]:
        selected_root_keys: set[str] = set()
        for item_id in tree.selection():
            current_item = item_id
            while current_item:
                if valid_keys is not None and current_item in valid_keys:
                    break
                parent_id = tree.parent(current_item)
                if not parent_id:
                    break
                current_item = parent_id
            selected_root_keys.add(current_item)
        return selected_root_keys

    @staticmethod
    def _get_selected_review_key(tree: ttk.Treeview, valid_keys: set[str]) -> str:
        selected_root_keys = ModManagementFrame._collect_selected_root_keys_from(tree, valid_keys)
        if selected_root_keys:
            return next(iter(selected_root_keys))
        return next(iter(valid_keys), "")

    @staticmethod
    def _set_review_entries_enabled(entries: dict[str, Any], keys: set[str], enabled: bool) -> bool:
        changed = False
        for key in keys:
            entry = entries.get(key)
            if entry is None or bool(getattr(entry, "enabled", True)) == enabled:
                continue
            entry.enabled = enabled
            changed = True
        return changed

    @staticmethod
    def _build_dependency_review_key(dependency_item: Any) -> tuple[str, str]:
        return (
            str(getattr(dependency_item, "project_id", "") or "").strip(),
            str(
                getattr(dependency_item, "version_id", "") or getattr(dependency_item, "version_name", "") or ""
            ).strip(),
        )

    @staticmethod
    def _is_optional_dependency_item(dependency_item: Any) -> bool:
        marker = getattr(dependency_item, "is_optional", None)
        if marker is None:
            return True
        return bool(marker)

    @staticmethod
    def _collect_review_entry_enabled_overrides(entries: list[Any], root_keys: list[str]) -> dict[str, bool]:
        return {
            root_key: bool(getattr(entry, "enabled", False))
            for root_key, entry in zip(root_keys, entries, strict=False)
            if root_key
        }

    def _collect_review_advisory_enabled_overrides(
        self, entries: list[Any], root_keys: list[str]
    ) -> dict[tuple[str, tuple[str, str]], bool]:
        overrides: dict[tuple[str, tuple[str, str]], bool] = {}
        for root_key, entry in zip(root_keys, entries, strict=False):
            if not root_key:
                continue
            dependency_plan = getattr(entry, "dependency_plan", None)
            for dependency_item in list(getattr(dependency_plan, "advisory_items", []) or []):
                dependency_key = self._build_dependency_review_key(dependency_item)
                overrides[(root_key, dependency_key)] = bool(getattr(dependency_item, "enabled", False))
        return overrides

    def _apply_review_advisory_enabled_overrides(
        self,
        dependency_plan: Any,
        root_key: str,
        advisory_enabled_overrides: dict[tuple[str, tuple[str, str]], bool] | None,
    ) -> None:
        if not advisory_enabled_overrides:
            return
        for dependency_item in list(getattr(dependency_plan, "advisory_items", []) or []):
            dependency_key = self._build_dependency_review_key(dependency_item)
            override_key = (root_key, dependency_key)
            if override_key not in advisory_enabled_overrides:
                continue
            dependency_item.enabled = advisory_enabled_overrides[override_key]

    @staticmethod
    def _count_enabled_runnable_entries(entries: list[Any]) -> int:
        return sum(
            1 for entry in entries if bool(getattr(entry, "enabled", False)) and bool(getattr(entry, "runnable", False))
        )

    @staticmethod
    def _count_blocked_entries(entries: list[Any]) -> int:
        return sum(1 for entry in entries if not bool(getattr(entry, "runnable", False)))

    @staticmethod
    def _count_dependency_plan_items(dependency_plan: Any) -> tuple[int, int]:
        """回傳必要依賴數與可選依賴數。"""
        auto_install_count = len(list(getattr(dependency_plan, "items", []) or []))
        advisory_items = list(getattr(dependency_plan, "advisory_items", []) or [])
        optional_count = sum(1 for item in advisory_items if ModManagementFrame._is_optional_dependency_item(item))
        return auto_install_count, optional_count

    def _build_online_review_root_status_text(self, review_entry: PendingInstallReviewEntry) -> str:
        """建立線上安裝 review 根節點摘要，供 task tree 快速判讀。"""
        base_status = ("可安裝" if review_entry.enabled else "已停用") if review_entry.runnable else "需先處理"

        auto_dependency_count, optional_dependency_count = self._count_dependency_plan_items(
            getattr(review_entry, "dependency_plan", None)
        )
        warning_count = len(self._dedupe_review_messages(list(getattr(review_entry, "warning_messages", []) or [])))
        blocking_count = len(self._dedupe_review_messages(list(getattr(review_entry, "blocking_reasons", []) or [])))

        segments = [base_status]
        if auto_dependency_count:
            segments.append(f"依賴 {auto_dependency_count}")
        if optional_dependency_count:
            segments.append(f"可選 {optional_dependency_count}")
        if warning_count:
            segments.append(f"提醒 {warning_count}")
        if blocking_count:
            segments.append(f"阻擋 {blocking_count}")
        return "｜".join(segments)

    def _build_pending_install_summary_lines(self, review_entry: PendingInstallReviewEntry) -> list[str]:
        """建立待安裝 review 詳細文字頂部摘要。"""
        lines = [f"摘要：{self._build_online_review_root_status_text(review_entry)}"]
        dependency_plan = getattr(review_entry, "dependency_plan", None)
        auto_dependency_count, optional_dependency_count = self._count_dependency_plan_items(dependency_plan)
        if auto_dependency_count:
            lines.append(f"- 將自動補裝 {auto_dependency_count} 個必要依賴")
        if optional_dependency_count:
            enabled_optional = sum(
                1
                for item in list(getattr(dependency_plan, "advisory_items", []) or [])
                if self._is_optional_dependency_item(item) and bool(getattr(item, "enabled", False))
            )
            lines.append(f"- 可選依賴 {optional_dependency_count} 項（已選 {enabled_optional} 項）")
        if review_entry.blocking_reasons:
            lines.append(
                f"- 目前有 {len(self._dedupe_review_messages(review_entry.blocking_reasons))} 個阻擋原因需先處理"
            )
        elif review_entry.warning_messages:
            lines.append(f"- 目前有 {len(self._dedupe_review_messages(review_entry.warning_messages))} 個提醒需留意")
        return lines

    @staticmethod
    def _normalize_side_support(value: Any) -> str:
        return str(value or "").strip().lower()

    @classmethod
    def _is_client_side_supported_mod(cls, server_side: Any, client_side: Any) -> bool:
        normalized_server_side = cls._normalize_side_support(server_side)
        normalized_client_side = cls._normalize_side_support(client_side)
        server_supported = normalized_server_side in {"required", "optional"}
        client_supported = normalized_client_side in {"required", "optional"}
        return server_supported and client_supported

    @classmethod
    def _build_client_install_reminder_line(cls, server_side: Any, client_side: Any) -> str | None:
        if not cls._is_client_side_supported_mod(server_side, client_side):
            return None
        return "提醒：此模組同時支援 client 端，請提醒玩家端也安裝相同模組版本，以避免連線或功能不一致問題。"

    @staticmethod
    def _dedupe_review_messages(messages: list[str] | tuple[str, ...]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for message in messages:
            normalized = str(message or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    @staticmethod
    def _summarize_review_messages(messages: list[str] | tuple[str, ...], max_items: int = 3) -> list[str]:
        deduped = ModManagementFrame._dedupe_review_messages(messages)
        if len(deduped) <= max_items:
            return deduped
        return [*deduped[:max_items], f"其餘 {len(deduped) - max_items} 項請於任務樹查看。"]

    @staticmethod
    def _summarize_review_note(value: str | None, max_length: int = 140) -> str:
        normalized = re.sub(r"\s+", " ", str(value or "").strip())
        if len(normalized) <= max_length:
            return normalized
        return normalized[: max(0, max_length - 3)].rstrip() + "..."

    @staticmethod
    def _format_required_by_list(required_by: list[str]) -> str:
        deduped = ModManagementFrame._dedupe_review_messages(required_by)
        if not deduped:
            return ""
        if len(deduped) <= 3:
            return "、".join(deduped)
        return f"{'、'.join(deduped[:3])} 等 {len(deduped)} 個項目"

    @staticmethod
    def _format_dependency_resolution_label(source: str | None, confidence: str | None) -> str:
        normalized_source = str(source or "").strip().lower()
        normalized_confidence = str(confidence or "").strip().lower()

        source_label = "project id 直連"
        if normalized_source == "version_detail":
            source_label = "版本詳情回補"
        elif normalized_source == "loader_override":
            source_label = "loader 覆寫"
        elif normalized_source == "version_id":
            source_label = "version id 線索"

        confidence_label = "高"
        if normalized_confidence == "fallback":
            confidence_label = "中"
        elif normalized_confidence in {"heuristic", "manual"}:
            confidence_label = "需確認"

        return f"{source_label}（{confidence_label}）"

    @staticmethod
    def _format_dependency_action_label(dependency_item: Any, is_advisory: bool, is_enabled: bool) -> str:
        if is_advisory and is_enabled:
            return "可選依賴，已啟用安裝"
        if is_advisory:
            return "可選依賴，預設略過"

        if bool(getattr(dependency_item, "maybe_installed", False)) and is_enabled:
            return "疑似已安裝，已改為安裝"
        if bool(getattr(dependency_item, "maybe_installed", False)):
            return "疑似已安裝，預設略過"

        status_note = str(getattr(dependency_item, "status_note", "") or "").strip()
        if status_note:
            return status_note
        return "將自動安裝"

    @staticmethod
    def _count_review_nodes(nodes: list[ReviewTaskNode], node_kind: str) -> int:
        return sum(1 for node in nodes if node.node_kind == node_kind)

    def _format_review_overview_text(
        self,
        entries: list[Any],
        nodes: list[ReviewTaskNode],
        *,
        action_label: str,
        global_notes: list[str] | None = None,
    ) -> str:
        _ = global_notes
        root_count = len(entries)
        dependency_count = self._count_review_nodes(nodes, "dependency")
        issue_count = self._count_review_nodes(nodes, "issue")
        warning_count = self._count_review_nodes(nodes, "warning")
        enabled_count = self._count_enabled_runnable_entries(entries)
        disabled_count = sum(
            1 for entry in entries if getattr(entry, "runnable", False) and not getattr(entry, "enabled", False)
        )

        segments = [f"Task graph：{root_count} 個根任務", f"目前將{action_label} {enabled_count} 個根項目"]
        if dependency_count:
            segments.append(f"{dependency_count} 個依賴")
        if issue_count:
            segments.append(f"{issue_count} 個待處理")
        if warning_count:
            segments.append(f"{warning_count} 個提醒")
        if disabled_count:
            segments.append(f"另有 {disabled_count} 個已停用項目")
        notes = self._dedupe_review_messages(list(global_notes or []))
        if notes:
            segments.append("預檢：" + self._summarize_review_note(notes[0], max_length=40))
        return "｜".join(segments)

    @staticmethod
    def _collect_online_review_global_notes(review_entries: list[PendingInstallReviewEntry]) -> list[str]:
        notes = ["已完成安裝前預檢：重新驗證目前伺服器條件、本地模組與必要依賴。"]
        for entry in review_entries:
            notes.extend(list(getattr(getattr(entry, "dependency_plan", None), "notes", []) or []))
        return ModManagementFrame._dedupe_review_messages(notes)

    @staticmethod
    def _collect_local_update_global_notes(
        update_plan: LocalModUpdatePlan, review_entries: list[LocalUpdateReviewEntry]
    ) -> list[str]:
        notes = ["已完成更新前預檢：優先使用本地雜湊與已快取 provider metadata 檢查最新版本。"]
        notes.extend(list(getattr(update_plan, "notes", []) or []))
        notes.extend(list(getattr(getattr(update_plan, "metadata_summary", None), "notes", []) or []))
        for entry in review_entries:
            notes.extend(list(getattr(getattr(entry, "dependency_plan", None), "notes", []) or []))
        return ModManagementFrame._dedupe_review_messages(notes)

    def _persist_local_update_plan_metadata(self, update_plan: LocalModUpdatePlan) -> None:
        """將更新檢查得到的 metadata / hash 回寫索引，接近 Prism 的 ensure metadata 流程。"""
        manager = self.mod_manager
        if not manager:
            return

        for candidate in getattr(update_plan, "candidates", []) or []:
            local_mod = getattr(candidate, "local_mod", None)
            file_path_raw = str(getattr(local_mod, "file_path", "") or "").strip()
            if not file_path_raw:
                continue

            file_path = Path(file_path_raw)
            current_hash = str(getattr(candidate, "current_hash", "") or "").strip()
            if current_hash:
                manager.index_manager.cache_file_hash(
                    file_path,
                    str(getattr(candidate, "hash_algorithm", "sha512") or "sha512"),
                    current_hash,
                )

            project_id = str(getattr(candidate, "project_id", "") or "").strip()
            if not project_id or project_id.startswith("__unresolved__::"):
                continue

            manager.index_manager.cache_provider_metadata(
                file_path,
                {
                    "platform": "modrinth",
                    "project_id": project_id,
                    "slug": str(getattr(local_mod, "platform_slug", "") or "").strip(),
                    "project_name": str(getattr(candidate, "project_name", "") or project_id).strip(),
                },
            )

        manager.index_manager.flush()

    @staticmethod
    def _collect_online_dependency_required_by(
        review_entries: list[PendingInstallReviewEntry],
    ) -> dict[tuple[str, str], list[str]]:
        return ModManagementFrame._collect_dependency_required_by(
            review_entries,
            parent_name_getter=lambda entry: str(
                getattr(getattr(entry, "pending", None), "project_name", "") or ""
            ).strip(),
        )

    @staticmethod
    def _collect_local_dependency_required_by(
        review_entries: list[LocalUpdateReviewEntry],
    ) -> dict[tuple[str, str], list[str]]:
        return ModManagementFrame._collect_dependency_required_by(
            review_entries,
            parent_name_getter=lambda entry: str(
                getattr(getattr(entry, "candidate", None), "project_name", "") or ""
            ).strip(),
        )

    @staticmethod
    def _build_local_update_review_key(candidate: Any) -> str:
        project_id = str(getattr(candidate, "project_id", "") or "").strip()
        local_mod = getattr(candidate, "local_mod", None)
        file_path = str(getattr(local_mod, "file_path", "") or "").strip()
        if project_id and file_path:
            return f"project::{project_id}::{file_path}"
        if project_id:
            return project_id
        if file_path:
            return f"local::{file_path}"

        filename = str(getattr(candidate, "filename", "") or getattr(local_mod, "filename", "") or "").strip()
        if filename:
            return f"local::{filename}"

        project_name = str(getattr(candidate, "project_name", "") or "unknown").strip()
        return f"local::{project_name}"

    @staticmethod
    def _build_dependency_key(dependency_item: Any) -> tuple[str, str]:
        return (
            str(getattr(dependency_item, "project_id", "") or "").strip(),
            str(
                getattr(dependency_item, "version_id", "") or getattr(dependency_item, "version_name", "") or ""
            ).strip(),
        )

    @staticmethod
    def _collect_dependency_required_by(
        review_entries: list[Any],
        *,
        parent_name_getter: Callable[[Any], str],
    ) -> dict[tuple[str, str], list[str]]:
        required_by: dict[tuple[str, str], list[str]] = {}
        for entry in review_entries:
            if not bool(getattr(entry, "enabled", False)) or not bool(getattr(entry, "runnable", False)):
                continue
            parent_name = parent_name_getter(entry)
            if not parent_name:
                continue
            dependency_entries = ModManagementFrame._get_sorted_dependency_review_items(entry.dependency_plan)
            for dependency_item in dependency_entries:
                dependency_key = ModManagementFrame._build_dependency_key(dependency_item)
                required_by.setdefault(dependency_key, []).append(parent_name)
        return required_by

    @staticmethod
    def _format_completion_notes(messages: list[str], max_items: int = 4) -> str:
        deduped = ModManagementFrame._dedupe_review_messages(messages)
        if not deduped:
            return ""
        preview = deduped[:max_items]
        suffix = f"\n另有 {len(deduped) - len(preview)} 則提醒。" if len(deduped) > len(preview) else ""
        return "\n提醒：\n- " + "\n- ".join(preview) + suffix

    @staticmethod
    def _get_sorted_dependency_review_items(dependency_plan: Any) -> list[Any]:
        dependency_entries = [
            *(list(getattr(dependency_plan, "items", []) or [])),
            *(list(getattr(dependency_plan, "advisory_items", []) or [])),
        ]
        dependency_entries.sort(
            key=lambda item: (
                str(getattr(item, "project_name", "") or "").casefold(),
                str(getattr(item, "version_name", "") or "").casefold(),
            )
        )
        return dependency_entries

    @staticmethod
    def _get_enabled_dependency_install_items(dependency_plan: Any) -> list[Any]:
        return [
            *list(getattr(dependency_plan, "items", []) or []),
            *[
                item
                for item in list(getattr(dependency_plan, "advisory_items", []) or [])
                if bool(getattr(item, "enabled", False))
            ],
        ]

    @staticmethod
    def _set_selected_advisory_dependency_items_enabled(
        tree: ttk.Treeview, entry_map: dict[str, Any], enabled: bool
    ) -> bool:
        changed = False
        for item_id in tree.selection():
            normalized_item_id = str(item_id or "").strip()
            if normalized_item_id.endswith("::optional-dependencies"):
                root_key = normalized_item_id.rsplit("::optional-dependencies", 1)[0]
                if root_key not in entry_map:
                    continue
                advisory_items = list(
                    getattr(getattr(entry_map[root_key], "dependency_plan", None), "advisory_items", []) or []
                )
                for dependency_item in advisory_items:
                    if bool(getattr(dependency_item, "enabled", False)) == enabled:
                        continue
                    dependency_item.enabled = enabled
                    changed = True
                continue

            if "::dependency::" not in normalized_item_id:
                continue

            root_key, dependency_index_text = normalized_item_id.rsplit("::dependency::", 1)
            if root_key not in entry_map:
                continue

            try:
                dependency_index = int(dependency_index_text)
            except ValueError:
                continue

            dependency_items = ModManagementFrame._get_sorted_dependency_review_items(
                getattr(entry_map[root_key], "dependency_plan", None)
            )
            advisory_items = list(
                getattr(getattr(entry_map[root_key], "dependency_plan", None), "advisory_items", []) or []
            )
            advisory_item_ids = {id(item) for item in advisory_items}
            if dependency_index < 0 or dependency_index >= len(dependency_items):
                continue

            dependency_item = dependency_items[dependency_index]
            if not (
                bool(getattr(dependency_item, "maybe_installed", False))
                or bool(getattr(dependency_item, "is_optional", False))
                or id(dependency_item) in advisory_item_ids
            ):
                continue
            if bool(getattr(dependency_item, "enabled", False)) == enabled:
                continue

            dependency_item.enabled = enabled
            changed = True

        return changed

    @staticmethod
    def _get_review_entry_group_key(entry: Any) -> str:
        if not bool(getattr(entry, "runnable", False)):
            return "blocked"
        if not bool(getattr(entry, "enabled", False)):
            return "disabled"
        return "enabled"

    @staticmethod
    def _get_review_group_specs() -> tuple[tuple[str, str], ...]:
        return (
            ("enabled", "已啟用項目"),
            ("disabled", "已停用項目"),
            ("blocked", "需先處理項目"),
        )

    @staticmethod
    def _build_group_node_id(group_key: str) -> str:
        return f"group::{group_key}"

    @staticmethod
    def _build_dependency_status_text(
        dependency_item: Any,
        parent_name: str,
        required_by_text: str,
        is_advisory: bool,
        is_enabled: bool,
    ) -> str:
        resolved_required_by = required_by_text or parent_name
        resolution_label = ModManagementFrame._format_dependency_resolution_label(
            getattr(dependency_item, "resolution_source", "project_id"),
            getattr(dependency_item, "resolution_confidence", "direct"),
        )
        action_label = ModManagementFrame._format_dependency_action_label(dependency_item, is_advisory, is_enabled)
        return f"required-by：{resolved_required_by}｜解析：{resolution_label}｜處理：{action_label}"

    def _build_dependency_review_nodes(
        self,
        *,
        root_key: str,
        group_key: str,
        optional_group_values: tuple[str, ...],
        parent_name: str,
        dependency_plan: Any,
        required_by_map: dict[tuple[str, str], list[str]],
        node_builder: Callable[[int, Any, str, bool, bool, str], ReviewTaskNode],
    ) -> list[ReviewTaskNode]:
        nodes: list[ReviewTaskNode] = []
        dependency_entries: list[tuple[Any, bool]] = [
            *((item, False) for item in list(getattr(dependency_plan, "items", []) or [])),
            *((item, True) for item in list(getattr(dependency_plan, "advisory_items", []) or [])),
        ]
        dependency_entries.sort(
            key=lambda entry: (
                str(getattr(entry[0], "project_name", "") or "").casefold(),
                str(getattr(entry[0], "version_name", "") or "").casefold(),
            )
        )
        optional_group_id = f"{root_key}::optional-dependencies"
        optional_group_added = False
        optional_count = sum(
            1 for item, is_from_advisory in dependency_entries if bool(getattr(item, "is_optional", is_from_advisory))
        )
        for index, (dependency_item, is_from_advisory) in enumerate(dependency_entries):
            dependency_key = self._build_dependency_key(dependency_item)
            required_by_text = self._format_required_by_list(required_by_map.get(dependency_key, [parent_name]))
            is_optional = bool(getattr(dependency_item, "is_optional", is_from_advisory))
            maybe_installed = bool(getattr(dependency_item, "maybe_installed", False))
            is_enabled = bool(getattr(dependency_item, "enabled", not (is_optional or maybe_installed)))
            dependency_status = self._build_dependency_status_text(
                dependency_item,
                parent_name,
                required_by_text,
                is_optional,
                is_enabled,
            )
            parent_id = root_key
            if is_optional:
                if not optional_group_added:
                    optional_group_added = True
                    group_status = f"共 {optional_count} 項，可啟用後一同安裝"
                    nodes.append(
                        ReviewTaskNode(
                            node_id=optional_group_id,
                            root_key=root_key,
                            group_key=group_key,
                            parent_id=root_key,
                            title="可選依賴",
                            values=(*optional_group_values[:-1], group_status),
                            node_kind="dependency-group",
                            detail=group_status,
                        )
                    )
                parent_id = optional_group_id
            nodes.append(node_builder(index, dependency_item, dependency_status, is_optional, is_enabled, parent_id))
        return nodes

    @staticmethod
    def _append_review_message_nodes(
        nodes: list[ReviewTaskNode],
        *,
        messages: list[str],
        node_factory: Callable[[int, str], ReviewTaskNode],
    ) -> None:
        for index, message in enumerate(messages):
            nodes.append(node_factory(index, message))

    @staticmethod
    def _mask_redundant_review_values(
        parent_values: tuple[str, ...],
        child_values: tuple[str, ...],
    ) -> tuple[str, ...]:
        """將與父節點相同的欄位值改以 '-' 顯示。"""
        masked_values: list[str] = []
        for index, raw_child in enumerate(child_values):
            child_text = str(raw_child or "").strip() or "-"
            parent_text = str(parent_values[index] if index < len(parent_values) else "").strip() or "-"
            if child_text != "-" and child_text == parent_text:
                masked_values.append("-")
            else:
                masked_values.append(child_text)
        return tuple(masked_values)

    def _build_online_dependency_task_node(
        self,
        *,
        root_key: str,
        group_key: str,
        parent_values: tuple[str, ...],
        index: int,
        dependency_item: Any,
        dependency_status: str,
        is_advisory: bool,
        is_enabled: bool,
        parent_id: str,
    ) -> ReviewTaskNode:
        child_values = (
            "自動" if is_enabled else "略過" if is_advisory else "自動",
            "Modrinth",
            dependency_item.project_name,
            dependency_item.version_name,
            "optional" if self._is_optional_dependency_item(dependency_item) else "required",
            dependency_status,
        )
        return ReviewTaskNode(
            node_id=f"{root_key}::dependency::{index}",
            root_key=root_key,
            group_key=group_key,
            parent_id=parent_id,
            title="依賴",
            values=self._mask_redundant_review_values(parent_values, child_values),
            node_kind="dependency",
            detail=dependency_status,
        )

    def _build_local_dependency_task_node(
        self,
        *,
        root_key: str,
        group_key: str,
        parent_values: tuple[str, ...],
        index: int,
        dependency_item: Any,
        dependency_status: str,
        is_advisory: bool,
        is_enabled: bool,
        parent_id: str,
    ) -> ReviewTaskNode:
        child_values = (
            "自動" if is_enabled else "略過" if is_advisory else "自動",
            "-",
            dependency_item.version_name,
            "可選依賴" if self._is_optional_dependency_item(dependency_item) else "Modrinth",
            dependency_status,
        )
        return ReviewTaskNode(
            node_id=f"{root_key}::dependency::{index}",
            root_key=root_key,
            group_key=group_key,
            parent_id=parent_id,
            title=f"依賴：{dependency_item.project_name}",
            values=self._mask_redundant_review_values(parent_values, child_values),
            node_kind="dependency",
            detail=dependency_status,
        )

    def _build_online_issue_task_node(
        self,
        *,
        root_key: str,
        group_key: str,
        parent_values: tuple[str, ...],
        index: int,
        message: str,
    ) -> ReviewTaskNode:
        return ReviewTaskNode(
            node_id=f"{root_key}::blocked::{index}",
            root_key=root_key,
            group_key=group_key,
            parent_id=root_key,
            title="需處理",
            values=self._mask_redundant_review_values(parent_values, ("-", "-", "-", "-", "-", message)),
            node_kind="issue",
        )

    def _build_local_issue_task_node(
        self,
        *,
        root_key: str,
        group_key: str,
        parent_values: tuple[str, ...],
        index: int,
        message: str,
    ) -> ReviewTaskNode:
        return ReviewTaskNode(
            node_id=f"{root_key}::blocked::{index}",
            root_key=root_key,
            group_key=group_key,
            parent_id=root_key,
            title="需處理",
            values=self._mask_redundant_review_values(parent_values, ("-", "-", "-", "-", message)),
            node_kind="issue",
        )

    @staticmethod
    def _append_simulated_installed_mod(
        simulated_installed_mods: list[Any],
        simulation_item: Any,
    ) -> None:
        simulated_installed_mods.append(simulation_item)

    def _append_enabled_dependency_simulations(self, simulated_installed_mods: list[Any], dependency_plan: Any) -> None:
        for dependency_item in self._get_enabled_dependency_install_items(dependency_plan):
            self._append_simulated_installed_mod(
                simulated_installed_mods,
                self._build_installed_mod_simulation_item(
                    dependency_item.project_id,
                    dependency_item.project_name,
                    dependency_item.filename,
                    dependency_item.version_name,
                ),
            )

    @staticmethod
    def _append_review_section(lines: list[str], title: str, messages: list[str], *, max_items: int) -> None:
        summarized = ModManagementFrame._summarize_review_messages(messages, max_items=max_items)
        if not summarized:
            return
        lines.append("")
        lines.append(title)
        lines.extend(f"- {item}" for item in summarized)

    @staticmethod
    def _append_dependency_review_sections(lines: list[str], dependency_plan: Any, required_heading: str) -> None:
        dependency_items = list(getattr(dependency_plan, "items", []) or [])
        advisory_items = list(getattr(dependency_plan, "advisory_items", []) or [])
        if dependency_items:
            lines.append("")
            lines.append(required_heading)
            lines.extend(f"- {item.project_name} ({item.version_name})" for item in dependency_items[:3])
            if len(dependency_items) > 3:
                lines.append(f"- 其餘 {len(dependency_items) - 3} 項請於任務樹查看。")
        if advisory_items:
            optional_items = [item for item in advisory_items if ModManagementFrame._is_optional_dependency_item(item)]
            maybe_installed_items = [
                item for item in advisory_items if not ModManagementFrame._is_optional_dependency_item(item)
            ]

            if optional_items:
                lines.append("")
                lines.append("可選依賴（可啟用後一同安裝）：")
                lines.extend(
                    f"- {item.project_name}{'（已啟用）' if getattr(item, 'enabled', False) else '（預設略過）'}"
                    for item in optional_items[:2]
                )
                if len(optional_items) > 2:
                    lines.append(f"- 其餘 {len(optional_items) - 2} 項請於任務樹查看。")

            if maybe_installed_items:
                lines.append("")
                lines.append("疑似已安裝、預設略過的必要依賴：")
                lines.extend(
                    f"- {item.project_name}{'（已改為安裝）' if getattr(item, 'enabled', False) else ''}"
                    for item in maybe_installed_items[:2]
                )
                if len(maybe_installed_items) > 2:
                    lines.append(f"- 其餘 {len(maybe_installed_items) - 2} 項請於任務樹查看。")

    def _append_plan_note_section(self, lines: list[str], dependency_plan: Any, *, max_items: int = 2) -> None:
        plan_notes = self._dedupe_review_messages(list(getattr(dependency_plan, "notes", []) or []))
        self._append_review_section(lines, "預檢補充：", plan_notes, max_items=max_items)

    @staticmethod
    def _configure_review_action_button(button: ctk.CTkButton, review_entries: list[Any], action_label: str) -> None:
        runnable_enabled = ModManagementFrame._count_enabled_runnable_entries(review_entries)
        button.configure(
            text=f"⬇️ {action_label} {runnable_enabled} 個已啟用項目",
            state="normal" if runnable_enabled else "disabled",
        )

    def _toggle_review_selection(
        self,
        *,
        tree: ttk.Treeview,
        entry_map: dict[str, Any],
        review_root_keys: set[str],
        enabled: bool,
        rebuild_entries: Callable[[], None],
        refresh_tree: Callable[[], None],
        refresh_summary: Callable[[], None],
        refresh_status_banner: Callable[[], None],
        refresh_action_button: Callable[[], None],
    ) -> None:
        if self._set_selected_advisory_dependency_items_enabled(tree, entry_map, enabled):
            rebuild_entries()
            refresh_tree()
            refresh_summary()
            refresh_status_banner()
            refresh_action_button()
            return

        selected_root_keys = self._collect_selected_root_keys_from(tree, review_root_keys)
        if not selected_root_keys:
            return
        if not self._set_review_entries_enabled(entry_map, selected_root_keys, enabled):
            return
        rebuild_entries()
        refresh_tree()
        refresh_summary()
        refresh_status_banner()
        refresh_action_button()

    def _create_review_action_button(
        self,
        parent,
        *,
        text: str,
        fg_color: Any,
        hover_color: Any,
        command: Callable[[], None],
        padx: tuple[int, int] | None = None,
        side: str = "left",
        bold: bool = False,
    ) -> ctk.CTkButton:
        button = ctk.CTkButton(
            parent,
            text=text,
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold" if bold else "normal"),
            fg_color=fg_color,
            hover_color=hover_color,
            text_color=Colors.TEXT_ON_DARK,
            command=command,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        pack_kwargs: dict[str, Any] = {"side": side}
        if padx is not None:
            pack_kwargs["padx"] = padx
        button.pack(**pack_kwargs)
        return button

    def _render_review_task_tree(self, tree: ttk.Treeview, nodes: list[ReviewTaskNode], column_count: int) -> None:
        selected_key = self._get_selected_review_key(
            tree,
            {node.root_key for node in nodes if node.node_kind == "root"},
        )

        for item_id in tree.get_children():
            tree.delete(item_id)

        blank_values = tuple("" for _ in range(column_count))
        group_parent_ids: dict[str, str] = {}
        for group_key, label in self._get_review_group_specs():
            if not any(node.node_kind == "root" and node.group_key == group_key for node in nodes):
                continue
            group_id = self._build_group_node_id(group_key)
            group_parent_ids[group_key] = group_id
            tree.insert(
                "",
                "end",
                iid=group_id,
                text=label,
                values=blank_values,
                open=True,
                tags=("group", group_key),
            )

        for node in nodes:
            parent_id = group_parent_ids.get(node.group_key, "") if node.parent_id is None else node.parent_id
            tree.insert(
                parent_id,
                "end",
                iid=node.node_id,
                text=node.title,
                values=node.values,
                open=node.node_kind in {"root", "dependency-group"},
                tags=(node.node_kind, node.root_key, node.group_key),
            )

        UIUtils.refresh_treeview_alternating_rows(tree)

        if selected_key and tree.exists(selected_key):
            tree.selection_set(selected_key)
        else:
            first_root = next((node.root_key for node in nodes if node.node_kind == "root"), "")
            if first_root and tree.exists(first_root):
                tree.selection_set(first_root)

    def _build_online_review_task_nodes(self, review_entries: list[PendingInstallReviewEntry]) -> list[ReviewTaskNode]:
        nodes: list[ReviewTaskNode] = []
        required_by_map = self._collect_online_dependency_required_by(review_entries)
        sorted_entries = sorted(
            review_entries,
            key=lambda entry: str(getattr(getattr(entry, "pending", None), "project_name", "") or "").casefold(),
        )
        for review_entry in sorted_entries:
            pending = review_entry.pending
            root_key = self._build_pending_install_key(pending.project_id, getattr(pending.version, "version_id", ""))
            group_key = self._get_review_entry_group_key(review_entry)
            status_text = self._build_online_review_root_status_text(review_entry)
            root_values = (
                "是" if review_entry.enabled else "否",
                self._format_review_provider_label(review_entry.provider),
                pending.project_name,
                getattr(pending.version, "display_name", "未知版本"),
                review_entry.version_type or "-",
                status_text,
            )

            nodes.append(
                ReviewTaskNode(
                    node_id=root_key,
                    root_key=root_key,
                    group_key=group_key,
                    title="模組",
                    values=root_values,
                    node_kind="root",
                )
            )

            nodes.extend(
                self._build_dependency_review_nodes(
                    root_key=root_key,
                    group_key=group_key,
                    optional_group_values=("-", "-", "-", "-", "optional", "-"),
                    parent_name=pending.project_name,
                    dependency_plan=review_entry.dependency_plan,
                    required_by_map=required_by_map,
                    node_builder=lambda index, dependency_item, dependency_status, is_advisory, is_enabled, parent_id: (
                        self._build_online_dependency_task_node(
                            root_key=root_key,
                            group_key=group_key,
                            parent_values=root_values,
                            index=index,
                            dependency_item=dependency_item,
                            dependency_status=dependency_status,
                            is_advisory=is_advisory,
                            is_enabled=is_enabled,
                            parent_id=parent_id,
                        )
                    ),
                )
            )

            self._append_review_message_nodes(
                nodes,
                messages=review_entry.blocking_reasons,
                node_factory=lambda index, message: self._build_online_issue_task_node(
                    root_key=root_key,
                    group_key=group_key,
                    parent_values=root_values,
                    index=index,
                    message=message,
                ),
            )

            self._append_review_message_nodes(
                nodes,
                messages=review_entry.warning_messages,
                node_factory=lambda index, message: ReviewTaskNode(
                    node_id=f"{root_key}::warning::{index}",
                    root_key=root_key,
                    group_key=group_key,
                    parent_id=root_key,
                    title="提醒",
                    values=self._mask_redundant_review_values(
                        root_values,
                        ("-", "-", "-", "-", "-", message),
                    ),
                    node_kind="warning",
                    detail=message,
                ),
            )

            info_messages = self._dedupe_review_messages(
                [
                    *list(getattr(getattr(review_entry, "report", None), "notes", []) or []),
                    *list(getattr(getattr(review_entry, "dependency_plan", None), "notes", []) or []),
                ]
            )
            self._append_review_message_nodes(
                nodes,
                messages=info_messages,
                node_factory=lambda index, message: ReviewTaskNode(
                    node_id=f"{root_key}::info::{index}",
                    root_key=root_key,
                    group_key=group_key,
                    parent_id=root_key,
                    title="預檢",
                    values=self._mask_redundant_review_values(
                        root_values,
                        ("-", "-", "-", "-", "-", message),
                    ),
                    node_kind="warning",
                    detail=message,
                ),
            )

        return nodes

    def _build_local_update_task_nodes(self, review_entries: list[LocalUpdateReviewEntry]) -> list[ReviewTaskNode]:
        nodes: list[ReviewTaskNode] = []
        required_by_map = self._collect_local_dependency_required_by(review_entries)
        sorted_entries = sorted(
            review_entries,
            key=lambda entry: str(getattr(getattr(entry, "candidate", None), "project_name", "") or "").casefold(),
        )
        seen_root_keys: set[str] = set()
        for review_entry in sorted_entries:
            candidate = review_entry.candidate
            root_key = self._build_local_update_review_key(candidate)
            if root_key in seen_root_keys:
                continue
            seen_root_keys.add(root_key)
            group_key = self._get_review_entry_group_key(review_entry)
            status_text = "需先處理"
            if review_entry.runnable:
                status_text = "可更新" if review_entry.enabled else "已停用"
            elif str(getattr(candidate, "metadata_source", "") or "").strip().lower() == "unresolved":
                status_text = "需先識別"
            root_values = (
                "是" if review_entry.enabled else "否",
                candidate.current_version or "未知",
                candidate.target_version_name or "-",
                self._format_local_update_source_text(review_entry),
                status_text,
            )

            nodes.append(
                ReviewTaskNode(
                    node_id=root_key,
                    root_key=root_key,
                    group_key=group_key,
                    title=candidate.project_name,
                    values=root_values,
                    node_kind="root",
                )
            )

            metadata_sections: list[str] = []
            metadata_detail = self._build_local_update_metadata_detail(review_entry)
            if metadata_detail:
                metadata_sections.append(metadata_detail)

            metadata_note = str(getattr(candidate, "metadata_note", "") or "").strip()
            if metadata_note and metadata_note not in metadata_sections:
                metadata_sections.append(metadata_note)

            if metadata_sections:
                metadata_status_text = next(
                    (line.strip() for section in metadata_sections for line in section.splitlines() if line.strip()),
                    "Metadata 已更新",
                )
                nodes.append(
                    ReviewTaskNode(
                        node_id=f"{root_key}::metadata",
                        root_key=root_key,
                        group_key=group_key,
                        parent_id=root_key,
                        title="Metadata",
                        values=self._mask_redundant_review_values(
                            root_values,
                            (
                                "-",
                                candidate.current_version or "-",
                                candidate.target_version_name or "-",
                                self._format_metadata_source_label(getattr(candidate, "metadata_source", "")),
                                metadata_status_text,
                            ),
                        ),
                        node_kind="warning",
                        detail="\n\n".join(metadata_sections),
                    )
                )

            nodes.extend(
                self._build_dependency_review_nodes(
                    root_key=root_key,
                    group_key=group_key,
                    optional_group_values=("-", "-", "-", "可選依賴", "-"),
                    parent_name=candidate.project_name,
                    dependency_plan=review_entry.dependency_plan,
                    required_by_map=required_by_map,
                    node_builder=lambda index, dependency_item, dependency_status, is_advisory, is_enabled, parent_id: (
                        self._build_local_dependency_task_node(
                            root_key=root_key,
                            group_key=group_key,
                            parent_values=root_values,
                            index=index,
                            dependency_item=dependency_item,
                            dependency_status=dependency_status,
                            is_advisory=is_advisory,
                            is_enabled=is_enabled,
                            parent_id=parent_id,
                        )
                    ),
                )
            )

            self._append_review_message_nodes(
                nodes,
                messages=review_entry.blocking_reasons,
                node_factory=lambda index, message: self._build_local_issue_task_node(
                    root_key=root_key,
                    group_key=group_key,
                    parent_values=root_values,
                    index=index,
                    message=message,
                ),
            )

            warnings = list(getattr(getattr(candidate, "report", None), "warnings", []) or [])
            notes = list(getattr(candidate, "notes", []) or [])
            self._append_review_message_nodes(
                nodes,
                messages=[*warnings, *notes],
                node_factory=lambda index, message: ReviewTaskNode(
                    node_id=f"{root_key}::note::{index}",
                    root_key=root_key,
                    group_key=group_key,
                    parent_id=root_key,
                    title="提醒",
                    values=self._mask_redundant_review_values(
                        root_values,
                        (
                            "-",
                            candidate.current_version or "-",
                            candidate.target_version_name or "-",
                            "-",
                            message,
                        ),
                    ),
                    node_kind="warning",
                    detail=message,
                ),
            )

            plan_notes = self._dedupe_review_messages(
                list(getattr(getattr(review_entry, "dependency_plan", None), "notes", []) or [])
            )
            self._append_review_message_nodes(
                nodes,
                messages=plan_notes,
                node_factory=lambda index, message: ReviewTaskNode(
                    node_id=f"{root_key}::plan::{index}",
                    root_key=root_key,
                    group_key=group_key,
                    parent_id=root_key,
                    title="預檢",
                    values=self._mask_redundant_review_values(
                        root_values,
                        (
                            "-",
                            candidate.current_version or "-",
                            candidate.target_version_name or "-",
                            "-",
                            message,
                        ),
                    ),
                    node_kind="warning",
                    detail=message,
                ),
            )

        return nodes

    def _get_supported_online_loader(self) -> tuple[str | None, str | None]:
        """回傳目前伺服器可用於線上模組功能的 loader；若不支援則附帶提示訊息。"""
        if not self.current_server:
            return None, "請先選擇伺服器後再使用線上模組功能"

        raw_loader = str(getattr(self.current_server, "loader_type", "") or "").strip()
        normalized_loader = raw_loader.lower()
        if normalized_loader not in SUPPORTED_ONLINE_MOD_LOADERS:
            loader_display = raw_loader or "未設定"
            return None, f"線上模組功能目前僅支援 Fabric 與 Forge，當前伺服器載入器為：{loader_display}"
        return normalized_loader, None

    def _refresh_online_queue_button(self) -> None:
        """更新安裝清單按鈕文字。"""
        if hasattr(self, "online_queue_button") and self.online_queue_button:
            self.online_queue_button.configure(text=f"🧺 安裝清單 ({len(self.pending_online_installs)})")

    @staticmethod
    def _build_pending_install_key(project_id: str, version_id: str) -> str:
        return f"{str(project_id or '').strip()}::{str(version_id or '').strip()}"

    def _get_current_installed_mods(self) -> list[Any]:
        manager = self.mod_manager
        if not manager:
            return list(self.local_mods)
        try:
            return manager.get_mod_list()
        except Exception as e:
            logger.error(f"讀取本地模組列表失敗: {e}")
            return list(self.local_mods)

    @staticmethod
    def _build_installed_mod_simulation_item(
        project_id: str, project_name: str, filename: str, version_name: str
    ) -> Any:
        normalized_name = str(project_name or project_id or filename or "未知模組").strip() or "未知模組"
        normalized_filename = str(filename or normalized_name).strip() or normalized_name
        return SimpleNamespace(
            platform_id=str(project_id or "").strip(),
            id=normalized_name,
            name=normalized_name,
            filename=normalized_filename,
            version=str(version_name or "").strip(),
        )

    def _add_pending_online_install(self, pending: PendingOnlineInstall) -> None:
        """加入待安裝清單，若同版本已存在則覆蓋。"""
        pending_key = self._build_pending_install_key(pending.project_id, getattr(pending.version, "version_id", ""))
        remaining_items = [
            item
            for item in self.pending_online_installs
            if self._build_pending_install_key(item.project_id, getattr(item.version, "version_id", "")) != pending_key
        ]
        remaining_items.append(pending)
        self.pending_online_installs = remaining_items
        self._refresh_online_queue_button()
        self.update_status(
            f"已加入安裝清單：{pending.project_name} ({getattr(pending.version, 'display_name', '未知版本')})"
        )

    def _prepare_online_install_review_entries(
        self,
    ) -> list[PendingInstallReviewEntry]:
        """以目前本地模組狀態重新驗證待安裝清單。"""
        minecraft_version, loader_type, loader_version = self._get_current_modrinth_context()
        simulated_installed_mods = list(self._get_current_installed_mods())
        review_entries: list[PendingInstallReviewEntry] = []

        for pending in self.pending_online_installs:
            dependency_project_ids = {
                str(dependency.get("project_id", "") or "").strip()
                for dependency in (getattr(pending.version, "dependencies", []) or [])
                if isinstance(dependency, dict) and str(dependency.get("project_id", "") or "").strip()
            }
            dependency_names = resolve_modrinth_project_names(dependency_project_ids)
            report = analyze_mod_version_compatibility(
                pending.version,
                project_id=pending.project_id,
                project_name=pending.project_name,
                minecraft_version=minecraft_version,
                loader=loader_type,
                loader_version=loader_version,
                installed_mods=simulated_installed_mods,
                dependency_names=dependency_names,
            )
            dependency_plan = build_required_dependency_install_plan(
                pending.version,
                minecraft_version=minecraft_version,
                loader=loader_type,
                loader_version=loader_version,
                installed_mods=simulated_installed_mods,
                root_project_id=pending.project_id,
                root_project_name=pending.project_name,
            )
            blocking_reasons = [
                *list(getattr(report, "hard_errors", []) or []),
                *list(getattr(dependency_plan, "unresolved_required", []) or []),
            ]
            review_entry = PendingInstallReviewEntry(
                pending=pending,
                report=report,
                dependency_plan=dependency_plan,
                blocking_reasons=blocking_reasons,
                warning_messages=list(getattr(report, "warnings", []) or []),
                enabled=not blocking_reasons,
                provider=str(getattr(pending.version, "provider", "modrinth") or "modrinth"),
                version_type=str(getattr(pending.version, "version_type", "") or ""),
                date_published=str(getattr(pending.version, "date_published", "") or ""),
                changelog=str(getattr(pending.version, "changelog", "") or ""),
            )
            review_entries.append(review_entry)

            if review_entry.actionable:
                self._append_enabled_dependency_simulations(simulated_installed_mods, dependency_plan)

                primary_file = getattr(pending.version, "primary_file", None) or {}
                self._append_simulated_installed_mod(
                    simulated_installed_mods,
                    self._build_installed_mod_simulation_item(
                        pending.project_id,
                        pending.project_name,
                        str(primary_file.get("filename", "") or pending.project_name),
                        str(
                            getattr(pending.version, "version_number", "")
                            or getattr(pending.version, "display_name", "")
                        ),
                    ),
                )

        return review_entries

    def search_online_mods(self, _event=None) -> None:
        """載入 Modrinth 線上模組；有關鍵字時搜尋，空白時瀏覽推薦清單。"""
        self._load_online_mods(force=True, show_warning=True)

    def refresh_browse_list(self) -> None:
        """重新整理線上模組列表。"""
        self._refresh_online_results_summary()
        if not self.browse_tree:
            return

        logger.debug(f"重新整理線上模組列表: result_count={len(self.online_mods)}")

        for item in self.browse_tree.get_children():
            self.browse_tree.delete(item)

        for mod in self.online_mods:
            self.browse_tree.insert(
                "",
                "end",
                values=self._build_online_browse_row(mod),
                tags=(getattr(mod, "project_id", ""), getattr(mod, "slug", ""), getattr(mod, "url", "")),
            )
            UIUtils.refresh_treeview_alternating_rows(self.browse_tree)

    def show_browse_context_menu(self, event) -> None:
        """顯示線上模組右鍵選單。"""
        if not self.browse_tree:
            return

        selection = self.browse_tree.selection()
        if not selection:
            return

        menu = tk.Menu(
            self.parent,
            tearoff=0,
            font=FontManager.get_font("Microsoft JhengHei", FontSize.LARGE),
        )
        menu.add_command(label="⬇️ 安裝模組", command=self.install_online_mod)
        menu.add_separator()
        menu.add_command(label="📋 複製模組資訊", command=self.copy_online_mod_info)
        menu.add_command(label="🌐 開啟模組頁面", command=self.open_mod_webpage)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def install_online_mod(self, _event=None) -> None:
        """取得模組版本列表並讓使用者選擇要安裝的版本。"""
        manager = self.mod_manager
        if not self.current_server or not manager:
            UIUtils.show_warning("警告", "請先選擇伺服器後再安裝模組", self.parent)
            return
        if not self.browse_tree:
            return

        selection = self.browse_tree.selection()
        if not selection:
            UIUtils.show_warning("警告", "請先從線上列表選取模組", self.parent)
            return

        item = selection[0]
        tags = self.browse_tree.item(item, "tags")
        project_id = tags[0] if tags else ""
        selected_mod = self._online_mod_index.get(project_id)
        if not selected_mod:
            UIUtils.show_error("錯誤", "找不到選取的線上模組資料", self.parent)
            return

        minecraft_version, _, loader_version = self._get_current_modrinth_context()
        loader_type, warning_message = self._get_supported_online_loader()
        if warning_message:
            UIUtils.show_warning("目前不支援", warning_message, self.parent)
            return

        def load_versions_task() -> None:
            try:
                self.update_status_safe(f"正在讀取 {selected_mod.name} 的版本列表...")
                versions = get_mod_versions(selected_mod.project_id, minecraft_version, loader_type)
                if not versions:
                    versions = get_mod_versions(selected_mod.project_id)

                installed_mods = manager.get_mod_list()
                dependency_project_ids = {
                    str(dependency.get("project_id", "") or "").strip()
                    for version in versions
                    for dependency in (getattr(version, "dependencies", []) or [])
                    if isinstance(dependency, dict) and str(dependency.get("project_id", "") or "").strip()
                }
                dependency_names = resolve_modrinth_project_names(dependency_project_ids)
                version_reports = [
                    analyze_mod_version_compatibility(
                        version,
                        project_id=selected_mod.project_id,
                        project_name=selected_mod.name,
                        minecraft_version=minecraft_version,
                        loader=loader_type,
                        loader_version=loader_version,
                        installed_mods=installed_mods,
                        dependency_names=dependency_names,
                    )
                    for version in versions
                ]

                def open_dialog() -> None:
                    if not versions:
                        UIUtils.show_warning("找不到版本", f"{selected_mod.name} 目前查無可下載版本", self.parent)
                        return
                    self._show_version_install_dialog(selected_mod, versions, version_reports)

                self.ui_queue.put(open_dialog)
                self.update_status_safe(f"已載入 {selected_mod.name} 的 {len(versions)} 個版本")
            except Exception as e:
                logger.error(f"取得模組版本失敗: {e}\n{traceback.format_exc()}")
                self.update_status_safe(f"取得模組版本失敗: {e}")

        UIUtils.run_async(load_versions_task)

    def _show_version_install_dialog(
        self, mod: Any, versions: list[Any], version_reports: list[Any] | None = None
    ) -> None:
        """顯示版本選擇對話框。"""
        dialog = UIUtils.create_toplevel_dialog(
            self.parent,
            f"安裝模組 - {mod.name}",
            width=920,
            height=780,
            make_modal=True,
            bind_icon=True,
            center_on_parent=True,
            delay_ms=250,
            min_width=900,
            min_height=760,
            max_width=FontManager.get_dpi_scaled_size(1180),
            max_height=FontManager.get_dpi_scaled_size(900),
            native_window=True,
            use_transient_for_modal=False,
        )

        main_frame = ctk.CTkFrame(dialog)
        main_frame.pack(fill="both", expand=True, padx=18, pady=18)

        title = ctk.CTkLabel(
            main_frame,
            text=f"選擇要安裝的版本：{mod.name}",
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
        )
        title.pack(anchor="w", padx=12, pady=(12, 10))

        filter_label = ctk.CTkLabel(
            main_frame,
            text=self._get_online_version_dialog_hint_text(),
            font=FontManager.get_font(size=FontSize.SMALL_PLUS),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=FontManager.get_dpi_scaled_size(760),
        )
        filter_label.pack(fill="x", padx=12, pady=(0, 8))

        tree_container = ctk.CTkFrame(main_frame)
        tree_container.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        tree_style = UIUtils.configure_treeview_list_style(
            "OnlineVersionList",
            body_font=FontManager.get_font(size=FontSize.INPUT),
            heading_font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            rowheight=int(25 * FontManager.get_scale_factor()),
        )
        columns = ("version", "minecraft", "loader", "status", "date")
        version_tree = ttk.Treeview(
            tree_container,
            columns=columns,
            show="headings",
            height=12,
            style=tree_style,
        )
        column_config = {
            "version": ("版本", 150),
            "minecraft": ("Minecraft", 150),
            "loader": ("Loader", 120),
            "status": ("狀態", 140),
            "date": ("發布時間", 170),
        }
        for col, (text, width) in column_config.items():
            version_tree.heading(col, text=text, anchor="w")
            version_tree.column(col, width=width, minwidth=60, anchor="w", stretch=(col == "status"))
        UIUtils.bind_treeview_header_auto_fit(
            version_tree,
            heading_font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            body_font=FontManager.get_font(size=FontSize.INPUT),
            stretch_columns={"status"},
        )

        version_scroll = ttk.Scrollbar(tree_container, orient="vertical", command=version_tree.yview)
        version_tree.configure(yscrollcommand=version_scroll.set)
        version_tree.grid(row=0, column=0, sticky="nsew")
        version_scroll.grid(row=0, column=1, sticky="ns")
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        for index, version in enumerate(versions):
            published = str(getattr(version, "date_published", "") or "")
            report = None
            if version_reports and index < len(version_reports):
                report = version_reports[index]
            version_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    getattr(version, "display_name", "未知版本"),
                    ", ".join(getattr(version, "game_versions", []) or []) or "-",
                    ", ".join(getattr(version, "loaders", []) or []) or "-",
                    self._get_online_version_status_text(report),
                    published.replace("T", " ").replace("Z", "")[:16] if published else "-",
                ),
            )

        if versions:
            version_tree.selection_set("0")
        UIUtils.refresh_treeview_alternating_rows(version_tree)

        summary_label = ctk.CTkLabel(
            main_frame,
            text="版本分析",
            font=FontManager.get_font(size=FontSize.HEADING_SMALL, weight="bold"),
        )
        summary_label.pack(anchor="w", padx=12, pady=(0, 6))

        summary_box = self._create_review_summary_box(main_frame, height=138)

        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x", padx=12, pady=(0, 8))

        install_button = ctk.CTkButton(
            button_frame,
            text="➕ 加入安裝清單",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            fg_color=Colors.BUTTON_SUCCESS,
            hover_color=Colors.BUTTON_SUCCESS_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            command=lambda: self._install_online_version(mod, versions, version_tree, dialog, version_reports),
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        install_button.pack(side="left")

        open_button = ctk.CTkButton(
            button_frame,
            text="🧺 查看清單",
            font=FontManager.get_font(size=FontSize.LARGE),
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            command=self.show_online_install_queue,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        open_button.pack(side="left", padx=(10, 0))

        project_page_url = self._resolve_online_mod_project_page_url(mod)
        project_page_button = ctk.CTkButton(
            button_frame,
            text="🌐 專案頁面",
            font=FontManager.get_font(size=FontSize.LARGE),
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            command=lambda: self._open_project_page(project_page_url, dialog),
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
            state="normal" if project_page_url else "disabled",
        )
        project_page_button.pack(side="left", padx=(10, 0))

        close_button = ctk.CTkButton(
            button_frame,
            text="關閉",
            font=FontManager.get_font(size=FontSize.LARGE),
            fg_color=Colors.BUTTON_SECONDARY,
            hover_color=Colors.BUTTON_SECONDARY_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            command=dialog.destroy,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        close_button.pack(side="right")

        def refresh_version_report(_event=None) -> None:
            selection = version_tree.selection()
            if not selection:
                return

            selected_index = int(selection[0])
            selected_version = versions[selected_index]
            report = None
            if version_reports and selected_index < len(version_reports):
                report = version_reports[selected_index]

            summary_box.configure(state="normal")
            summary_box.delete("1.0", "end")
            summary_box.insert("1.0", self._format_online_version_report(selected_version, report))
            summary_box.configure(state="disabled")
            install_button.configure(
                state="normal" if report is None or getattr(report, "compatible", True) else "disabled"
            )

        version_tree.bind("<<TreeviewSelect>>", refresh_version_report)
        refresh_version_report()
        UIUtils.schedule_toplevel_layout_refresh(
            dialog,
            min_width=900,
            min_height=760,
            max_width=FontManager.get_dpi_scaled_size(1180),
            max_height=FontManager.get_dpi_scaled_size(900),
            parent=self.parent,
        )

    def _install_online_version(
        self,
        mod: Any,
        versions: list[Any],
        version_tree: ttk.Treeview,
        dialog,
        version_reports: list[Any] | None = None,
    ) -> None:
        """將選取版本加入待安裝清單。"""
        selection = version_tree.selection()
        if not selection:
            UIUtils.show_warning("警告", "請先選擇要安裝的版本", dialog)
            return

        selected_index = int(selection[0])
        version = versions[selected_index]
        report = None
        if version_reports and selected_index < len(version_reports):
            report = version_reports[selected_index]

        if report is not None and not getattr(report, "compatible", True):
            UIUtils.show_error("版本不相容", self._format_online_version_report(version, report), dialog)
            return

        file_info = getattr(version, "primary_file", None)
        if not file_info:
            UIUtils.show_error("錯誤", "此版本沒有可下載的 JAR 檔案", dialog)
            return

        download_url = str(file_info.get("url", "") or "")
        filename = str(file_info.get("filename", "") or "")
        if not download_url or not filename:
            UIUtils.show_error("錯誤", "無法取得下載連結或檔名", dialog)
            return

        self._add_pending_online_install(
            PendingOnlineInstall(
                project_id=str(getattr(mod, "project_id", "") or "").strip(),
                project_name=str(getattr(mod, "name", "未知模組") or "未知模組").strip(),
                version=version,
                report=report,
                homepage_url=str(getattr(mod, "homepage_url", "") or "").strip(),
                source_url=str(getattr(mod, "url", "") or "").strip(),
                server_side=str(getattr(mod, "server_side", "") or "").strip(),
                client_side=str(getattr(mod, "client_side", "") or "").strip(),
            )
        )
        dialog.destroy()

    def _format_pending_install_review_text(self, review_entry: PendingInstallReviewEntry) -> str:
        """格式化待安裝項目的 review 內容。"""
        lines = [self._format_online_version_report(review_entry.pending.version, review_entry.report)]

        lines.append("")
        lines.extend(self._build_pending_install_summary_lines(review_entry))
        client_install_reminder = self._build_client_install_reminder_line(
            getattr(review_entry.pending, "server_side", ""),
            getattr(review_entry.pending, "client_side", ""),
        )
        if client_install_reminder:
            lines.append(client_install_reminder)
        lines.append("")
        lines.append(f"執行狀態：{'已啟用' if review_entry.enabled else '已停用'}")

        dependency_plan = getattr(review_entry, "dependency_plan", None)
        self._append_dependency_review_sections(lines, dependency_plan, "將自動安裝的必要依賴：")

        if review_entry.blocking_reasons:
            self._append_review_section(lines, "需先處理：", review_entry.blocking_reasons, max_items=3)
        elif review_entry.warning_messages:
            self._append_review_section(lines, "安裝前提醒：", review_entry.warning_messages, max_items=3)

        self._append_plan_note_section(lines, dependency_plan)

        return "\n".join(lines)

    def _remove_selected_pending_online_installs(self, queue_tree, dialog) -> None:
        """從待安裝清單移除選取的根項目。"""
        selected_root_keys = self._collect_selected_root_keys(queue_tree)

        if not selected_root_keys:
            return

        self.pending_online_installs = [
            item
            for item in self.pending_online_installs
            if self._build_pending_install_key(item.project_id, getattr(item.version, "version_id", ""))
            not in selected_root_keys
        ]
        self._refresh_online_queue_button()
        dialog.destroy()
        if self.pending_online_installs:
            self.show_online_install_queue()

    def _clear_pending_online_installs(self, dialog) -> None:
        """清空待安裝清單。"""
        self.pending_online_installs = []
        self._refresh_online_queue_button()
        dialog.destroy()

    def _install_pending_online_install_queue(self, dialog) -> None:
        """執行待安裝清單中的所有可安裝項目。"""
        manager = self.mod_manager
        if not manager:
            UIUtils.show_error("錯誤", "模組管理器未初始化", self.parent)
            return

        review_entries = self._prepare_online_install_review_entries()
        actionable_entries = [entry for entry in review_entries if entry.actionable]
        blocked_entries = [entry for entry in review_entries if not entry.runnable]

        if not actionable_entries:
            UIUtils.show_warning("無法安裝", "安裝清單中的項目目前都無法安裝，請先處理相容性或依賴問題。", dialog)
            return

        if blocked_entries:
            proceed = UIUtils.ask_yes_no_cancel(
                "部分項目無法安裝",
                (
                    f"目前有 {len(blocked_entries)} 個項目仍有阻擋原因。\n"
                    f"將只安裝其餘 {len(actionable_entries)} 個可安裝項目，未完成項目會保留在清單中。\n\n是否繼續？"
                ),
                parent=dialog,
                show_cancel=False,
            )
            if proceed is not True:
                return

        dialog.destroy()

        completion_notes = self._format_completion_notes(
            [
                *[
                    message
                    for entry in actionable_entries
                    for message in list(getattr(entry, "warning_messages", []) or [])
                ],
                *[
                    message
                    for entry in actionable_entries
                    for message in list(getattr(getattr(entry, "report", None), "notes", []) or [])
                ],
                *[
                    message
                    for entry in actionable_entries
                    for message in list(getattr(getattr(entry, "dependency_plan", None), "notes", []) or [])
                ],
            ]
        )

        def install_task() -> None:
            succeeded_keys: set[str] = set()
            total_steps = sum(
                len(self._get_enabled_dependency_install_items(entry.dependency_plan)) + 1
                for entry in actionable_entries
            )
            current_step = 0

            def make_step_progress_callback(step_index: int):
                def _callback(downloaded: int, total: int) -> None:
                    fraction = (downloaded / total) if total > 0 else 0.0
                    self.update_progress_safe((step_index + fraction) / max(1, total_steps))

                return _callback

            try:
                for review_entry in actionable_entries:
                    pending = review_entry.pending
                    for dependency_item in self._get_enabled_dependency_install_items(review_entry.dependency_plan):
                        self.update_status_safe(f"正在安裝必要依賴：{dependency_item.project_name}")
                        installed_dependency = manager.install_remote_mod_file(
                            dependency_item.download_url,
                            dependency_item.filename,
                            progress_callback=make_step_progress_callback(current_step),
                        )
                        if installed_dependency is None:
                            raise RuntimeError(f"必要依賴安裝失敗：{dependency_item.project_name}")
                        current_step += 1

                    primary_file = getattr(pending.version, "primary_file", None) or {}
                    filename = str(primary_file.get("filename", "") or "").strip()
                    download_url = str(primary_file.get("url", "") or "").strip()
                    self.update_status_safe(
                        f"正在安裝模組：{pending.project_name} ({getattr(pending.version, 'display_name', '未知版本')})"
                    )
                    installed_path = manager.install_remote_mod_file(
                        download_url,
                        filename,
                        progress_callback=make_step_progress_callback(current_step),
                    )
                    if installed_path is None:
                        raise RuntimeError(f"模組安裝失敗：{pending.project_name}")
                    current_step += 1
                    succeeded_keys.add(
                        self._build_pending_install_key(pending.project_id, getattr(pending.version, "version_id", ""))
                    )

                self.pending_online_installs = [
                    item
                    for item in self.pending_online_installs
                    if self._build_pending_install_key(item.project_id, getattr(item.version, "version_id", ""))
                    not in succeeded_keys
                ]
                self._refresh_online_queue_button()
                self.update_progress_safe(1.0)
                self.update_status_safe(f"已完成 {len(succeeded_keys)} 個安裝項目")
                self.ui_queue.put(self.load_local_mods)
                self.ui_queue.put(
                    lambda: UIUtils.show_info(
                        "安裝完成",
                        (
                            f"已安裝 {len(succeeded_keys)} 個排程項目。"
                            + (
                                f"\n仍有 {len(self.pending_online_installs)} 個項目保留在安裝清單中。"
                                if self.pending_online_installs
                                else ""
                            )
                            + completion_notes
                        ),
                        self.parent,
                    )
                )
            except Exception as e:
                logger.error(f"批次安裝線上模組失敗: {e}\n{traceback.format_exc()}")
                self.update_status_safe(f"批次安裝失敗: {e}")
                self.ui_queue.put(
                    lambda msg=str(e): UIUtils.show_error("安裝失敗", f"無法完成安裝：{msg}", self.parent)
                )
            finally:
                self.update_progress_safe(0)

        UIUtils.run_async(install_task)

    def show_online_install_queue(self) -> None:
        """顯示待安裝清單與最終 review。"""
        if not self.pending_online_installs:
            UIUtils.show_info("安裝清單", "目前安裝清單是空的。", self.parent)
            return

        review_entries = self._prepare_online_install_review_entries()
        review_entry_map = {
            self._build_pending_install_key(
                entry.pending.project_id, getattr(entry.pending.version, "version_id", "")
            ): entry
            for entry in review_entries
        }
        global_review_notes = self._collect_online_review_global_notes(review_entries)

        dialog = UIUtils.create_toplevel_dialog(
            self.parent,
            "安裝清單 Review",
            width=1040,
            height=860,
            make_modal=True,
            bind_icon=True,
            center_on_parent=True,
            delay_ms=250,
            min_width=1000,
            min_height=820,
            max_width=FontManager.get_dpi_scaled_size(1280),
            max_height=FontManager.get_dpi_scaled_size(960),
            native_window=True,
            use_transient_for_modal=False,
        )

        main_frame = ctk.CTkFrame(dialog)
        main_frame.pack(fill="both", expand=True, padx=18, pady=18)

        title = ctk.CTkLabel(
            main_frame,
            text="待安裝模組與依賴檢查",
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
        )
        title.pack(anchor="w", padx=12, pady=(12, 8))

        subtitle = ctk.CTkLabel(
            main_frame,
            text=self._build_online_install_review_subtitle(
                sum(1 for entry in review_entries if entry.actionable),
                self._count_blocked_entries(review_entries),
            ),
            font=FontManager.get_font(size=FontSize.SMALL_PLUS),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=FontManager.get_dpi_scaled_size(860),
        )
        subtitle.pack(fill="x", padx=12, pady=(0, 6))

        overview_label = ctk.CTkLabel(
            main_frame,
            text="",
            font=FontManager.get_font(size=FontSize.NORMAL),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=FontManager.get_dpi_scaled_size(860),
        )
        overview_label.pack(fill="x", padx=12, pady=(0, 6))

        tree_container = ctk.CTkFrame(main_frame)
        tree_container.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        queue_tree = ttk.Treeview(
            tree_container,
            columns=("run", "source", "name", "version", "channel", "status"),
            show="tree headings",
            height=12,
            style=UIUtils.configure_treeview_list_style(
                "InstallQueueList",
                body_font=FontManager.get_font(size=FontSize.INPUT),
                heading_font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
                rowheight=int(25 * FontManager.get_scale_factor()),
            ),
        )
        queue_tree.heading("#0", text="項目")
        queue_tree.column("#0", width=120, minwidth=90, anchor="w", stretch=False)
        queue_tree.heading("run", text="執行")
        queue_tree.column("run", width=80, minwidth=60, anchor="center", stretch=False)
        queue_tree.heading("source", text="來源")
        queue_tree.column("source", width=100, minwidth=80, anchor="w", stretch=False)
        queue_tree.heading("name", text="名稱")
        queue_tree.column("name", width=240, minwidth=160, anchor="w", stretch=False)
        queue_tree.heading("version", text="版本")
        queue_tree.column("version", width=180, minwidth=120, anchor="w", stretch=False)
        queue_tree.heading("channel", text="類型")
        queue_tree.column("channel", width=100, minwidth=80, anchor="w", stretch=False)
        queue_tree.heading("status", text="狀態")
        queue_tree.column("status", width=170, minwidth=130, anchor="w", stretch=True)
        UIUtils.bind_treeview_header_auto_fit(
            queue_tree,
            include_tree_column=True,
            heading_font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            body_font=FontManager.get_font(size=FontSize.INPUT),
            stretch_columns={"status"},
        )

        queue_scroll = ttk.Scrollbar(tree_container, orient="vertical", command=queue_tree.yview)
        queue_tree.configure(yscrollcommand=queue_scroll.set)
        queue_tree.grid(row=0, column=0, sticky="nsew")
        queue_scroll.grid(row=0, column=1, sticky="ns")
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        review_root_keys = set(review_entry_map)

        def refresh_queue_tree() -> None:
            self._render_review_task_tree(
                queue_tree, self._build_online_review_task_nodes(review_entries), column_count=6
            )

        summary_box = self._create_review_summary_box(main_frame, height=138)
        self._bind_vertical_mousewheel(queue_tree, scroll_callback=queue_tree.yview_scroll)
        summary_text_widget = getattr(summary_box, "_textbox", summary_box)
        self._bind_vertical_mousewheel(summary_box, scroll_callback=summary_text_widget.yview_scroll)
        self._bind_vertical_mousewheel(summary_text_widget, scroll_callback=summary_text_widget.yview_scroll)

        def refresh_queue_status_banner() -> None:
            review_nodes = self._build_online_review_task_nodes(review_entries)
            actionable_count = sum(1 for entry in review_entries if entry.actionable)
            blocked_count = self._count_blocked_entries(review_entries)
            subtitle.configure(text=self._build_online_install_review_subtitle(actionable_count, blocked_count))
            overview_label.configure(
                text=self._format_review_overview_text(
                    review_entries,
                    review_nodes,
                    action_label="安裝",
                    global_notes=global_review_notes,
                )
            )

        def refresh_queue_summary(_event=None) -> None:
            selected_root_key = self._get_selected_review_key(queue_tree, review_root_keys)
            review_entry = review_entry_map.get(selected_root_key)
            if not review_entry:
                return

            summary_box.configure(state="normal")
            summary_box.delete("1.0", "end")
            summary_box.insert("1.0", self._format_pending_install_review_text(review_entry))
            summary_box.configure(state="disabled")

        def open_selected_queue_project_page() -> None:
            selected_root_key = self._get_selected_review_key(queue_tree, review_root_keys)
            review_entry = review_entry_map.get(selected_root_key)
            project_page_url = (
                self._resolve_pending_install_review_project_page_url(review_entry) if review_entry else ""
            )
            self._open_project_page(project_page_url, dialog)

        queue_tree.bind("<<TreeviewSelect>>", refresh_queue_summary)
        refresh_queue_tree()
        refresh_queue_summary()

        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x", padx=12, pady=(0, 8))

        install_button = self._create_review_action_button(
            button_frame,
            text="",
            fg_color=Colors.BUTTON_SUCCESS,
            hover_color=Colors.BUTTON_SUCCESS_HOVER,
            command=lambda: self._install_pending_online_install_queue(dialog),
            bold=True,
        )

        def refresh_queue_action_button() -> None:
            actionable_count = sum(1 for entry in review_entries if entry.actionable)
            install_button.configure(
                text=f"⬇️ 安裝 {actionable_count} 個可安裝項目",
                state="normal" if actionable_count else "disabled",
            )

        def refresh_queue_project_page_button(_event=None) -> None:
            selected_root_key = self._get_selected_review_key(queue_tree, review_root_keys)
            review_entry = review_entry_map.get(selected_root_key)
            project_page_button.configure(
                state="normal"
                if review_entry and self._resolve_pending_install_review_project_page_url(review_entry)
                else "disabled"
            )

        self._create_review_action_button(
            button_frame,
            text="移除選取項目",
            fg_color=Colors.BUTTON_WARNING,
            hover_color=Colors.BUTTON_WARNING_HOVER,
            command=lambda: self._remove_selected_pending_online_installs(queue_tree, dialog),
            padx=(10, 0),
        )

        self._create_review_action_button(
            button_frame,
            text="清空清單",
            fg_color=Colors.BUTTON_SECONDARY,
            hover_color=Colors.BUTTON_SECONDARY_HOVER,
            command=lambda: self._clear_pending_online_installs(dialog),
            padx=(10, 0),
        )

        project_page_button = self._create_review_action_button(
            button_frame,
            text="開啟專案頁面",
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            command=open_selected_queue_project_page,
            padx=(10, 0),
        )

        self._create_review_action_button(
            button_frame,
            text="關閉",
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            command=dialog.destroy,
            side="right",
        )

        refresh_queue_status_banner()
        refresh_queue_action_button()
        refresh_queue_project_page_button()
        queue_tree.bind("<<TreeviewSelect>>", refresh_queue_project_page_button, add="+")

        UIUtils.schedule_toplevel_layout_refresh(
            dialog,
            min_width=1000,
            min_height=820,
            max_width=FontManager.get_dpi_scaled_size(1280),
            max_height=FontManager.get_dpi_scaled_size(960),
            parent=self.parent,
        )

    def _ensure_local_mod_project_ids(self, local_mods: list[Any]) -> None:
        """盡量補齊本地模組的 Modrinth project id，供更新檢查使用。"""
        for local_mod in local_mods:
            if str(getattr(local_mod, "platform_id", "") or "").strip():
                continue

            enhanced = self.enhanced_mods_cache.get(getattr(local_mod, "filename", ""))
            if enhanced is None:
                enhanced = enhance_local_mod(
                    getattr(local_mod, "filename", ""),
                    platform_id=getattr(local_mod, "platform_id", ""),
                    platform_slug=getattr(local_mod, "platform_slug", ""),
                    local_name=getattr(local_mod, "name", ""),
                )
                if enhanced:
                    self.enhanced_mods_cache[getattr(local_mod, "filename", "")] = enhanced

            project_id = str(getattr(enhanced, "project_id", "") or "").strip() if enhanced else ""
            if project_id:
                local_mod.platform_id = project_id
                self._cache_local_provider_metadata(local_mod, enhanced)

    def _cache_local_provider_metadata(self, mod: Any, enhanced: Any | None = None) -> None:
        """將本地模組已解析出的 provider metadata 回寫到索引。"""
        manager = self.mod_manager
        if not manager:
            return

        file_path_raw = str(getattr(mod, "file_path", "") or "").strip()
        if not file_path_raw:
            return

        resolved_project_id = str(getattr(enhanced, "project_id", "") or getattr(mod, "platform_id", "") or "").strip()
        slug = str(getattr(enhanced, "slug", "") or getattr(mod, "platform_slug", "") or "").strip()
        project_name = str(getattr(enhanced, "name", "") or getattr(mod, "name", "") or "").strip()
        provider_metadata = {
            "platform": "modrinth" if resolved_project_id else "local",
            "project_id": resolved_project_id,
            "slug": slug,
            "project_name": project_name,
        }

        manager.index_manager.cache_provider_metadata(Path(file_path_raw), provider_metadata)

    def _prepare_local_update_review_entries(
        self,
        update_plan: LocalModUpdatePlan,
        root_enabled_overrides: dict[str, bool] | None = None,
        advisory_enabled_overrides: dict[tuple[str, tuple[str, str]], bool] | None = None,
    ) -> list[LocalUpdateReviewEntry]:
        """建立本地模組更新 review 項目，並依序模擬更新後狀態避免重複依賴。"""
        minecraft_version, loader_type, loader_version = self._get_current_modrinth_context()
        simulated_installed_mods = list(self._get_current_installed_mods())
        review_entries: list[LocalUpdateReviewEntry] = []

        for candidate in update_plan.candidates:
            root_key = str(candidate.project_id or "").strip()
            dependency_plan = SimpleNamespace(items=[], unresolved_required=[])
            blocking_reasons = [*list(getattr(candidate, "hard_errors", []) or [])]
            non_blocking_warnings = self._dedupe_review_messages(
                [
                    *list(getattr(candidate, "current_issues", []) or []),
                    *list(getattr(candidate, "dependency_issues", []) or []),
                ]
            )

            target_version = getattr(candidate, "target_version", None)
            if getattr(candidate, "update_available", False) and target_version is not None:
                dependency_plan = build_required_dependency_install_plan(
                    target_version,
                    minecraft_version=minecraft_version,
                    loader=loader_type,
                    loader_version=loader_version,
                    installed_mods=simulated_installed_mods,
                    root_project_id=candidate.project_id,
                    root_project_name=candidate.project_name,
                )
                self._apply_review_advisory_enabled_overrides(dependency_plan, root_key, advisory_enabled_overrides)
                blocking_reasons.extend(list(getattr(dependency_plan, "unresolved_required", []) or []))

            review_entry = LocalUpdateReviewEntry(
                candidate=candidate,
                dependency_plan=dependency_plan,
                blocking_reasons=blocking_reasons,
                enabled=root_enabled_overrides.get(
                    root_key, bool(getattr(candidate, "actionable", False)) and not blocking_reasons
                )
                if root_enabled_overrides is not None
                else bool(getattr(candidate, "actionable", False)) and not blocking_reasons,
                provider=str(getattr(target_version, "provider", "modrinth") or "modrinth")
                if target_version
                else "modrinth",
                version_type=str(getattr(target_version, "version_type", "") or "") if target_version else "",
                date_published=str(getattr(target_version, "date_published", "") or "") if target_version else "",
                changelog=str(getattr(target_version, "changelog", "") or "") if target_version else "",
            )
            review_entries.append(review_entry)

            if non_blocking_warnings:
                existing_notes = list(getattr(candidate, "notes", []) or [])
                candidate.notes = self._dedupe_review_messages([*non_blocking_warnings, *existing_notes])

            if review_entry.actionable:
                self._append_enabled_dependency_simulations(simulated_installed_mods, dependency_plan)

                self._append_simulated_installed_mod(
                    simulated_installed_mods,
                    self._build_installed_mod_simulation_item(
                        candidate.project_id,
                        candidate.project_name,
                        candidate.target_filename or candidate.filename,
                        candidate.target_version_name,
                    ),
                )

        return review_entries

    def _format_local_update_review_text(self, review_entry: LocalUpdateReviewEntry) -> str:
        """格式化本地模組更新 review 內容。"""
        candidate = review_entry.candidate
        lines = [
            f"模組：{candidate.project_name}",
            f"來源：{self._format_review_provider_label(review_entry.provider)}",
            f"Metadata 來源：{self._format_metadata_source_label(getattr(candidate, 'metadata_source', ''))}",
            f"目前版本：{candidate.current_version or '未知'}",
            f"推薦版本：{candidate.target_version_name or '查無可用版本'}",
        ]

        metadata_note = str(getattr(candidate, "metadata_note", "") or "").strip()
        if metadata_note:
            lines.append(f"Metadata 狀態：{metadata_note}")

        published_text = self._format_review_published_at(review_entry.date_published)
        if published_text:
            lines.append(f"發布時間：{published_text}")

        client_install_reminder = self._build_client_install_reminder_line(
            getattr(candidate, "server_side", ""),
            getattr(candidate, "client_side", ""),
        )
        if client_install_reminder:
            lines.append(client_install_reminder)

        lines.append(f"執行狀態：{'已啟用' if review_entry.enabled else '已停用'}")

        if review_entry.blocking_reasons:
            self._append_review_section(lines, "需先處理：", review_entry.blocking_reasons, max_items=3)

        self._append_dependency_review_sections(lines, review_entry.dependency_plan, "更新時將一併安裝的必要依賴：")

        notes = list(getattr(candidate, "notes", []) or [])
        warnings = list(getattr(getattr(candidate, "report", None), "warnings", []) or [])
        if warnings:
            self._append_review_section(lines, "提醒：", warnings, max_items=3)
        if notes:
            self._append_review_section(lines, "補充說明：", notes, max_items=2)

        changelog_text = self._summarize_review_changelog(review_entry.changelog)
        if changelog_text:
            lines.append("")
            lines.append("更新內容：")
            lines.append(changelog_text)

        self._append_plan_note_section(lines, getattr(review_entry, "dependency_plan", None))

        return "\n".join(lines)

    def _install_local_update_review_entries(self, dialog, review_entries: list[LocalUpdateReviewEntry]) -> None:
        """安裝本地模組更新。"""
        manager = self.mod_manager
        if not manager:
            UIUtils.show_error("錯誤", "模組管理器未初始化", self.parent)
            return

        actionable_entries = [entry for entry in review_entries if entry.actionable]
        blocked_entries = [entry for entry in review_entries if not entry.runnable]
        disabled_entries = [entry for entry in review_entries if entry.runnable and not entry.enabled]
        if not actionable_entries:
            message = "目前沒有可直接更新的模組。"
            if disabled_entries:
                message = "目前沒有已啟用的可更新項目，請先啟用要執行的更新項目。"
            UIUtils.show_warning("沒有可更新項目", message, dialog)
            return

        if blocked_entries:
            proceed = UIUtils.ask_yes_no_cancel(
                "部分模組暫時無法更新",
                (
                    f"目前有 {len(blocked_entries)} 個模組因相容性或依賴問題無法直接更新。\n"
                    f"將只更新其餘 {len(actionable_entries)} 個可更新項目。\n\n是否繼續？"
                ),
                parent=dialog,
                show_cancel=False,
            )
            if proceed is not True:
                return

        dialog.destroy()

        completion_notes = self._format_completion_notes(
            [
                *[
                    message
                    for entry in actionable_entries
                    for message in list(getattr(getattr(entry.candidate, "report", None), "warnings", []) or [])
                ],
                *[
                    message
                    for entry in actionable_entries
                    for message in list(getattr(entry.candidate, "notes", []) or [])
                ],
                *[
                    message
                    for entry in actionable_entries
                    for message in list(getattr(getattr(entry, "dependency_plan", None), "notes", []) or [])
                ],
            ]
        )

        def install_task() -> None:
            total_steps = sum(
                len(self._get_enabled_dependency_install_items(entry.dependency_plan)) + 1
                for entry in actionable_entries
            )
            current_step = 0
            success_count = 0

            def make_step_progress_callback(step_index: int):
                def _callback(downloaded: int, total: int) -> None:
                    fraction = (downloaded / total) if total > 0 else 0.0
                    self.update_progress_safe((step_index + fraction) / max(1, total_steps))

                return _callback

            try:
                for review_entry in actionable_entries:
                    candidate = review_entry.candidate
                    for dependency_item in self._get_enabled_dependency_install_items(review_entry.dependency_plan):
                        self.update_status_safe(f"正在更新所需依賴：{dependency_item.project_name}")
                        installed_dependency = manager.install_remote_mod_file(
                            dependency_item.download_url,
                            dependency_item.filename,
                            progress_callback=make_step_progress_callback(current_step),
                        )
                        if installed_dependency is None:
                            raise RuntimeError(f"依賴安裝失敗：{dependency_item.project_name}")
                        current_step += 1

                    self.update_status_safe(f"正在更新模組：{candidate.project_name}")
                    updated_path = manager.replace_local_mod_file(
                        candidate.local_mod,
                        candidate.download_url,
                        candidate.target_filename,
                        progress_callback=make_step_progress_callback(current_step),
                    )
                    if updated_path is None:
                        raise RuntimeError(f"模組更新失敗：{candidate.project_name}")
                    current_step += 1
                    success_count += 1

                self.update_progress_safe(1.0)
                self.update_status_safe(f"已完成 {success_count} 個模組更新")
                self.ui_queue.put(self.load_local_mods)
                self.ui_queue.put(
                    lambda: UIUtils.show_info(
                        "更新完成",
                        (
                            f"已完成 {success_count} 個模組更新。"
                            + (f"\n已略過 {len(disabled_entries)} 個停用項目。" if disabled_entries else "")
                            + completion_notes
                        ),
                        self.parent,
                    )
                )
            except Exception as e:
                logger.error(f"本地模組更新失敗: {e}\n{traceback.format_exc()}")
                self.update_status_safe(f"本地模組更新失敗: {e}")
                self.ui_queue.put(
                    lambda msg=str(e): UIUtils.show_error("更新失敗", f"無法完成更新：{msg}", self.parent)
                )
            finally:
                self.update_progress_safe(0)

        UIUtils.run_async(install_task)

    def _show_local_update_review_dialog(self, update_plan: LocalModUpdatePlan, scope_text: str) -> None:
        """顯示本地模組更新檢查結果。"""
        review_entries = self._prepare_local_update_review_entries(update_plan)
        if not review_entries:
            message = update_plan.notes[0] if update_plan.notes else f"{scope_text}目前沒有可更新或需處理的模組。"
            UIUtils.show_info("更新檢查", message, self.parent)
            return

        entry_map = {self._build_local_update_review_key(entry.candidate): entry for entry in review_entries}
        review_root_keys = set(entry_map)
        global_review_notes = self._collect_local_update_global_notes(update_plan, review_entries)

        def rebuild_update_review_entries() -> None:
            nonlocal review_entries, entry_map, review_root_keys
            root_keys = [self._build_local_update_review_key(entry.candidate) for entry in review_entries]
            root_enabled_overrides = self._collect_review_entry_enabled_overrides(review_entries, root_keys)
            advisory_enabled_overrides = self._collect_review_advisory_enabled_overrides(review_entries, root_keys)
            review_entries = self._prepare_local_update_review_entries(
                update_plan,
                root_enabled_overrides=root_enabled_overrides,
                advisory_enabled_overrides=advisory_enabled_overrides,
            )
            entry_map = {self._build_local_update_review_key(entry.candidate): entry for entry in review_entries}
            review_root_keys = set(entry_map)

        dialog = UIUtils.create_toplevel_dialog(
            self.parent,
            "本地模組更新檢查",
            width=1100,
            height=900,
            make_modal=True,
            bind_icon=True,
            center_on_parent=True,
            delay_ms=250,
            min_width=1060,
            min_height=860,
            max_width=FontManager.get_dpi_scaled_size(1280),
            max_height=FontManager.get_dpi_scaled_size(980),
            native_window=True,
            use_transient_for_modal=False,
        )

        main_frame = ctk.CTkFrame(dialog)
        main_frame.pack(fill="both", expand=True, padx=18, pady=18)

        title = ctk.CTkLabel(
            main_frame,
            text="本地模組更新與相容性 Review",
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
        )
        title.pack(anchor="w", padx=12, pady=(12, 8))

        subtitle = ctk.CTkLabel(
            main_frame,
            text=self._build_local_update_review_subtitle(
                scope_text,
                self._count_enabled_runnable_entries(review_entries),
                self._count_blocked_entries(review_entries),
            ),
            font=FontManager.get_font(size=FontSize.SMALL_PLUS),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=FontManager.get_dpi_scaled_size(880),
        )
        subtitle.pack(fill="x", padx=12, pady=(0, 6))

        overview_label = ctk.CTkLabel(
            main_frame,
            text="",
            font=FontManager.get_font(size=FontSize.NORMAL),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=FontManager.get_dpi_scaled_size(880),
        )
        overview_label.pack(fill="x", padx=12, pady=(0, 6))

        tree_container = ctk.CTkFrame(main_frame)
        tree_container.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        update_tree = ttk.Treeview(
            tree_container,
            columns=("run", "current", "target", "source", "status"),
            show="tree headings",
            height=12,
            style=UIUtils.configure_treeview_list_style(
                "LocalUpdateList",
                body_font=FontManager.get_font(size=FontSize.INPUT),
                heading_font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
                rowheight=int(25 * FontManager.get_scale_factor()),
            ),
        )
        update_tree.heading("#0", text="模組")
        update_tree.column("#0", width=250, minwidth=170, anchor="w", stretch=False)
        update_tree.heading("run", text="套用")
        update_tree.column("run", width=50, minwidth=48, anchor="center", stretch=False)
        update_tree.heading("current", text="目前版本")
        update_tree.column("current", width=120, minwidth=96, anchor="w", stretch=False)
        update_tree.heading("target", text="建議版本")
        update_tree.column("target", width=155, minwidth=120, anchor="w", stretch=False)
        update_tree.heading("source", text="來源 / 識別")
        update_tree.column("source", width=170, minwidth=130, anchor="w", stretch=False)
        update_tree.heading("status", text="檢查狀態")
        update_tree.column("status", width=300, minwidth=240, anchor="w", stretch=True)
        UIUtils.bind_treeview_header_auto_fit(
            update_tree,
            include_tree_column=True,
            heading_font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            body_font=FontManager.get_font(size=FontSize.INPUT),
            stretch_columns={"status"},
        )

        update_scroll = ttk.Scrollbar(tree_container, orient="vertical", command=update_tree.yview)
        update_tree.configure(yscrollcommand=update_scroll.set)
        update_tree.grid(row=0, column=0, sticky="nsew")
        update_scroll.grid(row=0, column=1, sticky="ns")
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        def refresh_update_tree() -> None:
            self._render_review_task_tree(
                update_tree, self._build_local_update_task_nodes(review_entries), column_count=5
            )

        summary_box = self._create_review_summary_box(main_frame, height=138)

        def refresh_update_status_banner() -> None:
            review_nodes = self._build_local_update_task_nodes(review_entries)
            enabled_count = self._count_enabled_runnable_entries(review_entries)
            blocked_count = self._count_blocked_entries(review_entries)
            subtitle.configure(text=self._build_local_update_review_subtitle(scope_text, enabled_count, blocked_count))
            overview_label.configure(
                text=self._format_review_overview_text(
                    review_entries,
                    review_nodes,
                    action_label="更新",
                    global_notes=global_review_notes,
                )
            )

        def refresh_update_summary(_event=None) -> None:
            selected_key = self._get_selected_review_key(update_tree, review_root_keys)
            review_entry = entry_map.get(selected_key)
            if not review_entry:
                return

            summary_box.configure(state="normal")
            summary_box.delete("1.0", "end")
            summary_box.insert("1.0", self._format_local_update_review_text(review_entry))
            summary_box.configure(state="disabled")

        def toggle_update_selection(enabled: bool) -> None:
            self._toggle_review_selection(
                tree=update_tree,
                entry_map=entry_map,
                review_root_keys=review_root_keys,
                enabled=enabled,
                rebuild_entries=rebuild_update_review_entries,
                refresh_tree=refresh_update_tree,
                refresh_summary=refresh_update_summary,
                refresh_status_banner=refresh_update_status_banner,
                refresh_action_button=refresh_update_action_button,
            )

        def open_selected_update_project_page() -> None:
            selected_key = self._get_selected_review_key(update_tree, review_root_keys)
            review_entry = entry_map.get(selected_key)
            project_page_url = self._resolve_local_update_review_project_page_url(review_entry) if review_entry else ""
            self._open_project_page(project_page_url, dialog)

        update_tree.bind("<<TreeviewSelect>>", refresh_update_summary)
        refresh_update_tree()
        refresh_update_summary()

        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x", padx=12, pady=(0, 8))

        update_button = self._create_review_action_button(
            button_frame,
            text="",
            fg_color=Colors.BUTTON_SUCCESS,
            hover_color=Colors.BUTTON_SUCCESS_HOVER,
            command=lambda: self._install_local_update_review_entries(dialog, review_entries),
            bold=True,
        )

        self._create_review_action_button(
            button_frame,
            text="啟用選取項目",
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            command=lambda: toggle_update_selection(True),
            padx=(10, 0),
        )

        self._create_review_action_button(
            button_frame,
            text="停用選取項目",
            fg_color=Colors.BUTTON_SECONDARY,
            hover_color=Colors.BUTTON_SECONDARY_HOVER,
            command=lambda: toggle_update_selection(False),
            padx=(10, 0),
        )

        project_page_button = self._create_review_action_button(
            button_frame,
            text="開啟專案頁面",
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            command=open_selected_update_project_page,
            padx=(10, 0),
        )

        def refresh_update_action_button() -> None:
            self._configure_review_action_button(update_button, review_entries, "更新")

        def refresh_update_project_page_button(_event=None) -> None:
            selected_key = self._get_selected_review_key(update_tree, review_root_keys)
            review_entry = entry_map.get(selected_key)
            project_page_button.configure(
                state="normal"
                if review_entry and self._resolve_local_update_review_project_page_url(review_entry)
                else "disabled"
            )

        self._create_review_action_button(
            button_frame,
            text="關閉",
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            command=dialog.destroy,
            side="right",
        )

        update_tree.bind("<<TreeviewSelect>>", refresh_update_project_page_button, add="+")
        refresh_update_status_banner()
        refresh_update_action_button()
        refresh_update_project_page_button()

        UIUtils.schedule_toplevel_layout_refresh(
            dialog,
            min_width=1060,
            min_height=860,
            max_width=FontManager.get_dpi_scaled_size(1280),
            max_height=FontManager.get_dpi_scaled_size(980),
            parent=self.parent,
        )

    def check_local_mod_updates(self) -> None:
        """檢查本地模組是否有可用更新與相容性問題。"""
        manager = self.mod_manager
        if not self.current_server or not manager:
            UIUtils.show_warning("警告", "請先選擇伺服器後再檢查模組更新", self.parent)
            return

        selected_mod_ids = self._capture_selected_mod_ids()
        minecraft_version, loader_type, loader_version = self._get_current_modrinth_context()

        def check_task() -> None:
            try:
                self.update_status_safe("正在掃描本地模組更新與相容性...")
                self.update_progress_safe(0.0)
                installed_mods = manager.get_mod_list()
                self._ensure_local_mod_project_ids(installed_mods)

                target_mods = installed_mods
                scope_text = "全部模組"
                if selected_mod_ids:
                    target_mods = [
                        mod
                        for mod in installed_mods
                        if mod.filename.replace(".jar.disabled", "").replace(".jar", "") in selected_mod_ids
                    ]
                    scope_text = f"已選取的 {len(target_mods)} 個模組"

                last_hash_progress_percent = -1

                def on_hash_progress(completed: int, total: int) -> None:
                    nonlocal last_hash_progress_percent
                    if total <= 0:
                        return
                    fraction = max(0.0, min(1.0, completed / total))
                    progress_percent = int(fraction * 100)
                    if progress_percent == last_hash_progress_percent:
                        return
                    last_hash_progress_percent = progress_percent
                    self.update_progress_safe(fraction)
                    self.update_status_safe(f"正在計算本地模組雜湊... {completed}/{total}")

                update_plan = build_local_mod_update_plan(
                    target_mods,
                    minecraft_version=minecraft_version,
                    loader=loader_type,
                    loader_version=loader_version,
                    hash_progress_callback=on_hash_progress,
                )
                self._persist_local_update_plan_metadata(update_plan)
                self._latest_local_update_plan = update_plan
                self.update_progress_safe(1.0)
                self.update_status_safe(
                    f"更新檢查完成：{update_plan.actionable_count} 個可更新，{len(update_plan.candidates)} 個需 review"
                )
                self.ui_queue.put(lambda: self._show_local_update_review_dialog(update_plan, scope_text))
            except Exception as e:
                logger.error(f"檢查本地模組更新失敗: {e}\n{traceback.format_exc()}")
                self.update_progress_safe(0)
                self.update_status_safe(f"檢查本地模組更新失敗: {e}")
                self.ui_queue.put(lambda msg=str(e): UIUtils.show_error("更新檢查失敗", msg, self.parent))

        UIUtils.run_async(check_task)

    def copy_online_mod_info(self) -> None:
        """複製線上模組資訊。"""
        if not self.browse_tree:
            return
        selection = self.browse_tree.selection()
        if not selection:
            return

        item = selection[0]
        values = self.browse_tree.item(item, "values")
        tags = self.browse_tree.item(item, "tags")
        project_id = tags[0] if tags else ""
        mod = self._online_mod_index.get(project_id)
        if not values or not mod:
            return

        info = f"模組名稱: {values[0]}\n作者: {values[1]}\n下載數: {values[2]}\n頁面: {getattr(mod, 'url', '')}"
        self.parent.clipboard_clear()
        self.parent.clipboard_append(info)
        self.parent.update()
        self.update_status("線上模組資訊已複製到剪貼簿")

    def open_mod_webpage(self) -> None:
        """開啟選取模組的 Modrinth 頁面。"""
        if not self.browse_tree:
            return
        selection = self.browse_tree.selection()
        if not selection:
            return

        item = selection[0]
        tags = self.browse_tree.item(item, "tags")
        project_id = tags[0] if tags else ""
        mod = self._online_mod_index.get(project_id)
        if not mod:
            return

        url = self._resolve_online_mod_project_page_url(mod)
        if url:
            UIUtils.open_external(url)

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
                self._refresh_online_filter_hint()
                self._load_online_mods(show_warning=False)
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
            command=self.check_local_mod_updates,
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
            self.local_tree.column(col, width=width, minwidth=50, stretch=(col == "description"))

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
        bg_odd, bg_even = self._get_local_row_palette(is_dark)

        self.local_tree.tag_configure("odd", background=bg_odd)
        self.local_tree.tag_configure("even", background=bg_even)

        # 配置 grid 權重
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        # 綁定事件
        UIUtils.bind_treeview_header_auto_fit(
            self.local_tree,
            on_row_double_click=self.toggle_local_mod,
            heading_font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            body_font=FontManager.get_font(size=FontSize.INPUT),
            stretch_columns={"description"},
        )
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
                min_width=Sizes.DIALOG_LARGE_WIDTH,
                min_height=Sizes.DIALOG_LARGE_HEIGHT,
                max_width=FontManager.get_dpi_scaled_size(1280),
                max_height=FontManager.get_dpi_scaled_size(960),
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

            UIUtils.schedule_toplevel_layout_refresh(
                dialog,
                min_width=Sizes.DIALOG_LARGE_WIDTH,
                min_height=Sizes.DIALOG_LARGE_HEIGHT,
                max_width=FontManager.get_dpi_scaled_size(1280),
                max_height=FontManager.get_dpi_scaled_size(960),
                parent=self.parent,
            )

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
                self.mod_manager = None
                if hasattr(self, "local_mods"):
                    self.local_mods = []
                if hasattr(self, "refresh_local_list"):
                    self.refresh_local_list()
                self._refresh_online_filter_hint()
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

            self.mod_manager = ModManager(selected_server.path, selected_server)
            self._last_online_request = None
            self._refresh_online_filter_hint()

            # 載入本地模組
            self.load_local_mods()

            if self._is_browse_tab_active():
                self._load_online_mods(force=True, show_warning=False)

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

                enhanced = enhance_local_mod(
                    mod.filename,
                    platform_id=getattr(mod, "platform_id", ""),
                    platform_slug=getattr(mod, "platform_slug", ""),
                    local_name=getattr(mod, "name", ""),
                )
                if enhanced:
                    resolved_project_id = str(getattr(enhanced, "project_id", "") or "").strip()
                    resolved_slug = str(getattr(enhanced, "slug", "") or "").strip()
                    if resolved_project_id:
                        mod.platform_id = resolved_project_id
                    if resolved_slug and hasattr(mod, "platform_slug"):
                        mod.platform_slug = resolved_slug
                    self.enhanced_mods_cache[mod.filename] = enhanced
                    self._cache_local_provider_metadata(mod, enhanced)
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

    def _is_exact_local_enhancement_match(self, mod: Any, enhanced: Any) -> bool:
        if not enhanced:
            return False

        platform_id = str(getattr(mod, "platform_id", "") or "").strip().lower()
        enhanced_project_id = str(getattr(enhanced, "project_id", "") or "").strip().lower()
        enhanced_slug = str(getattr(enhanced, "slug", "") or "").strip().lower()

        return bool(platform_id and platform_id in {enhanced_project_id, enhanced_slug})

    def _resolve_local_display_name(self, mod: Any, enhanced: Any) -> str:
        local_name = str(getattr(mod, "name", "") or "").strip()
        if local_name and local_name.lower() not in {"unknown", "unknown mod"}:
            return local_name

        enhanced_name = self._get_enhanced_attr(enhanced, "name", local_name)
        if self._is_exact_local_enhancement_match(mod, enhanced):
            return enhanced_name or local_name
        return local_name or enhanced_name

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

    def _purge_orphan_local_tree_items(self, expected_item_ids: set[str]) -> None:
        """刪除 Treeview 中不屬於目前映射表的孤兒列，避免重複顯示。"""
        tree = self.local_tree
        if not tree or not tree.winfo_exists():
            return

        recycled_pool = set(self._local_recycled_item_ids)
        active_children = list(tree.get_children(""))
        for item_id in active_children:
            if item_id in expected_item_ids:
                continue
            with contextlib.suppress(Exception):
                tree.delete(item_id)

        if recycled_pool:
            self._local_recycled_item_ids = [
                item_id for item_id in self._local_recycled_item_ids if tree.exists(item_id)
            ]

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

                expected_item_ids = {
                    item_id for mod_id in mod_order for item_id in [self._local_item_by_mod_id.get(mod_id)] if item_id
                }
                self._purge_orphan_local_tree_items(expected_item_ids)

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
            expected_item_ids = {
                item_id for mod_id in mod_order for item_id in [self._local_item_by_mod_id.get(mod_id)] if item_id
            }
            self._purge_orphan_local_tree_items(expected_item_ids)
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

        seen_mod_ids: set[str] = set()
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
            display_name = self._resolve_local_display_name(mod, enhanced)
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
            if mod_base_name in seen_mod_ids:
                continue
            seen_mod_ids.add(mod_base_name)

            parity_tag = self._get_parity_tag(len(mod_order))
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
                                current_tags = list(tree.item(item, "tags") or [])
                                parity_tag = (
                                    current_tags[1] if len(current_tags) > 1 else self._get_parity_tag(tree.index(item))
                                )
                                tree.item(item, values=tuple(row_values), tags=(mod_id, parity_tag))

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
        if not self._select_tree_item_for_context_menu(tree, event):
            return
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
            selected_mods: list[tuple[str, str]] = []
            seen_mod_ids: set[str] = set()
            for item_id in selection:
                values = tree.item(item_id, "values")
                tags = tree.item(item_id, "tags")
                if not values or len(values) < 2 or not tags or len(tags) == 0:
                    continue
                mod_id = str(tags[0] or "").strip()
                mod_name = str(values[1] or mod_id).strip()
                if not mod_id or mod_id in seen_mod_ids:
                    continue
                seen_mod_ids.add(mod_id)
                selected_mods.append((mod_id, mod_name))

            if not selected_mods:
                return

            mod_count = len(selected_mods)
            mod_label = selected_mods[0][1] if mod_count == 1 else f"這 {mod_count} 個模組"
            result = UIUtils.ask_yes_no_cancel(
                "確認刪除",
                f"確定要刪除{mod_label}嗎？\n此操作無法復原。",
                parent=self.parent,
                show_cancel=False,
            )

            if not result:
                return

            mods_dir = Path(self.current_server.path) / "mods"
            deleted_names: list[str] = []
            failed_names: list[str] = []

            for mod_filename, mod_name in selected_mods:
                deleted = False
                for ext in [".jar", ".jar.disabled"]:
                    mod_file = mods_dir / f"{mod_filename}{ext}"
                    if not mod_file.exists():
                        continue
                    mod_file.unlink()
                    deleted = True
                    break

                if deleted:
                    deleted_names.append(mod_name)
                else:
                    failed_names.append(mod_name)

            if deleted_names:
                self.load_local_mods()
                if hasattr(self, "status_label") and self.status_label.winfo_exists():
                    self.status_label.configure(text=f"已刪除 {len(deleted_names)} 個模組")

                if len(deleted_names) == 1 and not failed_names:
                    UIUtils.show_info("成功", f"模組 '{deleted_names[0]}' 已刪除", self.parent)
                else:
                    summary = f"已刪除 {len(deleted_names)} 個模組"
                    if failed_names:
                        summary += f"，{len(failed_names)} 個刪除失敗"
                    UIUtils.show_info("成功", summary, self.parent)
            elif hasattr(self, "status_label") and self.status_label.winfo_exists():
                self.status_label.configure(text="刪除失敗")

            if failed_names and not deleted_names:
                UIUtils.show_warning("提示", f"沒有成功刪除任何模組：{', '.join(failed_names)}", self.parent)

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
                                    current_tags = list(self.local_tree.item(item_id, "tags") or [])
                                    parity_tag = (
                                        current_tags[1]
                                        if len(current_tags) > 1
                                        else self._get_parity_tag(self.local_tree.index(item_id))
                                    )
                                    self.local_tree.item(item_id, values=tuple(row_values), tags=(mod_id, parity_tag))
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
