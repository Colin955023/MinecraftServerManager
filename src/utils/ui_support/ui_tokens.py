"""
UI Token 定義
包含所有的視覺系統常數，包含字型大小、顏色、間距與元件基本尺寸
統一集中管理以消除硬編碼 (Hardcoding)
"""

from __future__ import annotations

from typing import Final


class FontSize:
    """字型大小定義，單位為 pt (points)"""

    TINY: Final[int] = 9
    SMALL: Final[int] = 10
    SMALL_PLUS: Final[int] = 11
    MEDIUM: Final[int] = 12
    NORMAL_PLUS: Final[int] = 13
    LARGE: Final[int] = 14
    HEADING_LARGE: Final[int] = 18


class Colors:
    """
    顏色定義，包含按鈕、文字、背景與其他 UI 元件的顏色
    每個顏色定義為一個二元組，包含 (light_mode_color, dark_mode_color)
    """

    # --- 綠色系 (Success) ---
    BUTTON_SUCCESS: Final[tuple[str, str]] = ("#059669", "#047857")
    BUTTON_SUCCESS_HOVER: Final[tuple[str, str]] = ("#047857", "#065f46")

    # --- 灰色系 (Secondary) ---
    BUTTON_LIGHT: Final[tuple[str, str]] = ("#e2e8f0", "#d1d5db")

    # --- 紅色系 (Danger) ---
    BUTTON_DANGER: Final[tuple[str, str]] = ("#dc2626", "#b91c1c")
    BUTTON_DANGER_HOVER: Final[tuple[str, str]] = ("#b91c1c", "#991b1b")

    # --- 文字色彩 ---
    TEXT_PRIMARY: Final[tuple[str, str]] = ("#1f2937", "#e5e7eb")
    TEXT_SECONDARY: Final[tuple[str, str]] = ("#6b7280", "#9ca3af")
    TEXT_MUTED: Final[tuple[str, str]] = ("#4b5563", "#9ca3af")
    TEXT_TERTIARY: Final[tuple[str, str]] = ("#a0aec0", "#a0aec0")
    TEXT_ERROR: Final[tuple[str, str]] = ("#e53e3e", "#e53e3e")
    TEXT_WARNING: Final[tuple[str, str]] = ("#b45309", "#d97706")

    # --- 介面與背景色彩 ---
    BG_PRIMARY: Final[tuple[str, str]] = ("#ffffff", "#1e1e1e")
    BG_CONSOLE: Final[str] = "#000000"
    BG_LISTBOX_LIGHT: Final[str] = "#f8fafc"
    BG_LISTBOX_DARK: Final[str] = "#2b2b2b"
    BG_CARD_LIGHT: Final[str] = "#ffffff"
    BG_CARD_DARK: Final[str] = "#2b2b2b"

    # --- 邊框與其他元件 ---
    BORDER_LIGHT: Final[tuple[str, str]] = ("#d1d5db", "#374151")
    BORDER: Final[tuple[str, str]] = ("#d1d5db", "#374151")
    TABLE_HEADER_BORDER: Final[tuple[str, str]] = ("#d1d5db", "#475569")
    CONSOLE_TEXT: Final[str] = "#00ff00"


class Spacing:
    """間距定義，單位為 px (pixels)"""

    TINY: Final[int] = 5
    SMALL: Final[int] = 6
    SMALL_PLUS: Final[int] = 8
    MEDIUM: Final[int] = 9
    LARGE: Final[int] = 12
    XL: Final[int] = 15
    XXL: Final[int] = 18


class Sizes:
    """尺寸定義，單位為 px (pixels)"""

    # === 按鈕 ===
    BUTTON_HEIGHT: Final[int] = 27
    BUTTON_HEIGHT_LARGE: Final[int] = 30
    BUTTON_WIDTH_SMALL: Final[int] = 75
    BUTTON_WIDTH_PRIMARY: Final[int] = 105
    BUTTON_WIDTH_SECONDARY: Final[int] = 90
    BUTTON_WIDTH_ACTION: Final[int] = 120
    BUTTON_WIDTH_COMPACT: Final[int] = 60
    DIALOG_BUTTON_WIDTH: Final[int] = 135
    DIALOG_BUTTON_HEIGHT: Final[int] = 38

    # === 輸入與選單 ===
    INPUT_HEIGHT: Final[int] = 24
    INPUT_WIDTH: Final[int] = 450
    DROPDOWN_WIDTH: Final[int] = 210
    DROPDOWN_COMPACT_WIDTH: Final[int] = 150
    DROPDOWN_FILTER_WIDTH: Final[int] = 75

    # === TreeView 欄寬 ===
    SERVER_TREE_COL_NAME: Final[int] = 225
    SERVER_TREE_COL_LOADER: Final[int] = 113

    # === 視窗對話框版面 ===
    DIALOG_SMALL_HEIGHT: Final[int] = 150
    DIALOG_PROGRESS_WIDTH: Final[int] = 600
    DIALOG_LARGE_WIDTH: Final[int] = 600
    DIALOG_LARGE_HEIGHT: Final[int] = 450
    SERVER_PROPERTIES_DIALOG_MIN_WIDTH: Final[int] = 900
    SERVER_PROPERTIES_DIALOG_MIN_HEIGHT: Final[int] = 600
    CONSOLE_PANEL_HEIGHT: Final[int] = 180
    PREVIEW_TEXTBOX_HEIGHT: Final[int] = 225
    MOD_EXPORT_SAVE_BUTTON_WIDTH: Final[int] = 135
    MOD_EXPORT_CLOSE_BUTTON_WIDTH: Final[int] = 113
    MOD_PROGRESS_HEIGHT: Final[int] = 15
    TABLE_HEADER_BORDER_WIDTH: Final[int] = 1


__all__ = [
    "Colors",
    "FontSize",
    "Sizes",
    "Spacing",
]
