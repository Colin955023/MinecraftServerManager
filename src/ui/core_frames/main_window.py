"""
主視窗
Minecraft 伺服器管理器的主要使用者介面
本模組定義 Minecraft 伺服器管理器的主視窗
"""

from __future__ import annotations

import sys
from contextlib import suppress
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    FluentWindow,
    NavigationItemPosition,
    Theme,
    setTheme,
)

from src.core import (
    LoaderManager,
    LoaderManagerRulesAdapter,
    ModPlanning,
    ModrinthHttpAdapter,
    ServerBackupManager,
    ServerCRUD,
    ServerImportService,
    ServerInspector,
    ServerPropertiesMigrationService,
    ServerPropertiesStore,
    ServerRuntime,
)
from src.models import ServerConfig
from src.ui import (
    FluentInputDialog,
    FontManager,
    ImportDialog,
    ModManagementFrame,
    ProgressDialog,
    ServerInitializationDialog,
    Sizes,
    TaskCoordinator,
    UIUtils,
    UIWorkScope,
    WorkOutcome,
    apply_window_icon,
    center_window,
    ensure_application,
    initialize_ui_theme,
    is_qobject_alive,
    set_ui_closing,
)
from src.utils import (
    ConfigurationError,
    SettingsManager,
    get_logger,
    resolve_stable_directory,
    shutdown_shared_manager,
    validate_server_name,
)

from .about_preferences_frame import AboutPreferencesFrame
from .create_server_frame import CreateServerFrame
from .manage_server_frame import ManageServerFrame

logger = get_logger().bind(component="MainWindow")


