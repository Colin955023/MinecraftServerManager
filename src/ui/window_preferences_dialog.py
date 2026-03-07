#!/usr/bin/env python3
"""視窗偏好設定對話框
Window preferences dialog for configuring window behavior and appearance.
"""

import sys
import traceback
from collections.abc import Callable

import customtkinter as ctk

from ..utils import (
    AppRestart,
    FontManager,
    FontSize,
    Sizes,
    UIUtils,
    WindowManager,
    get_button_style,
    get_logger,
    get_settings_manager,
)

logger = get_logger().bind(component="WindowPreferencesDialog")


class WindowPreferencesDialog:
    """視窗偏好設定對話框"""

    def __init__(self, parent, on_settings_changed: Callable | None = None):
        self.parent = parent
        self.on_settings_changed = on_settings_changed
        self.settings = get_settings_manager()

        # 建立對話框
        self.dialog = UIUtils.create_toplevel_dialog(
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

        # 建立介面
        self._create_widgets()

        # 載入當前設定
        self._load_current_settings()

    def _create_widgets(self) -> None:
        """建立介面元件"""
        # 主滾動框架
        main_frame = ctk.CTkScrollableFrame(self.dialog)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 標題
        title_label = ctk.CTkLabel(
            main_frame,
            text="🖥️ 視窗偏好設定",
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
        )
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
        """建立設定區域框架"""
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=(0, 15))

        section_title = f"{emoji} {title}" if emoji else title
        ctk.CTkLabel(frame, text=section_title, font=FontManager.get_font(size=FontSize.MEDIUM, weight="bold")).pack(
            anchor="w",
            padx=15,
            pady=(15, 10),
        )

        return frame

    def _create_checkbox(self, parent, text: str, variable: ctk.BooleanVar) -> ctk.CTkCheckBox:
        """建立複選框"""
        checkbox = ctk.CTkCheckBox(
            parent, text=text, variable=variable, font=FontManager.get_font(size=FontSize.NORMAL)
        )
        checkbox.pack(anchor="w", padx=25, pady=(0, 10))
        return checkbox

    def _create_general_section(self, parent) -> None:
        """建立一般設定區域"""
        general_frame = self._create_section_frame(parent, "一般設定", "📋")

        # 建立所有複選框
        self.remember_size_var = ctk.BooleanVar()
        self._create_checkbox(general_frame, "記住主視窗大小和位置", self.remember_size_var)

        self.auto_center_var = ctk.BooleanVar()
        self._create_checkbox(general_frame, "自動置中新的對話框視窗", self.auto_center_var)

        self.adaptive_sizing_var = ctk.BooleanVar()
        self._create_checkbox(general_frame, "啟用自適應視窗大小調整", self.adaptive_sizing_var)

        # 根據環境決定是否顯示除錯選項
        # 開發環境顯示除錯選項，打包環境隱藏
        # 支援 PyInstaller (frozen/MEIPASS) 和 Nuitka (__compiled__)
        is_nuitka = "__compiled__" in globals()
        is_packaged = bool(getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS") or is_nuitka)
        should_show_debug = not is_packaged

        if should_show_debug:
            self.debug_logging_var = ctk.BooleanVar()
            checkbox = self._create_checkbox(general_frame, "啟用除錯日誌輸出", self.debug_logging_var)
            checkbox.pack(anchor="w", padx=25, pady=(0, 15))  # 最後一個有額外間距
        else:
            # 如果是打包環境，隱藏除錯選項並設為 False
            self.debug_logging_var = ctk.BooleanVar()
            self.debug_logging_var.set(False)

    def _create_main_window_section(self, parent) -> None:
        """建立主視窗設定區域"""
        main_window_frame = self._create_section_frame(parent, "主視窗設定", "🏠")

        # 當前視窗資訊
        screen_info = WindowManager.get_screen_info(self.dialog)
        current_settings = self.settings.get_main_window_settings()

        info_text = (
            f"目前螢幕解析度: {screen_info['width']} × {screen_info['height']}\n"
            f"目前主視窗大小: {current_settings.get('width', 1200)} × {current_settings.get('height', 800)}"
        )

        ctk.CTkLabel(
            main_window_frame,
            text=info_text,
            font=FontManager.get_font(size=FontSize.NORMAL),
            justify="left",
        ).pack(
            anchor="w",
            padx=25,
            pady=(0, 15),
        )

        scale_factor = get_settings_manager().get_dpi_scaling()
        # 重設按鈕
        reset_button = ctk.CTkButton(
            main_window_frame,
            text="重設為預設大小",
            command=self._reset_to_default_size,
            font=FontManager.get_font(size=FontSize.NORMAL),
            width=int(150 * scale_factor),
            height=int(32 * scale_factor),
        )
        reset_button.pack(anchor="w", padx=25, pady=(0, 15))

    def _create_display_section(self, parent) -> None:
        """建立顯示設定區域"""
        display_frame = self._create_section_frame(parent, "顯示設定", "🎨")

        # DPI 縮放設定
        dpi_frame = ctk.CTkFrame(display_frame, fg_color="transparent")
        dpi_frame.pack(fill="x", padx=25, pady=(0, 15))

        ctk.CTkLabel(dpi_frame, text="DPI 縮放因子:", font=FontManager.get_font(size=FontSize.NORMAL)).pack(side="left")

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

        self.dpi_scale_label = ctk.CTkLabel(
            dpi_frame,
            text="1.0x",
            font=FontManager.get_font(size=FontSize.NORMAL),
            width=int(40 * scale_factor),
        )
        self.dpi_scale_label.pack(side="left")

        # DPI 說明
        ctk.CTkLabel(
            display_frame,
            text="調整此設定以適應高解析度螢幕或改善視覺效果",
            font=FontManager.get_font(size=FontSize.NORMAL),
            text_color="gray",
        ).pack(anchor="w", padx=25, pady=(0, 15))

    def _create_button_section(self, parent) -> None:
        """建立按鈕區域"""
        button_frame = ctk.CTkFrame(parent, fg_color="transparent")
        button_frame.pack(fill="x", pady=(20, 0))

        # 按鈕配置
        buttons = [
            (
                "恢復預設",
                self._reset_all_settings,
                "left",
                get_button_style("danger"),
            ),
            ("套用設定", self._apply_settings, "right", get_button_style("primary")),
            ("取消", self._cancel, "right", {"fg_color": "gray", "hover_color": ("gray70", "gray30")}),
        ]

        for text, command, side, style in buttons:
            btn_config = {
                "text": text,
                "command": command,
                "font": FontManager.get_font(size=FontSize.NORMAL, weight="bold" if text == "套用設定" else "normal"),
                "width": 100,
                "height": 35,
                **style,
            }

            button = ctk.CTkButton(button_frame, **btn_config)
            padding = (10, 0) if side == "right" else (0, 0)
            button.pack(side=side, padx=padding)

    def _load_current_settings(self) -> None:
        """載入當前設定"""
        self.remember_size_var.set(self.settings.is_remember_size_position_enabled())
        self.auto_center_var.set(self.settings.is_auto_center_enabled())
        self.adaptive_sizing_var.set(self.settings.is_adaptive_sizing_enabled())
        self.debug_logging_var.set(self.settings.is_debug_logging_enabled())

        # 載入 DPI 設定
        current_dpi = self.settings.get_dpi_scaling()
        self.dpi_scale_var.set(current_dpi)
        self.dpi_scale_label.configure(text=f"{current_dpi:.1f}x")

    def _on_dpi_scale_changed(self, value) -> None:
        """DPI 縮放變更事件"""
        self.dpi_scale_label.configure(text=f"{value:.1f}x")

    def _get_setting_changes(self) -> dict:
        """取得設定變更"""
        return {
            "old": {
                "remember": self.settings.is_remember_size_position_enabled(),
                "auto_center": self.settings.is_auto_center_enabled(),
                "adaptive": self.settings.is_adaptive_sizing_enabled(),
                "debug": self.settings.is_debug_logging_enabled(),
                "dpi": self.settings.get_dpi_scaling(),
            },
            "new": {
                "remember": self.remember_size_var.get(),
                "auto_center": self.auto_center_var.get(),
                "adaptive": self.adaptive_sizing_var.get(),
                "debug": self.debug_logging_var.get(),
                "dpi": self.dpi_scale_var.get(),
            },
        }

    def _has_important_changes(self, changes: dict) -> bool:
        """檢查是否有重要變更需要重啟"""
        old, new = changes["old"], changes["new"]

        dpi_changed = abs(old["dpi"] - new["dpi"]) > 0.01
        return (
            old["remember"] != new["remember"]
            or old["auto_center"] != new["auto_center"]
            or old["adaptive"] != new["adaptive"]
            or dpi_changed
        )

    def _reset_to_default_size(self) -> None:
        """重設主視窗為預設大小"""
        if UIUtils.ask_yes_no_cancel(
            "確認重設",
            "確定要將主視窗重設為預設大小嗎？\n這將立即應用變更。",
            parent=self.dialog,
            show_cancel=False,
        ):
            self.settings.set_main_window_settings(1200, 800, None, None, False)

            # 立即應用到主視窗
            if self.parent:
                WindowManager.setup_main_window(self.parent, force_defaults=True)

            UIUtils.show_info("重設完成", "主視窗大小已重設為預設值", parent=self.dialog)

    def _reset_all_settings(self) -> None:
        """恢復所有設定為預設值，並比對是否有重要變更需要重啟"""
        if UIUtils.ask_yes_no_cancel(
            "確認恢復預設",
            "確定要恢復所有視窗設定為預設值嗎？",
            parent=self.dialog,
            show_cancel=False,
        ):
            # 取得恢復前的設定
            changes_before = self._get_setting_changes()

            # 恢復預設設定
            self.settings.set_remember_size_position(True)
            self.settings.set_auto_center(True)
            self.settings.set_adaptive_sizing(True)
            self.settings.set_debug_logging(False)
            self.settings.set_dpi_scaling(1.0)
            self.settings.set_main_window_settings(1200, 800, None, None, False)

            # 重新載入設定到界面
            self._load_current_settings()

            # 取得恢復後的設定
            changes_after = self._get_setting_changes()
            # 用恢復前的 old 與現在的 new 比較
            compare_changes = {
                "old": changes_before["old"],
                "new": changes_after["new"],
            }
            important_changes = self._has_important_changes(compare_changes)

            msg = "所有視窗設定已恢復為預設值"
            if important_changes:
                msg += "\n\n部分設定（如 DPI、視窗記憶、自適應等）需要重新啟動程式才能完全套用。"
            UIUtils.show_info("恢復完成", msg, parent=self.dialog)

            # 若需要重啟，依 AppRestart.can_restart() 決定提示
            if important_changes:
                supported = AppRestart.can_restart()
                supported_diag = None
                if not supported:
                    # 取得詳細診斷以便提示使用者
                    try:
                        _, supported_diag = AppRestart.get_restart_diagnostics()
                    except Exception:
                        supported_diag = None

                if supported:
                    if UIUtils.ask_yes_no_cancel(
                        "重新啟動程式",
                        "設定已恢復為預設值！\n\n為了確保所有變更完全生效，建議重新啟動程式。\n\n是否要立即重新啟動？",
                        parent=self.dialog,
                        show_cancel=False,
                    ):
                        try:
                            self.dialog.destroy()
                            AppRestart.schedule_restart_and_exit(self.parent, delay=0.5)
                            return
                        except Exception as restart_error:
                            logger.error(f"重啟失敗: {restart_error}\n{traceback.format_exc()}")
                            UIUtils.show_error(
                                "重啟失敗",
                                f"無法重新啟動應用程式: {restart_error}\n\n設定已恢復，請手動重新啟動程式以套用所有變更。",
                                parent=self.dialog,
                            )
                else:
                    # 無法自動重啟，顯示詳細診斷（若有）
                    detail_text = supported_diag if supported_diag else None
                    UIUtils.show_manual_restart_dialog(self.dialog, detail_text)

    def _apply_settings(self) -> None:
        """套用設定"""
        try:
            changes = self._get_setting_changes()
            new_settings = changes["new"]

            # 儲存新設定
            self.settings.set_remember_size_position(new_settings["remember"])
            self.settings.set_auto_center(new_settings["auto_center"])
            self.settings.set_adaptive_sizing(new_settings["adaptive"])
            self.settings.set_debug_logging(new_settings["debug"])
            self.settings.set_dpi_scaling(new_settings["dpi"])

            # 檢查 DPI 變更並立即套用
            dpi_changed = abs(changes["old"]["dpi"] - new_settings["dpi"]) > 0.01
            if dpi_changed:
                FontManager.set_scale_factor(new_settings["dpi"])

            # 執行回調函數
            if self.on_settings_changed:
                self.on_settings_changed()

            # 顯示成功訊息
            important_changes = self._has_important_changes(changes)
            success_msg = "視窗偏好設定已成功儲存並套用！"
            if important_changes:
                success_msg += "\n\n設定已生效，部分變更可能需要重新啟動程式才能完全套用。"

            UIUtils.show_info("設定套用成功", success_msg, parent=self.dialog)

            # 處理重啟邏輯
            if important_changes and AppRestart.can_restart():
                if UIUtils.ask_yes_no_cancel(
                    "重新啟動程式",
                    "設定已成功套用！\n\n為了確保所有變更完全生效，建議重新啟動程式。\n\n是否要立即重新啟動？",
                    parent=self.dialog,
                    show_cancel=False,
                ):
                    try:
                        AppRestart.schedule_restart_and_exit(self.parent, delay=0.5)
                        return

                    except Exception as restart_error:
                        logger.error(f"重啟失敗: {restart_error}\n{traceback.format_exc()}")
                        UIUtils.show_error(
                            "重啟失敗",
                            f"無法重新啟動應用程式: {restart_error}\n\n設定已儲存，請手動重新啟動程式以套用所有變更。",
                            parent=self.dialog,
                        )
            elif important_changes and not AppRestart.can_restart():
                # 無法重啟時提供說明並附上診斷細節
                try:
                    _, diag = AppRestart.get_restart_diagnostics()
                except Exception:
                    diag = None
                # 顯示更完整的手動重啟 dialog，包含可複製的診斷文字
                UIUtils.show_manual_restart_dialog(self.dialog, diag)
            # 正常關閉對話框
            self.dialog.destroy()

        except Exception as e:
            logger.error(f"儲存失敗: {e}\n{traceback.format_exc()}")
            UIUtils.show_error("儲存失敗", f"無法儲存設定: {e}", parent=self.dialog)

    def _cancel(self) -> None:
        """取消設定"""
        self.dialog.destroy()
