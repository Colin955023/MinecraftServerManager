"""UI 應用程式配置

此模組負責 PySide6 全域配置與主題設定。
所有 GUI 組件建立前應先導入此模組以套用主題。
"""

from typing import Any, ClassVar

from ..utils.ui_support.fluent import apply_fluent_theme
from ..utils.ui_support.qt_runtime import QtCore, QtGui, QtWidgets, ensure_application


def resolve_color(color: Any, *, dark: bool | None = None) -> str:
    """解析專案色彩設定為 Qt stylesheet 可用色碼。

    Args:
        color: 單一色碼或 `(light, dark)` 色碼 tuple。
        dark: 是否使用深色主題；未指定時由目前 QApplication 判斷。

    Returns:
        Qt stylesheet 可接受的色彩字串。
    """
    if dark is None:
        app = QtWidgets.QApplication.instance()
        dark = _is_dark_scheme(app) if isinstance(app, QtWidgets.QApplication) else False
    if isinstance(color, tuple):
        return str(color[1 if dark and len(color) > 1 else 0])
    return str(color)


def _requested_scheme(mode: str) -> QtCore.Qt.ColorScheme:
    normalized = str(mode or "system").strip().lower()
    if normalized == "dark":
        return QtCore.Qt.ColorScheme.Dark
    if normalized == "light":
        return QtCore.Qt.ColorScheme.Light
    return QtCore.Qt.ColorScheme.Unknown


def _is_dark_scheme(app: QtWidgets.QApplication | None) -> bool:
    if app is None:
        return False
    scheme = app.styleHints().colorScheme()
    if scheme == QtCore.Qt.ColorScheme.Dark:
        return True
    if scheme == QtCore.Qt.ColorScheme.Light:
        return False
    return app.palette().color(QtGui.QPalette.ColorRole.Window).lightness() < 128


def _preferred_ui_font(point_size: int = 12) -> QtGui.QFont:
    candidates = ("Microsoft JhengHei UI", "Microsoft JhengHei", "Noto Sans CJK TC")
    try:
        families = set(QtGui.QFontDatabase.families())
        family = next((candidate for candidate in candidates if candidate in families), "")
        font = (
            QtGui.QFont(family, point_size)
            if family
            else QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.GeneralFont)
        )
        font.setPointSize(point_size)
        return font
    except Exception:
        return QtGui.QFont("Arial", point_size)


def _scope_selector(selector: str, scope: str | None = None) -> str:
    if not scope:
        return selector
    return ", ".join(f"{scope} {part.strip()}" for part in selector.split(","))


def _dialog_control_stylesheet(
    *,
    text: str = "#0f172a",
    input_bg: str = "#ffffff",
    input_border: str = "#64748b",
    primary: str = "#2563eb",
    primary_hover: str = "#1d4ed8",
    secondary_button: str = "#4b5563",
    secondary_hover: str = "#374151",
    panel_2: str = "#f8fafc",
    selection: str = "#dbeafe",
    disabled_button: str = "#9ca3af",
    scope: str | None = None,
) -> str:
    button = _scope_selector("QPushButton", scope)
    input_selector = _scope_selector(
        "QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox",
        scope,
    )
    input_focus = _scope_selector(
        "QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus",
        scope,
    )
    return (
        f"{button} {{ background: {primary}; color: white; border: 0; border-radius: 4px; padding: 6px 10px; }}"
        f"{button}:hover {{ background: {primary_hover}; }}"
        f"{button}:pressed {{ background: {secondary_hover}; }}"
        f"{button}:disabled {{ background: {disabled_button}; color: #f8fafc; }}"
        f'{button}[secondary="true"] {{ background: {secondary_button}; }}'
        f'{button}[secondary="true"]:hover {{ background: {secondary_hover}; }}'
        f"{input_selector} {{ background: {input_bg}; color: {text}; border: 2px solid {input_border}; "
        "border-radius: 3px; padding: 4px 7px; selection-color: #ffffff; "
        f"selection-background-color: {primary}; }}"
        f"{input_focus} {{ border-color: {primary}; }}"
        f"{_scope_selector('QComboBox::drop-down', scope)} {{ width: 21px; border-left: 1px solid {input_border}; "
        f"background: {panel_2}; }}"
        f"{_scope_selector('QComboBox QAbstractItemView', scope)} {{ background: {input_bg}; color: {text}; "
        f"selection-background-color: {selection}; selection-color: {text}; }}"
        + _checkbox_stylesheet(
            text=text,
            unchecked_fill=input_bg,
            unchecked_border=input_border,
            checked_fill=primary,
            checked_border=primary_hover,
            hover_fill=panel_2,
            checked_hover_fill=primary_hover,
            disabled_fill=panel_2,
            disabled_border=disabled_button,
            scope=scope,
        )
        + f"{_scope_selector('QRadioButton', scope)} {{ color: {text}; spacing: 6px; background: transparent; }}"
    )


