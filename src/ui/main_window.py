"""
主視窗
Minecraft 伺服器管理器的主要使用者介面
本模組定義 Minecraft 伺服器管理器的主視窗
"""

from __future__ import annotations

import queue
import re
import sys
import traceback
from contextlib import suppress
from pathlib import Path
from typing import Any

from qfluentwidgets import (
    BodyLabel,
    FluentWindow,
    LineEdit,
    MessageBoxBase,
    NavigationItemPosition,
    PushButton,
    SubtitleLabel,
    TextEdit,
    Theme,
    TitleLabel,
    setTheme,
)
from qfluentwidgets import FluentIcon as FIF

from ..core import (
    ConfigurationError,
    LoaderManager,
    ServerBackupManager,
    ServerCRUD,
    ServerStartup,
)
from ..models import ServerConfig
from ..utils import (
    Colors,
    ExceptionUtils,
    FontManager,
    FontSize,
    PathUtils,
    QtCore,
    QtGui,
    QtWidgets,
    ServerCommands,
    ServerDetectionUtils,
    ServerPropertiesHelper,
    Sizes,
    SubprocessUtils,
    SystemUtils,
    TaskUtils,
    UIUtils,
    ensure_application,
    get_logger,
    get_settings_manager,
    initialize_ui_theme,
    resolve_color,
    run_on_ui_thread,
)
from . import (
    CreateServerFrame,
    ManageServerFrame,
    ModManagementFrame,
    PageRouter,
    ProgressDialog,
    TaskCoordinator,
)
from .modal_msfluent_window import ModalMSFluentWindow

logger = get_logger().bind(component="MainWindow")


class ImportDialog(MessageBoxBase):
    """匯入伺服器對話框"""

    def __init__(self, parent):
        super().__init__(parent)
        self.custom_title = TitleLabel("匯入伺服器", self.widget)
        self.viewLayout.addWidget(self.custom_title)
        self.buttonGroup.hide()
        self.buttonLayout.setContentsMargins(0, 0, 0, 0)
        self.buttonGroup.setFixedSize(0, 0)
        self.widget.setMinimumWidth(380)

        self.viewLayout.setContentsMargins(24, 24, 24, 24)
        self.viewLayout.setSpacing(12)

        info_label = SubtitleLabel("請選擇要匯入的伺服器類型:", self.widget)
        info_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(info_label)
        self.viewLayout.addSpacing(16)

        self.choice = None

        folder_btn = PushButton("📁 匯入資料夾", self.widget)
        folder_btn.clicked.connect(lambda: self._set_choice("folder"))
        self.viewLayout.addWidget(folder_btn)

        archive_btn = PushButton("📦 匯入壓縮檔", self.widget)
        archive_btn.clicked.connect(lambda: self._set_choice("archive"))
        self.viewLayout.addWidget(archive_btn)

        cancel_btn = PushButton("❌ 取消", self.widget)
        cancel_btn.clicked.connect(lambda: self._set_choice("cancel"))
        self.viewLayout.addWidget(cancel_btn)

    def _set_choice(self, val):
        self.choice = val
        self.accept()


class FluentInputDialog(MessageBoxBase):
    """現代化輸入對話框"""

    def __init__(self, parent, title: str, content: str, default_text: str = ""):
        super().__init__(parent)
        self.custom_title = TitleLabel(title, self.widget)
        self.viewLayout.addWidget(self.custom_title)

        self.viewLayout.setContentsMargins(24, 24, 24, 24)
        self.viewLayout.setSpacing(12)

        info_label = SubtitleLabel(content, self.widget)
        self.viewLayout.addWidget(info_label)
        self.viewLayout.addSpacing(16)

        self.lineEdit = LineEdit(self.widget)
        self.lineEdit.setText(default_text)
        self.lineEdit.setClearButtonEnabled(True)
        self.viewLayout.addWidget(self.lineEdit)

        self.widget.setMinimumWidth(380)
        self.yesButton.setText("確定")
        self.cancelButton.setText("取消")

        self.textValue = ""

    def validate(self) -> bool:
        """
        驗證輸入是否有效，並將輸入值存儲到 self.textValue

        Returns:
            bool: 輸入是否有效
        """
        self.textValue = self.lineEdit.text()
        return True


