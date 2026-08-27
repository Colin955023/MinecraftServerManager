from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any, cast

from src.models import ServerConfig
from src.ui import ManageServerFrame, ManageServerService
from src.utils import WorkOutcome


class _DummyFrame:
    def __init__(self):
        self.server_tree: Any = None
        self.service: Any = None
        self.selected_server: str = ""
        self._monitor_windows: dict[str, Any] = {}
        self.server_crud: Any = None
        self.server_runtime: Any = None
        self.action_buttons: dict[str, Any] = {}
        self.info_label: Any = None

    def _show_existing_monitor_window(self, win, bring_to_front=True):
        target = getattr(win, "window", win)
        if bring_to_front:
            target.show()
            target.raise_()
            target.activateWindow()
            target.setFocus()
        else:
            target.show()


class FakeMonitorWindow:
    def __init__(self) -> None:
        self.show_calls = 0
        self.raise_calls = 0
        self.activate_calls = 0
        self.focus_calls = 0

    def is_alive(self) -> bool:
        return True

    def show(self) -> None:
        self.show_calls += 1

    def raise_(self) -> None:
        self.raise_calls += 1

    def activateWindow(self) -> None:
        self.activate_calls += 1

    def setFocus(self) -> None:
        self.focus_calls += 1


def _manage_service(server_crud: Any, *, server_backup: Any | None = None) -> ManageServerService:
    runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=False))
    backup = server_backup or SimpleNamespace(list_backups=lambda _name: [])
    inspector = SimpleNamespace(inspect=lambda *_args, **_kwargs: None)
    return ManageServerService(
        server_crud,
        cast(Any, runtime),
        backup,
        cast(Any, inspector),
    )


def test_build_server_tree_payload_skips_empty_rows_and_preserves_order() -> None:
    server_data = [
        ["Alpha", "1.21", "Fabric", "運行中", "0 B", "已備份", "servers\\Alpha"],
        [],
        ["Beta", "1.20.6", "Forge", "已停止", "0 B", "未備份", "servers\\Beta"],
    ]

    server_order, server_rows = ManageServerService._build_server_tree_payload(server_data)

    assert server_order == ["Alpha", "Beta"]
    assert server_rows["Alpha"] == tuple(server_data[0])
    assert server_rows["Beta"] == tuple(server_data[2])


def test_build_server_tree_payload_last_duplicate_name_wins_values() -> None:
    server_data = [
        ["Alpha", "1.21", "Fabric", "運行中", "0 B", "已備份", "servers\\Alpha"],
        ["Alpha", "1.21.1", "Fabric", "已停止", "0 B", "未備份", "servers\\Alpha"],
    ]

    server_order, server_rows = ManageServerService._build_server_tree_payload(server_data)

    assert server_order == ["Alpha", "Alpha"]
    assert server_rows["Alpha"] == tuple(server_data[1])


def test_build_server_refresh_payload_combines_signature_order_and_rows() -> None:
    server_data = [
        ["Alpha", "1.21", "Fabric", "運行中", "0 B", "已備份", "servers\\Alpha"],
        ["Beta", "1.20.6", "Forge", "已停止", "0 B", "未備份", "servers\\Beta"],
    ]

    payload = ManageServerService._build_server_refresh_payload(server_data)

    assert payload.signature == (
        ("Alpha", tuple(server_data[0])),
        ("Beta", tuple(server_data[1])),
    )
    assert payload.server_order == ["Alpha", "Beta"]
    assert payload.server_rows == {
        "Alpha": tuple(server_data[0]),
        "Beta": tuple(server_data[1]),
    }


def test_monitor_server_reuses_existing_window_for_user_click_and_brings_to_front() -> None:
    frame = _DummyFrame()
    frame.selected_server = "Alpha"
    fake_window = FakeMonitorWindow()
    frame._monitor_windows = {"Alpha": SimpleNamespace(window=fake_window)}

    ManageServerFrame.monitor_server(cast(Any, frame))

    assert fake_window.show_calls == 1
    assert fake_window.raise_calls == 1
    assert fake_window.activate_calls == 1
    assert fake_window.focus_calls == 1