def _checkbox_stylesheet(
    *,
    text: str,
    unchecked_fill: str,
    unchecked_border: str,
    checked_fill: str,
    checked_border: str,
    hover_fill: str,
    checked_hover_fill: str,
    disabled_fill: str,
    disabled_border: str,
    scope: str | None = None,
) -> str:
    checkbox = _scope_selector("QCheckBox", scope)
    indicator = _scope_selector("QCheckBox::indicator", scope)
    unchecked_indicator = _scope_selector("QCheckBox::indicator:unchecked", scope)
    checked_indicator = _scope_selector("QCheckBox::indicator:checked", scope)
    return (
        f"{checkbox} {{ color: {text}; spacing: 8px; background: transparent; }}"
        f"{indicator} {{ width: 18px; height: 18px; border-radius: 5px; border: 2px solid {unchecked_border}; "
        f"background: {unchecked_fill}; }}"
        f"{unchecked_indicator}:hover {{ border-color: {checked_border}; background: {hover_fill}; }}"
        f"{checked_indicator} {{ border-color: {checked_border}; background: {checked_fill}; }}"
        f"{checked_indicator}:hover {{ border-color: {checked_border}; background: {checked_hover_fill}; }}"
        f"{unchecked_indicator}:disabled {{ border-color: {disabled_border}; background: {disabled_fill}; }}"
        f"{checked_indicator}:disabled {{ border-color: {disabled_border}; background: {disabled_border}; }}"
    )


def _dialog_surface_stylesheet(*, panel_2: str = "#f8fafc", text: str = "#0f172a") -> str:
    return (
        f"QDialog, QMessageBox {{ background: {panel_2}; color: {text}; }}"
        f"QLabel {{ color: {text}; background: transparent; }}"
    )


