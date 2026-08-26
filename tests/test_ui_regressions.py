from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import src.ui.core_frames.create_server_frame as create_server_frame_module
import src.ui.core_frames.main_window as main_window_module
from src.core import ModPlanning
from src.models import ServerConfig, ServerCreationPlan, ServerCreationWarning
from src.ui import CreateServerFrame, MainWindow, ModManagementFrame, ServerMonitorWindow


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


def test_server_creation_confirmation_renders_canonical_plan_and_requires_warning_consent(tmp_path) -> None:
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import CheckBox, LineEdit, PlainTextEdit

    from src.ui import ServerCreationConfirmDialog

    _ = QApplication.instance() or QApplication([])
    plan = ServerCreationPlan(
        transaction_id="tx",
        name="canonical-name",
        minecraft_version="1.21.1",
        loader_type="fabric",
        loader_version="0.16.0",
        memory_max_mb=2048,
        memory_min_mb=1024,
        jvm_args=("-Ddemo=true",),
        properties=(),
        final_path=tmp_path / "canonical-name",
        staging_path=tmp_path / ".staging",
        user_java_path=None,
        installer_artifact=None,
        warnings=(ServerCreationWarning("installer_checksum_missing", "checksum warning"),),
    )

    dialog = ServerCreationConfirmDialog(plan)
    field_values = {field.text() for field in dialog.findChildren(LineEdit)}
    command_text = dialog.findChild(PlainTextEdit).toPlainText()
    consent = dialog.findChild(CheckBox)

    assert dialog.plan is plan
    assert {"canonical-name", "1.21.1", "Fabric 0.16.0", "最大 2048 MB / 最小 1024 MB"} <= field_values
    assert "-Ddemo=true" in command_text
    assert "fabric-server-launch.jar" in command_text
    assert consent is not None
    assert dialog.yesButton.isEnabled() is False
    consent.setChecked(True)
    assert dialog.yesButton.isEnabled() is True
    dialog.close()


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


def test_mod_management_frame_composes_named_features_without_dynamic_host() -> None:
    from PySide6.QtWidgets import QApplication

    _ = QApplication.instance() or QApplication([])
    planning = cast(ModPlanning, SimpleNamespace())
    frame = ModManagementFrame(None, SimpleNamespace(servers={}), planning)

    assert frame.queue_ops.controller is frame
    assert frame.review_ops.controller is frame
    assert frame.install_executor.controller is frame
    assert frame.tree_sync.controller is frame
    assert frame.local_mod_list_presenter.controller is frame
    assert frame.online_browse_presenter.controller is frame
    assert "local_tree" not in frame.__dict__
    assert "browse_tree" not in frame.__dict__

    frame._ui_queue_timer.stop()
    frame.scope.cancel_all()
    frame.main_frame.close()


def test_main_window_composition_builds_one_shared_service_graph(tmp_path: Path, monkeypatch) -> None:
    events: list[str] = []

    class _CRUD:
        def __init__(self, *, servers_root: str) -> None:
            events.append("crud")
            self.servers_root = servers_root

    class _Loader:
        def __init__(self) -> None:
            events.append("loader")

    class _Inspector:
        def __init__(self) -> None:
            events.append("inspector")

    def _build_import(crud, inspector):
        events.append("import")
        return SimpleNamespace(crud=crud, inspector=inspector)

    monkeypatch.setattr(main_window_module, "ServerCRUD", _CRUD)
    monkeypatch.setattr(main_window_module, "LoaderManager", _Loader)
    monkeypatch.setattr(main_window_module, "ServerInspector", _Inspector)
    monkeypatch.setattr(main_window_module, "ModrinthPlanningAdapter", lambda: SimpleNamespace(kind="provider"))
    monkeypatch.setattr(
        main_window_module,
        "LoaderManagerRulesAdapter",
        lambda loader: SimpleNamespace(loader_manager=loader),
    )
    monkeypatch.setattr(
        main_window_module,
        "ModPlanning",
        lambda provider, rules: SimpleNamespace(provider=provider, loader_rules=rules),
    )
    monkeypatch.setattr(
        main_window_module,
        "ServerImportService",
        _build_import,
    )
    monkeypatch.setattr(
        main_window_module,
        "ServerPropertiesStore",
        lambda crud: SimpleNamespace(crud=crud),
    )
    monkeypatch.setattr(
        main_window_module,
        "ServerRuntime",
        lambda crud, *, server_inspector: SimpleNamespace(crud=crud, inspector=server_inspector),
    )
    monkeypatch.setattr(
        main_window_module,
        "ServerBackupManager",
        lambda crud, *, server_runtime=None: SimpleNamespace(crud=crud, runtime=server_runtime),
    )

    window: Any = MainWindow.__new__(MainWindow)
    window._compose_services(str(tmp_path))

    assert events == ["crud", "loader", "inspector", "import"]
    assert window.servers_root == str(tmp_path)
    assert window.server_import.crud is window.server_crud
    assert window.server_import.inspector is window.server_inspector
    assert window.server_properties.crud is window.server_crud
    assert window.server_runtime.crud is window.server_crud
    assert window.server_runtime.inspector is window.server_inspector
    assert window.server_backup.crud is window.server_crud
    assert window.server_backup.runtime is window.server_runtime
    assert window.mod_planning.loader_rules.loader_manager is window.loader_manager