class MainWindow(FluentWindow):
    """Minecraft 伺服器管理器主視窗類別"""

    def __init__(self):
        super().__init__()
        self.root = self
        self.page_router = PageRouter(self)
        self._console_queue: queue.Queue[Any] = queue.Queue()
        self._startup_update_check_job = None
        self.settings = get_settings_manager()
        self.setup_window()

        theme_mode = self.settings.get_theme_mode()
        if theme_mode == "system":
            setTheme(Theme.AUTO)
        elif theme_mode == "dark":
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.LIGHT)
        QtCore.QTimer.singleShot(0, self._deferred_init)

    def set_servers_root(self, new_root: str | None = None) -> str:
        """
        取得或設定伺服器根目錄

        Args:
            new_root: 要設定的新根目錄；未提供時會提示使用者選擇

        Returns:
            解析後的伺服器根目錄字串
        """
        settings = get_settings_manager()

        def _fail_exit(msg: str):
            """錯誤退出處理"""
            UIUtils.show_message("錯誤", msg, self.root, message_level="error")
            self.root.close()
            sys.exit(0)

        def _prompt_for_directory() -> str:
            """提示選擇目錄"""
            UIUtils.show_message(
                "選擇伺服器資料夾",
                "請選擇要存放所有 Minecraft 伺服器的主資料夾\n(系統會在該資料夾內自動建立 servers 子資料夾)",
                self.root,
                message_level="info",
            )
            folder = QtWidgets.QFileDialog.getExistingDirectory(self.root, "選擇伺服器主資料夾")
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
                UIUtils.show_message("設定錯誤", f"無法寫入設定: {e}", self.root, message_level="error")
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
                        UIUtils.show_message("設定錯誤", f"無法寫入設定: {e}", self.root, message_level="error")
        self.servers_root = str(path_obj)
        return self.servers_root

    def closeEvent(self, e: QtGui.QCloseEvent) -> None:
        """
        主視窗關閉處理，儲存視窗狀態並清理快取

        Args:
            e: 關閉事件
        """
        try:
            get_logger().bind(component="WindowState").debug("儲存視窗狀態...")
            is_maximized = self.isMaximized()
            if not is_maximized:
                w, h = self.width(), self.height()
                x, y = self.x(), self.y()
            else:
                prev = self.settings.get_main_window_settings()
                w, h = prev.get("width", 1350), prev.get("height", 820)
                x, y = prev.get("x"), prev.get("y")
            self.settings.set_main_window_settings(w, h, x, y, is_maximized)

            logger.debug("清理字體快取...")
            FontManager.clear_cache()
            if getattr(self, "server_crud", None) is not None:
                self.server_crud.write_servers_config()

            app = QtWidgets.QApplication.instance()
            if isinstance(app, QtWidgets.QApplication):
                for widget in app.topLevelWidgets():
                    if widget is not self:
                        with suppress(Exception):
                            widget.close()
        except Exception as ex:
            logger.error(f"清理資源時發生錯誤: {ex}\n{traceback.format_exc()}")
        super().closeEvent(e)

    def setup_window(self) -> None:
        """設定主視窗標題、圖示和現代化樣式"""
        self.setWindowTitle("Minecraft 伺服器管理器")

        width = Sizes.DIALOG_LARGE_WIDTH
        height = Sizes.DIALOG_LARGE_HEIGHT

        if hasattr(self, "settings") and self.settings.is_remember_size_position_enabled():
            win_settings = self.settings.get_main_window_settings()
            width = win_settings.get("width", width)
            height = win_settings.get("height", height)

        self.resize(width, height)

        if hasattr(self, "settings") and self.settings.is_remember_size_position_enabled():
            win_settings = self.settings.get_main_window_settings()
            x = win_settings.get("x")
            y = win_settings.get("y")
            if x is not None and y is not None:
                self.move(x, y)
            elif hasattr(self, "settings") and self.settings.is_auto_center_enabled():
                self._center_window()
        elif hasattr(self, "settings") and self.settings.is_auto_center_enabled():
            self._center_window()

        self.setup_theme_tokens()

    def setup_theme_tokens(self) -> None:
        """設定目前主題的色彩 token"""
        self.colors = {
            "primary": resolve_color(Colors.BUTTON_PRIMARY),
            "secondary": resolve_color(Colors.TEXT_SECONDARY),
            "success": resolve_color(Colors.BUTTON_SUCCESS),
            "warning": resolve_color(Colors.TEXT_WARNING),
            "danger": resolve_color(Colors.BUTTON_DANGER),
            "background": resolve_color(Colors.BG_PRIMARY),
            "surface": resolve_color((Colors.BG_LISTBOX_LIGHT, Colors.BG_LISTBOX_DARK)),
            "text": resolve_color(Colors.TEXT_PRIMARY),
            "text_secondary": resolve_color(Colors.TEXT_SECONDARY),
            "border": resolve_color(Colors.DROPDOWN_BUTTON),
            "menu_bg": Colors.BG_PRIMARY,
        }

    def create_widgets(self) -> None:
        """建立所有介面元件，包含標題和主要內容"""
        self.create_server_frame = CreateServerFrame(
            self, self.loader_manager, self.on_server_created, self.server_crud
        )
        self.create_server_frame.setObjectName("CreateServerInterface")
        self.manage_server_frame = None
        self.mod_frame = None
        self._ensure_manage_server_frame()
        self._ensure_mod_management_frame()

        from .about_preferences_frame import AboutPreferencesFrame

        self.about_prefs_frame = AboutPreferencesFrame(self)
        self.about_prefs_frame.setObjectName("AboutPreferencesInterface")

        self.addSubInterface(self.create_server_frame, FIF.ADD, "建立伺服器")
        self.addSubInterface(self.manage_server_frame, FIF.SETTING, "管理伺服器")
        if self.mod_frame is not None:
            self.addSubInterface(self.mod_frame, FIF.APPLICATION, "模組管理")

        self.navigationInterface.addItem("import", FIF.DOWNLOAD, "匯入伺服器", onClick=self.import_server)
        self.navigationInterface.addItem("folder", FIF.FOLDER, "開啟資料夾", onClick=self.open_servers_folder)
        self.addSubInterface(self.about_prefs_frame, FIF.INFO, "關於與設定", position=NavigationItemPosition.BOTTOM)

        self.page_router.show_create_server()

    def import_server(self) -> None:
        """
        匯入伺服器（資料夾或壓縮檔）
        統一入口匯入伺服器，支援資料夾和壓縮檔
        """
        dialog = ImportDialog(self.root)
        dialog.exec()

        selected_choice = dialog.choice
        if selected_choice in [None, "cancel"]:
            return
        QtWidgets.QApplication.processEvents()
        self._handle_import_choice(selected_choice)

    def open_servers_folder(self) -> None:
        """開啟伺服器資料夾"""
        folder = self.servers_root
        folder_path = Path(folder)
        if not folder_path.exists():
            folder_path.mkdir(parents=True, exist_ok=True)
        try:
            UIUtils.open_external(str(folder_path))
        except Exception as e:
            logger.error(f"無法開啟路徑: {e}\n{traceback.format_exc()}")
            UIUtils.show_message("錯誤", f"無法開啟路徑: {e}", self.root, message_level="error")

    def on_server_created(self, server_config: ServerConfig) -> None:
        """
        伺服器建立完成的回調

        Args:
            server_config: 新建立的伺服器設定
        """
        self.initialize_server(server_config)

    def initialize_server(self, server_config: ServerConfig) -> None:
        """
        啟動伺服器初始化流程

        Args:
            server_config: 要初始化的伺服器設定
        """
        dialog = ServerInitializationDialog(self.root, server_config, self.complete_initialization)
        dialog.start_initialization()

    def on_server_selected(self, server_name: str) -> None:
        """
        伺服器被選中的回調

        Args:
            server_name: 被選取的伺服器名稱
        """
        if getattr(self, "_last_logged_server_selection", None) == server_name:
            return
        self._last_logged_server_selection = server_name
        logger.info(f"選中伺服器: {server_name}")

    def complete_initialization(self, server_config: ServerConfig, init_dialog) -> None:
        """
        完成伺服器初始化後的 UI 收尾

        Args:
            server_config: 已初始化的伺服器設定
            init_dialog: 初始化對話框實例
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
        self.page_router.show_manage_server(auto_select=server_config.name)
        UIUtils.show_message(
            "初始化完成",
            f"伺服器 「{server_config.name}」 已成功初始化並可開始使用！\n\n你現在可以進一步調整伺服器設定或直接啟動",
            self.root,
            message_level="info",
        )

    def _deferred_init(self) -> None:
        """延遲初始化：在事件循環啟動後執行需要使用者互動的步驟"""
        try:
            self.servers_root = self.set_servers_root()
            if not self.servers_root:
                return
            self.loader_manager = LoaderManager()
            self.server_crud = ServerCRUD(servers_root=self.servers_root)
            self.server_startup = ServerStartup(self.server_crud)
            self.server_backup = ServerBackupManager(self.server_crud)

            self.create_widgets()
            if self.settings.is_remember_size_position_enabled() and self.settings.get_main_window_settings().get(
                "maximized", False
            ):
                UIUtils.schedule_debounce(
                    self.root, "_post_reveal_zoom_job", 160, lambda: self.root.showMaximized(), owner=self
                )
            self.task_coordinator = TaskCoordinator(self)
            self.task_coordinator.preload_java_candidates()
            UIUtils.schedule_debounce(
                self.root, "_startup_tasks_job", 1000, self.task_coordinator.handle_startup_tasks, owner=self
            )
            self.task_coordinator.preload_all_versions()
            self.task_coordinator.load_data_async()
        except Exception as e:
            logger.exception(f"延遲初始化失敗: {e}")
            UIUtils.show_message("啟動錯誤", f"初始化失敗: {e}", self.root, message_level="error")

    def _ensure_manage_server_frame(self) -> None:
        """確保管理伺服器頁面已建立並放置於內容堆疊層"""
        if getattr(self, "manage_server_frame", None) is not None:
            return
        manage_server_frame = ManageServerFrame(
            self,
            self.server_crud,
            self.server_startup,
            self.server_backup,
            self.on_server_selected,
            self.page_router.show_create_server,
            set_servers_root=self.set_servers_root,
        )
        self.manage_server_frame = manage_server_frame
        manage_server_frame.setObjectName("ManageServerInterface")

    def _ensure_mod_management_frame(self) -> None:
        """確保模組管理頁面已建立並放置於內容堆疊層"""
        if getattr(self, "mod_frame", None) is not None:
            return
        mod_controller = ModManagementFrame(self, self.server_crud, self.on_server_selected, self.loader_manager)
        self.mod_frame_controller = mod_controller
        try:
            frame = mod_controller.get_frame()
            if frame is not None:
                frame.setObjectName("ModManagementInterface")
                self.mod_frame = frame
        except Exception as e:
            logger.debug(f"ModManagementFrame 加入頁面堆疊失敗: {e}")

    def _center_window(self) -> None:
        """將視窗置中於螢幕"""
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)

    def _handle_import_choice(self, choice_type) -> None:
        """處理匯入選擇"""
        try:
            if choice_type == "folder":
                path = self._select_server_folder()
            elif choice_type == "archive":
                path = self._select_server_archive()
            else:
                logger.warning(f"未知匯入選擇: {choice_type!r}")
                return
            if path:
                server_name = self._prompt_server_name(path.stem if path.is_file() else path.name)
                if server_name:
                    self._finalize_import(path, server_name)
        except Exception as e:
            logger.error(f"匯入錯誤: {e}\n{traceback.format_exc()}")
            UIUtils.show_message("匯入錯誤", str(e), self.root, message_level="error")

    def _select_server_folder(self) -> Path | None:
        """選擇伺服器資料夾"""
        folder_path = QtWidgets.QFileDialog.getExistingDirectory(
            self.root,
            "選擇伺服器資料夾",
            str(self.server_crud.servers_root),
        )
        if not folder_path:
            return None
        path = Path(folder_path)

        if not ServerDetectionUtils.is_valid_server_folder(path):
            UIUtils.show_message(
                "無效資料夾", "選擇的資料夾不是有效的 Minecraft 伺服器資料夾", self.root, message_level="error"
            )
            return None
        return path

    def _select_server_archive(self) -> Path | None:
        """選擇伺服器壓縮檔"""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            parent=self.root,
            caption="選擇伺服器壓縮檔",
            dir=str(self.server_crud.servers_root),
            filter="ZIP 壓縮檔 (*.zip);;所有檔案 (*.*)",
        )
        if not file_path:
            return None
        path = Path(file_path)
        if path.suffix.lower() != ".zip":
            UIUtils.show_message(
                "不支援的格式", f"目前僅支援 ZIP 格式\n選擇的檔案: {path.suffix}", self.root, message_level="error"
            )
            return None
        return path

    def _prompt_server_name(self, default_name: str) -> str | None:
        """提示輸入伺服器名稱"""
        while True:
            dialog = FluentInputDialog(self.root, "輸入伺服器名稱", "請輸入伺服器名稱:", default_name)
            if not dialog.exec():
                return None
            name = dialog.textValue.strip()
            if not name:
                UIUtils.show_message("輸入錯誤", "請輸入伺服器名稱", self.root, message_level="error")
                continue
            root_path = self.server_crud.servers_root
            if (root_path / name).exists():
                UIUtils.show_message("名稱重複", f"'{name}' 已存在，請換一個名稱", self.root, message_level="error")
                continue
            if self.server_crud.server_exists(name) and (
                not UIUtils.ask_yes_no_cancel(
                    "名稱衝突", f"'{name}' 已存在於設定，是否覆蓋?", self.root, show_cancel=False
                )
            ):
                continue
            return name

    def _finalize_import(self, source_path: Path, server_name: str) -> None:
        """完成伺服器匯入流程"""
        target_path = self.server_crud.servers_root / server_name

        progress_dialog = ProgressDialog(self.root, f"正在匯入 {server_name}...", show_cancel=False)
        progress_dialog.status_label.setText("大型匯入可能需要較長時間，請稍候")
        progress_dialog.show()

        def _close_progress_dialog() -> None:
            with suppress(Exception):
                progress_dialog.close()
                progress_dialog.deleteLater()

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
                        with suppress(Exception):
                            progress_dialog.progress.setValue(progress_value)

                    run_on_ui_thread(_update_progress_ui)

                if source_path.is_file():
                    target_path.mkdir(parents=True, exist_ok=True)
                    PathUtils.safe_extract_zip(source_path, target_path, progress_callback=_on_import_progress)
                    if last_percent < 100:
                        run_on_ui_thread(lambda: progress_dialog.progress.setValue(100))
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
                        run_on_ui_thread(lambda: progress_dialog.progress.setValue(100))
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
                        UIUtils.show_message(
                            "匯入失敗",
                            f"伺服器 '{server_name}' 匯入完成，但無法寫入伺服器設定",
                            self.root,
                            message_level="error",
                        )
                        return
                    UIUtils.show_message(
                        "匯入成功",
                        f"伺服器 '{server_name}' 匯入成功!\n\n類型: {server_config.loader_type}\n版本: {server_config.minecraft_version}",
                        self.root,
                        message_level="info",
                    )
                    self.page_router.show_manage_server(auto_select=server_name)

                run_on_ui_thread(_on_import_success)
            except Exception as e:
                logger.error(f"匯入失敗: {e}\n{traceback.format_exc()}")

                def _on_import_error(msg: str = str(e)) -> None:
                    _close_progress_dialog()
                    UIUtils.show_message(
                        "匯入失敗", f"伺服器 '{server_name}' 匯入失敗: {msg}", self.root, message_level="error"
                    )

                run_on_ui_thread(_on_import_error)

        TaskUtils.run_async(_import_task)


class ServerInitializationDialog(ModalMSFluentWindow):
    """伺服器初始化對話框"""

    def __init__(self, parent: QtWidgets.QWidget, server_config: ServerConfig, completion_callback=None):
        super().__init__(parent, is_modal=True, show_buttons=False)
        self.parent_widget = parent
        self.server_config = server_config
        self.server_path = Path(server_config.path)
        self.completion_callback = completion_callback
        self.server_process: Any | None = None
        self.server_process_pid: int = 0
        self.done_detected = False

        self.setWindowTitle(f"初始化伺服器 - {self.server_config.name}")
        self.setMinimumSize(600, 450)

        self.title_label = TitleLabel(f"正在初始化伺服器: {self.server_config.name}", self.widget)
        self.title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(self.title_label)

        self.info_label = SubtitleLabel(
            "伺服器正在首次啟動，請等待初始化完成...\n系統會自動在完成後關閉伺服器", self.widget
        )
        self.info_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(self.info_label)

        self.console_text = TextEdit(self.widget)
        self.console_text.setReadOnly(True)
        self.console_text.setFont(FontManager.get_font(family="Consolas", size=FontSize.TINY))
        self.console_text.setStyleSheet(
            f"QTextEdit {{ background-color: {Colors.BG_CONSOLE}; color: {Colors.CONSOLE_TEXT}; border: 1px solid #333333; }}"
        )
        self.viewLayout.addWidget(self.console_text, 1)

        self.progress_label = BodyLabel("狀態: 準備啟動...", self.widget)
        self.progress_label.setFont(FontManager.get_font(size=FontSize.INPUT, weight="bold"))
        self.progress_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(self.progress_label)

        self.close_button = PushButton("取消初始化", self.widget)
        self.close_button.setStyleSheet(f"PushButton {{ color: {resolve_color(Colors.TEXT_ERROR)}; }}")
        self.close_button.clicked.connect(self._close_init_server)

        self.buttonLayout.addWidget(self.close_button)
        self.buttonGroup.show()

        self._console_queue: queue.Queue[str] = queue.Queue()
        self._console_timer = QtCore.QTimer(self)
        self._console_timer.timeout.connect(self._tick_console)
        self._process_output_buffer = ""
        self._stop_sent = False

        self._timeout_timer = QtCore.QTimer(self)
        self._timeout_timer.timeout.connect(self._timeout_force_close)

    def start_initialization(self) -> None:
        """啟動初始化對話框流程"""
        self._console_timer.start(50)
        self._timeout_timer.start(120000)
        self.show()
        self._start_server_thread()

    def _enqueue_console(self, text: str) -> None:
        try:
            self._console_queue.put_nowait(text)
        except Exception as e:
            get_logger().bind(component="InitServerDialog").exception(f"加入 console queue 失敗: {e}")

    def _tick_console(self) -> None:
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

    def _start_server_thread(self) -> None:
        """使用 QProcess 啟動伺服器"""
        self._run_server()

    def _close_init_server(self) -> None:
        """關閉初始化伺服器"""
        if self.done_detected:
            self._console_timer.stop()
            self._timeout_timer.stop()
            UIUtils.show_message(
                "初始化完成", "伺服器已成功初始化並安全關閉", parent=self.parent_widget, message_level="info"
            )
            self.reject()
        else:
            self._terminate_server_process()
            self._console_timer.stop()
            self._timeout_timer.stop()
            UIUtils.show_message(
                "強制關閉",
                "伺服器初始化未完成，已強制關閉請檢查伺服器日誌",
                self.parent_widget,
                message_level="warning",
            )
            self.reject()

    def _terminate_server_process(self) -> None:
        """終止伺服器程式"""
        try:
            if self.server_process and self.server_process.state() != QtCore.QProcess.ProcessState.NotRunning:
                self.server_process.terminate()
                if not self.server_process.waitForFinished(5000):
                    self.server_process.kill()
            if self.server_process is not None:
                with suppress(Exception):
                    SystemUtils.unregister_managed_process(self.server_path, self.server_process_pid)
        except Exception as e:
            get_logger().bind(component="InitServerDialog").exception(f"終止伺服器程式失敗: {e}")

    def _timeout_force_close(self) -> None:
        """超時強制關閉"""
        if not self.done_detected:
            self._close_init_server()

    def _update_console(self, text: str) -> None:
        """更新控制台輸出"""
        try:
            if self.console_text:
                self.console_text.insertPlainText(text)
                scrollbar = self.console_text.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
        except Exception:
            logger.exception("更新控制台輸出失敗")

    def _run_server(self) -> None:
        """以 QProcess 啟動伺服器並接上 signal"""
        try:
            self.progress_label.setText("狀態: 正在啟動伺服器...")
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
        with suppress(Exception):
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
        if not self.isVisible():
            return
        if "Loading dimension" in output or "Preparing spawn area" in output:
            with suppress(Exception):
                self.progress_label.setText("狀態: 準備世界...")
        elif "Preparing level" in output:
            with suppress(Exception):
                self.progress_label.setText("狀態: 載入世界...")
        elif "Done (" in output and 'For help, type "help"' in output and (not self.done_detected):
            self.done_detected = True
            if self.close_button:
                self.close_button.setText("關閉伺服器")
                self.close_button.setStyleSheet(f"color: {resolve_color(Colors.BUTTON_SUCCESS)};")

    def _handle_server_ready(self, output: str) -> None:
        """處理伺服器就緒狀態"""
        if "ERROR" in output.upper() or "WARN" in output.upper():
            self._enqueue_console(f"[注意] {output}")

        def update_closing_status():
            if self.progress_label:
                self.progress_label.setText("狀態: 伺服器完全啟動，正在關閉...")
                self._enqueue_console("\n[系統] 所有模組載入完成，正在關閉伺服器...\n")

        update_closing_status()
        if self.server_process and self.server_process.state() != QtCore.QProcess.ProcessState.NotRunning:
            self._stop_sent = True
            self.server_process.write(b"stop\n")

    def _handle_server_completion(self) -> None:
        """處理伺服器完成狀態"""
        if not self.isVisible():
            return
        if self.done_detected:
            self._update_console("[系統] 伺服器初始化完成！\n")
            if self.progress_label:
                self.progress_label.setText("狀態: 初始化完成")

            if self.completion_callback:
                QtCore.QTimer.singleShot(2000, lambda: self.completion_callback(self.server_config, self))
        else:
            self._update_console("[系統] 伺服器啟動可能有問題，請檢查輸出\n")
            if self.progress_label:
                self.progress_label.setText("狀態: 啟動異常")

    def _handle_server_error(self, err_msg: str) -> None:
        """處理伺服器錯誤"""
        if not self.isVisible():
            return

        self._update_console(f"[錯誤] 啟動失敗: {err_msg}\n")
        if self.progress_label:
            self.progress_label.setText("狀態: 啟動失敗")


def run_application():
    """初始化應用程式並啟動主視窗"""
    LoaderManager()
    logger.info("啟動 Minecraft 伺服器管理器...")
    try:
        settings = get_settings_manager()
        if settings.get("auto_prune_markers_on_startup"):
            PathUtils.auto_prune_markers()
    except Exception as e:
        with suppress(Exception):
            ExceptionUtils.record_and_mark(
                e,
                marker_path=PathUtils.get_project_root(),
                reason="auto_prune_markers failed",
                details={"context": "startup"},
            )
        logger.exception("auto_prune_markers failed")
    app = ensure_application()
    settings = get_settings_manager()
    initialize_ui_theme(settings.get_theme_mode())

    logger.info("啟動主視窗...")
    manager = MainWindow()
    logger.info("主視窗啟動完成，進入事件循環...")
    manager.show()
    app.exec()