class NativeQtStyle:
    """集中存放原生 Qt UI stylesheet。"""

    _theme: ClassVar[dict[str, str]] = {}
    _dark: ClassVar[bool] = False

    app_root = (
        "#AppRoot { background: #f3f4f6; color: #0f172a; }"
        "QToolTip { background: #111827; color: white; border: 0; padding: 3px; }"
    )
    main_header = "#MainHeader { background: #f3f4f6; border: 0; }"
    sidebar_toggle = (
        "#SidebarToggleButton { background: #2563eb; color: white; border: 0; border-radius: 4px; }"
        "#SidebarToggleButton:hover { background: #1d4ed8; }"
    )
    main_content = "#MainContent { background: #f3f4f6; border: 0; }"
    sidebar = "#Sidebar { background: #ffffff; border: 0; }"
    content_container = "#ContentContainer { background: #f3f4f6; border: 0; }"
    content_stack = "#ContentStack { background: transparent; border: 0; }"
    create_page = (
        "#CreateServerFrame { background: #f3f4f6; color: #0f172a; }"
        "QLineEdit, QComboBox {"
        "background: #ffffff; border: 1px solid #cbd5e1; border-radius: 3px;"
        "padding: 3px 5px; color: #0f172a;"
        "}"
        "QLineEdit:focus, QComboBox:focus { border-color: #2563eb; }"
        "QComboBox::drop-down { width: 14px; border-left: 1px solid #d1d5db; background: #e5e7eb; }"
        "QComboBox QAbstractItemView { background: #ffffff; color: #0f172a; selection-background-color: #dbeafe; }"
    )
    custom_dropdown = (
        "QComboBox { background: #ffffff; color: #0f172a; border: 1px solid #cbd5e1;"
        "border-radius: 3px; padding: 3px 5px; }"
        "QComboBox::drop-down { width: 14px; border-left: 1px solid #d1d5db; background: #e5e7eb; }"
        "QComboBox QAbstractItemView { background: #ffffff; color: #0f172a;"
        "selection-background-color: #dbeafe; }"
    )
    eula_notice = "#EulaNotice { background: #fffbe6; border: 1px solid #fde68a; border-radius: 3px; }"
    create_form_panel = "#CreateFormPanel { background: transparent; border: 0; }"
    create_actions = "#CreateServerActions { background: #f3f4f6; border: 0; }"
    monitor_window = (
        "#ServerMonitorWindow { background: #f3f4f6; color: #0f172a; }"
        "#ServerMonitorWindow QLabel { color: #0f172a; }"
        "#ServerMonitorWindow QFrame { background: #f3f4f6; border: 0; }"
        "#ServerMonitorWindow QListWidget {"
        "background: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 3px;"
        "}" + _dialog_control_stylesheet(scope="#ServerMonitorWindow")
    )
    dialog_controls = _dialog_control_stylesheet()
    generic_dialog = _dialog_surface_stylesheet() + dialog_controls
    message_box = generic_dialog
    about_dialog = _dialog_surface_stylesheet() + dialog_controls
    progress_dialog = (
        "QDialog { background: #f8fafc; color: #0f172a; }"
        "QLabel { color: #0f172a; }"
        "QProgressBar { background: #e5e7eb; border: 1px solid #cbd5e1; border-radius: 3px; text-align: center; }"
        "QProgressBar::chunk { background: #2563eb; border-radius: 3px; }" + dialog_controls
    )
    preferences_dialog = (
        _dialog_surface_stylesheet()
        + "QFrame, QScrollArea, QScrollArea QWidget { background: transparent; color: #0f172a; border: 0; }"
        + dialog_controls
    )
    server_properties_dialog = _dialog_surface_stylesheet() + dialog_controls

    @staticmethod
    def nav_item_frame(key: str) -> str:
        """產生側欄項目容器樣式。

        Args:
            key: 導航項目識別鍵。

        Returns:
            Qt stylesheet 字串。
        """
        return f"#NavItem_{key} {{ background: transparent; border: 0; }}"

    @staticmethod
    def nav_button(*, active: bool, mini: bool) -> str:
        """產生側欄按鈕樣式。

        Args:
            active: 是否為目前作用中頁面。
            mini: 是否為迷你側欄模式。

        Returns:
            Qt stylesheet 字串。
        """
        dark = bool(getattr(NativeQtStyle, "_dark", False))
        fg = "#1e40af" if active and dark else "#2557d6" if active else "#2563eb" if dark else "#3b82f6"
        hover = "#1e3a8a" if active and dark else "#1e40af" if active else "#1d4ed8" if dark else "#2563eb"
        align = "center" if mini else "left"
        padding = "0" if mini else "0 16px"
        return (
            "QPushButton {"
            f"background: {fg}; color: white; border: 0; border-radius: 4px;"
            f"text-align: {align}; padding: {padding};"
            "}"
            f"QPushButton:hover {{ background: {hover}; }}"
            "QPushButton:disabled { background: #9ca3af; color: #f8fafc; }"
        )

    @staticmethod
    def create_button(*, kind: str) -> str:
        """產生建立伺服器頁按鈕樣式。

        Args:
            kind: 按鈕種類，例如 primary 或 secondary。

        Returns:
            Qt stylesheet 字串。
        """
        theme = getattr(NativeQtStyle, "_theme", {})
        bg = (
            theme.get("button_primary_dark", "#1f4e79")
            if kind == "primary"
            else theme.get("button_secondary", "#2f3b52")
        )
        hover = (
            theme.get("button_primary_hover", "#163d61")
            if kind == "primary"
            else theme.get("button_secondary_hover", "#1f2937")
        )
        return (
            "QPushButton {"
            f"background: {bg}; color: white; border: 0; border-radius: 4px; padding: 4px 8px;"
            "}"
            f"QPushButton:hover {{ background: {hover}; }}"
            "QPushButton:disabled { background: #9ca3af; color: #f8fafc; }"
        )

    @staticmethod
    def color_style(color: str) -> str:
        """產生文字顏色樣式。

        Args:
            color: CSS/Qt 可接受的顏色字串。

        Returns:
            Qt stylesheet 字串。
        """
        return f"color: {color};"


