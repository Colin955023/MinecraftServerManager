"""
UI Token 定義
包含所有的視覺系統常數，包含字型大小、顏色、間距與元件基本尺寸
統一集中管理以消除硬編碼 (Hardcoding)
"""

from typing import Final


class FontSize:
    """字型大小定義，單位為 pt (points)"""

    TINY: Final[int] = 9
    SMALL: Final[int] = 10
    NORMAL: Final[int] = 12
    SMALL_PLUS: Final[int] = 11
    MEDIUM: Final[int] = 12
    NORMAL_PLUS: Final[int] = 13
    INPUT: Final[int] = 12
    LARGE: Final[int] = 14
    HEADING_SMALL: Final[int] = 15
    HEADING_MEDIUM: Final[int] = 17
    HEADING_SMALL_PLUS: Final[int] = 17
    HEADING_LARGE: Final[int] = 18
    HEADING_XLARGE: Final[int] = 21
    CONSOLE: Final[int] = 9
    ICON: Final[int] = 17


class Colors:
    """顏色定義，包含按鈕、文本、背景與其他 UI 元件的顏色每個顏色定義為一個二元組，包含 (light_mode_color, dark_mode_color)"""

    # --- 基礎藍色系 (Primary / Info 共用) ---
    BUTTON_PRIMARY: Final[tuple[str, str]] = ("#2563eb", "#1d4ed8")
    BUTTON_PRIMARY_HOVER: Final[tuple[str, str]] = ("#1d4ed8", "#1e40af")
    BUTTON_PRIMARY_ACTIVE: Final[tuple[str, str]] = BUTTON_PRIMARY_HOVER
    BUTTON_PRIMARY_ACTIVE_HOVER: Final[tuple[str, str]] = ("#1e40af", "#1e40af")

    BUTTON_INFO: Final[tuple[str, str]] = ("#3b82f6", "#2563eb")
    BUTTON_INFO_HOVER: Final[tuple[str, str]] = BUTTON_PRIMARY

    # --- 綠色系 (Success) ---
    BUTTON_SUCCESS: Final[tuple[str, str]] = ("#059669", "#047857")
    BUTTON_SUCCESS_HOVER: Final[tuple[str, str]] = ("#047857", "#065f46")

    # --- 灰色系 (Secondary) ---
    BUTTON_SECONDARY: Final[tuple[str, str]] = ("#6b7280", "#4b5563")
    BUTTON_SECONDARY_HOVER: Final[tuple[str, str]] = ("#4b5563", "#374151")
    BUTTON_LIGHT: Final[tuple[str, str]] = ("#e2e8f0", "#d1d5db")
    BUTTON_LIGHT_HOVER: Final[tuple[str, str]] = ("#cbd5e1", "#e5e7eb")

    # --- 紫色系 (Purple / Accent) ---
    BUTTON_PURPLE: Final[tuple[str, str]] = ("#8b5cf6", "#7c3aed")
    BUTTON_PURPLE_HOVER: Final[tuple[str, str]] = ("#7c3aed", "#6d28d9")
    BUTTON_PURPLE_DARK: Final[tuple[str, str]] = BUTTON_PURPLE_HOVER
    BUTTON_PURPLE_DARK_HOVER: Final[tuple[str, str]] = ("#6d28d9", "#5b21b6")

    # --- 橘/黃色系 (Warning) ---
    BUTTON_WARNING: Final[tuple[str, str]] = ("#f59e0b", "#d97706")
    BUTTON_WARNING_HOVER: Final[tuple[str, str]] = ("#d97706", "#b45309")

    # --- 紅色系 (Danger) ---
    BUTTON_DANGER: Final[tuple[str, str]] = ("#dc2626", "#b91c1c")
    BUTTON_DANGER_HOVER: Final[tuple[str, str]] = ("#b91c1c", "#991b1b")

    # --- 文本色彩 ---
    TEXT_PRIMARY: Final[tuple[str, str]] = ("#1f2937", "#e5e7eb")
    TEXT_PRIMARY_CONTRAST: Final[tuple[str, str]] = TEXT_PRIMARY
    TEXT_HEADING: Final[tuple[str, str]] = ("#111827", "#f3f4f6")
    TEXT_SECONDARY: Final[tuple[str, str]] = ("#6b7280", "#9ca3af")
    TEXT_MUTED: Final[tuple[str, str]] = ("#4b5563", "#9ca3af")
    TEXT_TERTIARY: Final[tuple[str, str]] = ("#a0aec0", "#a0aec0")
    TEXT_ON_LIGHT: Final[str] = "#000000"
    TEXT_ON_DARK: Final[str] = "#ffffff"
    TEXT_LINK: Final[tuple[str, str]] = ("blue", "#4dabf7")
    TEXT_SUCCESS: Final[tuple[str, str]] = ("green", "#10b981")
    TEXT_ERROR: Final[tuple[str, str]] = ("#e53e3e", "#e53e3e")
    TEXT_WARNING: Final[tuple[str, str]] = ("#b45309", "#d97706")

    # --- 介面與背景色彩 ---
    BG_PRIMARY: Final[tuple[str, str]] = ("#ffffff", "#1e1e1e")
    BG_SECONDARY: Final[tuple[str, str]] = ("#f3f4f6", "#2b2b2b")
    BG_ALERT: Final[tuple[str, str]] = ("#fffbe6", "#2d2a1f")
    BG_CONSOLE: Final[str] = "#000000"
    BG_LISTBOX_LIGHT: Final[str] = "#f8fafc"
    BG_LISTBOX_DARK: Final[str] = "#2b2b2b"
    BG_ROW_SOFT_LIGHT: Final[str] = "#f1f5f9"
    BG_LISTBOX_ALT_LIGHT: Final[str] = "#e2e8f0"
    BG_LISTBOX_ALT_DARK: Final[str] = "#363636"

    # --- 邊框與其他元件 ---
    BORDER_LIGHT: Final[tuple[str, str]] = ("#d1d5db", "#374151")
    BORDER_MEDIUM: Final[tuple[str, str]] = ("#9ca3af", "#4b5563")
    DROPDOWN_BG: Final[tuple[str, str]] = ("#ffffff", "#2b2b2b")
    DROPDOWN_HOVER: Final[tuple[str, str]] = ("#f3f4f6", "#363636")
    DROPDOWN_BUTTON: Final[tuple[str, str]] = ("#e5e7eb", "#3f3f3f")
    DROPDOWN_BUTTON_HOVER: Final[tuple[str, str]] = ("#d1d5db", "#4f4f4f")
    CONSOLE_TEXT: Final[str] = "#00ff00"
    SCROLLBAR_BUTTON: Final[tuple[str, str]] = ("#333333", "#333333")
    SCROLLBAR_BUTTON_HOVER: Final[tuple[str, str]] = ("#555555", "#555555")
    SELECT_BG: Final[str] = "#1f538d"
    PROGRESS_ACCENT: Final[tuple[str, str]] = ("#22d3ee", "#4ade80")
    PROGRESS_TRACK: Final[tuple[str, str]] = ("#e5e7eb", "#374151")


