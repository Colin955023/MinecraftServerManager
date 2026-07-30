"""
UI Token 定義
包含所有的視覺系統常數，包含字型大小、顏色、間距與元件基本尺寸。
統一集中管理以消除硬編碼 (Hardcoding)。
"""

from typing import Final

from PySide6.QtGui import QColor
from qfluentwidgets import ThemeColor, themeColor


class FontSize:
    """字型大小定義，單位為 pt (points)"""

    TINY: Final[int] = 12
    SMALL: Final[int] = 15
    NORMAL: Final[int] = 16
    SMALL_PLUS: Final[int] = 17
    MEDIUM: Final[int] = 18
    NORMAL_PLUS: Final[int] = 20
    INPUT: Final[int] = 18
    LARGE: Final[int] = 21
    HEADING_SMALL: Final[int] = 23
    HEADING_MEDIUM: Final[int] = 26
    HEADING_SMALL_PLUS: Final[int] = 26
    HEADING_LARGE: Final[int] = 27
    HEADING_XLARGE: Final[int] = 32
    CONSOLE: Final[int] = 14
    ICON: Final[int] = 26


class FluentTokens:
    """統一管理所有可自訂的設計 Token，自動追蹤主題變更"""

    # 語義化色彩（映射到 Fluent ThemeColor）
    PRIMARY = "ThemeColor.PRIMARY"
    SECONDARY = "ThemeColor.SECONDARY"
    BACKGROUND = "ThemeColor.BACKGROUND"
    SURFACE = "ThemeColor.SURFACE"
    TEXT_PRIMARY = "ThemeColor.TEXT_PRIMARY"
    TEXT_SECONDARY = "ThemeColor.TEXT_SECONDARY"
    BORDER = "ThemeColor.BORDER"
    HOVER = "ThemeColor.HOVER"
    PRESSED = "ThemeColor.PRESSED"
    DISABLED = "ThemeColor.DISABLED"

    # 尺寸 Token
    SPACING_XS = 4
    SPACING_SM = 8
    SPACING_MD = 12
    SPACING_LG = 16
    SPACING_XL = 24

    BORDER_RADIUS_SM = 4
    BORDER_RADIUS_MD = 6
    BORDER_RADIUS_LG = 8
    BORDER_RADIUS_FULL = 999

    FONT_SIZE_SM = 27
    FONT_SIZE_MD = 32
    FONT_SIZE_LG = 36
    FONT_SIZE_XL = 45

    @classmethod
    def resolve_color(cls, token: str) -> QColor:
        """
        解析 Token 為實際 QColor（支援主題切換）

        Args:
            token (str): 顏色 Token，支援 ThemeColor 前綴。

        Returns:
            QColor: 對應的 QColor 物件。
        """
        if token.startswith("ThemeColor."):
            color_attr = token.split(".")[1]
            return themeColor(getattr(ThemeColor, color_attr))
        return QColor(token)

    @classmethod
    def qss_value(cls, token: str) -> str:
        """
        產生 QSS 可用的色彩值（含主題變數）

        Args:
            token (str): 顏色 Token，支援 ThemeColor 前綴。

        Returns:
            str: 對應的 QSS 色彩值，若為 ThemeColor 則回傳 CSS 變數格式。
        """
        if token.startswith("ThemeColor."):
            return f"var({token})"  # qfluentwidgets 支援 CSS 變數
        color = cls.resolve_color(token)
        return color.name()


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
    BG_WARNING: Final[tuple[str, str]] = ("#fff7ed", "#2d1f1a")
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
    BUTTON_HEIGHT: Final[int] = 42
    BUTTON_HEIGHT_MEDIUM: Final[int] = 42
    BUTTON_HEIGHT_LARGE: Final[int] = 46
    BUTTON_HEIGHT_SMALL: Final[int] = 48
    BUTTON_WIDTH_PRIMARY: Final[int] = 158
    BUTTON_WIDTH_SECONDARY: Final[int] = 180
    BUTTON_WIDTH_COMPACT: Final[int] = 90
    BUTTON_WIDTH_TOOLBAR: Final[int] = 160
    BUTTON_WIDTH_SMALL: Final[int] = 113
    BUTTON_WIDTH_EXPORT: Final[int] = 150
    BUTTON_HEIGHT_EXPORT: Final[int] = 40
    ICON_BUTTON: Final[int] = 23
    DETECT_BUTTON_WIDTH: Final[int] = 220

    # === 輸入與選單 ===
    INPUT_HEIGHT: Final[int] = 36
    INPUT_WIDTH: Final[int] = 338
    INPUT_FIELD_WIDTH_CHARS: Final[int] = 24
    SPINBOX_WIDTH_CHARS: Final[int] = 11
    WRAP_LENGTH_MEDIUM: Final[int] = 450
    WRAP_LENGTH_WIDE: Final[int] = 1013
    DROPDOWN_HEIGHT: Final[int] = 35
    DROPDOWN_WIDTH: Final[int] = 315
    SERVER_PROPERTY_TEXT_INPUT_WIDTH: Final[int] = 473
    DROPDOWN_COMPACT_WIDTH: Final[int] = 225
    DROPDOWN_FILTER_WIDTH: Final[int] = 113
    DROPDOWN_MAX_HEIGHT: Final[int] = 225
    DROPDOWN_ITEM_HEIGHT: Final[int] = 35

    # === TreeView 欄寬 ===
    SERVER_TREE_COL_NAME: Final[int] = 338
    SERVER_TREE_COL_VERSION: Final[int] = 86
    SERVER_TREE_COL_LOADER: Final[int] = 170
    SERVER_TREE_COL_STATUS: Final[int] = 125
    SERVER_TREE_COL_BACKUP: Final[int] = 125
    SERVER_TREE_COL_PATH: Final[int] = 225

    # === 視窗對話框版面 ===
    DIALOG_SMALL_WIDTH: Final[int] = 450
    DIALOG_SMALL_HEIGHT: Final[int] = 225
    DIALOG_MEDIUM_WIDTH: Final[int] = 675
    DIALOG_MEDIUM_HEIGHT: Final[int] = 450
    DIALOG_PROGRESS_WIDTH: Final[int] = 750
    DIALOG_PROGRESS_HEIGHT: Final[int] = 360
    DIALOG_LARGE_WIDTH: Final[int] = 900
    DIALOG_LARGE_HEIGHT: Final[int] = 675
    DIALOG_PREFERENCES_WIDTH: Final[int] = 720
    DIALOG_PREFERENCES_HEIGHT: Final[int] = 810
    DIALOG_FIRST_RUN_WIDTH: Final[int] = 540
    DIALOG_FIRST_RUN_HEIGHT: Final[int] = 282
    DIALOG_IMPORT_WIDTH: Final[int] = 507
    DIALOG_IMPORT_HEIGHT: Final[int] = 315
    DIALOG_ABOUT_WIDTH: Final[int] = 675
    DIALOG_ABOUT_HEIGHT: Final[int] = 732
    SERVER_PROPERTIES_DIALOG_WIDTH: Final[int] = 1200
    SERVER_PROPERTIES_DIALOG_HEIGHT: Final[int] = 800
    SERVER_PROPERTIES_DIALOG_MIN_WIDTH: Final[int] = 1200
    SERVER_PROPERTIES_DIALOG_MIN_HEIGHT: Final[int] = 800
    CONSOLE_PANEL_HEIGHT: Final[int] = 270
    CONSOLE_OUTPUT_HEIGHT: Final[int] = 360
    PREVIEW_TEXTBOX_HEIGHT: Final[int] = 338
    TREEVIEW_VISIBLE_ROWS: Final[int] = 12
    PLAYER_LIST_VISIBLE_ROWS: Final[int] = 5
    MOD_EXPORT_SAVE_BUTTON_WIDTH: Final[int] = 203
    MOD_EXPORT_CLOSE_BUTTON_WIDTH: Final[int] = 170
    MOD_PROGRESS_HEIGHT: Final[int] = 23
    ONLINE_HINT_WRAP_LENGTH: Final[int] = 1103
    ONLINE_VERSION_HINT_WRAP_LENGTH: Final[int] = 855
    SERVER_PROPERTY_BOOL_WIDTH: Final[int] = 405
    SERVER_PROPERTY_BOOL_HEIGHT: Final[int] = 81
    PREFERENCES_RESET_BUTTON_HEIGHT: Final[int] = 48
    CARD_CORNER_RADIUS: Final[int] = 6
    INPUT_CORNER_RADIUS: Final[int] = 3
    APP_HEADER_HEIGHT: Final[int] = 68
    FLUENT_BUTTON_HEIGHT: Final[int] = 59
    RELOAD_BUTTON_WIDTH: Final[int] = 108
    FORM_LABEL_WIDTH: Final[int] = 215
    SIDEBAR_SPACER_WIDTH: Final[int] = 54
    PROGRESS_BUTTON_HEIGHT: Final[int] = 57
    WARNING_AREA_HEIGHT: Final[int] = 63