def _refresh_native_styles(dark: bool) -> None:
    bg = "#0b0b0b" if dark else "#f3f4f6"
    panel = "#000000" if dark else "#ffffff"
    panel_2 = "#171717" if dark else "#f8fafc"
    text = "#ffffff" if dark else "#0f172a"
    heading = "#f8fafc" if dark else "#374151"
    muted = "#cbd5e1" if dark else "#4b5563"
    border = "#4b5563" if dark else "#cbd5e1"
    border_soft = "#374151" if dark else "#d1d5db"
    input_border = "#94a3b8" if dark else "#64748b"
    primary = "#1d4ed8" if dark else "#2563eb"
    primary_hover = "#1e40af" if dark else "#1d4ed8"
    secondary_button = "#4b5563" if dark else "#2f3b52"
    secondary_hover = "#374151" if dark else "#1f2937"
    input_bg = "#000000" if dark else "#ffffff"
    selection = "#2563eb" if dark else "#dbeafe"
    disabled_button = "#4b5563" if dark else "#9ca3af"
    tooltip_bg = "#111827"
    tooltip_text = "#ffffff"
    NativeQtStyle._theme = {
        "button_primary_dark": "#1f4e79" if not dark else primary,
        "button_primary_hover": "#163d61" if not dark else primary_hover,
        "button_secondary": secondary_button,
        "button_secondary_hover": secondary_hover,
        "bg": bg,
        "panel": panel,
        "panel_2": panel_2,
        "input_bg": input_bg,
        "text": text,
        "heading": heading,
        "muted": muted,
        "border": border,
        "border_soft": border_soft,
        "input_border": input_border,
        "primary": primary,
        "primary_hover": primary_hover,
    }
    NativeQtStyle._dark = dark
    NativeQtStyle.app_root = (
        f"#AppRoot {{ background: {bg}; color: {text}; }}"
        f"QToolTip {{ background: {tooltip_bg}; color: {tooltip_text}; border: 0; padding: 5px; }}"
    )
    NativeQtStyle.main_header = f"#MainHeader {{ background: {bg}; border: 0; }}"
    NativeQtStyle.sidebar_toggle = (
        f"#SidebarToggleButton {{ background: {primary}; color: white; border: 0; border-radius: 4px; }}"
        f"#SidebarToggleButton:hover {{ background: {primary_hover}; }}"
    )
    NativeQtStyle.main_content = f"#MainContent {{ background: {bg}; border: 0; }}"
    NativeQtStyle.sidebar = f"#Sidebar {{ background: {panel}; border: 0; }}"
    NativeQtStyle.content_container = f"#ContentContainer {{ background: {bg}; border: 0; }}"
    NativeQtStyle.content_stack = "#ContentStack { background: transparent; border: 0; }"
    NativeQtStyle.create_page = (
        f"#CreateServerFrame, #CreateServerFrame QWidget, #CreateServerScrollArea, #CreateServerScrollArea QWidget, "
        f"#CreateServerContent {{ background: {bg}; color: {text}; }}"
        f"#CreateServerScrollArea::viewport {{ background: {bg}; }}"
        f"#CreateServerFrame QLabel {{ color: {text}; background: transparent; }}"
        "#CreateServerFrame QLineEdit, #CreateServerFrame QComboBox {"
        f"background: {input_bg}; border: 2px solid {input_border}; border-radius: 3px;"
        f"padding: 4px 7px; color: {text};"
        "}"
        f"#CreateServerFrame QLineEdit:focus, #CreateServerFrame QComboBox:focus {{ border-color: {primary}; }}"
        f"#CreateServerFrame QComboBox::drop-down {{ width: 21px; border-left: 1px solid {input_border}; background: {panel_2}; }}"
        f"#CreateServerFrame QComboBox QAbstractItemView {{ background: {input_bg}; color: {text}; selection-background-color: {selection}; }}"
    )
    NativeQtStyle.custom_dropdown = (
        f"QComboBox {{ background: {input_bg}; color: {text}; border: 2px solid {input_border};"
        "border-radius: 3px; padding: 4px 7px; }"
        f"QComboBox:focus {{ border-color: {primary}; }}"
        f"QComboBox::drop-down {{ width: 21px; border-left: 1px solid {input_border}; background: {panel_2}; }}"
        f"QComboBox QAbstractItemView {{ background: {input_bg}; color: {text};"
        f"selection-background-color: {selection}; }}"
    )
    NativeQtStyle.eula_notice = (
        "#EulaNotice { background: #2d2a1f; border: 1px solid #a16207; border-radius: 3px; }"
        if dark
        else "#EulaNotice { background: #fffbe6; border: 1px solid #fde68a; border-radius: 3px; }"
    )
    NativeQtStyle.create_form_panel = f"#CreateFormPanel {{ background: {bg}; color: {text}; border: 0; }}"
    NativeQtStyle.create_actions = f"#CreateServerActions {{ background: {bg}; border: 0; }}"
    NativeQtStyle.dialog_controls = _dialog_control_stylesheet(
        text=text,
        input_bg=input_bg,
        input_border=input_border,
        primary=primary,
        primary_hover=primary_hover,
        secondary_button=secondary_button,
        secondary_hover=secondary_hover,
        panel_2=panel_2,
        selection=selection,
        disabled_button=disabled_button,
    )
    NativeQtStyle.generic_dialog = (
        _dialog_surface_stylesheet(panel_2=panel_2, text=text) + NativeQtStyle.dialog_controls
    )
    NativeQtStyle.message_box = NativeQtStyle.generic_dialog
    NativeQtStyle.monitor_window = (
        f"#ServerMonitorWindow {{ background: {bg}; color: {text}; }}"
        f"#ServerMonitorWindow QLabel {{ color: {text}; }}"
        f"#ServerMonitorWindow QFrame {{ background: {bg}; border: 0; }}"
        "#ServerMonitorWindow QListWidget {"
        f"background: {input_bg}; color: {text}; border: 1px solid {border}; border-radius: 3px;"
        "}"
        + _dialog_control_stylesheet(
            text=text,
            input_bg=input_bg,
            input_border=input_border,
            primary=primary,
            primary_hover=primary_hover,
            secondary_button=secondary_button,
            secondary_hover=secondary_hover,
            panel_2=panel_2,
            selection=selection,
            disabled_button=disabled_button,
            scope="#ServerMonitorWindow",
        )
    )
    NativeQtStyle.about_dialog = _dialog_surface_stylesheet(panel_2=panel_2, text=text) + NativeQtStyle.dialog_controls
    NativeQtStyle.progress_dialog = (
        f"QDialog {{ background: {panel_2}; color: {text}; }}"
        f"QLabel {{ color: {text}; }}"
        f"QProgressBar {{ background: {panel}; color: {text}; border: 1px solid {border}; border-radius: 3px; text-align: center; }}"
        f"QProgressBar::chunk {{ background: {primary}; border-radius: 3px; }}" + NativeQtStyle.dialog_controls
    )
    NativeQtStyle.preferences_dialog = (
        _dialog_surface_stylesheet(panel_2=panel_2, text=text)
        + f"QFrame, QScrollArea, QScrollArea QWidget {{ background: transparent; color: {text}; border: 0; }}"
        f"QSlider::groove:horizontal {{ background: {border}; height: 4px; border-radius: 2px; }}"
        f"QSlider::handle:horizontal {{ background: {primary}; width: 12px; margin: -5px 0; border-radius: 6px; }}"
        + NativeQtStyle.dialog_controls
    )
    NativeQtStyle.server_properties_dialog = (
        _dialog_surface_stylesheet(panel_2=panel_2, text=text)
        + f"QFrame, QScrollArea, QScrollArea QWidget {{ background: {panel_2}; color: {text}; border: 0; }}"
        f"QLabel#ServerPropertiesTitle {{ color: {heading}; }}"
        f"QTabWidget::pane {{ background: {panel}; border: 1px solid {border}; }}"
        f"QTabBar::tab {{ background: {primary}; color: white; border: 1px solid {border_soft}; padding: 5px 12px; }}"
        f"QTabBar::tab:selected {{ background: {primary_hover}; }}" + NativeQtStyle.dialog_controls
    )


