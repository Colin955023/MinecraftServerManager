"""
主視窗
Minecraft 伺服器管理器的主要使用者介面
本模組定義 Minecraft 伺服器管理器的主視窗
"""

from __future__ import annotations

import sys
import traceback
from contextlib import suppress
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentWindow,
    LineEdit,
    NavigationItemPosition,
    PushButton,
    SubtitleLabel,
    TextEdit,
    Theme,
    TitleLabel,
    setTheme,
)
from qfluentwidgets import FluentIcon as FIF

from src.core import (
    LoaderManager,
    LoaderManagerRulesAdapter,
    ModPlanning,
    ModrinthPlanningAdapter,
    ServerBackupManager,
    ServerCRUD,
    ServerImportService,
    ServerInspector,
    ServerPropertiesStore,
    ServerRuntime,
)
from src.models import ServerConfig
from src.ui import (
    AboutPreferencesFrame,
    CreateServerFrame,
    ManageServerFrame,
    ModalMSFluentWindow,
    ModManagementFrame,
    PageRouter,
    ProgressDialog,
    TaskCoordinator,
)
from src.utils import (
    Colors,
    ConfigurationError,
    FontManager,
    FontSize,
    Sizes,
    StatusPushButton,
    UIUtils,
    UIWorkScope,
    WorkOutcome,
    center_window,
    ensure_application,
    get_logger,
    get_settings_manager,
    initialize_ui_theme,
    run_on_ui_thread,
)

logger = get_logger().bind(component="MainWindow")


class ImportDialog(ModalMSFluentWindow):
    """匯入伺服器對話框"""

    def __init__(self, parent):
        super().__init__(parent, is_modal=True, show_buttons=False)
        self.setWindowTitle("匯入伺服器")
        self.setFixedSize(520, 340)

        if hasattr(self, "titleBar"):
            if hasattr(self.titleBar, "minBtn"):
                self.titleBar.minBtn.hide()
            if hasattr(self.titleBar, "maxBtn"):
                self.titleBar.maxBtn.hide()

        self.choice = None

        title_lbl = TitleLabel("匯入伺服器", self.widget)
        title_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(title_lbl)

        info_label = SubtitleLabel("請選擇要匯入的伺服器類型:", self.widget)
        info_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(info_label)
        self.viewLayout.addStretch(1)

        folder_btn = PushButton("📁 匯入資料夾", self.widget)
        folder_btn.clicked.connect(lambda _checked=False: self._set_choice("folder"))
        self.viewLayout.addWidget(folder_btn)

        archive_btn = PushButton("📦 匯入壓縮檔", self.widget)
        archive_btn.clicked.connect(lambda _checked=False: self._set_choice("archive"))
        self.viewLayout.addWidget(archive_btn)

        cancel_btn = PushButton("❌ 取消", self.widget)
        cancel_btn.clicked.connect(lambda _checked=False: self._set_choice("cancel"))
        self.viewLayout.addWidget(cancel_btn)

    def _set_choice(self, val):
        self.choice = val
        self.accept()


class FluentInputDialog(ModalMSFluentWindow):
    """現代化輸入對話框"""

    def __init__(self, parent, title: str, content: str, default_text: str = ""):
        super().__init__(parent, is_modal=True, show_buttons=False)
        self.setWindowTitle(title)
        self.setFixedSize(520, 300)

        if hasattr(self, "titleBar"):
            if hasattr(self.titleBar, "minBtn"):
                self.titleBar.minBtn.hide()
            if hasattr(self.titleBar, "maxBtn"):
                self.titleBar.maxBtn.hide()

        title_lbl = TitleLabel(title, self.widget)
        title_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(title_lbl)
        info_label = SubtitleLabel(content, self.widget)
        info_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(info_label)

        self.lineEdit = LineEdit(self.widget)
        self.lineEdit.setText(default_text)
        self.lineEdit.setClearButtonEnabled(True)
        self.viewLayout.addWidget(self.lineEdit)
        self.viewLayout.addStretch(1)

        self.yesButton.setText("確定")
        self.yesButton.clicked.connect(self._accept_input)
        self.cancelButton.setText("取消")
        self.cancelButton.clicked.connect(self.reject)
        self.buttonGroup.show()

        self.textValue = ""

    def _accept_input(self) -> None:
        self.validate()
        self.accept()

    def validate(self) -> bool:
        """
        驗證輸入是否有效，並將輸入值儲存到 self.textValue

        Returns:
            輸入是否有效
        """
        self.textValue = self.lineEdit.text()
        return True


