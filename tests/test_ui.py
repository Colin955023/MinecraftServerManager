from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import src.ui.core_frames.create_server_frame as create_server_frame_module
import src.ui.core_frames.main_window as main_window_module
from src.core import ModPlanning, ServerConfigChangeSet
from src.core.server.server_creation import ServerCreationConfirmation
from src.models import ProgressEvent, ServerConfig, ServerCreationPlan
from src.ui import MainWindow, ModManagementFrame, ServerMonitorWindow
from src.ui.core_frames.create_server_frame import CreateServerFrame


def _register(manager: Any, config: ServerConfig) -> None:
    baseline = manager.snapshot()
    result = manager.commit(ServerConfigChangeSet(upserts=(config,)), expected_revision=baseline.revision)
    assert result.success, result.message


def test_initial_server_root_cancel_closes_without_reprompt_loop(monkeypatch) -> None:
    calls: list[str] = []

    class _Settings:
        def get_servers_root(self) -> str:
            return ""

    class _Root:
        def close(self) -> None:
            calls.append("close")

    monkeypatch.setattr(main_window_module.QtWidgets.QFileDialog, "getExistingDirectory", lambda *_args: "")
    monkeypatch.setattr(main_window_module.UIUtils, "show_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_window_module.UIUtils, "ask_yes_no_cancel", lambda *_args, **_kwargs: False)

    window: Any = MainWindow.__new__(MainWindow)
    window.root = _Root()
    window.settings = _Settings()

    assert window.set_servers_root() == ""
    assert calls == ["close"]


def test_monitor_initial_size_never_exceeds_available_screen() -> None:
    assert ServerMonitorWindow._fit_initial_size(600, 450, 1280, 720) == (1280, 720, 1280, 720)
    assert ServerMonitorWindow._fit_initial_size(1600, 1200, 1280, 720) == (1280, 720, 1280, 720)
    assert ServerMonitorWindow._fit_initial_size(600, 450, 500, 400, 1350, 900) == (500, 400, 500, 400)


def test_modal_msfluent_window_and_message_dialog_instantiation() -> None:
    from PySide6.QtCore import Qt
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
    assert dlg.content_label.textFormat() == Qt.TextFormat.PlainText
    dlg.close()


def test_server_property_sensitive_fields_use_password_echo() -> None:
    from PySide6.QtWidgets import QApplication, QWidget
    from qfluentwidgets import LineEdit

    from src.ui import ServerPropertiesDialog, TextState

    _ = QApplication.instance() or QApplication([])
    parent = QWidget()
    dialog_policy = SimpleNamespace(
        SENSITIVE_PROPS=ServerPropertiesDialog.SENSITIVE_PROPS,
        CHOICE_PROPS={},
        RANGE_PROPS={},
        _should_use_checkbox=lambda *_args: False,
    )

    for prop_name in ServerPropertiesDialog.SENSITIVE_PROPS:
        widget = ServerPropertiesDialog.create_property_widget(
            cast(Any, dialog_policy),
            parent,
            prop_name,
            TextState("secret"),
        )
        assert isinstance(widget, LineEdit)
        assert widget.echoMode() == LineEdit.EchoMode.Password

    ordinary = ServerPropertiesDialog.create_property_widget(
        cast(Any, dialog_policy),
        parent,
        "motd",
        TextState("hello"),
    )
    assert ordinary.echoMode() == LineEdit.EchoMode.Normal
    parent.close()


def test_server_creation_confirmation_renders_canonical_plan(tmp_path) -> None:
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import LineEdit, PlainTextEdit

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
        warnings=(),
        confirmation=ServerCreationConfirmation(
            name="canonical-name",
            minecraft_version="1.21.1",
            loader_type="fabric",
            loader_version="0.16.0",
            memory_max_mb=2048,
            memory_min_mb=1024,
            warnings=(),
            java_executable="java",
            jvm_args=("-Ddemo=true",),
            launch_target="fabric-server-launch.jar",
            command=("java", "-Ddemo=true", "-jar", "fabric-server-launch.jar"),
        ),
    )

    dialog = ServerCreationConfirmDialog(plan)
    field_values = {field.text() for field in dialog.findChildren(LineEdit)}
    command_text = dialog.findChild(PlainTextEdit).toPlainText()
    assert dialog.plan is plan
    assert {"canonical-name", "1.21.1", "Fabric 0.16.0", "最大 2048 MB / 最小 1024 MB"} <= field_values
    assert "-Ddemo=true" in command_text
    assert "fabric-server-launch.jar" in command_text
    assert dialog.yesButton.isEnabled() is True
    dialog.close()