def initialize_ui_theme(mode: str = "light") -> None:
    """初始化 UI 主題配置。

    應在應用程式啟動時（組建主視窗前）呼叫一次。
    設定全域外觀模式與色彩主題。

    Args:
        mode: 主題模式，可為 `light` 或 `dark`。

    Returns:
        None
    """
    app = ensure_application()
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(_requested_scheme(mode))
    dark = _is_dark_scheme(app)
    _refresh_native_styles(dark)
    apply_fluent_theme(dark=dark, accent_color="#1d4ed8" if dark else "#2563eb")

    colors = {
        "window": "#0b0b0b" if dark else "#f3f4f6",
        "window_text": "#ffffff" if dark else "#0f172a",
        "base": "#000000" if dark else "#ffffff",
        "alternate_base": "#171717" if dark else "#f8fafc",
        "text": "#ffffff" if dark else "#0f172a",
        "button": "#1d4ed8" if dark else "#2563eb",
        "button_text": "#ffffff",
        "highlight": "#2563eb",
        "highlighted_text": "#ffffff",
        "input_border": "#94a3b8" if dark else "#64748b",
        "disabled_button": "#4b5563" if dark else "#9ca3af",
        "tree_border": "#4b5563" if dark else "#cbd5e1",
        "tree_header": "#171717" if dark else "#f1f5f9",
        "tree_alt": "#111827" if dark else "#f8fafc",
    }
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(colors["window"]))
    palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(colors["window_text"]))
    palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(colors["base"]))
    palette.setColor(QtGui.QPalette.ColorRole.AlternateBase, QtGui.QColor(colors["alternate_base"]))
    palette.setColor(QtGui.QPalette.ColorRole.ToolTipBase, QtGui.QColor("#111827"))
    palette.setColor(QtGui.QPalette.ColorRole.ToolTipText, QtGui.QColor("#ffffff"))
    palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(colors["text"]))
    palette.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor(colors["button"]))
    palette.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor(colors["button_text"]))
    palette.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor(colors["highlight"]))
    palette.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor(colors["highlighted_text"]))
    app.setPalette(palette)

    ui_font = _preferred_ui_font(12)
    QtWidgets.QApplication.setFont(ui_font)
    font_family = ui_font.family().replace("'", "\\'")
    app.setStyleSheet(
        f"QWidget {{ font-family: '{font_family}'; color: {colors['text']}; }}"
        f"QLabel, QRadioButton, QGroupBox, QTabWidget, QTreeView {{ color: {colors['text']}; }}"
        "QToolTip { background: #000000; color: #ffffff; border: 1px solid #ffffff; padding: 5px; }"
        "QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {"
        f"background: {colors['base']}; color: {colors['text']}; border: 2px solid {colors['input_border']}; "
        "border-radius: 3px; padding: 4px 7px;"
        "}"
        f"QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus "
        f"{{ border-color: {colors['button']}; }}"
        f"QComboBox::drop-down {{ width: 21px; border-left: 1px solid {colors['input_border']}; "
        f"background: {colors['alternate_base']}; }}"
        f"QComboBox QAbstractItemView {{ background: {colors['base']}; color: {colors['text']}; "
        f"selection-background-color: {colors['highlight']}; selection-color: #ffffff; }}"
        + _checkbox_stylesheet(
            text=colors["text"],
            unchecked_fill=colors["alternate_base"] if dark else colors["base"],
            unchecked_border="#cbd5e1" if dark else colors["input_border"],
            checked_fill=colors["button"],
            checked_border="#bfdbfe" if dark else colors["button"],
            hover_fill="#334155" if dark else colors["alternate_base"],
            checked_hover_fill="#1e40af" if dark else "#1d4ed8",
            disabled_fill=colors["alternate_base"],
            disabled_border=colors["disabled_button"],
        )
        + f"QTreeView {{ background: {colors['base']}; color: {colors['text']}; "
        f"alternate-background-color: {colors['tree_alt']}; border: 1px solid {colors['tree_border']}; "
        "padding: 0px; margin: 0px; }}"
        f"QTreeView::item {{ padding-left: 0px; margin-left: 0px; color: {colors['text']}; }}"
        f"QTreeView::item:selected {{ background: {colors['highlight']}; color: #ffffff; }}"
        f"QHeaderView::section {{ background: {colors['tree_header']}; color: {colors['text']}; "
        f"border: 1px solid {colors['tree_border']}; padding: 3px 4px 3px 0px; }}"
        f"QPushButton {{ background: {colors['button']}; color: #ffffff; border: 0; border-radius: 4px; padding: 6px 10px; }}"
        f"QPushButton:hover {{ background: {'#1e40af' if dark else '#1d4ed8'}; }}"
        f"QPushButton:disabled {{ background: {colors['disabled_button']}; color: #f8fafc; }}"
    )
