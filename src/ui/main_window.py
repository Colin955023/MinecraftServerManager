"""
主視窗
Minecraft 伺服器管理器的主要使用者介面
本模組定義 Minecraft 伺服器管理器的主視窗，使用 qfluentwidgets 的 FluentWindow 提供現代化 UI 體驗。
"""

from __future__ import annotations

import contextlib
import queue
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from PySide6 import QtGui, QtWidgets
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    FluentWindow,
    MessageBoxBase,
    NavigationItemPosition,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)

from ..core import (
    ConfigurationError,
    JavaManager,
    LoaderManager,
    MinecraftVersionManager,
    ServerBackup,
    ServerCRUD,
    ServerRepository,
    ServerStartup,
)
from ..models import ServerConfig
from ..utils import (
    APP_VERSION,
    GITHUB_OWNER,
    GITHUB_REPO,
    FontManager,
    FontSize,
    Sizes,
    TaskUtils,
    UIUtils,
    UpdateChecker,
    WindowManager,
    ensure_application,
    get_logger,
    get_settings_manager,
    initialize_ui_theme,
    is_qobject_alive,
)
from . import (
    AboutPreferencesFrame,
    CreateServerFrame,
    ImportServerService,
    ManageServerFrame,
    ModManagementFrame,
    ProgressDialog,
)

logger = get_logger().bind(component="MainWindow")
_manager: MinecraftServerManager | None = None  # 模組層級持有，防止 GC 回收


class ImportConflictDialog(MessageBoxBase):
    """Fluent 風格的匯入衝突對話框。"""

    def __init__(self, server_name: str, target_path: Path, parent: Any = None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("伺服器已存在", self.widget)
        self.bodyLabel = BodyLabel(f"伺服器「{server_name}」已存在，是否覆蓋？\n\n目標路徑：{target_path}", self.widget)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.bodyLabel)

        # 隱藏預設按鈕群組，改在 viewLayout 添加自訂按鈕
        self.buttonGroup.hide()

        self.overwriteButton = PrimaryPushButton("覆蓋現有伺服器", self.widget)
        self.renameButton = PushButton("自動重新命名匯入", self.widget)
        self.cancelImportButton = PushButton("取消匯入", self.widget)

        for btn in (self.overwriteButton, self.renameButton, self.cancelImportButton):
            btn.setFixedHeight(36)

        self.viewLayout.addSpacing(8)
        self.viewLayout.addWidget(self.overwriteButton)
        self.viewLayout.addWidget(self.renameButton)
        self.viewLayout.addWidget(self.cancelImportButton)

        self.overwriteButton.clicked.connect(self._on_overwrite)
        self.renameButton.clicked.connect(self._on_rename_clicked)
        self.cancelImportButton.clicked.connect(self.reject)

        self.choice = "cancel"
        self.widget.setMinimumWidth(360)

    def _on_overwrite(self):
        self.choice = "overwrite"
        self.accept()

    def _on_rename_clicked(self):
        self.choice = "rename"
        self.accept()

    def reject(self):
        """覆寫 reject 方法，確保在取消時 choice 為 "cancel"。"""
        self.choice = "cancel"
        super().reject()


def run() -> None:
    """UI 層啟動入口，由 main.py 呼叫"""
    global _manager

    app = ensure_application()
    settings = get_settings_manager()
    theme_mode = settings.get_theme_mode()
    initialize_ui_theme(theme_mode)

    _manager = MinecraftServerManager()
    _manager.show()
    app.exec()


class ImportServerDialog(MessageBoxBase):
    """匯入伺服器選項對話框"""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.choice: str | None = None

        self.titleLabel = SubtitleLabel("匯入伺服器", self.widget)
        self.contentLabel = BodyLabel("請選擇要匯入的伺服器來源：", self.widget)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.contentLabel)

        self.zipButton = PrimaryPushButton("匯入壓縮檔 (.zip)", self.widget)
        self.folderButton = PrimaryPushButton("匯入資料夾", self.widget)
        self.cancelButton = PushButton("取消", self.widget)

        for btn in (self.zipButton, self.folderButton, self.cancelButton):
            btn.setFixedHeight(36)

        self.viewLayout.addSpacing(8)
        self.viewLayout.addWidget(self.zipButton)
        self.viewLayout.addWidget(self.folderButton)
        self.viewLayout.addWidget(self.cancelButton)

        self.buttonGroup.hide()

        self.zipButton.clicked.connect(self._on_zip)
        self.folderButton.clicked.connect(self._on_folder)
        self.cancelButton.clicked.connect(self._on_cancel)

    def _on_zip(self) -> None:
        self.choice = "zip"
        self.accept()

    def _on_folder(self) -> None:
        self.choice = "folder"
        self.accept()

    def _on_cancel(self) -> None:
        self.choice = None
        self.reject()