def test_import_and_input_dialog_centered_titles() -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel

    from src.ui.dialogs.main_window_dialogs import FluentInputDialog, ImportDialog

    _ = QApplication.instance() or QApplication([])
    import_dlg = ImportDialog(None)
    assert import_dlg.viewLayout.count() >= 2
    import_title_item = import_dlg.viewLayout.itemAt(0)
    assert import_title_item is not None
    import_title = import_title_item.widget()
    assert isinstance(import_title, QLabel)
    assert import_title.alignment() == Qt.AlignmentFlag.AlignCenter
    import_dlg.close()

    input_dlg = FluentInputDialog(None, "測試標題", "測試提示", "預設值")
    assert input_dlg.viewLayout.count() >= 2
    input_title_item = input_dlg.viewLayout.itemAt(0)
    assert input_title_item is not None
    input_title = input_title_item.widget()
    assert isinstance(input_title, QLabel)
    assert input_title.alignment() == Qt.AlignmentFlag.AlignCenter
    input_dlg.close()


def test_table_header_scroll_filter_adjusts_vbar() -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import TreeWidget

    from src.ui.support.ui_config import _TableHeaderScrollFilter, apply_table_header_style

    _ = QApplication.instance() or QApplication([])
    tree = TreeWidget()
    tree.resize(500, 400)
    apply_table_header_style(tree)
    filter = _TableHeaderScrollFilter()
    filter.eventFilter(tree, QEvent(QEvent.Type.Resize))
    vbar = tree.scrollDelagate.vScrollBar
    header_h = tree.header().height() if tree.header().isVisible() else 0
    assert vbar.y() >= header_h