class MainWindow(FluentWindow):
    """Minecraft 伺服器管理器主視窗類別"""

    def __init__(self):
        super().__init__()
        self.root = self
        self.scope = UIWorkScope(self)
        self.setProperty("_primary_window", True)
        self.page_router = PageRouter(self)
        self.settings = get_settings_manager()
        self.setup_window()

        theme_mode = self.settings.get_theme_mode()
        if theme_mode == "system":
            setTheme(Theme.AUTO)
        elif theme_mode == "dark":
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.LIGHT)

        self.stackedWidget.currentChanged.connect(self._on_page_changed)
        self._widgets_initialized = False

        stored_root = self.settings.get_servers_root()
        if stored_root:
            try:
                path_obj = self.settings.get_validated_servers_root_path(create=True)
                self._compose_services(str(path_obj))
                self.create_widgets()
                self._widgets_initialized = True
            except Exception as e:
                logger.warning(f"啟動時預先建立介面未完成，將延後至 deferred_init 處理: {e}\n{traceback.format_exc()}")

        QtCore.QTimer.singleShot(0, self._deferred_init)

    def _compose_services(self, servers_root: str) -> None:
        """建立 MainWindow 唯一使用的 production service graph

        Args:
            servers_root: 已驗證的伺服器根目錄
        """
        server_crud = ServerCRUD(servers_root=servers_root)
        loader_manager = LoaderManager()
        server_inspector = ServerInspector()
        mod_planning = ModPlanning(
            ModrinthPlanningAdapter(),
            LoaderManagerRulesAdapter(loader_manager),
        )
        server_import = ServerImportService(server_crud, server_inspector)
        server_properties = ServerPropertiesStore(server_crud)
        server_runtime = ServerRuntime(server_crud, server_inspector=server_inspector)
        server_backup = ServerBackupManager(server_crud, server_runtime=server_runtime)

        self.servers_root = servers_root
        self.loader_manager = loader_manager
        self.mod_planning = mod_planning
        self.server_crud = server_crud
        self.server_inspector = server_inspector
        self.server_import = server_import
        self.server_properties = server_properties
        self.server_runtime = server_runtime
        self.server_backup = server_backup

    def _on_page_changed(self, index: int) -> None:
        widget = self.stackedWidget.widget(index)
        if widget is getattr(self, "mod_frame", None) and getattr(self, "mod_frame_controller", None):
            QtCore.QTimer.singleShot(60, self.mod_frame_controller.load_servers)
        elif widget is getattr(self, "manage_server_frame", None) and self.manage_server_frame:
            QtCore.QTimer.singleShot(60, self.manage_server_frame.refresh_servers)

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

        def _prompt_for_directory() -> str | None:
            """提示選擇目錄"""
            UIUtils.show_message(
                "選擇伺服器資料夾",
                "請選擇要存放所有 Minecraft 伺服器的主資料夾\n(系統會在該資料夾內自動建立 servers 子資料夾)",
                self.root,
                message_level="info",
            )
            folder = UIUtils.get_existing_directory(self.root, "選擇伺服器主資料夾")
            if not folder:
                should_exit = UIUtils.ask_yes_no_cancel(
                    "結束程式", "未選擇資料夾，是否要結束程式？", self.root, show_cancel=False
                )
                if should_exit is not True:
                    UIUtils.show_message(
                        "需要伺服器資料夾", "未選擇伺服器資料夾，程式將關閉", self.root, message_level="warning"
                    )
                self.root.close()
                return None
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
                base_dir = _prompt_for_directory()
                if not base_dir:
                    return ""
                while base_dir:
                    try:
                        settings.set_servers_root(base_dir)
                        path_obj = settings.get_validated_servers_root_path(create=True)
                        break
                    except Exception as e:
                        logger.error(f"無法寫入設定: {e}\n{traceback.format_exc()}")
                        UIUtils.show_message("設定錯誤", f"無法寫入設定: {e}", self.root, message_level="error")
                        return ""
        self.servers_root = str(path_obj)
        return self.servers_root

    def closeEvent(self, e: QtGui.QCloseEvent) -> None:
        """
        主視窗關閉處理，儲存視窗狀態並清理快取

        Args:
            e: 關閉事件
        """
        try:
            is_maximized = self.isMaximized()
            if not is_maximized:
                w, h = self.width(), self.height()
                x, y = self.x(), self.y()
            else:
                prev = self.settings.get_main_window_settings()
                w, h = prev.get("width", 1350), prev.get("height", 820)
                x, y = prev.get("x"), prev.get("y")
            self.settings.set_main_window_settings(w, h, x, y, is_maximized)

            FontManager.clear_cache()
            if getattr(self, "server_crud", None) is not None:
                self.server_crud.write_servers_config()
            if getattr(self, "server_runtime", None) is not None:
                self.server_runtime.shutdown()

            if hasattr(self, "manage_server_frame") and self.manage_server_frame:
                with suppress(Exception):
                    if hasattr(self.manage_server_frame, "_auto_refresh_timer"):
                        self.manage_server_frame._auto_refresh_timer.stop()

            if hasattr(self, "mod_frame_controller") and self.mod_frame_controller:
                with suppress(Exception):
                    if hasattr(self.mod_frame_controller, "_ui_queue_timer"):
                        self.mod_frame_controller._ui_queue_timer.stop()

            if hasattr(self, "scope") and self.scope:
                self.scope.drain(timeout_ms=1000)

            app = QtWidgets.QApplication.instance()
            if isinstance(app, QtWidgets.QApplication):
                for widget in app.topLevelWidgets():
                    if widget is not self:
                        with suppress(Exception):
                            widget.close()
                app.quit()
        except Exception as ex:
            logger.error(f"清理資源時發生錯誤: {ex}\n{traceback.format_exc()}")
        super().closeEvent(e)

    def _force_full_window_repaint(self) -> None:
        """強制整個主視窗及其子頁面重新排版與重繪，防止最大化、還原或失焦時的畫面撕裂與殘影"""
        win_layout = self.layout()
        if win_layout is not None:
            win_layout.activate()
        if hasattr(self, "navigationInterface") and self.navigationInterface:
            self.navigationInterface.update()
        if hasattr(self, "stackedWidget") and self.stackedWidget:
            current = self.stackedWidget.currentWidget()
            if current is not None:
                current.update()
            self.stackedWidget.update()
        self.update()

    def changeEvent(self, e: QtCore.QEvent) -> None:
        """
        監聽視窗狀態變更（最大化/還原/焦點切換），強制重新計算佈局並重繪防止畫面撕裂

        Args:
            e: 視窗事件
        """
        super().changeEvent(e)
        if e.type() in (QtCore.QEvent.Type.WindowStateChange, QtCore.QEvent.Type.ActivationChange):
            QtCore.QTimer.singleShot(0, self._force_full_window_repaint)

    def resizeEvent(self, e: QtGui.QResizeEvent) -> None:
        """
        監聽視窗尺寸改變，確保子頁面同步重繪

        Args:
            e: 尺寸變更事件
        """
        super().resizeEvent(e)
        if hasattr(self, "stackedWidget") and self.stackedWidget:
            current = self.stackedWidget.currentWidget()
            if current is not None:
                current.update()

    def setup_window(self) -> None:
        """設定主視窗標題、圖示和現代化樣式"""
        self.setWindowTitle("Minecraft 伺服器管理器")

        if hasattr(self, "navigationInterface") and self.navigationInterface:
            self.navigationInterface.setExpandWidth(240)
            if hasattr(self.navigationInterface, "setMinimumExpandWidth"):
                self.navigationInterface.setMinimumExpandWidth(220)

        width = Sizes.DIALOG_LARGE_WIDTH
        height = Sizes.DIALOG_LARGE_HEIGHT

        if hasattr(self, "settings") and self.settings.is_remember_size_position_enabled():
            win_settings = self.settings.get_main_window_settings()
            width = win_settings.get("width", width)
            height = win_settings.get("height", height)

        screen = QtWidgets.QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QtCore.QRect(0, 0, width, height)
        min_width = min(1100, available.width())
        min_height = min(700, available.height())
        width = max(min_width, min(width, available.width()))
        height = max(min_height, min(height, available.height()))
        self.setMinimumSize(min_width, min_height)
        self.resize(width, height)

        if hasattr(self, "settings") and self.settings.is_remember_size_position_enabled():
            win_settings = self.settings.get_main_window_settings()
            x = win_settings.get("x")
            y = win_settings.get("y")
            if x is not None and y is not None:
                self.move(x, y)
            elif hasattr(self, "settings") and self.settings.is_auto_center_enabled():
                center_window(self)
        elif hasattr(self, "settings") and self.settings.is_auto_center_enabled():
            center_window(self)

    def create_widgets(self) -> None:
        """建立所有介面元件，包含標題和主要內容"""
        self.create_server_frame = CreateServerFrame(
            self,
            self.loader_manager,
            self.initialize_server,
            self.server_crud,
            self.server_properties,
        )
        self.create_server_frame.setObjectName("CreateServerInterface")
        self.manage_server_frame = None
        self.mod_frame = None
        self._ensure_manage_server_frame()
        self._ensure_mod_management_frame()

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

    def _restore_current_navigation_item(self) -> None:
        """將導航欄選中指示條還原為目前實際顯示的子介面"""
        if (
            hasattr(self, "stackedWidget")
            and self.stackedWidget
            and hasattr(self, "navigationInterface")
            and self.navigationInterface
        ):
            current_widget = self.stackedWidget.currentWidget()
            if current_widget is not None and current_widget.objectName():
                self.navigationInterface.setCurrentItem(current_widget.objectName())

    def import_server(self) -> None:
        """
        匯入伺服器（資料夾或壓縮檔）
        統一入口匯入伺服器，支援資料夾和壓縮檔
        """
        dialog = ImportDialog(self.root)
        dialog.exec()

        selected_choice = dialog.choice
        if selected_choice in [None, "cancel"]:
            self._restore_current_navigation_item()
            return
        QtWidgets.QApplication.processEvents()
        self._handle_import_choice(selected_choice)

    def open_servers_folder(self) -> None:
        """開啟伺服器資料夾"""
        self._restore_current_navigation_item()
        folder = self.servers_root
        folder_path = Path(folder)
        if not folder_path.exists():
            folder_path.mkdir(parents=True, exist_ok=True)
        try:
            UIUtils.open_external(str(folder_path))
        except Exception as e:
            logger.error(f"無法開啟路徑: {e}\n{traceback.format_exc()}")
            UIUtils.show_message("錯誤", f"無法開啟路徑: {e}", self.root, message_level="error")

    def initialize_server(self, server_config: ServerConfig) -> None:
        """
        啟動伺服器初始化流程

        Args:
            server_config: 要初始化的伺服器設定
        """
        dialog = ServerInitializationDialog(
            self.root,
            self.server_runtime,
            server_config,
            self.complete_initialization,
        )
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
        init_dialog.reject()
        init_dialog.deleteLater()
        self.page_router.show_manage_server(auto_select=server_config.name)
        QtCore.QTimer.singleShot(
            0,
            lambda: UIUtils.show_message(
                "初始化完成",
                f"伺服器 「{server_config.name}」 已成功初始化並可開始使用！\n\n你現在可以進一步調整伺服器設定或直接啟動",
                self.root,
                message_level="info",
            ),
        )

    def _deferred_init(self) -> None:
        """延遲初始化：在事件循環啟動後執行需要使用者互動的步驟與背景任務排程"""
        try:
            if not self._widgets_initialized:
                self.servers_root = self.set_servers_root()
                if not self.servers_root:
                    logger.warning("未選取伺服器目錄，中止延遲初始化")
                    return
                previous_runtime = getattr(self, "server_runtime", None)
                if previous_runtime is not None:
                    previous_runtime.shutdown()
                self._compose_services(self.servers_root)
                self.create_widgets()
                self._widgets_initialized = True

            if self.settings.is_remember_size_position_enabled() and self.settings.get_main_window_settings().get(
                "maximized", False
            ):
                UIUtils.schedule_debounce(
                    self.root, "_post_reveal_zoom_job", 160, lambda: self.root.showMaximized(), owner=self
                )
            self.task_coordinator = TaskCoordinator(self)
            self.task_coordinator.preload_java_candidates()
            UIUtils.schedule_debounce(
                self.root, "_startup_tasks_job", 1200, self.task_coordinator.handle_startup_tasks, owner=self
            )
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
            self.server_runtime,
            self.server_properties,
            self.server_backup,
            self.server_import,
            self.on_server_selected,
            self.page_router.show_create_server,
        )
        self.manage_server_frame = manage_server_frame
        manage_server_frame.setObjectName("ManageServerInterface")

    def _ensure_mod_management_frame(self) -> None:
        """確保模組管理頁面已建立並放置於內容堆疊層"""
        if getattr(self, "mod_frame", None) is not None:
            return
        mod_controller = ModManagementFrame(
            self,
            self.server_crud,
            self.mod_planning,
            self.on_server_selected,
            self.loader_manager,
        )
        self.mod_frame_controller = mod_controller
        try:
            frame = mod_controller.get_frame()
            if frame is not None:
                frame.setObjectName("ModManagementInterface")
                self.mod_frame = frame
        except Exception as e:
            logger.debug(f"ModManagementFrame 加入頁面堆疊失敗: {e}")

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
        folder_path = UIUtils.get_existing_directory(
            self.root,
            "選擇伺服器資料夾",
            "",
        )
        if not folder_path:
            return None
        return Path(folder_path)

    def _select_server_archive(self) -> Path | None:
        """選擇伺服器壓縮檔"""
        file_path = UIUtils.get_open_file_name(
            parent=self.root,
            caption="選擇伺服器壓縮檔",
            dir="",
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
            return name

    def _finalize_import(self, source_path: Path, server_name: str) -> None:
        """將 UI request 交給交易式 core 匯入 owner"""
        try:
            inspection = self.server_import.inspect(source_path, server_name)
        except Exception as exc:
            UIUtils.show_message("匯入失敗", str(exc), self.root, message_level="error")
            return
        if not inspection.committable:
            UIUtils.show_message(
                "無法匯入",
                "\n".join(inspection.warnings) or "候選不可提交",
                self.root,
                message_level="warning",
            )
            return

        progress_dialog = ProgressDialog(self.root, f"正在匯入 {server_name}...", show_cancel=False)
        progress_dialog.status_label.setText("大型匯入可能需要較長時間，請稍候")
        progress_dialog.show()

        def _close_progress_dialog() -> None:
            with suppress(Exception):
                progress_dialog.close()
                progress_dialog.deleteLater()

        def _import_task():
            def _progress(percent: int, message: str) -> None:
                def _update() -> None:
                    with suppress(Exception):
                        progress_dialog.progress.setValue(percent)
                        progress_dialog.status_label.setText(message)

                run_on_ui_thread(_update)

            return self.server_import.execute(inspection, progress_callback=_progress)

        def _on_done(outcome: WorkOutcome) -> None:
            _close_progress_dialog()
            if not outcome.is_succeeded or outcome.value is None:
                err = outcome.error or "未知錯誤"
                UIUtils.show_message("匯入失敗", f"匯入伺服器失敗: {err}", self.root, message_level="error")
                return

            result = outcome.value
            if not result.completed or result.config is None:
                cleanup = "" if result.cleanup_complete else "\n部分檔案無法自動清理，請依診斷編號檢查"
                UIUtils.show_message(
                    "匯入未完成",
                    f"{result.message}{cleanup}",
                    self.root,
                    message_level="warning" if result.status in {"skipped", "cancelled"} else "error",
                )
                return

            self.page_router.show_manage_server(auto_select=server_name)
            UIUtils.show_message(
                "匯入成功",
                f"伺服器 '{server_name}' 匯入成功!\n\n"
                f"類型: {result.config.loader_type}\n版本: {result.config.minecraft_version}",
                self.root,
                message_level="info",
            )

        self.scope.submit(_import_task, on_done=_on_done, key="server_import", critical=True)


class ServerInitializationDialog(ModalMSFluentWindow):
    """伺服器初始化對話框"""

    def __init__(self, parent: QWidget, server_runtime: Any, server_config: ServerConfig, completion_callback=None):
        super().__init__(parent, is_modal=True, show_buttons=False)
        self.parent_widget = parent
        self.server_runtime = server_runtime
        self.server_config = server_config
        self.completion_callback = completion_callback
        self._completion_scheduled = False
        self.done_detected = False
        self._runtime_sequence = 0

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
            f"TextEdit {{ background-color: {Colors.BG_CONSOLE}; color: {Colors.CONSOLE_TEXT}; border: 1px solid #333333; }}"
        )
        self.viewLayout.addWidget(self.console_text, 1)

        self.progress_label = BodyLabel("狀態: 準備啟動...", self.widget)
        self.progress_label.setFont(FontManager.get_font(size=FontSize.MEDIUM, weight="bold"))
        self.progress_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(self.progress_label)

        self.close_button = StatusPushButton("取消初始化", self.widget)
        self.close_button.set_status("danger")
        self.close_button.clicked.connect(self._close_initialization)

        self.cancelButton.hide()
        self.yesButton.hide()
        self.buttonLayout.insertWidget(3, self.close_button)
        self.buttonGroup.show()

        self._timeout_timer = QtCore.QTimer(self)
        self._timeout_timer.timeout.connect(self._timeout_force_close)
        self._runtime_timer = QtCore.QTimer(self)
        self._runtime_timer.timeout.connect(self._poll_runtime)

    def start_initialization(self) -> None:
        """啟動初始化對話框流程"""
        self._timeout_timer.start(120000)
        self._runtime_timer.start(100)
        center_window(self, self.parentWidget())
        self.show()
        self._start_initialization()

    def _start_initialization(self) -> None:
        """透過唯一 ServerRuntime 啟動初始化流程"""
        self.progress_label.setText("狀態: 正在啟動伺服器...")
        self._update_console("正在啟動 Minecraft 伺服器...\n")
        result = self.server_runtime.start(self.server_config.name, intent="initialize")
        if result.failed:
            self._handle_server_error(result.message)

    def _poll_runtime(self) -> None:
        """讀取 runtime 快照並將事件投影到初始化 UI"""
        snapshot = self.server_runtime.observe(
            self.server_config.name,
            after_sequence=self._runtime_sequence,
        )
        self._runtime_sequence = snapshot.sequence
        for event in snapshot.events:
            if event.kind == "output":
                self._update_console(f"{event.message}\n")
                self._process_server_output(event.message)
            elif event.kind == "ready":
                self.done_detected = True
                self.progress_label.setText("狀態: 伺服器完全啟動，正在關閉...")
                self._update_console("\n[系統] 所有模組載入完成，正在關閉伺服器...\n")
            elif event.kind == "failed":
                self._handle_server_error(event.message)
        if snapshot.state in {"stopped", "failed"}:
            self._runtime_timer.stop()
            if snapshot.state == "stopped":
                self._handle_server_completion()

    def _close_initialization(self) -> None:
        """關閉初始化伺服器"""
        if hasattr(self, "_countdown_timer"):
            self._countdown_timer.stop()
        if self.done_detected:
            self._timeout_timer.stop()
            self._runtime_timer.stop()
            if self.completion_callback and not self._completion_scheduled:
                self._completion_scheduled = True
                self.completion_callback(self.server_config, self)
            else:
                self.reject()
        else:
            self._stop_initialization()
            self._timeout_timer.stop()
            self._runtime_timer.stop()
            UIUtils.show_message(
                "強制關閉",
                "伺服器初始化未完成，已強制關閉請檢查伺服器日誌",
                self.parent_widget,
                message_level="warning",
            )
            self.reject()

    def _stop_initialization(self) -> None:
        """要求 runtime 終止初始化伺服器"""
        try:
            self.server_runtime.stop(self.server_config.name)
        except Exception as e:
            logger.exception(f"終止伺服器程式失敗: {e}")

    def _timeout_force_close(self) -> None:
        """超時強制關閉"""
        if not self.done_detected:
            self._close_initialization()

    def _update_console(self, text: str) -> None:
        """更新控制台輸出"""
        try:
            if self.console_text:
                self.console_text.insertPlainText(text)
                scrollbar = self.console_text.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
        except Exception:
            logger.exception("更新控制台輸出失敗")

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

    def _handle_server_completion(self) -> None:
        """處理伺服器完成狀態"""
        if not self.isVisible():
            return
        if self.done_detected:
            self._update_console("[系統] 伺服器初始化完成！\n")
            if self.progress_label:
                self.progress_label.setText("狀態: 初始化完成")

            if self.completion_callback and not self._completion_scheduled:
                self._completion_scheduled = True
                QtCore.QTimer.singleShot(2000, lambda: self.completion_callback(self.server_config, self))
        else:
            self._update_console("[系統] 伺服器啟動可能有問題，請檢查輸出\n")
            if self.progress_label:
                self.progress_label.setText("狀態: 啟動異常")

    def _handle_server_error(self, err_msg: str) -> None:
        """處理伺服器錯誤並啟動倒數計時強制終止"""
        if not self.isVisible():
            return

        self._update_console(f"[錯誤] 啟動失敗: {err_msg}\n")
        self._start_failure_countdown(60)

    def _start_failure_countdown(self, seconds: int = 60) -> None:
        """啟動失敗倒數計時"""
        self._failure_countdown = seconds
        self._update_failure_countdown_ui()
        if not hasattr(self, "_countdown_timer"):
            self._countdown_timer = QtCore.QTimer(self)
            self._countdown_timer.timeout.connect(self._on_countdown_tick)
        self._countdown_timer.start(1000)

    def _update_failure_countdown_ui(self) -> None:
        if self.progress_label:
            self.progress_label.setText(f"狀態: 啟動失敗\n將於 {self._failure_countdown} 秒後強制終止")

    def _on_countdown_tick(self) -> None:
        self._failure_countdown -= 1
        if self._failure_countdown <= 0:
            if hasattr(self, "_countdown_timer"):
                self._countdown_timer.stop()
            self._close_initialization()
        else:
            self._update_failure_countdown_ui()


def run_application():
    """初始化應用程式並啟動主視窗"""
    logger.info("啟動 Minecraft 伺服器管理器...")
    app = ensure_application()
    app.setQuitOnLastWindowClosed(True)
    settings = get_settings_manager()
    initialize_ui_theme(settings.get_theme_mode())

    logger.info("啟動主視窗...")
    manager = MainWindow()
    logger.info("主視窗啟動完成，進入事件循環...")
    manager.show()
    app.exec()


__all__ = ["MainWindow", "run_application"]
