"""
伺服器記憶體設定對話框
提供視覺化介面調整伺服器的最大與最小記憶體設定
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TitleLabel,
)

from src.core import ServerCRUD
from src.models import ServerConfig
from src.ui import ModalMSFluentWindow
from src.utils import (
    Colors,
    MemoryUtils,
    ServerCommands,
    Spacing,
    SystemUtils,
    UIUtils,
    get_logger,
    resolve_color,
)

logger = get_logger().bind(component="ServerMemoryDialog")


class ServerMemoryDialog(ModalMSFluentWindow):
    """伺服器記憶體設定對話框"""

    def __init__(
        self,
        config: ServerConfig,
        server_crud: ServerCRUD,
        parent: Any = None,
    ):
        super().__init__(parent, is_modal=True, show_buttons=False)
        self.config = config
        self.server_crud = server_crud
        self.setWindowTitle(f"修改記憶體設定 - {config.name}")
        self.setMinimumSize(480, 420)
        self.resize(520, 460)

        self._init_ui()

    def _init_ui(self) -> None:
        """初始化對話框介面"""
        layout = self.viewLayout
        layout.setSpacing(Spacing.MEDIUM)
        layout.setContentsMargins(Spacing.LARGE, Spacing.LARGE, Spacing.LARGE, Spacing.LARGE)

        title = TitleLabel("🧠 修改伺服器記憶體", self.widget)
        title.setStyleSheet("background: transparent;")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)

        desc = CaptionLabel(
            f"伺服器：{self.config.name} ({self.config.minecraft_version} {self.config.loader_type})\n"
            "請設定 JVM 堆疊記憶體（單位為 MB，1 GB = 1024 MB）：",
            self.widget,
        )
        desc.setStyleSheet("background: transparent;")
        layout.addWidget(desc)

        total_mb = SystemUtils.get_total_memory_mb()
        if total_mb > 0:
            sys_info = BodyLabel(f"💻 系統實體記憶體總量：{total_mb} MB ({total_mb // 1024} GB)", self.widget)
            sys_info.setStyleSheet("background: transparent;")
            layout.addWidget(sys_info)

        card = CardWidget(self.widget)
        card.setStyleSheet(
            "CardWidget { background-color: transparent; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px; }"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(Spacing.MEDIUM)
        card_layout.setContentsMargins(Spacing.LARGE, Spacing.LARGE, Spacing.LARGE, Spacing.LARGE)

        sub_title = SubtitleLabel("記憶體設定 (MB)", card)
        sub_title.setStyleSheet("background: transparent;")
        card_layout.addWidget(sub_title)

        h_max = QHBoxLayout()
        max_label = BodyLabel("最大記憶體 (-Xmx):", card)
        max_label.setStyleSheet("background: transparent;")
        max_label.setFixedWidth(150)
        self.max_memory_input = LineEdit(card)
        self.max_memory_input.setPlaceholderText("例如: 4096")
        self.max_memory_input.setText(str(self.config.memory_max_mb or 2048))
        h_max.addWidget(max_label)
        h_max.addWidget(self.max_memory_input)
        card_layout.addLayout(h_max)

        h_min = QHBoxLayout()
        min_label = BodyLabel("最小記憶體 (-Xms):", card)
        min_label.setStyleSheet("background: transparent;")
        min_label.setFixedWidth(150)
        self.min_memory_input = LineEdit(card)
        self.min_memory_input.setPlaceholderText("選填，例如: 1024")
        self.min_memory_input.setText(str(self.config.memory_min_mb or "") if self.config.memory_min_mb else "")
        h_min.addWidget(min_label)
        h_min.addWidget(self.min_memory_input)
        card_layout.addLayout(h_min)

        self.memory_tip = CaptionLabel(
            "最小記憶體選填，若留空由 Java 決定\n最大記憶體(必填)建議： 2048MB (最低) | 4096MB (一般) | 8192MB (多人遊戲)",
            card,
        )
        self.memory_tip.setStyleSheet("background: transparent;")
        self.memory_tip.setWordWrap(True)
        card_layout.addWidget(self.memory_tip)

        self.memory_warning_label = CaptionLabel("", card)
        self.memory_warning_label.setStyleSheet(f"color: {resolve_color(Colors.TEXT_ERROR)}; background: transparent;")
        self.memory_warning_label.setWordWrap(True)
        card_layout.addWidget(self.memory_warning_label)

        self.max_memory_input.textChanged.connect(self._update_memory_warning)
        self.min_memory_input.textChanged.connect(self._update_memory_warning)

        layout.addWidget(card)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(Spacing.MEDIUM)
        btn_layout.addStretch()

        self.cancel_btn = PushButton("取消", self.widget)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.save_btn = PrimaryPushButton("儲存變更", self.widget)
        self.save_btn.clicked.connect(self._save_memory_settings)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)
        self._update_memory_warning()

    def _update_memory_warning(self) -> None:
        """即時更新記憶體警告標籤"""
        max_str = self.max_memory_input.text().strip()
        min_str = self.min_memory_input.text().strip()
        if not max_str:
            self.memory_warning_label.setText("")
            return

        try:
            max_mb = int(max_str)
        except ValueError:
            self.memory_warning_label.setText("⚠️ 警告：最大記憶體必須為有效的整數")
            self.memory_warning_label.setStyleSheet(
                f"color: {resolve_color(Colors.TEXT_ERROR)}; background: transparent;"
            )
            return

        min_mb: int | None = None
        if min_str:
            try:
                min_mb = int(min_str)
            except ValueError:
                self.memory_warning_label.setText("⚠️ 警告：最小記憶體必須為有效的整數")
                self.memory_warning_label.setStyleSheet(
                    f"color: {resolve_color(Colors.TEXT_ERROR)}; background: transparent;"
                )
                return

        total_mb = SystemUtils.get_total_memory_mb()
        half_total_mb = total_mb // 2 if total_mb > 0 else 0

        if max_mb < 1024:
            self.memory_warning_label.setText("⚠️ 警告：最大記憶體不可低於 1024 MB")
            self.memory_warning_label.setStyleSheet(
                f"color: {resolve_color(Colors.TEXT_ERROR)}; background: transparent;"
            )
        elif min_mb is not None and min_mb > max_mb:
            self.memory_warning_label.setText("⚠️ 警告：最小記憶體必須小於或等於最大記憶體")
            self.memory_warning_label.setStyleSheet(
                f"color: {resolve_color(Colors.TEXT_ERROR)}; background: transparent;"
            )
        elif total_mb > 0 and (max_mb > total_mb or (min_mb is not None and min_mb > total_mb)):
            self.memory_warning_label.setText(f"⚠️ 警告：設定記憶體超過系統總實體記憶體 ({total_mb} MB)")
            self.memory_warning_label.setStyleSheet(
                f"color: {resolve_color(Colors.TEXT_ERROR)}; background: transparent;"
            )
        elif total_mb > 0 and max_mb > half_total_mb:
            self.memory_warning_label.setText(f"⚠️ 提示：設定記憶體超過系統記憶體的一半 ({half_total_mb} MB)")
            self.memory_warning_label.setStyleSheet(
                f"color: {resolve_color(Colors.TEXT_WARNING)}; background: transparent;"
            )
        else:
            self.memory_warning_label.setText("")

    def _save_memory_settings(self) -> None:
        """驗證並儲存記憶體設定"""
        max_text = self.max_memory_input.text().strip()
        min_text = self.min_memory_input.text().strip()
        total_mb = SystemUtils.get_total_memory_mb()

        result = MemoryUtils.validate_and_normalize_server_memory(max_text, min_text, total_memory_mb=total_mb)
        if not result.is_valid:
            UIUtils.show_message("輸入錯誤", result.error_message or "記憶體設定無效", self, message_level="error")
            return

        if result.adjusted_max:
            self.max_memory_input.setText(str(result.memory_max_mb))
        if result.adjusted_min and result.memory_min_mb is not None:
            self.min_memory_input.setText(str(result.memory_min_mb))
        for warning in result.warning_messages:
            UIUtils.show_message("記憶體調整", warning, self, message_level="warning")

        max_mb = result.memory_max_mb
        min_mb = result.memory_min_mb

        updated_config = ServerConfig(
            name=self.config.name,
            minecraft_version=self.config.minecraft_version,
            loader_type=self.config.loader_type,
            loader_version=self.config.loader_version,
            memory_max_mb=max_mb,
            memory_min_mb=min_mb,
            jvm_args=list(self.config.jvm_args),
            path=self.config.path,
        )

        try:
            previous_config = self.server_crud.servers.get(self.config.name, self.config)
            self.server_crud.servers[self.config.name] = updated_config
            if not self.server_crud.write_servers_config():
                self.server_crud.servers[self.config.name] = previous_config
                UIUtils.show_message(
                    "儲存失敗", "無法寫入伺服器設定檔，記憶體設定未套用。", self, message_level="error"
                )
                return

            server_path = Path(self.config.path)
            if server_path.exists():
                if (
                    str(updated_config.loader_type or "").lower() in ("forge", "neoforge")
                    and (server_path / "user_jvm_args.txt").exists()
                ):
                    ServerCommands.update_forge_user_jvm_args(server_path, updated_config)
                start_bat = server_path / "start_server.bat"
                if start_bat.exists():
                    ServerCommands.repair_startup_script_java_command(start_bat, updated_config)
                else:
                    self.server_crud.create_launch_script(updated_config)

            self.config = updated_config
            UIUtils.show_message(
                "設定成功",
                f"伺服器「{self.config.name}」記憶體已更新：\n最大: {max_mb} MB"
                + (f"\n最小: {min_mb} MB" if min_mb else ""),
                self.parent(),
                message_level="info",
            )
            self.accept()
        except Exception as e:
            logger.exception(f"儲存記憶體設定失敗: {e}")
            UIUtils.show_message("儲存失敗", f"更新記憶體設定時發生錯誤: {e}", self, message_level="error")


__all__ = ["ServerMemoryDialog"]