def test_mod_management_frame_composes_named_features_without_dynamic_host() -> None:
    from PySide6.QtWidgets import QApplication

    _ = QApplication.instance() or QApplication([])
    planning = cast(ModPlanning, SimpleNamespace())
    frame = ModManagementFrame(None, SimpleNamespace(snapshot=lambda: ()), planning, SimpleNamespace())

    assert frame.queue_ops.controller is frame.feature_context
    assert frame.review_ops.controller is frame.feature_context
    assert frame.install_executor.controller is frame.feature_context
    assert frame.tree_sync.controller is frame.feature_context
    assert frame.local_mod_list_presenter.controller is frame.feature_context
    assert frame.online_browse_presenter.controller is frame.feature_context
    assert "local_tree" not in frame.__dict__
    assert "browse_tree" not in frame.__dict__

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
    monkeypatch.setattr(main_window_module, "ModrinthHttpAdapter", lambda: SimpleNamespace(kind="provider"))
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
    plan = SimpleNamespace()

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
            assert callable(kwargs["progress_callback"])
            assert callable(kwargs["cancel_check"])
            return SimpleNamespace(status="completed", completed=True, config=config)

    class _ProgressDialog:
        cancelled = False

        def __init__(self, _parent, title):
            events.append(("progress", title))

        def show(self):
            return None

        def update_progress(self, _percent, _message):
            return None

        def update_progress_event(self, _event):
            return None

        def close(self):
            events.append(("progress_closed", ""))

    class _ConfirmDialog:
        def __init__(self, received_plan, **_kwargs):
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
    CreateServerFrame.create_server_async(cast(Any, _Frame()), config, "C:/Java/java.exe")
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
    _register(crud, config)

    dialog = ServerMemoryDialog(config, crud)
    assert dialog.max_memory_input.text() == "2048"
    assert dialog.min_memory_input.text() == "1024"

    dialog.max_memory_input.setText("4096")
    dialog.min_memory_input.setText("2048")
    monkeypatch.setattr("src.ui.UIUtils.show_message", lambda *_args, **_kwargs: None)
    dialog._save_memory_settings()
    deadline = time.monotonic() + 2
    while not dialog.save_btn.isEnabled() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)

    updated = crud.snapshot().get("demo_srv")
    assert updated is not None
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
    _register(crud, config)

    monkeypatch.setattr(SystemUtils, "get_total_memory_mb", lambda: 8192)
    warnings: list[str] = []
    monkeypatch.setattr("src.ui.UIUtils.show_message", lambda _title, msg, *_args, **_kwargs: warnings.append(msg))

    dialog = ServerMemoryDialog(config, crud)
    dialog.max_memory_input.setText("16384")
    dialog.min_memory_input.setText("10240")
    dialog._save_memory_settings()
    deadline = time.monotonic() + 2
    while not dialog.save_btn.isEnabled() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)

    assert dialog.max_memory_input.text() == "8192"
    assert dialog.min_memory_input.text() == "8192"
    assert any("已自動調整為上限值" in msg for msg in warnings)
    dialog.close()


def test_server_runtime_does_not_execute_startup_scripts_via_cmd() -> None:
    from src.core.server.server_runtime import ServerRuntime

    assert not hasattr(ServerRuntime, "_startup_script_command")


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
    _register(crud, config)

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


def test_progress_dialog_does_not_clear_after_determinate_progress() -> None:
    from PySide6.QtWidgets import QApplication

    from src.ui import ProgressDialog

    _ = QApplication.instance() or QApplication([])
    dialog = ProgressDialog(None, show_cancel=False)
    dialog._apply_progress_event(ProgressEvent("download", "下載中", 45, 100))
    assert dialog.progress.minimum() == 0
    assert dialog.progress.maximum() == 100
    assert dialog.progress.value() == 45

    dialog._apply_progress_event(ProgressEvent("installer", "安裝器正在處理文字階段"))
    assert dialog.progress.minimum() == 0
    assert dialog.progress.maximum() == 100
    assert dialog.progress.value() == 45
    dialog.close()


def test_progress_dialog_direct_update_restores_determinate_mode_and_does_not_regress() -> None:
    from PySide6.QtWidgets import QApplication

    from src.ui import ProgressDialog

    _ = QApplication.instance() or QApplication([])
    dialog = ProgressDialog(None, show_cancel=False)
    dialog._apply_progress_event(ProgressEvent("installer", "等待 installer 輸出"))
    assert dialog.progress.minimum() == 0
    assert dialog.progress.maximum() == 0

    dialog._apply_progress_update(60, "已取得整體進度")
    assert dialog.progress.minimum() == 0
    assert dialog.progress.maximum() == 100
    assert dialog.progress.value() == 60

    dialog._apply_progress_update(40, "較舊的延遲更新")
    assert dialog.progress.value() == 60
    dialog.close()


def test_themed_surface_stylesheet_has_contrasting_light_and_dark_tokens(monkeypatch) -> None:
    import src.ui.support.ui_config as ui_config

    monkeypatch.setattr(ui_config, "isDarkTheme", lambda: False)
    light = ui_config.themed_surface_stylesheet("Surface")
    monkeypatch.setattr(ui_config, "isDarkTheme", lambda: True)
    dark = ui_config.themed_surface_stylesheet("Surface")

    assert "background-color: #ffffff" in light
    assert "color: #1f2937" in light
    assert "background-color: #1e1e1e" in dark
    assert "color: #e5e7eb" in dark