def test_monitor_server_auto_reuses_existing_window_without_forcing_focus() -> None:
    frame = _DummyFrame()
    frame.selected_server = "Alpha"
    fake_window = FakeMonitorWindow()
    frame._monitor_windows = {"Alpha": SimpleNamespace(window=fake_window)}

    ManageServerFrame.monitor_server(cast(Any, frame), bring_to_front=False)

    assert fake_window.show_calls == 1
    assert fake_window.raise_calls == 0
    assert fake_window.activate_calls == 0
    assert fake_window.focus_calls == 0


def test_build_server_display_row_formats_unknown_mc_version_with_loader_version() -> None:
    config = ServerConfig(
        name="Alpha",
        minecraft_version="unknown",
        loader_type="fabric",
        loader_version="0.16.10",
        memory_max_mb=4096,
        path="servers\\Alpha",
    )

    row = ManageServerService._build_server_display_row(
        name="Alpha",
        config=config,
        status="已停止",
        backup_status="未備份",
        server_size="0 B",
        display_path="servers\\Alpha",
    )

    assert row == ["Alpha", "未知", "Fabric v0.16.10", "已停止", "0 B", "未備份", "servers\\Alpha"]


def test_build_server_display_row_formats_vanilla_loader() -> None:
    config = ServerConfig(
        name="Beta",
        minecraft_version="1.21.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path="servers\\Beta",
    )

    row = ManageServerService._build_server_display_row(
        name="Beta",
        config=config,
        status="運行中",
        backup_status="已備份",
        server_size="0 B",
        display_path="servers\\Beta",
    )

    assert row == ["Beta", "1.21.1", "1.21.1", "運行中", "0 B", "已備份", "servers\\Beta"]


def test_server_size_counts_all_files_and_is_recomputed_on_refresh(tmp_path) -> None:
    server_path = tmp_path / "Alpha"
    (server_path / "world" / "region").mkdir(parents=True)
    (server_path / "logs").mkdir()
    (server_path / "world" / "region" / "r.0.0.mca").write_bytes(b"12345")
    (server_path / "server.properties").write_bytes(b"123")

    assert ManageServerService._get_server_size(str(server_path)) == "8 B"

    (server_path / "logs" / "latest.log").write_bytes(b"6789")
    assert ManageServerService._get_server_size(str(server_path)) == "12 B"


def test_begin_refresh_returns_monotonic_generation() -> None:
    fake_crud = SimpleNamespace(servers={}, load_servers_config=lambda: None)
    service = _manage_service(fake_crud)

    gen1 = service.begin_refresh()
    gen2 = service.begin_refresh()
    gen3 = service.begin_refresh()

    assert gen1 < gen2 < gen3


def test_accept_projection_rejects_stale_generation() -> None:
    fake_crud = SimpleNamespace(servers={})
    service = _manage_service(fake_crud)

    gen1 = service.begin_refresh()
    gen2 = service.begin_refresh()

    payload = ManageServerService._build_server_refresh_payload(
        [["Alpha", "1.21", "Fabric", "運行中", "0 B", "已備份", "servers\\Alpha"]]
    )

    assert service.accept_projection(gen1, payload, "Alpha") is None
    plan = service.accept_projection(gen2, payload, "Alpha")
    assert plan is not None
    assert plan.has_changes is True
    assert plan.projection.generation == gen2


def test_accept_projection_returns_no_changes_when_unchanged() -> None:
    fake_crud = SimpleNamespace(servers={})
    service = _manage_service(fake_crud)

    gen1 = service.begin_refresh()
    payload = ManageServerService._build_server_refresh_payload(
        [["Alpha", "1.21", "Fabric", "運行中", "0 B", "已備份", "servers\\Alpha"]]
    )

    plan1 = service.accept_projection(gen1, payload, "Alpha")
    assert plan1 is not None
    assert plan1.has_changes is True

    gen2 = service.begin_refresh()
    plan2 = service.accept_projection(gen2, payload, "Alpha")
    assert plan2 is not None
    assert plan2.has_changes is False