class MinecraftServerManager(FluentWindow):
    """Minecraft 伺服器管理器主視窗類別 - 使用 FluentWindow"""

    # 側邊欄導航項目文字（用於計算展開寬度）
    _NAV_ITEMS: ClassVar[list[str]] = [
        "建立伺服器",
        "管理伺服器",
        "模組管理",
        "關於與設定",
        "匯入伺服器",
        "開啟伺服器資料夾",
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Minecraft 伺服器管理器")
        self.resize(Sizes.DIALOG_LARGE_WIDTH, Sizes.DIALOG_LARGE_HEIGHT)

        # 內部狀態
        self._startup_update_check_job = None
        self.ui_queue: queue.Queue[Callable[[], Any]] = queue.Queue()
        TaskUtils.start_ui_queue_pump(self, self.ui_queue)

        self.settings = get_settings_manager()
        self.servers_root = self.set_servers_root()
        self.version_manager = MinecraftVersionManager()
        self.loader_manager = LoaderManager()
        self.repository = ServerRepository(self.servers_root)
        self.server_crud = ServerCRUD(self.repository)
        self.server_startup = ServerStartup(self.repository, self.server_crud)
        self.server_backup = ServerBackup(self.server_startup)

        # 設定側邊欄展開寬度（與文字最多的欄位同寬）
        self._configure_sidebar_expand_width()

        # 建立子介面
        self._create_sub_interfaces()

        # 設定視窗
        WindowManager.setup_main_window(self)
        WindowManager.bind_window_state_tracking(self)

        if self.settings.is_remember_size_position_enabled() and self.settings.get_main_window_settings().get(
            "maximized", False
        ):
            UIUtils.schedule_debounce(self, "_post_reveal_zoom_job", 160, lambda: self.showMaximized(), owner=self)

        self.preload_java_candidates()
        UIUtils.schedule_debounce(self, "_startup_tasks_job", 1000, self._handle_startup_tasks, owner=self)
        self.preload_all_versions()
        self.load_data_async()

    def _configure_sidebar_expand_width(self) -> None:
        """設定側邊欄展開寬度，使其與最長導航項目文字同寬。"""
        try:
            font = FontManager.get_font(size=FontSize.NORMAL)
            if font is None:
                font = self.font()

            fm = QtGui.QFontMetrics(font) if font else None
            max_text_width = 0
            for item_text in self._NAV_ITEMS:
                text_width = fm.horizontalAdvance(item_text) if fm is not None else len(item_text) * 14
                max_text_width = max(max_text_width, text_width)
            # 加上 icon 寬度 + padding（icon 約 24px + 左右 padding 各 12px + 右側 margin 16px）
            expand_width = max_text_width + 24 + 24 + 16 + 8
            # 設定合理範圍：最小 180px，最大 320px
            expand_width = max(180, min(320, expand_width))
            self.navigationInterface.setExpandWidth(expand_width)
            logger.debug(f"側邊欄展開寬度設定為: {expand_width}px", "MainWindow")
        except Exception as e:
            logger.debug(f"設定側邊欄展開寬度失敗: {e}", "MainWindow")

    def _create_sub_interfaces(self) -> None:
        """建立所有子介面並加入導航"""
        # 建立伺服器介面
        self.create_server_interface = CreateServerFrame(
            self,
            self.version_manager,
            self.loader_manager,
            self.complete_initialization,
            self.repository,
            self.server_crud,
        )
        self.create_server_interface.setObjectName("createServerInterface")
        self.addSubInterface(
            self.create_server_interface,
            FluentIcon.ADD,
            "建立伺服器",
            position=NavigationItemPosition.TOP,
        )

        # 管理伺服器介面
        self.manage_server_interface = ManageServerFrame(
            self,
            self.repository,
            self.server_startup,
            self.server_backup,
            self.on_server_selected,
            self.show_create_server,
            set_servers_root=self.set_servers_root,
        )
        self.manage_server_interface.setObjectName("manageServerInterface")
        self.addSubInterface(
            self.manage_server_interface,
            FluentIcon.SETTING,
            "管理伺服器",
            position=NavigationItemPosition.TOP,
        )

        # 模組管理介面
        self.mod_management_interface = ModManagementFrame(
            self, self.repository, self.on_server_selected, self.version_manager
        )
        self.mod_management_interface.setObjectName("modManagementInterface")
        self.addSubInterface(
            self.mod_management_interface,
            FluentIcon.APPLICATION,
            "模組管理",
            position=NavigationItemPosition.TOP,
        )

        # 關於與偏好設定介面
        self.about_preferences_interface = AboutPreferencesFrame(self)
        self.about_preferences_interface.setObjectName("aboutPreferencesInterface")
        self.addSubInterface(
            self.about_preferences_interface,
            FluentIcon.INFO,
            "關於與設定",
            position=NavigationItemPosition.BOTTOM,
        )

        # 底部功能按鈕
        self.navigationInterface.addItem(
            routeKey="import_server",
            icon=FluentIcon.DOWNLOAD,
            text="匯入伺服器",
            onClick=self.import_server,
            position=NavigationItemPosition.BOTTOM,
            tooltip="匯入現有伺服器",
        )
        self.navigationInterface.addItem(
            routeKey="open_folder",
            icon=FluentIcon.FOLDER,
            text="開啟伺服器資料夾",
            onClick=self.open_servers_folder,
            position=NavigationItemPosition.BOTTOM,
            tooltip="在檔案總管中開啟伺服器根目錄",
        )

    def _ensure_manage_server_interface(self) -> None:
        """確保管理伺服器介面已建立"""
        if self.manage_server_interface is not None:
            return

        # 建立管理伺服器介面並設定名稱，避免在型別檢查時被視為 None
        manage_iface = ManageServerFrame(
            self,
            self.repository,
            self.server_startup,
            self.server_backup,
            self.on_server_selected,
            self.show_create_server,
            set_servers_root=self.set_servers_root,
        )
        manage_iface.setObjectName("manageServerInterface")
        self.manage_server_interface = manage_iface
        self.addSubInterface(
            manage_iface,
            FluentIcon.SETTING,
            "管理伺服器",
            position=NavigationItemPosition.TOP,
        )

    def _ensure_mod_management_interface(self) -> None:
        """確保模組管理介面已建立"""
        if self.mod_management_interface is not None:
            return

        mod_iface = ModManagementFrame(self, self.repository, self.on_server_selected, self.version_manager)
        mod_iface.setObjectName("modManagementInterface")
        self.mod_management_interface = mod_iface
        self.addSubInterface(
            mod_iface,
            FluentIcon.APPLICATION,
            "模組管理",
            position=NavigationItemPosition.TOP,
        )

    def set_servers_root(self, new_root: str | None = None) -> str:
        """
        取得或設定伺服器根目錄。

        Args:
            new_root: 要設定的新根目錄；未提供時會提示使用者選擇。

        Returns:
            解析後的伺服器根目錄字串。
        """

        def _fail_exit(msg: str):
            """錯誤退出處理"""
            UIUtils.show_error("錯誤", msg, self.root)
            self.root.close()
            sys.exit(0)

        settings = get_settings_manager()
        path_obj = None

        if new_root:
            try:
                settings.set_servers_root(new_root)
                path_obj = settings.get_validated_servers_root_path(create=True)
            except Exception as e:
                logger.error(f"無法寫入設定: {e}\n{traceback.format_exc()}")
                UIUtils.show_error("設定錯誤", f"無法寫入設定: {e}", None)
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
                    base_dir = self._prompt_for_directory()
                    if not base_dir:
                        continue
                    try:
                        settings.set_servers_root(base_dir)
                        path_obj = settings.get_validated_servers_root_path(create=True)
                        break
                    except Exception as e:
                        logger.error(f"無法寫入設定: {e}\n{traceback.format_exc()}")
                        UIUtils.show_error("設定錯誤", f"無法寫入設定: {e}", None)

        self.servers_root = str(path_obj)
        return self.servers_root

    def _prompt_for_directory(self) -> str:
        """提示使用者選擇伺服器主資料夾，並返回選擇的路徑。"""
        UIUtils.show_info(
            "選擇伺服器資料夾",
            "請選擇要存放所有 Minecraft 伺服器的主資料夾\n(系統會在該資料夾內自動建立 servers 子資料夾)",
            None,
        )
        folder = QtWidgets.QFileDialog.getExistingDirectory(None, "選擇伺服器主資料夾", str(Path.home()))
        if not folder:
            if UIUtils.ask_yes_no_cancel("結束程式", "未選擇資料夾，是否要結束程式？", None, show_cancel=False):
                self.close()
                sys.exit(0)
            return ""
        return str(Path(folder))

    def on_closing(self) -> None:
        """主視窗關閉處理，清理快取並儲存視窗狀態"""
        logger.debug("程式即將關閉！", "MainWindow")
        try:
            get_logger().bind(component="WindowState").debug("儲存視窗狀態...")
            WindowManager.save_main_window_state(self)
            logger.debug("清理字體快取...", "MainWindow")
            FontManager.clear_cache()
            if getattr(self, "repository", None) is not None:
                self.repository.write_servers_config()
            app = QtWidgets.QApplication.instance()
            if isinstance(app, QtWidgets.QApplication):
                for widget in app.topLevelWidgets():
                    if widget is self:
                        continue
                    try:
                        widget.close()
                    except Exception as e:
                        logger.error(f"清理子視窗時發生錯誤: {e}\n{traceback.format_exc()}")
        except Exception as e:
            logger.error(f"清理資源時發生錯誤: {e}\n{traceback.format_exc()}")
        finally:
            try:
                self.close()
                app = QtWidgets.QApplication.instance()
                if app is not None:
                    app.quit()
            except Exception as e:
                logger.error(f"銷毀主視窗時發生錯誤: {e}\n{traceback.format_exc()}")
                sys.exit(0)

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
            JavaManager.refresh_java_candidates_cache()
            logger.debug("本機 Java 快取更新完成", "MainWindow")

        TaskUtils.run_async(refresh_java_cache)

    def load_data_async(self) -> None:
        """非同步載入資料"""

        def load_versions():
            try:
                versions = self.version_manager.fetch_versions()
                self.ui_queue.put(lambda: self.create_server_interface.update_versions(versions))
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
            if not is_qobject_alive(self):
                return
            self._check_for_updates(show_msg=show_msg)

        UIUtils.schedule_debounce(
            self, "_startup_update_check_job", max(0, int(delay_ms)), _run_update_check, owner=self
        )

    def _show_first_run_prompt(self) -> None:
        """顯示首次執行的自動更新設定提示"""
        settings = get_settings_manager()
        choice = UIUtils.show_info(
            title="歡迎使用 Minecraft 伺服器管理器",
            message="已啟用自動檢查更新功能\n\n程式會在啟動時自動檢查新版本。\n您可以隨時在「關於」視窗中更改此設定。",
            parent=self,
        )
        logger.info(f"首次啟動設定對話結果: enable_auto_update={bool(choice)}", "MainWindow")
        enable_auto_update = bool(choice)
        settings.set_auto_update_enabled(enable_auto_update)
        settings.mark_first_run_completed()
        with contextlib.suppress(Exception):
            self.setFocus()
        if enable_auto_update:
            self._schedule_startup_update_check(delay_ms=900, show_msg=False)

    def _check_for_updates(self, show_msg: bool = True) -> None:
        """檢查更新"""
        try:
            UpdateChecker.check_and_prompt_update(
                APP_VERSION,
                GITHUB_OWNER,
                GITHUB_REPO,
                show_up_to_date_message=show_msg,
                parent=self,
            )
        except Exception as e:
            logger.error(f"自動更新檢查失敗: {e}\n{traceback.format_exc()}")
            if show_msg:
                UIUtils.show_error("更新檢查失敗", f"無法檢查更新：{e}", self)

    def complete_initialization(self, server_config: ServerConfig) -> None:
        """
        完成伺服器初始化，切換到管理頁面。

        Args:
            server_config: 已初始化的伺服器設定。
        """
        self._ensure_manage_server_interface()
        if self.manage_server_interface is None:
            raise RuntimeError("管理伺服器介面未正確初始化")
        self.switchTo(self.manage_server_interface)
        self.manage_server_interface.refresh_servers()
        self.manage_server_interface.select_server(server_config.name)

    def on_server_selected(self, server_config: ServerConfig) -> None:
        """
        伺服器選中時的回調。

        Args:
            server_config: 被選中的伺服器設定。
        """

    def show_create_server(self) -> None:
        """切換到建立伺服器頁面"""
        self.switchTo(self.create_server_interface)

    def import_server(self) -> None:
        """匯入伺服器對話框與執行流程"""
        dialog = ImportServerDialog(self)
        if not dialog.exec():
            return

        choice = dialog.choice
        if choice == "zip":
            file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "選擇伺服器壓縮檔",
                str(Path.home()),
                "壓縮檔 (*.zip);;所有檔案 (*)",
            )
            if file_path:
                self._finish_import_server(file_path)
        elif choice == "folder":
            folder_path = QtWidgets.QFileDialog.getExistingDirectory(
                self,
                "選擇伺服器資料夾",
                str(Path.home()),
            )
            if folder_path:
                self._finish_import_server(folder_path)

    def _finish_import_server(self, source: str) -> None:
        """執行匯入伺服器檔案或資料夾"""

        progress = ProgressDialog(self, "正在匯入伺服器…", show_cancel=False)
        progress.update_progress(10, "正在複製檔案…")

        try:
            target = ImportServerService.import_server(source, self.servers_root)
        except FileExistsError:
            source_path = Path(source)
            name = source_path.stem if source_path.is_file() else source_path.name
            target = Path(self.servers_root) / name
            progress.close()

            dialog = ImportConflictDialog(name, target, self)
            if not dialog.exec():
                return

            choice = dialog.choice
            if choice == "cancel":
                return

            progress = ProgressDialog(self, "正在匯入伺服器…", show_cancel=False)

            if choice == "overwrite":
                progress.update_progress(30, "正在覆蓋檔案…")
                try:
                    target = ImportServerService.import_server(source, self.servers_root, allow_overwrite=True)
                except Exception as exc:
                    progress.close()
                    logger.exception("匯入伺服器失敗: %s", exc)
                    UIUtils.show_error("匯入失敗", f"無法匯入伺服器：{exc}", self)
                    return
            elif choice == "rename":
                progress.update_progress(30, "正在重新命名並匯入檔案…")
                idx = 1
                new_name = f"{name}_{idx}"
                while (Path(self.servers_root) / new_name).exists():
                    idx += 1
                    new_name = f"{name}_{idx}"
                try:
                    target = ImportServerService.import_server(source, self.servers_root, custom_name=new_name)
                except Exception as exc:
                    progress.close()
                    logger.exception("匯入伺服器失敗: %s", exc)
                    UIUtils.show_error("匯入失敗", f"無法匯入伺服器：{exc}", self)
                    return

        try:
            progress.update_progress(70, "正在偵測伺服器…")
            self._ensure_manage_server_interface()
            if self.manage_server_interface:
                self.manage_server_interface.detect_servers(show_message=False)
            progress.close()
            self.switchTo(self.manage_server_interface)
            UIUtils.show_info("匯入完成", f"已匯入伺服器：{target.name}", self)
        except Exception as exc:
            progress.close()
            logger.exception("匯入伺服器失敗: %s", exc)
            UIUtils.show_error("匯入失敗", f"無法匯入伺服器：{exc}", self)

    def open_servers_folder(self) -> None:
        """開啟伺服器資料夾"""

        if not self.servers_root:
            UIUtils.show_info("資料夾不存在", "伺服器根目錄尚未設定", self)
            return
        servers_path = Path(self.servers_root)
        if servers_path.exists():
            UIUtils.open_external(str(servers_path))
        else:
            UIUtils.show_info("資料夾不存在", "伺服器資料夾尚未建立", self)

    def switchTo(self, interface: QtWidgets.QWidget) -> None:
        """
        切換到指定介面

        Args:
            interface: 要切換到的介面。
        """
        super().switchTo(interface)
        # 更新導航選中狀態
        if hasattr(interface, "objectName"):
            self.navigationInterface.setCurrentItem(interface.objectName())