class Spacing:
    """間距定義，單位為 px (pixels)"""

    TINY: Final[int] = 5
    XS: Final[int] = 3
    SMALL: Final[int] = 6
    SMALL_PLUS: Final[int] = 8
    MEDIUM: Final[int] = 9
    LARGE_MINUS: Final[int] = 12
    LARGE: Final[int] = 12
    XL: Final[int] = 15
    XXL: Final[int] = 18


class Sizes:
    """尺寸定義，單位為 px (pixels)"""

    # === 按鈕 ===
    BUTTON_HEIGHT: Final[int] = 27
    BUTTON_HEIGHT_MEDIUM: Final[int] = 27
    BUTTON_HEIGHT_LARGE: Final[int] = 30
    BUTTON_HEIGHT_SMALL: Final[int] = 21
    BUTTON_WIDTH_PRIMARY: Final[int] = 105
    BUTTON_WIDTH_SECONDARY: Final[int] = 90
    BUTTON_WIDTH_COMPACT: Final[int] = 60
    BUTTON_WIDTH_SMALL: Final[int] = 75
    BUTTON_HEIGHT_EXPORT: Final[int] = 20
    ICON_BUTTON: Final[int] = 15

    # === 輸入與選單 ===
    INPUT_HEIGHT: Final[int] = 24
    INPUT_WIDTH: Final[int] = 225
    INPUT_FIELD_WIDTH_CHARS: Final[int] = 24
    SPINBOX_WIDTH_CHARS: Final[int] = 11
    WRAP_LENGTH_MEDIUM: Final[int] = 300
    WRAP_LENGTH_WIDE: Final[int] = 675
    DROPDOWN_HEIGHT: Final[int] = 23
    DROPDOWN_WIDTH: Final[int] = 210
    SERVER_PROPERTY_TEXT_INPUT_WIDTH: Final[int] = 315
    DROPDOWN_COMPACT_WIDTH: Final[int] = 150
    DROPDOWN_FILTER_WIDTH: Final[int] = 75
    DROPDOWN_MAX_HEIGHT: Final[int] = 150
    DROPDOWN_ITEM_HEIGHT: Final[int] = 23

    # === TreeView 欄寬 ===
    SERVER_TREE_COL_NAME: Final[int] = 225
    SERVER_TREE_COL_VERSION: Final[int] = 57
    SERVER_TREE_COL_LOADER: Final[int] = 113
    SERVER_TREE_COL_STATUS: Final[int] = 83
    SERVER_TREE_COL_BACKUP: Final[int] = 83
    SERVER_TREE_COL_PATH: Final[int] = 150

    # === 視窗對話框版面 ===
    DIALOG_SMALL_WIDTH: Final[int] = 300
    DIALOG_SMALL_HEIGHT: Final[int] = 150
    DIALOG_MEDIUM_WIDTH: Final[int] = 450
    DIALOG_MEDIUM_HEIGHT: Final[int] = 300
    DIALOG_PROGRESS_WIDTH: Final[int] = 600
    DIALOG_PROGRESS_HEIGHT: Final[int] = 270
    DIALOG_LARGE_WIDTH: Final[int] = 600
    DIALOG_LARGE_HEIGHT: Final[int] = 450
    DIALOG_PREFERENCES_WIDTH: Final[int] = 480
    DIALOG_PREFERENCES_HEIGHT: Final[int] = 540
    DIALOG_FIRST_RUN_WIDTH: Final[int] = 360
    DIALOG_FIRST_RUN_HEIGHT: Final[int] = 188
    DIALOG_IMPORT_WIDTH: Final[int] = 338
    DIALOG_IMPORT_HEIGHT: Final[int] = 210
    DIALOG_ABOUT_WIDTH: Final[int] = 450
    DIALOG_ABOUT_HEIGHT: Final[int] = 488
    SERVER_PROPERTIES_DIALOG_WIDTH: Final[int] = 900
    SERVER_PROPERTIES_DIALOG_HEIGHT: Final[int] = 600
    SERVER_PROPERTIES_DIALOG_MIN_WIDTH: Final[int] = 900
    SERVER_PROPERTIES_DIALOG_MIN_HEIGHT: Final[int] = 600
    CONSOLE_PANEL_HEIGHT: Final[int] = 180
    CONSOLE_OUTPUT_HEIGHT: Final[int] = 240
    PREVIEW_TEXTBOX_HEIGHT: Final[int] = 225
    TREEVIEW_VISIBLE_ROWS: Final[int] = 12
    PLAYER_LIST_VISIBLE_ROWS: Final[int] = 5
    MOD_EXPORT_SAVE_BUTTON_WIDTH: Final[int] = 135
    MOD_EXPORT_CLOSE_BUTTON_WIDTH: Final[int] = 113
    MOD_PROGRESS_HEIGHT: Final[int] = 15
    ONLINE_HINT_WRAP_LENGTH: Final[int] = 735
    ONLINE_VERSION_HINT_WRAP_LENGTH: Final[int] = 570
    SERVER_PROPERTY_BOOL_WIDTH: Final[int] = 270
    SERVER_PROPERTY_BOOL_HEIGHT: Final[int] = 54
    PREFERENCES_RESET_BUTTON_HEIGHT: Final[int] = 16
    CARD_CORNER_RADIUS: Final[int] = 6
    INPUT_CORNER_RADIUS: Final[int] = 3
    APP_HEADER_HEIGHT: Final[int] = 45