def test_accept_projection_retains_selection_when_present() -> None:
    fake_crud = SimpleNamespace(servers={})
    service = _manage_service(fake_crud)

    gen = service.begin_refresh()
    payload = ManageServerService._build_server_refresh_payload(
        [
            ["Alpha", "1.21", "Fabric", "運行中", "0 B", "已備份", "servers\\Alpha"],
            ["Beta", "1.20.6", "Forge", "已停止", "0 B", "未備份", "servers\\Beta"],
        ]
    )

    plan = service.accept_projection(gen, payload, "Beta")
    assert plan is not None
    assert plan.projection.selected_server == "Beta"


def test_accept_projection_clears_selection_when_deleted() -> None:
    fake_crud = SimpleNamespace(servers={})
    service = _manage_service(fake_crud)

    gen = service.begin_refresh()
    payload = ManageServerService._build_server_refresh_payload(
        [["Alpha", "1.21", "Fabric", "運行中", "0 B", "已備份", "servers\\Alpha"]]
    )

    plan = service.accept_projection(gen, payload, "DeletedServer")
    assert plan is not None
    assert plan.projection.selected_server is None


def test_get_backup_status_uses_injected_backup_manager() -> None:
    fake_crud = SimpleNamespace(
        servers={
            "Alpha": ServerConfig(
                name="Alpha",
                minecraft_version="1.21",
                loader_type="fabric",
                loader_version="",
                memory_max_mb=2048,
                path="servers/Alpha",
            )
        }
    )
    fake_backup = SimpleNamespace(
        list_backups=lambda _server_name: [{"filename": "Alpha_202608201200.zip", "datetime": datetime.datetime.now()}]
    )
    service = _manage_service(fake_crud, server_backup=fake_backup)

    status = service.get_backup_status("Alpha")
    assert "剛剛" in status or "✅" in status


def test_work_outcome_statuses() -> None:
    s = WorkOutcome.succeeded(42)
    assert s.is_succeeded is True
    assert s.is_failed is False
    assert s.is_cancelled is False
    assert s.value == 42
    assert s.error is None

    err = RuntimeError("boom")
    f = WorkOutcome.failed(err)
    assert f.is_succeeded is False
    assert f.is_failed is True
    assert f.is_cancelled is False
    assert f.error is err

    c = WorkOutcome.cancelled()
    assert c.is_succeeded is False
    assert c.is_failed is False
    assert c.is_cancelled is True


def test_manage_server_frame_update_selection_disables_restore_when_running() -> None:
    class _FakeBtn:
        def __init__(self) -> None:
            self.enabled = False
            self.text = ""

        def setEnabled(self, val: bool) -> None:
            self.enabled = val

        def setText(self, val: str) -> None:
            self.text = val

    start_stop_btn = _FakeBtn()
    restore_btn = _FakeBtn()
    backup_btn = _FakeBtn()
    delete_btn = _FakeBtn()

    frame = _DummyFrame()
    frame.selected_server = "Alpha"
    frame.server_crud = SimpleNamespace(
        servers={
            "Alpha": ServerConfig(
                name="Alpha",
                minecraft_version="1.21.1",
                loader_type="fabric",
                loader_version="0.16.0",
                memory_max_mb=2048,
                path="servers/Alpha",
            )
        }
    )
    frame.action_buttons = {
        "start_stop": start_stop_btn,
        "restore": restore_btn,
        "backup": backup_btn,
        "delete": delete_btn,
    }
    frame.info_label = SimpleNamespace(setText=lambda _: None)

    frame.server_runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=True))
    ManageServerFrame.update_selection(cast(Any, frame))
    assert restore_btn.enabled is False
    assert backup_btn.enabled is False
    assert delete_btn.enabled is False
    assert start_stop_btn.enabled is True
    assert start_stop_btn.text == "🛑 停止"

    frame.server_runtime = SimpleNamespace(observe=lambda _name: SimpleNamespace(is_running=False))
    ManageServerFrame.update_selection(cast(Any, frame))
    assert restore_btn.enabled is True
    assert backup_btn.enabled is True
    assert delete_btn.enabled is True
    assert start_stop_btn.enabled is True
    assert start_stop_btn.text == "🚀 啟動"