class MainWindow(FluentWindow):
    """Minecraft 伺服器管理器主視窗類別"""

    def __init__(self, settings: SettingsManager):
        super().__init__()
        apply_window_icon(self)
        self.setMicaEffectEnabled(False)
        self.root = self
        self.scope = UIWorkScope(self)
        self.setProperty("_primary_window", True)
        self.settings = settings
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
            except Exception:
                logger.exception("啟動時預先建立介面未完成，將延後至 deferred_init 處理")

        QtCore.QTimer.singleShot(0, self._deferred_init)

    def _compose_services(self, servers_root: str) -> None:
        """
        建立 MainWindow 唯一使用的 production service graph

        Args:
            servers_root: 已驗證的伺服器根目錄
        """
        server_crud = ServerCRUD(servers_root=servers_root)
        loader_manager = LoaderManager()
        server_inspector = ServerInspector()
        mod_provider = ModrinthHttpAdapter()
        mod_planning = ModPlanning(
            mod_provider,
            LoaderManagerRulesAdapter(loader_manager),
        )
        server_import = ServerImportService(server_crud, server_inspector)
        server_properties = ServerPropertiesStore(server_crud)
        server_runtime = ServerRuntime(server_crud, server_inspector=server_inspector)
        server_backup = ServerBackupManager(server_crud, server_runtime=server_runtime)

        self.servers_root = servers_root
        self.loader_manager = loader_manager
        self.mod_provider = mod_provider
        self.mod_planning = mod_planning
        self.server_crud = server_crud
        self.server_inspector = server_inspector
        self.server_import = server_import
        self.server_properties = server_properties
        self.server_runtime = server_runtime
        self.server_backup = server_backup

    def _on_page_changed(self, index: int) -> None:
        widget = self.stackedWidget.widget(index)
        if widget is getattr(self, "manage_server_frame", None) and self.manage_server_frame:
            QtCore.QTimer.singleShot(60, self.manage_server_frame.refresh_servers)
        elif widget is getattr(self, "mod_frame", None) and hasattr(self, "mod_frame_controller"):
            QtCore.QTimer.singleShot(60, self.mod_frame_controller.on_page_shown)

    def set_servers_root(self, new_root: str | None = None) -> str:
        """
        取得或設定伺服器根目錄

        Args:
            new_root: 要設定的新根目錄；未提供時會提示使用者選擇

        Returns:
            解析後的伺服器根目錄字串
        """
        settings = self.settings

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
                logger.exception("無法寫入設定")
                UIUtils.show_message("設定錯誤", f"無法寫入設定: {e}", self.root, message_level="error")
                return ""
        else:
            stored = settings.get_servers_root()
            if stored:
                try:
                    path_obj = settings.get_validated_servers_root_path(create=True)
                except ConfigurationError as e:
                    _fail_exit(str(e))
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
                        logger.exception("無法寫入設定")
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
        if getattr(self, "_shutdown_complete", False):
            super().closeEvent(e)
            return
        e.ignore()
        if getattr(self, "_closing", False):
            return
        self._closing = True
        set_ui_closing(True)
        self.setEnabled(False)
        self.setWindowTitle("Minecraft 伺服器管理器 — 正在安全關閉…")
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

        except Exception as exc:
            logger.error(f"關閉時儲存設定失敗: {exc}")
        app = QtWidgets.QApplication.instance()
        windows = app.topLevelWidgets() if isinstance(app, QtWidgets.QApplication) else [self]
        self._shutdown_scopes = {scope for widget in windows for scope in widget.findChildren(UIWorkScope)}
        for scope in self._shutdown_scopes:
            scope.drain()
        for widget in windows:
            for timer in widget.findChildren(QtCore.QTimer):
                timer.stop()
            if widget is not self:
                widget.close()
        self._shutdown_timer = QtCore.QTimer(self)
        self._shutdown_timer.setInterval(50)
        self._shutdown_timer.timeout.connect(self._advance_shutdown)
        self._shutdown_timer.start()
        self._advance_shutdown()

    def _advance_shutdown(self) -> None:
        """保留 Qt 事件迴圈，等待交易與程序完整結束後關閉視窗"""
        runtime = getattr(self, "server_runtime", None)
        if runtime is not None and not runtime.shutdown(wait=False):
            return
        if not all(not is_qobject_alive(scope) or scope.drain() for scope in self._shutdown_scopes):
            return
        if not shutdown_shared_manager(wait=False):
            return
        self._shutdown_timer.stop()
        self._shutdown_scopes.clear()
        FontManager.clear_cache()
        self._shutdown_complete = True
        self.close()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.quit()

    def eventFilter(self, obj: QtCore.QObject, e: QtCore.QEvent) -> bool:
        """所有退出要求均先經過主視窗的安全關閉流程"""
        if e.type() == QtCore.QEvent.Type.Quit and not getattr(self, "_shutdown_complete", False):
            self.close()
            return True
        return super().eventFilter(obj, e)

    def _queue_surface_refresh(self) -> None:
        """重新取得焦點後只排程 repaint，不在 frameless 過渡狀態強制重算 geometry"""
        if not self.isVisible() or self.isMinimized():
            return
        self.update()
        if hasattr(self, "navigationInterface") and self.navigationInterface:
            self.navigationInterface.update()
        if hasattr(self, "stackedWidget") and self.stackedWidget:
            current = self.stackedWidget.currentWidget()
            if current is not None:
                current.update()
            self.stackedWidget.update()

    def changeEvent(self, event: QtCore.QEvent) -> None:
        """
        Windows Show Desktop/還原及最大化狀態改變後安全刷新 surface

        Args:
            event: QEvent 事件物件
        """
        super().changeEvent(event)
        if event.type() in (QtCore.QEvent.Type.WindowStateChange, QtCore.QEvent.Type.ActivationChange):
            QtCore.QTimer.singleShot(0, self._queue_surface_refresh)

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

        has_settings = hasattr(self, "settings")
        moved = False
        if has_settings and self.settings.is_remember_size_position_enabled():
            win_settings = self.settings.get_main_window_settings()
            x = win_settings.get("x")
            y = win_settings.get("y")
            if x is not None and y is not None:
                self.move(x, y)
                moved = True
        if not moved and has_settings and self.settings.is_auto_center_enabled():
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
        self.manage_server_frame: ManageServerFrame | None = None
        self.mod_frame: QWidget | None = None
        self._ensure_manage_server_frame()
        self._ensure_mod_management_frame()

        self.about_prefs_frame = AboutPreferencesFrame(self, self.settings)
        self.about_prefs_frame.setObjectName("AboutPreferencesInterface")

        self.addSubInterface(self.create_server_frame, FIF.ADD, "建立伺服器")
        self.addSubInterface(self.manage_server_frame, FIF.SETTING, "管理伺服器")
        if self.mod_frame is not None:
            self.addSubInterface(self.mod_frame, FIF.APPLICATION, "模組管理")

        self.navigationInterface.addItem("import", FIF.DOWNLOAD, "匯入伺服器", onClick=self.import_server)
        self.navigationInterface.addItem("folder", FIF.FOLDER, "開啟資料夾", onClick=self.open_servers_folder)
        self.addSubInterface(self.about_prefs_frame, FIF.INFO, "關於與設定", position=NavigationItemPosition.BOTTOM)

        self.show_create_server()

    def show_create_server(self) -> None:
        """顯示建立伺服器頁面並同步導覽列"""
        self._ensure_manage_server_frame()
        self._show_page_frame(self.create_server_frame)

    def show_manage_server(self, auto_select: str | None = None) -> None:
        """
        顯示管理伺服器頁面，必要時延遲選取指定伺服器

        Args:
            auto_select: 自動選取的伺服器名稱
        """
        self._ensure_manage_server_frame()
        self._show_page_frame(self.manage_server_frame)
        if auto_select:
            QtCore.QTimer.singleShot(100, lambda: self._refresh_and_optionally_select(auto_select))

    def _show_page_frame(self, frame: QWidget | None) -> None:
        """切換頁面並同步導覽列選取狀態"""
        if frame is None:
            return
        self.switchTo(frame)
        if getattr(self, "navigationInterface", None) and frame.objectName():
            self.navigationInterface.setCurrentItem(frame.objectName())

    def _refresh_and_optionally_select(self, server_name: str) -> None:
        """重新整理管理頁並選取伺服器"""
        frame = getattr(self, "manage_server_frame", None)
        if frame is None:
            return
        try:
            frame.selected_server = server_name
            frame.refresh_servers()
        except Exception as exc:
            logger.error(f"自動選取伺服器失敗: {exc}")

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
        if selected_choice in (None, "cancel"):
            self._restore_current_navigation_item()
            return
        QtWidgets.QApplication.processEvents()
        self._handle_import_choice(selected_choice)

    def open_servers_folder(self) -> None:
        """開啟伺服器資料夾"""
        self._restore_current_navigation_item()
        folder = self.servers_root
        folder_path = resolve_stable_directory(Path(folder), create=True)
        try:
            UIUtils.open_external(str(folder_path))
        except Exception as e:
            logger.exception("無法開啟路徑")
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
        伺服器被選中的回呼

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
        self.show_manage_server(auto_select=server_config.name)
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
        """延遲初始化：在事件迴圈啟動後執行需要使用者互動的步驟與背景工作排程"""
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
            self.task_coordinator = TaskCoordinator(self, self.settings)
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
            self.show_create_server,
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
            self.mod_provider,
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
            logger.exception("匯入錯誤")
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
            try:
                return validate_server_name(name)
            except ValueError as e:
                UIUtils.show_message("輸入錯誤", str(e), self.root, message_level="error")

    def _finalize_import(self, source_path: Path, server_name: str) -> None:
        """將 UI request 交給交易式 core 匯入 owner"""
        apply_migration = False
        try:
            plan = ServerPropertiesMigrationService.inspect_source(source_path)
            if plan is not None and plan.needs_migration:
                summary = plan.summary()
                res = UIUtils.ask_yes_no_cancel(
                    "舊版設定遷移提示",
                    f"伺服器設定檔 (server.properties) 包含舊版本格式或已廢棄項目：\n\n{summary}\n\n"
                    "是否自動將設定遷移至新版標準？（系統將保留 .backup 備份原檔）",
                    parent=self.root,
                    show_cancel=False,
                )
                apply_migration = bool(res)
        except Exception as e:
            logger.warning(f"檢查 server.properties 遷移狀態失敗: {e}")

        progress_dialog = ProgressDialog(self.root, f"正在匯入 {server_name}...", show_cancel=False)
        progress_dialog.status_label.setText("正在檢查匯入內容，大型檔案可能需要較長時間，請稍候")
        progress_dialog.show()

        def _close_progress_dialog() -> None:
            with suppress(Exception):
                progress_dialog.close()
                progress_dialog.deleteLater()

        def _import_task():
            inspection = self.server_import.inspect(source_path, server_name)
            if not inspection.committable:
                return inspection, None

            return inspection, self.server_import.execute(
                inspection,
                progress_callback=progress_dialog.update_progress_event,
                apply_properties_migration=apply_migration,
            )

        def _on_done(outcome: WorkOutcome) -> None:
            _close_progress_dialog()
            if not outcome.is_succeeded or outcome.value is None:
                err = outcome.error or "未知錯誤"
                UIUtils.show_message("匯入失敗", f"匯入伺服器失敗: {err}", self.root, message_level="error")
                return

            inspection, result = outcome.value
            if not inspection.committable:
                UIUtils.show_message(
                    "無法匯入",
                    "\n".join(inspection.warnings) or "候選不可提交",
                    self.root,
                    message_level="warning",
                )
                return
            if result is None:
                UIUtils.show_message("匯入失敗", "匯入未產生結果", self.root, message_level="error")
                return
            if not result.completed or result.config is None:
                cleanup = "" if result.cleanup_complete else "\n部分檔案無法自動清理，請依診斷編號檢查"
                UIUtils.show_message(
                    "匯入未完成",
                    f"{result.message}{cleanup}",
                    self.root,
                    message_level="warning" if result.status in {"skipped", "cancelled"} else "error",
                )
                return

            self.show_manage_server(auto_select=server_name)
            UIUtils.show_message(
                "匯入成功",
                f"伺服器 '{server_name}' 匯入成功!\n\n"
                f"類型: {result.config.loader_type}\n版本: {result.config.minecraft_version}",
                self.root,
                message_level="info",
            )

        self.scope.submit(_import_task, on_done=_on_done, key="server_import", critical=True)


def run_application():
    """初始化應用程式並啟動主視窗"""
    logger.info("啟動 Minecraft 伺服器管理器...")
    set_ui_closing(False)
    app = ensure_application()
    app.setQuitOnLastWindowClosed(True)
    settings = SettingsManager()
    initialize_ui_theme(settings.get_theme_mode())

    logger.info("啟動主視窗...")
    manager = MainWindow(settings)
    app.installEventFilter(manager)
    logger.info("主視窗啟動完成，進入事件迴圈...")
    manager.show()
    app.exec()


__all__ = ["MainWindow", "run_application"]