def _run_server_creation_ui_flow(monkeypatch, *, plan_error: Exception | None = None, confirmed: bool = True):
    events: list[tuple[str, object]] = []
    config = ServerConfig("demo", "1.21.1", "fabric", "0.16.0", 2048, 1024)
    plan = SimpleNamespace(requires_unverified_installer_confirmation=True)

    class _Journey:
        def plan(self, received_config, *, user_java_path):
            events.append(("plan", received_config))
            assert user_java_path == "C:/Java/java.exe"
            if plan_error is not None:
                raise plan_error
            return plan

        def execute(self, received_plan, **kwargs):
            events.append(("execute", received_plan))
            assert received_plan is plan
            assert kwargs["allow_unverified_installer"] is True
            return SimpleNamespace(status="completed", completed=True, config=config)

    class _ProgressDialog:
        cancelled = False

        def __init__(self, _parent, title):
            events.append(("progress", title))

        def show(self):
            return None

        def update_progress(self, _percent, _message):
            return None

        def close(self):
            events.append(("progress_closed", ""))

    class _ConfirmDialog:
        def __init__(self, received_plan, *, parent):
            del parent
            events.append(("confirm", received_plan))
            assert received_plan is plan

        def exec(self):
            return confirmed

    class _Frame:
        server_creation = _Journey()

        @staticmethod
        def window():
            return object()

        @staticmethod
        def callback(received_config):
            events.append(("callback", received_config))

        @staticmethod
        def _schedule_ui_job(_job_attr, _delay_ms, callback):
            callback()

    monkeypatch.setattr(create_server_frame_module, "ProgressDialog", _ProgressDialog)
    monkeypatch.setattr(create_server_frame_module, "ServerCreationConfirmDialog", _ConfirmDialog)
    monkeypatch.setattr(create_server_frame_module, "run_on_ui_thread", lambda callback, **_kwargs: callback())
    monkeypatch.setattr(create_server_frame_module.UIUtils, "show_message", lambda *_args, **_kwargs: None)
    CreateServerFrame.create_server_async(_Frame(), config, "C:/Java/java.exe")
    return events, plan


def test_server_creation_ui_confirms_plan_then_executes_same_plan_once(monkeypatch) -> None:
    events, plan = _run_server_creation_ui_flow(monkeypatch)

    assert [event for event, _value in events].count("execute") == 1
    assert next(value for event, value in events if event == "confirm") is plan
    assert next(value for event, value in events if event == "execute") is plan
    assert [event for event, _value in events].index("plan") < [event for event, _value in events].index("confirm")
    assert [event for event, _value in events].index("confirm") < [event for event, _value in events].index("execute")


def test_server_creation_ui_rejection_never_executes_plan(monkeypatch) -> None:
    events, _plan = _run_server_creation_ui_flow(monkeypatch, confirmed=False)

    assert [event for event, _value in events] == ["progress", "plan", "progress_closed", "confirm"]


def test_server_creation_ui_plan_failure_never_opens_confirmation_or_executes(monkeypatch) -> None:
    events, _plan = _run_server_creation_ui_flow(monkeypatch, plan_error=ValueError("invalid plan"))
    event_names = [event for event, _value in events]

    assert "confirm" not in event_names
    assert "execute" not in event_names
    assert event_names == ["progress", "plan", "progress_closed"]


