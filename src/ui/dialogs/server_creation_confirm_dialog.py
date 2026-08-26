"""伺服器建立參數確認對話框"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QFormLayout
from qfluentwidgets import BodyLabel, CheckBox, LineEdit, PlainTextEdit, StrongBodyLabel, SubtitleLabel, TitleLabel

from src.models import ServerCreationPlan
from src.ui import ModalMSFluentWindow
from src.utils import FontManager, FontSize, ServerCommands


class ServerCreationConfirmDialog(ModalMSFluentWindow):
    """建立伺服器參數確認對話框"""

    def __init__(
        self,
        plan: ServerCreationPlan,
        parent: Any = None,
    ) -> None:
        super().__init__(parent, is_modal=True, show_buttons=True)
        self.setWindowTitle("確認建立伺服器參數")
        self.resize(640, 600)
        self.plan = plan
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

        _add_readonly_field("伺服器名稱:", self.plan.name)
        _add_readonly_field("Minecraft 版本:", self.plan.minecraft_version)
        loader_text = (
            "Vanilla (無載入器)"
            if self.plan.loader_type == "vanilla"
            else f"{self.plan.loader_type.capitalize()} {self.plan.loader_version}"
        )
        _add_readonly_field("模組載入器:", loader_text)

        mem_text = f"最大 {self.plan.memory_max_mb} MB"
        if self.plan.memory_min_mb:
            mem_text += f" / 最小 {self.plan.memory_min_mb} MB"
        _add_readonly_field("記憶體設定:", mem_text)

        self.viewLayout.addLayout(form_layout)

        jvm_label = StrongBodyLabel("完整 JVM 啟動參數:", self.widget)
        jvm_label.setFont(FontManager.get_font(size=FontSize.NORMAL_PLUS, weight="bold"))
        self.viewLayout.addWidget(jvm_label)

        self.jvm_text_edit = PlainTextEdit(self.widget)
        self.jvm_text_edit.setReadOnly(True)

        config = self.plan.build_config(self.plan.final_path)
        self.jvm_text_edit.setPlainText(str(ServerCommands.build_java_command(config)))
        self.viewLayout.addWidget(self.jvm_text_edit, 1)

        if self.plan.warnings:
            warning_title = StrongBodyLabel("建立計畫警告:", self.widget)
            warning_title.setFont(FontManager.get_font(size=FontSize.NORMAL_PLUS, weight="bold"))
            self.viewLayout.addWidget(warning_title)
            warning_text = BodyLabel("\n".join(f"• {warning.message}" for warning in self.plan.warnings), self.widget)
            warning_text.setWordWrap(True)
            self.viewLayout.addWidget(warning_text)

        if self.plan.requires_unverified_installer_confirmation:
            consent = CheckBox("我了解安裝器缺少 checksum 驗證資訊，仍同意執行此建立計畫", self.widget)
            consent.stateChanged.connect(lambda state: self.yesButton.setEnabled(bool(state)))
            self.viewLayout.addWidget(consent)
            self.yesButton.setEnabled(False)

        self.yesButton.setText("確認並建立")


__all__ = ["ServerCreationConfirmDialog"]
