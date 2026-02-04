#!/usr/bin/env python3
"""主視窗
Minecraft 伺服器管理器的主要使用者介面
This module defines the main window for the Minecraft Server Manager application.
"""

import contextlib
import queue
import re
import sys
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog
from typing import Any, Callable

import customtkinter as ctk

from ..core import LoaderManager, MinecraftVersionManager, ServerManager
from ..models import ServerConfig
from ..utils import (
    FontManager,
    PathUtils,
    RuntimePaths,
    ServerCommands,
    ServerDetectionUtils,
    ServerPropertiesHelper,
    SubprocessUtils,
    UIUtils,
    UpdateChecker,
    WindowManager,
    get_logger,
    get_settings_manager,
)
from ..version_info import APP_VERSION, GITHUB_OWNER, GITHUB_REPO
from . import (
    CreateServerFrame,
    ManageServerFrame,
    ModManagementFrame,
    WindowPreferencesDialog,
)

logger = get_logger().bind(component="MainWindow")


class MinecraftServerManager:
    """Minecraft 伺服器管理器主視窗類別
    Main window class for Minecraft Server Manager application
    """

    # ====== 核心設定與初始化 ======
    # 設定伺服器根目錄
    def set_servers_root(self, new_root: str | None = None) -> str:
        """取得或設定伺服器根目錄
        Get or set the servers root directory

        Args:
            new_root (str, optional): 新的根目錄路徑

        Returns:
            str: 伺服器根目錄完整路徑

        """
        settings = get_settings_manager()

        def _fail_exit(msg: str):
            """錯誤退出處理"""
            UIUtils.show_error("錯誤", msg, self.root)
            self.root.destroy()
            exit(0)

        def _ensure_directory_exists(path: Path):
            """確保目錄存在"""
            if not path.exists():
                try:
                    path.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    logger.error(f"無法建立資料夾: {e}\n{traceback.format_exc()}")
                    _fail_exit(f"無法建立資料夾: {e}")

        def _normalize_base_dir(path_str: str) -> str:
            """將輸入路徑正規化成『使用者選擇的主資料夾』(base dir)。

            - 若輸入本身已是 ...\\servers，則回傳其上層資料夾（向後相容舊設定）。
            """
            norm = str(Path(path_str).resolve())
            try:
                if Path(norm).name.lower() == "servers":
                    parent = str(Path(norm).parent)
                    if parent:
                        return parent
            except Exception as e:
                logger.debug(f"路徑正規化輕微錯誤 (base dir check): {e}", "MainWindow")
            return norm

        def _servers_dir_from_base(base_dir: str) -> str:
            return str((Path(base_dir) / "servers").resolve())

        def _prompt_for_directory() -> str:
            """提示選擇目錄"""
            UIUtils.show_info(
                "選擇伺服器資料夾",
                "請選擇要存放所有 Minecraft 伺服器的主資料夾\n(系統會在該資料夾內自動建立 servers 子資料夾)",
                self.root,
            )
            folder = filedialog.askdirectory(title="選擇伺服器主資料夾")
            if not folder:
                if UIUtils.ask_yes_no_cancel(
                    "結束程式",
                    "未選擇資料夾，是否要結束程式？",
                    self.root,
                    show_cancel=False,
                ):
                    self.root.destroy()
                    exit(0)
                return ""
            return str(Path(folder))

        # === 執行主邏輯 ===
        if new_root:
            base_dir = _normalize_base_dir(new_root)
            try:
                settings.set_servers_root(base_dir)
            except Exception as e:
                logger.error(f"無法寫入設定: {e}\n{traceback.format_exc()}")
                UIUtils.show_error("設定錯誤", f"無法寫入設定: {e}", self.root)
        else:
            stored = settings.get_servers_root()
            base_dir = _normalize_base_dir(stored) if stored else ""
            while not base_dir:
                base_dir = _prompt_for_directory()
                if base_dir:
                    try:
                        settings.set_servers_root(base_dir)
                    except Exception as e:
                        logger.error(f"無法寫入設定: {e}\n{traceback.format_exc()}")
                        UIUtils.show_error("設定錯誤", f"無法寫入設定: {e}", self.root)

            # 向後相容：若舊設定直接存的是 ...\servers，這裡會自動轉成 base_dir 並回寫
            try:
                if stored and Path(stored).name.lower() == "servers":
                    settings.set_servers_root(base_dir)
            except Exception as e:
                logger.debug(f"向後相容性路徑檢查失敗: {e}", "MainWindow")

        servers_root = _servers_dir_from_base(base_dir)

        # 建立資料夾並更新屬性
        path_obj = Path(servers_root)
        _ensure_directory_exists(path_obj)
        self.servers_root = str(path_obj.resolve())
        return self.servers_root

    # 應用程式關閉處理
    def on_closing(self) -> None:
        """主視窗關閉處理，清理快取並儲存視窗狀態
        Handle main window closing, clear caches and save window state

        Args:
            None

        Returns:
            None

        """
        logger.debug("程式即將關閉！", "MainWindow")

        try:
            # 儲存視窗狀態
            get_logger().bind(component="WindowState").debug("儲存視窗狀態...")
            WindowManager.save_main_window_state(self.root)

            # 清理字體快取，避免銷毀時的錯誤
            logger.debug("清理字體快取...", "MainWindow")
            FontManager.cleanup_fonts()

            # 清理可能的子視窗
            for widget in self.root.winfo_children():
                try:
                    if isinstance(widget, (tk.Toplevel, ctk.CTkToplevel)):
                        widget.destroy()
                except Exception as e:
                    logger.error(f"清理子視窗時發生錯誤: {e}\n{traceback.format_exc()}")

        except Exception as e:
            logger.error(f"清理資源時發生錯誤: {e}\n{traceback.format_exc()}")
        finally:
            # 最後銷毀主視窗
            try:
                self.root.destroy()
            except Exception as e:
                logger.error(f"銷毀主視窗時發生錯誤: {e}\n{traceback.format_exc()}")
                # 強制退出
                sys.exit(0)

    # 主視窗初始化
    def __init__(self, root: tk.Tk):
        """初始化主視窗管理器
        Initialize main window manager

        Args:
            root (tk.Tk): 主視窗根物件

        Returns:
            None

        """
        self.root = root
        self.mini_sidebar: Any | None = None
        self.active_nav_title: str | None = None
        self.nav_buttons: dict[str, Any] = {}
        self._console_queue: queue.Queue[Any] = queue.Queue()

        # 初始化 UI 更新佇列 Initialize UI update queue
        self.ui_queue: queue.Queue[Callable[[], Any]] = queue.Queue()
        UIUtils.start_ui_queue_pump(self.root, self.ui_queue)

        # 獲取設定管理器
        self.settings = get_settings_manager()

        self.setup_window()

        # 啟動時檢查 servers_root
        self.servers_root = self.set_servers_root()

        # 初始化管理器
        self.version_manager = MinecraftVersionManager()
        self.loader_manager = LoaderManager()
        self.server_manager = ServerManager(servers_root=self.servers_root)

        # 建立介面
        self.create_widgets()

        # 使用新的視窗管理器設定視窗大小和位置
        WindowManager.setup_main_window(self.root)

        # 綁定視窗狀態追蹤，用於記住視窗大小和位置
        WindowManager.bind_window_state_tracking(self.root)

        # 首次執行提示和自動更新檢查
        self.root.after(1000, self._handle_startup_tasks)  # 延遲執行以確保界面完全載入

        # 載入資料
        self.preload_all_versions()
        self.load_data_async()

    def _ensure_manage_server_frame(self) -> None:
        """延後建立管理伺服器頁面，降低啟動時卡頓與撕裂。"""
        if getattr(self, "manage_server_frame", None) is not None:
            return
        self.manage_server_frame = ManageServerFrame(
            self.content_frame,
            self.server_manager,
            self.on_server_selected,
            self.show_create_server,
            set_servers_root=self.set_servers_root,
        )

    def _ensure_mod_management_frame(self) -> None:
        """延後建立模組管理頁面，降低啟動時卡頓與撕裂。"""
        if getattr(self, "mod_frame", None) is not None:
            return
        self.mod_frame = ModManagementFrame(
            self.content_frame,
            self.server_manager,
            self.on_server_selected,
            self.version_manager,
        )

    # ====== 資料載入與版本管理 ======
    # 預載所有版本資訊
    def preload_all_versions(self) -> None:
        """啟動時預先抓取版本資訊
        Preload version information at startup

        Args:
            None

        Returns:
            None

        """

        def fetch_all():
            logger.debug("預先抓取 Minecraft 所有版本...", "MainWindow")
            self.version_manager.fetch_versions()
            logger.debug("Minecraft 所有版本載入完成", "MainWindow")
            logger.debug("預先抓取所有載入器版本...", "MainWindow")
            self.loader_manager.preload_loader_versions()
            logger.debug("所有載入器版本載入完成", "MainWindow")

        UIUtils.run_async(fetch_all)

    # 非同步載入資料
    def load_data_async(self) -> None:
        """非同步載入資料
        Load data asynchronously

        Args:
            None

        Returns:
            None

        """

        def load_versions():
            try:
                versions = self.version_manager.get_versions()
                self.ui_queue.put(lambda: self.create_server_frame.update_versions(versions))
            except Exception as e:
                error_msg = f"載入版本資訊失敗: {e}\n{traceback.format_exc()}"
                self.ui_queue.put(lambda: logger.error(error_msg))

        UIUtils.run_async(load_versions)

    # ====== 啟動任務與首次執行處理 ======
    # 處理啟動任務
    def _handle_startup_tasks(self) -> None:
        """處理啟動時的任務：首次執行提示和自動更新檢查
        Handle startup tasks: first-run prompt and auto-update check

        Args:
            None

        Returns:
            None

        """
        settings = get_settings_manager()

        # 檢查是否為首次執行
        if not settings.is_first_run_completed():
            self._show_first_run_prompt()

        # 如果啟用自動更新，則檢查更新
        elif settings.is_auto_update_enabled():
            self._check_for_updates(show_msg=False)

    def _show_first_run_prompt(self) -> None:
        """顯示首次執行的自動更新設定提示
        Show first-run prompt for auto-update preference.
        """
        settings = get_settings_manager()

        # 創建首次執行對話框
        first_run_dialog = ctk.CTkToplevel(self.root)
        first_run_dialog.withdraw()  # 先隱藏
        first_run_dialog.title("歡迎使用 Minecraft 伺服器管理器")
        first_run_dialog.resizable(False, False)

        # 統一設定視窗屬性：相對於父視窗置中、設為模態視窗
        width = 480
        height = 250
        UIUtils.setup_window_properties(
            window=first_run_dialog,
            parent=self.root,
            width=width,
            height=height,
            bind_icon=True,
            center_on_parent=True,
            make_modal=True,
            delay_ms=250,  # 使用稍長延遲確保圖示綁定成功
        )
        first_run_dialog.deiconify()  # 顯示

        # 主容器
        main_frame = ctk.CTkFrame(first_run_dialog)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 標題
        title_label = ctk.CTkLabel(main_frame, text="🎮 歡迎使用！", font=FontManager.get_font(size=18, weight="bold"))
        title_label.pack(pady=(10, 15))

        # 說明文字
        info_label = ctk.CTkLabel(
            main_frame,
            text="是否要啟用自動檢查更新功能？\n\n啟用後，程式會在啟動時自動檢查新版本。\n您可以隨時在「關於」視窗中更改此設定。",
            font=FontManager.get_font(size=15),
            justify="center",
        )
        info_label.pack(pady=(0, 20))

        # 按鈕容器
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x", pady=(0, 10))

        def _enable_auto_update():
            settings.set_auto_update_enabled(True)
            settings.mark_first_run_completed()
            first_run_dialog.destroy()
            # 立即檢查更新
            self._check_for_updates(show_msg=False)

        def _disable_auto_update():
            settings.set_auto_update_enabled(False)
            settings.mark_first_run_completed()
            first_run_dialog.destroy()

        # 啟用按鈕
        enable_btn = ctk.CTkButton(
            button_frame,
            text="啟用自動更新",
            command=_enable_auto_update,
            font=FontManager.get_font(size=12, weight="bold"),
            width=140,
            height=35,
        )
        enable_btn.pack(side="left", padx=(20, 10))

        # 不啟用按鈕
        disable_btn = ctk.CTkButton(
            button_frame,
            text="暫不啟用",
            command=_disable_auto_update,
            font=FontManager.get_font(size=12),
            width=140,
            height=35,
            fg_color="gray",
            hover_color=("gray70", "gray30"),
        )
        disable_btn.pack(side="right", padx=(10, 20))

    def _check_for_updates(self, show_msg: bool = True) -> None:
        """檢查更新
        Check for updates.

        Args:
            show_msg (bool): 是否顯示「已是最新版本」的訊息

        """
        try:
            # 使用版本資訊常數
            UpdateChecker.check_and_prompt_update(
                APP_VERSION,
                GITHUB_OWNER,
                GITHUB_REPO,
                show_up_to_date_message=show_msg,
                parent=self.root,
            )
        except Exception as e:
            logger.error(f"自動更新檢查失敗: {e}\n{traceback.format_exc()}")
            if show_msg:
                UIUtils.show_error("更新檢查失敗", f"無法檢查更新：{e}", self.root)

    # ====== 視窗設定與主題配置 ======
    # 設定主視窗
    def setup_window(self) -> None:
        """設定主視窗標題、圖示和現代化樣式
        Set up the main window with title, icon, and modern style

        Args:
            None

        Returns:
            None

        """
        # 設定主視窗標題
        self.root.title("Minecraft 伺服器管理器")

        # 設定淺色主題
        self.setup_light_theme()

        # 主視窗僅需要綁定圖示，不需要置中或模態設定，使用更長延遲確保圖示設定成功
        UIUtils.setup_window_properties(
            window=self.root,
            parent=None,
            bind_icon=True,
            center_on_parent=False,
            make_modal=False,
            delay_ms=300,  # 主視窗使用更長延遲確保圖示設定成功
        )

    def setup_light_theme(self) -> None:
        """設定淺色主題配置
        Set up light theme configuration for CustomTkinter.
        """
        # 淺色主題色彩配置
        self.colors = {
            "primary": "#2563eb",  # 主要藍色
            "secondary": "#64748b",  # 次要灰色
            "success": "#059669",  # 成功綠色
            "warning": "#d97706",  # 警告橙色
            "danger": "#dc2626",  # 危險紅色
            "background": "#ffffff",  # 白色背景
            "surface": "#f8fafc",  # 表面顏色
            "text": "#1f2937",  # 深色文字 (高對比)
            "text_secondary": "#6b7280",  # 次要文字
            "border": "#e5e7eb",  # 邊框顏色
            "menu_bg": "#ffffff",  # 功能選單背景
        }

    # ====== 介面元件創建 ======
    # 建立所有介面元件
    def create_widgets(self) -> None:
        """建立所有介面元件，包含標題和主要內容
        Create all interface widgets including header and main content

        Args:
            None

        Returns:
            None

        """
        # CustomTkinter 會自動處理背景顏色

        # 頂部標題區域
        self.create_header()

        # 主內容區域
        self.create_main_content()

        # 預設顯示建立伺服器頁面
        self.show_create_server()

    def create_header(self) -> None:
        """建立現代化標題區域
        Create a modern header section with title.
        """
        header_frame = ctk.CTkFrame(self.root, height=60, corner_radius=0)
        header_frame.pack(fill="x", padx=0, pady=0)
        header_frame.pack_propagate(False)

        # 內容容器
        header_content = ctk.CTkFrame(header_frame, fg_color="transparent")
        header_content.pack(fill="both", expand=True, padx=20, pady=15)

        # 左側 - 選單按鈕和標題
        left_section = ctk.CTkFrame(header_content, fg_color="transparent")
        left_section.pack(side="left", fill="y", anchor="w")

        # 側邊欄開合按鈕
        self.sidebar_toggle_btn = ctk.CTkButton(
            left_section,
            text="☰",
            font=FontManager.get_font(size=18),
            width=FontManager.get_dpi_scaled_size(40),
            height=FontManager.get_dpi_scaled_size(32),
            command=self.toggle_sidebar,
        )
        self.sidebar_toggle_btn.pack(side="left", padx=(0, 15))

        # 標題區域
        title_section = ctk.CTkFrame(left_section, fg_color="transparent")
        title_section.pack(side="left", fill="y")

        title_label = ctk.CTkLabel(
            title_section,
            text="Minecraft 伺服器管理器",
            font=FontManager.get_font(size=20, weight="bold"),
        )
        title_label.pack(anchor="w")

    def create_main_content(self) -> None:
        """建立主內容區域
        Create the main content area with sidebar and content frames.
        """
        # 主容器
        main_container = ctk.CTkFrame(self.root, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=0, pady=0)
        # 保存容器參考，切換側邊欄時只調整 grid 欄寬（minsize），避免反覆 configure(width=...) 造成較大的重排成本
        self.main_container = main_container

        # 初始寬度
        self._nav_full_width = 250
        self._nav_mini_width = FontManager.get_dpi_scaled_size(70)
        # nav_container 的 grid padx=(20,20)；用 column minsize 時要把 padding 算進去，才會得到一致的實際側邊欄寬度
        self._nav_column_padding = 40

        # 你期望的 UX：完整側邊欄會「推開」內容區；切到迷你側邊欄時，整個頁面跟著收窄。
        # 這裡用 2 欄 grid：左側 nav_container 固定寬度（切換只改寬度），右側 content_container 自動伸縮。
        main_container.grid_rowconfigure(0, weight=1)
        main_container.grid_columnconfigure(0, weight=0, minsize=self._nav_full_width + self._nav_column_padding)
        main_container.grid_columnconfigure(1, weight=1)

        # 左側導航容器
        self.nav_container = ctk.CTkFrame(main_container, fg_color="transparent")
        self.nav_container.grid(row=0, column=0, sticky="nsew", padx=(20, 20), pady=20)
        self.nav_container.grid_rowconfigure(0, weight=1)
        self.nav_container.grid_columnconfigure(0, weight=1)
        try:
            self.nav_container.grid_propagate(False)
            self.nav_container.configure(width=int(self._nav_full_width))
        except Exception as e:
            logger.debug(f"設定導航欄寬度失敗: {e}", "MainWindow")

        # 右側內容容器
        self.content_container = ctk.CTkFrame(main_container, fg_color="transparent")
        self.content_container.grid(row=0, column=1, sticky="nsew", padx=(0, 20), pady=20)
        self.content_container.grid_rowconfigure(0, weight=1)
        self.content_container.grid_columnconfigure(0, weight=1)

        self.content_frame = ctk.CTkFrame(self.content_container)
        self.content_frame.grid(row=0, column=0, sticky="nsew")
        # 內容區使用 stack grid：所有頁面都放在 (0,0)，切換只做 grid_remove + tkraise
        self.content_frame.grid_rowconfigure(0, weight=1)
        self.content_frame.grid_columnconfigure(0, weight=1)

        # 側邊欄
        self.create_sidebar(self.nav_container)

        # 建立預設頁面：建立伺服器（其他頁面延後建立，以降低啟動時的 UI 卡頓/撕裂）
        self.create_server_frame = CreateServerFrame(
            self.content_frame,
            self.version_manager,
            self.loader_manager,
            self.on_server_created,
            self.server_manager,  # 傳入正確的 server_manager 實例
        )
        # 預先 grid，切換時只需 tkraise，不用重複 pack/reflow
        try:
            self.create_server_frame.grid(row=0, column=0, sticky="nsew")
        except Exception as e:
            logger.debug(f"CreateServerFrame grid 設置失敗: {e}", "MainWindow")

        # 延後建立，首次切換頁面時才初始化
        self.manage_server_frame = None
        self.mod_frame = None

    def create_sidebar(self, parent) -> None:
        """建立現代化側邊欄
        Create a modern sidebar with navigation buttons and status information.

        Args:
            parent: 父元件

        """
        # 側邊欄（放進 nav_container 內；切換僅影響 nav_container 寬度與顯示的 frame）
        self.sidebar = ctk.CTkFrame(parent, width=self._nav_full_width, fg_color=self.colors["menu_bg"])
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        # 初始狀態：顯示
        self.sidebar_visible = True

        # 側邊欄標題
        sidebar_title = ctk.CTkLabel(
            self.sidebar,
            text="功能選單",
            font=FontManager.get_font(size=16, weight="bold"),
            text_color="#000000",
        )
        sidebar_title.pack(anchor="w", padx=20, pady=(20, 15))

        # 創建可滾動的按鈕區域
        self.nav_scroll_frame = ctk.CTkScrollableFrame(self.sidebar, label_text="")
        self.nav_scroll_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        # 導航按鈕（只保存 CTkButton 本體，避免切換時遍歷整個 sidebar 導致撕裂）
        self.nav_buttons = {}
        self.active_nav_title = None

        nav_items = [
            ("🆕", "建立伺服器", "建立新的 Minecraft 伺服器", self.show_create_server),
            ("🔧", "管理伺服器", "管理現有的伺服器", self.show_manage_server),
            ("🧩", "模組管理", "管理伺服器模組與資源", self.show_mod_management),
            ("📥", "匯入伺服器", "匯入現有伺服器檔案", self.import_server),
            ("📁", "開啟資料夾", "開啟伺服器儲存資料夾", self.open_servers_folder),
            ("ⓘ", "關於程式", "查看程式資訊", self.show_about),
        ]

        for emoji, title, desc, command in nav_items:
            btn_frame = self.create_nav_button(self.nav_scroll_frame, emoji, title, desc, command)
            btn_frame.pack(fill="x", padx=5, pady=3)

        # 底部資訊（完整/迷你側邊欄都要顯示）
        self._create_sidebar_footer(self.sidebar, mini=False)

    def _create_sidebar_footer(self, parent, *, mini: bool) -> None:
        """在側邊欄底部顯示版本資訊（完整/迷你共用）。"""
        try:
            pad_x = 20 if not mini else 10
            pad_y = 20 if not mini else 12
            font_size = 14 if not mini else 12

            info_frame = ctk.CTkFrame(parent, fg_color="transparent")
            info_frame.pack(side="bottom", fill="x", padx=pad_x, pady=pad_y)

            version_label = ctk.CTkLabel(
                info_frame,
                text=f"版本 {APP_VERSION}",
                font=FontManager.get_font(size=font_size),
                text_color=("#a0aec0", "#a0aec0"),
            )
            version_label.pack(anchor="w")
        except Exception as e:
            logger.exception(f"建立側邊欄底部資訊失敗: {e}")

    def create_nav_button(self, parent, icon, title, description, command) -> ctk.CTkFrame:
        """建立導航按鈕
        Create navigation button

        Args:
            parent: 父元件
            icon: 圖示
            title: 標題
            description: 描述
            command: 命令回調

        Returns:
            CTkFrame: 按鈕容器框架

        """
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")

        # 建立按鈕
        btn_text = f"{icon} {title}" if icon else title
        btn = ctk.CTkButton(
            btn_frame,
            text=btn_text,
            font=FontManager.get_font(size=20),
            anchor="w",
            height=FontManager.get_dpi_scaled_size(55),
            corner_radius=8,
            border_spacing=FontManager.get_dpi_scaled_size(10),
            fg_color=("#3b82f6", "#3b82f6"),
            hover_color=("#1d4ed8", "#1d4ed8"),
            text_color=("#ffffff", "#ffffff"),
        )
        btn.pack(fill="x", padx=2, pady=2)

        # 描述標籤
        ctk.CTkLabel(
            btn_frame,
            text=description,
            font=FontManager.get_font(size=14),
            text_color=("#6b7280", "#6b7280"),
            anchor="w",
        ).pack(fill="x", padx=5, pady=(0, 5))

        # 設定點擊事件
        main_nav_titles = {"建立伺服器", "管理伺服器", "模組管理"}

        def on_click():
            if title in main_nav_titles:
                self.set_active_nav_button(title)
            command()

        btn.configure(command=on_click)
        self.nav_buttons[title] = btn
        return btn_frame

    def set_active_nav_button(self, title: str) -> None:
        """設定活動導航按鈕
        Set active navigation button

        Args:
            title: 要設為活動的導航標題

        """
        if not title:
            return

        # 同一個就不重設，避免不必要重繪
        if getattr(self, "active_nav_title", None) == title:
            return

        # 顏色配置
        default_colors = {"fg": ("#3b82f6", "#3b82f6"), "hover": ("#1d4ed8", "#1d4ed8")}
        active_colors = {"fg": ("#1d4ed8", "#1d4ed8"), "hover": ("#1e40af", "#1e40af")}

        def configure_button_colors(btn_widget: ctk.CTkButton, colors) -> None:
            """安全地設定按鈕顏色 / Safely configure button colors"""
            try:
                if btn_widget and hasattr(btn_widget, "configure"):
                    btn_widget.configure(fg_color=colors["fg"], hover_color=colors["hover"])
            except Exception as e:
                logger.exception(f"設定導航按鈕顏色失敗: {e}")

        # 只重置前一個 + 設定新的，避免每次遍歷所有導航按鈕造成撕裂
        prev_title = getattr(self, "active_nav_title", None)
        if prev_title:
            prev_btn = self.nav_buttons.get(prev_title)
            if isinstance(prev_btn, ctk.CTkButton):
                configure_button_colors(prev_btn, default_colors)

        new_btn = self.nav_buttons.get(title)
        if isinstance(new_btn, ctk.CTkButton):
            configure_button_colors(new_btn, active_colors)

        self.active_nav_title = title

    def toggle_sidebar(self) -> None:
        """乾淨利索地切換側邊欄顯示/隱藏，無動畫"""
        # 用 after_idle coalesce 多次點擊，減少反覆觸發造成撕裂。
        # 參考 tkinter 事件迴圈/after(): https://docs.python.org/3/library/tkinter.html
        self.sidebar_visible = not bool(getattr(self, "sidebar_visible", True))
        try:
            job = getattr(self, "_sidebar_toggle_job", None)
            if job:
                try:
                    self.root.after_cancel(job)
                except Exception as e:
                    logger.debug(f"取消 toggle_sidebar job 失敗: {e}", "MainWindow")
        except Exception as e:
            logger.debug(f"toggle_sidebar 發生錯誤: {e}", "MainWindow")
        self._sidebar_toggle_job = self.root.after_idle(self._apply_sidebar_visibility)

    def _apply_sidebar_visibility(self) -> None:
        """實際套用側邊欄顯示狀態（由 after_idle 觸發）。"""
        try:
            if not getattr(self, "sidebar_visible", True):
                # 顯示迷你側邊欄：改 nav_container 寬度 + 只切換內部 frame（不重建）
                try:
                    container = getattr(self, "main_container", None)
                    if container is not None:
                        pad = int(getattr(self, "_nav_column_padding", 0))
                        container.grid_columnconfigure(0, minsize=int(self._nav_mini_width) + pad)
                    nav = getattr(self, "nav_container", None)
                    if nav is not None:
                        nav.configure(width=int(self._nav_mini_width))
                except Exception as e:
                    logger.debug(f"設定 Nav 寬度 (Mini) 失敗: {e}", "MainWindow")

                if hasattr(self, "sidebar") and self.sidebar:
                    try:
                        self.sidebar.grid_remove()
                    except Exception as e:
                        logger.debug(f"隱藏 sidebar 失敗: {e}", "MainWindow")
                self.create_mini_sidebar()
            else:
                # 顯示完整側邊欄，隱藏迷你側邊欄
                try:
                    container = getattr(self, "main_container", None)
                    if container is not None:
                        pad = int(getattr(self, "_nav_column_padding", 0))
                        container.grid_columnconfigure(0, minsize=int(self._nav_full_width) + pad)
                    nav = getattr(self, "nav_container", None)
                    if nav is not None:
                        nav.configure(width=int(self._nav_full_width))
                except Exception as e:
                    logger.debug(f"設定 Nav 寬度 (Full) 失敗: {e}", "MainWindow")

                if hasattr(self, "mini_sidebar") and self.mini_sidebar:
                    try:
                        self.mini_sidebar.grid_remove()
                    except Exception as e:
                        logger.debug(f"隱藏 mini_sidebar 失敗: {e}", "MainWindow")
                if hasattr(self, "sidebar") and self.sidebar:
                    try:
                        self.sidebar.grid()
                    except Exception as e:
                        logger.debug(f"顯示 sidebar 失敗: {e}", "MainWindow")
        except Exception as e:
            logger.error(f"切換側邊欄失敗: {e}\n{traceback.format_exc()}")

    def create_mini_sidebar(self) -> None:
        """創建迷你側邊欄（只顯示圖示）
        Create a mini sidebar that only shows icons for quick access.
        """
        # 只建立一次；之後切換僅 grid/grid_remove，避免重建大量元件造成撕裂
        if hasattr(self, "mini_sidebar"):
            try:
                if self.mini_sidebar and self.mini_sidebar.winfo_exists():
                    try:
                        self.mini_sidebar.grid(row=0, column=0, sticky="nsew")
                    except Exception as e:
                        logger.debug(f"重顯示 mini_sidebar 失敗: {e}", "MainWindow")
                    return
            except Exception as e:
                logger.debug(f"檢查 mini_sidebar 失敗: {e}", "MainWindow")

        # 使用簡化的迷你側邊欄
        container = getattr(self, "nav_container", None) or self.sidebar.master
        self.mini_sidebar = ctk.CTkFrame(container, width=self._nav_mini_width, fg_color=self.colors["menu_bg"])
        self.mini_sidebar.grid(row=0, column=0, sticky="nsew")
        self.mini_sidebar.grid_propagate(False)

        # 迷你側邊欄標題
        mini_title = ctk.CTkLabel(
            self.mini_sidebar,
            text="功能選單",
            font=FontManager.get_font(size=14, weight="bold"),
            text_color="#1f2937",
        )
        mini_title.pack(pady=(15, 10))

        # 圖示按鈕容器（expand=True，確保底部資訊能固定在最下方）
        icons_frame = ctk.CTkFrame(self.mini_sidebar, fg_color="transparent")
        icons_frame.pack(fill="both", expand=True)

        # 圖示按鈕
        nav_icons = [
            ("🆕", "建立伺服器", self.show_create_server),
            ("🔧", "管理伺服器", self.show_manage_server),
            ("🧩", "模組管理", self.show_mod_management),
            ("📥", "匯入伺服器", self.import_server),
            ("📁", "開啟資料夾", self.open_servers_folder),
            ("ⓘ", "關於程式", self.show_about),
        ]

        for icon, tooltip, command in nav_icons:
            btn = ctk.CTkButton(
                icons_frame,
                text=icon,
                font=FontManager.get_font(size=20),
                width=FontManager.get_dpi_scaled_size(55),
                height=FontManager.get_dpi_scaled_size(55),
                corner_radius=8,
                fg_color=("#3b82f6", "#3b82f6"),
                hover_color=("#1d4ed8", "#1d4ed8"),
                text_color=("#ffffff", "#ffffff"),
                command=command,
            )
            btn.pack(pady=3)
            self.create_tooltip(btn, tooltip)

        # 底部資訊（迷你側邊欄也顯示）
        self._create_sidebar_footer(self.mini_sidebar, mini=True)

    def create_tooltip(self, widget, text) -> None:
        """為元件創建工具提示
        Create a tooltip for a widget.
        """
        UIUtils.bind_tooltip(
            widget,
            text,
            bg="#2b2b2b",
            fg="white",
            font=("Microsoft JhengHei", 9),
            padx=8,
            pady=4,
            offset_x=10,
            offset_y=10,
            auto_hide_ms=None,
        )

    def show_create_server(self) -> None:
        """顯示建立伺服器頁面
        Show create server page

        Args:
            None

        """
        self.hide_all_frames()
        try:
            self.create_server_frame.grid(row=0, column=0, sticky="nsew")
            self.create_server_frame.tkraise()
        except Exception:
            self.create_server_frame.pack(fill="both", expand=True)
        self.set_active_nav_button("建立伺服器")

    def show_manage_server(self, auto_select=None) -> None:
        """顯示管理伺服器頁面
        每次都強制刷新伺服器列表
        Show manage server page
        Force refresh server list each time

        Args:
            auto_select: 跳轉後自動選擇的伺服器名稱（可選）

        """
        self.hide_all_frames()
        self._ensure_manage_server_frame()
        try:
            self.manage_server_frame.grid(row=0, column=0, sticky="nsew")
            self.manage_server_frame.tkraise()
        except Exception:
            self.manage_server_frame.pack(fill="both", expand=True)
        self.set_active_nav_button("管理伺服器")

        # 讓 UI 先完成一輪繪製再做重刷新，降低切換頁面時的卡頓/撕裂。
        # 參考 tkinter after(): https://docs.python.org/3/library/tkinter.html#universal-widget-methods
        def _refresh_and_optionally_select() -> None:
            try:
                self.manage_server_frame.refresh_servers()
                if (
                    auto_select
                    and hasattr(self.manage_server_frame, "server_tree")
                    and self.manage_server_frame.server_tree
                ):
                    for item in self.manage_server_frame.server_tree.get_children():
                        values = self.manage_server_frame.server_tree.item(item)["values"]
                        if values and values[0] == auto_select:
                            self.manage_server_frame.server_tree.selection_set(item)
                            self.manage_server_frame.server_tree.see(item)
                            self.manage_server_frame.selected_server = auto_select
                            self.manage_server_frame.update_selection()
                            break
            except Exception as e:
                logger.error(f"切換到管理伺服器頁面後刷新失敗: {e}\n{traceback.format_exc()}")

        # coalesce：快速連點切換時取消舊的 refresh job
        try:
            old_job = getattr(self, "_nav_refresh_job", None)
            if old_job:
                self.root.after_cancel(old_job)
        except Exception as e:
            logger.debug(f"取消 _nav_refresh_job 失敗: {e}", "MainWindow")
        self._nav_refresh_job = self.root.after(0, _refresh_and_optionally_select)

    def show_mod_management(self) -> None:
        """顯示模組管理頁面
        Show mod management page

        Args:
            None

        """
        self.hide_all_frames()
        self._ensure_mod_management_frame()
        # 每次顯示頁面時，重新載入伺服器列表並預設選擇第一個
        self.mod_frame.load_servers()
        frame = self.mod_frame.get_frame()
        try:
            frame.grid(row=0, column=0, sticky="nsew")
            frame.tkraise()
        except Exception:
            frame.pack(fill="both", expand=True)
        self.set_active_nav_button("模組管理")

    def import_server(self) -> None:
        """匯入伺服器（資料夾或壓縮檔）
        統一入口匯入伺服器，支援資料夾和壓縮檔
        Import server (folder or archive)
        Unified entry to import a server from folder or archive
        """
        # 建立選擇對話框
        dialog = ctk.CTkToplevel(self.root)
        dialog.withdraw()  # 先隱藏
        dialog.title("匯入伺服器")
        dialog.resizable(False, False)

        UIUtils.setup_window_properties(
            window=dialog,
            parent=self.root,
            width=450,
            height=280,
            bind_icon=True,
            center_on_parent=True,
            make_modal=True,
        )
        dialog.deiconify()  # 顯示

        choice = {"value": None}

        # 對話框內容
        content = ctk.CTkFrame(dialog)
        content.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(content, text="選擇匯入方式", font=FontManager.get_font(size=18, weight="bold")).pack(
            pady=(10, 15)
        )
        ctk.CTkLabel(content, text="請選擇要匯入的伺服器類型:", font=FontManager.get_font(size=14)).pack(pady=(0, 20))

        button_frame = ctk.CTkFrame(content, fg_color="transparent")
        button_frame.pack(fill="x", padx=20)

        # 建立按鈕
        options = [
            ("📁 匯入資料夾", "folder"),
            ("📦 匯入壓縮檔", "archive"),
            ("❌ 取消", "cancel"),
        ]
        for label, key in options:
            font_weight = "bold" if key != "cancel" else "normal"
            btn = ctk.CTkButton(
                button_frame,
                text=label,
                command=lambda k=key: self._set_choice(choice, k, dialog),
                font=FontManager.get_font(size=15, weight=font_weight),
                height=35,
            )
            btn.pack(fill="x", pady=5)

        dialog.bind("<Escape>", lambda _e: self._set_choice(choice, "cancel", dialog))
        dialog.wait_window()

        if choice["value"] in [None, "cancel"]:
            return

        # 處理選擇的匯入類型
        self._handle_import_choice(choice["value"])

    def _set_choice(self, choice_dict, value, dialog) -> None:
        """設定選擇並關閉對話框
        Set choice and close dialog

        Args:
            choice_dict: 儲存選擇的字典
            value: 選擇的值
            dialog: 對話框實例

        """
        choice_dict["value"] = value
        dialog.destroy()

    def _handle_import_choice(self, choice_type) -> None:
        """處理匯入選擇
        Handle import choice

        Args:
            choice_type: 選擇的匯入類型

        """
        try:
            if choice_type == "folder":
                path = self._select_server_folder()
            elif choice_type == "archive":
                path = self._select_server_archive()
            else:
                return

            if path:
                server_name = self._prompt_server_name(path.stem if path.is_file() else path.name)
                if server_name:
                    self._finalize_import(path, server_name)
        except Exception as e:
            logger.error(f"匯入錯誤: {e}\n{traceback.format_exc()}", "MainWindow")
            UIUtils.show_error("匯入錯誤", str(e), self.root)

    def _select_server_folder(self) -> Path | None:
        """選擇伺服器資料夾
        Select server folder
        """
        folder_path = filedialog.askdirectory(title="選擇伺服器資料夾")
        if not folder_path:
            return None
        path = Path(folder_path)
        if not ServerDetectionUtils.is_valid_server_folder(path):
            UIUtils.show_error(
                "無效資料夾",
                "選擇的資料夾不是有效的 Minecraft 伺服器資料夾。",
                self.root,
            )
            return None
        return path

    def _select_server_archive(self) -> Path | None:
        """選擇伺服器壓縮檔
        Select server archive
        """
        file_path = filedialog.askopenfilename(
            title="選擇伺服器壓縮檔",
            filetypes=[("ZIP 壓縮檔", "*.zip"), ("所有檔案", "*.*")],
        )
        if not file_path:
            return None
        path = Path(file_path)
        if path.suffix.lower() != ".zip":
            UIUtils.show_error(
                "不支援的格式",
                f"目前僅支援 ZIP 格式。\n選擇的檔案: {path.suffix}",
                self.root,
            )
            return None
        return path

    def _prompt_server_name(self, default_name: str) -> str | None:
        """提示輸入伺服器名稱
        Prompt for server name input

        Args:
            default_name: 預設名稱

        Returns:
            str: 使用者輸入的名稱

        """
        dialog = ctk.CTkToplevel(self.root)
        dialog.withdraw()  # 先隱藏
        dialog.title("輸入伺服器名稱")
        dialog.resizable(False, False)

        UIUtils.setup_window_properties(
            window=dialog,
            parent=self.root,
            width=400,
            height=200,
            bind_icon=True,
            center_on_parent=True,
            make_modal=True,
        )
        dialog.deiconify()  # 顯示

        result = {"name": None}

        frame = ctk.CTkFrame(dialog)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(frame, text="請輸入伺服器名稱:", font=FontManager.get_font(size=14)).pack(pady=(10, 15))

        entry = ctk.CTkEntry(frame, font=FontManager.get_font(size=14), width=300)
        entry.pack(pady=(0, 20))
        entry.insert(0, default_name)
        entry.focus()
        entry.select_range(0, tk.END)

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack()

        def _ok():
            name = entry.get().strip()
            if not name:
                UIUtils.show_error("輸入錯誤", "請輸入伺服器名稱", dialog)
                return
            root = self.server_manager.servers_root
            if (root / name).exists():
                UIUtils.show_error("名稱重複", f"'{name}' 已存在，請換一個名稱", dialog)
                return
            if self.server_manager.server_exists(name) and not UIUtils.ask_yes_no_cancel(
                "名稱衝突",
                f"'{name}' 已存在於設定，是否覆蓋?",
                dialog,
                show_cancel=False,
            ):
                return
            result["name"] = name
            dialog.destroy()

        def _cancel():
            dialog.destroy()

        ctk.CTkButton(btn_frame, text="確定", command=_ok, width=80, height=35).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_frame, text="取消", command=_cancel, width=80, height=35).pack(side="left")

        entry.bind("<Return>", lambda _e: _ok())
        dialog.bind("<Escape>", lambda _e: _cancel())
        dialog.wait_window()
        return result["name"]

    def _finalize_import(self, source_path: Path, server_name: str) -> None:
        """完成伺服器匯入流程
        Complete server import process

        Args:
            source_path: 來源路徑
            server_name: 伺服器名稱

        """
        target_path = self.server_manager.servers_root / server_name

        try:
            if source_path.is_file():
                target_path.mkdir(parents=True, exist_ok=True)
                PathUtils.safe_extract_zip(source_path, target_path)
                items = list(target_path.iterdir())
                if len(items) == 1 and items[0].is_dir():
                    for item in items[0].iterdir():
                        PathUtils.move_path(item, target_path / item.name)
                    items[0].rmdir()
            else:
                PathUtils.copy_dir(source_path, target_path)

            if not ServerDetectionUtils.is_valid_server_folder(target_path):
                raise Exception("找不到有效的 Minecraft 伺服器檔案")

            server_config = ServerConfig(
                name=server_name,
                minecraft_version="unknown",
                loader_type="unknown",
                loader_version="unknown",
                memory_max_mb=2048,
                path=str(target_path),
                eula_accepted=False,
            )
            ServerDetectionUtils.detect_server_type(target_path, server_config)
            self.server_manager.add_server(server_config)

            UIUtils.show_info(
                "匯入成功",
                f"伺服器 '{server_name}' 匯入成功!\n\n類型: {server_config.loader_type}\n版本: {server_config.minecraft_version}",
                self.root,
            )
            # 跳轉到管理伺服器頁面並自動選擇剛匯入的伺服器
            self.show_manage_server(auto_select=server_name)

        except Exception as e:
            logger.error(f"匯入失敗: {e}\n{traceback.format_exc()}", "MainWindow")
            UIUtils.show_error("匯入失敗", f"伺服器 '{server_name}' 匯入失敗: {e}", self.root)
            raise e

    def hide_all_frames(self) -> None:
        """隱藏所有頁面
        Hide all content frames except the sidebar.
        """
        try:
            self.create_server_frame.grid_remove()
        except Exception:
            try:
                self.create_server_frame.pack_forget()
            except Exception as e:
                logger.debug(f"隱藏 create_server_frame 失敗: {e}", "MainWindow")

        if getattr(self, "manage_server_frame", None) is not None:
            try:
                self.manage_server_frame.grid_remove()
            except Exception:
                try:
                    self.manage_server_frame.pack_forget()
                except Exception as e:
                    logger.debug(f"隱藏 manage_server_frame 失敗: {e}", "MainWindow")

        # 隱藏模組管理頁面
        if getattr(self, "mod_frame", None) is not None:
            try:
                frame = self.mod_frame.get_frame()
                try:
                    frame.grid_remove()
                except Exception:
                    frame.pack_forget()
            except Exception as e:
                logger.debug(f"隱藏 mod_frame 失敗: {e}", "MainWindow")

    def open_servers_folder(self) -> None:
        """開啟伺服器資料夾
        Open servers folder
        """
        folder = self.servers_root  # 直接使用目前已載入的 servers_root
        folder_path = Path(folder)
        if not folder_path.exists():
            folder_path.mkdir(parents=True, exist_ok=True)

        try:
            UIUtils.open_external(str(folder_path))
        except Exception as e:
            logger.error(f"無法開啟路徑: {e}\n{traceback.format_exc()}", "MainWindow")
            UIUtils.show_error("錯誤", f"無法開啟路徑: {e}", self.root)

    def show_about(self) -> None:
        """顯示關於對話框
        Show the about dialog with application information.
        """
        about_dialog = ctk.CTkToplevel(self.root)
        about_dialog.withdraw()  # 先隱藏
        about_dialog.title("關於 Minecraft 伺服器管理器")
        about_dialog.resizable(True, True)

        # 設定視窗屬性
        UIUtils.setup_window_properties(
            window=about_dialog,
            parent=self.root,
            width=600,
            height=650,
            bind_icon=True,
            center_on_parent=True,
            make_modal=True,
        )
        about_dialog.deiconify()  # 顯示

        # 創建滾動框架
        scrollable_frame = ctk.CTkScrollableFrame(about_dialog)
        scrollable_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 標題
        ctk.CTkLabel(
            scrollable_frame,
            text="🎮 Minecraft 伺服器管理器",
            font=FontManager.get_font(size=27, weight="bold"),
        ).pack(pady=(0, 5))

        ctk.CTkLabel(
            scrollable_frame,
            text=f"版本 {APP_VERSION}",
            font=FontManager.get_font(size=18),
            text_color=("#a0aec0", "#a0aec0"),
        ).pack(pady=(0, 20))

        # 開發資訊
        ctk.CTkLabel(
            scrollable_frame,
            text="👨‍💻 開發資訊",
            font=FontManager.get_font(size=21, weight="bold"),
        ).pack(anchor="w", pady=(0, 10))

        dev_info = """• 開發者: Minecraft Server Manager Team
• 技術棧: Python 3.7+, tkinter, coustomtkinter
• Java 管理：自動偵測/下載 Minecraft官方 JDK，完全自動化
• 架構: 模組化設計, 事件驅動
• 參考專案: PrismLauncher、MinecraftModChecker"""

        ctk.CTkLabel(
            scrollable_frame,
            text=dev_info,
            font=FontManager.get_font(size=15),
            justify="left",
            wraplength=500,
        ).pack(anchor="w", pady=(0, 5))
        github_url = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
        github_lbl = ctk.CTkLabel(
            scrollable_frame,
            text="GitHub-MinecraftServerManager",
            font=("微軟正黑體", 14, "underline"),
            text_color="black",
            cursor="hand2",
            anchor="w",
        )
        github_lbl.pack(anchor="w", pady=(0, 20))
        github_lbl.bind("<Button-1>", lambda _e, url=github_url: UIUtils.open_external(url))

        # 授權條款
        ctk.CTkLabel(scrollable_frame, text="📄 授權條款", font=FontManager.get_font(size=24, weight="bold")).pack(
            anchor="w",
            pady=(0, 10),
        )

        license_info = """• 本專案採用 GNU General Public License v3.0 授權條款
• 部分設計理念參考 PrismLauncher、MinecraftModChecker
• 僅供學習和個人使用
• 請遵守 Minecraft EULA 和當地法律法規

特別感謝 PrismLauncher 與 MinecraftModChecker 開發團隊的開源貢獻！"""

        ctk.CTkLabel(
            scrollable_frame,
            text=license_info,
            font=FontManager.get_font(size=15),
            justify="left",
            wraplength=500,
        ).pack(anchor="w", pady=(0, 30))

        # 建立通用的設定區塊
        settings_frame = ctk.CTkFrame(scrollable_frame, fg_color="transparent")
        settings_frame.pack(fill="x", pady=(0, 20))

        settings = get_settings_manager()

        # 顯示更新設定
        ctk.CTkLabel(settings_frame, text="🔄 更新設定", font=FontManager.get_font(size=24, weight="bold")).pack(
            anchor="w",
            pady=(0, 10),
        )

        # 自動更新複選框
        auto_update_var = ctk.BooleanVar(value=settings.is_auto_update_enabled())
        auto_update_checkbox = ctk.CTkCheckBox(
            settings_frame,
            text="自動檢查更新",
            variable=auto_update_var,
            font=FontManager.get_font(size=15),
            command=lambda: self._on_auto_update_changed(auto_update_var.get(), manual_check_btn),
        )
        auto_update_checkbox.pack(anchor="w", pady=(0, 10))

        # 手動檢查更新按鈕
        manual_check_btn: ctk.CTkButton | None = None
        manual_check_btn = ctk.CTkButton(
            settings_frame,
            text="檢查更新",
            command=self._manual_check_updates,
            font=FontManager.get_font(size=12),
            width=120,
            height=30,
        )

        if not settings.is_auto_update_enabled():
            manual_check_btn.pack(anchor="w", pady=(0, 10))

        # 若為可攜式，額外顯示便攜提示（但不隱藏更新設定）
        if RuntimePaths.is_portable_mode():
            ctk.CTkLabel(settings_frame, text="📦 便攜模式", font=FontManager.get_font(size=24, weight="bold")).pack(
                anchor="w", pady=(12, 10)
            )

            portable_info_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
            portable_info_frame.pack(fill="x", pady=(0, 10))

            ctk.CTkLabel(
                portable_info_frame,
                text="您正在使用便攜版本。\n如需更新，請從 Releases 下載新版 portable ZIP，或使用內建的檢查更新功能。",
                font=FontManager.get_font(size=15),
                justify="left",
            ).pack(anchor="w")

        # 視窗偏好設定按鈕
        window_prefs_btn = ctk.CTkButton(
            settings_frame,
            text="視窗偏好設定",
            command=self._show_window_preferences,
            font=FontManager.get_font(size=12),
            width=120,
            height=30,
        )
        window_prefs_btn.pack(anchor="w", pady=(0, 10))

        # 關閉按鈕
        ctk.CTkButton(
            scrollable_frame,
            text="關閉",
            command=about_dialog.destroy,
            font=FontManager.get_font(size=12, weight="bold"),
            width=100,
            height=35,
        ).pack(pady=(10, 0))

        # Escape 鍵關閉
        about_dialog.bind("<Escape>", lambda _e: about_dialog.destroy())

    def _on_auto_update_changed(self, enabled: bool, manual_check_btn) -> None:
        """自動更新設定變更時的回調
        Callback when auto-update setting is changed.

        Args:
            enabled: 是否啟用自動更新
            manual_check_btn: 手動檢查按鈕

        """
        settings = get_settings_manager()
        settings.set_auto_update_enabled(enabled)

        # 根據設定顯示或隱藏手動檢查按鈕
        if enabled:
            manual_check_btn.pack_forget()
        else:
            manual_check_btn.pack(anchor="w", pady=(0, 10))

    def _manual_check_updates(self) -> None:
        """手動檢查更新
        Manually check for updates.
        """
        self._check_for_updates()

    def _show_window_preferences(self) -> None:
        """顯示視窗偏好設定對話框
        Show window preferences dialog.
        """

        def on_settings_changed():
            """設定變更回調"""
            # 可以在這裡添加設定變更後的處理邏輯
            logger.debug("視窗偏好設定已變更", "MainWindow")

        # 顯示視窗偏好設定對話框
        WindowPreferencesDialog(self.root, on_settings_changed)

    def on_server_created(self, server_config: ServerConfig) -> None:
        """伺服器建立完成的回調
        Callback for server creation completion.

        Args:
            server_config: 伺服器設定
            server_path: 伺服器根目錄

        """
        # 首次啟動伺服器進行初始化
        self.initialize_server(server_config)

    def initialize_server(self, server_config: ServerConfig) -> None:
        """初始化新建立的伺服器
        Initialize the newly created server.

        Args:
            server_path: 伺服器根目錄

        """
        dialog = ServerInitializationDialog(self.root, server_config, self.complete_initialization)
        dialog.start_initialization()

    def on_server_selected(self, server_name: str) -> None:
        """伺服器被選中的回調
        Server selection callback.

        當使用者在管理伺服器或模組管理頁面選擇伺服器時，此方法會被呼叫。
        This method is called when the user selects a server in the manage server or mod management pages.

        Args:
            server_name: 選中的伺服器名稱

        """
        # 目前僅作為記錄用途，未來可擴展為狀態同步等功能
        # Currently used only for logging, can be extended for state synchronization in the future
        logger.info(f"選中伺服器: {server_name}")

    def complete_initialization(self, server_config: ServerConfig, init_dialog) -> None:
        """完成初始化流程
        Complete the initialization process.

        Args:
            server_config: 伺服器設定
            init_dialog: 初始化對話框

        """
        # 關閉初始化對話框
        init_dialog.destroy()

        # 取得剛建立伺服器的根目錄
        server_path = Path(server_config.path)
        properties_file = server_path / "server.properties"

        # 讀取 server.properties 並匯入到 server_config（不自動彈出設定視窗）
        try:
            if properties_file.exists():
                properties = ServerPropertiesHelper.load_properties(properties_file)
                server_config.properties = properties
        except Exception as e:
            logger.error(f"初始化後讀取 server.properties 失敗: {e}\n{traceback.format_exc()}")

        # 直接提示初始化完成，並自動跳轉到管理伺服器頁面
        self.show_manage_server(auto_select=server_config.name)

        UIUtils.show_info(
            "初始化完成",
            f"伺服器 「{server_config.name}」 已成功初始化並可開始使用！\n\n你現在可以進一步調整伺服器設定或直接啟動",
            self.root,
        )


