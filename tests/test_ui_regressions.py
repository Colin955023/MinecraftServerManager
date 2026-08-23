from __future__ import annotations

from typing import Any

import src.ui.core_frames.main_window as main_window_module
from src.ui import MainWindow, ServerMonitorWindow


def test_initial_server_root_cancel_closes_without_reprompt_loop(monkeypatch) -> None:
    calls: list[str] = []

    class _Settings:
        def get_servers_root(self) -> str:
            return ""

    class _Root:
        def close(self) -> None:
            calls.append("close")

    monkeypatch.setattr(main_window_module, "get_settings_manager", lambda: _Settings())
    monkeypatch.setattr(main_window_module.QtWidgets.QFileDialog, "getExistingDirectory", lambda *_args: "")
    monkeypatch.setattr(main_window_module.UIUtils, "show_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_window_module.UIUtils, "ask_yes_no_cancel", lambda *_args, **_kwargs: False)

    window: Any = MainWindow.__new__(MainWindow)
    window.root = _Root()

    assert window.set_servers_root() == ""
    assert calls == ["close"]


def test_monitor_initial_size_never_exceeds_available_screen() -> None:
    assert ServerMonitorWindow._fit_initial_size(600, 450, 1280, 720) == (1280, 720, 1280, 720)
    assert ServerMonitorWindow._fit_initial_size(1600, 1200, 1280, 720) == (1280, 720, 1280, 720)
    assert ServerMonitorWindow._fit_initial_size(600, 450, 500, 400, 1350, 900) == (500, 400, 500, 400)


def test_modal_msfluent_window_and_message_dialog_instantiation() -> None:
    from PySide6.QtWidgets import QApplication

    from src.ui.dialogs.modal_msfluent_window import MessageDialog, ModalMSFluentWindow

    _ = QApplication.instance() or QApplication([])
    modal = ModalMSFluentWindow(None, is_modal=False, show_buttons=True)
    assert modal.stackedWidget.count() >= 1
    assert modal.widget is not None
    modal.close()

    dlg = MessageDialog("標題", "訊息內容", None, question=True)
    assert dlg.stackedWidget.count() >= 1
    assert dlg.title_label.text() == "標題"
    assert dlg.content_label.text() == "訊息內容"
    dlg.close()


def test_import_and_input_dialog_centered_titles() -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from src.ui.core_frames.main_window import FluentInputDialog, ImportDialog

    _ = QApplication.instance() or QApplication([])
    import_dlg = ImportDialog(None)
    assert import_dlg.viewLayout.count() >= 2
    import_title = import_dlg.viewLayout.itemAt(0).widget()
    assert import_title.alignment() == Qt.AlignmentFlag.AlignCenter
    import_dlg.close()

    input_dlg = FluentInputDialog(None, "測試標題", "測試提示", "預設值")
    assert input_dlg.viewLayout.count() >= 2
    input_title = input_dlg.viewLayout.itemAt(0).widget()
    assert input_title.alignment() == Qt.AlignmentFlag.AlignCenter
    input_dlg.close()


def test_table_header_scroll_filter_adjusts_vbar() -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import TreeWidget

    from src.utils.ui_support.ui_config import _TABLE_HEADER_SCROLL_FILTER, apply_table_header_style

    _ = QApplication.instance() or QApplication([])
    tree = TreeWidget()
    tree.resize(500, 400)
    apply_table_header_style(tree)
    _TABLE_HEADER_SCROLL_FILTER.eventFilter(tree, QEvent(QEvent.Type.Resize))
    vbar = tree.scrollDelagate.vScrollBar
    header_h = tree.header().height() if tree.header().isVisible() else 0
    assert vbar.y() >= header_h
