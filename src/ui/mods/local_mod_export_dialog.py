"""本地模組列表匯出對話框"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import PrimaryPushButton, PushButton, RadioButton, SubtitleLabel, TitleLabel

from src.core import ModManager
from src.models import ServerConfig
from src.ui import (
    ModalMSFluentWindow,
    Sizes,
    Spacing,
    TextState,
    UIUtils,
    UIWorkScope,
    WorkOutcome,
)
from src.utils import (
    atomic_write_bytes,
    atomic_write_text,
    get_logger,
)

logger = get_logger().bind(component="LocalModExportDialog")


class LocalModExportDialog(ModalMSFluentWindow):
    """本地模組功能擁有的列表匯出對話框"""

    def __init__(self, parent: Any, mod_manager: ModManager, server: ServerConfig):
        super().__init__(parent, is_modal=True, show_buttons=False)
        self.mod_manager = mod_manager
        self.server = server
        self.scope = UIWorkScope(self)
        self.setWindowTitle("匯出模組列表")
        self.resize(Sizes.DIALOG_LARGE_WIDTH, Sizes.DIALOG_LARGE_HEIGHT)
        self.setMinimumSize(Sizes.DIALOG_LARGE_WIDTH, Sizes.DIALOG_LARGE_HEIGHT)
        self._setup_ui()

    def _setup_ui(self) -> None:
        title_label = TitleLabel("匯出模組列表", self.widget)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(title_label)

        fmt_frame = QWidget(self.widget)
        fmt_layout = QHBoxLayout(fmt_frame)
        fmt_layout.setContentsMargins(0, Spacing.MEDIUM, 0, Spacing.MEDIUM)
        fmt_layout.addWidget(SubtitleLabel("選擇匯出格式:", fmt_frame))

        self.fmt_var = TextState(value="text")
        for label, value in (("純文字", "text"), ("JSON", "json"), ("HTML", "html"), ("Excel (.xlsx)", "xlsx")):
            radio = RadioButton(label, fmt_frame)
            radio.setChecked(value == "text")
            radio.toggled.connect(lambda checked, fmt=value: self.fmt_var.set(fmt) if checked else None)
            fmt_layout.addWidget(radio)
        fmt_layout.addStretch(1)
        self.viewLayout.addWidget(fmt_frame)

        btn_frame = QWidget(self.widget)
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setContentsMargins(0, Spacing.MEDIUM, 0, 0)

        def save_export() -> None:
            fmt = self.fmt_var.get()
            ext = {"text": "txt", "json": "json", "html": "html", "xlsx": "xlsx"}[fmt]
            default_name = f"{self.server.name}_模組列表.{ext}"
            file_path = UIUtils.get_save_file_name(
                self,
                "儲存模組列表",
                str(Path(self.server.path) / default_name),
                "所有檔案 (*.*);;純文字 (*.txt);;JSON (*.json);;HTML (*.html);;Excel 試算表 (*.xlsx)",
            )
            if not file_path:
                return

            def write_export(export_content: str | bytes) -> None:
                saved = (
                    atomic_write_bytes(file_path, export_content)
                    if isinstance(export_content, bytes)
                    else atomic_write_text(Path(file_path), export_content)
                )
                if not saved:
                    UIUtils.show_message("儲存失敗", f"無法寫入檔案: {file_path}", self, message_level="error")
                    return
                if UIUtils.ask_yes_no_cancel(
                    "匯出成功", f"已儲存: {file_path}\n\n是否要立即開啟匯出的檔案？", parent=self, show_cancel=False
                ):
                    try:
                        UIUtils.open_external(file_path)
                    except Exception as e:
                        logger.exception("開啟檔案失敗")
                        UIUtils.show_message("開啟檔案失敗", f"無法開啟檔案: {e}", parent=self, message_level="error")

            def build_export() -> str | bytes:
                return self.mod_manager.export_mod_list(fmt)

            def finish_export(outcome: WorkOutcome) -> None:
                if not outcome.is_succeeded:
                    logger.error(f"匯出模組列表失敗: {outcome.error}")
                    UIUtils.show_message(
                        "匯出失敗", f"產生匯出內容時發生錯誤: {outcome.error}", self, message_level="error"
                    )
                    return
                content = outcome.value
                write_export(content)

            self.scope.submit(build_export, on_done=finish_export, key="export_save", replace=True)

        save_btn = PrimaryPushButton("儲存到檔案", btn_frame)
        save_btn.clicked.connect(save_export)
        save_btn.setMinimumWidth(Sizes.MOD_EXPORT_SAVE_BUTTON_WIDTH)
        save_btn.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)
        btn_layout.addWidget(save_btn)

        close_btn = PushButton("關閉", btn_frame)
        close_btn.clicked.connect(self.close)
        close_btn.setMinimumWidth(Sizes.MOD_EXPORT_CLOSE_BUTTON_WIDTH)
        close_btn.setFixedHeight(Sizes.BUTTON_HEIGHT_LARGE)
        btn_layout.addWidget(close_btn)
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(btn_frame)


__all__ = ["LocalModExportDialog"]
