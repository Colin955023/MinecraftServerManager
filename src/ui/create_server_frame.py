"""建立伺服器頁面
負責建立新 Minecraft 伺服器的使用者介面。
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import queue
import threading
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core import LoaderManager, MinecraftVersionManager, ServerManager
from ..models import ServerConfig
from ..utils import (
    CancellationToken,
    Colors,
    FontSize,
    JavaUtils,
    Sizes,
    SystemUtils,
    UIUtils,
    get_logger,
    get_shared_manager,
    record_and_mark,
)
from ..utils.ui_support.qt_runtime import QtCore, QtGui, QtWidgets, ValueState, is_qobject_alive
from . import CustomDropdown, FontManager, ProgressDialog, TaskUtils
from .ui_config import NativeQtStyle, resolve_color

logger = get_logger().bind(component="CreateServerFrame")


def _qt_font(font: Any) -> QtGui.QFont:
    return getattr(font, "font", font)


def _qt_color(color: Any) -> str:
    if getattr(NativeQtStyle, "_dark", False) and color in {
        Colors.TEXT_PRIMARY,
        Colors.TEXT_PRIMARY_CONTRAST,
        Colors.TEXT_HEADING,
        Colors.TEXT_SECONDARY,
        Colors.TEXT_MUTED,
        Colors.TEXT_TERTIARY,
    }:
        return Colors.TEXT_ON_DARK
    return resolve_color(color)


def _set_layout_margins(layout: QtWidgets.QLayout, *margins: int) -> None:
    layout.setContentsMargins(*(int(value) for value in margins))


class CreateServerFrame(QtWidgets.QWidget):
    """建立伺服器頁面"""

    @staticmethod
    def get_system_memory_mb() -> int:
        """獲取系統記憶體容量。

        Returns:
            系統總記憶體容量（MB），失敗時回傳 0。
        """
        try:
            return SystemUtils.get_total_memory_mb()
        except Exception as e:
            with __import__("contextlib").suppress(Exception):
                record_and_mark(e, marker_path=Path(__file__), reason="get_system_memory_failed")
            logger.bind(component="").error(
                f"無法獲取系統記憶體資訊: {e}\n{traceback.format_exc()}", "CreateServerFrame"
            )
            UIUtils.show_error("錯誤", f"無法獲取系統記憶體資訊: {e}", topmost=True)
            return 0

    def update_memory_warning(self) -> None:
        """更新記憶體使用警告標籤"""
        try:
            max_memory_str = self.max_memory_var.get().strip()
            min_memory_str = self.min_memory_var.get().strip()
            if not max_memory_str:
                self._set_warning_text("")
                return
            max_memory = int(max_memory_str)
            min_memory = int(min_memory_str)
            system_memory = self.get_system_memory_mb()
            half_system_memory = system_memory // 2
            if (max_memory > system_memory or min_memory > system_memory) and min_memory >= 1024:
                warning_text = f"⚠️ 警告：設定記憶體超過系統總記憶體 ({system_memory}MB)"
                self._set_warning_text(warning_text, Colors.TEXT_ERROR)
            elif (max_memory > half_system_memory or min_memory > half_system_memory) and min_memory >= 1024:
                warning_text = f"⚠️ 警告：設定記憶體超過系統記憶體的一半 ({half_system_memory}MB)"
                self._set_warning_text(warning_text, Colors.TEXT_WARNING)
            elif min_memory > max_memory:
                warning_text = "⚠️ 警告：最小記憶體必須小於最大記憶體"
                self._set_warning_text(warning_text, Colors.TEXT_ERROR)
            else:
                self._set_warning_text("")
        except ValueError:
            if not min_memory_str:
                self._set_warning_text("")
            else:
                self._set_warning_text("⚠️ 警告：記憶體設定必須為有效的整數", Colors.TEXT_ERROR)
        except Exception as e:
            with __import__("contextlib").suppress(Exception):
                record_and_mark(e, marker_path=Path(__file__), reason="update_memory_warning_failed")
            logger.bind(component="").error(f"更新記憶體警告失敗: {e}\n{traceback.format_exc()}", "CreateServerFrame")
            UIUtils.show_error("錯誤", f"更新記憶體警告失敗: {e}", self.window())

    def _set_warning_text(self, text: str, color: Any = Colors.TEXT_ERROR) -> None:
        self.memory_warning_label.setText(text)
        self.memory_warning_label.setStyleSheet(NativeQtStyle.color_style(_qt_color(color)))

    def _make_label(self, text: str, *, muted: bool = False, bold: bool = True) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setFont(FontManager.get_font(size=FontSize.MEDIUM, weight="bold" if bold else "normal"))
        label.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_MUTED if muted else Colors.TEXT_PRIMARY)))
        label.setMinimumWidth(143)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        return label

    def _style_control(self, widget, *, height: int = 20) -> None:
        widget.setMinimumHeight(height)
        widget.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)

    def _make_button(self, text: str, command: Callable[[], Any], *, kind: str = "secondary") -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        button.setProperty("msm_button_kind", kind)
        button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        button.setFont(_qt_font(FontManager.get_font(size=FontSize.MEDIUM, weight="bold")))
        button.setMinimumHeight(30)
        button.clicked.connect(lambda _checked=False: command())
        button.setStyleSheet(NativeQtStyle.create_button(kind=kind))
        return button

    def _bind_entry(self, entry: QtWidgets.QLineEdit, variable: ValueState) -> None:
        entry.setText(str(variable.get()))
        entry.textChanged.connect(variable.set)

        def _sync_from_var(value: object) -> None:
            text = str(value or "")
            if entry.text() != text:
                entry.setText(text)

        variable.changed.connect(_sync_from_var)

    def create_java_path_field(self, parent, row) -> None:
        """建立 Java 路徑欄位（可手動輸入/瀏覽）。

        Args:
            parent: 父容器。
            row: 要放置的表單列號。
        """
        parent.addWidget(self._make_label("Java 執行檔路徑 (可選):"), row, 0)
        self.java_path_var = ValueState("")
        java_path_entry = QtWidgets.QLineEdit(self.form_panel)
        java_path_entry.setFont(FontManager.get_font(size=FontSize.MEDIUM))
        self._bind_entry(java_path_entry, self.java_path_var)
        self._style_control(java_path_entry)
        parent.addWidget(java_path_entry, row, 1)

        def browse_java():
            path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
                self.window(), "選擇 javaw.exe", "", "Java 執行檔 (javaw.exe);;所有檔案 (*)"
            )
            if path:
                self.java_path_var.set(path)

        browse_btn = self._make_button("瀏覽...", browse_java)
        browse_btn.setFixedWidth(72)
        parent.addWidget(browse_btn, row, 2)

        def auto_detect():
            mc_version = self.mc_version_var.get() if hasattr(self, "mc_version_var") else None
            if not mc_version:
                UIUtils.show_warning("Java 偵測", "請先選擇 Minecraft 版本！", self.window())
                return
            java_path = JavaUtils.get_best_java_path(mc_version, interaction=UIUtils)
            if java_path:
                java_path_win = str(Path(java_path))
                self.java_path_var.set(java_path_win)

        auto_btn = self._make_button("自動偵測", auto_detect)
        auto_btn.setFixedWidth(75)
        parent.addWidget(auto_btn, row, 3)

    def __init__(
        self,
        parent,
        version_manager: MinecraftVersionManager,
        loader_manager: LoaderManager,
        callback: Callable,
        server_manager: ServerManager,
    ):
        super().__init__(parent)
        self.version_manager = version_manager
        self.loader_manager = loader_manager
        self.callback = callback
        self.server_manager = server_manager
        self.versions: list = []
        self.release_versions: list = []
        self._loading_key: str | None = None
        self._create_server_progress_job = None
        self._create_server_success_job = None
        self._create_server_error_job = None
        self.server_name_var = ValueState("")
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
        self.setStyleSheet(NativeQtStyle.create_page)
        main_layout = QtWidgets.QVBoxLayout(self)
        _set_layout_margins(main_layout, 0, 0, 0, 0)
        main_layout.setSpacing(11)

        self.scroll_area = QtWidgets.QScrollArea(self)
        self.scroll_area.setObjectName("CreateServerScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(NativeQtStyle.create_page)
        self.content_widget = QtWidgets.QWidget()
        self.content_widget.setObjectName("CreateServerContent")
        self.content_widget.setStyleSheet(NativeQtStyle.create_page)
        content_layout = QtWidgets.QVBoxLayout(self.content_widget)
        _set_layout_margins(content_layout, 0, 0, 0, 0)
        content_layout.setSpacing(11)
        self.scroll_area.setWidget(self.content_widget)
        main_layout.addWidget(self.scroll_area, 1)

        title_label = QtWidgets.QLabel("建立新伺服器", self.content_widget)
        self.title_label = title_label
        title_label.setFont(_qt_font(FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold")))
        title_label.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_HEADING)))
        content_layout.addWidget(title_label)

        eula_frame = QtWidgets.QFrame(self.content_widget)
        self.eula_frame = eula_frame
        eula_frame.setObjectName("EulaNotice")
        eula_frame.setStyleSheet(NativeQtStyle.eula_notice)
        eula_layout = QtWidgets.QHBoxLayout(eula_frame)
        _set_layout_margins(eula_layout, 6, 5, 6, 5)
        eula_layout.setSpacing(8)
        eula_icon = QtWidgets.QLabel("⚠️", eula_frame)
        self.eula_icon = eula_icon
        eula_icon.setFont(_qt_font(FontManager.get_font(size=FontSize.LARGE, weight="bold")))
        eula_icon.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.BUTTON_WARNING_HOVER)))
        eula_layout.addWidget(eula_icon, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        eula_link = QtWidgets.QLabel(
            "請務必閱讀並同意 Minecraft EULA 條款 (點我閱讀)\n"
            "點擊建立即表示你同意Minecraft條款，任何違法行為本軟體不負責任",
            eula_frame,
        )
        self.eula_link = eula_link
        eula_link.setFont(_qt_font(FontManager.get_font(size=FontSize.MEDIUM, weight="bold", underline=True)))
        eula_link.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_WARNING)))
        eula_link.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        eula_link.mousePressEvent = lambda _event: UIUtils.open_external("https://aka.ms/MinecraftEULA")  # type: ignore[method-assign]
        eula_layout.addWidget(eula_link, 1)
        content_layout.addWidget(eula_frame)

        self.form_panel = QtWidgets.QFrame(self.content_widget)
        self.form_panel.setObjectName("CreateFormPanel")
        self.form_panel.setStyleSheet(NativeQtStyle.create_form_panel)
        form_layout = QtWidgets.QGridLayout(self.form_panel)
        _set_layout_margins(form_layout, 0, 3, 0, 0)
        form_layout.setHorizontalSpacing(8)
        form_layout.setVerticalSpacing(8)
        form_layout.setColumnStretch(1, 1)
        self.create_form(form_layout)
        content_layout.addWidget(self.form_panel)
        content_layout.addStretch(1)
        self.create_buttons(main_layout)

    def apply_theme_styles(self) -> None:
        """重新套用目前主題到建立伺服器頁。"""
        self.setStyleSheet(NativeQtStyle.create_page)
        if hasattr(self, "scroll_area"):
            self.scroll_area.setStyleSheet(NativeQtStyle.create_page)
        if hasattr(self, "content_widget"):
            self.content_widget.setStyleSheet(NativeQtStyle.create_page)
        if hasattr(self, "title_label"):
            self.title_label.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_HEADING)))
        if hasattr(self, "eula_frame"):
            self.eula_frame.setStyleSheet(NativeQtStyle.eula_notice)
        if hasattr(self, "eula_icon"):
            self.eula_icon.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.BUTTON_WARNING_HOVER)))
        if hasattr(self, "eula_link"):
            self.eula_link.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_WARNING)))
        if hasattr(self, "form_panel"):
            self.form_panel.setStyleSheet(NativeQtStyle.create_form_panel)
        if hasattr(self, "actions_frame"):
            self.actions_frame.setStyleSheet(NativeQtStyle.create_actions)
        if hasattr(self, "memory_warning_label"):
            self.memory_warning_label.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_ERROR)))
        special_labels = {
            getattr(self, "eula_icon", None),
            getattr(self, "eula_link", None),
            getattr(self, "memory_warning_label", None),
        }
        for label in self.findChildren(QtWidgets.QLabel):
            if label in special_labels:
                continue
            label.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_PRIMARY)))
        for dropdown in self.findChildren(CustomDropdown):
            dropdown.setStyleSheet(NativeQtStyle.custom_dropdown)
        for button in self.findChildren(QtWidgets.QPushButton):
            kind = str(button.property("msm_button_kind") or "secondary")
            button.setStyleSheet(NativeQtStyle.create_button(kind=kind))

    def create_form(self, parent) -> None:
        """建立表單。

        Args:
            parent: 父容器。
        """
        content_frame = parent
        self.create_field(content_frame, 0, "伺服器名稱:", "我的伺服器", "server_name")
        self.create_java_path_field(content_frame, 1)
        content_frame.addWidget(self._make_label("模組載入器:"), 2, 0)
        self.loader_type_var = ValueState("Vanilla")
        self.loader_type_combo = CustomDropdown(
            self.form_panel,
            variable=self.loader_type_var,
            values=["Vanilla", "Fabric", "Forge", "Quilt", "NeoForge"],
            width=Sizes.DROPDOWN_WIDTH,
            font_size=FontSize.MEDIUM,
            dropdown_font_size=FontSize.MEDIUM,
            state="readonly",
        )
        self._style_control(self.loader_type_combo)
        content_frame.addWidget(self.loader_type_combo, 2, 1)
        self.loader_type_var.trace_add("write", lambda *_args: self.update_server_config_ui())
        loader_version_row = 3
        content_frame.addWidget(self._make_label("載入器版本:"), loader_version_row, 0)
        self.loader_version_var = ValueState("無")
        self.loader_version_combo = CustomDropdown(
            self.form_panel,
            variable=self.loader_version_var,
            values=["無"],
            width=Sizes.DROPDOWN_WIDTH,
            font_size=FontSize.MEDIUM,
            dropdown_font_size=FontSize.MEDIUM,
            state="disabled",
        )
        self._style_control(self.loader_version_combo)
        content_frame.addWidget(self.loader_version_combo, loader_version_row, 1)
        loader_reload_btn = self._make_button("⟳", self.reload_loader_versions)
        loader_reload_btn.setFixedWidth(72)
        content_frame.addWidget(loader_reload_btn, loader_version_row, 2)
        content_frame.addWidget(self._make_label("Minecraft 版本:"), 4, 0)
        self.mc_version_var = ValueState("")
        self.mc_version_combo = CustomDropdown(
            self.form_panel,
            variable=self.mc_version_var,
            values=["載入中..."],
            command=self.update_server_config_ui,
            width=Sizes.DROPDOWN_COMPACT_WIDTH,
            font_size=FontSize.MEDIUM,
            dropdown_font_size=FontSize.MEDIUM,
            state="readonly",
        )
        self._style_control(self.mc_version_combo)
        content_frame.addWidget(self.mc_version_combo, 4, 1)
        mc_reload_btn = self._make_button("⟳", self.reload_mc_versions)
        mc_reload_btn.setFixedWidth(72)
        content_frame.addWidget(mc_reload_btn, 4, 2)

        memory_title = self._make_label("記憶體設定 (MB):")
        content_frame.addWidget(memory_title, 5, 0)
        memory_container = QtWidgets.QWidget(self.form_panel)
        memory_layout = QtWidgets.QVBoxLayout(memory_container)
        _set_layout_margins(memory_layout, 0, 0, 0, 0)
        memory_layout.setSpacing(5)
        memory_input_layout = QtWidgets.QHBoxLayout()
        memory_input_layout.setSpacing(8)
        self.min_memory_var = ValueState("1024")
        min_memory_frame = QtWidgets.QWidget(memory_container)
        min_layout = QtWidgets.QVBoxLayout(min_memory_frame)
        _set_layout_margins(min_layout, 0, 0, 0, 0)
        min_layout.setSpacing(3)
        min_label = QtWidgets.QLabel("最小記憶體:", min_memory_frame)
        min_label.setFont(_qt_font(FontManager.get_font(size=FontSize.MEDIUM)))
        min_label.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_MUTED)))
        min_layout.addWidget(min_label)
        self.min_memory_entry = QtWidgets.QLineEdit(min_memory_frame)
        self.min_memory_entry.setFont(FontManager.get_font(size=FontSize.MEDIUM))
        self._bind_entry(self.min_memory_entry, self.min_memory_var)
        self._style_control(self.min_memory_entry)
        min_layout.addWidget(self.min_memory_entry)
        memory_input_layout.addWidget(min_memory_frame, 1)

        self.max_memory_var = ValueState("2048")
        max_memory_frame = QtWidgets.QWidget(memory_container)
        max_layout = QtWidgets.QVBoxLayout(max_memory_frame)
        _set_layout_margins(max_layout, 0, 0, 0, 0)
        max_layout.setSpacing(3)
        max_label = QtWidgets.QLabel("最大記憶體:", max_memory_frame)
        max_label.setFont(_qt_font(FontManager.get_font(size=FontSize.MEDIUM)))
        max_label.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_MUTED)))
        max_layout.addWidget(max_label)
        self.max_memory_entry = QtWidgets.QLineEdit(max_memory_frame)
        self.max_memory_entry.setFont(FontManager.get_font(size=FontSize.MEDIUM))
        self._bind_entry(self.max_memory_entry, self.max_memory_var)
        self._style_control(self.max_memory_entry)
        max_layout.addWidget(self.max_memory_entry)
        memory_input_layout.addWidget(max_memory_frame, 1)
        memory_layout.addLayout(memory_input_layout)
        self.max_memory_var.trace_add("write", lambda *_args: self.update_memory_warning())
        self.min_memory_var.trace_add("write", lambda *_args: self.update_memory_warning())
        memory_tip = QtWidgets.QLabel(
            "最小記憶體選填，若留空由 Java 決定\n最大記憶體(必填)建議： 2048MB (最低) | 4096MB (一般) | 8192MB (多人遊戲)",
            memory_container,
        )
        memory_tip.setFont(FontManager.get_font(size=FontSize.MEDIUM))
        memory_tip.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_MUTED)))
        memory_tip.setWordWrap(True)
        memory_layout.addWidget(memory_tip)
        self.memory_warning_label = QtWidgets.QLabel("", memory_container)
        self.memory_warning_label.setFont(FontManager.get_font(size=FontSize.SMALL_PLUS))
        self.memory_warning_label.setStyleSheet(NativeQtStyle.color_style(_qt_color(Colors.TEXT_ERROR)))
        self.memory_warning_label.setWordWrap(True)
        memory_layout.addWidget(self.memory_warning_label)
        content_frame.addWidget(memory_container, 5, 1, 1, 2)

    def _update_combo_state(self, combo, var=None, message="載入中...", state="disabled") -> None:
        """統一更新下拉選單狀態"""
        combo.configure(values=[message])
        combo.set(message)
        if var:
            var.set(message)
        combo.configure(state=state)

    def _run_background_task(self, task_func: Callable, error_msg: str, error_callback: Callable | None = None) -> None:
        """執行背景任務並處理錯誤"""
        TaskUtils.run_in_daemon_thread(
            task_func,
            ui_queue=getattr(self, "ui_queue", None),
            widget=self,
            on_error=error_callback,
            error_log_prefix=error_msg,
            component="CreateServerFrame",
        )

    def preload_version_data(self) -> None:
        """預載入版本資訊並管理載入狀態"""
        self._update_combo_state(self.mc_version_combo, self.mc_version_var, "正在載入 MC 版本...")
        self._update_combo_state(self.loader_version_combo, self.loader_version_var, "等待 MC 版本選擇...")

        def task():
            versions = self.version_manager.get_versions()

            def update_mc():
                self.update_versions(versions)
                self._update_combo_state(self.loader_version_combo, self.loader_version_var, "請先選擇載入器類型...")

            self.ui_queue.put(update_mc)
            try:
                self.loader_manager.preload_loader_versions()
            except Exception as e:
                with __import__("contextlib").suppress(Exception):
                    record_and_mark(e, marker_path=Path(__file__), reason="preload_loader_versions_failed")
                logger.bind(component="").error(
                    f"預載入載入器版本失敗: {e}\n{traceback.format_exc()}", "CreateServerFrame"
                )

        def on_error():
            self._update_combo_state(self.mc_version_combo, self.mc_version_var, "載入失敗")
            self._update_combo_state(self.loader_version_combo, self.loader_version_var, "載入失敗")

        self._run_background_task(task, "預載入版本資訊失敗", on_error)

    def reload_mc_versions(self) -> None:
        """重新載入 Minecraft 版本"""
        self._update_combo_state(self.mc_version_combo)

        def task():
            versions = self.version_manager.fetch_versions()
            self.ui_queue.put(lambda: self.update_versions(versions))
            self.ui_queue.put(lambda: self.mc_version_combo.configure(state="readonly"))

        self._run_background_task(
            task, "載入 MC 版本失敗", lambda: self._update_combo_state(self.mc_version_combo, message="載入失敗")
        )

    def reload_loader_versions(self) -> None:
        """重新載入載入器版本"""
        loader_type = self.loader_type_var.get()
        mc_version = self.mc_version_var.get()
        if not loader_type or not mc_version or loader_type == "Vanilla":
            return
        self._update_combo_state(self.loader_version_combo, self.loader_version_var)

        def task():
            self.loader_manager.clear_cache_file()
            self.loader_manager.preload_loader_versions()
            versions = []
            if loader_type.lower():
                versions = self.loader_manager.get_compatible_loader_versions(mc_version, loader_type)

            def update_ui():
                if not is_qobject_alive(self.loader_version_combo):
                    return
                if versions:
                    v_names = []
                    for v in versions:
                        if hasattr(v, "version"):
                            v_names.append(v.version)
                        elif isinstance(v, str):
                            v_names.append(v)
                        else:
                            v_names.append(str(v))
                    self.loader_version_combo.configure(values=v_names)
                    if v_names:
                        self.loader_version_combo.set(v_names[0])
                        self.loader_version_var.set(v_names[0])
                    self.loader_version_combo.configure(state="readonly")
                else:
                    self._update_combo_state(self.loader_version_combo, self.loader_version_var, "無可用版本")

            self.ui_queue.put(update_ui)

        self._run_background_task(
            task,
            "載入載入器版本失敗",
            lambda: self._update_combo_state(self.loader_version_combo, self.loader_version_var, "載入失敗"),
        )

    def create_field(self, parent, row, label_text, default_value, var_name) -> tuple:
        """建立文字輸入欄位。

        Args:
            parent: 父容器。
            row: 要放置的表單列號。
            label_text: 欄位標籤文字。
            default_value: 預設值。
            var_name: 要建立的變數名稱前綴。

        Returns:
            `(ValueState, QLineEdit)` 元組。
        """
        parent.addWidget(self._make_label(label_text), row, 0)
        var = ValueState(default_value)
        setattr(self, f"{var_name}_var", var)
        entry = QtWidgets.QLineEdit(self.form_panel)
        entry.setFont(FontManager.get_font(size=FontSize.MEDIUM))
        self._bind_entry(entry, var)
        self._style_control(entry)
        parent.addWidget(entry, row, 1, 1, 3)
        setattr(self, f"{var_name}_entry", entry)
        return (var, entry)

    def create_buttons(self, parent) -> None:
        """建立按鈕。

        Args:
            parent: 父容器。
        """
        self.actions_frame = QtWidgets.QFrame(self)
        self.actions_frame.setObjectName("CreateServerActions")
        self.actions_frame.setStyleSheet(NativeQtStyle.create_actions)
        button_layout = QtWidgets.QHBoxLayout(self.actions_frame)
        _set_layout_margins(button_layout, 0, 4, 0, 0)
        button_layout.addStretch(1)
        self.create_button = self._make_button("建立伺服器", self.create_server, kind="primary")
        self.create_button.setFixedWidth(Sizes.BUTTON_WIDTH_PRIMARY)
        reset_button = self._make_button("重設表單", self.reset_form)
        reset_button.setFixedWidth(Sizes.BUTTON_WIDTH_SECONDARY)
        button_layout.addWidget(self.create_button)
        button_layout.addSpacing(8)
        button_layout.addWidget(reset_button)
        parent.addWidget(self.actions_frame, 0)

    def reset_form(self):
        """重設表單到預設值"""
        try:
            if hasattr(self, "release_versions") and self.release_versions:
                latest_version = self.release_versions[0].get("id", "未知版本")
                self.server_name_var.set(latest_version)
            else:
                self.server_name_var.set("我的伺服器")
            self.java_path_var.set("")
            self.loader_type_var.set("Vanilla")
            self.loader_version_var.set("無")
            self.loader_version_combo.configure(values=["無"])
            if hasattr(self, "mc_version_combo") and self.mc_version_combo.cget("values"):
                version_list = list(self.mc_version_combo.cget("values"))
                if version_list:
                    self.mc_version_var.set(version_list[0])
            self.update_version_list()
            self.min_memory_var.set("1024")
            self.max_memory_var.set("2048")
            UIUtils.show_info("重設完成", "表單已重設為預設值", self.window())
        except Exception as e:
            with __import__("contextlib").suppress(Exception):
                record_and_mark(e, marker_path=Path(__file__), reason="reset_form_failed")
            logger.error(f"重設表單失敗: {e}\n{traceback.format_exc()}")
            UIUtils.show_error("重設失敗", f"重設表單時發生錯誤：\n{e!s}", self.window())

    def update_versions(self, versions: list) -> None:
        """更新版本列表，並預設選擇最新版本。

        Args:
            versions: 可用版本清單。
        """
        self.versions = versions
        self.release_versions = versions
        self.update_version_list()
        if self.release_versions:
            latest_version = self.release_versions[0].get("id")
            if self.server_name_var.get() in ["我的伺服器", ""]:
                self.server_name_var.set(latest_version)

    def update_version_list(self) -> None:
        """更新版本列表顯示，並預設選擇最新版本"""
        if not hasattr(self, "versions") or not self.versions:
            self.mc_version_combo.configure(values=["載入中..."])
            self.mc_version_var.set("載入中...")
            return
        display_versions = [v for v in self.release_versions if v.get("server_url")]
        if not display_versions:
            self.mc_version_combo.configure(values=["無可用版本"], state="disabled")
            self.mc_version_var.set("無可用版本")
            return
        version_names = [v.get("id") for v in display_versions]
        self.mc_version_combo.configure(values=version_names, state="readonly")
        if display_versions:
            first_version = display_versions[0].get("id")
            self.mc_version_var.set(first_version)
        self.update_server_config_ui()

    @staticmethod
    def _compose_server_name(loader_type: str, mc_version: str, suffix: str = "") -> str:
        """依載入器類型與版本組合標準伺服器名稱。"""
        base_name = f"{mc_version}{suffix}"
        if loader_type in ("Fabric", "Forge", "Quilt", "NeoForge"):
            return f"{loader_type} {base_name}"
        return base_name

    @staticmethod
    def _extract_server_name_suffix(name: str, version_candidates: tuple[str, ...]) -> str | None:
        """解析「[載入器前綴] + 版本 + 自訂尾字」中的尾字。"""
        normalized = name.strip()
        if not normalized:
            return None
        for prefix in ("Fabric ", "Forge ", "Quilt ", "NeoForge "):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
                break
        for version in version_candidates:
            if version and normalized.startswith(version):
                return normalized[len(version) :]
        return None

    def update_server_config_ui(self, _event=None) -> None:
        """根據載入器類型與 Minecraft 版本自動更新伺服器名稱與載入器版本選單。

        Args:
            _event: 事件物件，供 trace callback 使用。
        """
        mc_version = self.mc_version_var.get()
        loader_type = self.loader_type_var.get()
        name = self.server_name_var.get()
        auto_names = [
            "我的伺服器",
            "",
            self._compose_server_name("Fabric", mc_version),
            self._compose_server_name("Forge", mc_version),
            self._compose_server_name("Vanilla", mc_version),
            self._compose_server_name("Quilt", mc_version),
            self._compose_server_name("NeoForge", mc_version),
        ]
        old_version = getattr(self, "old_mc_version", None)
        self.old_mc_version = mc_version
        if name in auto_names:
            self.server_name_var.set(self._compose_server_name(loader_type, mc_version))
        else:
            version_candidates = tuple(v for v in (old_version, mc_version) if v)
            suffix = self._extract_server_name_suffix(name, version_candidates)
            if suffix is not None:
                self.server_name_var.set(self._compose_server_name(loader_type, mc_version, suffix))
        if old_version and old_version in name and (name == self.server_name_var.get()):
            self.server_name_var.set(name.replace(old_version, mc_version))
        if loader_type == "Vanilla":
            self.loader_version_combo.configure(values=["無"], state="disabled")
            self.loader_version_combo.set("無")
            self.loader_version_var.set("無")
            return
        self.loader_version_combo.configure(state="readonly")
        if not mc_version:
            return
        current_key = f"{loader_type}_{mc_version}"
        if hasattr(self, "_loading_key") and self._loading_key == current_key:
            return
        self._loading_key = current_key
        threading.Thread(target=self.load_loader_versions, args=(loader_type, mc_version), daemon=True).start()

    def load_loader_versions(self, loader_type: str, mc_version: str) -> None:
        """載入載入器版本，並預設選擇最新版本（使用預載入的快取資料）。

        Args:
            loader_type: 載入器類型。
            mc_version: Minecraft 版本。
        """
        try:

            def set_loading():
                if is_qobject_alive(self.loader_version_combo):
                    self._update_combo_state(
                        self.loader_version_combo,
                        self.loader_version_var,
                        f"正在載入 {loader_type} 版本...",
                        "disabled",
                    )

            self.ui_queue.put(set_loading)
            versions = []
            versions = self.loader_manager.get_compatible_loader_versions(mc_version, loader_type)

            def update_ui():
                try:
                    if not is_qobject_alive(self.loader_version_combo):
                        return
                    current_type = self.loader_type_var.get()
                    current_version = self.mc_version_var.get()
                    if loader_type != current_type or mc_version != current_version:
                        return
                    if versions:
                        version_names = [v.version for v in versions]
                        self.loader_version_combo.configure(values=version_names)
                        self.loader_version_combo.configure(state="readonly")
                        if version_names:
                            self.loader_version_combo.set(version_names[0])
                            self.loader_version_var.set(version_names[0])
                    else:
                        self._update_combo_state(
                            self.loader_version_combo, self.loader_version_var, "無可用版本", "disabled"
                        )
                    if hasattr(self, "_loading_key"):
                        delattr(self, "_loading_key")
                except Exception as e:
                    with __import__("contextlib").suppress(Exception):
                        record_and_mark(e, marker_path=Path(__file__), reason="update_loader_versions_ui_failed")
                    logger.bind(component="").error(
                        f"更新載入器版本 UI 失敗: {e}\n{traceback.format_exc()}", "CreateServerFrame"
                    )
                    if hasattr(self, "_loading_key"):
                        delattr(self, "_loading_key")

            self.ui_queue.put(update_ui)
        except Exception as e:
            with __import__("contextlib").suppress(Exception):
                record_and_mark(e, marker_path=Path(__file__), reason="load_loader_versions_failed")
            logger.bind(component="").error(f"載入載入器版本失敗: {e}\n{traceback.format_exc()}", "CreateServerFrame")

            def handle_error():
                try:
                    if is_qobject_alive(self.loader_version_combo):
                        self._update_combo_state(
                            self.loader_version_combo, self.loader_version_var, "載入失敗", "disabled"
                        )
                except Exception as e2:
                    logger.exception(f"更新載入器版本失敗狀態 UI 失敗: {e2}")
                if hasattr(self, "_loading_key"):
                    delattr(self, "_loading_key")

            self.ui_queue.put(handle_error)

    def validate_form(self) -> bool:
        """驗證表單。

        Returns:
            若表單內容通過驗證則回傳 True，否則回傳 False。
        """
        server_name = self.server_name_var.get().strip()
        if not server_name:
            UIUtils.show_error("錯誤", "請輸入伺服器名稱", self.window())
            return False
        servers_root = self.server_manager.servers_root
        if (servers_root / server_name).exists():
            UIUtils.show_error(
                "名稱重複", f"伺服器名稱 '{server_name}' 已存在於伺服器資料夾，請換一個名稱。", self.window()
            )
            return False
        if self.server_manager.server_exists(server_name) and (
            not UIUtils.ask_yes_no_cancel(
                "名稱衝突",
                f"伺服器名稱 '{server_name}' 已存在於設定。是否覆蓋?",
                self.window(),
                show_cancel=False,
            )
        ):
            return False
        if not self.mc_version_var.get():
            UIUtils.show_error("錯誤", "請選擇 Minecraft 版本", self.window())
            return False
        max_memory = self.max_memory_var.get().strip()
        if not max_memory:
            UIUtils.show_error("錯誤", "請輸入最大記憶體", self.window())
            return False
        try:
            max_mem_int = int(max_memory)
            if max_mem_int < 1024:
                UIUtils.show_error("錯誤", "最大記憶體不能少於 1024MB", self.window())
                return False
            system_memory = self.get_system_memory_mb()
            if max_mem_int >= system_memory:
                UIUtils.show_error(
                    "記憶體超出限制",
                    f"最大記憶體 ({max_mem_int}MB) 不能等於或超過系統記憶體容量 ({system_memory}MB)\n已自動調整為 {system_memory - 1}MB",
                    self.window(),
                )
                self.max_memory_var.set(str(system_memory - 1))
                return False
        except ValueError:
            UIUtils.show_error("錯誤", "最大記憶體必須是數字", self.window())
            return False
        min_memory = self.min_memory_var.get().strip()
        if min_memory:
            try:
                min_mem_int = int(min_memory)
                if min_mem_int >= max_mem_int:
                    UIUtils.show_error("錯誤", "最小記憶體必須小於最大記憶體", self.window())
                    return False
            except ValueError:
                UIUtils.show_error("錯誤", "最小記憶體必須是數字", self.window())
                return False
        return True

    def create_server(self):
        """建立伺服器"""
        if not self.validate_form():
            return
        min_memory = self.min_memory_var.get().strip()
        max_memory = self.max_memory_var.get().strip()
        name = self.server_name_var.get().strip()
        loader_type = self.loader_type_var.get()
        mc_version = self.mc_version_var.get()
        if name in ["", "我的伺服器"]:
            if loader_type == "Vanilla":
                name = f"{mc_version}"
            elif loader_type == "Fabric":
                name = f"Fabric {mc_version}"
            elif loader_type == "Forge":
                name = f"Forge {mc_version}"
            elif loader_type == "Quilt":
                name = f"Quilt {mc_version}"
            elif loader_type == "NeoForge":
                name = f"NeoForge {mc_version}"
            self.server_name_var.set(name)
        config = ServerConfig(
            name=name,
            minecraft_version=mc_version,
            loader_type=loader_type,
            loader_version=self.loader_version_var.get() if loader_type != "Vanilla" else "",
            memory_max_mb=int(max_memory),
            memory_min_mb=int(min_memory) if min_memory else None,
            path="",
            eula_accepted=True,
        )
        TaskUtils.run_async(self.create_server_async, config)

    def create_server_async(self, config: ServerConfig) -> None:
        """非同步建立伺服器。

        Args:
            config: 伺服器建立設定。
        """
        parent_window = self.window()
        progress_dialog = None
        progress_ready = threading.Event()
        try:

            def create_progress():
                nonlocal progress_dialog
                progress_dialog = ProgressDialog(parent_window, "正在建立伺服器")
                progress_ready.set()

            self._schedule_ui_job("_create_server_progress_job", 0, create_progress)
            if not progress_ready.wait(timeout=10):
                raise Exception("建立進度對話框超時")
            if progress_dialog is None:
                raise Exception("建立進度對話框失敗")
            if not progress_dialog.update_progress(5, "建立伺服器目錄結構..."):
                return
            create_result = self.server_manager.create_server_result(config)
            if create_result.failed:
                logger.error(f"建立伺服器基礎結構失敗 config: {config} | {create_result.message}")
                progress_dialog.close()
                raise Exception(create_result.message or "建立伺服器基礎結構失敗")
            if not config.loader_type or config.loader_type == "unknown":
                progress_dialog.close()
                raise Exception(f"偵測失敗：loader_type 無法判斷，config={config}")
            if not config.minecraft_version or config.minecraft_version == "unknown":
                progress_dialog.close()
                raise Exception(f"偵測失敗：minecraft_version 無法判斷，config={config}")
            if config.loader_type.lower() in ["forge", "fabric", "quilt", "neoforge"] and (
                not config.loader_version or config.loader_version == "unknown"
            ):
                progress_dialog.close()
                raise Exception(f"偵測失敗：loader_version 無法判斷，config={config}")
            server_path = Path(config.path)
            if not progress_dialog.update_progress(15, "下載伺服器核心檔案..."):
                return
            try:
                if not self.download_server_files(config, progress_dialog, server_path):
                    progress_dialog.close()
                    return
                self.server_manager.create_launch_script(config)
            except Exception as e:
                with __import__("contextlib").suppress(Exception):
                    record_and_mark(
                        e,
                        marker_path=Path(__file__),
                        reason="download_server_files_failed",
                        details={"config": repr(config)},
                    )
                logger.bind(component="").error(
                    f"下載伺服器檔案失敗: {e}\n{traceback.format_exc()}", "CreateServerFrame"
                )
                error_message = str(e)

                def _show_download_error() -> None:
                    UIUtils.show_error("下載失敗", f"下載伺服器檔案失敗: {error_message}", self.window())

                self.ui_queue.put(_show_download_error)
                raise Exception(error_message) from None
            if not progress_dialog.update_progress(100, "伺服器建立完成！"):
                return

            def on_success():
                progress_dialog.close()
                self.callback(config)

            self._schedule_ui_job("_create_server_success_job", 1000, on_success)
        except Exception as error:
            with __import__("contextlib").suppress(Exception):
                record_and_mark(
                    error, marker_path=Path(__file__), reason="create_server_failed", details={"config": repr(config)}
                )
            logger.bind(component="").error(
                f"建立伺服器時發生錯誤: {error}\n{traceback.format_exc()}", "CreateServerFrame"
            )

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

    def download_server_files(self, config: ServerConfig, progress_dialog: ProgressDialog, server_path: Path) -> bool:
        """下載伺服器檔案。

        Args:
            config: 伺服器建立設定。
            progress_dialog: 進度對話框。
            server_path: 伺服器資料夾路徑。

        Returns:
            下載與建立流程是否成功。
        """
        loader_type = config.loader_type.lower()
        download_path = str(server_path / "server.jar")

        installer_url = self.loader_manager.get_installer_download_url(
            loader_type,
            config.minecraft_version,
            config.loader_version,
        )
        if installer_url:
            checksum = self.loader_manager._fetch_secure_checksum(installer_url)
            if checksum is None:
                proceed = UIUtils.ask_yes_no_cancel(
                    "缺少驗證資訊",
                    (f"{config.loader_type} 安裝器目前找不到 SHA-256 / SHA-512 驗證資訊。\n仍要繼續建立伺服器嗎？"),
                    parent=self.window(),
                    show_cancel=False,
                )
                if proceed is not True:
                    return False

        # [1] 建立 server_path 後 sleep 0.3 秒，確保目錄完全建立
        with contextlib.suppress(Exception):
            server_path.mkdir(parents=True, exist_ok=True)
        import time

        time.sleep(0.3)

        def progress_callback(percent, status):
            progress_dialog.update_progress(percent, status)

        result: list[bool | None] = [None]
        shared_cancel_token = CancellationToken()

        def do_download(cancel_token: CancellationToken | None = None):
            token = cancel_token or shared_cancel_token
            user_java_path = self.java_path_var.get().strip() or None
            if not self._validate_download_parameters(loader_type, config):
                self.ui_queue.put(
                    lambda: UIUtils.show_error(
                        "下載流程參數異常",
                        f"loader_type={loader_type}\nmc={config.minecraft_version}\nloader_ver={config.loader_version}",
                        topmost=True,
                    )
                )
                result[0] = False
                return
            ok = self.loader_manager.download_server_jar_with_progress(
                loader_type,
                config.minecraft_version,
                config.loader_version,
                download_path,
                progress_callback,
                token,
                user_java_path,
            )
            result[0] = ok

        future = self.bg_tasks.run(do_download, cancel_token=shared_cancel_token)
        while not future.done():
            if progress_dialog.cancelled:
                with __import__("contextlib").suppress(Exception):
                    shared_cancel_token.cancel()
            try:
                future.result(timeout=0.1)
            except concurrent.futures.TimeoutError:
                continue
        if result[0] is False:
            # [2] 失敗時補充 cmd 與 installer.log 內容
            log_details = []
            log_details.append(f"loader_type: {loader_type}")
            log_details.append(f"minecraft_version: {config.minecraft_version}")
            log_details.append(f"loader_version: {config.loader_version}")
            log_details.append(f"download_path: {download_path}")
            log_details.append(f"user_java_path: {getattr(self, 'java_path_var', None) and self.java_path_var.get()}")
            # 嘗試補充 cmd
            try:
                installer_dir = server_path
                possible_logs = [installer_dir / "installer.log"]
                for log_path in possible_logs:
                    if log_path.exists():
                        log_details.append(
                            f"\n--- {log_path.name} ---\n"
                            + log_path.read_text(encoding="utf-8", errors="ignore")[-2048:]
                        )
            except Exception as e:
                log_details.append(f"[installer.log 讀取失敗: {e}]")
            msg = "伺服器下載失敗，參數如下：\n" + "\n".join(log_details)

            logger.bind(component="").error(
                f"server_path: {server_path}\nconfig: {config}\n{msg}\n{traceback.format_exc()}", "CreateServerFrame"
            )
            raise Exception(msg)
        return True

    def _validate_download_parameters(self, loader_type: str, config) -> bool:
        """驗證下載參數"""
        if not loader_type or loader_type == "unknown":
            return False
        if not config.minecraft_version or config.minecraft_version == "unknown":
            return False
        requires_loader_version = loader_type in ["forge", "fabric", "quilt", "neoforge"]
        return not (requires_loader_version and (not config.loader_version or config.loader_version == "unknown"))

    def destroy(self, destroyWindow: bool = True, destroySubWindows: bool = True) -> None:
        """銷毀頁面前先清理待執行排程工作。

        Args:
            destroyWindow: 是否銷毀目前 Qt 視窗。
            destroySubWindows: 是否一併銷毀子視窗。
        """
        self._cancel_create_server_jobs()
        super().destroy(destroyWindow, destroySubWindows)
