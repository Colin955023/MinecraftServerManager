"""關於與視窗偏好設定整合頁面"""

from __future__ import annotations

import traceback
from typing import Any, ClassVar, cast

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    Theme,
    TitleLabel,
    setTheme,
)

from src.utils import (
    APP_VERSION,
    GITHUB_OWNER,
    GITHUB_REPO,
    BoolState,
    Colors,
    ScrollableComboBox,
    Sizes,
    Spacing,
    TextState,
    UIUtils,
    get_logger,
    get_settings_manager,
    resolve_color,
)

logger = get_logger().bind(component="AboutPreferencesFrame")


class AboutPreferencesFrame(QFrame):
    """整合關於程式與視窗偏好設定的左右分欄頁面"""

    THEME_LABELS: ClassVar[dict[str, str]] = {"system": "依照系統設定", "light": "淺色", "dark": "深色"}
    THEME_MODES: ClassVar[dict[str, str]] = {label: mode for mode, label in THEME_LABELS.items()}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = get_settings_manager()

        self.remember_size_var = BoolState(self.settings.is_remember_size_position_enabled())
        self.auto_center_var = BoolState(self.settings.is_auto_center_enabled())
        self.adaptive_sizing_var = BoolState(self.settings.is_adaptive_sizing_enabled())
        self.theme_mode_var = TextState(self._theme_mode_to_label(self.settings.get_theme_mode()))

        self._create_widgets()
        self._load_current_settings()

    def _theme_mode_to_label(self, mode: str) -> str:
        return self.THEME_LABELS.get(str(mode or "system").lower(), self.THEME_LABELS["system"])

    def _theme_label_to_mode(self, label: str) -> str:
        return self.THEME_MODES.get(str(label or "").strip(), "system")

    def _get_live_main_window_size(self) -> tuple[int, int] | None:
        win = self.window()
        if not win:
            return None
        try:
            width = int(win.width())
            height = int(win.height())
            if width > 0 and height > 0:
                return (width, height)
        except Exception as e:
            logger.debug(f"讀取目前主視窗大小失敗: {e}")
        return None

    def _create_widgets(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(Spacing.LARGE, Spacing.LARGE, Spacing.LARGE, Spacing.LARGE)
        main_layout.setSpacing(Spacing.LARGE)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        about_content = QFrame(self)
        about_layout = QVBoxLayout(about_content)
        about_layout.setContentsMargins(Spacing.MEDIUM, Spacing.MEDIUM, Spacing.MEDIUM, Spacing.MEDIUM)
        about_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._create_about_section(about_layout)
        main_layout.addWidget(about_content, 1)

        self.vertical_separator = QFrame(self)
        self.vertical_separator.setFixedWidth(2)
        self.vertical_separator.setStyleSheet(f"background-color: {resolve_color(Colors.BORDER_LIGHT)};")
        main_layout.addWidget(self.vertical_separator)

        prefs_content = QFrame(self)
        prefs_layout = QVBoxLayout(prefs_content)
        prefs_layout.setContentsMargins(Spacing.MEDIUM, Spacing.MEDIUM, Spacing.MEDIUM, Spacing.MEDIUM)
        prefs_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._create_preferences_section(prefs_layout)
        main_layout.addWidget(prefs_content, 1)

    def _create_about_section(self, layout: QVBoxLayout) -> None:
        title = TitleLabel("🎮 Minecraft 伺服器管理器", self)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self.version_lbl = BodyLabel(f"版本 {APP_VERSION}", self)
        self.version_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_lbl.setStyleSheet(f"color: {resolve_color(Colors.TEXT_TERTIARY)};")
        layout.addWidget(self.version_lbl)

        layout.addSpacing(Spacing.LARGE)

        dev_title = SubtitleLabel("👨‍💻 開發資訊", self)
        layout.addWidget(dev_title)

        dev_info = BodyLabel(
            "• 開發者: Minecraft Server Manager Team\n"
            "• 技術棧: Python 3.14+, PySide6\n"
            "• Java 管理: 自動偵測/下載 Minecraft 官方 JDK\n"
            "• 架構: 模組化設計, 事件驅動\n"
            "• 參考專案: PrismLauncher",
            self,
        )
        layout.addWidget(dev_info)

        layout.addSpacing(Spacing.MEDIUM)

        self.github_url = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
        self.github_lbl = BodyLabel("", self)
        self.github_lbl.setOpenExternalLinks(True)
        self._update_github_link()
        layout.addWidget(self.github_lbl)

        layout.addSpacing(Spacing.LARGE)

        license_title = SubtitleLabel("📄 授權條款", self)
        layout.addWidget(license_title)

        license_info = BodyLabel(
            "• 本專案採用 GNU General Public License v3.0 授權條款\n"
            "• 部分設計理念參考 PrismLauncher\n"
            "• 僅供學習和個人使用\n"
            "• 請遵守 Minecraft EULA 和當地法律法規\n\n"
            "特別感謝 PrismLauncher 開發團隊的開源貢獻！",
            self,
        )
        layout.addWidget(license_info)

        layout.addSpacing(Spacing.LARGE)

        update_title = SubtitleLabel("🔄 更新設定", self)
        layout.addWidget(update_title)

        self.auto_update_checkbox = CheckBox("自動檢查更新", self)
        self.auto_update_checkbox.setChecked(self.settings.is_auto_update_enabled())
        self.auto_update_checkbox.stateChanged.connect(self._on_auto_update_toggled)
        layout.addWidget(self.auto_update_checkbox)

        self.manual_check_btn = PushButton("檢查更新", self)

        def _do_check():
            if hasattr(self.window(), "task_coordinator"):
                cast(Any, self.window()).task_coordinator.manual_check_updates()
            else:
                logger.warning("找不到 task_coordinator，無法手動檢查更新")

        self.manual_check_btn.clicked.connect(_do_check)
        self.manual_check_btn.setVisible(not self.settings.is_auto_update_enabled())
        layout.addWidget(self.manual_check_btn, 0, Qt.AlignmentFlag.AlignLeft)

    def _on_auto_update_toggled(self, state) -> None:
        enabled = state == Qt.CheckState.Checked.value
        self.settings.set_auto_update_enabled(enabled)
        self.manual_check_btn.setVisible(not enabled)

    def _update_github_link(self) -> None:
        if hasattr(self, "github_lbl") and hasattr(self, "github_url"):
            self.github_lbl.setText(
                f"<a href='{self.github_url}' style='color: {resolve_color(Colors.TEXT_LINK)}; text-decoration: none;'>GitHub-MinecraftServerManager</a>"
            )

    def apply_theme_styles(self) -> None:
        """套用主題樣式"""
        self._update_github_link()
        if hasattr(self, "vertical_separator") and self.vertical_separator:
            self.vertical_separator.setStyleSheet(f"background-color: {resolve_color(Colors.BORDER_LIGHT)};")
        if hasattr(self, "version_lbl") and self.version_lbl:
            self.version_lbl.setStyleSheet(f"color: {resolve_color(Colors.TEXT_TERTIARY)};")
        if hasattr(self, "dpi_lbl") and self.dpi_lbl:
            self.dpi_lbl.setStyleSheet(f"color: {resolve_color(Colors.TEXT_SECONDARY)};")

    def _create_preferences_section(self, layout: QVBoxLayout) -> None:
        title = TitleLabel("🖥️ 視窗偏好設定", self)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addSpacing(Spacing.LARGE)

        gen_title = SubtitleLabel("📋 一般設定", self)
        layout.addWidget(gen_title)
        self._create_checkbox(layout, "記住主視窗大小和位置", self.remember_size_var)
        self._create_checkbox(layout, "自動置中新的對話框視窗", self.auto_center_var)
        self._create_checkbox(layout, "啟用自適應視窗大小調整", self.adaptive_sizing_var)
        layout.addSpacing(Spacing.MEDIUM)

        win_title = SubtitleLabel("🏠 主視窗設定", self)
        layout.addWidget(win_title)
        screen = self.window().screen().availableGeometry()
        screen_info = {"width": screen.width(), "height": screen.height()}
        current_settings = self.settings.get_main_window_settings()
        default_settings = self.settings.get_default_main_window_settings()
        live_size = self._get_live_main_window_size()
        current_width, current_height = live_size or (
            current_settings.get("width", default_settings["width"]),
            current_settings.get("height", default_settings["height"]),
        )
        info_text = f"目前螢幕解析度: {screen_info['width']} × {screen_info['height']}\n目前主視窗大小: {current_width} × {current_height}"
        layout.addWidget(BodyLabel(info_text, self))

        reset_button = PushButton("重設為預設大小", self)
        reset_button.setMinimumWidth(Sizes.BUTTON_WIDTH_SMALL)
        UIUtils.apply_danger_style(reset_button)
        reset_button.clicked.connect(self._reset_to_default_size)
        layout.addWidget(reset_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(Spacing.MEDIUM)

        disp_title = SubtitleLabel("🎨 顯示設定", self)
        layout.addWidget(disp_title)

        theme_layout = QHBoxLayout()
        theme_layout.addWidget(BodyLabel("主題模式:", self))
        self.theme_mode_dropdown = ScrollableComboBox(self)
        items = list(self.THEME_MODES.keys())
        self.theme_mode_dropdown.addItems(items)
        if self.theme_mode_var.get() in items:
            self.theme_mode_dropdown.setCurrentIndex(items.index(self.theme_mode_var.get()))

        def _on_combo(idx):
            self.theme_mode_var.set(items[idx])

        self.theme_mode_dropdown.currentIndexChanged.connect(_on_combo)

        def _on_var(*_args):
            val = self.theme_mode_var.get()
            if val in items and self.theme_mode_dropdown.currentIndex() != items.index(val):
                self.theme_mode_dropdown.setCurrentIndex(items.index(val))

        self.theme_mode_var.trace_add("write", _on_var)

        theme_layout.addWidget(self.theme_mode_dropdown)
        theme_layout.addStretch(1)
        layout.addLayout(theme_layout)

        self.dpi_lbl = BodyLabel("介面縮放會跟隨 Windows 顯示比例與 Qt 高 DPI 設定", self)
        self.dpi_lbl.setStyleSheet(f"color: {resolve_color(Colors.TEXT_SECONDARY)};")
        layout.addWidget(self.dpi_lbl)

        layout.addSpacing(Spacing.LARGE)

        btn_layout = QHBoxLayout()
        btn_reset_all = PushButton("恢復預設", self)
        UIUtils.apply_danger_style(btn_reset_all)
        btn_reset_all.clicked.connect(self._reset_all_settings)
        btn_layout.addWidget(btn_reset_all)

        btn_layout.addStretch(1)

        btn_apply = PrimaryPushButton("套用設定", self)
        btn_apply.clicked.connect(self._apply_settings)
        btn_layout.addWidget(btn_apply)

        layout.addLayout(btn_layout)

    def _create_checkbox(self, layout, text: str, variable: BoolState) -> None:
        checkbox = CheckBox(text, self)
        checkbox.setChecked(variable.get())

        def _on_check(checked):
            variable.set(checked == Qt.CheckState.Checked.value)

        checkbox.stateChanged.connect(_on_check)

        def _on_var_changed(*_args):
            if checkbox.isChecked() != variable.get():
                checkbox.setChecked(variable.get())

        variable.trace_add("write", _on_var_changed)

        layout.addWidget(checkbox)

    def _load_current_settings(self) -> None:
        self.remember_size_var.set(self.settings.is_remember_size_position_enabled())
        self.auto_center_var.set(self.settings.is_auto_center_enabled())
        self.adaptive_sizing_var.set(self.settings.is_adaptive_sizing_enabled())
        self.theme_mode_var.set(self._theme_mode_to_label(self.settings.get_theme_mode()))

    def _get_setting_changes(self) -> dict:
        return {
            "old": {
                "remember": self.settings.is_remember_size_position_enabled(),
                "auto_center": self.settings.is_auto_center_enabled(),
                "adaptive": self.settings.is_adaptive_sizing_enabled(),
                "theme": self.settings.get_theme_mode(),
            },
            "new": {
                "remember": self.remember_size_var.get(),
                "auto_center": self.auto_center_var.get(),
                "adaptive": self.adaptive_sizing_var.get(),
                "theme": self._theme_label_to_mode(self.theme_mode_var.get()),
            },
        }

    def _restore_window_geometry(self, win: QtWidgets.QWidget | None, defaults: dict[str, Any]) -> None:
        """重設主視窗大小與位置至螢幕中央"""
        if not win:
            return
        if win.isMaximized():
            win.showNormal()
        QtWidgets.QApplication.processEvents()
        screen = win.screen() if hasattr(win, "screen") and win.screen() else QtWidgets.QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QtCore.QRect(0, 0, defaults["width"], defaults["height"])
        target_w = min(defaults["width"], available.width())
        target_h = min(defaults["height"], available.height())
        win.resize(target_w, target_h)
        win.move(
            available.center().x() - target_w // 2,
            available.center().y() - target_h // 2,
        )
        win_layout = win.layout()
        if win_layout is not None:
            win_layout.activate()
        if hasattr(win, "navigationInterface") and win.navigationInterface:
            win.navigationInterface.update()
        if hasattr(win, "stackedWidget") and win.stackedWidget:
            win.stackedWidget.update()
        win.update()
        win.repaint()

    def _apply_theme_to_sub_frames(self, win: QtWidgets.QWidget | None) -> None:
        """通知主視窗下所有子頁面重新套用主題樣式"""
        if not win:
            return

        def _do_apply() -> None:
            for frame in (
                getattr(win, "create_server_frame", None),
                getattr(win, "manage_server_frame", None),
                getattr(win, "mod_frame", None),
                getattr(win, "mod_frame_controller", None),
                getattr(win, "about_prefs_frame", None),
                self,
            ):
                if frame:
                    apply_theme = getattr(frame, "apply_theme_styles", None)
                    if callable(apply_theme):
                        apply_theme()

        QtCore.QTimer.singleShot(0, _do_apply)

    def _reset_to_default_size(self) -> None:
        if UIUtils.ask_yes_no_cancel(
            "確認重設", "確定要將主視窗重設為預設大小嗎？\n這將立即套用變更", self.window(), show_cancel=False
        ):
            defaults = self.settings.get_default_main_window_settings()
            self.settings.set_main_window_settings(defaults["width"], defaults["height"], None, None, False)
            self._restore_window_geometry(self.window(), defaults)
            UIUtils.show_message("重設完成", "主視窗大小已重設為預設值", self.window(), message_level="info")

    def _reset_all_settings(self) -> None:
        if UIUtils.ask_yes_no_cancel(
            "確認恢復預設", "確定要恢復所有視窗設定為預設值嗎？", self.window(), show_cancel=False
        ):
            self.settings.set_remember_size_position(True)
            self.settings.set_auto_center(True)
            self.settings.set_adaptive_sizing(True)
            self.settings.set_theme_mode("system")

            defaults = self.settings.get_default_main_window_settings()
            self.settings.set_main_window_settings(defaults["width"], defaults["height"], None, None, False)
            self._load_current_settings()

            setTheme(Theme.AUTO)
            win = self.window()
            self._restore_window_geometry(win, defaults)
            self._apply_theme_to_sub_frames(win)

            UIUtils.show_message("恢復完成", "所有視窗設定已恢復為預設值", self.window(), message_level="info")

    def _apply_settings(self) -> None:
        try:
            changes = self._get_setting_changes()
            new_settings = changes["new"]
            self.settings.set_remember_size_position(new_settings["remember"])
            self.settings.set_auto_center(new_settings["auto_center"])
            self.settings.set_adaptive_sizing(new_settings["adaptive"])
            self.settings.set_theme_mode(new_settings["theme"])
            theme_changed = changes["old"]["theme"] != new_settings["theme"]
            if theme_changed:
                theme = new_settings["theme"]
                if theme == "system":
                    setTheme(Theme.AUTO)
                elif theme == "dark":
                    setTheme(Theme.DARK)
                else:
                    setTheme(Theme.LIGHT)
                self._apply_theme_to_sub_frames(self.window())
            UIUtils.show_message("設定套用成功", "視窗偏好設定已成功儲存並套用！", self.window(), message_level="info")
        except Exception as e:
            logger.error(f"套用設定失敗: {e}\n{traceback.format_exc()}")
            UIUtils.show_message("儲存失敗", f"無法儲存設定: {e}", self.window(), message_level="error")


__all__ = ["AboutPreferencesFrame"]
