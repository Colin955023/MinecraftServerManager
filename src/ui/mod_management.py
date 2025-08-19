#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模組管理頁面
參考 Prism Launcher 設計，支援線上模組查詢與下載
"""
# ====== 標準函式庫 ======
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable, Optional
import json
import os
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
import customtkinter as ctk
# ====== 專案內部模組 ======
from .custom_dropdown import CustomDropdown
from ..core.mod_manager import ModManager, ModStatus
from ..core.version_manager import MinecraftVersionManager
from ..utils.font_manager import font_manager, get_dpi_scaled_size, get_font
from ..utils.http_utils import HTTPUtils
from ..utils.settings_manager import get_settings_manager
from ..utils.log_utils import LogUtils
from ..utils.ui_utils import UIUtils
from ..version_info import APP_VERSION, GITHUB_OWNER, GITHUB_REPO

# 提供同步查詢的 search_mods_online 及 enhance_local_mod 包裝
def search_mods_online(query, minecraft_version=None, loader=None, categories=None, sort_by="relevance"):
    """
    線上搜尋模組
    Search for mods online

    Args:
        query: 搜尋關鍵字
        minecraft_version: Minecraft 版本
        loader: 載入器類型
        categories: 模組類別
        sort_by: 排序方式
    """
    url = "https://api.modrinth.com/v2/search"
    facets = [["project_type:mod"]]
    if minecraft_version:
        facets.append([f"game_versions:{minecraft_version}"])
    # loader 不直接加到 facets，API 不支援
    if categories:
        category_facets = [f"categories:{cat}" for cat in categories]
        facets.append(category_facets)
    params = {
        "query": query,
        "limit": 20,
        "facets": json.dumps(facets),
        "index": sort_by if sort_by in ["relevance", "downloads", "newest"] else "relevance",
    }
    headers = {"User-Agent": f"MinecraftServerManager/{APP_VERSION} (github.com/{GITHUB_OWNER}/{GITHUB_REPO})"}
    # 構建完整 URL
    full_url = url + "?" + urllib.parse.urlencode(params)
    response = HTTPUtils.get_content(full_url, headers=headers, timeout=10)
    if not response or response.status_code != 200:
        if response:
            LogUtils.error(f"Modrinth API status: {response.status_code}")
        else:
            LogUtils.error("Modrinth API request failed")
        return []
    hits = response.json().get("hits", [])
    mods = []
    for hit in hits:
        mod = type("OnlineModInfo", (), {})()
        mod.name = hit.get("title", "Unknown")
        mod.slug = hit.get("project_id", "")
        mod.url = f"https://modrinth.com/mod/{hit.get('slug', hit.get('project_id', ''))}"
        mod.versions = hit.get("versions", [])
        mod.available = True
        mod.download_url = None
        mod.filename = None
        mod.author = hit.get("author", "?")
        mod.description = hit.get("description", "")
        mod.homepage_url = hit.get("homepage_url", mod.url)
        mod.latest_version = hit.get("latest_version", "")
        mod.download_count = hit.get("downloads", 0)
        mod.source = "modrinth"
        mods.append(mod)
    if sort_by == "downloads":
        mods.sort(key=lambda x: getattr(x, "download_count", 0), reverse=True)
    elif sort_by == "name":
        mods.sort(key=lambda x: x.name.lower())
    return mods

def enhance_local_mod(filename):
    """
    增強本地模組資訊，從線上查詢模組詳細資訊
    Enhance local mod information by querying online for mod details.
    """
    name = filename.replace(".jar", "").replace(".jar.disabled", "")
    for suffix in ["-fabric", "-forge", "-mc"]:
        if suffix in name.lower():
            name = name.lower().split(suffix)[0]
            break
    name = re.sub(r"-[\d\.\+]+.*$", "", name)
    # 將底線與連字號都轉成空白，避免搜尋 API 查不到
    name = name.replace("_", "").replace("-", " ").strip()
    mods = search_mods_online(name)
    if mods:
        return mods[0]
    return None

class ModManagementFrame:
    def __init__(
        self,
        parent,
        server_manager,
        on_server_selected_callback: Optional[Callable] = None,
        version_manager: MinecraftVersionManager = None,
    ):
        self.parent = parent
        self.server_manager = server_manager
        self.on_server_selected = on_server_selected_callback
        self.version_manager = version_manager

        # 獲取設定管理器和動態縮放因子
        self.settings = get_settings_manager()

        # 目前選中的伺服器
        self.current_server = None
        self.mod_manager: Optional[ModManager] = None

        # 版本相關變數
        self.versions: list = []
        self.release_versions: list = []

        # 多選狀態管理
        self.all_selected = False
        self.selected_mods = set()  # 儲存選中的模組 ID

        # UI 元件
        self.main_frame = None
        self.notebook = None
        self.local_tab = None
        self.browse_tab = None

        # 本地模組頁面
        self.local_tree = None

        # 狀態
        self.local_mods = []
        self.enhanced_mods_cache = {}

        self.create_widgets()
        self.load_servers()

    def update_status(self, message: str) -> None:
        """
        安全地更新狀態標籤
        Safely update status label

        Args:
            message (str): 狀態訊息
        """
        try:
            if hasattr(self, "status_label") and self.status_label and self.status_label.winfo_exists():
                if hasattr(self, "parent") and self.parent and self.parent.winfo_exists():
                    self.parent.after(0, lambda: self.status_label.configure(text=message))
                else:
                    self.status_label.configure(text=message)
        except Exception as e:
            LogUtils.error(f"更新狀態失敗: {e}", "ModManagementFrame")

    def update_status_safe(self, message: str) -> None:
        """
        更安全的狀態更新，使用 after 方法
        More safe status update using after method

        Args:
            message (str): 狀態訊息
        """
        try:
            if hasattr(self, "status_label") and self.status_label:
                if hasattr(self, "parent") and self.parent and self.parent.winfo_exists():
                    self.parent.after(0, lambda: self.update_status(message))
                else:
                    self.update_status(message)
        except Exception as e:
            LogUtils.error(f"安全更新狀態失敗: {e}", "ModManagementFrame")

    def update_progress_safe(self, value: float) -> None:
        """
        更安全的進度更新，使用 after 方法
        More safe progress update using after method

        Args:
            value (float): 進度值
        """
        try:
            if hasattr(self, "progress_var") and self.progress_var:
                if hasattr(self, "parent") and self.parent and self.parent.winfo_exists():
                    self.parent.after(0, lambda: self.progress_var.set(value))
                else:
                    self.progress_var.set(value)
        except Exception as e:
            LogUtils.error(f"安全更新進度失敗: {e}", "ModManagementFrame")

    def create_widgets(self) -> None:
        """建立 UI 元件"""
        # 主框架
        self.main_frame = ctk.CTkFrame(self.parent)

        # 標題區域
        self.create_header()

        # 伺服器選擇區域
        self.create_server_selection()

        # 頁籤介面
        self.create_notebook()

        # 狀態列
        self.create_status_bar()

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
            font=get_font(size=15, weight="bold"),
        ).pack(side="left")

        self.server_var = tk.StringVar()
        self.server_combo = CustomDropdown(
            inner_frame,
            variable=self.server_var,
            values=["載入中..."],
            command=self.on_server_changed,
            width=get_dpi_scaled_size(200),
        )
        self.server_combo.pack(side="left", padx=(10, 0))

        # 重新整理按鈕
        refresh_btn = ctk.CTkButton(
            inner_frame,
            text="🔄 重新整理",
            font=get_font(size=14),
            command=self.load_servers,
            width=int(120),
            height=int(32),
        )
        refresh_btn.pack(side="left", padx=(10, 0))

    def create_header(self) -> None:
        """建立標題區域"""
        header_frame = ctk.CTkFrame(self.main_frame)
        header_frame.pack(fill="x", padx=20, pady=(20, 10))

        # 創建標題
        title_label = ctk.CTkLabel(header_frame, text="🧩 模組管理", font=get_font(size=27, weight="bold"))
        title_label.pack(side="left", padx=15, pady=15)

        desc_label = ctk.CTkLabel(
            header_frame,
            text="參考 Prism launcher 功能設計，提供模組管理體驗",
            font=get_font(size=15),
            text_color=("#64748b", "#64748b"),
        )
        desc_label.pack(side="left", padx=(15, 15), pady=15)

    def create_local_mods_tab(self) -> None:
        """建立本地模組頁面"""
        self.local_tab = ctk.CTkFrame(self.notebook)
        self.notebook.add(self.local_tab, text="📁 本地模組")
        # 工具列
        self.create_local_toolbar()

        # 模組列表
        self.create_local_mod_list()

    def create_browse_mods_tab(self) -> None:
        """建立線上瀏覽頁面（暫停開發，僅顯示通知）"""
        self.browse_tab = ctk.CTkFrame(self.notebook)
        self.notebook.add(self.browse_tab, text="🌐 瀏覽模組")
        notice = ctk.CTkLabel(
            self.browse_tab,
            text="目前瀏覽模組功能暫停開發，請手動下載模組。",
            font=get_font(size=24, weight="bold"),
            text_color=("#64748b", "#64748b"),
        )
        notice.pack(expand=True, fill="both", pady=80)

    def create_notebook(self) -> None:
        """建立頁籤介面"""
        # 使用 ttk.Notebook
        self.notebook = ttk.Notebook(self.main_frame)

        # 設置頁籤字體使用DPI縮放
        style = ttk.Style()
        style.configure("Tab", font=get_font("Microsoft JhengHei", 18, "bold"))

        self.notebook.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        # 本地模組頁面
        self.create_local_mods_tab()

        # 線上瀏覽頁面
        self.create_browse_mods_tab()

        # 綁定頁籤切換事件
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

    def on_tab_changed(self, event=None) -> None:
        """頁籤切換事件"""
        try:
            current_tab = self.notebook.index(self.notebook.select())
            if current_tab == 0:  # 本地模組頁面
                self.refresh_local_list()
            elif current_tab == 1:  # 線上瀏覽頁面
                pass  # 線上頁面不需要自動重新整理
        except Exception as e:
            LogUtils.error(f"處理頁籤切換事件失敗: {e}", "ModManagementFrame")

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
            font=get_font(size=18, weight="bold"),
            command=self.import_mod_file,
            fg_color="#059669",
            hover_color=self._get_hover_color("#059669"),
            text_color="white",
            width=80,
            height=36,
        )
        import_btn.pack(side="left", padx=(0, get_dpi_scaled_size(15)))

        # 重新整理（強制掃描）
        refresh_mod_list_btn = ctk.CTkButton(
            left_frame,
            text="🔄 重新整理",
            font=get_font(size=18, weight="bold"),
            command=self.refresh_mod_list_force,
            fg_color="#3b82f6",
            hover_color=self._get_hover_color("#3b82f6"),
            text_color="white",
            width=80,
            height=36,
        )
        refresh_mod_list_btn.pack(side="left", padx=(0, get_dpi_scaled_size(15)))

        # 檢查更新
        update_btn = ctk.CTkButton(
            left_frame,
            text="🔄 檢查更新",
            font=get_font(size=18, weight="bold"),
            command=lambda: UIUtils.show_info("提示", "目前檢查更新功能暫停開發，請手動檢查模組更新。", self.parent),
            fg_color="#2563eb",
            hover_color=self._get_hover_color("#2563eb"),
            text_color="white",
            width=80,
            height=36,
        )
        update_btn.pack(side="left", padx=(0, get_dpi_scaled_size(15)))

        # 全選/取消全選
        self.select_all_btn = ctk.CTkButton(
            left_frame,
            text="☑️ 全選",
            font=get_font(size=18, weight="bold"),
            command=self.toggle_select_all,
            fg_color="#f59e0b",
            hover_color=self._get_hover_color("#f59e0b"),
            text_color="white",
            width=80,
            height=36,
        )
        self.select_all_btn.pack(side="left", padx=(0, get_dpi_scaled_size(15)))

        # 批量啟用/停用
        batch_toggle_btn = ctk.CTkButton(
            left_frame,
            text="🔄 批量切換",
            font=get_font(size=18, weight="bold"),
            command=self.batch_toggle_selected,
            fg_color="#8b5cf6",
            hover_color=self._get_hover_color("#8b5cf6"),
            text_color="white",
            width=80,
            height=36,
        )
        batch_toggle_btn.pack(side="left", padx=(0, get_dpi_scaled_size(15)))

        # 開啟模組資料夾
        folder_btn = ctk.CTkButton(
            left_frame,
            text="📂 開啟資料夾",
            font=get_font(size=18, weight="bold"),
            command=self.open_mods_folder,
            fg_color="#7c3aed",
            hover_color=self._get_hover_color("#7c3aed"),
            text_color="white",
            width=80,
            height=36,
        )
        folder_btn.pack(side="left")

        # 右側篩選
        right_frame = ctk.CTkFrame(toolbar_frame, fg_color="transparent")
        right_frame.pack(side="right", padx=15)

        # 搜尋框
        search_frame = ctk.CTkFrame(right_frame, fg_color="transparent")
        search_frame.pack(side="left", padx=(0, 15))

        # 搜尋圖示
        search_label = ctk.CTkLabel(search_frame, text="🔍", font=get_font(size=21))
        search_label.pack(side="left")

        self.local_search_var = tk.StringVar()
        search_entry = ctk.CTkEntry(
            search_frame, textvariable=self.local_search_var, font=get_font(size=14), width=200, height=32
        )
        search_entry.pack(side="left", padx=(get_dpi_scaled_size(8), 0))
        self.local_search_var.trace("w", self.filter_local_mods)

        # 狀態篩選
        self.local_filter_var = tk.StringVar(value="all")
        filter_combo = ctk.CTkOptionMenu(
            right_frame,
            variable=self.local_filter_var,
            values=["all", "enabled", "disabled"],
            font=get_font(size=17),
            dropdown_font=get_font(size=17),
            command=self.on_filter_changed,
            width=100,
            height=32,
        )
        filter_combo.pack(side="left")

        # 添加滾輪支援
        UIUtils.add_mousewheel_support(filter_combo)

    def _get_hover_color(self, base_color: str) -> str:
        """根據基礎顏色生成懸停顏色"""
        color_map = {
            "#059669": "#047857",  # 綠色 -> 深綠色
            "#3b82f6": "#2563eb",  # 藍色 -> 深藍色
            "#2563eb": "#1d4ed8",  # 深藍色 -> 更深藍色
            "#f59e0b": "#d97706",  # 黃色 -> 深黃色
            "#8b5cf6": "#7c3aed",  # 紫色 -> 深紫色
            "#7c3aed": "#6d28d9",  # 深紫色 -> 更深紫色
        }
        return color_map.get(base_color, "#1a202c")  # 預設深灰色

    def on_filter_changed(self, value: str) -> None:
        """篩選變更回調"""
        self.filter_local_mods()

    def refresh_mod_list_force(self) -> None:
        """強制重新掃描本地模組並重繪列表"""
        if self.mod_manager:

            def load_thread():
                try:
                    self.update_status_safe("正在強制重新掃描本地模組...")
                    mods = self.mod_manager.scan_mods()
                    self.local_mods = mods
                    self.enhanced_mods_cache = {}
                    self.enhance_local_mods()
                    self.update_status_safe(f"找到 {len(mods)} 個本地模組 (已重新整理)")
                except Exception as e:
                    self.update_status_safe(f"強制掃描失敗: {e}")

            threading.Thread(target=load_thread, daemon=True).start()

    def create_local_mod_list(self) -> None:
        """建立本地模組列表"""
        list_frame = ctk.CTkFrame(self.local_tab)
        list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 匯出模組按鈕
        export_btn = ctk.CTkButton(
            list_frame,
            text="匯出模組列表",
            font=get_font(size=20, weight="bold"),
            fg_color=("#2563eb", "#1d4ed8"),
            hover_color=("#1d4ed8", "#1e40af"),
            text_color=("white", "white"),
            command=self.export_mod_list_dialog,
            width=80,
            height=25,
        )
        export_btn.pack(anchor="ne", pady=(10, 5), padx=10)

        # 建立包含 Treeview 和滾動條的容器
        tree_container = ctk.CTkFrame(list_frame)
        tree_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 建立 Treeview
        columns = ("status", "name", "version", "author", "loader", "size", "mtime", "description")
        self.local_tree = ttk.Treeview(
            tree_container, columns=columns, show="headings", height=15, selectmode="extended"  # 支援多選
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

        # 使用 grid 佈局確保滾動條在正確位置
        self.local_tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")

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
            dialog = ctk.CTkToplevel(self.parent)
            dialog.title("匯出模組列表")
            dialog.resizable(True, True)

            # 統一設定視窗屬性：綁定圖示、相對於父視窗置中、設為模態視窗
            UIUtils.setup_window_properties(
                window=dialog,
                parent=self.parent,
                width=800,
                height=600,
                bind_icon=True,
                center_on_parent=True,
                make_modal=True,
                delay_ms=250,  # 使用稍長延遲確保圖示綁定成功
            )

            # 主容器
            main_frame = ctk.CTkFrame(dialog)
            main_frame.pack(fill="both", expand=True, padx=20, pady=20)

            # 標題
            title_label = ctk.CTkLabel(main_frame, text="匯出模組列表", font=get_font(size=27, weight="bold"))
            title_label.pack(pady=(10, 20))

            # 格式選擇區域
            fmt_frame = ctk.CTkFrame(main_frame)
            fmt_frame.pack(fill="x", pady=(0, 15))

            fmt_inner = ctk.CTkFrame(fmt_frame, fg_color="transparent")
            fmt_inner.pack(fill="x", padx=20, pady=15)

            ctk.CTkLabel(fmt_inner, text="選擇匯出格式:", font=get_font(size=21, weight="bold")).pack(
                side="left", padx=(0, 15)
            )

            fmt_var = tk.StringVar(value="text")

            # 使用 CTK 選項按鈕
            text_radio = ctk.CTkRadioButton(
                fmt_inner, text="純文字", variable=fmt_var, value="text", font=get_font(size=18)
            )
            text_radio.pack(side="left", padx=5)

            json_radio = ctk.CTkRadioButton(
                fmt_inner, text="JSON", variable=fmt_var, value="json", font=get_font(size=18)
            )
            json_radio.pack(side="left", padx=5)

            html_radio = ctk.CTkRadioButton(
                fmt_inner, text="HTML", variable=fmt_var, value="html", font=get_font(size=18)
            )
            html_radio.pack(side="left", padx=5)

            # 預覽區域
            preview_frame = ctk.CTkFrame(main_frame)
            preview_frame.pack(fill="both", expand=True, pady=(0, 15))

            preview_label = ctk.CTkLabel(preview_frame, text="預覽:", font=get_font(size=21, weight="bold"))
            preview_label.pack(anchor="w", padx=15, pady=(15, 5))

            text_widget = ctk.CTkTextbox(preview_frame, font=get_font(size=18), height=300, wrap="word")
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
                    filetypes=[("所有檔案", "*.*"), ("純文字", "*.txt"), ("JSON", "*.json"), ("HTML", "*.html")],
                    initialfile=default_name,
                )
                if file_path:
                    export_text = self.mod_manager.export_mod_list(fmt)
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(export_text)
                    try:
                        result = UIUtils.ask_yes_no_cancel(
                            "匯出成功",
                            f"已儲存: {file_path}\n\n是否要立即開啟匯出的檔案？",
                            parent=dialog,  # 傳遞正確的父視窗
                            show_cancel=False,
                        )
                        if result:
                            os.startfile(file_path)
                    except Exception as e:
                        UIUtils.show_error("開啟檔案失敗", f"無法開啟檔案: {e}", parent=dialog)

            save_btn = ctk.CTkButton(
                btn_frame,
                text="儲存到檔案",
                command=do_save,
                font=get_font(size=18, weight="bold"),
                fg_color=("#2563eb", "#1d4ed8"),
                hover_color=("#1d4ed8", "#1e40af"),
                width=get_dpi_scaled_size(180),
                height=int(40 * font_manager.get_scale_factor()),
            )
            save_btn.pack(side="left", padx=(0, 10))

            close_btn = ctk.CTkButton(
                btn_frame,
                text="關閉",
                command=dialog.destroy,
                font=get_font(size=18),
                fg_color=("#6b7280", "#4b5563"),
                hover_color=("#4b5563", "#374151"),
                width=get_dpi_scaled_size(150),
                height=int(40 * font_manager.get_scale_factor()),
            )
            close_btn.pack(side="left")

            # 綁定 Escape 鍵
            dialog.bind("<Escape>", lambda e: dialog.destroy())

        except Exception as e:
            UIUtils.show_error("匯出對話框錯誤", str(e), self.parent)

    def create_status_bar(self) -> None:
        """建立狀態列"""
        status_frame = ctk.CTkFrame(self.main_frame, height=int(40 * font_manager.get_scale_factor()))
        status_frame.pack(fill="x", padx=20, pady=0)
        status_frame.pack_propagate(False)

        # 狀態標籤
        self.status_label = ctk.CTkLabel(
            status_frame, text="請選擇伺服器開始管理模組", font=get_font(size=21), text_color=("#64748b", "#64748b")
        )
        self.status_label.pack(side="left", padx=10, pady=int(6 * font_manager.get_scale_factor()))

        # 進度條（亮綠色，使用 CTK）
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ctk.CTkProgressBar(
            status_frame,
            variable=self.progress_var,
            width=get_dpi_scaled_size(300),
            height=int(20 * font_manager.get_scale_factor()),
            progress_color=("#22d3ee", "#4ade80"),
            fg_color=("#e5e7eb", "#374151"),
        )
        self.progress_bar.pack(side="right", padx=10, pady=int(6 * font_manager.get_scale_factor()))

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
                self.server_var.set(server_names[0])
                self.on_server_changed()

        except Exception as e:
            UIUtils.show_error("錯誤", f"載入伺服器列表失敗: {e}", self.parent)

    def on_server_changed(self, event=None) -> None:
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

            # 初始化模組管理器
            self.mod_manager = ModManager(selected_server.path)

            # 載入本地模組
            self.load_local_mods()

            # 更新狀態
            self.update_status(f"已選擇伺服器: {server_name}")

            if self.on_server_selected:
                self.on_server_selected(server_name)

        except Exception as e:
            UIUtils.show_error("錯誤", f"切換伺服器失敗: {e}", self.parent)

    def load_local_mods(self) -> None:
        """載入本地模組，並同步清空增強 cache，確保顯示一致，並顯示進度條"""
        if not self.mod_manager:
            return

        def load_thread():
            try:
                self.update_status_safe("正在掃描本地模組...")
                mods = list(self.mod_manager.scan_mods())
                total = len(mods)
                self.local_mods = []
                self.enhanced_mods_cache = {}
                for idx, mod in enumerate(mods):
                    self.local_mods.append(mod)
                    percent = (idx + 1) / total * 100 if total else 0
                    self.update_progress_safe(percent)
                    if hasattr(self, "progress_bar"):
                        self.progress_bar.update_idletasks()
                self.update_progress_safe(0)
                # 載入增強資訊，結束後自動刷新列表
                self.enhance_local_mods()
                self.update_status_safe(f"找到 {len(mods)} 個本地模組")
            except Exception as e:
                self.update_progress_safe(0)
                self.update_status_safe(f"掃描失敗: {e}")

        threading.Thread(target=load_thread, daemon=True).start()

    def enhance_local_mods(self) -> None:
        """本地模組資訊（同步查詢），查詢完自動刷新列表（可選）"""

        def enhance_thread():
            for mod in self.local_mods:
                if mod.filename not in self.enhanced_mods_cache:
                    try:
                        enhanced = enhance_local_mod(mod.filename)
                        if enhanced:
                            self.enhanced_mods_cache[mod.filename] = enhanced
                    except Exception as e:
                        LogUtils.error(f"模組 {mod.filename} 資訊失敗: {e}", "ModManagementFrame")
            # Safe after call
            if hasattr(self, "parent") and self.parent and self.parent.winfo_exists():
                self.parent.after(0, self.refresh_local_list)
            else:
                self.refresh_local_list()

        threading.Thread(target=enhance_thread, daemon=True).start()

    def refresh_local_list(self) -> None:
        """重新整理本地模組列表"""
        if not hasattr(self, "local_tree") or not self.local_tree:
            return
        # 清空列表
        for item in self.local_tree.get_children():
            self.local_tree.delete(item)
        # 獲取篩選條件
        search_text = self.local_search_var.get().lower() if hasattr(self, "local_search_var") else ""
        filter_status = self.local_filter_var.get() if hasattr(self, "local_filter_var") else "all"
        version_pattern = re.compile(r"-([\dv.]+)(?:\.jar(?:\.disabled)?)?$")
        for mod in self.local_mods:
            # 應用篩選
            if search_text and search_text not in mod.name.lower():
                continue
            if filter_status != "all":
                if filter_status == "enabled" and mod.status != ModStatus.ENABLED:
                    continue
                elif filter_status == "disabled" and mod.status != ModStatus.DISABLED:
                    continue
            # 獲取增強資訊
            enhanced = self.enhanced_mods_cache.get(mod.filename)
            # 解析檔名中的版本號
            parsed_version = "未知"
            m = version_pattern.search(mod.filename)
            if m:
                parsed_version = m.group(1)
            display_name = enhanced.name if enhanced and hasattr(enhanced, "name") and enhanced.name else mod.name
            display_author = (
                enhanced.author
                if enhanced and hasattr(enhanced, "author") and enhanced.author
                else (mod.author or "Unknown")
            )
            # 版本顯示優先順序：mod.version > enhanced.version > enhanced.versions[0] > parsed_version > "未知"
            if mod.version and mod.version not in ("", "未知"):
                display_version = mod.version
            elif enhanced and hasattr(enhanced, "version") and enhanced.version:
                display_version = enhanced.version
            elif enhanced and hasattr(enhanced, "versions") and enhanced.versions:
                display_version = (
                    enhanced.versions[0]
                    if isinstance(enhanced.versions, list) and enhanced.versions
                    else str(enhanced.versions)
                )
            elif parsed_version and parsed_version not in ("", "未知"):
                display_version = parsed_version
            else:
                display_version = "未知"
            display_description = (
                enhanced.description
                if enhanced and hasattr(enhanced, "description") and enhanced.description
                else (mod.description or "")
            )
            status_text = "✅ 已啟用" if mod.status == ModStatus.ENABLED else "❌ 已停用"
            mod_base_name = mod.filename.replace(".jar.disabled", "").replace(".jar", "")
            # 檔案大小顯示
            size_val = getattr(mod, "file_size", 0)
            if size_val >= 1024 * 1024:
                display_size = f"{size_val / 1024 / 1024:.1f} MB"
            elif size_val >= 1024:
                display_size = f"{size_val / 1024:.1f} KB"
            else:
                display_size = f"{size_val} B"
            # 修改時間顯示
            mtime_val = None
            try:
                mtime_val = os.path.getmtime(mod.file_path)
            except Exception:
                mtime_val = None
            if mtime_val:
                display_mtime = datetime.fromtimestamp(mtime_val).strftime("%Y-%m-%d %H:%M")
            else:
                display_mtime = "未知"
            self.local_tree.insert(
                "",
                "end",
                values=(
                    status_text,
                    display_name,
                    display_version,
                    display_author,
                    mod.loader_type,
                    display_size,
                    display_mtime,
                    display_description[:50] + "..." if len(display_description) > 50 else display_description,
                ),
                tags=(mod_base_name,),
            )

    def toggle_local_mod(self, event=None) -> None:
        """雙擊切換本地模組啟用/停用狀態 - 參考 Prism Launcher"""
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
            # 優先使用 tags 中的檔案名稱
            tags = self.local_tree.item(item, "tags")
            mod_id = None
            if tags and len(tags) > 0:
                mod_id = tags[0]  # tags 中存儲的是基礎檔案名稱
            else:
                # fallback: 從顯示的模組名稱推斷
                mod_id = mod_name

            if not mod_id:
                if hasattr(self, "status_label") and self.status_label.winfo_exists():
                    self.update_status(f"無法識別模組: {mod_name}")
                return

            # 找到對應的模組
            found_mod = None
            for mod in self.mod_manager.scan_mods():
                # 比較基礎檔案名稱（去除副檔名和 .disabled）
                mod_base_name = mod.filename.replace(".jar.disabled", "").replace(".jar", "")

                if mod_base_name == mod_id:
                    found_mod = mod
                    break
            LogUtils.info(f"找到的模組: {found_mod}", "ModManagementFrame")
            if not found_mod:
                if hasattr(self, "status_label") and self.status_label.winfo_exists():
                    self.update_status(f"找不到模組檔案: {mod_id}")
                return

            # 切換狀態
            success = False
            if found_mod.status == ModStatus.ENABLED:
                success = self.mod_manager.disable_mod(mod_id)
                action = "停用"
            else:
                success = self.mod_manager.enable_mod(mod_id)
                action = "啟用"

            if success:
                # 重新載入模組列表以反映狀態變更
                self.parent.after_idle(self.load_local_mods)
                if hasattr(self, "status_label") and self.status_label.winfo_exists():
                    self.update_status(f"已{action}模組: {mod_name}")
            else:
                if hasattr(self, "status_label") and self.status_label.winfo_exists():
                    self.update_status(f"{action}模組失敗: {mod_name}")

        except Exception as e:
            if hasattr(self, "status_label") and self.status_label.winfo_exists():
                self.update_status(f"操作失敗: {e}")
            LogUtils.error(f"切換模組狀態錯誤: {e}", "ModManagementFrame")

    def filter_local_mods(self, *args) -> None:
        """篩選本地模組"""
        self.refresh_local_list()

    def show_local_context_menu(self, event) -> None:
        """顯示本地模組右鍵選單"""
        selection = self.local_tree.selection()
        if not selection:
            return

        menu = tk.Menu(self.parent, tearoff=0, font=get_font("Microsoft JhengHei", 18))  # 動態字體縮放
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
                shutil.copy2(filename, target_path)

                UIUtils.show_info("成功", f"模組已匯入: {Path(filename).name}", self.parent)
                self.load_local_mods()

            except Exception as e:
                UIUtils.show_error("錯誤", f"匯入模組失敗: {e}", self.parent)

    def open_mods_folder(self) -> None:
        """開啟模組資料夾"""
        if not self.current_server:
            UIUtils.show_warning("警告", "請先選擇伺服器", self.parent)
            return

        mods_dir = Path(self.current_server.path) / "mods"
        if mods_dir.exists():
            os.startfile(str(mods_dir))
        else:
            UIUtils.show_warning("警告", "模組資料夾不存在", self.parent)

    def copy_mod_info(self) -> None:
        """複製模組資訊"""
        selection = self.local_tree.selection()
        if not selection:
            return

        try:
            item = selection[0]
            values = self.local_tree.item(item, "values")

            if values and len(values) >= 4:
                info = f"模組名稱: {values[1]}\n版本: {values[2]}\n狀態: {values[0]}\n檔案: {values[3] if len(values) > 3 else 'N/A'}"

                # 複製到剪貼板
                self.parent.clipboard_clear()
                self.parent.clipboard_append(info)
                self.parent.update()  # 確保剪貼板更新

                if hasattr(self, "status_label") and self.status_label.winfo_exists():
                    self.update_status("模組資訊已複製到剪貼板")
        except Exception as e:
            if hasattr(self, "status_label") and self.status_label.winfo_exists():
                self.status_label.configure(text=f"複製失敗: {e}")

    def show_in_explorer(self) -> None:
        """在檔案總管中顯示模組"""
        selection = self.local_tree.selection()
        if not selection or not self.current_server:
            return

        try:
            item = selection[0]
            tags = self.local_tree.item(item, "tags")

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
                    # 在檔案總管中選中該檔案
                    explorer_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "explorer.exe")
                    subprocess.run([explorer_path, "/select,", str(mod_file)], shell=False)

                    if hasattr(self, "status_label") and self.status_label.winfo_exists():
                        self.status_label.configure(text=f"已在檔案總管中顯示: {mod_file.name}")
                else:
                    if hasattr(self, "status_label") and self.status_label.winfo_exists():
                        self.status_label.configure(text="找不到要顯示的模組檔案")
            else:
                if hasattr(self, "status_label") and self.status_label.winfo_exists():
                    self.status_label.configure(text="無法識別模組檔案")

        except Exception as e:
            if hasattr(self, "status_label") and self.status_label.winfo_exists():
                self.status_label.configure(text=f"開啟檔案總管失敗: {e}")

    def delete_local_mod(self) -> None:
        """刪除本地模組"""
        selection = self.local_tree.selection()
        if not selection or not self.current_server:
            return

        try:
            item = selection[0]
            values = self.local_tree.item(item, "values")
            tags = self.local_tree.item(item, "tags")

            if not values or len(values) < 2:
                return

            mod_name = values[1]

            # 確認刪除
            result = UIUtils.ask_yes_no_cancel(
                "確認刪除", f"確定要刪除模組 '{mod_name}' 嗎？\n此操作無法復原。", parent=self.parent, show_cancel=False
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
                else:
                    if hasattr(self, "status_label") and self.status_label.winfo_exists():
                        self.status_label.configure(text="找不到要刪除的模組檔案")
            else:
                if hasattr(self, "status_label") and self.status_label.winfo_exists():
                    self.status_label.configure(text="無法識別要刪除的模組")

        except Exception as e:
            if hasattr(self, "status_label") and self.status_label.winfo_exists():
                self.status_label.configure(text=f"刪除失敗: {e}")
            UIUtils.show_error("錯誤", f"刪除模組失敗: {e}", self.parent)

    def get_frame(self) -> Optional[ctk.CTkFrame]:
        """獲取主框架"""
        if hasattr(self, "main_frame") and self.main_frame:
            return self.main_frame
        else:
            LogUtils.debug("主框架未初始化")
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
                except Exception:
                    pass
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
                except Exception:
                    pass

            # 更新狀態顯示
            self.update_selection_status()

        except Exception as e:
            LogUtils.error(f"切換全選失敗: {e}", "ModManagementFrame")

    def batch_toggle_selected(self) -> None:
        """批量切換選中模組的啟用/停用狀態"""
        try:
            if not self.mod_manager:
                UIUtils.show_error("錯誤", "模組管理器未初始化", self.parent)
                return
            selected_items = self.local_tree.selection()
            if not selected_items:
                UIUtils.show_warning("提示", "請先選擇要操作的模組", self.parent)
                return
            selected_mods = []
            processed_base_names = set()
            for item in selected_items:
                tags = self.local_tree.item(item, "tags")
                if tags and len(tags) > 0:
                    mod_base_name = tags[0]
                    if mod_base_name in processed_base_names:
                        continue
                    processed_base_names.add(mod_base_name)
                    found_mod = None
                    for mod in self.mod_manager.scan_mods():
                        current_base_name = mod.filename.replace(".jar.disabled", "").replace(".jar", "")
                        if current_base_name == mod_base_name:
                            if found_mod is None or mod.status == ModStatus.ENABLED:
                                found_mod = mod
                    if found_mod:
                        selected_mods.append(found_mod)
            if not selected_mods:
                UIUtils.show_warning("提示", "找不到對應的模組檔案", self.parent)
                return

            def do_batch():
                total = len(selected_mods)
                counter = [0]
                lock = threading.Lock()

                def update_progress():
                    percent = counter[0] / total * 100 if total else 0
                    self.progress_var.set(percent)
                    if hasattr(self, "progress_bar"):
                        self.progress_bar.update_idletasks()

                def toggle_mod(mod):
                    mod_id = mod.filename.replace(".jar.disabled", "").replace(".jar", "")
                    if mod.status == ModStatus.ENABLED:
                        result = self.mod_manager.disable_mod(mod_id)
                    else:
                        result = self.mod_manager.enable_mod(mod_id)
                    with lock:
                        counter[0] += 1
                        if hasattr(self, "main_frame") and self.main_frame and hasattr(self.main_frame, "after"):
                            self.main_frame.after(0, update_progress)
                        elif hasattr(self, "parent") and self.parent and self.parent.winfo_exists():
                            self.parent.after(0, update_progress)
                    time.sleep(0.5)  # 讓進度條動畫更明顯
                    return result

                with ThreadPoolExecutor(max_workers=8) as executor:
                    results = list(executor.map(toggle_mod, selected_mods))
                success_count = sum(1 for r in results if r)

                # Safe progress reset
                if hasattr(self, "main_frame") and self.main_frame and hasattr(self.main_frame, "after"):
                    self.main_frame.after(0, lambda: self.progress_var.set(0))
                elif hasattr(self, "parent") and self.parent and self.parent.winfo_exists():
                    self.parent.after(0, lambda: self.progress_var.set(0))

                if hasattr(self, "status_label") and self.status_label.winfo_exists():
                    status_text = f"已切換 {success_count}/{len(selected_mods)} 個模組狀態"
                    if hasattr(self, "main_frame") and self.main_frame and hasattr(self.main_frame, "after"):
                        self.main_frame.after(0, lambda: self.status_label.configure(text=status_text))
                    elif hasattr(self, "parent") and self.parent and self.parent.winfo_exists():
                        self.parent.after(0, lambda: self.status_label.configure(text=status_text))

                # Safe reload
                if hasattr(self, "main_frame") and self.main_frame and hasattr(self.main_frame, "after"):
                    self.main_frame.after(0, self.load_local_mods)
                elif hasattr(self, "parent") and self.parent and self.parent.winfo_exists():
                    self.parent.after(0, self.load_local_mods)

            threading.Thread(target=do_batch, daemon=True).start()
        except Exception as e:
            self.update_progress_safe(0)
            UIUtils.show_error("錯誤", f"批量操作失敗: {e}", self.parent)

    def update_selection_status(self) -> None:
        """更新選擇狀態顯示"""
        try:
            selected_count = len(self.local_tree.selection())
            total_count = len(self.local_tree.get_children())

            if selected_count == 0:
                status_text = f"找到 {total_count} 個模組"
            else:
                status_text = f"找到 {total_count} 個模組，已選擇 {selected_count} 個"

            if hasattr(self, "status_label"):
                self.status_label.configure(text=status_text)

        except Exception as e:
            LogUtils.error(f"更新選擇狀態失敗: {e}", "ModManagementFrame")

    def on_tree_selection_changed(self, event=None) -> None:
        """樹狀檢視選擇變化事件"""
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
                except Exception:
                    pass
            elif selected_items_count == total_items:
                self.all_selected = True
                try:
                    if hasattr(self.select_all_btn, "configure"):
                        self.select_all_btn.configure(text="❌ 取消全選")
                except Exception:
                    pass
            else:
                self.all_selected = False
                try:
                    if hasattr(self.select_all_btn, "configure"):
                        self.select_all_btn.configure(text="☑️ 全選")
                except Exception:
                    pass

        except Exception as e:
            LogUtils.error(f"處理選擇變化失敗: {e}", "ModManagementFrame")

    def pack(self, **kwargs) -> None:
        """讓框架可以被 pack"""
        if hasattr(self, "main_frame") and self.main_frame:
            self.main_frame.pack(**kwargs)
        else:
            LogUtils.debug("主框架未初始化，無法打包", "ModManagementFrame")

    def grid(self, **kwargs) -> None:
        """讓框架可以被 grid"""
        if hasattr(self, "main_frame") and self.main_frame:
            self.main_frame.grid(**kwargs)
        else:
            LogUtils.debug("主框架未初始化，無法佈局", "ModManagementFrame")
