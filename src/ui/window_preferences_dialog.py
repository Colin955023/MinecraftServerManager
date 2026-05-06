"""視窗偏好設定對話框
Window preferences dialog for configuring window behavior and appearance.
"""

import traceback
from collections.abc import Callable
from typing import ClassVar

from ..utils import (
    Colors,
    FontSize,
    Sizes,
    Spacing,
    UIUtils,
    WindowManager,
    get_button_style,
    get_logger,
    get_settings_manager,
)
from ..utils.ui_support import qt_widgets as qt
from . import CustomDropdown, DialogUtils, FontManager, ui_config
from .ui_config import NativeQtStyle

logger = get_logger().bind(component="WindowPreferencesDialog")


class WindowPreferencesDialog:
    """視窗偏好設定對話框"""

    THEME_LABELS: ClassVar[dict[str, str]] = {"system": "依照系統設定", "light": "淺色", "dark": "深色"}
    THEME_MODES: ClassVar[dict[str, str]] = {label: mode for mode, label in THEME_LABELS.items()}

    def _get_live_main_window_size(self) -> tuple[int, int] | None:
        """優先取得目前主視窗真實尺寸；若視窗尚未完成佈局則回傳 None。"""
        if not self.parent:
            return None
        try:
            app = qt.ensure_app()
            if app is not None:
                app.processEvents()
            width = int(self.parent.width())
            height = int(self.parent.height())
            if WindowManager.is_valid_main_window_size(width, height):
                return (width, height)
        except Exception as e:
            logger.debug(f"讀取目前主視窗大小失敗，將回退到已儲存設定: {e}")
        return None

    def __init__(self, parent, on_settings_changed: Callable | None = None):
        self.parent = parent
        self.on_settings_changed = on_settings_changed
        self.settings = get_settings_manager()
        self.dialog = DialogUtils.create_toplevel_dialog(
            parent,
            "視窗偏好設定",
            width=Sizes.DIALOG_PREFERENCES_WIDTH,
            height=Sizes.DIALOG_PREFERENCES_HEIGHT,
            resizable=False,
            center_on_parent=True,
            make_modal=True,
            bind_icon=True,
            delay_ms=250,
        )
        self.dialog.setStyleSheet(NativeQtStyle.preferences_dialog)
        self._create_widgets()
        self._load_current_settings()

    def _theme_mode_to_label(self, mode: str) -> str:
        return self.THEME_LABELS.get(str(mode or "system").lower(), self.THEME_LABELS["system"])

    def _theme_label_to_mode(self, label: str) -> str:
        return self.THEME_MODES.get(str(label or "").strip(), "system")

    def _create_widgets(self) -> None:
        """建立介面元件"""
        main_frame = qt.ScrollableFrame(self.dialog)
        main_frame.attach(fill="both", expand=True, padx=Spacing.XL, pady=Spacing.XL)
        title_label = qt.Label(
            main_frame, text="🖥️ 視窗偏好設定", font=FontManager.get_font(size=FontSize.LARGE, weight="bold")
        )
        title_label.attach(pady=(0, Spacing.XL))
        self._create_general_section(main_frame)
        self._create_main_window_section(main_frame)
        self._create_display_section(main_frame)
        self._create_button_section(main_frame)

    def _create_section_frame(self, parent, title: str, emoji: str = "") -> qt.Frame:
        """建立設定區域框架"""
        frame = qt.Frame(parent)
        frame.attach(fill="x", pady=(0, Spacing.LARGE_MINUS))
        section_title = f"{emoji} {title}" if emoji else title
        qt.Label(frame, text=section_title, font=FontManager.get_font(size=FontSize.MEDIUM, weight="bold")).attach(
            anchor="w", padx=Spacing.LARGE_MINUS, pady=(Spacing.LARGE_MINUS, Spacing.SMALL_PLUS)
        )
        return frame

    def _create_checkbox(self, parent, text: str, variable: qt.BoolState) -> qt.CheckBox:
        """建立複選框"""
        checkbox = qt.CheckBox(parent, text=text, variable=variable, font=FontManager.get_font(size=FontSize.NORMAL))
        checkbox.attach(anchor="w", padx=20, pady=(0, Spacing.SMALL_PLUS))
        return checkbox

    def _create_general_section(self, parent) -> None:
        """建立一般設定區域"""
        general_frame = self._create_section_frame(parent, "一般設定", "📋")
        self.remember_size_var = qt.BoolState(self.settings.is_remember_size_position_enabled())
        self._create_checkbox(general_frame, "記住主視窗大小和位置", self.remember_size_var)
        self.auto_center_var = qt.BoolState(self.settings.is_auto_center_enabled())
        self._create_checkbox(general_frame, "自動置中新的對話框視窗", self.auto_center_var)
        self.adaptive_sizing_var = qt.BoolState(self.settings.is_adaptive_sizing_enabled())
        self._create_checkbox(general_frame, "啟用自適應視窗大小調整", self.adaptive_sizing_var)

    def _create_main_window_section(self, parent) -> None:
        """建立主視窗設定區域"""
        main_window_frame = self._create_section_frame(parent, "主視窗設定", "🏠")
        screen_info = WindowManager.get_screen_info(self.dialog)
        current_settings = self.settings.get_main_window_settings()
        default_settings = self.settings.get_default_main_window_settings()
        live_size = self._get_live_main_window_size()
        current_width, current_height = live_size or (
            current_settings.get("width", default_settings["width"]),
            current_settings.get("height", default_settings["height"]),
        )
        info_text = f"目前螢幕解析度: {screen_info['width']} × {screen_info['height']}\n目前主視窗大小: {current_width} × {current_height}"
        qt.Label(
            main_window_frame, text=info_text, font=FontManager.get_font(size=FontSize.NORMAL), justify="left"
        ).attach(anchor="w", padx=20, pady=(0, Spacing.LARGE_MINUS))
        reset_button = qt.Button(
            main_window_frame,
            text="重設為預設大小",
            command=self._reset_to_default_size,
            font=FontManager.get_font(size=FontSize.NORMAL),
            width=Sizes.BUTTON_WIDTH_SMALL,
            height=Sizes.PREFERENCES_RESET_BUTTON_HEIGHT,
        )
        reset_button.attach(anchor="w", padx=20, pady=(0, Spacing.LARGE_MINUS))

    def _create_display_section(self, parent) -> None:
        """建立顯示設定區域"""
        display_frame = self._create_section_frame(parent, "顯示設定", "🎨")
        theme_frame = qt.Frame(display_frame, fg_color="transparent")
        theme_frame.attach(fill="x", padx=20, pady=(0, Spacing.LARGE_MINUS))
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
        self.theme_mode_dropdown.attach(side="left", padx=(Spacing.SMALL_PLUS, 0))
        qt.Label(
            display_frame,
            text="介面縮放會跟隨 Windows 顯示比例與 Qt 高 DPI 設定",
            font=FontManager.get_font(size=FontSize.NORMAL),
            text_color=Colors.TEXT_SECONDARY,
        ).attach(anchor="w", padx=20, pady=(0, Spacing.LARGE_MINUS))

    def _create_button_section(self, parent) -> None:
        """建立按鈕區域"""
        button_frame = qt.Frame(parent, fg_color=Colors.BG_SECONDARY)
        button_frame.attach(fill="x", pady=(Spacing.XL, 0), padx=(-Spacing.XL, -Spacing.XL))
        left_button_frame = qt.Frame(button_frame, fg_color="transparent")
        left_button_frame.attach(side="left", padx=(Spacing.XL, 0), pady=Spacing.LARGE_MINUS)
        right_button_frame = qt.Frame(button_frame, fg_color="transparent")
        right_button_frame.attach(side="right", padx=(0, Spacing.XL), pady=Spacing.LARGE_MINUS)

        reset_button = qt.Button(
            left_button_frame,
            text="恢復預設",
            command=self._reset_all_settings,
            font=FontManager.get_font(size=FontSize.NORMAL, weight="normal"),
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT_SMALL,
            **get_button_style("danger"),
        )
        reset_button.attach(side="left", padx=0)

        apply_button = qt.Button(
            right_button_frame,
            text="套用設定",
            command=self._apply_settings,
            font=FontManager.get_font(size=FontSize.NORMAL, weight="bold"),
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT_SMALL,
            **get_button_style("primary"),
        )
        apply_button.attach(side="right", padx=(0, Spacing.SMALL_PLUS))

        cancel_button = qt.Button(
            right_button_frame,
            text="取消",
            command=self._cancel,
            font=FontManager.get_font(size=FontSize.NORMAL, weight="normal"),
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT_SMALL,
            **get_button_style("secondary"),
        )
        cancel_button.attach(side="right", padx=0)

    def _load_current_settings(self) -> None:
        """載入當前設定"""
        self.remember_size_var.set(self.settings.is_remember_size_position_enabled())
        self.auto_center_var.set(self.settings.is_auto_center_enabled())
        self.adaptive_sizing_var.set(self.settings.is_adaptive_sizing_enabled())
        self.theme_mode_var.set(self._theme_mode_to_label(self.settings.get_theme_mode()))

    def _get_setting_changes(self) -> dict:
        """取得設定變更"""
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

    def _reset_to_default_size(self) -> None:
        """重設主視窗為預設大小"""
        if UIUtils.ask_yes_no_cancel(
            "確認重設", "確定要將主視窗重設為預設大小嗎？\n這將立即應用變更。", parent=self.dialog, show_cancel=False
        ):
            defaults = self.settings.get_default_main_window_settings()
            self.settings.set_main_window_settings(defaults["width"], defaults["height"], None, None, False)
            if self.parent:
                WindowManager.setup_main_window(self.parent, force_defaults=True)
            UIUtils.show_info("重設完成", "主視窗大小已重設為預設值", parent=self.dialog)

    def _reset_all_settings(self) -> None:
        """恢復所有視窗偏好為預設值。"""
        if UIUtils.ask_yes_no_cancel(
            "確認恢復預設", "確定要恢復所有視窗設定為預設值嗎？", parent=self.dialog, show_cancel=False
        ):
            self.settings.set_remember_size_position(True)
            self.settings.set_auto_center(True)
            self.settings.set_adaptive_sizing(True)
            self.settings.set_theme_mode("system")
            ui_config.initialize_ui_theme("system")
            self.dialog.setStyleSheet(NativeQtStyle.preferences_dialog)
            self.theme_mode_dropdown.setStyleSheet(NativeQtStyle.custom_dropdown)
            defaults = self.settings.get_default_main_window_settings()
            self.settings.set_main_window_settings(defaults["width"], defaults["height"], None, None, False)
            self._load_current_settings()
            UIUtils.show_info("恢復完成", "所有視窗設定已恢復為預設值。", parent=self.dialog)

    def _apply_settings(self) -> None:
        """套用設定"""
        try:
            changes = self._get_setting_changes()
            new_settings = changes["new"]
            self.settings.set_remember_size_position(new_settings["remember"])
            self.settings.set_auto_center(new_settings["auto_center"])
            self.settings.set_adaptive_sizing(new_settings["adaptive"])
            self.settings.set_theme_mode(new_settings["theme"])
            theme_changed = changes["old"]["theme"] != new_settings["theme"]
            if theme_changed:
                ui_config.initialize_ui_theme(new_settings["theme"])
                self.dialog.setStyleSheet(NativeQtStyle.preferences_dialog)
                self.theme_mode_dropdown.setStyleSheet(NativeQtStyle.custom_dropdown)
            if self.on_settings_changed:
                self.on_settings_changed()
            UIUtils.show_info("設定套用成功", "視窗偏好設定已成功儲存並套用！", parent=self.dialog)
            self.dialog.destroy()
        except Exception as e:
            logger.error(f"儲存失敗: {e}\n{traceback.format_exc()}")
            UIUtils.show_error("儲存失敗", f"無法儲存設定: {e}", parent=self.dialog)

    def _cancel(self) -> None:
        """取消設定"""
        self.dialog.destroy()
