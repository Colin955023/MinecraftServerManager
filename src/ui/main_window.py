"""
主視窗
Minecraft 伺服器管理器的主要使用者介面
本模組定義 Minecraft 伺服器管理器的主視窗。
"""

from __future__ import annotations

import contextlib
import queue
import re
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from ..core import (
    ConfigurationError,
    LoaderManager,
    MinecraftVersionManager,
    ServerBackupManager,
    ServerCRUD,
    ServerStartup,
)
from ..models import ServerConfig
from ..utils import (
    APP_VERSION,
    GITHUB_OWNER,
    GITHUB_REPO,
    Colors,
    DialogUtils,
    FluentPushButton,
    FontManager,
    FontSize,
    IconUtils,
    NativeQtStyle,
    PathUtils,
    QtCore,
    QtGui,
    QtWidgets,
    ServerCommands,
    ServerDetectionUtils,
    ServerPropertiesHelper,
    Sizes,
    Spacing,
    SubprocessUtils,
    SystemUtils,
    TaskUtils,
    UIUtils,
    WindowManager,
    ensure_application,
    get_logger,
    get_settings_manager,
    initialize_ui_theme,
    install_open_url_click,
    record_and_mark,
    resolve_color,
    show_window,
)
from ..utils.ui_support import qt_widgets as qt
from . import (
    CreateServerFrame,
    ManageServerFrame,
    ModManagementFrame,
    PageRouter,
    TaskCoordinator,
    WindowPreferencesDialog,
)

logger = get_logger().bind(component="MainWindow")


def _qt_font(font: Any) -> QtGui.QFont:
    """回傳 FontManager 內保存的原生 QFont。"""
    return getattr(font, "font", font)


def _qt_color(color: Any) -> str:
    """回傳專案色彩 token 對應的 Qt 色碼。"""
    return resolve_color(color)


def _native_widget(widget: Any) -> QtWidgets.QWidget | None:
    """將 adapter 物件解析為原生 Qt widget。"""
    if widget is None:
        return None
    return getattr(widget, "_qt_widget", widget)


def _set_layout_margins(layout: QtWidgets.QLayout, *margins: int) -> None:
    layout.setContentsMargins(*(int(v) for v in margins))


def _make_fluent_button(text: str, parent: QtWidgets.QWidget | None = None) -> QtWidgets.QPushButton:
    try:
        return FluentPushButton(text, parent)
    except TypeError:
        button = FluentPushButton(parent)
        button.setText(text)
        return button


