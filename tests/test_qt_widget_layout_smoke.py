from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtGui
from src.ui import DialogUtils
from src.ui.task_utils import TaskUtils
from src.ui.ui_config import NativeQtStyle, initialize_ui_theme
from src.utils import UIUtils
from src.utils.ui_support import qt_widgets as qt
from src.utils.ui_support.qt_runtime import QtCore, QtWidgets
from src.utils.ui_support.ui_tokens import Colors, Sizes
from src.utils.ui_support.ui_utils import get_button_style


def test_qt_wrapper_attach_creates_layout_for_native_parent() -> None:
    qt.ensure_app()
    dialog = QtWidgets.QDialog()
    try:
        frame = qt.Frame(dialog)
        frame.attach(fill="both", expand=True)

        layout = dialog.layout()
        assert layout is not None
        assert layout.count() == 1
        item = layout.itemAt(0)
        assert item is not None
        assert item.widget() is frame
    finally:
        dialog.deleteLater()


def test_pack_main_frame_attaches_qt_frame_to_native_parent() -> None:
    qt.ensure_app()
    dialog = QtWidgets.QDialog()
    try:
        frame = qt.Frame(dialog)
        UIUtils.pack_main_frame(frame, padx=10, pady=11)

        layout = dialog.layout()
        margins = frame.contentsMargins()
        assert layout is not None
        assert layout.count() == 1
        item = layout.itemAt(0)
        assert item is not None
        assert item.widget() is frame
        assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (10, 11, 10, 11)
    finally:
        dialog.deleteLater()


def test_layout_resize_lock_uses_qt_size_limits_and_restores_them() -> None:
    qt.ensure_app()
    frame = qt.Frame(None, height=30)
    try:
        original_min = frame.minimumSize()
        original_max = frame.maximumSize()

        frame.set_box_layout_propagation(False)
        assert frame.minimumHeight() == 30
        assert frame.maximumHeight() == 30

        frame.set_box_layout_propagation(True)
        assert frame.minimumSize() == original_min
        assert frame.maximumSize() == original_max
    finally:
        frame.deleteLater()


def test_textbox_min_height_keeps_preview_expandable() -> None:
    qt.ensure_app()
    text_box = qt.TextBox(None, min_height=225, wrap="word")
    try:
        assert text_box.minimumHeight() == 225
        assert text_box.maximumHeight() > text_box.minimumHeight()
    finally:
        text_box.deleteLater()


def test_checkbox_state_tracks_bound_variable_in_both_directions() -> None:
    qt.ensure_app()
    variable = qt.BoolState(True)
    checkbox = qt.CheckBox(None, text="測試", variable=variable)
    try:
        assert checkbox.isChecked() is True

        checkbox.setChecked(False)
        assert variable.get() is False

        variable.set(True)
        assert checkbox.isChecked() is True
    finally:
        checkbox.deleteLater()


def test_progress_bar_shows_percentage_text_by_default() -> None:
    qt.ensure_app()
    progress_bar = qt.ProgressBar(None)
    try:
        assert progress_bar.isTextVisible() is True
        assert progress_bar.format() == "%p%"
        assert progress_bar.text() == "0%"
        progress_bar.set(0.25)
        assert progress_bar.value() == 25
        assert progress_bar.text() == "25%"
    finally:
        progress_bar.deleteLater()