def test_server_memory_dialog_validation_and_save(tmp_path: Path, monkeypatch: Any) -> None:
    from PySide6.QtWidgets import QApplication

    from src.core import ServerCRUD
    from src.models import ServerConfig
    from src.ui import ServerMemoryDialog

    _ = QApplication.instance() or QApplication([])

    server_dir = tmp_path / "demo_srv"
    server_dir.mkdir(parents=True)
    (server_dir / "start_server.bat").write_text("java -Xmx2048M -jar server.jar\n", encoding="utf-8")

    crud = ServerCRUD(str(tmp_path))
    config = ServerConfig(
        name="demo_srv",
        minecraft_version="1.21.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        memory_min_mb=1024,
        path=str(server_dir),
    )
    crud.servers["demo_srv"] = config

    dialog = ServerMemoryDialog(config, crud)
    assert dialog.max_memory_input.text() == "2048"
    assert dialog.min_memory_input.text() == "1024"

    dialog.max_memory_input.setText("4096")
    dialog.min_memory_input.setText("2048")
    monkeypatch.setattr("src.utils.UIUtils.show_message", lambda *_args, **_kwargs: None)
    dialog._save_memory_settings()

    updated = crud.servers["demo_srv"]
    assert updated.memory_max_mb == 4096
    assert updated.memory_min_mb == 2048
    dialog.close()


def test_server_monitor_history_and_ready_logic() -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    from src.ui import ServerMonitorWindow

    _ = QApplication.instance() or QApplication([])

    class _FakeRuntime:
        @staticmethod
        def observe(_name: str):
            return SimpleNamespace(is_running=False, sequence=0, output_lines=[])

    win = ServerMonitorWindow(None, _FakeRuntime(), "demo")
    win.create_window()
    assert win._server_ready_notified is True

    win._command_history = ["list", "say hello"]
    win.command_entry.setText("")

    event_up = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
    win.eventFilter(win.command_entry, event_up)
    assert win.command_entry.text() == "say hello"

    win.eventFilter(win.command_entry, event_up)
    assert win.command_entry.text() == "list"

    event_down = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
    win.eventFilter(win.command_entry, event_down)
    assert win.command_entry.text() == "say hello"

    win.eventFilter(win.command_entry, event_down)
    assert win.command_entry.text() == ""
    win.close()


def test_server_memory_dialog_auto_clamp_to_system_memory(tmp_path: Path, monkeypatch: Any) -> None:
    from PySide6.QtWidgets import QApplication

    from src.core import ServerCRUD
    from src.models import ServerConfig
    from src.ui import ServerMemoryDialog
    from src.utils import SystemUtils

    _ = QApplication.instance() or QApplication([])

    server_dir = tmp_path / "demo_srv2"
    server_dir.mkdir(parents=True)
    (server_dir / "start_server.bat").write_text("java -Xmx2048M -jar server.jar\n", encoding="utf-8")

    crud = ServerCRUD(str(tmp_path))
    config = ServerConfig(
        name="demo_srv2",
        minecraft_version="1.21.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        memory_min_mb=1024,
        path=str(server_dir),
    )
    crud.servers["demo_srv2"] = config

    monkeypatch.setattr(SystemUtils, "get_total_memory_mb", lambda: 8192)
    warnings: list[str] = []
    monkeypatch.setattr("src.utils.UIUtils.show_message", lambda _title, msg, *_args, **_kwargs: warnings.append(msg))

    dialog = ServerMemoryDialog(config, crud)
    dialog.max_memory_input.setText("16384")
    dialog.min_memory_input.setText("10240")
    dialog._save_memory_settings()

    assert dialog.max_memory_input.text() == "8192"
    assert dialog.min_memory_input.text() == "8192"
    assert any("已自動調整為上限值" in msg for msg in warnings)
    dialog.close()


def test_server_runtime_startup_script_command_windows_spaces(monkeypatch: Any) -> None:
    from pathlib import Path

    from src.core.server.server_runtime import ServerRuntime

    monkeypatch.setattr("os.name", "nt")
    bat = Path(r"C:\Servers\Fabric 26.2\start_server.bat")
    cmd = ServerRuntime._startup_script_command(bat)
    assert cmd == ["cmd.exe", "/d", "/c", "start_server.bat"]


