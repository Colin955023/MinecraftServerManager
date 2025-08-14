#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
視窗偏好設定對話框
Window preferences dialog for configuring window behavior and appearance.
"""
# ====== 標準函式庫 ======
from typing import Callable, Optional
import customtkinter as ctk
# ====== 專案內部模組 ======
from ..utils.app_restart import can_restart, schedule_restart_and_exit
from ..utils.settings_manager import get_settings_manager
from ..utils.ui_utils import DialogUtils, UIUtils
from ..utils.window_manager import WindowManager
from ..utils.font_manager import set_ui_scale_factor, get_font

class WindowPreferencesDialog:
    """
    視窗偏好設定對話框
    Dialog for configuring window preferences including size, position, and behavior.
    """

    def __init__(self, parent, on_settings_changed: Optional[Callable] = None):
        self.parent = parent
        self.on_settings_changed = on_settings_changed
        self.settings = get_settings_manager()

        # 建立對話框
        self.dialog = DialogUtils.create_modal_dialog(
            parent, "視窗偏好設定", size=(500, 600), resizable=False, center=True
        )

        # 建立介面
        self._create_widgets()

        # 載入當前設定
        self._load_current_settings()

    def _create_widgets(self):
        """建立介面元件"""
        # 主滾動框架
        main_frame = ctk.CTkScrollableFrame(self.dialog)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 標題
        title_label = ctk.CTkLabel(main_frame, text="🖥️ 視窗偏好設定", font=get_font(size=18, weight="bold"))
        title_label.pack(pady=(0, 20))

        # 一般設定區域
        self._create_general_section(main_frame)

        # 主視窗設定區域
        self._create_main_window_section(main_frame)

        # 顯示設定區域
        self._create_display_section(main_frame)

        # 按鈕區域
        self._create_button_section(main_frame)

    def _create_section_frame(self, parent, title: str, emoji: str = "") -> ctk.CTkFrame:
        """
        建立設定區域框架 / Create settings section frame

        Args:
            parent: 父元件 / Parent widget
            title: 區域標題 / Section title
            emoji: 表情符號 / Emoji icon

        Returns:
            CTkFrame: 建立的區域框架 / Created section frame
        """
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=(0, 15))

        section_title = f"{emoji} {title}" if emoji else title
        ctk.CTkLabel(frame, text=section_title, font=get_font(size=14, weight="bold")).pack(
            anchor="w", padx=15, pady=(15, 10)
        )

        return frame

    def _create_checkbox(self, parent, text: str, variable: ctk.BooleanVar) -> ctk.CTkCheckBox:
        """
        建立複選框 / Create checkbox widget

        Args:
            parent: 父元件 / Parent widget
            text: 複選框文字 / Checkbox text
            variable: 綁定變數 / Bound variable

        Returns:
            CTkCheckBox: 建立的複選框 / Created checkbox
        """
        checkbox = ctk.CTkCheckBox(parent, text=text, variable=variable, font=get_font(size=12))
        checkbox.pack(anchor="w", padx=25, pady=(0, 10))
        return checkbox

    def _create_general_section(self, parent):
        """建立一般設定區域 / Create general settings section"""
        general_frame = self._create_section_frame(parent, "一般設定", "📋")

        # 建立所有複選框 / Create all checkboxes
        self.remember_size_var = ctk.BooleanVar()
        self._create_checkbox(general_frame, "記住主視窗大小和位置", self.remember_size_var)

        self.auto_center_var = ctk.BooleanVar()
        self._create_checkbox(general_frame, "自動置中新的對話框視窗", self.auto_center_var)

        self.adaptive_sizing_var = ctk.BooleanVar()
        self._create_checkbox(general_frame, "啟用自適應視窗大小調整", self.adaptive_sizing_var)

        # 根據環境決定是否顯示調試選項
        # 開發環境顯示調試選項，打包環境隱藏
        import sys
        should_show_debug = not hasattr(sys, '_MEIPASS')

        if should_show_debug:
            self.debug_logging_var = ctk.BooleanVar()
            checkbox = self._create_checkbox(general_frame, "啟用調試日誌輸出", self.debug_logging_var)
            checkbox.pack(anchor="w", padx=25, pady=(0, 15))  # 最後一個有額外間距
        else:
            # 如果是打包環境，隱藏調試選項並設為 False
            self.debug_logging_var = ctk.BooleanVar()
            self.debug_logging_var.set(False)

    def _create_main_window_section(self, parent):
        """建立主視窗設定區域 / Create main window settings section"""
        main_window_frame = self._create_section_frame(parent, "主視窗設定", "🏠")

        # 當前視窗資訊 / Current window information
        screen_info = WindowManager.get_screen_info(self.dialog)
        current_settings = self.settings.get_main_window_settings()

        info_text = (
            f"目前螢幕解析度: {screen_info['width']} × {screen_info['height']}\n"
            f"目前主視窗大小: {current_settings.get('width', 1200)} × {current_settings.get('height', 800)}"
        )

        ctk.CTkLabel(main_window_frame, text=info_text, font=get_font(size=12), justify="left").pack(
            anchor="w", padx=25, pady=(0, 15)
        )

        scale_factor = get_settings_manager().get_dpi_scaling()
        # 重設按鈕 / Reset button
        reset_button = ctk.CTkButton(
            main_window_frame,
            text="重設為預設大小",
            command=self._reset_to_default_size,
            font=get_font(size=12),
            width=int(150 * scale_factor),
            height=int(32 * scale_factor),
        )
        reset_button.pack(anchor="w", padx=25, pady=(0, 15))

    def _create_display_section(self, parent):
        """建立顯示設定區域 / Create display settings section"""
        display_frame = self._create_section_frame(parent, "顯示設定", "🎨")

        # DPI 縮放設定 / DPI scaling settings
        dpi_frame = ctk.CTkFrame(display_frame, fg_color="transparent")
        dpi_frame.pack(fill="x", padx=25, pady=(0, 15))

        ctk.CTkLabel(dpi_frame, text="DPI 縮放因子:", font=get_font(size=12)).pack(side="left")

        scale_factor = get_settings_manager().get_dpi_scaling()
        self.dpi_scale_var = ctk.DoubleVar()
        self.dpi_scale_slider = ctk.CTkSlider(
            dpi_frame,
            from_=0.5,
            to=3.0,
            number_of_steps=25,
            variable=self.dpi_scale_var,
            width=int(200 * scale_factor),
            command=self._on_dpi_scale_changed,
        )
        self.dpi_scale_slider.pack(side="left", padx=(10, 10))

        self.dpi_scale_label = ctk.CTkLabel(dpi_frame, text="1.0x", font=get_font(size=12), width=int(40 * scale_factor))
        self.dpi_scale_label.pack(side="left")

        # DPI 說明 / DPI description
        ctk.CTkLabel(
            display_frame,
            text="調整此設定以適應高解析度螢幕或改善視覺效果",
            font=get_font(size=12),
            text_color="gray",
        ).pack(anchor="w", padx=25, pady=(0, 15))

    def _create_button_section(self, parent):
        """建立按鈕區域 / Create button section"""
        button_frame = ctk.CTkFrame(parent, fg_color="transparent")
        button_frame.pack(fill="x", pady=(20, 0))

        # 按鈕配置 / Button configurations
        buttons = [
            ("恢復預設", self._reset_all_settings, "left", ("#dc2626", "#b91c1c"), ("#b91c1c", "#991b1b")),
            ("套用設定", self._apply_settings, "right", None, None),  # 使用預設顏色
            ("取消", self._cancel, "right", "gray", ("gray70", "gray30")),
        ]

        for text, command, side, fg_color, hover_color in buttons:
            btn_config = {"text": text, "command": command, "font": ctk.CTkFont(size=12), "width": 100, "height": 35}

            if text == "套用設定":
                btn_config["font"] = get_font(size=12, weight="bold")
            if fg_color:
                btn_config["fg_color"] = fg_color
            if hover_color:
                btn_config["hover_color"] = hover_color

            button = ctk.CTkButton(button_frame, **btn_config)
            padding = (10, 0) if side == "right" else (0, 0)
            button.pack(side=side, padx=padding)

    def _load_current_settings(self):
        """載入當前設定 / Load current settings"""
        self.remember_size_var.set(self.settings.is_remember_size_position_enabled())
        self.auto_center_var.set(self.settings.is_auto_center_enabled())
        self.adaptive_sizing_var.set(self.settings.is_adaptive_sizing_enabled())
        self.debug_logging_var.set(self.settings.is_debug_logging_enabled())

        # 載入 DPI 設定 / Load DPI settings
        current_dpi = self.settings.get_dpi_scaling()
        self.dpi_scale_var.set(current_dpi)
        self.dpi_scale_label.configure(text=f"{current_dpi:.1f}x")

    def _on_dpi_scale_changed(self, value):
        """DPI 縮放變更事件 / DPI scaling change event"""
        self.dpi_scale_label.configure(text=f"{value:.1f}x")

    def _get_setting_changes(self) -> dict:
        """
        取得設定變更 / Get setting changes

        Returns:
            dict: 包含舊值、新值和變更標記的字典 / Dictionary with old, new values and change flags
        """
        return {
            'old': {
                'remember': self.settings.is_remember_size_position_enabled(),
                'auto_center': self.settings.is_auto_center_enabled(),
                'adaptive': self.settings.is_adaptive_sizing_enabled(),
                'debug': self.settings.is_debug_logging_enabled(),
                'dpi': self.settings.get_dpi_scaling(),
            },
            'new': {
                'remember': self.remember_size_var.get(),
                'auto_center': self.auto_center_var.get(),
                'adaptive': self.adaptive_sizing_var.get(),
                'debug': self.debug_logging_var.get(),
                'dpi': self.dpi_scale_var.get(),
            },
        }

    def _has_important_changes(self, changes: dict) -> bool:
        """
        檢查是否有重要變更需要重啟 / Check if there are important changes requiring restart

        Args:
            changes: 設定變更字典 / Settings changes dictionary

        Returns:
            bool: 需要重啟返回 True / True if restart is needed
        """
        old, new = changes['old'], changes['new']

        dpi_changed = abs(old['dpi'] - new['dpi']) > 0.01
        return (
            old['remember'] != new['remember']
            or old['auto_center'] != new['auto_center']
            or old['adaptive'] != new['adaptive']
            or dpi_changed
        )

    def _reset_to_default_size(self):
        """重設主視窗為預設大小 / Reset main window to default size"""
        if UIUtils.ask_yes_no_cancel(
            "確認重設", "確定要將主視窗重設為預設大小嗎？\n這將立即應用變更。", parent=self.dialog, show_cancel=False
        ):
            self.settings.set_main_window_settings(1200, 800, None, None, False)

            # 立即應用到主視窗 / Apply immediately to main window
            if self.parent:
                WindowManager.setup_main_window(self.parent, force_defaults=True)

            UIUtils.show_info("重設完成", "主視窗大小已重設為預設值", parent=self.dialog)

    def _reset_all_settings(self):
        """恢復所有設定為預設值 / Reset all settings to defaults"""
        if UIUtils.ask_yes_no_cancel(
            "確認恢復預設", "確定要恢復所有視窗設定為預設值嗎？", parent=self.dialog, show_cancel=False
        ):
            # 恢復預設設定 / Restore default settings
            self.settings.set_remember_size_position(True)
            self.settings.set_auto_center(True)
            self.settings.set_adaptive_sizing(True)
            self.settings.set_debug_logging(False)
            self.settings.set_dpi_scaling(1.0)
            self.settings.set_main_window_settings(1200, 800, None, None, False)

            # 重新載入設定到界面 / Reload settings to interface
            self._load_current_settings()

            UIUtils.show_info("恢復完成", "所有視窗設定已恢復為預設值", parent=self.dialog)

    def _apply_settings(self):
        """套用設定 / Apply settings"""
        try:
            changes = self._get_setting_changes()
            new_settings = changes['new']

            # 儲存新設定 / Save new settings
            self.settings.set_remember_size_position(new_settings['remember'])
            self.settings.set_auto_center(new_settings['auto_center'])
            self.settings.set_adaptive_sizing(new_settings['adaptive'])
            self.settings.set_debug_logging(new_settings['debug'])
            self.settings.set_dpi_scaling(new_settings['dpi'])

            # 檢查 DPI 變更並立即套用 / Check DPI changes and apply immediately
            dpi_changed = abs(changes['old']['dpi'] - new_settings['dpi']) > 0.01
            if dpi_changed:
                set_ui_scale_factor(new_settings['dpi'])

            # 執行回調函數 / Execute callback
            if self.on_settings_changed:
                self.on_settings_changed()

            # 顯示成功訊息 / Show success message
            important_changes = self._has_important_changes(changes)
            success_msg = "視窗偏好設定已成功儲存並套用！"
            if important_changes:
                success_msg += "\n\n設定已生效，部分變更可能需要重新啟動程式才能完全套用。"

            UIUtils.show_info("設定套用成功", success_msg, parent=self.dialog)

            # 處理重啟邏輯 / Handle restart logic
            if important_changes and can_restart():
                if UIUtils.ask_yes_no_cancel(
                    "重新啟動程式",
                    "設定已成功套用！\n\n為了確保所有變更完全生效，建議重新啟動程式。\n\n是否要立即重新啟動？",
                    parent=self.dialog,
                    show_cancel=False,
                ):
                    try:
                        self.dialog.destroy()
                        schedule_restart_and_exit(self.parent, delay=0.5)
                        return

                    except Exception as restart_error:
                        UIUtils.show_error(
                            "重啟失敗",
                            f"無法重新啟動應用程式: {restart_error}\n\n設定已儲存，請手動重新啟動程式以套用所有變更。",
                            parent=self.dialog,
                        )
            elif important_changes and not can_restart():
                # 無法重啟時提供說明 / Provide explanation when restart is not possible
                UIUtils.show_info(
                    "需要手動重啟",
                    "設定已成功儲存！\n\n由於環境限制，無法自動重新啟動程式。\n請手動關閉並重新啟動應用程式以套用所有變更。",
                    parent=self.dialog,
                )

            # 正常關閉對話框 / Normal dialog closure
            self.dialog.destroy()

        except Exception as e:
            UIUtils.show_error("儲存失敗", f"無法儲存設定: {e}", parent=self.dialog)

    def _cancel(self):
        """取消設定 / Cancel settings"""
        self.dialog.destroy()
