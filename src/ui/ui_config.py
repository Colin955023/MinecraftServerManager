"""UI 應用程式配置

此模組負責 customtkinter 全域配置與主題設定。
所有 GUI 組件建立前應先導入此模組以套用主題。

使用方式:
    from src.ui import ui_config
    ui_config.initialize_ui_theme()
"""

import customtkinter as ctk


def initialize_ui_theme() -> None:
    """初始化 UI 主題配置。

    應在應用程式啟動時（組建主視窗前）呼叫一次。
    設定全域外觀模式與色彩主題。

    Returns:
        None
    """
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