def test_progress_bar_renders_text_when_visibility_enabled() -> None:
    app = qt.ensure_app()
    progress_bar = qt.ProgressBar(None)
    try:
        progress_bar.resize(220, 28)
        progress_bar.set(0.25)
        app.processEvents()

        def _render_snapshot(text_visible: bool) -> QtGui.QImage:
            progress_bar.setTextVisible(text_visible)
            image = QtGui.QImage(progress_bar.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QtGui.QColor(0, 0, 0, 0))
            painter = QtGui.QPainter(image)
            try:
                progress_bar.render(painter, QtCore.QPoint(0, 0))
            finally:
                painter.end()
            return image

        hidden_image = _render_snapshot(False)
        visible_image = _render_snapshot(True)
        sample_points = [
            (x, y)
            for x in range(progress_bar.width() // 2 - 24, progress_bar.width() // 2 + 24, 4)
            for y in range(progress_bar.height() // 2 - 6, progress_bar.height() // 2 + 6, 2)
        ]
        assert any(hidden_image.pixelColor(x, y) != visible_image.pixelColor(x, y) for x, y in sample_points)
    finally:
        progress_bar.deleteLater()


def test_slider_state_tracks_bound_variable_in_both_directions() -> None:
    qt.ensure_app()
    variable = qt.FloatState(1.25)
    slider = qt.Slider(None, from_=0.5, to=3.0, variable=variable)
    try:
        assert slider.get() == 1.25

        slider.set(1.75)
        assert variable.get() == 1.75

        variable.set(2.0)
        assert slider.get() == 2.0
    finally:
        slider.deleteLater()


def test_treeview_extended_selection_accepts_multiple_ids() -> None:
    qt.ensure_app()
    tree = qt.Treeview(None, columns=("name",), selectmode="extended")
    try:
        first = tree.insert("", "end", iid="first", values=("A",))
        second = tree.insert("", "end", iid="second", values=("B",))

        tree.selection_set(first, second)

        assert set(tree.selection()) == {"first", "second"}
    finally:
        tree.deleteLater()


def test_treeview_uses_left_aligned_native_qt_rows_and_tag_styles() -> None:
    qt.ensure_app()
    tree = qt.Treeview(None, columns=("status", "name"), selectmode="extended")
    try:
        tree.tag_configure("odd", background="#f1f5f9", foreground="#0f172a")
        item_id = tree.insert("", "end", iid="first", values=("已啟用", "demo"), tags=("odd",))
        item = tree._items[item_id]

        assert tree.indentation() == 0
        assert tree.rootIsDecorated() is False
        assert item.textAlignment(0) & QtCore.Qt.AlignmentFlag.AlignLeft
        assert item.background(0).color().name() == "#f1f5f9"
        assert item.foreground(0).color().name() == "#0f172a"
    finally:
        tree.deleteLater()


def test_task_utils_call_on_ui_rejects_non_qt_parent() -> None:
    qt.ensure_app()
    try:
        TaskUtils.call_on_ui(object(), lambda: None)
    except TypeError as exc:
        assert "Qt QObject" in str(exc)
    else:
        raise AssertionError("TaskUtils.call_on_ui should reject non-Qt parents")


def test_button_command_ignores_qt_checked_argument() -> None:
    qt.ensure_app()
    received: list[str] = []
    button = qt.Button(None, text="匯入", command=lambda value="folder": received.append(value))
    try:
        button._invoke_command(False)

        assert received == ["folder"]
    finally:
        button.deleteLater()


def test_search_entry_binds_text_state_and_filter_logic() -> None:
    qt.ensure_app()
    variable = qt.TextState()
    search = qt.SearchEntry(None, textvariable=variable, filter_logic=qt.SearchFilter())
    try:
        search.setText("  Sodium   Mod  ")

        assert variable.get() == "  Sodium   Mod  "
        assert search.filter_text() == "sodium mod"
        assert search.matches("Install Sodium Mod")
        assert search.matches({"name": "Sodium", "summary": "Rendering mod"})
        assert not search.matches({"name": "Sodium", "summary": "Performance"})

        variable.set("Lithium")
        assert search.text() == "Lithium"
    finally:
        search.deleteLater()


def test_dialog_utils_creates_resizable_dialog_with_standard_window_controls() -> None:
    qt.ensure_app()
    dialog = DialogUtils.create_toplevel_dialog(
        None,
        "測試視窗控制",
        bind_icon=False,
        make_modal=False,
        reveal_after_setup=False,
    )
    try:
        flags = dialog.windowFlags()
        assert flags & QtCore.Qt.WindowType.WindowMinimizeButtonHint
        assert flags & QtCore.Qt.WindowType.WindowMaximizeButtonHint
        assert flags & QtCore.Qt.WindowType.WindowCloseButtonHint
    finally:
        dialog.destroy()


def test_dialog_utils_applies_distinct_button_and_input_styles() -> None:
    qt.ensure_app()
    initialize_ui_theme("light")
    dialog = DialogUtils.create_toplevel_dialog(
        None,
        "測試視窗樣式",
        bind_icon=False,
        make_modal=False,
        reveal_after_setup=False,
    )
    try:
        stylesheet = dialog.styleSheet()
        assert "QPushButton" in stylesheet
        assert "QLineEdit" in stylesheet
        assert "QComboBox" in stylesheet
        assert "background: #f8fafc" in stylesheet
        assert "background: #ffffff" in stylesheet
        assert "background: #2563eb" in stylesheet
        assert "QCheckBox::indicator" in stylesheet
        assert "QCheckBox::indicator:checked" in stylesheet
        assert "QCheckBox::indicator:unchecked" in stylesheet
    finally:
        dialog.destroy()


def test_native_dialog_styles_keep_controls_distinct_from_dialog_background() -> None:
    qt.ensure_app()
    initialize_ui_theme("light")

    for stylesheet in (
        NativeQtStyle.about_dialog,
        NativeQtStyle.progress_dialog,
        NativeQtStyle.preferences_dialog,
        NativeQtStyle.server_properties_dialog,
        NativeQtStyle.message_box,
    ):
        assert "QPushButton" in stylesheet
        assert "QLineEdit" in stylesheet
        assert "QComboBox" in stylesheet
        assert "background: #f8fafc" in stylesheet
        assert "background: #ffffff" in stylesheet
        assert "background: #2563eb" in stylesheet
        assert "QCheckBox::indicator" in stylesheet
        assert "QCheckBox::indicator:unchecked" in stylesheet


def test_get_button_style_has_secondary_button_color() -> None:
    assert get_button_style("secondary")["fg_color"] == Colors.BUTTON_SECONDARY


def test_server_property_text_input_width_is_one_and_half_dropdown_width() -> None:
    assert int(Sizes.DROPDOWN_WIDTH * 1.5) == Sizes.SERVER_PROPERTY_TEXT_INPUT_WIDTH
