"""
建立伺服器頁面
負責建立新 Minecraft 伺服器的使用者介面
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    HyperlinkLabel,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    TitleLabel,
    qconfig,
)

from src.core import CreateServerJourney, LoaderManager, ServerCRUD, ServerPropertiesStore
from src.models import ServerConfig
from src.ui import JvmArgsDialog, ProgressDialog, ServerCreationConfirmDialog
from src.utils import (
    Colors,
    FontManager,
    FontSize,
    JavaDownloader,
    JavaUtils,
    JvmOptionPolicy,
    MemoryUtils,
    ScrollableComboBox,
    Sizes,
    StatusPushButton,
    SystemUtils,
    UIUtils,
    UIWorkScope,
    ValueState,
    WorkOutcome,
    get_logger,
    is_qobject_alive,
    resolve_color,
    run_on_ui_thread,
)

logger = get_logger().bind(component="CreateServerFrame")


def _qt_font(font: Any) -> QtGui.QFont:
    return getattr(font, "font", font)


class CreateServerFrame(QWidget):
    """建立伺服器頁面"""

    def __init__(
        self,
        parent,
        loader_manager: LoaderManager,
        callback: Callable,
        server_crud: ServerCRUD,
        server_properties: ServerPropertiesStore,
    ):
        super().__init__(parent)
        self.loader_manager = loader_manager
        self.callback = callback
        self.server_crud = server_crud
        self.server_creation = CreateServerJourney(server_crud, loader_manager, server_properties)
        self.versions: list = []
        self.release_versions: list = []
        self._loading_key: str | None = None
        self.server_name_var = ValueState("")
        self.scope = UIWorkScope(self)
        self.jvm_args_customized = False
        self.selected_jvm_args: list[str] = []
        self.setObjectName("CreateServerFrame")
        self.create_widgets()
        self.preload_version_data()
        self.apply_theme_styles()
        qconfig.themeChangedFinished.connect(self.apply_theme_styles)

    @staticmethod
    def get_system_memory_mb() -> int:
        """
        取得系統記憶體容量

        Returns:
            系統總記憶體容量（MB），失敗時回傳 0
        """
        try:
            return SystemUtils.get_total_memory_mb()
        except Exception as e:
            logger.error(f"無法取得系統記憶體資訊: {e}\n{traceback.format_exc()}")
            UIUtils.show_message("錯誤", f"無法取得系統記憶體資訊: {e}", message_level="error")
            return 0

    @staticmethod
    def _compose_server_name(loader_type: str, mc_version: str, suffix: str = "") -> str:
        """依載入器類型與版本組合標準伺服器名稱"""
        base_name = f"{mc_version}{suffix}"
        if loader_type in ("Fabric", "Forge", "Quilt", "NeoForge"):
            return f"{loader_type} {base_name}"
        return base_name

    @staticmethod
    def _extract_server_name_suffix(name: str, version_candidates: tuple[str, ...]) -> str | None:
        """解析「[載入器前綴] + 版本 + 自訂尾字」中的尾字"""
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
            logger.error(f"更新記憶體警告失敗: {e}\n{traceback.format_exc()}")
            UIUtils.show_message("錯誤", f"更新記憶體警告失敗: {e}", self.window(), message_level="error")

    def create_java_path_field(self, parent, row) -> None:
        """
        建立 Java 路徑欄位（可手動輸入/瀏覽）

        Args:
            parent: 父容器
            row: 要放置的表單列號
        """
        parent.addWidget(self._make_label("Java 執行檔路徑 (可選):"), row, 0)
        self.java_path_var = ValueState("")
        java_path_entry = LineEdit(self.form_panel)
        java_path_entry.setFont(FontManager.get_font(size=FontSize.MEDIUM))
        self._bind_entry(java_path_entry, self.java_path_var)
        self._style_control(java_path_entry)
        parent.addWidget(java_path_entry, row, 1)

        def browse_java():
            path = UIUtils.get_open_file_name(
                self.window(), "選擇 javaw.exe", "", "Java 執行檔 (javaw.exe);;所有檔案 (*)"
            )
            if path:
                self.java_path_var.set(path)

        browse_btn = self._make_button("瀏覽...", browse_java)
        browse_btn.setMinimumWidth(72)
        parent.addWidget(browse_btn, row, 2)

        def auto_detect():
            mc_version = self.mc_version_var.get() if hasattr(self, "mc_version_var") else None
            if not mc_version or "載入中" in mc_version or "等待" in mc_version or "請先選擇" in mc_version:
                UIUtils.show_message(
                    "Java 偵測", "請先選擇有效的 Minecraft 版本！", self.window(), message_level="warning"
                )
                return

            auto_btn.setEnabled(False)
            auto_btn.setText("偵測中...")

            def _detect_task() -> str | None:
                return JavaUtils.get_best_java_path(mc_version, ask_download=False)

            def _on_done(outcome: WorkOutcome) -> None:
                auto_btn.setEnabled(True)
                auto_btn.setText("自動偵測")
                if outcome.is_succeeded and outcome.value:
                    java_path_win = str(Path(outcome.value))
                    self.java_path_var.set(java_path_win)
                    return

                required_major = JavaUtils.get_required_java_major(mc_version)
                vendor = "Oracle jre" if required_major == 8 else "Microsoft JDK"
                res = UIUtils.ask_yes_no_cancel(
                    "Java 未找到",
                    (
                        f"未找到合適的 Java {required_major}，是否由程式自動安裝 {vendor}？\n\n"
                        "選擇 [是] 會在背景使用 winget 安裝並自動同意相關授權條款；\n"
                        "選擇 [否] 則不會安裝，由你自行下載並在程式中指定 Java 路徑"
                    ),
                    parent=self.window(),
                    show_cancel=False,
                )
                if not res:
                    UIUtils.show_message(
                        "請手動下載 Java",
                        f"請手動安裝或指定 Java 路徑\n建議安裝 Microsoft JDK、Adoptium、Azul、Oracle JDK {required_major} 等",
                        self.window(),
                        message_level="info",
                    )
                    return

                auto_btn.setEnabled(False)
                auto_btn.setText("安裝中...")

                def _install_task() -> str | None:
                    JavaDownloader.install_java_with_winget(required_major)
                    JavaUtils.refresh_java_candidates_cache()
                    return JavaUtils.get_best_java_path(mc_version, ask_download=False)

                def _on_install_done(install_outcome: WorkOutcome) -> None:
                    auto_btn.setEnabled(True)
                    auto_btn.setText("自動偵測")
                    if install_outcome.is_succeeded and install_outcome.value:
                        java_path_win = str(Path(install_outcome.value))
                        self.java_path_var.set(java_path_win)
                        UIUtils.show_message(
                            title=f"Java {required_major} 安裝成功",
                            message=f"Java {required_major} 已成功安裝並偵測到 javaw.exe",
                            parent=self.window(),
                            message_level="info",
                        )
                    else:
                        err = install_outcome.error if install_outcome.error else "未知錯誤"
                        UIUtils.show_message(
                            "Java 下載失敗",
                            f"自動下載 Microsoft JDK {required_major} 失敗：{err}\n請手動安裝或指定 Java 路徑",
                            parent=self.window(),
                            message_level="error",
                        )

                self.scope.submit(_install_task, on_done=_on_install_done, key="java_install", replace=True)

            self.scope.submit(_detect_task, on_done=_on_done, key="java_detect", replace=True)

        auto_btn = self._make_button("自動偵測", auto_detect)
        auto_btn.setMinimumWidth(75)
        parent.addWidget(auto_btn, row, 3)

    def create_widgets(self) -> None:
        """建立介面元件"""
        self.setObjectName("CreateServerFrame")
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(11)

        self.scroll_area = ScrollArea(self)
        self.scroll_area.setObjectName("CreateServerScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.content_widget = QWidget()
        self.content_widget.setObjectName("CreateServerContent")
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(11)
        self.scroll_area.setWidget(self.content_widget)
        main_layout.addWidget(self.scroll_area, 1)

        title_label = TitleLabel("建立新伺服器", self.content_widget)
        self.title_label = title_label
        title_label.setFont(_qt_font(FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold")))
        content_layout.addWidget(title_label)

        eula_frame = CardWidget(self.content_widget)
        self.eula_frame = eula_frame
        eula_frame.setObjectName("EulaNotice")
        eula_layout = QHBoxLayout(eula_frame)
        eula_layout.setContentsMargins(8, 6, 8, 6)
        eula_layout.setSpacing(8)
        eula_icon = BodyLabel("⚠️", eula_frame)
        self.eula_icon = eula_icon
        eula_icon.setStyleSheet("background: transparent;")
        eula_icon.setFont(_qt_font(FontManager.get_font(size=FontSize.LARGE, weight="bold")))
        eula_layout.addWidget(eula_icon, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        eula_link = HyperlinkLabel(
            QtCore.QUrl("https://aka.ms/MinecraftEULA"),
            "請務必閱讀並同意 Minecraft EULA 條款 (點我閱讀)\n"
            "點擊建立即表示你同意Minecraft條款，任何違法行為本軟體不負責任",
            eula_frame,
        )
        self.eula_link = eula_link
        self.eula_link.setFont(_qt_font(FontManager.get_font(size=FontSize.MEDIUM, weight="bold")))
        eula_layout.addWidget(eula_link, 1, QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        content_layout.addWidget(eula_frame)

        self.form_panel = QWidget(self.content_widget)
        self.form_panel.setObjectName("CreateFormPanel")
        form_layout = QGridLayout(self.form_panel)
        form_layout.setContentsMargins(0, 3, 0, 0)
        form_layout.setHorizontalSpacing(8)
        form_layout.setVerticalSpacing(8)
        form_layout.setColumnStretch(1, 1)
        self.create_form(form_layout)
        content_layout.addWidget(self.form_panel)
        content_layout.addStretch(1)
        self.create_buttons(main_layout)

    def apply_theme_styles(self) -> None:
        """重新套用目前主題到建立伺服器頁"""
        background = resolve_color(Colors.BG_PRIMARY)
        self.setStyleSheet(f"#CreateServerFrame {{ background-color: {background}; }}")
        if hasattr(self, "scroll_area"):
            self.scroll_area.setStyleSheet(f"ScrollArea {{ background-color: {background}; border: 0; }}")
            self.scroll_area.viewport().setStyleSheet(f"background-color: {background};")
        if hasattr(self, "content_widget"):
            self.content_widget.setStyleSheet(f"background-color: {background};")
        if hasattr(self, "actions_frame"):
            self.actions_frame.setStyleSheet(f"background-color: {background};")
        if hasattr(self, "eula_frame"):
            self.eula_frame.setStyleSheet(
                "CardWidget#EulaNotice { background-color: transparent; border: 1px solid rgba(128, 128, 128, 0.2); border-radius: 6px; }"
            )
        if hasattr(self, "eula_icon"):
            self.eula_icon.setStyleSheet("background: transparent;")
        if hasattr(self, "memory_warning_label"):
            self.memory_warning_label.setStyleSheet(
                f"color: {resolve_color(Colors.TEXT_ERROR)}; background: transparent;"
            )

    def create_form(self, parent) -> None:
        """
        建立表單

        Args:
            parent: 父容器
        """
        content_frame = parent
        self.create_field(content_frame, 0, "伺服器名稱:", "我的伺服器", "server_name")
        self.create_java_path_field(content_frame, 1)
        content_frame.addWidget(self._make_label("模組載入器:"), 2, 0)
        self.loader_type_var = ValueState("Vanilla")
        self.loader_type_combo = ScrollableComboBox(self.form_panel)
        self.loader_type_combo.addItems(["Vanilla", "Fabric", "Forge", "Quilt", "NeoForge"])
        self._bind_combo(self.loader_type_combo, self.loader_type_var)
        self.loader_type_combo.setMinimumWidth(Sizes.DROPDOWN_WIDTH)
        self._style_control(self.loader_type_combo)
        content_frame.addWidget(self.loader_type_combo, 2, 1)
        self.loader_type_var.trace_add("write", lambda *_args: self.update_server_config_ui())

        loader_version_row = 3
        content_frame.addWidget(self._make_label("載入器版本:"), loader_version_row, 0)
        self.loader_version_var = ValueState("無")
        self.loader_version_combo = ScrollableComboBox(self.form_panel)
        self.loader_version_combo.addItem("無")
        self._bind_combo(self.loader_version_combo, self.loader_version_var)
        self.loader_version_combo.setEnabled(False)
        self.loader_version_combo.setMinimumWidth(Sizes.DROPDOWN_WIDTH)
        self._style_control(self.loader_version_combo)
        content_frame.addWidget(self.loader_version_combo, loader_version_row, 1)
        loader_reload_btn = self._make_button("⟳", self.reload_loader_versions)
        loader_reload_btn.setMinimumWidth(72)
        content_frame.addWidget(loader_reload_btn, loader_version_row, 2)

        content_frame.addWidget(self._make_label("Minecraft 版本:"), 4, 0)
        self.mc_version_var = ValueState("")
        self.mc_version_combo = ScrollableComboBox(self.form_panel)
        self.mc_version_combo.addItem("載入中...")
        self._bind_combo(self.mc_version_combo, self.mc_version_var)
        self.mc_version_combo.currentTextChanged.connect(self.update_server_config_ui)
        self.mc_version_combo.setMinimumWidth(Sizes.DROPDOWN_COMPACT_WIDTH)
        self._style_control(self.mc_version_combo)
        content_frame.addWidget(self.mc_version_combo, 4, 1)
        mc_reload_btn = self._make_button("⟳", self.reload_mc_versions)
        mc_reload_btn.setMinimumWidth(72)
        content_frame.addWidget(mc_reload_btn, 4, 2)

        memory_title = self._make_label("記憶體設定 (MB):")
        content_frame.addWidget(memory_title, 5, 0)
        memory_container = QWidget(self.form_panel)
        memory_layout = QVBoxLayout(memory_container)
        memory_layout.setContentsMargins(0, 0, 0, 0)
        memory_layout.setSpacing(5)
        memory_input_layout = QGridLayout()
        memory_input_layout.setContentsMargins(0, 0, 0, 0)
        memory_input_layout.setHorizontalSpacing(8)
        memory_input_layout.setColumnStretch(0, 1)
        memory_input_layout.setColumnStretch(1, 1)
        self.min_memory_var = ValueState("1024")
        min_memory_frame = QWidget(memory_container)
        min_layout = QVBoxLayout(min_memory_frame)
        min_layout.setContentsMargins(0, 0, 0, 0)
        min_layout.setSpacing(3)
        min_label = CaptionLabel("最小記憶體:", min_memory_frame)
        self.min_label = min_label
        min_label.setFont(_qt_font(FontManager.get_font(size=FontSize.MEDIUM)))
        min_layout.addWidget(min_label)
        self.min_memory_entry = LineEdit(min_memory_frame)
        self.min_memory_entry.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.min_memory_entry.setFont(FontManager.get_font(size=FontSize.MEDIUM))
        self._bind_entry(self.min_memory_entry, self.min_memory_var)
        self._style_control(self.min_memory_entry)
        min_layout.addWidget(self.min_memory_entry)
        memory_input_layout.addWidget(min_memory_frame, 0, 0)

        self.max_memory_var = ValueState("2048")
        max_memory_frame = QWidget(memory_container)
        max_layout = QVBoxLayout(max_memory_frame)
        max_layout.setContentsMargins(0, 0, 0, 0)
        max_layout.setSpacing(3)
        max_label = CaptionLabel("最大記憶體:", max_memory_frame)
        self.max_label = max_label
        max_label.setFont(_qt_font(FontManager.get_font(size=FontSize.MEDIUM)))
        max_layout.addWidget(max_label)
        self.max_memory_entry = LineEdit(max_memory_frame)
        self.max_memory_entry.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.max_memory_entry.setFont(FontManager.get_font(size=FontSize.MEDIUM))
        self._bind_entry(self.max_memory_entry, self.max_memory_var)
        self._style_control(self.max_memory_entry)
        max_layout.addWidget(self.max_memory_entry)
        memory_input_layout.addWidget(max_memory_frame, 0, 1)
        memory_layout.addLayout(memory_input_layout)
        self.max_memory_var.trace_add("write", lambda *_args: self.update_memory_warning())
        self.min_memory_var.trace_add("write", lambda *_args: self.update_memory_warning())
        memory_tip = CaptionLabel(
            "最小記憶體選填，若留空由 Java 決定\n最大記憶體(必填)建議： 2048MB (最低) | 4096MB (一般) | 8192MB (多人遊戲)",
            memory_container,
        )
        self.memory_tip = memory_tip
        memory_tip.setFont(FontManager.get_font(size=FontSize.MEDIUM))
        memory_tip.setWordWrap(True)
        memory_layout.addWidget(memory_tip)
        self.memory_warning_label = CaptionLabel("", memory_container)
        self.memory_warning_label.setFont(FontManager.get_font(size=FontSize.SMALL_PLUS))
        self.memory_warning_label.setStyleSheet(f"color: {resolve_color(Colors.TEXT_ERROR)};")
        self.memory_warning_label.setWordWrap(True)
        memory_layout.addWidget(self.memory_warning_label)
        content_frame.addWidget(memory_container, 5, 1, 1, 2)

        content_frame.addWidget(self._make_label("JVM啟動參數:"), 6, 0)
        jvm_container = QWidget(self.form_panel)
        jvm_layout = QHBoxLayout(jvm_container)
        jvm_layout.setContentsMargins(0, 0, 0, 0)
        jvm_layout.setSpacing(10)

        self.jvm_summary_label = BodyLabel("載入中...", jvm_container)
        self.jvm_summary_label.setFont(_qt_font(FontManager.get_font(size=FontSize.MEDIUM)))

        self.jvm_config_btn = PrimaryPushButton("JVM參數設定...", jvm_container)
        self.jvm_config_btn.clicked.connect(self.open_jvm_args_dialog)

        jvm_layout.addWidget(self.jvm_config_btn)
        jvm_layout.addWidget(self.jvm_summary_label)
        jvm_layout.addStretch(1)

        content_frame.addWidget(jvm_container, 6, 1, 1, 2)

        self.max_memory_var.trace_add("write", lambda *_args: self.update_default_jvm_args())
        self.mc_version_var.trace_add("write", lambda *_args: self.update_default_jvm_args())

        def _on_loader_changed(*_args):
            self.jvm_args_customized = False
            self.update_default_jvm_args()

        self.loader_type_var.trace_add("write", _on_loader_changed)

    def get_suggested_java_version(self) -> int | None:
        """根據目前的 Minecraft 版本取得建議的 Java major version"""
        mc_version = self.mc_version_var.get()
        if not mc_version or "載入" in mc_version or "等待" in mc_version or "請先選擇" in mc_version:
            return None
        return JavaUtils.get_required_java_major(mc_version)

    def update_default_jvm_args(self) -> None:
        """當記憶體或版本改變時，若玩家未自訂，則自動更新 JVM 參數與 summary"""
        if self.jvm_args_customized:
            self.jvm_summary_label.setText("自訂參數已套用")
            return

        mc_version = self.mc_version_var.get()
        if not mc_version or "載入中" in mc_version:
            self.jvm_summary_label.setText("等待版本選擇...")
            return

        max_mem_str = self.max_memory_var.get().strip()
        max_mem = int(max_mem_str) if max_mem_str.isdigit() else 2048

        java_major = self.get_suggested_java_version()
        loader_type = self.loader_type_var.get()

        recommended = JvmOptionPolicy.get_recommended_jvm_args_details(
            java_major=java_major, memory_max_mb=max_mem, loader_type=loader_type
        )
        self.selected_jvm_args = [arg[0] for arg in recommended]

        if java_major and java_major >= 21:
            self.jvm_summary_label.setText(f"已自動建議 Java {java_major} (ZGC 優化)")
        elif java_major:
            self.jvm_summary_label.setText(f"已自動建議 Java {java_major} (G1GC 優化)")
        else:
            self.jvm_summary_label.setText("已自動建議最佳化參數")

    def open_jvm_args_dialog(self) -> None:
        """開啟 JVM 參數設定對話框"""
        max_mem_str = self.max_memory_var.get().strip()
        max_mem = int(max_mem_str) if max_mem_str.isdigit() else 2048
        java_major = self.get_suggested_java_version()
        loader_type = self.loader_type_var.get()

        dialog = JvmArgsDialog(
            java_major=java_major,
            memory_max_mb=max_mem,
            loader_type=loader_type,
            existing_args=self.selected_jvm_args if self.jvm_args_customized else None,
            parent=self.window(),
        )
        if dialog.exec():
            self.selected_jvm_args = dialog.get_jvm_args()
            self.jvm_args_customized = True
            self.jvm_summary_label.setText("自訂參數已套用")

    def preload_version_data(self) -> None:
        """預載入版本資訊並管理載入狀態"""
        self._update_combo_state(self.mc_version_combo, self.mc_version_var, "正在載入 MC 版本...", enabled=True)
        self._update_combo_state(
            self.loader_version_combo, self.loader_version_var, "等待 MC 版本選擇...", enabled=True
        )

        def task():
            """執行背景任務的工作內容"""
            versions = self.loader_manager.get_versions()

            def update_mc():
                self.update_versions(versions)
                self._update_combo_state(
                    self.loader_version_combo, self.loader_version_var, "請先選擇載入器類型...", enabled=True
                )

            run_on_ui_thread(update_mc)
            try:
                self.loader_manager.preload_loader_versions()
            except Exception as e:
                logger.error(f"預載入載入器版本失敗: {e}\n{traceback.format_exc()}")

        def on_error():
            self._update_combo_state(self.mc_version_combo, self.mc_version_var, "載入失敗", enabled=True)
            self._update_combo_state(self.loader_version_combo, self.loader_version_var, "載入失敗", enabled=True)

        self._run_background_task(task, "預載入版本資訊失敗", on_error)

    def reload_mc_versions(self) -> None:
        """重新載入 Minecraft 版本"""
        self._update_combo_state(self.mc_version_combo, enabled=True)

        def task():
            """執行背景任務的工作內容"""
            versions = self.loader_manager.get_versions(force_fetch=True)

            def _update():
                self.update_versions(versions)
                self.mc_version_combo.setEnabled(True)

            run_on_ui_thread(_update)

        self._run_background_task(
            task,
            "載入 MC 版本失敗",
            lambda: self._update_combo_state(self.mc_version_combo, message="載入失敗", enabled=False),
        )

    def reload_loader_versions(self) -> None:
        """重新載入載入器版本"""
        loader_type = self.loader_type_var.get()
        mc_version = self.mc_version_var.get()
        if not loader_type or not mc_version or loader_type == "Vanilla":
            return
        self._update_combo_state(self.loader_version_combo, self.loader_version_var, enabled=False)

        def task():
            """執行背景任務的工作內容"""
            self.loader_manager.clear_cache_file()
            self.loader_manager.preload_loader_versions()
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
                    self.loader_version_combo.clear()
                    self.loader_version_combo.addItems(v_names)
                    if v_names:
                        self.loader_version_combo.setCurrentText(v_names[0])
                        self.loader_version_var.set(v_names[0])
                    self.loader_version_combo.setEnabled(True)
                else:
                    self._update_combo_state(
                        self.loader_version_combo, self.loader_version_var, "無可用版本", enabled=False
                    )

            run_on_ui_thread(update_ui)

        self._run_background_task(
            task,
            "載入載入器版本失敗",
            lambda: self._update_combo_state(
                self.loader_version_combo, self.loader_version_var, "載入失敗", enabled=False
            ),
        )

    def create_field(self, parent, row, label_text, default_value, var_name) -> tuple:
        """
        建立文字輸入欄位

        Args:
            parent: 父容器
            row: 要放置的表單列號
            label_text: 欄位標籤文字
            default_value: 預設值
            var_name: 要建立的變數名稱前綴

        Returns:
            (ValueState, LineEdit) 元組
        """
        parent.addWidget(self._make_label(label_text), row, 0)
        var = ValueState(default_value)
        setattr(self, f"{var_name}_var", var)
        entry = LineEdit(self.form_panel)
        entry.setFont(FontManager.get_font(size=FontSize.MEDIUM))
        self._bind_entry(entry, var)
        self._style_control(entry)
        parent.addWidget(entry, row, 1, 1, 3)
        setattr(self, f"{var_name}_entry", entry)
        return (var, entry)

    def create_buttons(self, parent) -> None:
        """
        建立按鈕

        Args:
            parent: 父容器
        """
        self.actions_frame = QWidget(self)
        self.actions_frame.setObjectName("CreateServerActions")
        self.actions_frame.setStyleSheet(
            f"#CreateServerActions {{ background-color: {resolve_color(Colors.BG_PRIMARY)}; }}"
        )
        button_layout = QHBoxLayout(self.actions_frame)
        button_layout.setContentsMargins(0, 4, 0, 0)
        button_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        button_layout.addStretch(1)
        self.reset_button = StatusPushButton("重設表單", self.actions_frame)
        self.reset_button.clicked.connect(self.reset_form)
        self.reset_button.set_status("danger")
        self.reset_button.setMinimumWidth(Sizes.BUTTON_WIDTH_SECONDARY)
        self.reset_button.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)
        button_layout.addWidget(self.reset_button)
        button_layout.addSpacing(8)
        self.create_button = self._make_button(
            "建立伺服器", self.create_server, kind="primary", parent=self.actions_frame
        )
        self.create_button.setMinimumWidth(Sizes.BUTTON_WIDTH_PRIMARY)
        self.create_button.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)
        button_layout.addWidget(self.create_button)
        parent.addWidget(self.actions_frame, 0)

    def reset_form(self):
        """重設表單到預設值"""
        if not UIUtils.ask_yes_no_cancel(
            "重設表單", "確定要重設所有欄位為預設值嗎？", parent=self.window(), show_cancel=False
        ):
            return
        try:
            if hasattr(self, "release_versions") and self.release_versions:
                latest_version = self.release_versions[0].get("id", "未知版本")
                self.server_name_var.set(latest_version)
            else:
                self.server_name_var.set("我的伺服器")
            self.java_path_var.set("")
            self.loader_type_var.set("Vanilla")
            self.loader_version_var.set("無")
            self.loader_version_combo.clear()
            self.loader_version_combo.addItem("無")
            if hasattr(self, "mc_version_combo") and self.mc_version_combo.count() > 0:
                version_list = self._get_combo_items(self.mc_version_combo)
                if version_list:
                    self.mc_version_var.set(version_list[0])
            self.update_version_list()
            self.min_memory_var.set("1024")
            self.max_memory_var.set("2048")

            self.jvm_args_customized = False
            self.selected_jvm_args = []
            self.update_default_jvm_args()

            UIUtils.show_message("重設完成", "表單已重設為預設值", self.window(), message_level="info")
        except Exception as e:
            logger.error(f"重設表單失敗: {e}\n{traceback.format_exc()}")
            UIUtils.show_message("重設失敗", f"重設表單時發生錯誤：\n{e!s}", self.window(), message_level="error")

    def update_versions(self, versions: list) -> None:
        """
        更新版本列表，並預設選擇最新版本

        Args:
            versions: 可用版本清單
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
            self.mc_version_combo.clear()
            self.mc_version_combo.addItem("載入中...")
            self.mc_version_var.set("載入中...")
            return
        display_versions = [v for v in self.release_versions if v.get("server_url")]
        if not display_versions:
            self.mc_version_combo.clear()
            self.mc_version_combo.addItem("無可用版本")
            self.mc_version_combo.setEnabled(False)
            self.mc_version_var.set("無可用版本")
            return
        version_names = [v.get("id") for v in display_versions]
        self.mc_version_combo.clear()
        self.mc_version_combo.addItems(version_names)
        self.mc_version_combo.setEnabled(True)
        if display_versions:
            first_version = display_versions[0].get("id")
            self.mc_version_var.set(first_version)
        self.update_server_config_ui()

    def update_server_config_ui(self, _event=None) -> None:
        """
        根據載入器類型與 Minecraft 版本自動更新伺服器名稱與載入器版本選單

        Args:
            _event: 事件物件，供 trace callback 使用
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
            self.loader_version_combo.clear()
            self.loader_version_combo.addItem(mc_version or "無")
            self.loader_version_combo.setEnabled(False)
            self.loader_version_combo.setCurrentText(mc_version or "無")
            self.loader_version_var.set(mc_version or "無")
            return
        self.loader_version_combo.setEnabled(True)
        if not mc_version:
            return
        current_key = f"{loader_type}_{mc_version}"
        if hasattr(self, "_loading_key") and self._loading_key == current_key:
            return
        self._loading_key = current_key
        self.scope.submit(
            lambda: self.load_loader_versions(loader_type, mc_version), key="load_loader_versions", replace=True
        )

    def load_loader_versions(self, loader_type: str, mc_version: str) -> None:
        """
        載入載入器版本，並預設選擇最新版本（使用預載入的快取資料）

        Args:
            loader_type: 載入器類型
            mc_version: Minecraft 版本
        """
        try:

            def set_loading():
                if is_qobject_alive(self.loader_version_combo):
                    self._update_combo_state(
                        self.loader_version_combo,
                        self.loader_version_var,
                        f"正在載入 {loader_type} 版本...",
                        enabled=True,
                    )

            run_on_ui_thread(set_loading)
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
                        version_names = []
                        for v in versions:
                            if hasattr(v, "version"):
                                version_names.append(v.version)
                            elif isinstance(v, str):
                                version_names.append(v)
                            else:
                                version_names.append(str(v))
                        self.loader_version_combo.clear()
                        self.loader_version_combo.addItems(version_names)
                        self.loader_version_combo.setEnabled(True)
                        if version_names:
                            self.loader_version_combo.setCurrentText(version_names[0])
                            self.loader_version_var.set(version_names[0])
                    else:
                        self._update_combo_state(
                            self.loader_version_combo, self.loader_version_var, "無可用版本", enabled=False
                        )
                    if hasattr(self, "_loading_key"):
                        delattr(self, "_loading_key")
                except Exception as e:
                    logger.error(f"更新載入器版本 UI 失敗: {e}\n{traceback.format_exc()}")
                    if hasattr(self, "_loading_key"):
                        delattr(self, "_loading_key")

            run_on_ui_thread(update_ui)
        except Exception as e:
            logger.error(f"載入載入器版本失敗: {e}\n{traceback.format_exc()}")

            def handle_error():
                try:
                    if is_qobject_alive(self.loader_version_combo):
                        self._update_combo_state(
                            self.loader_version_combo, self.loader_version_var, "載入失敗", enabled=True
                        )
                except Exception as e2:
                    logger.exception(f"更新載入器版本失敗狀態 UI 失敗: {e2}")
                if hasattr(self, "_loading_key"):
                    delattr(self, "_loading_key")

            run_on_ui_thread(handle_error)

    def _capture_creation_request(self) -> tuple[ServerConfig, str | None] | None:
        """一次擷取表單；UI 執行即時完整驗證，不符規範時立即中斷並提示使用者"""
        name = self.server_name_var.get().strip()
        if not name:
            UIUtils.show_message("錯誤", "請輸入伺服器名稱", self.window(), message_level="error")
            return None
        if len(name) > 100:
            UIUtils.show_message("錯誤", "伺服器名稱過長（上限 100 字元）", self.window(), message_level="error")
            return None

        if any(c in name for c in '<>:"/\\|?*') or name.endswith((".", " ")):
            UIUtils.show_message(
                "錯誤", "伺服器名稱包含 Windows 不允許的特殊字元或結尾為空格/點", self.window(), message_level="error"
            )
            return None
        if name in {".", ".."} or Path(name).name != name:
            UIUtils.show_message("錯誤", "無效的伺服器名稱", self.window(), message_level="error")
            return None

        minecraft_version = self.mc_version_var.get().strip()
        invalid_versions = {"載入中...", "載入失敗", "無可用版本", "unknown", "Unknown", ""}
        if not minecraft_version or minecraft_version in invalid_versions:
            UIUtils.show_message("錯誤", "請選擇有效的 Minecraft 版本", self.window(), message_level="error")
            return None

        loader_type = self.loader_type_var.get().strip()
        if not loader_type:
            loader_type = "Vanilla"

        if name == "我的伺服器":
            name = self._compose_server_name(loader_type, minecraft_version)
            self.server_name_var.set(name)

        if name in self.server_crud.servers or (self.server_crud.servers_root / name).exists():
            UIUtils.show_message(
                "錯誤", f"同名伺服器「{name}」已存在，請使用其他名稱", self.window(), message_level="error"
            )
            return None

        loader_version = (
            self.loader_version_var.get().strip() if loader_type.lower() != "vanilla" else minecraft_version
        )
        invalid_loader_versions = {"載入中...", "載入失敗", "無可用版本", "無", "unknown", "Unknown", ""}
        if loader_type.lower() != "vanilla" and (not loader_version or loader_version in invalid_loader_versions):
            UIUtils.show_message(
                "錯誤", f"請選擇有效的 {loader_type} 模組載入器版本", self.window(), message_level="error"
            )
            return None

        max_memory_text = self.max_memory_var.get().strip()
        min_memory_text = self.min_memory_var.get().strip()
        total_memory_mb = SystemUtils.get_total_memory_mb()
        mem_result = MemoryUtils.validate_and_normalize_server_memory(
            max_memory_text, min_memory_text, total_memory_mb=total_memory_mb
        )
        if not mem_result.is_valid:
            UIUtils.show_message(
                "錯誤", mem_result.error_message or "記憶體設定無效", self.window(), message_level="error"
            )
            return None

        if mem_result.adjusted_max:
            self.max_memory_var.set(str(mem_result.memory_max_mb))
        if mem_result.adjusted_min and mem_result.memory_min_mb is not None:
            self.min_memory_var.set(str(mem_result.memory_min_mb))
        for warning in mem_result.warning_messages:
            UIUtils.show_message("記憶體調整", warning, self.window(), message_level="warning")

        memory_max_mb = mem_result.memory_max_mb
        memory_min_mb = mem_result.memory_min_mb

        user_java_path = self.java_path_var.get().strip() or None
        if user_java_path:
            java_file = Path(user_java_path)
            if not java_file.is_file():
                UIUtils.show_message(
                    "錯誤", f"指定的 Java 執行檔不存在：{user_java_path}", self.window(), message_level="error"
                )
                return None

        if not self.selected_jvm_args and not self.jvm_args_customized:
            self.update_default_jvm_args()

        config = ServerConfig(
            name=name,
            minecraft_version=minecraft_version,
            loader_type=loader_type,
            loader_version=loader_version,
            memory_max_mb=memory_max_mb,
            memory_min_mb=memory_min_mb,
            jvm_args=self.selected_jvm_args.copy(),
            path="",
        )
        return config, user_java_path

    def create_server(self):
        """建立伺服器"""
        request = self._capture_creation_request()
        if request is None:
            return
        config, user_java_path = request
        self.scope.submit(
            lambda: self.create_server_async(config, user_java_path),
            key="create_server",
            critical=True,
        )

    def create_server_async(self, config: ServerConfig, user_java_path: str | None) -> None:
        """
        非同步建立伺服器

        Args:
            config: 伺服器建立設定
        """
        parent_window = self.window()
        progress_dialog = None
        try:

            def _create_progress_dialog(title: str):
                dlg = ProgressDialog(parent_window, title)
                dlg.show()
                return dlg

            progress_dialog = run_on_ui_thread(lambda: _create_progress_dialog("正在規劃伺服器"), timeout=10)
            if progress_dialog is None:
                raise Exception("建立進度對話框失敗")

            progress_dialog.update_progress(2, "正在產生並驗證建立計畫...")
            plan = self.server_creation.plan(
                config,
                user_java_path=user_java_path,
            )
            run_on_ui_thread(progress_dialog.close)
            progress_dialog = None
            confirmed = run_on_ui_thread(
                lambda: ServerCreationConfirmDialog(plan, parent=parent_window).exec(),
                timeout=300,
            )
            if confirmed is not True:
                return

            progress_dialog = run_on_ui_thread(lambda: _create_progress_dialog("正在建立伺服器"), timeout=10)
            if progress_dialog is None:
                raise Exception("建立進度對話框失敗")

            result = self.server_creation.execute(
                plan,
                allow_unverified_installer=plan.requires_unverified_installer_confirmation,
                progress_callback=lambda percent, message: progress_dialog.update_progress(percent, message),
                cancel_check=lambda: bool(progress_dialog.cancelled),
            )
            if result.status == "cancelled":
                run_on_ui_thread(progress_dialog.close)
                run_on_ui_thread(
                    lambda: UIUtils.show_message("取消", result.message, parent_window, message_level="info")
                )
                return
            if not result.completed or result.config is None:
                run_on_ui_thread(progress_dialog.close)
                raise RuntimeError(result.message)

            def on_success():
                progress_dialog.close()
                self.callback(result.config)

            self._schedule_ui_job("_create_server_success_job", 1000, on_success)
        except Exception as e:
            logger.error(f"建立伺服器時發生錯誤: {e}\n{traceback.format_exc()}")

            def on_error(error=e):
                if progress_dialog:
                    progress_dialog.close()
                UIUtils.show_message(
                    "建立失敗", f"建立伺服器時發生錯誤：\n{error}", parent_window, message_level="error"
                )

            self._schedule_ui_job("_create_server_error_job", 0, on_error)

    def destroy(self, destroyWindow: bool = True, destroySubWindows: bool = True) -> None:
        """
        銷毀頁面前先清理待執行排程工作

        Args:
            destroyWindow: 是否銷毀目前 Qt 視窗
            destroySubWindows: 是否一併銷毀子視窗
        """
        self._cancel_create_server_jobs()
        super().destroy(destroyWindow, destroySubWindows)

    def _set_warning_text(self, text: str, color: Any = Colors.TEXT_ERROR) -> None:
        self.memory_warning_label.setText(text)

        self.memory_warning_label.setStyleSheet(f"color: {resolve_color(color)};")

    def _make_label(self, text: str, *, muted: bool = False, bold: bool = True) -> StrongBodyLabel | BodyLabel:
        label = StrongBodyLabel(text) if bold else BodyLabel(text)
        label.setProperty("isMuted", muted)
        label.setMinimumWidth(143)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        if not hasattr(self, "_form_labels"):
            self._form_labels = []
        self._form_labels.append(label)
        return label

    def _style_control(self, widget, *, height: int = 32) -> None:
        widget.setMinimumHeight(height)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if isinstance(widget, LineEdit):
            widget.setMinimumWidth(Sizes.INPUT_WIDTH)

    def _make_button(
        self, text: str, command: Callable[[], Any], *, kind: str = "secondary", parent: QWidget | None = None
    ) -> PushButton | PrimaryPushButton:
        btn_parent = parent or self
        button = PrimaryPushButton(text, btn_parent) if kind == "primary" else PushButton(text, btn_parent)
        button.setProperty("msm_button_kind", kind)
        button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        button.setFont(_qt_font(FontManager.get_font(size=FontSize.MEDIUM, weight="bold")))
        button.setMinimumHeight(30)
        button.clicked.connect(lambda _checked=False: command())
        return button

    def _bind_entry(self, entry: LineEdit, variable: ValueState) -> None:
        entry.setText(str(variable.get()))
        entry.textChanged.connect(variable.set)

        def _sync_from_var(value: object) -> None:
            text = str(value or "")
            if entry.text() != text:
                entry.setText(text)

        variable.changed.connect(_sync_from_var)

    def _bind_combo(self, combo: ScrollableComboBox, variable: ValueState) -> None:
        combo.currentTextChanged.connect(variable.set)

        def _sync_from_var(value: object) -> None:
            text = str(value or "")
            if combo.currentText() != text:
                combo.setCurrentText(text)

        variable.changed.connect(_sync_from_var)

    def _schedule_ui_job(self, job_attr: str, delay_ms: int, callback: Callable[[], Any]) -> None:
        """透過主執行緒佇列建立 debounce 排程"""

        def _schedule() -> None:
            if not is_qobject_alive(self):
                return
            UIUtils.schedule_debounce(self, job_attr, delay_ms, callback, owner=self)

        run_on_ui_thread(_schedule)

    def _cancel_create_server_jobs(self) -> None:
        """取消建立伺服器流程相關的待執行 UI 工作"""
        for job_attr in ("_create_server_progress_job", "_create_server_success_job", "_create_server_error_job"):
            UIUtils.cancel_scheduled_job(self, job_attr, owner=self)

    def _update_combo_state(self, combo: ScrollableComboBox, var=None, message="載入中...", enabled=False) -> None:
        """統一更新下拉選單狀態"""
        combo.clear()
        combo.addItem(message)
        combo.setCurrentText(message)
        if var:
            var.set(message)
        combo.setEnabled(enabled)

    def _get_combo_items(self, combo: ScrollableComboBox) -> list[str]:
        return [combo.itemText(i) for i in range(combo.count())]

    def _run_background_task(self, task_func: Callable, error_msg: str, error_callback: Callable | None = None) -> None:
        """執行背景任務並處理錯誤"""

        def _work() -> None:
            task_func()

        def _on_done(outcome: WorkOutcome) -> None:
            if outcome.is_failed:
                logger.exception("%s: %s", error_msg, outcome.error)
                if error_callback is not None:
                    error_callback()

        self.scope.submit(_work, on_done=_on_done, replace=False)


__all__ = ["CreateServerFrame"]
