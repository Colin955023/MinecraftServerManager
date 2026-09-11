"""伺服器建立參數確認對話框"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QFormLayout
from qfluentwidgets import BodyLabel, LineEdit, PlainTextEdit, StrongBodyLabel, SubtitleLabel, TitleLabel

from src.models import ServerCreationPlan
from src.ui import (
    FontManager,
    FontSize,
)

from .modal_msfluent_window import ModalMSFluentWindow


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
        self.confirmation = plan.confirmation
        if self.confirmation is None:
            raise ValueError("建立計畫缺少確認投影")
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

        projection = self.confirmation
        _add_readonly_field("伺服器名稱:", projection.name)
        _add_readonly_field("Minecraft 版本:", projection.minecraft_version)
        loader_text = (
            "Vanilla (無載入器)"
            if projection.loader_type == "vanilla"
            else f"{projection.loader_type.capitalize()} {projection.loader_version}"
        )
        _add_readonly_field("模組載入器:", loader_text)
        _add_readonly_field("Java 執行檔:", projection.java_executable)

        mem_text = f"最大 {projection.memory_max_mb} MB"
        if projection.memory_min_mb:
            mem_text += f" / 最小 {projection.memory_min_mb} MB"
        _add_readonly_field("記憶體設定:", mem_text)

        self.viewLayout.addLayout(form_layout)

        jvm_label = StrongBodyLabel("完整 JVM 啟動參數:", self.widget)
        jvm_label.setFont(FontManager.get_font(size=FontSize.NORMAL_PLUS, weight="bold"))
        self.viewLayout.addWidget(jvm_label)

        self.jvm_text_edit = PlainTextEdit(self.widget)
        self.jvm_text_edit.setReadOnly(True)

        self.jvm_text_edit.setPlainText(" ".join(projection.command))
        self.viewLayout.addWidget(self.jvm_text_edit, 1)

        if projection.warnings:
            warning_title = StrongBodyLabel("建立計畫警告:", self.widget)
            warning_title.setFont(FontManager.get_font(size=FontSize.NORMAL_PLUS, weight="bold"))
            self.viewLayout.addWidget(warning_title)
            warning_text = BodyLabel("\n".join(f"• {message}" for message in projection.warnings), self.widget)
            warning_text.setWordWrap(True)
            self.viewLayout.addWidget(warning_text)

        self.yesButton.setText("確認並建立")


__all__ = ["ServerCreationConfirmDialog"]
