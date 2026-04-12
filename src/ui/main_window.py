"""主視窗
Minecraft 伺服器管理器的主要使用者介面
本模組定義 Minecraft 伺服器管理器的主視窗。
"""

import contextlib
import queue
import re
import sys
import tkinter
import tkinter.filedialog as filedialog
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any
import customtkinter as ctk
from ..core import ConfigurationError, LoaderManager, MinecraftVersionManager, ServerManager
from ..models import ServerConfig
from ..utils import (
    Colors,
    FontSize,
    JavaUtils,
    PathUtils,
    RuntimePaths,
    ServerCommands,
    ServerDetectionUtils,
    ServerPropertiesHelper,
    Sizes,
    Spacing,
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
    DialogUtils,
    FontManager,
    ManageServerFrame,
    ModManagementFrame,
    TaskUtils,
    WindowPreferencesDialog,
)

logger = get_logger().bind(component="MainWindow")


class MinecraftServerManager:
    """Minecraft 伺服器管理器主視窗類別"""

    def set_servers_root(self, new_root: str | None = None) -> str:
        """取得或設定伺服器根目錄。

        Args:
            new_root: 要設定的新根目錄；未提供時會提示使用者選擇。

        Returns:
            解析後的伺服器根目錄字串。
        """
        settings = get_settings_manager()

        def _fail_exit(msg: str):
            """錯誤退出處理"""
            UIUtils.show_error("錯誤", msg, self.root)
            self.root.destroy()
            exit(0)

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
                    "結束程式", "未選擇資料夾，是否要結束程式？", self.root, show_cancel=False
                ):
                    self.root.destroy()
                    exit(0)
                return ""
            return str(Path(folder))

        if new_root:
            try:
                settings.set_servers_root(new_root)
                path_obj = settings.get_validated_servers_root_path(create=True)
            except Exception as e:
                logger.error(f"無法寫入設定: {e}\n{traceback.format_exc()}")
                UIUtils.show_error("設定錯誤", f"無法寫入設定: {e}", self.root)
                return ""
        else:
            stored = settings.get_servers_root()
            if stored:
                try:
                    path_obj = settings.get_validated_servers_root_path(create=True)
                except ConfigurationError as exc:
                    _fail_exit(str(exc))
                    return ""
            else:
                while True:
                    base_dir = _prompt_for_directory()
                    if not base_dir:
                        continue
                    try:
                        settings.set_servers_root(base_dir)
                        path_obj = settings.get_validated_servers_root_path(create=True)
                        break
                    except Exception as e:
                        logger.error(f"無法寫入設定: {e}\n{traceback.format_exc()}")
                        UIUtils.show_error("設定錯誤", f"無法寫入設定: {e}", self.root)
        self.servers_root = str(path_obj)
        return self.servers_root

    def on_closing(self) -> None:
        """主視窗關閉處理，清理快取並儲存視窗狀態"""
        logger.debug("程式即將關閉！", "MainWindow")
        try:
            get_logger().bind(component="WindowState").debug("儲存視窗狀態...")
            WindowManager.save_main_window_state(self.root)
            logger.debug("清理字體快取...", "MainWindow")
            FontManager.cleanup_fonts()
            if getattr(self, "server_manager", None) is not None:
                self.server_manager.write_servers_config()
            for widget in self.root.winfo_children():
                try:
                    if isinstance(widget, (tkinter.Toplevel, ctk.CTkToplevel)):
                        widget.destroy()
                except Exception as e:
                    logger.error(f"清理子視窗時發生錯誤: {e}\n{traceback.format_exc()}")
        except Exception as e:
            logger.error(f"清理資源時發生錯誤: {e}\n{traceback.format_exc()}")
        finally:
            try:
                self.root.destroy()
            except Exception as e:
                logger.error(f"銷毀主視窗時發生錯誤: {e}\n{traceback.format_exc()}")
                sys.exit(0)

    def __init__(self, root: tkinter.Tk):
        self.root = root
        self.mini_sidebar: Any | None = None
        self.active_nav_title: str | None = None
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self._sidebar_toggle_job = None
        self._sidebar_unlock_job = None
        self._sidebar_layout_unlock_delay_ms = 70
        self._content_layout_locked = False
        self._console_queue: queue.Queue[Any] = queue.Queue()
        self._startup_update_check_job = None
        self.ui_queue: queue.Queue[Callable[[], Any]] = queue.Queue()
        TaskUtils.start_ui_queue_pump(self.root, self.ui_queue)
        self.settings = get_settings_manager()
        self.setup_window()
        self.servers_root = self.set_servers_root()
        self.version_manager = MinecraftVersionManager()
        self.loader_manager = LoaderManager()
        self.server_manager = ServerManager(servers_root=self.servers_root)
        self.create_widgets()
        WindowManager.setup_main_window(self.root)
        WindowManager.bind_window_state_tracking(self.root)
        if self.settings.is_remember_size_position_enabled() and self.settings.get_main_window_settings().get(
            "maximized", False
        ):
            UIUtils.schedule_debounce(
                self.root, "_post_reveal_zoom_job", 160, lambda: DialogUtils.maximize_window(self.root), owner=self
            )
        self.preload_java_candidates()
        UIUtils.schedule_debounce(self.root, "_startup_tasks_job", 1000, self._handle_startup_tasks, owner=self)
        self.preload_all_versions()
        self.load_data_async()

    def _ensure_manage_server_frame(self) -> None:
        """確保管理伺服器頁面已建立並放置於內容堆疊層。"""
        if getattr(self, "manage_server_frame", None) is not None:
            return
        manage_server_frame = ManageServerFrame(
            self.content_frame,
            self.server_manager,
            self.on_server_selected,
            self.show_create_server,
            set_servers_root=self.set_servers_root,
        )
        self.manage_server_frame = manage_server_frame
        try:
            manage_server_frame.grid(row=0, column=0, sticky="nsew")
        except Exception as e:
            logger.debug(f"ManageServerFrame grid 設置失敗: {e}", "MainWindow")

    def _ensure_mod_management_frame(self) -> None:
        """確保模組管理頁面已建立並放置於內容堆疊層。"""
        if getattr(self, "mod_frame", None) is not None:
            return
        mod_frame = ModManagementFrame(
            self.content_frame, self.server_manager, self.on_server_selected, self.version_manager
        )
        self.mod_frame = mod_frame
        try:
            frame = mod_frame.get_frame()
            if frame is not None:
                frame.grid(row=0, column=0, sticky="nsew")
        except Exception as e:
            logger.debug(f"ModManagementFrame grid 設置失敗: {e}", "MainWindow")

    def preload_all_versions(self) -> None:
        """啟動時預先抓取版本資訊"""

        def fetch_loader_versions_only():
            logger.debug("預先抓取所有載入器版本...", "MainWindow")
            self.loader_manager.preload_loader_versions()
            logger.debug("所有載入器版本載入完成", "MainWindow")

        TaskUtils.run_async(fetch_loader_versions_only)

    def preload_java_candidates(self) -> None:
        """啟動時背景掃描本機 Java 並更新快取。"""

        def refresh_java_cache():
            logger.debug("預先掃描本機 Java 執行檔...", "MainWindow")
            JavaUtils.refresh_java_candidates_cache()
            logger.debug("本機 Java 快取更新完成", "MainWindow")

        TaskUtils.run_async(refresh_java_cache)

    def load_data_async(self) -> None:
        """非同步載入資料"""

        def load_versions():
            try:
                versions = self.version_manager.fetch_versions()
                self.ui_queue.put(lambda: self.create_server_frame.update_versions(versions))
            except Exception as e:
                error_msg = f"載入版本資訊失敗: {e}\n{traceback.format_exc()}"
                self.ui_queue.put(lambda: logger.error(error_msg))

        TaskUtils.run_async(load_versions)

    def _handle_startup_tasks(self) -> None:
        """處理啟動時的任務：首次執行提示和自動更新檢查"""
        settings = get_settings_manager()
        if not settings.is_first_run_completed():
            self._show_first_run_prompt()
        elif settings.is_auto_update_enabled():
            self._schedule_startup_update_check(delay_ms=600, show_msg=False)

    def _schedule_startup_update_check(self, *, delay_ms: int = 600, show_msg: bool = False) -> None:
        """延遲啟動更新檢查，避開 modal 對話框剛關閉時的 UI 卡頓。"""

        def _run_update_check() -> None:
            if not getattr(self, "root", None):
                return
            if not self.root.winfo_exists():
                return
            self._check_for_updates(show_msg=show_msg)

        UIUtils.schedule_debounce(
            self.root, "_startup_update_check_job", max(0, int(delay_ms)), _run_update_check, owner=self
        )

    def _show_first_run_prompt(self) -> None:
        """顯示首次執行的自動更新設定提示"""
        settings = get_settings_manager()
        with contextlib.suppress(Exception):
            stale_grab_widget = self.root.grab_current()
            if stale_grab_widget is not None:
                stale_grab_widget.grab_release()
        choice = UIUtils.ask_yes_no_cancel(
            title="歡迎使用 Minecraft 伺服器管理器",
            message="是否要啟用自動檢查更新功能？\n\n啟用後，程式會在啟動時自動檢查新版本。\n您可以隨時在「關於」視窗中更改此設定。",
            parent=self.root,
            show_cancel=False,
            topmost=False,
        )
        logger.info(f"首次啟動設定對話結果: enable_auto_update={bool(choice)}", "MainWindow")
        enable_auto_update = bool(choice)
        settings.set_auto_update_enabled(enable_auto_update)
        settings.mark_first_run_completed()
        with contextlib.suppress(Exception):
            self.root.focus_set()
        if enable_auto_update:
            self._schedule_startup_update_check(delay_ms=900, show_msg=False)

    def _check_for_updates(self, show_msg: bool = True) -> None:
        """檢查更新"""
        try:
            UpdateChecker.check_and_prompt_update(
                APP_VERSION, GITHUB_OWNER, GITHUB_REPO, show_up_to_date_message=show_msg, parent=self.root
            )
        except Exception as e:
            logger.error(f"自動更新檢查失敗: {e}\n{traceback.format_exc()}")
            if show_msg:
                UIUtils.show_error("更新檢查失敗", f"無法檢查更新：{e}", self.root)

    def setup_window(self) -> None:
        """設定主視窗標題、圖示和現代化樣式"""
        self.root.title("Minecraft 伺服器管理器")
        self.setup_light_theme()
        DialogUtils.setup_window_properties(
            window=self.root,
            parent=None,
            width=Sizes.DIALOG_LARGE_WIDTH,
            height=Sizes.DIALOG_LARGE_HEIGHT,
            bind_icon=True,
            center_on_parent=False,
            make_modal=False,
            delay_ms=300,
            reveal_after_setup=False,
        )

    def setup_light_theme(self) -> None:
        """設定淺色主題配置"""
        self.colors = {
            "primary": Colors.BUTTON_PRIMARY[0],
            "secondary": Colors.TEXT_SECONDARY[0],
            "success": Colors.BUTTON_SUCCESS[0],
            "warning": Colors.TEXT_WARNING[1],
            "danger": Colors.BUTTON_DANGER[0],
            "background": Colors.BG_PRIMARY[0],
            "surface": Colors.BG_LISTBOX_LIGHT,
            "text": Colors.TEXT_PRIMARY[0],
            "text_secondary": Colors.TEXT_SECONDARY[0],
            "border": Colors.DROPDOWN_BUTTON[0],
            "menu_bg": Colors.BG_PRIMARY,
        }

    def create_widgets(self) -> None:
        """建立所有介面元件，包含標題和主要內容"""
        self.create_header()
        self.create_main_content()
        self.show_create_server()

    def create_header(self) -> None:
        """建立現代化標題區域"""
        header_frame = ctk.CTkFrame(self.root, height=Sizes.APP_HEADER_HEIGHT, corner_radius=0)
        header_frame.pack(fill="x", padx=0, pady=0)
        header_frame.pack_propagate(False)
        header_content = ctk.CTkFrame(header_frame, fg_color="transparent")
        header_content.pack(fill="both", expand=True, padx=Spacing.XL, pady=Spacing.LARGE_MINUS)
        left_section = ctk.CTkFrame(header_content, fg_color="transparent")
        left_section.pack(side="left", fill="y", anchor="w")
        self.sidebar_toggle_btn = ctk.CTkButton(
            left_section,
            text="☰",
            font=FontManager.get_font(size=FontSize.LARGE),
            width=FontManager.get_dpi_scaled_size(40),
            height=FontManager.get_dpi_scaled_size(32),
            command=self.toggle_sidebar,
        )
        self.sidebar_toggle_btn.pack(side="left", padx=(0, Spacing.LARGE_MINUS))
        title_section = ctk.CTkFrame(left_section, fg_color="transparent")
        title_section.pack(side="left", fill="y")
        title_label = ctk.CTkLabel(
            title_section,
            text="Minecraft 伺服器管理器",
            font=FontManager.get_font(size=FontSize.HEADING_SMALL, weight="bold"),
        )
        title_label.pack(anchor="w")

    def create_main_content(self) -> None:
        """建立主內容區域"""
        main_container = ctk.CTkFrame(self.root, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=0, pady=0)
        self.main_container = main_container
        self._nav_full_width = 250
        self._nav_mini_width = FontManager.get_dpi_scaled_size(70)
        self._nav_column_padding = 40
        main_container.grid_rowconfigure(0, weight=1)
        main_container.grid_columnconfigure(0, weight=0, minsize=self._nav_full_width + self._nav_column_padding)
        main_container.grid_columnconfigure(1, weight=1)
        self.nav_container = ctk.CTkFrame(main_container, fg_color="transparent")
        self.nav_container.grid(row=0, column=0, sticky="nsew", padx=(Spacing.XL, Spacing.XL), pady=Spacing.XL)
        self.nav_container.grid_rowconfigure(0, weight=1)
        self.nav_container.grid_columnconfigure(0, weight=1)
        try:
            self.nav_container.grid_propagate(False)
            self.nav_container.configure(width=int(self._nav_full_width))
        except Exception as e:
            logger.debug(f"設定導航欄寬度失敗: {e}", "MainWindow")
        self.content_container = ctk.CTkFrame(main_container, fg_color="transparent")
        self.content_container.grid(row=0, column=1, sticky="nsew", padx=(0, Spacing.XL), pady=Spacing.XL)
        self.content_container.grid_rowconfigure(0, weight=1)
        self.content_container.grid_columnconfigure(0, weight=1)
        self.content_frame = ctk.CTkFrame(self.content_container)
        self.content_frame.grid(row=0, column=0, sticky="nsew")
        self.content_frame.grid_rowconfigure(0, weight=1)
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.create_sidebar(self.nav_container)
        self.create_mini_sidebar()
        try:
            self.sidebar.tkraise()
        except Exception as e:
            logger.debug(f"初始化側邊欄疊層失敗: {e}", "MainWindow")
        create_server_frame = CreateServerFrame(
            self.content_frame, self.version_manager, self.loader_manager, self.on_server_created, self.server_manager
        )
        self.create_server_frame = create_server_frame
        try:
            create_server_frame.grid(row=0, column=0, sticky="nsew")
        except Exception as e:
            logger.debug(f"CreateServerFrame grid 設置失敗: {e}", "MainWindow")
        self.manage_server_frame = None
        self.mod_frame = None

    def create_sidebar(self, parent) -> None:
        """建立現代化側邊欄。

        Args:
            parent: 父容器。
        """
        self.sidebar = ctk.CTkFrame(parent, width=self._nav_full_width, fg_color=self.colors["menu_bg"])
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar_visible = True
        sidebar_title = ctk.CTkLabel(
            self.sidebar,
            text="功能選單",
            font=FontManager.get_font(size=FontSize.INPUT, weight="bold"),
            text_color=Colors.TEXT_ON_LIGHT,
        )
        sidebar_title.pack(anchor="w", padx=Spacing.XL, pady=(Spacing.XL, Spacing.LARGE_MINUS))
        self.nav_scroll_frame = ctk.CTkScrollableFrame(self.sidebar, label_text="")
        self.nav_scroll_frame.pack(fill="both", expand=True, padx=Spacing.LARGE_MINUS, pady=(0, Spacing.LARGE_MINUS))
        self.nav_buttons = {}
        self.active_nav_key: str | None = None
        nav_items = [
            ("🆕", "建立伺服器", "建立新的 Minecraft 伺服器", self.show_create_server, "create"),
            ("🔧", "管理伺服器", "管理現有的伺服器", self.show_manage_server, "manage"),
            ("🧩", "模組管理", "管理伺服器模組與資源", self.show_mod_management, "mods"),
            ("📥", "匯入伺服器", "匯入現有伺服器檔案", self.import_server, "import"),
            ("📁", "開啟資料夾", "開啟伺服器儲存資料夾", self.open_servers_folder, "folder"),
            ("ⓘ", "關於程式", "查看程式資訊", self.show_about, "about"),
        ]
        for emoji, title, desc, command, key in nav_items:
            btn_frame = self.create_nav_button(self.nav_scroll_frame, emoji, title, desc, command, key)
            btn_frame.pack(fill="x", padx=Spacing.TINY, pady=Spacing.XS)
        self._create_sidebar_footer(self.sidebar, mini=False)

    def _create_sidebar_footer(self, parent, *, mini: bool) -> None:
        """在側邊欄底部顯示版本資訊（完整/迷你共用）。"""
        try:
            pad_x = 20 if not mini else 10
            pad_y = 20 if not mini else 12
            font_size = FontSize.MEDIUM if not mini else FontSize.NORMAL
            info_frame = ctk.CTkFrame(parent, fg_color="transparent")
            info_frame.pack(side="bottom", fill="x", padx=pad_x, pady=pad_y)
            version_label = ctk.CTkLabel(
                info_frame,
                text=f"版本 {APP_VERSION}",
                font=FontManager.get_font(size=font_size),
                text_color=Colors.TEXT_TERTIARY,
            )
            version_label.pack(anchor="w")
        except Exception as e:
            logger.exception(f"建立側邊欄底部資訊失敗: {e}")

    def create_nav_button(self, parent, icon, title, description, command, key) -> ctk.CTkFrame:
        """建立導航按鈕。

        Args:
            parent: 父容器。
            icon: 按鈕圖示。
            title: 按鈕標題。
            description: 按鈕說明文字。
            command: 按鈕點擊回呼。
            key: 導航識別鍵。

        Returns:
            包含按鈕與說明文字的框架。
        """
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_text = f"{icon} {title}" if icon else title
        btn = ctk.CTkButton(
            btn_frame,
            text=btn_text,
            font=FontManager.get_font(size=FontSize.HEADING_SMALL),
            anchor="w",
            height=FontManager.get_dpi_scaled_size(55),
            corner_radius=Spacing.SMALL,
            border_spacing=FontManager.get_dpi_scaled_size(10),
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            text_color=Colors.TEXT_ON_DARK,
        )
        btn.pack(fill="x", padx=Spacing.XS, pady=Spacing.XS)
        ctk.CTkLabel(
            btn_frame,
            text=description,
            font=FontManager.get_font(size=FontSize.MEDIUM),
            text_color=Colors.TEXT_SECONDARY,
            anchor="w",
        ).pack(fill="x", padx=Spacing.TINY, pady=(0, Spacing.TINY))
        main_nav_keys = {"create", "manage", "mods"}

        def on_click():
            if key in main_nav_keys:
                self.set_active_nav_button(key)
            command()

        btn.configure(command=on_click)
        self.nav_buttons[key] = btn
        return btn_frame

    def set_active_nav_button(self, key: str) -> None:
        """設定活動導航按鈕。

        Args:
            key: 要設為活動狀態的導航鍵。
        """
        if not key:
            return
        if getattr(self, "active_nav_key", None) == key:
            return
        default_colors = {"fg": Colors.BUTTON_INFO, "hover": Colors.BUTTON_INFO_HOVER}
        active_colors = {"fg": Colors.BUTTON_PRIMARY_ACTIVE, "hover": Colors.BUTTON_PRIMARY_ACTIVE_HOVER}

        def configure_button_colors(btn_widget: ctk.CTkButton, colors) -> None:
            """安全地設定按鈕顏色。"""
            try:
                if btn_widget and hasattr(btn_widget, "configure"):
                    btn_widget.configure(fg_color=colors["fg"], hover_color=colors["hover"])
            except Exception as e:
                logger.exception(f"設定導航按鈕顏色失敗: {e}")

        prev_key = getattr(self, "active_nav_key", None)
        if prev_key:
            prev_btn = self.nav_buttons.get(prev_key)
            if isinstance(prev_btn, ctk.CTkButton):
                configure_button_colors(prev_btn, default_colors)
        new_btn = self.nav_buttons.get(key)
        if isinstance(new_btn, ctk.CTkButton):
            configure_button_colors(new_btn, active_colors)
        self.active_nav_key = key

    def toggle_sidebar(self) -> None:
        """乾淨利索地切換側邊欄顯示/隱藏，無動畫"""
        self.sidebar_visible = not bool(getattr(self, "sidebar_visible", True))
        try:
            UIUtils.cancel_scheduled_job(self.root, "_sidebar_toggle_job", owner=self)
            UIUtils.cancel_scheduled_job(self.root, "_sidebar_unlock_job", owner=self)
        except Exception as e:
            logger.debug(f"toggle_sidebar 發生錯誤: {e}", "MainWindow")
        UIUtils.schedule_coalesced_idle(self.root, "_sidebar_toggle_job", self._apply_sidebar_visibility, owner=self)

    def _schedule_content_layout_unlock_for_sidebar_toggle(self) -> None:
        """側邊欄切換結束後延遲解鎖內容佈局（debounce）。"""
        delay_ms = max(0, int(getattr(self, "_sidebar_layout_unlock_delay_ms", 70)))
        UIUtils.schedule_debounce(
            self.root, "_sidebar_unlock_job", delay_ms, self._unlock_content_layout_for_sidebar_toggle, owner=self
        )

    def _apply_sidebar_visibility(self) -> None:
        """實際套用側邊欄顯示狀態（由 after_idle 觸發）。"""
        self._lock_content_layout_for_sidebar_toggle()
        try:
            if not getattr(self, "sidebar_visible", True):
                try:
                    container = getattr(self, "main_container", None)
                    if container is not None:
                        pad = int(getattr(self, "_nav_column_padding", 0))
                        container.grid_columnconfigure(0, minsize=int(self._nav_mini_width) + pad)
                    nav = getattr(self, "nav_container", None)
                    if nav is not None:
                        nav.configure(width=int(self._nav_mini_width))
                except Exception as e:
                    logger.debug(f"設定 Nav 寬度 失敗: {e}", "MainWindow")
                self.create_mini_sidebar()
                if hasattr(self, "mini_sidebar") and self.mini_sidebar:
                    try:
                        self.mini_sidebar.tkraise()
                    except Exception as e:
                        logger.debug(f"提升 mini_sidebar 失敗: {e}", "MainWindow")
            else:
                try:
                    container = getattr(self, "main_container", None)
                    if container is not None:
                        pad = int(getattr(self, "_nav_column_padding", 0))
                        container.grid_columnconfigure(0, minsize=int(self._nav_full_width) + pad)
                    nav = getattr(self, "nav_container", None)
                    if nav is not None:
                        nav.configure(width=int(self._nav_full_width))
                except Exception as e:
                    logger.debug(f"設定 Nav 寬度 失敗: {e}", "MainWindow")
                if hasattr(self, "sidebar") and self.sidebar:
                    try:
                        self.sidebar.tkraise()
                    except Exception as e:
                        logger.debug(f"提升 sidebar 失敗: {e}", "MainWindow")
        except Exception as e:
            logger.error(f"切換側邊欄失敗: {e}\n{traceback.format_exc()}")
        finally:
            self._schedule_content_layout_unlock_for_sidebar_toggle()

    def create_mini_sidebar(self) -> None:
        """創建迷你側邊欄（只顯示圖示）"""
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
        container = getattr(self, "nav_container", None) or self.sidebar.master
        self.mini_sidebar = ctk.CTkFrame(container, width=self._nav_mini_width, fg_color=self.colors["menu_bg"])
        self.mini_sidebar.grid(row=0, column=0, sticky="nsew")
        self.mini_sidebar.grid_propagate(False)
        mini_title = ctk.CTkLabel(
            self.mini_sidebar,
            text="功能選單",
            font=FontManager.get_font(size=FontSize.MEDIUM, weight="bold"),
            text_color=Colors.TEXT_PRIMARY[0],
        )
        mini_title.pack(pady=(Spacing.LARGE_MINUS, Spacing.SMALL_PLUS))
        icons_frame = ctk.CTkFrame(self.mini_sidebar, fg_color="transparent")
        icons_frame.pack(fill="both", expand=True)
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
                font=FontManager.get_font(size=FontSize.HEADING_SMALL),
                width=FontManager.get_dpi_scaled_size(55),
                height=FontManager.get_dpi_scaled_size(55),
                corner_radius=Spacing.SMALL,
                fg_color=Colors.BUTTON_INFO,
                hover_color=Colors.BUTTON_INFO_HOVER,
                text_color=Colors.TEXT_ON_DARK,
                command=command,
            )
            btn.pack(pady=Spacing.XS)
            self.create_tooltip(btn, tooltip)
        self._create_sidebar_footer(self.mini_sidebar, mini=True)

    def create_tooltip(self, widget, text) -> None:
        """為元件建立工具提示。

        Args:
            widget: 要綁定提示的元件。
            text: 提示文字。
        """
        UIUtils.bind_tooltip(
            widget,
            text,
            bg=Colors.BG_TOOLTIP,
            fg=Colors.TEXT_ON_DARK,
            font=FontManager.get_font(family="Microsoft JhengHei", size=FontSize.TINY),
            padx=Spacing.SMALL,
            pady=Spacing.XS,
            offset_x=10,
            offset_y=10,
            auto_hide_ms=None,
        )

    def _show_page_frame(self, frame) -> None:
        """使用 stack-grid + tkraise 切換頁面，避免反覆隱藏/重排。"""
        if frame is None:
            return
        try:
            if frame.winfo_manager() != "grid":
                frame.grid(row=0, column=0, sticky="nsew")
            frame.tkraise()
        except Exception:
            frame.pack(fill="both", expand=True)

    def _lock_content_layout_for_sidebar_toggle(self) -> None:
        """側邊欄切換期間暫時鎖住主內容區，降低 resize 撕裂。"""
        if getattr(self, "_content_layout_locked", False):
            return
        container = getattr(self, "content_container", None)
        content = getattr(self, "content_frame", None)
        if not container or not content:
            return
        try:
            width = int(container.winfo_width())
            height = int(container.winfo_height())
            if width <= 1 or height <= 1:
                return
            container.grid_propagate(False)
            content.grid_propagate(False)
            container.configure(width=width, height=height)
            self._content_layout_locked = True
        except Exception as e:
            logger.debug(f"鎖定內容區佈局失敗: {e}", "MainWindow")

    def _unlock_content_layout_for_sidebar_toggle(self) -> None:
        """解除側邊欄切換期間的內容區佈局鎖。"""
        self._sidebar_unlock_job = None
        if not getattr(self, "_content_layout_locked", False):
            return
        container = getattr(self, "content_container", None)
        content = getattr(self, "content_frame", None)
        try:
            if container:
                container.grid_propagate(True)
            if content:
                content.grid_propagate(True)
        except Exception as e:
            logger.debug(f"解除內容區佈局鎖失敗: {e}", "MainWindow")
        finally:
            self._content_layout_locked = False

    def show_create_server(self) -> None:
        """顯示建立伺服器頁面"""
        if getattr(self, "manage_server_frame", None) is not None:
            with contextlib.suppress(Exception):
                self.manage_server_frame.set_auto_refresh_enabled(False)
        self._show_page_frame(self.create_server_frame)
        self.set_active_nav_button("create")

    def show_manage_server(self, auto_select=None) -> None:
        """顯示管理伺服器頁面並強制刷新伺服器列表。

        Args:
            auto_select: 可選的伺服器名稱，用於刷新後自動選取。
        """
        self._ensure_manage_server_frame()
        with contextlib.suppress(Exception):
            self.manage_server_frame.set_auto_refresh_enabled(True)
        self._show_page_frame(self.manage_server_frame)
        self.set_active_nav_button("manage")

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

        UIUtils.schedule_debounce(self.root, "_nav_refresh_job", 0, _refresh_and_optionally_select, owner=self)

    def show_mod_management(self) -> None:
        """顯示模組管理頁面"""
        if getattr(self, "manage_server_frame", None) is not None:
            with contextlib.suppress(Exception):
                self.manage_server_frame.set_auto_refresh_enabled(False)
        self._ensure_mod_management_frame()
        self.mod_frame.load_servers()
        frame = self.mod_frame.get_frame()
        self._show_page_frame(frame)
        self.set_active_nav_button("mods")

    def import_server(self) -> None:
        """
        匯入伺服器（資料夾或壓縮檔）
        統一入口匯入伺服器，支援資料夾和壓縮檔
        """
        dialog = DialogUtils.create_toplevel_dialog(
            parent=self.root,
            title="匯入伺服器",
            width=Sizes.DIALOG_IMPORT_WIDTH,
            height=Sizes.DIALOG_IMPORT_HEIGHT,
            resizable=False,
            delay_ms=0,
            reveal_after_setup=False,
        )
        choice = {"value": None}
        content = ctk.CTkFrame(dialog)
        content.pack(fill="both", expand=True, padx=Spacing.XL, pady=Spacing.XL)
        ctk.CTkLabel(content, text="選擇匯入方式", font=FontManager.get_font(size=FontSize.LARGE, weight="bold")).pack(
            pady=(Spacing.SMALL_PLUS, Spacing.LARGE_MINUS)
        )
        ctk.CTkLabel(content, text="請選擇要匯入的伺服器類型:", font=FontManager.get_font(size=FontSize.MEDIUM)).pack(
            pady=(0, Spacing.XL)
        )
        button_frame = ctk.CTkFrame(content, fg_color="transparent")
        button_frame.pack(fill="x", padx=Spacing.XL)
        options = [("📁 匯入資料夾", "folder"), ("📦 匯入壓縮檔", "archive"), ("❌ 取消", "cancel")]
        for label, key in options:
            font_weight = "bold" if key != "cancel" else "normal"
            btn = ctk.CTkButton(
                button_frame,
                text=label,
                command=lambda k=key: self._set_choice(choice, k, dialog),
                font=FontManager.get_font(size=FontSize.NORMAL_PLUS, weight=font_weight),
                height=Sizes.BUTTON_HEIGHT_MEDIUM,
            )
            btn.pack(fill="x", pady=Spacing.TINY)
        dialog.bind("<Escape>", lambda _e: self._set_choice(choice, "cancel", dialog))
        dialog.wait_window()
        if choice["value"] in [None, "cancel"]:
            return
        self._handle_import_choice(choice["value"])

    def _set_choice(self, choice_dict, value, dialog) -> None:
        """設定選擇並關閉對話框"""
        choice_dict["value"] = value
        dialog.destroy()

    def _handle_import_choice(self, choice_type) -> None:
        """處理匯入選擇"""
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
        """選擇伺服器資料夾"""
        folder_path = filedialog.askdirectory(title="選擇伺服器資料夾")
        if not folder_path:
            return None
        path = Path(folder_path)

        if not ServerDetectionUtils.is_valid_server_folder(path):
            UIUtils.show_error("無效資料夾", "選擇的資料夾不是有效的 Minecraft 伺服器資料夾。", self.root)
            return None
        return path

    def _select_server_archive(self) -> Path | None:
        """選擇伺服器壓縮檔"""
        file_path = filedialog.askopenfilename(
            title="選擇伺服器壓縮檔", filetypes=[("ZIP 壓縮檔", "*.zip"), ("所有檔案", "*.*")]
        )
        if not file_path:
            return None
        path = Path(file_path)
        if path.suffix.lower() != ".zip":
            UIUtils.show_error("不支援的格式", f"目前僅支援 ZIP 格式。\n選擇的檔案: {path.suffix}", self.root)
            return None
        return path

    def _prompt_server_name(self, default_name: str) -> str | None:
        """提示輸入伺服器名稱"""
        dialog = DialogUtils.create_toplevel_dialog(
            parent=self.root,
            title="輸入伺服器名稱",
            width=Sizes.DIALOG_SMALL_WIDTH,
            height=Sizes.DIALOG_SMALL_HEIGHT,
            resizable=False,
            delay_ms=0,
            reveal_after_setup=False,
        )
        result = {"name": None}
        frame = ctk.CTkFrame(dialog)
        frame.pack(fill="both", expand=True, padx=Spacing.XL, pady=Spacing.XL)
        ctk.CTkLabel(frame, text="請輸入伺服器名稱:", font=FontManager.get_font(size=FontSize.MEDIUM)).pack(
            pady=(Spacing.SMALL_PLUS, Spacing.LARGE_MINUS)
        )
        entry = ctk.CTkEntry(frame, font=FontManager.get_font(size=FontSize.MEDIUM), width=Sizes.INPUT_WIDTH)
        entry.pack(pady=(0, Spacing.XL))
        entry.insert(0, default_name)
        entry.focus()
        entry.select_range(0, tkinter.END)
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
            if self.server_manager.server_exists(name) and (
                not UIUtils.ask_yes_no_cancel(
                    "名稱衝突", f"'{name}' 已存在於設定，是否覆蓋?", dialog, show_cancel=False
                )
            ):
                return
            result["name"] = name
            dialog.destroy()

        def _cancel():
            dialog.destroy()

        ctk.CTkButton(
            btn_frame, text="確定", command=_ok, width=Sizes.BUTTON_WIDTH_COMPACT, height=Sizes.BUTTON_HEIGHT_MEDIUM
        ).pack(side="left", padx=(0, Spacing.SMALL_PLUS))
        ctk.CTkButton(
            btn_frame, text="取消", command=_cancel, width=Sizes.BUTTON_WIDTH_COMPACT, height=Sizes.BUTTON_HEIGHT_MEDIUM
        ).pack(side="left")
        entry.bind("<Return>", lambda _e: _ok())
        dialog.bind("<Escape>", lambda _e: _cancel())
        dialog.wait_window()
        return result["name"]

    def _finalize_import(self, source_path: Path, server_name: str) -> None:
        """完成伺服器匯入流程"""
        target_path = self.server_manager.servers_root / server_name
        progress_dialog = DialogUtils.create_toplevel_dialog(
            parent=self.root,
            title="正在匯入伺服器",
            width=Sizes.DIALOG_SMALL_WIDTH,
            height=Sizes.DIALOG_SMALL_HEIGHT,
            resizable=False,
            make_modal=True,
            delay_ms=0,
            reveal_after_setup=False,
        )
        content = ctk.CTkFrame(progress_dialog)
        content.pack(fill="both", expand=True, padx=Spacing.XL, pady=Spacing.XL)
        ctk.CTkLabel(
            content, text=f"正在匯入 {server_name}...", font=FontManager.get_font(size=FontSize.LARGE, weight="bold")
        ).pack(pady=(Spacing.TINY, Spacing.SMALL_PLUS))
        ctk.CTkLabel(
            content,
            text="大型匯入可能需要較長時間，請稍候。",
            font=FontManager.get_font(size=FontSize.NORMAL),
            text_color=Colors.TEXT_SECONDARY,
        ).pack(pady=(0, Spacing.SMALL_PLUS))
        progress_text = ctk.CTkLabel(
            content, text="進度: 0%", font=FontManager.get_font(size=FontSize.NORMAL), text_color=Colors.TEXT_SECONDARY
        )
        progress_text.pack(pady=(0, Spacing.SMALL))
        progress_bar = ctk.CTkProgressBar(content, mode="determinate")
        progress_bar.pack(fill="x", padx=Spacing.SMALL_PLUS, pady=(0, Spacing.TINY))
        progress_bar.set(0)
        progress_dialog.protocol("WM_DELETE_WINDOW", lambda: None)

        def _close_progress_dialog() -> None:
            with contextlib.suppress(Exception):
                progress_bar.stop()
            with contextlib.suppress(Exception):
                if progress_dialog.winfo_exists():
                    progress_dialog.destroy()

        def _import_task() -> None:
            try:
                last_percent = -1

                def _on_import_progress(done_units: int, total_units: int) -> None:
                    nonlocal last_percent
                    if total_units <= 0:
                        return
                    percent = max(0, min(100, int(done_units * 100 / total_units)))
                    if percent == last_percent:
                        return
                    last_percent = percent

                    def _update_progress_ui(progress_value: int = percent) -> None:
                        with contextlib.suppress(Exception):
                            progress_bar.set(progress_value / 100)
                        with contextlib.suppress(Exception):
                            progress_text.configure(text=f"進度: {progress_value}%")

                    self.ui_queue.put(_update_progress_ui)

                if source_path.is_file():
                    target_path.mkdir(parents=True, exist_ok=True)
                    PathUtils.safe_extract_zip(source_path, target_path, progress_callback=_on_import_progress)
                    if last_percent < 100:
                        self.ui_queue.put(lambda: progress_bar.set(1.0))
                        self.ui_queue.put(lambda: progress_text.configure(text="進度: 100%"))
                    items = list(target_path.iterdir())
                    if len(items) == 1 and items[0].is_dir():
                        for item in items[0].iterdir():
                            if not PathUtils.move_within(target_path, item, target_path / item.name):
                                raise Exception(f"搬移匯入檔案失敗：{item.name}")
                        items[0].rmdir()
                else:
                    if not PathUtils.copy_dir(source_path, target_path, progress_callback=_on_import_progress):
                        raise Exception("複製伺服器資料夾失敗")
                    if last_percent < 100:
                        self.ui_queue.put(lambda: progress_bar.set(1.0))
                        self.ui_queue.put(lambda: progress_text.configure(text="進度: 100%"))
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

                def _on_import_success() -> None:
                    _close_progress_dialog()
                    self.server_manager.add_server(server_config)
                    UIUtils.show_info(
                        "匯入成功",
                        f"伺服器 '{server_name}' 匯入成功!\n\n類型: {server_config.loader_type}\n版本: {server_config.minecraft_version}",
                        self.root,
                    )
                    self.show_manage_server(auto_select=server_name)

                self.ui_queue.put(_on_import_success)
            except Exception as e:
                logger.error(f"匯入失敗: {e}\n{traceback.format_exc()}", "MainWindow")

                def _on_import_error(msg: str = str(e)) -> None:
                    _close_progress_dialog()
                    UIUtils.show_error("匯入失敗", f"伺服器 '{server_name}' 匯入失敗: {msg}", self.root)

                self.ui_queue.put(_on_import_error)

        TaskUtils.run_async(_import_task)

    def hide_all_frames(self) -> None:
        """相容舊流程：頁面切換已改用 tkraise，不再逐一隱藏 frame。"""
        return

    def open_servers_folder(self) -> None:
        """開啟伺服器資料夾"""
        folder = self.servers_root
        folder_path = Path(folder)
        if not folder_path.exists():
            folder_path.mkdir(parents=True, exist_ok=True)
        try:
            UIUtils.open_external(str(folder_path))
        except Exception as e:
            logger.error(f"無法開啟路徑: {e}\n{traceback.format_exc()}", "MainWindow")
            UIUtils.show_error("錯誤", f"無法開啟路徑: {e}", self.root)

    def show_about(self) -> None:
        """顯示關於對話框"""
        about_dialog = DialogUtils.create_toplevel_dialog(
            parent=self.root,
            title="關於 Minecraft 伺服器管理器",
            width=Sizes.DIALOG_ABOUT_WIDTH,
            height=Sizes.DIALOG_ABOUT_HEIGHT,
            resizable=True,
            bind_icon=True,
            delay_ms=0,
            reveal_after_setup=False,
        )
        scrollable_frame = ctk.CTkScrollableFrame(about_dialog)
        scrollable_frame.pack(fill="both", expand=True, padx=Spacing.XL, pady=Spacing.XL)
        ctk.CTkLabel(
            scrollable_frame,
            text="🎮 Minecraft 伺服器管理器",
            font=FontManager.get_font(size=FontSize.HEADING_XLARGE, weight="bold"),
        ).pack(pady=(0, Spacing.TINY))
        ctk.CTkLabel(
            scrollable_frame,
            text=f"版本 {APP_VERSION}",
            font=FontManager.get_font(size=FontSize.LARGE),
            text_color=Colors.TEXT_TERTIARY,
        ).pack(pady=(0, Spacing.XL))
        ctk.CTkLabel(
            scrollable_frame,
            text="👨\u200d💻 開發資訊",
            font=FontManager.get_font(size=FontSize.HEADING_MEDIUM, weight="bold"),
        ).pack(anchor="w", pady=(0, Spacing.SMALL_PLUS))
        dev_info = "• 開發者: Minecraft Server Manager Team\n• 技術棧: Python 3.7+, tkinter, coustomtkinter\n• Java 管理：自動偵測/下載 Minecraft官方 JDK，完全自動化\n• 架構: 模組化設計, 事件驅動\n• 參考專案: PrismLauncher"
        ctk.CTkLabel(
            scrollable_frame,
            text=dev_info,
            font=FontManager.get_font(size=FontSize.NORMAL_PLUS),
            justify="left",
            wraplength=Sizes.DIALOG_PREFERENCES_WIDTH,
        ).pack(anchor="w", pady=(0, Spacing.TINY))
        github_url = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
        github_lbl = ctk.CTkLabel(
            scrollable_frame,
            text="GitHub-MinecraftServerManager",
            font=FontManager.get_font(family="Microsoft JhengHei", size=FontSize.MEDIUM, underline=True),
            text_color=Colors.TEXT_LINK,
            cursor="hand2",
            anchor="w",
        )
        github_lbl.pack(anchor="w", pady=(0, Spacing.XL))
        github_lbl.bind("<Button-1>", lambda _e, url=github_url: UIUtils.open_external(url))
        ctk.CTkLabel(
            scrollable_frame, text="📄 授權條款", font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold")
        ).pack(anchor="w", pady=(0, Spacing.SMALL_PLUS))
        license_info = "• 本專案採用 GNU General Public License v3.0 授權條款\n• 部分設計理念參考 PrismLauncher\n• 僅供學習和個人使用\n• 請遵守 Minecraft EULA 和當地法律法規\n\n特別感謝 PrismLauncher 開發團隊的開源貢獻！"
        ctk.CTkLabel(
            scrollable_frame,
            text=license_info,
            font=FontManager.get_font(size=FontSize.NORMAL_PLUS),
            justify="left",
            wraplength=Sizes.DIALOG_PREFERENCES_WIDTH,
        ).pack(anchor="w", pady=(0, Spacing.XXL))
        settings_frame = ctk.CTkFrame(scrollable_frame, fg_color="transparent")
        settings_frame.pack(fill="x", pady=(0, Spacing.XL))
        settings = get_settings_manager()
        ctk.CTkLabel(
            settings_frame, text="🔄 更新設定", font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold")
        ).pack(anchor="w", pady=(0, Spacing.SMALL_PLUS))
        auto_update_var = ctk.BooleanVar(value=settings.is_auto_update_enabled())
        auto_update_checkbox = ctk.CTkCheckBox(
            settings_frame,
            text="自動檢查更新",
            variable=auto_update_var,
            font=FontManager.get_font(size=FontSize.NORMAL_PLUS),
            command=lambda: self._on_auto_update_changed(auto_update_var.get(), manual_check_btn),
        )
        auto_update_checkbox.pack(anchor="w", pady=(0, Spacing.SMALL_PLUS))
        manual_check_btn: ctk.CTkButton | None = None
        manual_check_btn = ctk.CTkButton(
            settings_frame,
            text="檢查更新",
            command=self._manual_check_updates,
            font=FontManager.get_font(size=FontSize.NORMAL),
            width=Sizes.BUTTON_WIDTH_SECONDARY,
            height=Sizes.DROPDOWN_HEIGHT,
        )
        if not settings.is_auto_update_enabled():
            manual_check_btn.pack(anchor="w", pady=(0, Spacing.SMALL_PLUS))
        if RuntimePaths.is_portable_mode():
            ctk.CTkLabel(
                settings_frame,
                text="📦 便攜模式",
                font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
            ).pack(anchor="w", pady=(Spacing.MEDIUM, Spacing.SMALL_PLUS))
            portable_info_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
            portable_info_frame.pack(fill="x", pady=(0, Spacing.SMALL_PLUS))
            ctk.CTkLabel(
                portable_info_frame,
                text="您正在使用便攜版本。\n如需更新，請從 Releases 下載新版 portable ZIP，或使用內建的檢查更新功能。",
                font=FontManager.get_font(size=FontSize.NORMAL_PLUS),
                justify="left",
            ).pack(anchor="w")
        window_prefs_btn = ctk.CTkButton(
            settings_frame,
            text="視窗偏好設定",
            command=self._show_window_preferences,
            font=FontManager.get_font(size=FontSize.NORMAL),
            width=Sizes.BUTTON_WIDTH_SECONDARY,
            height=Sizes.DROPDOWN_HEIGHT,
        )
        window_prefs_btn.pack(anchor="w", pady=(0, Spacing.SMALL_PLUS))
        ctk.CTkButton(
            scrollable_frame,
            text="關閉",
            command=about_dialog.destroy,
            font=FontManager.get_font(size=FontSize.NORMAL, weight="bold"),
            width=Sizes.BUTTON_WIDTH_SMALL,
            height=Sizes.BUTTON_HEIGHT_MEDIUM,
        ).pack(pady=(Spacing.SMALL_PLUS, 0))
        about_dialog.bind("<Escape>", lambda _e: about_dialog.destroy())

    def _on_auto_update_changed(self, enabled: bool, manual_check_btn) -> None:
        """自動更新設定變更時的回調"""
        settings = get_settings_manager()
        settings.set_auto_update_enabled(enabled)
        if enabled:
            manual_check_btn.pack_forget()
        else:
            manual_check_btn.pack(anchor="w", pady=(0, Spacing.SMALL_PLUS))

    def _manual_check_updates(self) -> None:
        """手動檢查更新"""
        self._check_for_updates()

    def _show_window_preferences(self) -> None:
        """顯示視窗偏好設定對話框"""

        def on_settings_changed():
            """設定變更回調"""
            logger.debug("視窗偏好設定已變更", "MainWindow")

        WindowPreferencesDialog(self.root, on_settings_changed)

    def on_server_created(self, server_config: ServerConfig) -> None:
        """伺服器建立完成的回調。

        Args:
            server_config: 新建立的伺服器設定。
        """
        self.initialize_server(server_config)

    def initialize_server(self, server_config: ServerConfig) -> None:
        """啟動伺服器初始化流程。

        Args:
            server_config: 要初始化的伺服器設定。
        """
        dialog = ServerInitializationDialog(self.root, server_config, self.complete_initialization)
        dialog.start_initialization()

    def on_server_selected(self, server_name: str) -> None:
        """伺服器被選中的回調。

        Args:
            server_name: 被選取的伺服器名稱。
        """
        logger.info(f"選中伺服器: {server_name}")

    def complete_initialization(self, server_config: ServerConfig, init_dialog) -> None:
        """完成伺服器初始化後的 UI 收尾。

        Args:
            server_config: 已初始化的伺服器設定。
            init_dialog: 初始化對話框實例。
        """
        init_dialog.destroy()
        server_path = Path(server_config.path)
        properties_file = server_path / "server.properties"
        try:
            if properties_file.exists():
                properties = ServerPropertiesHelper.load_properties(properties_file)
                server_config.properties = properties
        except Exception as e:
            logger.error(f"初始化後讀取 server.properties 失敗: {e}\n{traceback.format_exc()}")
        self.show_manage_server(auto_select=server_config.name)
        UIUtils.show_info(
            "初始化完成",
            f"伺服器 「{server_config.name}」 已成功初始化並可開始使用！\n\n你現在可以進一步調整伺服器設定或直接啟動",
            self.root,
        )


