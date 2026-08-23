"""伺服器建立參數確認對話框"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QFormLayout, QPlainTextEdit
from qfluentwidgets import LineEdit, StrongBodyLabel, SubtitleLabel, TitleLabel

from src.ui import ModalMSFluentWindow
from src.utils import Colors, FontManager, FontSize, JvmOptionPolicy, ServerDetectionUtils, resolve_color


class ServerCreationConfirmDialog(ModalMSFluentWindow):
    """建立伺服器參數確認對話框"""

    def __init__(
        self,
        server_name: str,
        mc_version: str,
        loader_type: str,
        loader_version: str,
        memory_max_mb: int,
        memory_min_mb: int | None,
        jvm_args: list[str],
        parent: Any = None,
    ):
        super().__init__(parent, is_modal=True, show_buttons=True)
        self.setWindowTitle("確認建立伺服器參數")
        self.resize(600, 500)

        self.server_name = server_name
        self.mc_version = mc_version
        self.loader_type = loader_type
        self.loader_version = loader_version
        self.memory_max_mb = memory_max_mb
        self.memory_min_mb = memory_min_mb
        self.jvm_args = jvm_args

        self._setup_ui()

    def _setup_ui(self) -> None:
        title_label = TitleLabel("確認建立伺服器參數", self.widget)
        title_label.setFont(FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"))
        self.viewLayout.addWidget(title_label)

        desc_label = SubtitleLabel("在開始建立伺服器前，請確認以下設定是否正確：", self.widget)
        desc_label.setFont(FontManager.get_font(size=FontSize.MEDIUM))
        self.viewLayout.addWidget(desc_label)

        form_layout = QFormLayout()
        form_layout.setContentsMargins(10, 10, 10, 10)
        form_layout.setSpacing(10)

        def _add_readonly_field(label: str, text: str) -> None:
            le = LineEdit(self.widget)
            le.setText(text)
            le.setReadOnly(True)
            lbl = StrongBodyLabel(label, self.widget)
            lbl.setFont(FontManager.get_font(size=13, weight="bold"))
            form_layout.addRow(lbl, le)

        _add_readonly_field("伺服器名稱:", self.server_name)
        _add_readonly_field("Minecraft 版本:", self.mc_version)
        loader_text = (
            "Vanilla (無載入器)"
            if self.loader_type.lower() == "vanilla"
            else f"{self.loader_type.capitalize()} {self.loader_version}"
        )
        _add_readonly_field("模組載入器:", loader_text)

        mem_text = f"最大 {self.memory_max_mb} MB"
        if self.memory_min_mb:
            mem_text += f" / 最小 {self.memory_min_mb} MB"
        _add_readonly_field("記憶體設定:", mem_text)

        self.viewLayout.addLayout(form_layout)

        jvm_label = StrongBodyLabel("完整 JVM 啟動參數:", self.widget)
        jvm_label.setFont(FontManager.get_font(size=FontSize.NORMAL_PLUS, weight="bold"))
        self.viewLayout.addWidget(jvm_label)

        self.jvm_text_edit = QPlainTextEdit(self.widget)
        self.jvm_text_edit.setReadOnly(True)

        mem_min = self.memory_min_mb
        mem_max = self.memory_max_mb or 2048
        if mem_min is not None and mem_max < mem_min:
            mem_max = mem_min

        custom_args = JvmOptionPolicy.normalize_jvm_args(self.jvm_args)
        recommended_args = JvmOptionPolicy.recommend_gc_args(
            memory_max_mb=mem_max,
            java_major=None,
            loader_type=self.loader_type.lower(),
            existing_args=custom_args,
        )

        expected_jar = ServerDetectionUtils.get_expected_main_jar(self.loader_type, self.mc_version)
        cmd_list = ["java"]
        if mem_min:
            cmd_list.append(f"-Xms{mem_min}M")
        if self.memory_max_mb:
            cmd_list.append(f"-Xmx{self.memory_max_mb}M")
        cmd_list.extend(recommended_args)
        cmd_list.extend(custom_args)
        cmd_list.extend([expected_jar if expected_jar.startswith("@") else f"-jar {expected_jar}", "nogui"])

        full_command = " ".join(cmd_list)

        self.jvm_text_edit.setPlainText(full_command)
        self.viewLayout.addWidget(self.jvm_text_edit, 1)

        self.yesButton.setText("確認並建立")
        self._apply_theme_styles()

    def _apply_theme_styles(self) -> None:
        """更新對話框內部元件之樣式以響應主題切換"""
        super()._apply_theme_styles()
        if not hasattr(self, "jvm_text_edit") or not self.jvm_text_edit:
            return

        border_color = resolve_color(Colors.BORDER_LIGHT)
        text_color = resolve_color(Colors.TEXT_PRIMARY)
        self.jvm_text_edit.setStyleSheet(
            f"QPlainTextEdit {{ border: 1px solid {border_color}; border-radius: 4px; padding: 5px; background-color: transparent; color: {text_color}; }}"
        )

        if hasattr(self, "widget") and self.widget:
            for le in self.widget.findChildren(LineEdit):
                le.setStyleSheet(f"QLineEdit {{ background: transparent; border: none; color: {text_color}; }}")


__all__ = ["ServerCreationConfirmDialog"]
