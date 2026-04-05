"""UI Token 定義
包含所有的視覺系統常數，包含字型大小、顏色、間距與元件基本尺寸。
統一集中管理以消除硬編碼 (Hardcoding)。
"""

from typing import Final


class FontSize:
    """字型大小定義，單位為 pt (points)"""

    TINY: Final[int] = 10
    SMALL: Final[int] = 11
    NORMAL: Final[int] = 12
    SMALL_PLUS: Final[int] = 13
    MEDIUM: Final[int] = 14
    NORMAL_PLUS: Final[int] = 15
    INPUT: Final[int] = 16
    LARGE: Final[int] = 18
    HEADING_SMALL: Final[int] = 20
    HEADING_MEDIUM: Final[int] = 21
    HEADING_SMALL_PLUS: Final[int] = 22
    HEADING_LARGE: Final[int] = 24
    HEADING_XLARGE: Final[int] = 27
    CONSOLE: Final[int] = 11
    ICON: Final[int] = 21


class Colors:
    """顏色定義，包含按鈕、文本、背景與其他 UI 元件的顏色。每個顏色定義為一個二元組，包含 (light_mode_color, dark_mode_color)。"""

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
    BG_TOOLTIP: Final[str] = "#2b2b2b"
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
    XS: Final[int] = 4
    SMALL: Final[int] = 8
    SMALL_PLUS: Final[int] = 10
    MEDIUM: Final[int] = 12
    LARGE_MINUS: Final[int] = 15
    LARGE: Final[int] = 16
    XL: Final[int] = 20
    XXL: Final[int] = 24


class Sizes:
    """尺寸定義，單位為 px (pixels)"""

    # === 按鈕 ===
    BUTTON_HEIGHT: Final[int] = 36
    BUTTON_HEIGHT_MEDIUM: Final[int] = 35
    BUTTON_HEIGHT_LARGE: Final[int] = 40
    BUTTON_HEIGHT_SMALL: Final[int] = 28
    BUTTON_WIDTH_PRIMARY: Final[int] = 140
    BUTTON_WIDTH_SECONDARY: Final[int] = 120
    BUTTON_WIDTH_COMPACT: Final[int] = 80
    BUTTON_WIDTH_SMALL: Final[int] = 100
    BUTTON_HEIGHT_EXPORT: Final[int] = 25
    ICON_BUTTON: Final[int] = 20

    # === 輸入與選單 ===
    INPUT_HEIGHT: Final[int] = 32
    INPUT_WIDTH: Final[int] = 300
    INPUT_FIELD_WIDTH_CHARS: Final[int] = 32
    SPINBOX_WIDTH_CHARS: Final[int] = 14
    WRAP_LENGTH_MEDIUM: Final[int] = 400
    WRAP_LENGTH_WIDE: Final[int] = 900
    DROPDOWN_HEIGHT: Final[int] = 30
    DROPDOWN_WIDTH: Final[int] = 280
    DROPDOWN_COMPACT_WIDTH: Final[int] = 200
    DROPDOWN_FILTER_WIDTH: Final[int] = 100
    DROPDOWN_MAX_HEIGHT: Final[int] = 200
    DROPDOWN_ITEM_HEIGHT: Final[int] = 30

    # === TreeView 欄寬 ===
    SERVER_TREE_COL_NAME: Final[int] = 300
    SERVER_TREE_COL_VERSION: Final[int] = 75
    SERVER_TREE_COL_LOADER: Final[int] = 150
    SERVER_TREE_COL_STATUS: Final[int] = 110
    SERVER_TREE_COL_BACKUP: Final[int] = 110
    SERVER_TREE_COL_PATH: Final[int] = 200

    # === 視窗對話框版面 ===
    DIALOG_SMALL_WIDTH: Final[int] = 400
    DIALOG_SMALL_HEIGHT: Final[int] = 200
    DIALOG_MEDIUM_WIDTH: Final[int] = 600
    DIALOG_MEDIUM_HEIGHT: Final[int] = 400
    DIALOG_LARGE_WIDTH: Final[int] = 800
    DIALOG_LARGE_HEIGHT: Final[int] = 600
    DIALOG_PREFERENCES_WIDTH: Final[int] = 500
    DIALOG_PREFERENCES_HEIGHT: Final[int] = 600
    DIALOG_FIRST_RUN_WIDTH: Final[int] = 480
    DIALOG_FIRST_RUN_HEIGHT: Final[int] = 250
    DIALOG_IMPORT_WIDTH: Final[int] = 450
    DIALOG_IMPORT_HEIGHT: Final[int] = 280
    DIALOG_ABOUT_WIDTH: Final[int] = 600
    DIALOG_ABOUT_HEIGHT: Final[int] = 650
    CONSOLE_PANEL_HEIGHT: Final[int] = 240
    PREVIEW_TEXTBOX_HEIGHT: Final[int] = 300
    TREEVIEW_VISIBLE_ROWS: Final[int] = 15
    APP_HEADER_HEIGHT: Final[int] = 60