def test_cleanup_redundant_startup_scripts(tmp_path: Path) -> None:
    from src.utils import ServerCommands

    (tmp_path / "start_server.bat").write_text("keep", encoding="utf-8")
    (tmp_path / "run.bat").write_text("delete", encoding="utf-8")
    (tmp_path / "run.sh").write_text("delete", encoding="utf-8")
    (tmp_path / "custom_launch.ps1").write_text("java -Xmx4G -jar server.jar nogui", encoding="utf-8")
    (tmp_path / "backup.ps1").write_text("Compress-Archive -Path . -DestinationPath backup.zip", encoding="utf-8")
    (tmp_path / "maintenance.sh").write_text("echo 'performing maintenance'", encoding="utf-8")

    removed = ServerCommands.cleanup_redundant_startup_scripts(tmp_path)
    assert set(removed) == {"run.bat", "run.sh", "custom_launch.ps1"}
    assert (tmp_path / "start_server.bat").exists()
    assert not (tmp_path / "run.bat").exists()
    assert not (tmp_path / "run.sh").exists()
    assert not (tmp_path / "custom_launch.ps1").exists()
    assert (tmp_path / "backup.ps1").exists()
    assert (tmp_path / "maintenance.sh").exists()


def test_find_loader_args_from_run_bat(tmp_path: Path) -> None:
    from src.core import ServerInspector

    libs_dir = tmp_path / "libraries" / "net" / "minecraftforge" / "forge" / "1.20.1-47.3.0"
    libs_dir.mkdir(parents=True)
    win_args = libs_dir / "win_args.txt"
    win_args.write_text("-Xmx2G", encoding="utf-8")

    (tmp_path / "run.bat").write_text(
        r"java @user_jvm_args.txt @libraries/net/minecraftforge/forge/1.20.1-47.3.0/win_args.txt %*",
        encoding="utf-8",
    )

    detected = ServerInspector.find_main_jar(tmp_path, "forge")
    assert detected == "@libraries/net/minecraftforge/forge/1.20.1-47.3.0/win_args.txt"


def test_server_memory_dialog_realtime_warning(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from src.core import ServerCRUD
    from src.models import ServerConfig
    from src.ui import ServerMemoryDialog

    _ = QApplication.instance() or QApplication([])
    server_dir = tmp_path / "srv"
    server_dir.mkdir()
    crud = ServerCRUD(str(tmp_path))
    config = ServerConfig(
        name="srv",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(server_dir),
    )
    crud.servers["srv"] = config

    dialog = ServerMemoryDialog(config, crud)
    assert dialog.memory_warning_label.text() == ""

    dialog.max_memory_input.setText("512")
    assert "不可低於 1024" in dialog.memory_warning_label.text()

    dialog.max_memory_input.setText("4096")
    dialog.min_memory_input.setText("8192")
    assert "最小記憶體必須小於或等於最大記憶體" in dialog.memory_warning_label.text()
    dialog.close()


def test_build_java_command_forge_with_user_jvm_args(tmp_path: Path) -> None:
    from src.models import ServerConfig
    from src.utils import ServerCommands

    server_dir = tmp_path / "forge_srv"
    server_dir.mkdir()
    (server_dir / "user_jvm_args.txt").write_text("# user args\n", encoding="utf-8")

    config = ServerConfig(
        name="forge_srv",
        minecraft_version="26.2",
        loader_type="forge",
        loader_version="26.2-65.1.2",
        memory_max_mb=4096,
        path=str(server_dir),
    )
    cmd = ServerCommands.build_java_command(
        config,
        return_list=False,
        launch_target="@libraries/net/minecraftforge/forge/26.2-65.1.2/win_args.txt",
    )
    assert "-Xmx4096M" in cmd
    assert "@libraries/net/minecraftforge/forge/26.2-65.1.2/win_args.txt" in cmd
    assert cmd.endswith("nogui")
    user_args_content = (server_dir / "user_jvm_args.txt").read_text(encoding="utf-8")
    assert "-Xmx4096M" in user_args_content