class MainWindow:
    """Minecraft 伺服器管理器主視窗類別"""

    def set_servers_root(self, new_root: str | None = None) -> str:
        """
        取得或設定伺服器根目錄。

        Args:
            new_root: 要設定的新根目錄；未提供時會提示使用者選擇。

        Returns:
            解析後的伺服器根目錄字串。
        """
        settings = get_settings_manager()

        def _fail_exit(msg: str):
            """錯誤退出處理"""
            UIUtils.show_error("錯誤", msg, self.root)
            self.root.close()
            sys.exit(0)

        def _prompt_for_directory() -> str:
            """提示選擇目錄"""
            UIUtils.show_info(
                "選擇伺服器資料夾",
                "請選擇要存放所有 Minecraft 伺服器的主資料夾\n(系統會在該資料夾內自動建立 servers 子資料夾)",
                self.root,
            )
            folder = qt.get_existing_directory(title="選擇伺服器主資料夾")
            if not folder:
                if UIUtils.ask_yes_no_cancel(
                    "結束程式", "未選擇資料夾，是否要結束程式？", self.root, show_cancel=False
                ):
                    self.root.close()
                    sys.exit(0)
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
            FontManager.clear_cache()
            if getattr(self, "server_crud", None) is not None:
                self.server_crud.write_servers_config()
            app = QtWidgets.QApplication.instance()
            if isinstance(app, QtWidgets.QApplication):
                for widget in app.topLevelWidgets():
                    if widget is self.root:
                        continue
                    try:
                        widget.close()
                    except Exception as e:
                        logger.error(f"清理子視窗時發生錯誤: {e}\n{traceback.format_exc()}")
        except Exception as e:
            logger.error(f"清理資源時發生錯誤: {e}\n{traceback.format_exc()}")
        finally:
            try:
                root_any = cast(Any, self.root)
                root_any._msm_closing = True
                self.root.close()
                app = QtWidgets.QApplication.instance()
                if app is not None:
                    app.quit()
            except Exception as e:
                logger.error(f"銷毀主視窗時發生錯誤: {e}\n{traceback.format_exc()}")
                sys.exit(0)

    def __init__(self, root: QtWidgets.QWidget):
        self.root = root
        self.mini_sidebar: Any | None = None
        self.active_nav_title: str | None = None
        self.active_nav_key: str | None = None
        self.nav_buttons: dict[str, Any] = {}
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
        self.server_crud = ServerCRUD(servers_root=self.servers_root)
        self.server_startup = ServerStartup(self.server_crud)
        self.server_backup = ServerBackupManager(self.server_crud)
        self.create_widgets()
        WindowManager.setup_main_window(self.root)
        WindowManager.bind_window_state_tracking(self.root)
        if self.settings.is_remember_size_position_enabled() and self.settings.get_main_window_settings().get(
            "maximized", False
        ):
            UIUtils.schedule_debounce(
                self.root, "_post_reveal_zoom_job", 160, lambda: DialogUtils.maximize_window(self.root), owner=self
            )
        TaskCoordinator.preload_java_candidates()
        UIUtils.schedule_debounce(
            self.root, "_startup_tasks_job", 1000, TaskCoordinator.handle_startup_tasks, owner=self
        )
        TaskCoordinator.preload_all_versions()
        TaskCoordinator.load_data_async()

    def _ensure_manage_server_frame(self) -> None:
        """確保管理伺服器頁面已建立並放置於內容堆疊層。"""
        if getattr(self, "manage_server_frame", None) is not None:
            return
        manage_server_frame = ManageServerFrame(
            self.content_frame,
            self.server_crud,
            self.server_startup,
            self.server_backup,
            self.on_server_selected,
            PageRouter.show_create_server,
            set_servers_root=self.set_servers_root,
        )
        self.manage_server_frame = manage_server_frame
        PageRouter.add_page_widget(manage_server_frame)

    def _ensure_mod_management_frame(self) -> None:
        """確保模組管理頁面已建立並放置於內容堆疊層。"""
        if getattr(self, "mod_frame", None) is not None:
            return
        mod_frame = ModManagementFrame(
            self.content_frame, self.server_crud, self.server_startup, self.on_server_selected, self.version_manager
        )
        self.mod_frame = mod_frame
        try:
            frame = mod_frame.get_frame()
            if frame is not None:
                PageRouter.add_page_widget(frame)
        except Exception as e:
            logger.debug(f"ModManagementFrame 加入頁面堆疊失敗: {e}", "MainWindow")

    def setup_window(self) -> None:
        """設定主視窗標題、圖示和現代化樣式"""
        self.root.setWindowTitle("Minecraft 伺服器管理器")
        self.setup_theme_tokens()
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

    def setup_theme_tokens(self) -> None:
        """設定目前主題的色彩 token。"""
        self.colors = {
            "primary": _qt_color(Colors.BUTTON_PRIMARY),
            "secondary": _qt_color(Colors.TEXT_SECONDARY),
            "success": _qt_color(Colors.BUTTON_SUCCESS),
            "warning": _qt_color(Colors.TEXT_WARNING),
            "danger": _qt_color(Colors.BUTTON_DANGER),
            "background": _qt_color(Colors.BG_PRIMARY),
            "surface": _qt_color((Colors.BG_LISTBOX_LIGHT, Colors.BG_LISTBOX_DARK)),
            "text": _qt_color(Colors.TEXT_PRIMARY),
            "text_secondary": _qt_color(Colors.TEXT_SECONDARY),
            "border": _qt_color(Colors.DROPDOWN_BUTTON),
            "menu_bg": Colors.BG_PRIMARY,
        }

    def create_widgets(self) -> None:
        """建立所有介面元件，包含標題和主要內容"""
        self.create_header()
        self.create_main_content()
        PageRouter.show_create_server()

    def create_header(self) -> None:
        """建立原生 Qt 標題列。"""
        self.root.setObjectName("AppRoot")
        self.root.setStyleSheet(NativeQtStyle.app_root)
        root_layout = self.root.layout()
        if root_layout is None:
            root_layout = QtWidgets.QVBoxLayout(self.root)
            _set_layout_margins(root_layout, 0, 0, 0, 0)
            root_layout.setSpacing(0)
        self.root_layout = root_layout

        header_frame = QtWidgets.QFrame(self.root)
        header_frame.setObjectName("MainHeader")
        self.header_frame = header_frame
        header_frame.setFixedHeight(Sizes.APP_HEADER_HEIGHT)
        header_frame.setStyleSheet(NativeQtStyle.main_header)
        header_layout = QtWidgets.QHBoxLayout(header_frame)
        _set_layout_margins(header_layout, 0, 0, 12, 0)
        header_layout.setSpacing(0)

        self.sidebar_toggle_btn = _make_fluent_button("☰", header_frame)
        self.sidebar_toggle_btn.setObjectName("SidebarToggleButton")
        self.sidebar_toggle_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.sidebar_toggle_btn.setFixedSize(36, 33)
        self.sidebar_toggle_btn.setFont(_qt_font(FontManager.get_font(size=FontSize.LARGE, weight="bold")))
        self.sidebar_toggle_btn.clicked.connect(lambda _checked=False: self.toggle_sidebar())
        self.sidebar_toggle_btn.setStyleSheet(NativeQtStyle.sidebar_toggle)
        header_layout.addWidget(self.sidebar_toggle_btn, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        header_layout.addStretch(1)

        title_label = QtWidgets.QLabel("Minecraft 伺服器管理器", header_frame)
        self.title_label = title_label
        title_label.setFont(_qt_font(FontManager.get_font(size=FontSize.HEADING_SMALL, weight="bold")))
        title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_PRIMARY)))
        header_layout.addWidget(title_label, 0, QtCore.Qt.AlignmentFlag.AlignCenter)
        header_layout.addStretch(1)

        right_spacer = QtWidgets.QWidget(header_frame)
        right_spacer.setFixedWidth(36)
        header_layout.addWidget(right_spacer)
        root_layout.addWidget(header_frame)

    def apply_theme_styles(self) -> None:
        """重新套用目前主題到主視窗已存在的原生 Qt 元件。"""
        self.setup_theme_tokens()
        if hasattr(self, "root"):
            self.root.setStyleSheet(NativeQtStyle.app_root)
        if hasattr(self, "header_frame"):
            self.header_frame.setStyleSheet(NativeQtStyle.main_header)
        if hasattr(self, "sidebar_toggle_btn"):
            self.sidebar_toggle_btn.setStyleSheet(NativeQtStyle.sidebar_toggle)
        if hasattr(self, "title_label"):
            self.title_label.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_PRIMARY)))
        if hasattr(self, "main_container"):
            self.main_container.setStyleSheet(NativeQtStyle.main_content)
        if hasattr(self, "nav_container"):
            self.nav_container.setStyleSheet(NativeQtStyle.sidebar)
        if hasattr(self, "content_container"):
            self.content_container.setStyleSheet(NativeQtStyle.content_container)
        if hasattr(self, "content_frame"):
            self.content_frame.setStyleSheet(NativeQtStyle.content_stack)
        if hasattr(self, "sidebar_title"):
            self.sidebar_title.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_PRIMARY)))
        if hasattr(self, "sidebar_footer"):
            self.sidebar_footer.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_TERTIARY)))
        for key, item in getattr(self, "nav_buttons", {}).items():
            button = item.get("button")
            description = item.get("description")
            if button is not None:
                button.setStyleSheet(
                    self._nav_button_style(active=key == self.active_nav_key, mini=not self.sidebar_visible)
                )
            if description is not None:
                description.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_SECONDARY)))
        create_frame = getattr(self, "create_server_frame", None)
        if create_frame is not None and hasattr(create_frame, "apply_theme_styles"):
            create_frame.apply_theme_styles()
        mod_frame = getattr(self, "mod_frame", None)
        if mod_frame is not None and hasattr(mod_frame, "apply_theme_styles"):
            mod_frame.apply_theme_styles()
        manage_frame = getattr(self, "manage_server_frame", None)
        if manage_frame is not None and hasattr(manage_frame, "apply_theme_styles"):
            manage_frame.apply_theme_styles()

    def create_main_content(self) -> None:
        """建立原生 Qt 主內容骨架。"""
        self._nav_full_width = 225
        self._nav_mini_button_width = 36
        self._nav_mini_side_padding = 6
        self._nav_mini_width = self._nav_mini_button_width + self._nav_mini_side_padding * 2
        self._nav_column_padding = 0
        self.sidebar_visible = True

        main_container = QtWidgets.QFrame(self.root)
        main_container.setObjectName("MainContent")
        main_container.setStyleSheet(NativeQtStyle.main_content)
        main_layout = QtWidgets.QHBoxLayout(main_container)
        _set_layout_margins(main_layout, 0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.main_container = main_container

        self.nav_container = QtWidgets.QFrame(main_container)
        self.nav_container.setObjectName("Sidebar")
        self.nav_container.setFixedWidth(self._nav_full_width)
        self.nav_container.setStyleSheet(NativeQtStyle.sidebar)
        main_layout.addWidget(self.nav_container, 0)

        self.content_container = QtWidgets.QFrame(main_container)
        self.content_container.setObjectName("ContentContainer")
        self.content_container.setStyleSheet(NativeQtStyle.content_container)
        content_layout = QtWidgets.QVBoxLayout(self.content_container)
        _set_layout_margins(
            content_layout,
            18,
            14,
            18,
            14,
        )
        content_layout.setSpacing(0)
        self.content_frame = QtWidgets.QStackedWidget(self.content_container)
        self.content_frame.setObjectName("ContentStack")
        self.content_frame.setStyleSheet(NativeQtStyle.content_stack)
        content_layout.addWidget(self.content_frame, 1)
        main_layout.addWidget(self.content_container, 1)

        cast(Any, self.root_layout).addWidget(main_container, 1)
        self.create_sidebar(self.nav_container)

        self.create_server_frame = CreateServerFrame(
            self.content_frame, self.version_manager, self.loader_manager, self.on_server_created, self.server_crud
        )
        PageRouter.add_page_widget(self.create_server_frame)
        self.manage_server_frame = None
        self.mod_frame = None

    def create_sidebar(self, parent) -> None:
        """
        建立單一原生 Qt 側欄，完整/迷你模式共用。

        Args:
            parent: 承載側欄的 Qt 容器。
        """
        self.sidebar = parent
        layout = QtWidgets.QVBoxLayout(parent)
        _set_layout_margins(layout, 12, 11, 12, 9)
        layout.setSpacing(9)
        self.sidebar_layout = layout

        self.sidebar_title = QtWidgets.QLabel("功能選單", parent)
        self.sidebar_title.setFont(_qt_font(FontManager.get_font(size=FontSize.INPUT, weight="bold")))
        self.sidebar_title.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_PRIMARY)))
        layout.addWidget(self.sidebar_title, 0, QtCore.Qt.AlignmentFlag.AlignLeft)

        self.nav_buttons = {}
        self.active_nav_key = None
        self._nav_items = [
            ("🆕", "建立伺服器", "建立新的 Minecraft 伺服器", PageRouter.show_create_server, "create"),
            ("🔧", "管理伺服器", "管理現有的伺服器", PageRouter.show_manage_server, "manage"),
            ("🧩", "模組管理", "管理伺服器模組與資源", PageRouter.show_mod_management, "mods"),
            ("📥", "匯入伺服器", "匯入現有伺服器檔案", self.import_server, "import"),
            ("📁", "開啟資料夾", "開啟伺服器儲存資料夾", self.open_servers_folder, "folder"),
            ("ⓘ", "關於程式", "查看程式資訊", self.show_about, "about"),
        ]
        for emoji, title, desc, command, key in self._nav_items:
            layout.addWidget(self.create_nav_button(parent, emoji, title, desc, command, key))
        layout.addStretch(1)
        self._create_sidebar_footer(parent, mini=False)

    def _create_sidebar_footer(self, parent, *, mini: bool) -> None:
        """在側邊欄底部顯示版本資訊（完整/迷你共用）。"""
        try:
            self.sidebar_footer = QtWidgets.QLabel(f"版本 {APP_VERSION}", parent)
            self.sidebar_footer.setFont(_qt_font(FontManager.get_font(size=FontSize.MEDIUM)))
            self.sidebar_footer.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_TERTIARY)))
            self.sidebar_layout.addWidget(self.sidebar_footer, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
            self.sidebar_footer.setVisible(not mini)
        except Exception as e:
            logger.exception(f"建立側邊欄底部資訊失敗: {e}")

    def create_nav_button(self, parent, icon, title, description, command, key) -> QtWidgets.QFrame:
        """
        建立導航按鈕。

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
        btn_frame = QtWidgets.QFrame(parent)
        btn_frame.setObjectName(f"NavItem_{key}")
        btn_frame.setStyleSheet(NativeQtStyle.nav_item_frame(key))
        btn_layout = QtWidgets.QVBoxLayout(btn_frame)
        _set_layout_margins(btn_layout, 0, 0, 0, 0)
        btn_layout.setSpacing(3)

        btn = _make_fluent_button(f"{icon}  {title}", btn_frame)
        btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        btn.setFont(_qt_font(FontManager.get_font(size=FontSize.HEADING_SMALL, weight="bold")))
        btn.setMinimumHeight(39)
        btn.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        btn.setToolTip(description)
        btn_layout.addWidget(btn)

        desc_label = QtWidgets.QLabel(description, btn_frame)
        desc_label.setFont(_qt_font(FontManager.get_font(size=FontSize.MEDIUM)))
        desc_label.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_SECONDARY)))
        desc_label.setWordWrap(True)
        btn_layout.addWidget(desc_label)
        main_nav_keys = {"create", "manage", "mods"}

        def on_click():
            if key in main_nav_keys:
                PageRouter.set_active_nav_button(key)
            command()

        btn.clicked.connect(lambda _checked=False: on_click())
        self.nav_buttons[key] = {
            "button": btn,
            "description": desc_label,
            "icon": icon,
            "title": title,
            "tooltip": description,
        }
        btn.setStyleSheet(self._nav_button_style(active=False, mini=False))
        return btn_frame

    def _nav_button_style(self, *, active: bool, mini: bool) -> str:
        return NativeQtStyle.nav_button(active=active, mini=mini)

    def toggle_sidebar(self) -> None:
        """切換完整/迷你側欄。"""
        self.sidebar_visible = not bool(getattr(self, "sidebar_visible", True))
        self._apply_sidebar_visibility()

    def _schedule_content_layout_unlock_for_sidebar_toggle(self) -> None:
        """側邊欄切換結束後延遲解鎖內容佈局（debounce）。"""
        delay_ms = max(0, int(getattr(self, "_sidebar_layout_unlock_delay_ms", 70)))
        UIUtils.schedule_debounce(
            self.root, "_sidebar_unlock_job", delay_ms, self._unlock_content_layout_for_sidebar_toggle, owner=self
        )

    def _apply_sidebar_visibility(self) -> None:
        """實際套用完整/迷你側欄狀態。"""
        try:
            mini = not bool(getattr(self, "sidebar_visible", True))
            width = self._nav_mini_width if mini else self._nav_full_width
            self.nav_container.setFixedWidth(width)
            self.sidebar_toggle_btn.setText("☰")
            self.sidebar_title.setVisible(not mini)
            self.sidebar_footer.setVisible(not mini)
            if mini:
                side_padding = getattr(self, "_nav_mini_side_padding", 6)
                _set_layout_margins(self.sidebar_layout, side_padding, 10, side_padding, 8)
                self.sidebar_layout.setSpacing(11)
            else:
                _set_layout_margins(self.sidebar_layout, 12, 11, 12, 9)
                self.sidebar_layout.setSpacing(9)
            for key, item in self.nav_buttons.items():
                btn = item["button"]
                desc = item["description"]
                btn.setText(item["icon"] if mini else f"{item['icon']}  {item['title']}")
                if mini:
                    btn.setFixedWidth(getattr(self, "_nav_mini_button_width", 36))
                else:
                    btn.setMinimumWidth(0)
                    btn.setMaximumWidth(16777215)
                btn.setMinimumHeight(24 if mini else 26)
                btn.setToolTip(item["title"] if mini else item["tooltip"])
                desc.setVisible(not mini)
                btn.setStyleSheet(self._nav_button_style(active=key == self.active_nav_key, mini=mini))
        except Exception as e:
            logger.error(f"切換側邊欄失敗: {e}\n{traceback.format_exc()}")

    def create_mini_sidebar(self) -> None:
        """保留舊呼叫點；迷你側欄由同一套原生 Qt 元件切換。"""
        self.sidebar_visible = False
        self._apply_sidebar_visibility()

    def create_tooltip(self, widget, text) -> None:
        """
        為元件建立工具提示。

        Args:
            widget: 要綁定提示的元件。
            text: 提示文字。
        """
        native = _native_widget(widget)
        if native is not None and hasattr(native, "setToolTip"):
            native.setToolTip(str(text))

    def _lock_content_layout_for_sidebar_toggle(self) -> None:
        """側邊欄切換期間暫時鎖住主內容區，降低 resize 撕裂。"""
        if getattr(self, "_content_layout_locked", False):
            return
        container = getattr(self, "content_container", None)
        content = getattr(self, "content_frame", None)
        if not container or not content:
            return
        try:
            width = int(container.width())
            height = int(container.height())
            if width <= 1 or height <= 1:
                return
            container.setFixedSize(width, height)
            content.setFixedSize(width, height)
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
                container.setMinimumSize(0, 0)
                container.setMaximumSize(16777215, 16777215)
            if content:
                content.setMinimumSize(0, 0)
                content.setMaximumSize(16777215, 16777215)
        except Exception as e:
            logger.debug(f"解除內容區佈局鎖失敗: {e}", "MainWindow")
        finally:
            self._content_layout_locked = False

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
        content = qt.Frame(dialog)
        content.attach(fill="both", expand=True, padx=Spacing.XL, pady=Spacing.XL)
        content_layout = content._ensure_layout("vbox")
        content_layout.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        import_content_width = Sizes.DIALOG_IMPORT_WIDTH - Spacing.XL * 4
        qt.Label(
            content,
            text="選擇匯入方式",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            anchor="center",
        ).attach(
            anchor="center",
            pady=(Spacing.SMALL_PLUS, Spacing.LARGE_MINUS),
        )
        qt.Label(
            content,
            text="請選擇要匯入的伺服器類型:",
            font=FontManager.get_font(size=FontSize.MEDIUM),
            anchor="center",
            wraplength=import_content_width,
        ).attach(
            anchor="center",
            pady=(0, Spacing.XL),
        )
        button_frame = qt.Frame(content, fg_color="transparent", width=import_content_width)
        button_frame.attach(anchor="center")
        options = [("📁 匯入資料夾", "folder"), ("📦 匯入壓縮檔", "archive"), ("❌ 取消", "cancel")]
        for label, key in options:
            font_weight = "bold" if key != "cancel" else "normal"
            btn = qt.Button(
                button_frame,
                text=label,
                command=lambda k=key: self._set_choice(choice, k, dialog),
                font=FontManager.get_font(size=FontSize.NORMAL_PLUS, weight=font_weight),
                height=Sizes.BUTTON_HEIGHT_MEDIUM,
                width=import_content_width,
            )
            btn.attach(fill="x", pady=Spacing.TINY)
        dialog.connect_event("escape_pressed", lambda _e: self._set_choice(choice, "cancel", dialog))
        dialog.exec()
        selected_choice = choice["value"]
        if selected_choice in [None, "cancel"]:
            return
        QtWidgets.QApplication.processEvents()
        self._handle_import_choice(selected_choice)

    def _set_choice(self, choice_dict, value, dialog) -> None:
        """設定選擇並關閉對話框"""
        choice_dict["value"] = value
        with contextlib.suppress(Exception):
            dialog._exists = False
        with contextlib.suppress(Exception):
            dialog.done(0)
        with contextlib.suppress(Exception):
            dialog.deleteLater()

    def _handle_import_choice(self, choice_type) -> None:
        """處理匯入選擇"""
        try:
            if choice_type == "folder":
                path = self._select_server_folder()
            elif choice_type == "archive":
                path = self._select_server_archive()
            else:
                logger.warning(f"未知匯入選擇: {choice_type!r}", "MainWindow")
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
        folder_path = qt.get_existing_directory(
            parent=self.root,
            title="選擇伺服器資料夾",
            initialdir=str(self.server_crud.servers_root),
        )
        if not folder_path:
            return None
        path = Path(folder_path)

        if not ServerDetectionUtils.is_valid_server_folder(path):
            UIUtils.show_error("無效資料夾", "選擇的資料夾不是有效的 Minecraft 伺服器資料夾。", self.root)
            return None
        return path

    def _select_server_archive(self) -> Path | None:
        """選擇伺服器壓縮檔"""
        file_path = qt.get_open_file_name(
            parent=self.root,
            title="選擇伺服器壓縮檔",
            filetypes=[("ZIP 壓縮檔", "*.zip"), ("所有檔案", "*.*")],
            initialdir=str(self.server_crud.servers_root),
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
        result: dict[str, str | None] = {"name": None}
        frame = qt.Frame(dialog)
        frame.attach(fill="both", expand=True, padx=Spacing.XL, pady=Spacing.XL)
        frame_layout = frame._ensure_layout("vbox")
        frame_layout.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        qt.Label(
            frame,
            text="請輸入伺服器名稱:",
            font=FontManager.get_font(size=FontSize.MEDIUM),
            anchor="center",
        ).attach(
            anchor="center",
            pady=(Spacing.SMALL_PLUS, Spacing.LARGE_MINUS),
        )
        entry = qt.Entry(frame, font=FontManager.get_font(size=FontSize.MEDIUM), width=Sizes.INPUT_WIDTH)
        entry.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        entry.attach(anchor="center", pady=(0, Spacing.XL))
        entry.insert(0, default_name)
        entry.setFocus()
        entry.select_range(0, qt.END)
        btn_frame = qt.Frame(frame, fg_color="transparent")
        btn_frame.attach(anchor="center")

        def _ok():
            name = entry.get().strip()
            if not name:
                UIUtils.show_error("輸入錯誤", "請輸入伺服器名稱", dialog)
                return
            root = self.server_crud.servers_root
            if (root / name).exists():
                UIUtils.show_error("名稱重複", f"'{name}' 已存在，請換一個名稱", dialog)
                return
            if self.server_crud.server_exists(name) and (
                not UIUtils.ask_yes_no_cancel(
                    "名稱衝突", f"'{name}' 已存在於設定，是否覆蓋?", dialog, show_cancel=False
                )
            ):
                return
            result["name"] = name
            dialog.destroy()

        def _cancel():
            dialog.destroy()

        qt.Button(
            btn_frame, text="確定", command=_ok, width=Sizes.BUTTON_WIDTH_COMPACT, height=Sizes.BUTTON_HEIGHT_MEDIUM
        ).attach(side="left", padx=(0, Spacing.SMALL_PLUS))
        qt.Button(
            btn_frame, text="取消", command=_cancel, width=Sizes.BUTTON_WIDTH_COMPACT, height=Sizes.BUTTON_HEIGHT_MEDIUM
        ).attach(side="left")
        entry.connect_event("return_pressed", lambda _e: _ok())
        dialog.connect_event("escape_pressed", lambda _e: _cancel())
        dialog.exec()
        return result["name"]

    def _finalize_import(self, source_path: Path, server_name: str) -> None:
        """完成伺服器匯入流程"""
        target_path = self.server_crud.servers_root / server_name
        progress_dialog = DialogUtils.create_toplevel_dialog(
            parent=self.root,
            title="正在匯入伺服器",
            width=Sizes.DIALOG_IMPORT_WIDTH,
            height=Sizes.DIALOG_IMPORT_HEIGHT,
            resizable=False,
            make_modal=True,
            delay_ms=0,
            reveal_after_setup=False,
        )
        content = qt.Frame(progress_dialog)
        content.attach(fill="both", expand=True, padx=Spacing.XL, pady=Spacing.XL)
        content_layout = content._ensure_layout("vbox")
        content_layout.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        import_content_width = Sizes.DIALOG_IMPORT_WIDTH - Spacing.XL * 4
        qt.Label(
            content,
            text=f"正在匯入 {server_name}...",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            anchor="center",
            wraplength=import_content_width,
        ).attach(anchor="center", pady=(Spacing.TINY, Spacing.SMALL_PLUS))
        qt.Label(
            content,
            text="大型匯入可能需要較長時間，請稍候。",
            font=FontManager.get_font(size=FontSize.NORMAL),
            text_color=Colors.TEXT_SECONDARY,
            anchor="center",
            wraplength=import_content_width,
        ).attach(anchor="center", pady=(0, Spacing.SMALL_PLUS))
        progress_bar = qt.ProgressBar(content, mode="determinate", width=import_content_width)
        progress_bar.attach(anchor="center", pady=(0, Spacing.TINY))
        progress_bar.setTextVisible(True)
        progress_bar.set(0)
        progress_dialog.set_close_callback(lambda: False)
        show_window(progress_dialog)

        def _close_progress_dialog() -> None:
            with contextlib.suppress(Exception):
                progress_bar.stop()
            with contextlib.suppress(Exception):
                if progress_dialog.is_alive():
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

                    self.ui_queue.put(_update_progress_ui)

                if source_path.is_file():
                    target_path.mkdir(parents=True, exist_ok=True)
                    PathUtils.safe_extract_zip(source_path, target_path, progress_callback=_on_import_progress)
                    if last_percent < 100:
                        self.ui_queue.put(lambda: progress_bar.set(1.0))
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
                    if not self.server_crud.add_server(server_config):
                        UIUtils.show_error(
                            "匯入失敗", f"伺服器 '{server_name}' 匯入完成，但無法寫入伺服器設定。", self.root
                        )
                        return
                    UIUtils.show_info(
                        "匯入成功",
                        f"伺服器 '{server_name}' 匯入成功!\n\n類型: {server_config.loader_type}\n版本: {server_config.minecraft_version}",
                        self.root,
                    )
                    PageRouter.show_manage_server(auto_select=server_name)

                self.ui_queue.put(_on_import_success)
            except Exception as e:
                logger.error(f"匯入失敗: {e}\n{traceback.format_exc()}", "MainWindow")

                def _on_import_error(msg: str = str(e)) -> None:
                    _close_progress_dialog()
                    UIUtils.show_error("匯入失敗", f"伺服器 '{server_name}' 匯入失敗: {msg}", self.root)

                self.ui_queue.put(_on_import_error)

        TaskUtils.run_async(_import_task)

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
        """顯示原生 Qt 關於對話框。"""
        parent = _native_widget(self.root)
        about_dialog = QtWidgets.QDialog(parent)
        about_dialog.setWindowTitle("關於 Minecraft 伺服器管理器")
        about_dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        about_dialog.resize(
            Sizes.DIALOG_ABOUT_WIDTH,
            Sizes.DIALOG_ABOUT_HEIGHT,
        )
        about_dialog.setStyleSheet(NativeQtStyle.about_dialog)
        IconUtils.set_window_icon(about_dialog, delay_ms=0)

        outer_layout = QtWidgets.QVBoxLayout(about_dialog)
        _set_layout_margins(outer_layout, 24, 24, 24, 18)
        outer_layout.setSpacing(21)
        scroll_area = QtWidgets.QScrollArea(about_dialog)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(scroll_content)
        _set_layout_margins(content_layout, 0, 0, 0, 0)
        content_layout.setSpacing(18)
        scroll_area.setWidget(scroll_content)
        outer_layout.addWidget(scroll_area, 1)

        def add_label(text: str, *, size: int, weight: str = "normal", color: str | None = None) -> QtWidgets.QLabel:
            label = QtWidgets.QLabel(text, scroll_content)
            label.setFont(_qt_font(FontManager.get_font(size=size, weight=weight)))
            label.setWordWrap(True)
            label.setStyleSheet(NativeQtStyle.color_style(color or _qt_color(Colors.TEXT_PRIMARY)))
            content_layout.addWidget(label)
            return label

        title = add_label("🎮 Minecraft 伺服器管理器", size=FontSize.HEADING_XLARGE, weight="bold")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        version = add_label(f"版本 {APP_VERSION}", size=FontSize.LARGE, color=_qt_color(Colors.TEXT_TERTIARY))
        version.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        add_label("👨‍💻 開發資訊", size=FontSize.HEADING_MEDIUM, weight="bold")
        add_label(
            "• 開發者: Minecraft Server Manager Team\n"
            "• 技術棧: Python 3.14+, Qt, PySide6\n"
            "• Java 管理: 自動偵測/下載 Minecraft 官方 JDK\n"
            "• 架構: 模組化設計, 事件驅動\n"
            "• 參考專案: PrismLauncher",
            size=FontSize.NORMAL_PLUS,
        )
        github_url = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
        github_lbl = add_label("GitHub-MinecraftServerManager", size=FontSize.MEDIUM, color=_qt_color(Colors.TEXT_LINK))
        github_lbl.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

        install_open_url_click(github_lbl, github_url)
        add_label("📄 授權條款", size=FontSize.HEADING_LARGE, weight="bold")
        add_label(
            "• 本專案採用 GNU General Public License v3.0 授權條款\n"
            "• 部分設計理念參考 PrismLauncher\n"
            "• 僅供學習和個人使用\n"
            "• 請遵守 Minecraft EULA 和當地法律法規\n\n"
            "特別感謝 PrismLauncher 開發團隊的開源貢獻！",
            size=FontSize.NORMAL_PLUS,
        )
        add_label("🔄 更新設定", size=FontSize.HEADING_LARGE, weight="bold")
        settings = get_settings_manager()
        auto_update_checkbox = QtWidgets.QCheckBox("自動檢查更新", scroll_content)
        auto_update_checkbox.setFont(_qt_font(FontManager.get_font(size=FontSize.NORMAL_PLUS)))
        auto_update_checkbox.setChecked(settings.is_auto_update_enabled())
        content_layout.addWidget(auto_update_checkbox)

        manual_check_btn = _make_fluent_button("檢查更新", scroll_content)
        manual_check_btn.setFont(_qt_font(FontManager.get_font(size=FontSize.NORMAL)))
        manual_check_btn.clicked.connect(lambda _checked=False: TaskCoordinator.manual_check_updates())
        manual_check_btn.setVisible(not settings.is_auto_update_enabled())
        content_layout.addWidget(manual_check_btn, 0, QtCore.Qt.AlignmentFlag.AlignLeft)

        def on_auto_update_toggled(enabled: bool) -> None:
            settings.set_auto_update_enabled(enabled)
            manual_check_btn.setVisible(not enabled)

        auto_update_checkbox.toggled.connect(on_auto_update_toggled)

        prefs_btn = _make_fluent_button("視窗偏好設定", scroll_content)
        prefs_btn.setFont(_qt_font(FontManager.get_font(size=FontSize.NORMAL)))
        prefs_btn.clicked.connect(lambda _checked=False: self._show_window_preferences())
        content_layout.addWidget(prefs_btn, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        content_layout.addStretch(1)

        close_btn = _make_fluent_button("關閉", about_dialog)
        close_btn.setFont(_qt_font(FontManager.get_font(size=FontSize.NORMAL, weight="bold")))
        close_btn.clicked.connect(lambda _checked=False: about_dialog.close())
        outer_layout.addWidget(close_btn, 0, QtCore.Qt.AlignmentFlag.AlignCenter)
        QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key.Key_Escape), about_dialog).activated.connect(
            about_dialog.close
        )
        about_dialog.show()
        about_dialog.raise_()
        about_dialog.activateWindow()

    def _on_auto_update_changed(self, enabled: bool, manual_check_btn) -> None:
        """自動更新設定變更時的回調"""
        settings = get_settings_manager()
        settings.set_auto_update_enabled(enabled)
        if enabled:
            manual_check_btn.hide_from_layout()
        else:
            manual_check_btn.attach(anchor="w", pady=(0, Spacing.SMALL_PLUS))

    def _show_window_preferences(self) -> None:
        """顯示視窗偏好設定對話框"""

        def on_settings_changed():
            """設定變更回調"""
            logger.debug("視窗偏好設定已變更", "MainWindow")
            initialize_ui_theme(self.settings.get_theme_mode())
            self.apply_theme_styles()

        WindowPreferencesDialog(self.root, on_settings_changed)

    def on_server_created(self, server_config: ServerConfig) -> None:
        """
        伺服器建立完成的回調。

        Args:
            server_config: 新建立的伺服器設定。
        """
        self.initialize_server(server_config)

    def initialize_server(self, server_config: ServerConfig) -> None:
        """
        啟動伺服器初始化流程。

        Args:
            server_config: 要初始化的伺服器設定。
        """
        dialog = ServerInitializationDialog(self.root, server_config, self.complete_initialization)
        dialog.start_initialization()

    def on_server_selected(self, server_name: str) -> None:
        """
        伺服器被選中的回調。

        Args:
            server_name: 被選取的伺服器名稱。
        """
        if getattr(self, "_last_logged_server_selection", None) == server_name:
            return
        self._last_logged_server_selection = server_name
        logger.info(f"選中伺服器: {server_name}")

    def complete_initialization(self, server_config: ServerConfig, init_dialog) -> None:
        """
        完成伺服器初始化後的 UI 收尾。

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
        PageRouter.show_manage_server(auto_select=server_config.name)
        UIUtils.show_info(
            "初始化完成",
            f"伺服器 「{server_config.name}」 已成功初始化並可開始使用！\n\n你現在可以進一步調整伺服器設定或直接啟動",
            self.root,
        )


class ServerInitializationDialog:
    """伺服器初始化對話框"""

    def __init__(self, parent: QtWidgets.QWidget, server_config: ServerConfig, completion_callback=None):
        self.parent = parent
        self.server_config = server_config
        self.server_path = Path(server_config.path)
        self.completion_callback = completion_callback
        self.server_process: Any | None = None
        self.server_process_pid: int = 0
        self.done_detected = False
        self.init_dialog: Any | None = None
        self.console_text: qt.TextBox | None = None
        self.progress_label: qt.Label | None = None
        self.close_button: qt.Button | None = None
        self._console_queue: queue.Queue[str] = queue.Queue()
        self._console_pump_job = None
        self._process_output_buffer = ""
        self._stop_sent = False

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
            if not self.init_dialog or not self.init_dialog.is_alive():
                self._console_pump_job = None
                return
            UIUtils.schedule_debounce(self.init_dialog, "_console_pump_job", delay_ms, _tick, owner=self)

        def _tick() -> None:
            self._console_pump_job = None
            try:
                if not self.init_dialog or not self.init_dialog.is_alive():
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
        if not dialog or not dialog.is_alive():
            return
        UIUtils.schedule_debounce(dialog, job_attr, delay_ms, callback, owner=self)

    def _cancel_dialog_jobs(self) -> None:
        """關閉初始化對話框前，集中取消待執行排程。"""
        dialog = self.init_dialog
        if not dialog or not dialog.is_alive():
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
            "_init_close_button_job",
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
        title_label = qt.Label(
            self.init_dialog,
            text=f"正在初始化伺服器: {self.server_config.name}",
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
        )
        title_label.attach(anchor="center", pady=Spacing.SMALL_PLUS)
        info_label = qt.Label(
            self.init_dialog,
            text="伺服器正在首次啟動，請等待初始化完成...\n系統會自動在完成後關閉伺服器",
            font=FontManager.get_font(size=FontSize.LARGE),
        )
        info_label.attach(anchor="center", justify="center", pady=Spacing.TINY)

    def _create_console(self) -> None:
        """建立控制台輸出區域"""
        console_frame = qt.Frame(self.init_dialog)
        console_frame.attach(fill="both", expand=True, padx=Spacing.SMALL_PLUS, pady=Spacing.SMALL_PLUS)
        self.console_text = qt.TextBox(
            console_frame,
            font=FontManager.get_font(family="Consolas", size=FontSize.TINY),
            wrap="none",
            fg_color=(Colors.BG_CONSOLE, Colors.BG_CONSOLE),
            text_color=(Colors.CONSOLE_TEXT, Colors.CONSOLE_TEXT),
        )
        self.console_text.attach(fill="both", expand=True, padx=Spacing.TINY, pady=Spacing.TINY)
        self._start_console_pump()

    def _create_progress_label(self) -> None:
        """建立進度標籤"""
        if not self.init_dialog:
            return
        self.progress_label = qt.Label(
            self.init_dialog, text="狀態: 準備啟動...", font=FontManager.get_font(size=FontSize.INPUT, weight="bold")
        )
        self.progress_label.attach(anchor="center", pady=Spacing.TINY)

    def _create_buttons(self) -> None:
        """建立按鈕區域"""
        if not self.init_dialog:
            return
        button_frame = qt.Frame(self.init_dialog, fg_color="transparent")
        button_frame.attach(fill="x", pady=Spacing.SMALL_PLUS)
        self.close_button = qt.Button(
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
        self.close_button.attach(anchor="center")

    def _setup_timeout(self) -> None:
        """設定超時自動關閉"""
        if self.init_dialog:
            self._schedule_dialog_job("_init_timeout_job", 120000, self._timeout_force_close)

    def _start_server_thread(self) -> None:
        """使用 QProcess 啟動伺服器。"""
        self._run_server()

    def _close_init_server(self) -> None:
        """關閉初始化伺服器。"""
        if self.done_detected:
            if self.init_dialog and self.init_dialog.is_alive():
                self._cancel_dialog_jobs()
                UIUtils.show_info("初始化完成", "伺服器已成功初始化並安全關閉。", parent=self.parent)
                self.init_dialog.destroy()
        else:
            self._terminate_server_process()
            if self.init_dialog and self.init_dialog.is_alive():
                self._cancel_dialog_jobs()
                UIUtils.show_warning("強制關閉", "伺服器初始化未完成，已強制關閉。請檢查伺服器日誌。", self.parent)
                self.init_dialog.destroy()

    def _terminate_server_process(self) -> None:
        """終止伺服器程式"""
        try:
            if self.server_process and self.server_process.state() != QtCore.QProcess.ProcessState.NotRunning:
                self.server_process.terminate()
                if not self.server_process.waitForFinished(5000):
                    self.server_process.kill()
            if self.server_process is not None:
                with contextlib.suppress(Exception):
                    SystemUtils.unregister_managed_process(self.server_path, self.server_process_pid)
        except Exception as e:
            get_logger().bind(component="InitServerDialog").exception(f"終止伺服器程式失敗: {e}")

    def _timeout_force_close(self) -> None:
        """超時強制關閉"""
        if self.init_dialog and self.init_dialog.is_alive() and (not self.done_detected):
            self._close_init_server()

    def _update_console(self, text: str) -> None:
        """更新控制台輸出"""
        try:
            if self.init_dialog and self.init_dialog.is_alive() and self.console_text:
                self.console_text.insert("end", text)
                self.console_text.see("end")
        except Exception:
            logger.exception("更新控制台輸出失敗")

    def _run_server(self) -> None:
        """以 QProcess 啟動伺服器並接上 signal。"""
        try:
            if self.init_dialog:
                self._schedule_dialog_job(
                    "_init_progress_job",
                    0,
                    lambda: (
                        self.progress_label.configure(text="狀態: 正在啟動伺服器...")
                        if self.progress_label and self.progress_label.is_alive()
                        else None
                    ),
                )
            self._enqueue_console("正在啟動 Minecraft 伺服器...\n")
            java_cmd = self._build_java_command()
            process = SubprocessUtils.create_qprocess_checked(
                java_cmd,
                cwd=str(self.server_path),
            )
            self.server_process = process
            process.started.connect(self._on_server_process_started)
            process.readyReadStandardOutput.connect(self._on_server_process_output)
            process.finished.connect(self._on_server_process_finished)
            process.errorOccurred.connect(self._on_server_process_error)
            process.start()
        except Exception as e:
            get_logger().bind(component="ServerInitializationDialog").error(
                f"伺服器啟動失敗: {e}\n{traceback.format_exc()}"
            )
            self._handle_server_error(str(e))

    @QtCore.Slot()
    def _on_server_process_started(self) -> None:
        if self.server_process is None:
            return
        self.server_process_pid = int(self.server_process.processId())
        SystemUtils.register_managed_process(self.server_path, self.server_process_pid)

    @QtCore.Slot()
    def _on_server_process_output(self) -> None:
        if self.server_process is None:
            return
        try:
            chunk = bytes(self.server_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        except Exception as exc:
            logger.exception(f"讀取 QProcess 輸出失敗: {exc}")
            return
        if not chunk:
            return
        self._enqueue_console(chunk)
        self._process_output_buffer += chunk
        lines = self._process_output_buffer.splitlines()
        if self._process_output_buffer and not self._process_output_buffer.endswith(("\n", "\r")):
            self._process_output_buffer = lines.pop() if lines else self._process_output_buffer
        else:
            self._process_output_buffer = ""
        for line in lines:
            self._process_server_output(line)
            if self.done_detected and not self._stop_sent:
                self._handle_server_ready(line)

    @QtCore.Slot(int, QtCore.QProcess.ExitStatus)
    def _on_server_process_finished(self, _exit_code: int, _status: QtCore.QProcess.ExitStatus) -> None:
        if self._process_output_buffer:
            line = self._process_output_buffer
            self._process_output_buffer = ""
            self._process_server_output(line)
            if self.done_detected and not self._stop_sent:
                self._handle_server_ready(line)
        with contextlib.suppress(Exception):
            SystemUtils.unregister_managed_process(self.server_path, self.server_process_pid)
        self._handle_server_completion()

    @QtCore.Slot(QtCore.QProcess.ProcessError)
    def _on_server_process_error(self, _error: QtCore.QProcess.ProcessError) -> None:
        if self.server_process is None:
            return
        self._handle_server_error(self.server_process.errorString())

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
                    if re.search("\\bjavaw?(?:\\.exe)?\\b.*@user_jvm_args\\.txt\\b", line, re.IGNORECASE):
                        cleaned = re.sub("\\s*[%$]\\*?$", "", line.strip())
                        if cleaned.lower().startswith("call "):
                            cleaned = cleaned[5:].lstrip()
                        java_cmd = ServerCommands.split_windows_command_line(cleaned)
                        get_logger().bind(component="ServerInitializationDialog").debug(
                            f"forge_java_command: {java_cmd}"
                        )
                        return java_cmd
        except Exception as e:
            logger.exception(f"提取 Java 命令失敗: {e}")
        return None

    def _process_server_output(self, output: str) -> None:
        """處理伺服器輸出"""
        if self.init_dialog is None or not self.init_dialog.is_alive():
            return
        if "Loading dimension" in output or "Preparing spawn area" in output:
            with contextlib.suppress(Exception):
                self._schedule_dialog_job(
                    "_init_world_prep_job",
                    0,
                    lambda: (
                        self.progress_label.configure(text="狀態: 準備世界...")
                        if self.progress_label and self.progress_label.is_alive()
                        else None
                    ),
                )
        elif "Preparing level" in output:
            with contextlib.suppress(Exception):
                self._schedule_dialog_job(
                    "_init_world_load_job",
                    0,
                    lambda: (
                        self.progress_label.configure(text="狀態: 載入世界...")
                        if self.progress_label and self.progress_label.is_alive()
                        else None
                    ),
                )
        elif "Done (" in output and 'For help, type "help"' in output and (not self.done_detected):
            self.done_detected = True

            def update_close_button() -> None:
                if self.close_button and self.close_button.is_alive():
                    self.close_button.configure(
                        text="關閉伺服器", command=self._close_init_server, fg_color=Colors.BUTTON_SUCCESS
                    )

            self._schedule_dialog_job("_init_close_button_job", 0, update_close_button)

    def _handle_server_ready(self, output: str) -> None:
        """處理伺服器就緒狀態"""
        if "ERROR" in output.upper() or "WARN" in output.upper():
            self._enqueue_console(f"[注意] {output}")

        def update_closing_status():
            if (
                self.init_dialog
                and self.init_dialog.is_alive()
                and self.progress_label
                and self.progress_label.is_alive()
            ):
                self.progress_label.configure(text="狀態: 伺服器完全啟動，正在關閉...")
                self._enqueue_console("\n[系統] 所有模組載入完成，正在關閉伺服器...\n")

        if self.init_dialog:
            self._schedule_dialog_job("_init_closing_job", 0, update_closing_status)
        if self.server_process and self.server_process.state() != QtCore.QProcess.ProcessState.NotRunning:
            self._stop_sent = True
            self.server_process.write(b"stop\n")

    def _handle_server_completion(self) -> None:
        """處理伺服器完成狀態"""
        if self.init_dialog is None:
            return
        if self.done_detected:

            def complete_init():
                if self.init_dialog and self.init_dialog.is_alive():
                    self._update_console("[系統] 伺服器初始化完成！\n")
                    if self.progress_label and self.progress_label.is_alive():
                        self.progress_label.configure(text="狀態: 初始化完成")

            self._schedule_dialog_job("_init_complete_job", 0, complete_init)
            if self.completion_callback:
                self._schedule_dialog_job(
                    "_init_transition_job", 2000, lambda: self.completion_callback(self.server_config, self.init_dialog)
                )
        else:

            def show_error():
                if self.init_dialog and self.init_dialog.is_alive():
                    self._update_console("[系統] 伺服器啟動可能有問題，請檢查輸出\n")
                    if self.progress_label and self.progress_label.is_alive():
                        self.progress_label.configure(text="狀態: 啟動異常")

            self._schedule_dialog_job("_init_error_job", 0, show_error)

    def _handle_server_error(self, err_msg: str) -> None:
        """處理伺服器錯誤"""
        if self.init_dialog is None:
            return

        def show_error():
            if self.init_dialog and self.init_dialog.is_alive():
                self._update_console(f"[錯誤] 啟動失敗: {err_msg}\n")
                if self.progress_label and self.progress_label.is_alive():
                    self.progress_label.configure(text="狀態: 啟動失敗")

        self._schedule_dialog_job("_init_error_job", 0, show_error)


def show_message(title, message, message_type="error"):
    """統一的訊息提示入口，提供 UI 與 logger fallback 機制"""
    import contextlib

    try:
        if message_type == "error":
            UIUtils.show_error(title, message, topmost=True)
        elif message_type == "warning":
            UIUtils.show_warning(title, message, topmost=True)
        else:
            UIUtils.show_info(title, message, topmost=True)
        return True
    except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as ui_error:
        with contextlib.suppress(Exception):
            log_message = f"{title}: {message}"
            if message_type == "error":
                logger.error(log_message)
            elif message_type == "warning":
                logger.warning(log_message)
            else:
                logger.info(log_message)
            logger.debug(f"UI 提示失敗，改用 logger。原因: {ui_error}")
        return False


def _initialize_managers():
    """初始化全域管理器實例"""
    LoaderManager()
    MinecraftVersionManager()


def _setup_ui_environment():
    """設定 UI 環境和主題"""
    settings = get_settings_manager()
    from ..utils import initialize_ui_theme

    initialize_ui_theme(settings.get_theme_mode())


class _ApplicationRoot(QtWidgets.QWidget):
    """主應用程式根視窗。"""

    def closeEvent(self, event) -> None:
        manager = getattr(self, "_msm_manager", None)
        if manager is None or getattr(self, "_msm_closing", False):
            event.accept()
            return
        event.ignore()
        manager.on_closing()


def run_application():
    """初始化應用程式並啟動主視窗"""
    _initialize_managers()
    try:
        settings = get_settings_manager()
        if settings.get("auto_prune_markers_on_startup"):
            PathUtils.auto_prune_markers()
    except Exception as e:
        with contextlib.suppress(Exception):
            record_and_mark(
                e,
                marker_path=PathUtils.get_project_root(),
                reason="auto_prune_markers failed",
                details={"context": "startup"},
            )
        logger.exception("auto_prune_markers failed")
    _setup_ui_environment()

    app = ensure_application()
    root = _ApplicationRoot()
    manager = MainWindow(root)
    root._msm_manager = manager
    root.show()
    app.exec()