class ServerInitializationDialog:
    """伺服器初始化對話框"""

    def __init__(self, parent: tkinter.Tk, server_config: ServerConfig, completion_callback=None):
        self.parent = parent
        self.server_config = server_config
        self.server_path = Path(server_config.path)
        self.completion_callback = completion_callback
        self.server_process: Any | None = None
        self.done_detected = False
        self.init_dialog: ctk.CTkToplevel | None = None
        self.console_text: ctk.CTkTextbox | None = None
        self.progress_label: ctk.CTkLabel | None = None
        self.close_button: ctk.CTkButton | None = None
        self._console_queue: queue.Queue[str] = queue.Queue()
        self._console_pump_job = None

    def _enqueue_console(self, text: str) -> None:
        try:
            self._console_queue.put_nowait(text)
        except Exception as e:
            get_logger().bind(component="InitServerDialog").exception(f"加入 console queue 失敗: {e}")

    def _start_console_pump(self) -> None:
        """啟動初始化 console 批次刷新（debounce 迴圈）。"""
        if self._console_pump_job is not None:
            return

        def _schedule_next(delay_ms: int) -> None:
            if not self.init_dialog or not self.init_dialog.winfo_exists():
                self._console_pump_job = None
                return
            UIUtils.schedule_debounce(self.init_dialog, "_console_pump_job", delay_ms, _tick, owner=self)

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
            _schedule_next(delay)

        _schedule_next(50)

    def _schedule_dialog_job(self, job_attr: str, delay_ms: int, callback: Callable[[], Any]) -> None:
        """統一對初始化對話框排程 UI 工作（debounce）。"""
        dialog = self.init_dialog
        if not dialog or not dialog.winfo_exists():
            return
        UIUtils.schedule_debounce(dialog, job_attr, delay_ms, callback, owner=self)

    def _cancel_dialog_jobs(self) -> None:
        """關閉初始化對話框前，集中取消待執行排程。"""
        dialog = self.init_dialog
        if not dialog or not dialog.winfo_exists():
            return
        for job_attr in (
            "_console_pump_job",
            "_init_timeout_job",
            "_init_progress_job",
            "_init_world_prep_job",
            "_init_world_load_job",
            "_init_closing_job",
            "_init_complete_job",
            "_init_error_job",
            "_init_transition_job",
        ):
            UIUtils.cancel_scheduled_job(dialog, job_attr, owner=self)

    def start_initialization(self) -> None:
        """啟動初始化對話框流程。"""
        self._create_dialog()
        self._setup_ui()
        self._start_server_thread()

    def _create_dialog(self) -> None:
        """建立初始化對話框"""
        self.init_dialog = DialogUtils.create_toplevel_dialog(
            self.parent,
            f"初始化伺服器 - {self.server_config.name}",
            width=Sizes.DIALOG_LARGE_WIDTH,
            height=Sizes.DIALOG_LARGE_HEIGHT,
            delay_ms=250,
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
        title_label = ctk.CTkLabel(
            self.init_dialog,
            text=f"正在初始化伺服器: {self.server_config.name}",
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
        )
        title_label.pack(pady=Spacing.SMALL_PLUS)
        info_label = ctk.CTkLabel(
            self.init_dialog,
            text="伺服器正在首次啟動，請等待初始化完成...\n系統會自動在完成後關閉伺服器",
            font=FontManager.get_font(size=FontSize.LARGE),
        )
        info_label.pack(pady=Spacing.TINY)

    def _create_console(self) -> None:
        """建立控制台輸出區域"""
        console_frame = ctk.CTkFrame(self.init_dialog)
        console_frame.pack(fill="both", expand=True, padx=Spacing.SMALL_PLUS, pady=Spacing.SMALL_PLUS)
        self.console_text = ctk.CTkTextbox(
            console_frame,
            font=FontManager.get_font(family="Consolas", size=FontSize.TINY),
            wrap="none",
            fg_color=(Colors.BG_CONSOLE, Colors.BG_CONSOLE),
            text_color=(Colors.CONSOLE_TEXT, Colors.CONSOLE_TEXT),
        )
        self.console_text.pack(fill="both", expand=True, padx=Spacing.TINY, pady=Spacing.TINY)
        self._start_console_pump()

    def _create_progress_label(self) -> None:
        """建立進度標籤"""
        if not self.init_dialog:
            return
        self.progress_label = ctk.CTkLabel(
            self.init_dialog, text="狀態: 準備啟動...", font=FontManager.get_font(size=FontSize.INPUT, weight="bold")
        )
        self.progress_label.pack(pady=Spacing.TINY)

    def _create_buttons(self) -> None:
        """建立按鈕區域"""
        if not self.init_dialog:
            return
        button_frame = ctk.CTkFrame(self.init_dialog, fg_color="transparent")
        button_frame.pack(pady=Spacing.SMALL_PLUS)
        self.close_button = ctk.CTkButton(
            button_frame,
            text="取消初始化",
            command=self._close_init_server,
            font=FontManager.get_font(size=FontSize.MEDIUM),
            width=Sizes.BUTTON_WIDTH_SECONDARY,
            height=Sizes.BUTTON_HEIGHT_MEDIUM,
            fg_color=Colors.TEXT_ERROR,
            hover_color=Colors.BUTTON_DANGER,
            border_width=Spacing.XS,
            border_color=Colors.BUTTON_DANGER_HOVER,
            corner_radius=Spacing.TINY,
        )
        self.close_button.pack(side="right", padx=Spacing.TINY)

    def _setup_timeout(self) -> None:
        """設定超時自動關閉"""
        if self.init_dialog:
            self._schedule_dialog_job("_init_timeout_job", 120000, self._timeout_force_close)

    def _start_server_thread(self) -> None:
        """在背景執行緒中啟動伺服器"""
        TaskUtils.run_async(self._run_server)

    def _close_init_server(self) -> None:
        """關閉初始化伺服器。"""
        if self.done_detected:
            if self.init_dialog and self.init_dialog.winfo_exists():
                self._cancel_dialog_jobs()
                UIUtils.show_info("初始化完成", "伺服器已成功初始化並安全關閉。", parent=self.parent)
                self.init_dialog.destroy()
        else:
            self._terminate_server_process()
            if self.init_dialog and self.init_dialog.winfo_exists():
                self._cancel_dialog_jobs()
                UIUtils.show_warning("強制關閉", "伺服器初始化未完成，已強制關閉。請檢查伺服器日誌。", self.parent)
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
        if self.init_dialog and self.init_dialog.winfo_exists() and (not self.done_detected):
            self._close_init_server()

    def _update_console(self, text: str) -> None:
        """更新控制台輸出"""
        try:
            if self.init_dialog and self.init_dialog.winfo_exists() and self.console_text:
                self.console_text.insert("end", text)
                self.console_text.see("end")
        except tkinter.TclError:
            logger.exception("更新控制台輸出失敗")

    def _run_server(self) -> None:
        """在背景執行緒中啟動伺服器"""
        try:
            if self.init_dialog:
                self._schedule_dialog_job(
                    "_init_progress_job",
                    0,
                    lambda: (
                        self.progress_label.configure(text="狀態: 正在啟動伺服器...")
                        if self.progress_label and self.progress_label.winfo_exists()
                        else None
                    ),
                )
            self._enqueue_console("正在啟動 Minecraft 伺服器...\n")
            java_cmd = self._build_java_command()
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
                f"伺服器啟動失敗: {e}\n{traceback.format_exc()}"
            )
            self._handle_server_error(str(e))

    def _build_java_command(self) -> list[str]:
        """建立 Java 命令"""
        loader_type = str(self.server_config.loader_type or "").lower()
        if loader_type == "forge":
            return self._build_forge_command()
        java_cmd = ServerCommands.build_java_command(self.server_config, return_list=True)
        self._enqueue_console(f"執行命令: {' '.join(java_cmd)}\n\n")
        return java_cmd

    def _build_forge_command(self) -> list[str]:
        """建立 Forge 伺服器命令"""
        user_args = Path(self.server_path) / "user_jvm_args.txt"

        if user_args.exists():
            ServerDetectionUtils.update_forge_user_jvm_args(self.server_path, self.server_config)
        start_bat = Path(self.server_path) / "start_server.bat"
        java_cmd = None
        if user_args.exists() and start_bat.exists():
            java_cmd = self._extract_java_command_from_bat(start_bat)
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
                    if re.search("\\bjava\\b.*@user_jvm_args\\.txt\\b", line, re.IGNORECASE):
                        cleaned = re.sub("\\s*[%$]\\*?$", "", line.strip())
                        java_cmd = cleaned.split()
                        get_logger().bind(component="ServerInitializationDialog").debug(
                            f"forge_java_command: {java_cmd}"
                        )
                        return java_cmd
        except Exception as e:
            logger.exception(f"提取 Java 命令失敗: {e}")
        return None

    def _monitor_server_output(self) -> None:
        """監控伺服器輸出"""
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
        if self.server_process is not None:
            self.server_process.wait()

    def _process_server_output(self, output: str) -> None:
        """處理伺服器輸出"""
        if self.init_dialog is None or not self.init_dialog.winfo_exists():
            return
        if "Loading dimension" in output or "Preparing spawn area" in output:
            with contextlib.suppress(tkinter.TclError):
                self._schedule_dialog_job(
                    "_init_world_prep_job",
                    0,
                    lambda: (
                        self.progress_label.configure(text="狀態: 準備世界...")
                        if self.progress_label and self.progress_label.winfo_exists()
                        else None
                    ),
                )
        elif "Preparing level" in output:
            with contextlib.suppress(tkinter.TclError):
                self._schedule_dialog_job(
                    "_init_world_load_job",
                    0,
                    lambda: (
                        self.progress_label.configure(text="狀態: 載入世界...")
                        if self.progress_label and self.progress_label.winfo_exists()
                        else None
                    ),
                )
        elif "Done (" in output and 'For help, type "help"' in output and (not self.done_detected):
            self.done_detected = True
            if self.close_button and self.close_button.winfo_exists():
                self.close_button.configure(
                    text="關閉伺服器", command=self._close_init_server, fg_color=Colors.BUTTON_SUCCESS
                )

    def _handle_server_ready(self, output: str) -> None:
        """處理伺服器就緒狀態"""
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
            self._schedule_dialog_job("_init_closing_job", 0, update_closing_status)
        if self.server_process and self.server_process.stdin:
            self.server_process.stdin.write("stop\n")
            self.server_process.stdin.flush()

    def _handle_server_completion(self) -> None:
        """處理伺服器完成狀態"""
        if self.init_dialog is None:
            return
        if self.done_detected:

            def complete_init():
                if self.init_dialog and self.init_dialog.winfo_exists():
                    self._update_console("[系統] 伺服器初始化完成！\n")
                    if self.progress_label and self.progress_label.winfo_exists():
                        self.progress_label.configure(text="狀態: 初始化完成")

            self._schedule_dialog_job("_init_complete_job", 0, complete_init)
            if self.completion_callback:
                self._schedule_dialog_job(
                    "_init_transition_job", 2000, lambda: self.completion_callback(self.server_config, self.init_dialog)
                )
        else:

            def show_error():
                if self.init_dialog and self.init_dialog.winfo_exists():
                    self._update_console("[系統] 伺服器啟動可能有問題，請檢查輸出\n")
                    if self.progress_label and self.progress_label.winfo_exists():
                        self.progress_label.configure(text="狀態: 啟動異常")

            self._schedule_dialog_job("_init_error_job", 0, show_error)

    def _handle_server_error(self, err_msg: str) -> None:
        """處理伺服器錯誤"""
        if self.init_dialog is None:
            return

        def show_error():
            if self.init_dialog and self.init_dialog.winfo_exists():
                self._update_console(f"[錯誤] 啟動失敗: {err_msg}\n")
                if self.progress_label and self.progress_label.winfo_exists():
                    self.progress_label.configure(text="狀態: 啟動失敗")

        self._schedule_dialog_job("_init_error_job", 0, show_error)
