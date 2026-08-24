"""JVM 參數設定對話框模組"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    LineEdit,
    PushButton,
    ScrollArea,
    TitleLabel,
    ToolTipFilter,
    ToolTipPosition,
)

from src.ui import ModalMSFluentWindow
from src.utils import JvmOptionPolicy


class JvmArgsDialog(ModalMSFluentWindow):
    """JVM 參數設定對話框"""

    def __init__(
        self,
        java_major: int | None,
        memory_max_mb: int,
        loader_type: str = "",
        existing_args: list[str] | None = None,
        parent: Any = None,
    ):
        super().__init__(parent, is_modal=True, show_buttons=True)
        self.setWindowTitle("JVM 啟動參數設定")
        self.resize(700, 500)

        self.java_major = java_major
        self.memory_max_mb = memory_max_mb
        self.loader_type = loader_type

        self.recommended_details = JvmOptionPolicy.get_recommended_jvm_args_details(
            java_major=self.java_major,
            memory_max_mb=self.memory_max_mb,
            loader_type=self.loader_type,
        )
        self.recommended_args_set = {arg[0] for arg in self.recommended_details}

        self.normalized_existing = JvmOptionPolicy.normalize_jvm_args(existing_args) if existing_args else []
        self.custom_args = [arg for arg in self.normalized_existing if arg not in self.recommended_args_set]
        self.is_first_time = existing_args is None

        self.checkboxes: dict[str, CheckBox] = {}

        self._setup_ui()

    def _setup_ui(self) -> None:
        title_label = TitleLabel("JVM 參數設定", self.widget)
        self.viewLayout.addWidget(title_label)

        desc_text = "Java 21+ 建議使用 ZGC；Java 8/16/17 建議使用 G1GC。滑鼠游標移至項目可查看說明。"
        if self.java_major and self.java_major >= 21:
            desc_text = (
                f"目前偵測為 Java {self.java_major}，已自動切換至 ZGC 低延遲優化設定。滑鼠游標移至項目可查看說明。"
            )
        elif self.java_major:
            desc_text = f"目前偵測為 Java {self.java_major}，已自動切換至 G1GC (Aikar's Flags) 優化設定。滑鼠游標移至項目可查看說明。"

        desc_label = BodyLabel(desc_text, self.widget)
        desc_label.setWordWrap(True)
        self.viewLayout.addWidget(desc_label)

        self.scroll_area = ScrollArea(self.widget)
        self.scroll_area.setWidgetResizable(True)

        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(0, 0, 16, 0)
        self.scroll_layout.setSpacing(10)

        for arg, desc in self.recommended_details:
            cb = CheckBox(arg, self.scroll_widget)
            cb.setToolTipDuration(10000)
            cb.setToolTip(desc)
            cb.installEventFilter(ToolTipFilter(cb, showDelay=300, position=ToolTipPosition.BOTTOM))

            if self.is_first_time:
                cb.setChecked(True)
            else:
                cb.setChecked(arg in self.normalized_existing)

            self.checkboxes[arg] = cb
            self.scroll_layout.addWidget(cb)

        self.scroll_layout.addSpacing(10)
        self.custom_args_cb = CheckBox("其他自訂參數", self.scroll_widget)
        self.custom_args_cb.setChecked(bool(self.custom_args))
        self.scroll_layout.addWidget(self.custom_args_cb)

        self.custom_args_input = LineEdit(self.scroll_widget)
        self.custom_args_input.setPlaceholderText("請輸入額外的 JVM 參數，以逗號分隔")
        self.custom_args_input.setText(",".join(self.custom_args))
        self.custom_args_input.setEnabled(bool(self.custom_args))
        self.scroll_layout.addWidget(self.custom_args_input)

        self.custom_args_cb.stateChanged.connect(
            lambda state: self.custom_args_input.setEnabled(state == Qt.CheckState.Checked.value)
        )

        self.scroll_layout.addStretch(1)
        self.scroll_area.setWidget(self.scroll_widget)

        self.viewLayout.addWidget(self.scroll_area, 1)

        self.reset_button = PushButton("重設為建議預設", self.buttonGroup)
        self.reset_button.clicked.connect(self._reset_to_default)
        self.buttonLayout.insertWidget(0, self.reset_button)

    def _reset_to_default(self) -> None:
        """重設為預設全部勾選，並清空自訂參數"""
        for cb in self.checkboxes.values():
            cb.setChecked(True)
        self.custom_args_cb.setChecked(False)
        self.custom_args_input.clear()
        self.custom_args_input.setEnabled(False)

    def get_jvm_args(self) -> list[str]:
        """
        取得使用者勾選與自訂的最終 JVM 參數列表

        Returns:
            完整的 JVM 參數列表字串
        """
        args = []
        for arg, cb in self.checkboxes.items():
            if cb.isChecked():
                args.append(arg)

        if self.custom_args_cb.isChecked():
            custom_text = self.custom_args_input.text().strip()
            if custom_text:
                tokens = [t.strip() for t in custom_text.replace(",", " ").split() if t.strip()]
                args.extend(tokens)

        return args


__all__ = ["JvmArgsDialog"]