class ServerInitializationDialog:
    """伺服器初始化對話框
    Server initialization dialog class.
    """

    def __init__(self, parent: tk.Tk, server_config: ServerConfig, completion_callback=None):
        self.parent = parent
        self.server_config = server_config
        self.server_path = Path(server_config.path)
        self.completion_callback = completion_callback

        # 狀態變數
        self.server_process: Any | None = None
        self.done_detected = False

        # UI 元件
        self.init_dialog: ctk.CTkToplevel | None = None
        self.console_text: ctk.CTkTextbox | None = None
        self.progress_label: ctk.CTkLabel | None = None
        self.close_button: ctk.CTkButton | None = None

        # 控制台輸出批次刷新（避免每行都觸發一次 UI 更新造成撕裂）
        self._console_queue: queue.Queue[str] = queue.Queue()
        self._console_pump_job = None

    def _enqueue_console(self, text: str) -> None:
        try:
            self._console_queue.put_nowait(text)
        except Exception as e:
            get_logger().bind(component="InitServerDialog").exception(f"加入 console queue 失敗: {e}")

    def _start_console_pump(self) -> None:
        if self._console_pump_job is not None:
            return

        def _tick() -> None:
            self._console_pump_job = None
            try:
                if not self.init_dialog or not self.init_dialog.winfo_exists():
                    return
            except Exception:
                return

            chunks = []
            remaining_chars = 20000
            for _ in range(200):
                try:
                    part = self._console_queue.get_nowait()
                except queue.Empty:
                    break
                chunks.append(part)
                remaining_chars -= len(part)
                if remaining_chars <= 0:
                    break

            if chunks:
                self._update_console("".join(chunks))

            delay = 25 if not self._console_queue.empty() else 100
            try:
                if self.init_dialog:
                    self._console_pump_job = self.init_dialog.after(delay, _tick)
            except tk.TclError:
                return

        if self.init_dialog:
            self._console_pump_job = self.init_dialog.after(50, _tick)

    def start_initialization(self) -> None:
        """開始初始化流程"""
        self._create_dialog()
        self._setup_ui()
        self._start_server_thread()

    def _create_dialog(self) -> None:
        """建立初始化對話框"""
        self.init_dialog = UIUtils.create_toplevel_dialog(
            self.parent,
            f"初始化伺服器 - {self.server_config.name}",
            width=800,
            height=600,
            delay_ms=250,  # 使用稍長延遲確保圖示綁定成功
        )

    def _setup_ui(self) -> None:
        """設定使用者介面"""
        self._create_title_and_info()
        self._create_console()
        self._create_progress_label()
        self._create_buttons()
        self._setup_timeout()

    def _create_title_and_info(self) -> None:
        """建立標題和說明文字"""
        # 標題
        title_label = ctk.CTkLabel(
            self.init_dialog,
            text=f"正在初始化伺服器: {self.server_config.name}",
            font=FontManager.get_font(size=24, weight="bold"),
        )
        title_label.pack(pady=10)

        # 說明文字
        info_label = ctk.CTkLabel(
            self.init_dialog,
            text="伺服器正在首次啟動，請等待初始化完成...\n系統會自動在完成後關閉伺服器",
            font=FontManager.get_font(size=18),
        )
        info_label.pack(pady=5)

    def _create_console(self) -> None:
        """建立控制台輸出區域"""
        # 控制台輸出區域
        console_frame = ctk.CTkFrame(self.init_dialog)
        console_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # 滾動文字區域
        self.console_text = ctk.CTkTextbox(
            console_frame,
            font=FontManager.get_font(family="Consolas", size=10),
            wrap="none",
            fg_color=("#000000", "#000000"),
            text_color=("#00ff00", "#00ff00"),
        )
        self.console_text.pack(fill="both", expand=True, padx=5, pady=5)
        self._start_console_pump()

    def _create_progress_label(self) -> None:
        """建立進度標籤"""
        if not self.init_dialog:
            return
        self.progress_label = ctk.CTkLabel(
            self.init_dialog,
            text="狀態: 準備啟動...",
            font=FontManager.get_font(size=16, weight="bold"),
        )
        self.progress_label.pack(pady=5)

    def _create_buttons(self) -> None:
        """建立按鈕區域"""
        if not self.init_dialog:
            return
        # 按鈕區域
        button_frame = ctk.CTkFrame(self.init_dialog, fg_color="transparent")
        button_frame.pack(pady=10)

        self.close_button = ctk.CTkButton(
            button_frame,
            text="取消初始化",
            command=self._close_init_server,
            font=FontManager.get_font(size=14),
            width=120,
            height=35,
            fg_color=("#e53e3e", "#e53e3e"),
            hover_color=("#dc2626", "#dc2626"),
            border_width=2,
            border_color=("#b91c1c", "#b91c1c"),
            corner_radius=6,
        )
        self.close_button.pack(side="right", padx=5)

    def _setup_timeout(self) -> None:
        """設定超時自動關閉"""
        # 2分鐘超時自動強制關閉
        if self.init_dialog:
            self.init_dialog.after(120000, self._timeout_force_close)

    def _start_server_thread(self) -> None:
        """在背景執行緒中啟動伺服器"""
        UIUtils.run_async(self._run_server)

    def _close_init_server(self) -> None:
        """關閉初始化伺服器"""
        if self.done_detected:
            # 正常關閉
            if self.init_dialog and self.init_dialog.winfo_exists():
                UIUtils.show_info("初始化完成", "伺服器已成功初始化並安全關閉。", parent=self.parent)
                self.init_dialog.destroy()
        else:
            # 強制關閉
            self._terminate_server_process()
            if self.init_dialog and self.init_dialog.winfo_exists():
                UIUtils.show_warning(
                    "強制關閉",
                    "伺服器初始化未完成，已強制關閉。請檢查伺服器日誌。",
                    self.parent,
                )
                self.init_dialog.destroy()

    def _terminate_server_process(self) -> None:
        """終止伺服器程式"""
        try:
            if self.server_process and self.server_process.poll() is None:
                self.server_process.terminate()
                try:
                    self.server_process.wait(timeout=5)
                except Exception as e:
                    logger.exception(f"等待程式終止逾時/失敗，改用 kill: {e}")
                    self.server_process.kill()
        except Exception as e:
            get_logger().bind(component="InitServerDialog").exception(f"終止伺服器程式失敗: {e}")

    def _timeout_force_close(self) -> None:
        """超時強制關閉"""
        if self.init_dialog and self.init_dialog.winfo_exists() and not self.done_detected:
            self._close_init_server()

    def _update_console(self, text: str) -> None:
        """更新控制台輸出
        Update the console output.
        """
        try:
            if self.init_dialog and self.init_dialog.winfo_exists() and self.console_text:
                self.console_text.insert("end", text)
                # 自動滾動到最新一行
                self.console_text.see("end")
        except tk.TclError:
            # 對話框已被關閉，忽略此操作
            pass

    def _run_server(self) -> None:
        """在背景執行緒中啟動伺服器
        Start the server in a background thread.
        """
        try:
            # 更新狀態
            if self.init_dialog:
                self.init_dialog.after(
                    0,
                    lambda: (
                        self.progress_label.configure(text="狀態: 正在啟動伺服器...")
                        if self.progress_label and self.progress_label.winfo_exists()
                        else None
                    ),
                )
            self._enqueue_console("正在啟動 Minecraft 伺服器...\n")

            java_cmd = self._build_java_command()

            # 啟動伺服器程式
            self.server_process = SubprocessUtils.popen_checked(
                java_cmd,
                cwd=str(self.server_path),
                stdout=SubprocessUtils.PIPE,
                stderr=SubprocessUtils.STDOUT,
                stdin=SubprocessUtils.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
                creationflags=SubprocessUtils.CREATE_NO_WINDOW,
            )

            self._monitor_server_output()
            self._handle_server_completion()

        except Exception as e:
            get_logger().bind(component="ServerInitializationDialog").error(
                f"伺服器啟動失敗: {e}\n{traceback.format_exc()}",
            )
            self._handle_server_error(str(e))

    def _build_java_command(self) -> list[str]:
        """建立 Java 命令"""
        loader_type = str(self.server_config.loader_type or "").lower()

        # --- Forge 專用初始化 ---
        if loader_type == "forge":
            return self._build_forge_command()
        # 其他類型
        java_cmd = ServerCommands.build_java_command(self.server_config, return_list=True)
        self._enqueue_console(f"執行命令: {' '.join(java_cmd)}\n\n")
        return java_cmd

    def _build_forge_command(self) -> list[str]:
        """建立 Forge 伺服器命令"""
        # 強制覆蓋 Forge 的 user_jvm_args.txt
        user_args = Path(self.server_path) / "user_jvm_args.txt"
        if user_args.exists():
            ServerDetectionUtils.update_forge_user_jvm_args(self.server_path, self.server_config)

        # 檢查並選擇啟動腳本
        start_bat = Path(self.server_path) / "start_server.bat"
        java_cmd = None

        if user_args.exists() and start_bat.exists():
            java_cmd = self._extract_java_command_from_bat(start_bat)

        # fallback: 用 build_java_command()
        if not java_cmd:
            java_cmd = ServerCommands.build_java_command(self.server_config, return_list=True)
            self._enqueue_console(f"執行命令: {' '.join(java_cmd)}\n\n")

        return java_cmd

    def _extract_java_command_from_bat(self, start_bat: Path) -> list[str] | None:
        """從 bat 檔案提取 Java 命令"""
        try:
            content = PathUtils.read_text_file(start_bat, errors="ignore")
            if content:
                for line in content.splitlines():
                    if re.search(r"\bjava\b.*@user_jvm_args\.txt\b", line, re.IGNORECASE):
                        # 去除尾端的 %* 或其他 shell 變數符號
                        cleaned = re.sub(r"\s*[%$]\*?$", "", line.strip())
                        java_cmd = cleaned.split()
                        get_logger().bind(component="ServerInitializationDialog").debug(
                            f"forge_java_command: {java_cmd}",
                        )
                        return java_cmd
        except Exception as e:
            logger.exception(f"提取 Java 命令失敗: {e}")
        return None

    def _monitor_server_output(self) -> None:
        """監控伺服器輸出
        Monitor server output.
        """
        if self.server_process is None or self.server_process.stdout is None:
            return

        while True:
            output = self.server_process.stdout.readline()
            if output == "" and self.server_process.poll() is not None:
                break
            if output:
                self._enqueue_console(output)
                self._process_server_output(output)

                if self.done_detected:
                    self._handle_server_ready(output)
                    break

        # 等待程式結束
        if self.server_process is not None:
            self.server_process.wait()

    def _process_server_output(self, output: str) -> None:
        """處理伺服器輸出
        Handle server output.

        Args:
            output (str): 伺服器輸出

        """
        if self.init_dialog is None or not self.init_dialog.winfo_exists():
            return

        if "Loading dimension" in output or "Preparing spawn area" in output:
            with contextlib.suppress(tk.TclError):
                self.init_dialog.after(
                    0,
                    lambda: (
                        self.progress_label.configure(text="狀態: 準備世界...")
                        if self.progress_label and self.progress_label.winfo_exists()
                        else None
                    ),
                )
        elif "Preparing level" in output:
            with contextlib.suppress(tk.TclError):
                self.init_dialog.after(
                    0,
                    lambda: (
                        self.progress_label.configure(text="狀態: 載入世界...")
                        if self.progress_label and self.progress_label.winfo_exists()
                        else None
                    ),
                )
        # 檢查是否載入完成 - 更精確的條件
        elif "Done (" in output and 'For help, type "help"' in output and not self.done_detected:
            self.done_detected = True
            # 修改按鈕為"關閉伺服器"並切換行為
            if self.close_button and self.close_button.winfo_exists():
                self.close_button.configure(
                    text="關閉伺服器",
                    command=self._close_init_server,
                    fg_color="#059669",
                )

    def _handle_server_ready(self, output: str) -> None:
        """處理伺服器就緒狀態
        Handle server ready status.
        """
        if "ERROR" in output.upper() or "WARN" in output.upper():
            self._enqueue_console(f"[注意] {output}")

        def update_closing_status():
            if (
                self.init_dialog
                and self.init_dialog.winfo_exists()
                and self.progress_label
                and self.progress_label.winfo_exists()
            ):
                self.progress_label.configure(text="狀態: 伺服器完全啟動，正在關閉...")
                self._enqueue_console("\n[系統] 所有模組載入完成，正在關閉伺服器...\n")

        if self.init_dialog:
            self.init_dialog.after(0, update_closing_status)

        # 發送 stop 命令
        if self.server_process and self.server_process.stdin:
            self.server_process.stdin.write("stop\n")
            self.server_process.stdin.flush()

    def _handle_server_completion(self) -> None:
        """處理伺服器完成狀態
        Handle server completion status.
        """
        if self.init_dialog is None:
            return

        if self.done_detected:

            def complete_init():
                if self.init_dialog and self.init_dialog.winfo_exists():
                    self._update_console("[系統] 伺服器初始化完成！\n")
                    if self.progress_label and self.progress_label.winfo_exists():
                        self.progress_label.configure(text="狀態: 初始化完成")

            self.init_dialog.after(0, complete_init)

            # 延遲後自動進入設定頁面
            if self.completion_callback:
                self.init_dialog.after(
                    2000,
                    lambda: self.completion_callback(  # type: ignore
                        self.server_config,
                        self.init_dialog,
                    ),
                )
        else:

            def show_error():
                if self.init_dialog and self.init_dialog.winfo_exists():
                    self._update_console("[系統] 伺服器啟動可能有問題，請檢查輸出\n")
                    if self.progress_label and self.progress_label.winfo_exists():
                        self.progress_label.configure(text="狀態: 啟動異常")

            self.init_dialog.after(0, show_error)

    def _handle_server_error(self, err_msg: str) -> None:
        """處理伺服器錯誤
        Handle server errors.

        Args:
            err_msg (str): 錯誤訊息

        """
        if self.init_dialog is None:
            return

        def show_error():
            if self.init_dialog and self.init_dialog.winfo_exists():
                self._update_console(f"[錯誤] 啟動失敗: {err_msg}\n")
                if self.progress_label and self.progress_label.winfo_exists():
                    self.progress_label.configure(text="狀態: 啟動失敗")

        self.init_dialog.after(0, show_error)

    def run(self) -> None:
        """執行主程式，註冊關閉事件
        Run the main application and register the close event.
        """
        # Note: This method is part of MainWindow class, not ServerInitializationDialog
