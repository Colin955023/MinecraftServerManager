"""
關於與偏好設定頁面
整合程式資訊與視窗設定於單一介面。
"""

from __future__ import annotations

from typing import Any, ClassVar

from PySide6 import QtWidgets

from ..utils import (
    APP_VERSION,
    GITHUB_OWNER,
    GITHUB_REPO,
    Colors,
    CustomDropdown,
    FontManager,
    FontSize,
    RuntimePaths,
    Sizes,
    Spacing,
    UIUtils,
    UpdateChecker,
    WindowManager,
    get_logger,
    get_settings_manager,
    initialize_ui_theme,
)
from ..utils.ui_support import qt_widgets as qt

logger = get_logger().bind(component="AboutPreferencesFrame")


class AboutPreferencesFrame(qt.Frame):
    """關於與偏好設定整合頁面"""

    THEME_LABELS: ClassVar[dict[str, str]] = {"system": "依照系統設定", "light": "淺色", "dark": "深色"}
    THEME_MODES: ClassVar[dict[str, str]] = {label: mode for mode, label in THEME_LABELS.items()}

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("AboutPreferencesFrame")
        self.settings = get_settings_manager()
        self.create_widgets()
        self._load_current_settings()

    def _theme_mode_to_label(self, mode: str) -> str:
        return self.THEME_LABELS.get(str(mode or "system").lower(), self.THEME_LABELS["system"])

    def _theme_label_to_mode(self, label: str) -> str:
        return self.THEME_MODES.get(str(label or "").strip(), "system")

    def create_widgets(self) -> None:
        """建立左右分欄介面元件"""
        main_frame = qt.Frame(self, fg_color="transparent")
        main_frame.attach(fill="both", expand=True, padx=Spacing.LARGE, pady=Spacing.LARGE)

        split_frame = qt.Frame(main_frame, fg_color="transparent")
        split_frame.attach(fill="both", expand=True)

        # --- 關於程式 ---
        left_frame = qt.Frame(split_frame, fg_color=Colors.BG_SECONDARY)
        left_frame.attach(side="left", fill="both", expand=True, padx=(0, Spacing.MEDIUM))

        about_scroll = qt.ScrollableFrame(left_frame, fg_color="transparent")
        about_scroll.attach(fill="both", expand=True)
        about_content_container = about_scroll._content_widget

        about_title = qt.Label(
            about_content_container,
            text="🎮 Minecraft 伺服器管理器",
            font=FontManager.get_font(size=FontSize.HEADING_XLARGE, weight="bold"),
            justify="center",
        )
        about_title.attach(pady=(Spacing.XL, 0), padx=Spacing.LARGE)

        version_lbl = qt.Label(
            about_content_container,
            text=f"版本 {APP_VERSION}",
            font=FontManager.get_font(size=FontSize.LARGE),
            fg_color=Colors.BG_SECONDARY,
            text_color=Colors.TEXT_TERTIARY,
            justify="center",
        )
        version_lbl.attach(pady=(0, Spacing.LARGE), padx=Spacing.LARGE)

        # 開發資訊
        dev_title = qt.Label(
            about_content_container,
            text="👨‍💻 開發資訊",
            font=FontManager.get_font(size=FontSize.HEADING_MEDIUM, weight="bold"),
        )
        dev_title.attach(pady=(Spacing.MEDIUM, Spacing.SMALL), padx=Spacing.LARGE)

        dev_info = qt.Label(
            about_content_container,
            text=(
                "• 開發者: Minecraft Server Manager Team\n"
                "• 技術棧: Python 3.14+, Qt, PySide6\n"
                "• Java 管理: 自動偵測/下載 Minecraft 官方 JDK\n"
                "• 架構: 模組化設計, 事件驅動\n"
                "• 參考專案: PrismLauncher"
            ),
            font=FontManager.get_font(size=FontSize.NORMAL),
            justify="left",
        )
        dev_info.attach(padx=Spacing.LARGE, pady=(0, Spacing.MEDIUM))

        # GitHub 連結
        github_url = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
        github_lbl = qt.HyperlinkLabel(
            about_content_container,
            text="GitHub - MinecraftServerManager",
            url=github_url,
            font=FontManager.get_font(size=FontSize.MEDIUM),
            text_color=Colors.TEXT_LINK,
            cursor="pointing_hand",
        )
        github_lbl.attach(padx=Spacing.LARGE, pady=(0, Spacing.LARGE))
        github_lbl.clicked.connect(lambda: UIUtils.open_url(github_url))

        # 授權條款
        license_title = qt.Label(
            about_content_container,
            text="📄 授權條款",
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
        )
        license_title.attach(pady=(Spacing.MEDIUM, Spacing.SMALL), padx=Spacing.LARGE)

        license_info = qt.Label(
            about_content_container,
            text=(
                "• 本專案採用 GNU General Public License v3.0 授權條款\n"
                "• 部分設計理念參考 PrismLauncher\n"
                "• 僅供學習和個人使用\n"
                "• 請遵守 Minecraft EULA 和當地法律法規\n\n"
                "特別感謝 PrismLauncher 開發團隊的開源貢獻！"
            ),
            font=FontManager.get_font(size=FontSize.NORMAL),
            justify="left",
        )
        license_info.attach(padx=Spacing.LARGE, pady=(0, Spacing.MEDIUM))

        # 更新設定
        update_title = qt.Label(
            about_content_container,
            text="🔄 更新設定",
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
        )
        update_title.attach(pady=(Spacing.MEDIUM, Spacing.SMALL), padx=Spacing.LARGE)

        self.auto_update_var = qt.BoolState(self.settings.is_auto_update_enabled())
        self.auto_update_cb = qt.CheckBox(
            about_content_container,
            text="自動檢查更新",
            variable=self.auto_update_var,
            command=self._on_auto_update_toggled,
            font=FontManager.get_font(size=FontSize.NORMAL),
        )
        self.auto_update_cb.attach(anchor="w", padx=Spacing.LARGE * 2, pady=(0, Spacing.SMALL))

        self.manual_check_btn = qt.Button(
            about_content_container,
            text="檢查更新",
            command=self._manual_check_updates,
            font=FontManager.get_font(size=FontSize.NORMAL),
            width=Sizes.BUTTON_WIDTH_SECONDARY,
            height=Sizes.BUTTON_HEIGHT_SMALL,
        )
        self.manual_check_btn.attach(anchor="w", padx=Spacing.LARGE * 2, pady=(0, Spacing.MEDIUM))
        self.manual_check_btn.setVisible(not self.settings.is_auto_update_enabled())

        # 便攜模式提示
        if RuntimePaths.is_portable_mode():
            portable_title = qt.Label(
                about_content_container,
                text="📦 便攜模式",
                font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
            )
            portable_title.attach(pady=(Spacing.MEDIUM, Spacing.SMALL), padx=Spacing.LARGE)

            portable_info = qt.Label(
                about_content_container,
                text=(
                    "您正在使用便攜模式。\n"
                    "如需更新，請使用內建的檢查更新功能，或從 Releases 下載安裝程式 exe 後選擇可攜式安裝。"
                ),
                font=FontManager.get_font(size=FontSize.NORMAL),
                justify="left",
            )
            portable_info.attach(padx=Spacing.LARGE, pady=(0, Spacing.MEDIUM))

        # --- 視窗偏好設定 ---
        right_frame = qt.Frame(split_frame, fg_color=Colors.BG_PRIMARY)
        right_frame.attach(side="left", fill="both", expand=True, padx=(Spacing.MEDIUM, 0))

        # 標題
        pref_title = qt.Label(
            right_frame,
            text="⚙️ 視窗偏好設定",
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
        )
        pref_title.attach(pady=(Spacing.XL, Spacing.LARGE), padx=Spacing.LARGE)

        # 設定內容容器
        self.pref_container = qt.ScrollableFrame(right_frame)
        self.pref_container.attach(fill="both", expand=True, padx=Spacing.LARGE, pady=(0, Spacing.LARGE))
        content = self.pref_container._content_widget

        # 1. 一般設定
        self._create_section(content, "一般設定", "📋")
        self.remember_size_var = qt.BoolState(self.settings.is_remember_size_position_enabled())
        self._create_checkbox(content, "記住主視窗大小和位置", self.remember_size_var)

        self.auto_center_var = qt.BoolState(self.settings.is_auto_center_enabled())
        self._create_checkbox(content, "自動置中新的對話框視窗", self.auto_center_var)

        self.adaptive_sizing_var = qt.BoolState(self.settings.is_adaptive_sizing_enabled())
        self._create_checkbox(content, "啟用自適應視窗大小調整", self.adaptive_sizing_var)

        # 2. 主視窗設定
        self._create_section(content, "主視窗設定", "🏠")
        self.window_info_label = qt.Label(content, font=FontManager.get_font(size=FontSize.NORMAL))
        self.window_info_label.attach(anchor="w", padx=Spacing.MEDIUM, pady=(0, Spacing.SMALL))
        self._update_window_info()

        self.reset_size_btn = qt.Button(
            content,
            text="重設為預設大小",
            command=self._reset_to_default_size,
            font=FontManager.get_font(size=FontSize.NORMAL),
            width=Sizes.BUTTON_WIDTH_SECONDARY,
            height=Sizes.BUTTON_HEIGHT_SMALL,
        )
        self.reset_size_btn.attach(anchor="w", padx=Spacing.MEDIUM, pady=(0, Spacing.MEDIUM))

        # 3. 顯示設定
        self._create_section(content, "顯示設定", "🎨")
        theme_frame = qt.Frame(content, fg_color="transparent")
        theme_frame.attach(fill="x", padx=Spacing.MEDIUM, pady=(0, Spacing.SMALL))

        qt.Label(theme_frame, text="主題模式:", font=FontManager.get_font(size=FontSize.NORMAL)).attach(side="left")
        self.theme_mode_var = qt.TextState(self._theme_mode_to_label(self.settings.get_theme_mode()))
        self.theme_mode_dropdown = CustomDropdown(
            theme_frame,
            variable=self.theme_mode_var,
            values=list(self.THEME_MODES.keys()),
            width=Sizes.DROPDOWN_COMPACT_WIDTH,
            font_size=FontSize.NORMAL,
            state="readonly",
        )
        self.theme_mode_dropdown.attach(side="left", fill="x", expand=True, padx=(Spacing.SMALL_PLUS, 0))
        self.theme_mode_dropdown.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, self.theme_mode_dropdown.sizePolicy().verticalPolicy()
        )

        # --- 底部按鈕 ---
        btn_frame = qt.Frame(content, fg_color="transparent")
        btn_frame.attach(fill="x", pady=(Spacing.MEDIUM, 0))

        self.apply_btn = qt.Button(
            btn_frame,
            text="套用設定",
            command=self._apply_settings,
            font=FontManager.get_font(size=FontSize.NORMAL, weight="bold"),
            width=Sizes.BUTTON_WIDTH_SECONDARY,
            height=Sizes.BUTTON_HEIGHT_SMALL,
            fg_color=Colors.BUTTON_PRIMARY,
            hover_color=Colors.BUTTON_PRIMARY_HOVER,
            text_color=Colors.TEXT_ON_DARK,
        )
        self.apply_btn.attach(side="right", padx=(0, Spacing.SMALL_PLUS))

        self.reset_all_btn = qt.Button(
            btn_frame,
            text="恢復預設",
            command=self._reset_all_settings,
            font=FontManager.get_font(size=FontSize.NORMAL),
            width=Sizes.BUTTON_WIDTH_SECONDARY,
            height=Sizes.BUTTON_HEIGHT_SMALL,
            fg_color=Colors.BUTTON_DANGER,
            hover_color=Colors.BUTTON_DANGER_HOVER,
            text_color=Colors.TEXT_ON_DARK,
        )
        self.reset_all_btn.attach(side="right")

    def _create_section(self, parent, title: str, emoji: str) -> None:
        """建立設定分區標題"""
        sep = qt.Frame(parent, height=1, fg_color=Colors.TEXT_MUTED)
        sep.attach(fill="x", pady=(Spacing.MEDIUM, Spacing.SMALL))

        lbl = qt.Label(parent, text=f"{emoji} {title}", font=FontManager.get_font(size=FontSize.MEDIUM, weight="bold"))
        lbl.attach(anchor="w", padx=Spacing.MEDIUM, pady=(Spacing.SMALL, Spacing.SMALL))

    def _create_checkbox(self, parent, text: str, variable: Any) -> None:
        cb = qt.CheckBox(parent, text=text, variable=variable, font=FontManager.get_font(size=FontSize.NORMAL))
        cb.attach(anchor="w", padx=Spacing.MEDIUM * 2, pady=(0, Spacing.SMALL_PLUS))

    def _load_current_settings(self) -> None:
        self.remember_size_var.set(self.settings.is_remember_size_position_enabled())
        self.auto_center_var.set(self.settings.is_auto_center_enabled())
        self.adaptive_sizing_var.set(self.settings.is_adaptive_sizing_enabled())
        self.theme_mode_var.set(self._theme_mode_to_label(self.settings.get_theme_mode()))
        self._update_window_info()

    def _update_window_info(self) -> None:
        if not self.window():
            return
        screen_info = WindowManager.get_screen_info(self.window())
        self.settings.get_main_window_settings()
        self.settings.get_default_main_window_settings()

        width = int(self.window().width())
        height = int(self.window().height())

        info_text = (
            f"目前螢幕解析度: {screen_info['width']} × {screen_info['height']}\n目前主視窗大小: {width} × {height}"
        )
        self.window_info_label.setText(info_text)

    def _reset_to_default_size(self) -> None:
        if UIUtils.ask_yes_no_cancel(
            "確認重設", "確定要將主視窗重設為預設大小嗎？", parent=self.window(), show_cancel=False
        ):
            defaults = self.settings.get_default_main_window_settings()
            self.settings.set_main_window_settings(defaults["width"], defaults["height"], None, None, False)
            WindowManager.setup_main_window(self.window(), force_defaults=True)
            self._update_window_info()
            UIUtils.show_info("重設完成", "主視窗大小已重設為預設值", parent=self.window())

    def _reset_all_settings(self) -> None:
        if UIUtils.ask_yes_no_cancel(
            "確認恢復預設", "確定要恢復所有視窗設定為預設值嗎？", parent=self.window(), show_cancel=False
        ):
            self.settings.set_remember_size_position(True)
            self.settings.set_auto_center(True)
            self.settings.set_adaptive_sizing(True)
            self.settings.set_theme_mode("system")
            initialize_ui_theme("system")

            defaults = self.settings.get_default_main_window_settings()
            self.settings.set_main_window_settings(defaults["width"], defaults["height"], None, None, False)

            self._load_current_settings()
            UIUtils.show_info("恢復完成", "所有視窗設定已恢復為預設值。", parent=self.window())

    def _apply_settings(self) -> None:
        try:
            self.settings.set_remember_size_position(self.remember_size_var.get())
            self.settings.set_auto_center(self.auto_center_var.get())
            self.settings.set_adaptive_sizing(self.adaptive_sizing_var.get())

            new_theme = self._theme_label_to_mode(self.theme_mode_var.get())
            if new_theme != self.settings.get_theme_mode():
                self.settings.set_theme_mode(new_theme)
                initialize_ui_theme(new_theme)

            UIUtils.show_info("設定套用成功", "視窗偏好設定已成功儲存並套用！", parent=self.window())
        except Exception as e:
            logger.error(f"儲存失敗: {e}")
            UIUtils.show_error("儲存失敗", f"無法儲存設定: {e}", parent=self.window())

    def _on_auto_update_toggled(self) -> None:
        """處理自動更新勾選狀態變更"""
        enabled = self.auto_update_var.get()
        self.settings.set_auto_update_enabled(enabled)
        self.manual_check_btn.setVisible(not enabled)

    def _manual_check_updates(self) -> None:
        """手動檢查更新"""
        try:
            UpdateChecker.check_and_prompt_update(
                APP_VERSION,
                GITHUB_OWNER,
                GITHUB_REPO,
                show_up_to_date_message=True,
                parent=self.window(),
            )
        except Exception as e:
            logger.error(f"手動更新檢查失敗: {e}")
            UIUtils.show_error("更新檢查失敗", f"無法檢查更新：{e}", self.window())


__all__ = ["AboutPreferencesFrame"]