def test_apply_window_icon_updates_qt_window_and_fluent_title_bar() -> None:
    from PySide6.QtWidgets import QWidget

    from src.ui import apply_window_icon, ensure_application

    app = ensure_application()
    assert not app.windowIcon().isNull()
    received: list[Any] = []
    window: Any = QWidget()
    window.titleBar = SimpleNamespace(setIcon=received.append)

    apply_window_icon(window)

    assert not window.windowIcon().isNull()
    assert received and not received[0].isNull()
    window.close()


def test_delete_server_dialog_options_and_decisions() -> None:
    """
    驗證 DeleteServerDialog 在有備份與無備份情境下的介面元件與決策狀態
    """
    from src.ui import DeleteServerDialog, ensure_application

    ensure_application()

    # 有備份情境
    dialog_with_backups = DeleteServerDialog("TestServer", 3)
    assert dialog_with_backups.cancel_btn.text() == "取消"
    assert dialog_with_backups.no_btn.text() == "否（只刪除伺服器）"
    assert dialog_with_backups.yes_btn.text() == "是（連備份一併刪除）"
    assert "3 個外部備份檔案" in dialog_with_backups.content_label.text()

    dialog_with_backups._choose_all()
    assert dialog_with_backups.decision == "all"
    dialog_with_backups._choose_server_only()
    assert dialog_with_backups.decision == "server_only"
    dialog_with_backups._choose_cancel()
    assert dialog_with_backups.decision == "cancel"
    dialog_with_backups.close()

    # 無備份情境
    dialog_no_backups = DeleteServerDialog("TestServer", 0)
    assert dialog_no_backups.cancel_btn.text() == "取消"
    assert dialog_no_backups.confirm_btn.text() == "確定刪除"
    assert "外部備份檔案" not in dialog_no_backups.content_label.text()

    dialog_no_backups._choose_server_only()
    assert dialog_no_backups.decision == "server_only"
    dialog_no_backups._choose_cancel()
    assert dialog_no_backups.decision == "cancel"
    dialog_no_backups.close()


def test_server_memory_dialog_shows_and_persists_backup_path(tmp_path: Path, monkeypatch) -> None:
    """
    驗證 ServerMemoryDialog 介面包含備份路徑欄位並在儲存時寫入設定
    """

    from src.core import ServerCRUD
    from src.models import ServerConfig
    from src.ui import ServerMemoryDialog, WorkOutcome, ensure_application

    ensure_application()
    servers_root = tmp_path / "servers_root"
    servers_root.mkdir()
    server_dir = servers_root / "Demo"
    server_dir.mkdir()
    (server_dir / "start_server.bat").write_text("java -Xmx2048M -jar server.jar\n", encoding="utf-8")
    backup_dir = tmp_path / "my_backups"
    backup_dir.mkdir()

    crud = ServerCRUD(str(servers_root))
    config = ServerConfig(
        name="Demo",
        minecraft_version="1.20.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(server_dir),
        backup_path="",
    )
    _register(crud, config)

    dialog = ServerMemoryDialog(config, crud)
    assert hasattr(dialog, "backup_path_input")
    assert dialog.backup_path_input.text() == ""

    # 同步執行以避免背景執行緒與測試目錄清理競爭
    def _sync_submit(task, on_done=None, **_kwargs):
        res = task()
        if on_done:
            on_done(WorkOutcome.succeeded(res))

    dialog.scope.submit = _sync_submit

    dialog.backup_path_input.setText(str(backup_dir))
    monkeypatch.setattr("src.ui.UIUtils.show_message", lambda *_args, **_kwargs: None)

    dialog._save_memory_settings()

    updated = crud.snapshot().get("Demo")
    assert updated is not None
    assert updated.backup_path == str(backup_dir)
    dialog.close()
