"""
建立伺服器頁面
負責建立新 Minecraft 伺服器的使用者介面。
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import queue
import re
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6 import QtCore

from ..core import (
    JavaManager,
    LoaderManager,
    MinecraftVersionManager,
    ServerCommands,
    ServerCRUD,
    ServerDetectionUtils,
    ServerRepository,
)
from ..models import ServerConfig
from ..utils import (
    CancellationToken,
    Colors,
    CustomDropdown,
    FontManager,
    FontSize,
    PathUtils,
    Sizes,
    Spacing,
    SubprocessUtils,
    SystemUtils,
    TaskUtils,
    UIUtils,
    get_logger,
    get_shared_manager,
    install_open_url_click,
    is_qobject_alive,
    record_and_mark,
)
from ..utils.ui_support import qt_widgets as qt
from . import CreateServerService, ProgressDialog, ServerConfigInputs

logger = get_logger().bind(component="CreateServerFrame")


class CreateServerFrame(qt.Frame):
    """建立伺服器頁面"""

    def update_memory_warning(self) -> None:
        """更新記憶體使用警告標籤"""
        try:
            inputs = ServerConfigInputs(
                server_name=self.server_name_entry.text().strip() if hasattr(self, "server_name_entry") else "",
                mc_version=self.mc_version_combo.currentText().strip() if hasattr(self, "mc_version_combo") else "",
                loader_type=self.loader_type_combo.currentText().strip()
                if hasattr(self, "loader_type_combo")
                else "Vanilla",
                loader_version=self.loader_version_combo.currentText().strip()
                if hasattr(self, "loader_version_combo")
                else "",
                min_memory=self.min_memory_entry.text().strip() if hasattr(self, "min_memory_entry") else "",
                max_memory=self.max_memory_entry.text().strip() if hasattr(self, "max_memory_entry") else "",
                system_memory=SystemUtils.get_total_memory_mb(),
                servers_root=self.repository.servers_root,
            )
            val_result = CreateServerService.validate_server_config_inputs(inputs)

            if val_result.memory_warning:
                color = Colors.TEXT_ERROR if val_result.memory_color == "error" else Colors.TEXT_WARNING
                self._set_warning_text(val_result.memory_warning, color)
            elif "記憶體設定必須為有效整數" in val_result.errors:
                if not inputs.min_memory and not inputs.max_memory:
                    self._set_warning_text("")
                else:
                    self._set_warning_text("⚠️ 警告：記憶體設定必須為有效的整數", Colors.TEXT_ERROR)
            else:
                self._set_warning_text("")
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(e, marker_path=Path(__file__), reason="update_memory_warning_failed")
            logger.bind(component="").error(f"更新記憶體警告失敗: {e}\n{traceback.format_exc()}", "CreateServerFrame")
            UIUtils.show_error("錯誤", f"更新記憶體警告失敗: {e}", self.window())

    def _set_warning_text(self, text: str, color: Any = Colors.TEXT_ERROR) -> None:
        self.memory_warning_label.configure(text=text, text_color=color)

    def _make_label(self, text: str, *, muted: bool = False, bold: bool = True) -> qt.Label:
        label = qt.Label(self.form_panel, text=text)
        label.configure(
            font=FontManager.get_font(size=FontSize.MEDIUM, weight="bold" if bold else "normal"),
            text_color=Colors.TEXT_MUTED if muted else Colors.TEXT_PRIMARY,
            width=Sizes.FORM_LABEL_WIDTH,
            anchor="w",
        )
        return label

    def _make_button(self, parent: Any, text: str, command: Callable[[], Any], *, kind: str = "secondary") -> qt.Button:
        """建立按鈕並掛載至實際使用它的容器。"""
        button = qt.Button(parent, text=text, command=command)
        button.configure(
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            height=Sizes.BUTTON_HEIGHT_LARGE,
            cursor="hand2",
        )
        if kind == "primary":
            button.configure(
                fg_color=Colors.BUTTON_PRIMARY, hover_color=Colors.BUTTON_PRIMARY_HOVER, text_color=Colors.TEXT_ON_DARK
            )
        elif kind == "danger":
            button.configure(
                fg_color=Colors.BUTTON_DANGER, hover_color=Colors.BUTTON_DANGER_HOVER, text_color=Colors.TEXT_ON_DARK
            )
        else:
            button.configure(
                fg_color=Colors.BUTTON_SECONDARY,
                hover_color=Colors.BUTTON_SECONDARY_HOVER,
                text_color=Colors.TEXT_PRIMARY,
            )
        return button

    def create_java_path_field(self, parent, row) -> None:
        """
        建立 Java 路徑欄位（可手動輸入/瀏覽）。

        Args:
            parent: 父容器。
            row: 要放置的表單列號。
        """
        self._make_label("Java 路徑 (可選):").attach_matrix(
            row=row, column=0, sticky="w", padx=Spacing.MEDIUM, pady=Spacing.SMALL
        )
        self.java_path_entry = qt.Entry(self.form_panel)
        self.java_path_entry.configure(font=FontManager.get_font(size=FontSize.MEDIUM))
        self.java_path_entry.attach_matrix(row=row, column=1, sticky="ew", padx=Spacing.MEDIUM, pady=Spacing.SMALL)

        def browse_java():
            path = qt.get_open_file_name(self.window(), "選擇 javaw.exe", "", "Java 執行檔 (javaw.exe);;所有檔案 (*)")
            if path:
                self.java_path_entry.setText(path)

        browse_btn = self._make_button(parent, "瀏覽...", command=browse_java)
        browse_btn.configure(width=Sizes.BUTTON_WIDTH_PRIMARY)
        browse_btn.attach_matrix(row=row, column=2, padx=Spacing.SMALL, pady=Spacing.SMALL)

        def auto_detect():
            mc_version = self.mc_version_combo.currentText() if hasattr(self, "mc_version_combo") else None
            if not mc_version or mc_version in ["載入中...", "無可用版本", "載入失敗"]:
                UIUtils.show_warning("Java 偵測", "請先選擇有效的 Minecraft 版本！", self.window())
                return
            java_path = JavaManager.get_best_java_path(mc_version, interaction=UIUtils)
            if java_path:
                java_path_win = str(Path(java_path))
                self.java_path_entry.setText(java_path_win)

        auto_btn = self._make_button(parent, "自動偵測", command=auto_detect)
        auto_btn.configure(width=Sizes.BUTTON_WIDTH_PRIMARY)
        auto_btn.attach_matrix(row=row, column=3, padx=Spacing.SMALL, pady=Spacing.SMALL)
        parent.set_grid_column_stretch(1, weight=1)

    def __init__(
        self,
        parent,
        version_manager: MinecraftVersionManager,
        loader_manager: LoaderManager,
        callback: Callable,
        repository: ServerRepository,
        server_crud: ServerCRUD,
    ):
        super().__init__(parent)
        self.version_manager = version_manager
        self.loader_manager = loader_manager
        self.callback = callback
        self.repository = repository
        self.server_crud = server_crud
        self.versions: list = []
        self.release_versions: list = []
        self._loading_key: str | None = None
        self._create_server_progress_job = None
        self._create_server_success_job = None
        self._create_server_error_job = None
        self.server_name_entry: qt.Entry
        self.min_memory_entry: qt.Entry
        self.max_memory_entry: qt.Entry
        self.loader_type_combo: qt.ComboBox
        self.loader_version_combo: qt.ComboBox
        self.mc_version_combo: qt.ComboBox
        self.ui_queue: queue.Queue[Callable[[], Any]] = queue.Queue()
        self.bg_tasks = get_shared_manager()
        TaskUtils.start_ui_queue_pump(self, self.ui_queue)
        self.create_widgets()
        self.preload_version_data()

    def _schedule_ui_job(self, job_attr: str, delay_ms: int, callback: Callable[[], Any]) -> None:
        """透過主執行緒佇列建立 debounce 排程。"""

        def _schedule() -> None:
            if not is_qobject_alive(self):
                return
            UIUtils.schedule_debounce(self, job_attr, delay_ms, callback, owner=self)

        self.ui_queue.put(_schedule)

    def _cancel_create_server_jobs(self) -> None:
        """取消建立伺服器流程相關的待執行 UI 工作。"""
        for job_attr in ("_create_server_progress_job", "_create_server_success_job", "_create_server_error_job"):
            UIUtils.cancel_scheduled_job(self, job_attr, owner=self)

    def create_widgets(self) -> None:
        """建立介面元件"""
        self.setObjectName("CreateServerFrame")
        main_frame = qt.Frame(self, fg_color="transparent")
        main_frame.attach(fill="both", expand=True)

        self.scroll_area = qt.ScrollableFrame(main_frame)
        self.scroll_area.setObjectName("CreateServerScrollArea")
        self.scroll_area.attach(fill="both", expand=True)

        self.content_widget = self.scroll_area._content_widget
        self.content_widget.setObjectName("CreateServerContent")

        title_label = qt.Label(self.content_widget, text="建立新伺服器")
        self.title_label = title_label
        title_label.configure(
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
            text_color=Colors.TEXT_HEADING,
        )
        title_label.attach(pady=(0, Spacing.LARGE))

        eula_frame = qt.Frame(self.content_widget)
        self.eula_frame = eula_frame
        eula_frame.setObjectName("EulaNotice")
        eula_frame.configure(fg_color=Colors.BG_WARNING, height=Sizes.WARNING_AREA_HEIGHT)
        eula_frame.attach(fill="x", pady=(0, Spacing.SMALL))

        eula_icon = qt.Label(eula_frame, text="⚠️")
        self.eula_icon = eula_icon
        eula_icon.configure(
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            text_color=Colors.BUTTON_WARNING_HOVER,
        )
        eula_icon.attach(side="left", padx=Spacing.MEDIUM, pady=Spacing.SMALL, anchor="v")

        eula_link = qt.Label(
            eula_frame,
            text="請務必閱讀並同意 Minecraft EULA 條款 (點我閱讀)\n點擊建立即表示你同意Minecraft條款，任何違法行為本軟體不負責任",
        )
        self.eula_link = eula_link
        eula_link.configure(
            font=FontManager.get_font(size=FontSize.SMALL, weight="bold", underline=True),
            text_color=Colors.TEXT_WARNING,
            cursor="hand2",
        )
        install_open_url_click(eula_link, "https://aka.ms/MinecraftEULA")
        eula_link.attach(side="left", fill="x", expand=True, padx=(Spacing.SMALL, Spacing.MEDIUM), pady=Spacing.SMALL)

        self.form_panel = qt.Frame(self.content_widget)
        self.form_panel.setObjectName("CreateFormPanel")
        self.form_panel.configure(fg_color=Colors.BG_SECONDARY)
        self.form_panel.attach(fill="x", pady=(0, Spacing.LARGE))
        # 防止 Y 軸自動填滿，將所有表單內容推至頂部
        layout = self.content_widget.layout()
        if layout and hasattr(layout, "addStretch"):
            layout.addStretch(1)  # type: ignore[attr-defined]
        self.create_form(self.form_panel)

        self.create_buttons(main_frame)

    def create_form(self, parent) -> None:
        """
        建立表單。

        Args:
            parent: 父容器。
        """
        parent.set_grid_column_stretch(1, weight=1)

        self.create_field(parent, 0, "伺服器名稱:", "我的伺服器", "server_name")
        self.create_java_path_field(parent, 1)

        self._make_label("模組載入器:").attach_matrix(
            row=2, column=0, sticky="w", padx=Spacing.MEDIUM, pady=Spacing.SMALL
        )
        self.loader_type_combo = CustomDropdown(
            parent,
            values=["Vanilla", "Fabric", "Forge", "Quilt", "NeoForge"],
            width=Sizes.DROPDOWN_WIDTH,
            font_size=FontSize.MEDIUM,
            state="readonly",
        )
        self.loader_type_combo.set("Vanilla")
        self.loader_type_combo.attach_matrix(row=2, column=1, sticky="ew", padx=Spacing.MEDIUM, pady=Spacing.SMALL)
        self.loader_type_combo.currentTextChanged.connect(lambda *_: self.update_server_config_ui())

        loader_version_row = 3
        self._make_label("載入器版本:").attach_matrix(
            row=loader_version_row, column=0, sticky="w", padx=Spacing.MEDIUM, pady=Spacing.SMALL
        )
        self.loader_version_combo = CustomDropdown(
            parent,
            values=["無"],
            width=Sizes.DROPDOWN_WIDTH,
            font_size=FontSize.MEDIUM,
            state="disabled",
        )
        self.loader_version_combo.set("無")
        self.loader_version_combo.attach_matrix(
            row=loader_version_row, column=1, sticky="ew", padx=Spacing.MEDIUM, pady=Spacing.SMALL
        )
        loader_reload_btn = self._make_button(parent, "⟳", self.reload_loader_versions)
        loader_reload_btn.configure(width=Sizes.BUTTON_WIDTH_SMALL)
        loader_reload_btn.attach_matrix(row=loader_version_row, column=2, padx=Spacing.SMALL, pady=Spacing.SMALL)

        self._make_label("Minecraft 版本:").attach_matrix(
            row=4, column=0, sticky="w", padx=Spacing.MEDIUM, pady=Spacing.SMALL
        )
        self.mc_version_combo = CustomDropdown(
            parent,
            values=["載入中..."],
            command=self.update_server_config_ui,
            width=Sizes.DROPDOWN_COMPACT_WIDTH,
            font_size=FontSize.MEDIUM,
            state="readonly",
        )
        self.mc_version_combo.set("載入中...")
        self.mc_version_combo.attach_matrix(row=4, column=1, sticky="ew", padx=Spacing.MEDIUM, pady=Spacing.SMALL)
        mc_reload_btn = self._make_button(parent, "⟳", self.reload_mc_versions)
        mc_reload_btn.configure(width=Sizes.BUTTON_WIDTH_SMALL)
        mc_reload_btn.attach_matrix(row=4, column=2, padx=Spacing.SMALL, pady=Spacing.SMALL)

        memory_title = self._make_label("記憶體設定 (MB):")
        memory_title.attach_matrix(row=5, column=0, sticky="nw", padx=Spacing.MEDIUM, pady=Spacing.SMALL)

        memory_container = qt.Frame(parent)
        memory_container.attach_matrix(
            row=5, column=1, columnspan=2, sticky="ew", padx=Spacing.MEDIUM, pady=Spacing.SMALL
        )

        memory_fields_row = qt.Frame(memory_container, fg_color="transparent")
        memory_fields_row.attach(fill="x", pady=(0, Spacing.SMALL))

        min_memory_frame = qt.Frame(memory_fields_row, fg_color="transparent")
        min_memory_frame.attach(side="left", fill="x", expand=True, padx=(0, Spacing.LARGE))
        min_label = qt.Label(min_memory_frame, text="最小記憶體:")
        min_label.configure(
            font=FontManager.get_font(size=FontSize.MEDIUM),
            text_color=Colors.TEXT_MUTED,
        )
        min_label.attach(fill="x")
        self.min_memory_entry = qt.Entry(min_memory_frame)
        self.min_memory_entry.setText("1024")
        self.min_memory_entry.configure(font=FontManager.get_font(size=FontSize.MEDIUM))
        self.min_memory_entry.attach(fill="x", pady=(Spacing.XS, 0))
        self.min_memory_entry.textChanged.connect(self.update_memory_warning)

        max_memory_frame = qt.Frame(memory_fields_row, fg_color="transparent")
        max_memory_frame.attach(side="left", fill="x", expand=True, padx=(Spacing.SMALL, 0))
        max_label = qt.Label(max_memory_frame, text="最大記憶體:")
        max_label.configure(
            font=FontManager.get_font(size=FontSize.MEDIUM),
            text_color=Colors.TEXT_MUTED,
        )
        max_label.attach(fill="x")
        self.max_memory_entry = qt.Entry(max_memory_frame)
        self.max_memory_entry.setText("2048")
        self.max_memory_entry.configure(font=FontManager.get_font(size=FontSize.MEDIUM))
        self.max_memory_entry.attach(fill="x", pady=(Spacing.XS, Spacing.LARGE))
        self.max_memory_entry.textChanged.connect(self.update_memory_warning)

        memory_tip = qt.Label(
            memory_container,
            text="最小記憶體選填，若留空由 Java 決定\n最大記憶體(必填)建議： 2048MB (最低) | 4096MB (一般) | 8192MB (多人遊戲)",
        )
        memory_tip.configure(
            font=FontManager.get_font(size=FontSize.MEDIUM),
            text_color=Colors.TEXT_MUTED,
        )
        memory_tip.setWordWrap(True)
        memory_tip.attach(anchor="nw", fill="x", pady=(Spacing.SMALL, 0))

        self.memory_warning_label = qt.Label(memory_container, text="")
        self.memory_warning_label.configure(
            font=FontManager.get_font(size=FontSize.SMALL_PLUS),
            text_color=Colors.TEXT_ERROR,
        )
        self.memory_warning_label.setWordWrap(True)
        self.memory_warning_label.attach(anchor="nw", fill="x", pady=(Spacing.XS, 0))

    def _update_combo_state(self, combo, message="載入中...", state="disabled") -> None:
        """統一更新下拉選單狀態"""
        combo.configure(values=[message])
        combo.set(message)
        combo.configure(state=state)

    def _run_background_task(self, task_func: Callable, error_msg: str, error_callback: Callable | None = None) -> None:
        """執行背景任務並處理錯誤"""
        TaskUtils.run_background_task(
            task_func,
            ui_queue=getattr(self, "ui_queue", None),
            widget=self,
            on_error=error_callback,
            error_log_prefix=error_msg,
            component="CreateServerFrame",
        )

    def preload_version_data(self) -> None:
        """預載入版本資訊並管理載入狀態"""
        self._update_combo_state(self.mc_version_combo, "正在載入 MC 版本...")
        self._update_combo_state(self.loader_version_combo, "等待 MC 版本選擇...")

        def task():
            """執行背景任務的工作內容。"""
            versions = self.version_manager.get_versions()

            def update_mc():
                self.update_versions(versions)
                self._update_combo_state(self.loader_version_combo, "請先選擇載入器類型...")

            self.ui_queue.put(update_mc)
            try:
                self.loader_manager.preload_loader_versions()
            except Exception as e:
                with contextlib.suppress(Exception):
                    record_and_mark(e, marker_path=Path(__file__), reason="preload_loader_versions_failed")
                logger.bind(component="").error(
                    f"預載入載入器版本失敗: {e}\n{traceback.format_exc()}", "CreateServerFrame"
                )

        def on_error():
            self._update_combo_state(self.mc_version_combo, "載入失敗")
            self._update_combo_state(self.loader_version_combo, "載入失敗")

        self._run_background_task(task, "預載入版本資訊失敗", on_error)

    def reload_mc_versions(self) -> None:
        """重新載入 Minecraft 版本"""
        self._update_combo_state(self.mc_version_combo)

        def task():
            """執行背景任務的工作內容。"""
            versions = self.version_manager.fetch_versions()
            self.ui_queue.put(lambda: self.update_versions(versions))
            self.ui_queue.put(lambda: self.mc_version_combo.configure(state="readonly"))

        self._run_background_task(
            task, "載入 MC 版本失敗", lambda: self._update_combo_state(self.mc_version_combo, message="載入失敗")
        )

    def reload_loader_versions(self) -> None:
        """重新載入載入器版本"""
        loader_type = self.loader_type_combo.currentText()
        mc_version = self.mc_version_combo.currentText()
        if not loader_type or not mc_version or loader_type == "Vanilla":
            return
        self._update_combo_state(self.loader_version_combo)

        def task():
            """執行背景任務的工作內容。"""
            self.loader_manager.clear_cache_file()
            self.loader_manager.preload_loader_versions()
            versions: list = []
            if loader_type.lower():
                versions = self.loader_manager.get_compatible_loader_versions(mc_version, loader_type)
            self.ui_queue.put(lambda: self._apply_loader_version_ui(versions, loader_type, mc_version))

        self._run_background_task(
            task,
            "載入載入器版本失敗",
            lambda: self._update_combo_state(self.loader_version_combo, "載入失敗"),
        )

    def _apply_loader_version_ui(self, versions: list, loader_type: str, mc_version: str) -> None:
        """將載入器版本清單套用至下拉選單 UI。"""
        try:
            if not is_qobject_alive(self.loader_version_combo):
                return
            current_type = self.loader_type_combo.currentText()
            current_version = self.mc_version_combo.currentText()
            if loader_type != current_type or mc_version != current_version:
                return
            if versions:
                v_names = [v.version if hasattr(v, "version") else str(v) for v in versions]
                self.loader_version_combo.configure(values=v_names)
                self.loader_version_combo.configure(state="readonly")
                if v_names:
                    self.loader_version_combo.set(v_names[0])
            else:
                self._update_combo_state(self.loader_version_combo, "無可用版本")
        except Exception as e:
            logger.exception(f"更新載入器版本 UI 失敗: {e}")

    def create_field(self, parent, row, label_text, default_value, var_name) -> tuple:
        """
        建立文字輸入欄位。

        Args:
            parent: 父容器。
            row: 要放置的表單列號。
            label_text: 欄位標籤文字。
            default_value: 預設值。
            var_name: 要建立的變數名稱前綴。

        Returns:
            `(Entry, str)` 元組。
        """
        self._make_label(label_text).attach_matrix(
            row=row, column=0, sticky="w", padx=Spacing.MEDIUM, pady=Spacing.SMALL
        )
        entry = qt.Entry(parent)
        entry.setText(default_value)
        entry.configure(font=FontManager.get_font(size=FontSize.MEDIUM))
        entry.attach_matrix(row=row, column=1, sticky="ew", padx=Spacing.MEDIUM, pady=Spacing.SMALL)
        setattr(self, f"{var_name}_entry", entry)
        return (entry, default_value)

    def create_buttons(self, parent) -> None:
        """
        建立操作按鈕，置於頁面底部右側。

        Args:
            parent: 父容器（main_frame）。
        """
        self.actions_frame = qt.Frame(parent, fg_color=Colors.BG_SECONDARY)
        self.actions_frame.attach(pady=(Spacing.LARGE, 0), anchor="e")

        self.create_button = self._make_button(
            self.actions_frame, "建立伺服器", command=self.create_server, kind="primary"
        )
        self.create_button.configure(width=Sizes.MOD_EXPORT_SAVE_BUTTON_WIDTH)
        self.create_button.attach(side="right", padx=(Spacing.SMALL, 0))

        reset_button = self._make_button(
            self.actions_frame, "重設表單", command=self._confirm_reset_form, kind="danger"
        )
        reset_button.configure(width=Sizes.MOD_EXPORT_SAVE_BUTTON_WIDTH)
        reset_button.attach(side="right", padx=(Spacing.SMALL, 0))

    def _confirm_reset_form(self) -> None:
        """重設表單前進行二次確認，避免誤觸。"""
        if UIUtils.ask_yes_no_cancel(
            "確認重設",
            "確定要重設表單嗎？\n所有已輸入的資料將恢復為預設值。",
            parent=self.window(),
            show_cancel=False,
        ):
            self.reset_form()

    def reset_form(self):
        """重設表單到預設值"""
        try:
            if hasattr(self, "release_versions") and self.release_versions:
                latest_version = self.release_versions[0].get("id", "未知版本")
                self.server_name_entry.setText(latest_version)
            else:
                self.server_name_entry.setText("我的伺服器")
            self.java_path_entry.setText("")
            self.loader_type_combo.set("Vanilla")
            self.loader_version_combo.set("無")
            self.loader_version_combo.configure(values=["無"])
            if hasattr(self, "mc_version_combo") and self.mc_version_combo.cget("values"):
                version_list = list(self.mc_version_combo.cget("values"))
                if version_list:
                    self.mc_version_combo.set(version_list[0])
            self.update_version_list()
            self.min_memory_entry.setText("1024")
            self.max_memory_entry.setText("2048")
            UIUtils.show_info("重設完成", "表單已重設為預設值", self.window())
        except Exception as e:
            with contextlib.suppress(Exception):
                record_and_mark(e, marker_path=Path(__file__), reason="reset_form_failed")
            logger.error(f"重設表單失敗: {e}\n{traceback.format_exc()}")
            UIUtils.show_error("重設失敗", f"重設表單時發生錯誤：\n{e!s}", self.window())

    def update_versions(self, versions: list) -> None:
        """
        更新版本列表，並預設選擇最新版本。

        Args:
            versions: 可用版本清單。
        """
        self.versions = versions
        self.release_versions = versions
        self.update_version_list()
        if self.release_versions:
            latest_version = self.release_versions[0].get("id")
            if self.server_name_entry.text() in ["我的伺服器", ""]:
                self.server_name_entry.setText(latest_version)

    def update_version_list(self) -> None:
        """更新版本列表顯示，並預設選擇最新版本"""
        if not hasattr(self, "versions") or not self.versions:
            self.mc_version_combo.configure(values=["載入中..."])
            self.mc_version_combo.set("載入中...")
            return
        display_versions = [v for v in self.release_versions if v.get("server_url")]
        if not display_versions:
            self.mc_version_combo.configure(values=["無可用版本"], state="disabled")
            self.mc_version_combo.set("無可用版本")
            return
        version_names = [v.get("id") for v in display_versions]
        self.mc_version_combo.configure(values=version_names, state="readonly")
        if display_versions:
            first_version = display_versions[0].get("id")
            self.mc_version_combo.set(first_version)
        self.update_server_config_ui()

    def update_server_config_ui(self, _event=None) -> None:
        """
        根據載入器類型與 Minecraft 版本自動更新伺服器名稱與載入器版本選單。

        Args:
            _event: 事件物件，供 trace callback 使用。
        """
        mc_version = self.mc_version_combo.currentText()
        loader_type = self.loader_type_combo.currentText()
        name = self.server_name_entry.text()
        auto_names = [
            "我的伺服器",
            "",
            CreateServerService.compose_server_name("Fabric", mc_version),
            CreateServerService.compose_server_name("Forge", mc_version),
            CreateServerService.compose_server_name("Vanilla", mc_version),
            CreateServerService.compose_server_name("Quilt", mc_version),
            CreateServerService.compose_server_name("NeoForge", mc_version),
        ]
        old_version = getattr(self, "old_mc_version", None)
        self.old_mc_version = mc_version
        if name in auto_names:
            self.server_name_entry.setText(CreateServerService.compose_server_name(loader_type, mc_version))
        else:
            version_candidates = tuple(v for v in (old_version, mc_version) if v)
            suffix = CreateServerService.extract_server_name_suffix(name, version_candidates)
            if suffix is not None:
                self.server_name_entry.setText(CreateServerService.compose_server_name(loader_type, mc_version, suffix))
        if old_version and old_version in name and (name == self.server_name_entry.text()):
            self.server_name_entry.setText(name.replace(old_version, mc_version))
        if loader_type == "Vanilla":
            self.loader_version_combo.configure(values=["無"], state="disabled")
            self.loader_version_combo.set("無")
            return
        self.loader_version_combo.configure(state="readonly")
        if not mc_version:
            return
        current_key = f"{loader_type}_{mc_version}"
        if hasattr(self, "_loading_key") and self._loading_key == current_key:
            return
        self._loading_key = current_key
        TaskUtils.run_async(self.load_loader_versions, loader_type, mc_version)

    def load_loader_versions(self, loader_type: str, mc_version: str) -> None:
        """
        載入載入器版本，並預設選擇最新版本（使用預載入的快取資料）。

        Args:
            loader_type: 載入器類型。
            mc_version: Minecraft 版本。
        """
        try:

            def set_loading():
                if is_qobject_alive(self.loader_version_combo):
                    self._update_combo_state(
                        self.loader_version_combo,
                        f"正在載入 {loader_type} 版本...",
                        "disabled",
                    )

            self.ui_queue.put(set_loading)
            versions = self.loader_manager.get_compatible_loader_versions(mc_version, loader_type)
            self.ui_queue.put(lambda: self._apply_loader_version_ui(versions, loader_type, mc_version))
        except Exception as e:
            logger.exception(f"載入載入器版本失敗: {e}")
            self.ui_queue.put(lambda: self._update_combo_state(self.loader_version_combo, "載入失敗"))

    def create_server(self) -> None:
        """建立伺服器按鈕點擊處理"""
        parent_window = self.window()
        progress_dialog = None
        try:
            inputs = ServerConfigInputs(
                server_name=self.server_name_entry.text().strip(),
                mc_version=self.mc_version_combo.currentText().strip(),
                loader_type=self.loader_type_combo.currentText().strip(),
                loader_version=self.loader_version_combo.currentText().strip(),
                min_memory=self.min_memory_entry.text().strip(),
                max_memory=self.max_memory_entry.text().strip(),
                system_memory=SystemUtils.get_total_memory_mb(),
                servers_root=self.repository.servers_root,
            )

            val_result = CreateServerService.validate_server_config_inputs(inputs)
            if not val_result.is_valid:
                UIUtils.show_error("錯誤", val_result.errors[0], self.window())
                return

            config = CreateServerService.build_server_config(inputs)

            progress_dialog = TaskUtils.call_on_ui(
                parent_window,
                lambda: ProgressDialog(parent_window, "正在建立伺服器"),
                timeout=10,
            )
            if progress_dialog is None:
                raise Exception("建立進度對話框失敗")

            def progress_callback(percent, status):
                return progress_dialog.update_progress(percent, status)

            shared_cancel_token = CancellationToken()

            def ask_proceed(title, msg):
                return UIUtils.ask_yes_no_cancel(title, msg, parent=self.window(), show_cancel=False)

            def do_download(cancel_token: CancellationToken | None = None):
                token = cancel_token or shared_cancel_token
                user_java_path = self.java_path_entry.text().strip() or None
                CreateServerService.execute_server_creation(
                    config=config,
                    server_crud=self.server_crud,
                    loader_manager=self.loader_manager,
                    progress_callback=progress_callback,
                    cancel_token=token,
                    user_java_path=user_java_path,
                    ask_proceed_callback=ask_proceed,
                )

            future = self.bg_tasks.run(do_download, cancel_token=shared_cancel_token)
            while not future.done():
                QtCore.QCoreApplication.processEvents()
                if progress_dialog.cancelled:
                    with contextlib.suppress(Exception):
                        shared_cancel_token.cancel()
                try:
                    future.result(timeout=0.1)
                except concurrent.futures.TimeoutError:
                    continue

            def on_success():
                progress_dialog.close()
                init_dialog = ServerInitializationDialog(
                    parent=self.window(),
                    server_config=config,
                    completion_callback=self._on_init_complete,
                )
                init_dialog.start_initialization()

            self._schedule_ui_job("_create_server_success_job", 1000, on_success)
        except Exception as error:
            logger.warning(f"建立伺服器時發生錯誤: {error}", "CreateServerFrame")
            error_str = str(error)
            if "下載" in error_str or "下載失敗" in error_str:
                if progress_dialog:
                    progress_dialog.close()
            else:

                def on_error(error=error):
                    if progress_dialog:
                        progress_dialog.close()
                    UIUtils.show_error("建立失敗", f"建立伺服器時發生錯誤：\n{error}", parent_window)

                self._schedule_ui_job("_create_server_error_job", 0, on_error)

    def _on_init_complete(self, server_config: ServerConfig, init_dialog: Any) -> None:
        """初始化對話框完成後的回調，關閉對話框並通知主視窗。"""
        if init_dialog and init_dialog.is_alive():
            init_dialog.destroy()
        self.callback(server_config)

    def destroy(self, destroyWindow: bool = True, destroySubWindows: bool = True) -> None:
        """
        銷毀頁面前先清理待執行排程工作。

        Args:
            destroyWindow: 是否銷毀目前 Qt 視窗。
            destroySubWindows: 是否一併銷毀子視窗。
        """
        self._cancel_create_server_jobs()
        super().destroy(destroyWindow, destroySubWindows)


class ServerInitializationDialog:
    """伺服器初始化對話框 — 首次啟動伺服器以產生世界檔案與設定。"""

    def __init__(
        self,
        parent: Any,
        server_config: ServerConfig,
        completion_callback: Callable[[ServerConfig, Any], None] | None = None,
    ) -> None:
        self._parent = parent
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
        self._console_pump_job: Any = None
        self._process_output_buffer = ""
        self._stop_sent = False

    # ── console 輸出佇列 ──────────────────────────────────────────

    def _enqueue_console(self, text: str) -> None:
        """將文字加入 console 輸出佇列，稍後由 UI 排程處理。"""
        with contextlib.suppress(Exception):
            self._console_queue.put_nowait(text)

    def _start_console_pump(self) -> None:
        """啟動 console 輸出排程，將佇列中的文字定期更新到 UI。"""
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
            chunks: list[str] = []
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

    def _update_console(self, text: str) -> None:
        with contextlib.suppress(Exception):
            if self.init_dialog and self.init_dialog.is_alive() and self.console_text:
                self.console_text.insert("end", text)
                self.console_text.see("end")

    # ── 排程管理 ──────────────────────────────────────────────────

    def _schedule_dialog_job(self, job_attr: str, delay_ms: int, callback: Callable[[], Any]) -> None:
        dialog = self.init_dialog
        if not dialog or not dialog.is_alive():
            return
        UIUtils.schedule_debounce(dialog, job_attr, delay_ms, callback, owner=self)

    def _cancel_dialog_jobs(self) -> None:
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

    # ── 公開 API ──────────────────────────────────────────────────

    def start_initialization(self) -> None:
        """啟動初始化對話框流程：建立視窗、設定 UI、啟動伺服器程序。"""
        self._create_dialog()
        self._setup_ui()
        self._run_server()

    # ── 對話框建立 ────────────────────────────────────────────────

    def _create_dialog(self) -> None:
        self.init_dialog = qt.PlainWindow(
            title=f"初始化伺服器 - {self.server_config.name}",
        )
        self.init_dialog.resize(Sizes.DIALOG_LARGE_WIDTH, Sizes.DIALOG_LARGE_HEIGHT)
        self.init_dialog.configure(fg_color=Colors.BG_CONSOLE)
        self.init_dialog.show()

    def _setup_ui(self) -> None:
        self._create_title_and_info()
        self._create_console()
        self._create_progress_label()
        self._create_buttons()
        self._setup_timeout()

    def _create_title_and_info(self) -> None:
        title_label = qt.Label(
            self.init_dialog,
            text=f"正在初始化伺服器: {self.server_config.name}",
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
            text_color=Colors.CONSOLE_TEXT,
            fg_color=Colors.BG_CONSOLE,
        )
        title_label.attach(anchor="center", pady=Spacing.SMALL_PLUS)
        info_label = qt.Label(
            self.init_dialog,
            text="伺服器正在首次啟動，請等待初始化完成...\n系統會自動在完成後關閉伺服器",
            font=FontManager.get_font(size=FontSize.LARGE),
            text_color=Colors.CONSOLE_TEXT,
            fg_color=Colors.BG_CONSOLE,
        )
        info_label.attach(anchor="center", justify="center", pady=Spacing.TINY)

    def _create_console(self) -> None:
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
        if not self.init_dialog:
            return
        self.progress_label = qt.Label(
            self.init_dialog,
            text="狀態: 準備啟動...",
            font=FontManager.get_font(size=FontSize.INPUT, weight="bold"),
            text_color=Colors.CONSOLE_TEXT,
            fg_color=Colors.BG_CONSOLE,
        )
        self.progress_label.attach(anchor="center", pady=Spacing.TINY)

    def _create_buttons(self) -> None:
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
            fg_color=Colors.BUTTON_DANGER,
            hover_color=Colors.BUTTON_DANGER_HOVER,
            text_color=Colors.TEXT_ON_DARK,
            border_width=0,
            corner_radius=Spacing.TINY,
        )
        self.close_button.attach(anchor="center")

    def _setup_timeout(self) -> None:
        if self.init_dialog:
            self._schedule_dialog_job("_init_timeout_job", 120000, self._timeout_force_close)

    # ── 關閉邏輯 ──────────────────────────────────────────────────

    def _close_init_server(self) -> None:
        if self.done_detected:
            if self.init_dialog and self.init_dialog.is_alive():
                self._cancel_dialog_jobs()
                UIUtils.show_info("初始化完成", "伺服器已成功初始化並安全關閉。", parent=self._parent)
                if self.completion_callback:
                    self.completion_callback(self.server_config, self.init_dialog)
                else:
                    self.init_dialog.destroy()
        else:
            self._terminate_server_process()
            if self.init_dialog and self.init_dialog.is_alive():
                self._cancel_dialog_jobs()
                UIUtils.show_warning("強制關閉", "伺服器初始化未完成，已強制關閉。請檢查伺服器日誌。", self._parent)
                self.init_dialog.destroy()

    def _terminate_server_process(self) -> None:
        with contextlib.suppress(Exception):
            if self.server_process and self.server_process.state() != QtCore.QProcess.ProcessState.NotRunning:
                self.server_process.terminate()
                if not self.server_process.waitForFinished(5000):
                    self.server_process.kill()
            if self.server_process is not None:
                with contextlib.suppress(Exception):
                    SystemUtils.unregister_managed_process(self.server_path, self.server_process_pid)

    def _timeout_force_close(self) -> None:
        if self.init_dialog and self.init_dialog.is_alive() and not self.done_detected:
            self._close_init_server()

    # ── 伺服器啟動 ────────────────────────────────────────────────

    def _run_server(self) -> None:
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
            process = SubprocessUtils.create_qprocess_checked(java_cmd, cwd=str(self.server_path))
            self.server_process = process
            process.started.connect(self._on_server_process_started)
            process.readyReadStandardOutput.connect(self._on_server_process_output)
            process.finished.connect(self._on_server_process_finished)
            process.errorOccurred.connect(self._on_server_process_error)
            process.start()
        except Exception as e:
            logger.exception(f"伺服器啟動失敗: {e}")
            self._handle_server_error(str(e))

    def _build_java_command(self) -> list[str]:
        loader_type = str(self.server_config.loader_type or "").lower()
        if loader_type == "forge":
            return self._build_forge_command()
        java_cmd = ServerCommands.build_java_command(self.server_config, return_list=True)
        if isinstance(java_cmd, str):
            java_cmd = [java_cmd]
        self._enqueue_console(f"執行命令: {' '.join(java_cmd)}\n\n")
        return java_cmd

    def _build_forge_command(self) -> list[str]:
        user_args = self.server_path / "user_jvm_args.txt"
        if user_args.exists():
            ServerDetectionUtils.update_forge_user_jvm_args(self.server_path, self.server_config)
        start_bat = self.server_path / "start_server.bat"
        java_cmd: list[str] | None = None
        if user_args.exists() and start_bat.exists():
            java_cmd = self._extract_java_command_from_bat(start_bat)
        if java_cmd is None:
            raw_cmd = ServerCommands.build_java_command(self.server_config, return_list=True)
            java_cmd = [raw_cmd] if isinstance(raw_cmd, str) else raw_cmd
            self._enqueue_console(f"執行命令: {' '.join(java_cmd)}\n\n")
        return java_cmd

    def _extract_java_command_from_bat(self, start_bat: Path) -> list[str] | None:
        with contextlib.suppress(Exception):
            content = PathUtils.read_text_file(start_bat, errors="ignore")
            if content:
                for line in content.splitlines():
                    if re.search(r"\bjavaw?(?:\.exe)?\b.*@user_jvm_args\.txt\b", line, re.IGNORECASE):
                        cleaned = re.sub(r"\s*[%$]\*?$", "", line.strip())
                        if cleaned.lower().startswith("call "):
                            cleaned = cleaned[5:].lstrip()
                        return ServerCommands.split_windows_command_line(cleaned)
        return None

    # ── QProcess signal handlers ───────────────────────────────────

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
        except Exception:
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

    # ── 輸出解析 ──────────────────────────────────────────────────

    def _process_server_output(self, output: str) -> None:
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
                        text="完成初始化",
                        command=self._close_init_server,
                        fg_color=Colors.BUTTON_SUCCESS,
                        hover_color=Colors.BUTTON_SUCCESS_HOVER
                        if hasattr(Colors, "BUTTON_SUCCESS_HOVER")
                        else Colors.BUTTON_SUCCESS,
                        text_color=Colors.TEXT_ON_DARK,
                    )

            self._schedule_dialog_job("_init_close_button_job", 0, update_close_button)

    def _handle_server_ready(self, output: str) -> None:
        if "ERROR" in output.upper() or "WARN" in output.upper():
            self._enqueue_console(f"[注意] {output}")

        def update_closing_status() -> None:
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
        if self.init_dialog is None:
            return

        if self.done_detected:

            def complete_init() -> None:
                if self.init_dialog and self.init_dialog.is_alive():
                    self._update_console("[系統] 伺服器初始化完成！\n")
                    if self.progress_label and self.progress_label.is_alive():
                        self.progress_label.configure(text="狀態: 初始化完成")

            self._schedule_dialog_job("_init_complete_job", 0, complete_init)
            if self.completion_callback:
                _cb = self.completion_callback
                _cfg = self.server_config
                _dlg = self.init_dialog
                self._schedule_dialog_job(
                    "_init_transition_job",
                    2000,
                    lambda: _cb(_cfg, _dlg),
                )
        else:

            def show_error() -> None:
                if self.init_dialog and self.init_dialog.is_alive():
                    self._update_console("[系統] 伺服器啟動可能有問題，請檢查輸出\n")
                    if self.progress_label and self.progress_label.is_alive():
                        self.progress_label.configure(text="狀態: 啟動異常")

            self._schedule_dialog_job("_init_error_job", 0, show_error)

    def _handle_server_error(self, err_msg: str) -> None:
        if self.init_dialog is None:
            return

        def show_error() -> None:
            if self.init_dialog and self.init_dialog.is_alive():
                self._update_console(f"[錯誤] 啟動失敗: {err_msg}\n")
                if self.progress_label and self.progress_label.is_alive():
                    self.progress_label.configure(text="狀態: 啟動失敗")

        self._schedule_dialog_job("_init_error_job", 0, show_error)


__all__ = ["CreateServerFrame", "ServerInitializationDialog"]
