from __future__ import annotations


class _DummyFrame:
    def __init__(self):
        self._server_refresh_token = 0
        self.server_tree = None
        self.service = None
        self.selected_server = ""
        self._monitor_windows = {}

    def _cancel_server_refresh_job(self):
        pass

    def _show_existing_monitor_window(self, win, bring_to_front=True):
        if bring_to_front:
            win.show()
            win.raise_()
            win.activateWindow()
            win.setFocus()
        else:
            win.show()

    def _recycle_server_item(self, item_id):
        pass

    def _apply_server_refresh_payload(self, payload, context):
        pass


from types import SimpleNamespace
from typing import Any, cast

import pytest
import src.ui.manage_server_frame as manage_server_frame_module
import src.ui.manage_server_service as manage_server_service_module
from src.models import ServerConfig


class FakeTreeview:
    def __init__(self) -> None:
        self.updated: list[tuple[str, tuple[Any, ...]]] = []
        self.fail_item_ids: set[str] = set()

    def item(self, item: str | int, option: str | None = None, **kw: Any) -> Any:
        if option is not None:
            return None
        values = kw.get("values")
        item_id = str(item)
        if item_id in self.fail_item_ids:
            raise RuntimeError(f"boom: {item_id}")
        if isinstance(values, tuple):
            self.updated.append((item_id, values))
        elif isinstance(values, list):
            self.updated.append((item_id, tuple(values)))
        return None


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


def test_build_server_tree_payload_skips_empty_rows_and_preserves_order() -> None:
    server_data = [
        ["Alpha", "1.21", "Fabric", "運行中", "已備份", "servers\\Alpha"],
        [],
        ["Beta", "1.20.6", "Forge", "已停止", "未備份", "servers\\Beta"],
    ]

    server_order, server_rows = manage_server_service_module.ManageServerService._build_server_tree_payload(server_data)

    assert server_order == ["Alpha", "Beta"]
    assert server_rows["Alpha"] == tuple(server_data[0])
    assert server_rows["Beta"] == tuple(server_data[2])


def test_build_server_tree_payload_last_duplicate_name_wins_values() -> None:
    server_data = [
        ["Alpha", "1.21", "Fabric", "運行中", "已備份", "servers\\Alpha"],
        ["Alpha", "1.21.1", "Fabric", "已停止", "未備份", "servers\\Alpha"],
    ]

    server_order, server_rows = manage_server_service_module.ManageServerService._build_server_tree_payload(server_data)

    assert server_order == ["Alpha", "Alpha"]
    assert server_rows["Alpha"] == tuple(server_data[1])


def test_build_server_refresh_payload_combines_signature_order_and_rows() -> None:
    server_data = [
        ["Alpha", "1.21", "Fabric", "運行中", "已備份", "servers\\Alpha"],
        ["Beta", "1.20.6", "Forge", "已停止", "未備份", "servers\\Beta"],
    ]

    payload = manage_server_service_module.ManageServerService._build_server_refresh_payload(server_data)

    assert payload.signature == (
        ("Alpha", tuple(server_data[0])),
        ("Beta", tuple(server_data[1])),
    )
    assert payload.server_order == ["Alpha", "Beta"]
    assert payload.server_rows == {
        "Alpha": tuple(server_data[0]),
        "Beta": tuple(server_data[1]),
    }


def test_should_apply_server_refresh_updates_hash_only_when_changed() -> None:
    service = object.__new__(manage_server_service_module.ManageServerService)
    service.__dict__["_last_server_data_hash"] = None
    payload = manage_server_service_module.ManageServerService._build_server_refresh_payload(
        [["Alpha", "1.21", "Fabric", "運行中", "已備份", "servers\\Alpha"]]
    )

    assert service._should_apply_server_refresh(payload) is True
    first_hash = service._last_server_data_hash
    assert isinstance(first_hash, int)
    assert service._should_apply_server_refresh(payload) is False
    assert service._last_server_data_hash == first_hash


def test_begin_server_refresh_cycle_returns_context() -> None:
    service = object.__new__(manage_server_service_module.ManageServerService)
    context = service._begin_server_refresh_cycle()
    assert context.refresh_token == 0


def test_monitor_server_reuses_existing_window_for_user_click_and_brings_to_front() -> None:
    frame = _DummyFrame()
    frame.selected_server = "Alpha"
    fake_window = FakeMonitorWindow()
    frame._monitor_windows = {"Alpha": SimpleNamespace(window=fake_window)}

    manage_server_frame_module.ManageServerFrame.monitor_server(frame)  # type: ignore[arg-type]

    assert fake_window.show_calls == 1
    assert fake_window.raise_calls == 1
    assert fake_window.activate_calls == 1
    assert fake_window.focus_calls == 1


def test_monitor_server_auto_reuses_existing_window_without_forcing_focus() -> None:
    frame = _DummyFrame()
    frame.selected_server = "Alpha"
    fake_window = FakeMonitorWindow()
    frame._monitor_windows = {"Alpha": SimpleNamespace(window=fake_window)}

    manage_server_frame_module.ManageServerFrame.monitor_server(frame, bring_to_front=False)  # type: ignore[arg-type]

    assert fake_window.show_calls == 1
    assert fake_window.raise_calls == 0
    assert fake_window.activate_calls == 0
    assert fake_window.focus_calls == 0


def test_prepare_server_tree_diff_updates_existing_rows_and_collects_pending() -> None:
    service = object.__new__(manage_server_service_module.ManageServerService)
    item_by_name = {"Alpha": "item-a", "Beta": "item-b"}
    previous_snapshot = {
        "Alpha": ("Alpha", "old"),
        "Beta": ("Beta", "same"),
    }

    preparation = service.prepare_server_tree_diff(
        server_item_by_name=item_by_name,
        previous_snapshot=previous_snapshot,
        server_order=["Alpha", "Beta", "Gamma"],
        server_rows={
            "Alpha": ("Alpha", "new"),
            "Beta": ("Beta", "changed"),
            "Gamma": ("Gamma", "fresh"),
        },
    )

    assert preparation.pending_update == [("item-a", ("Alpha", "new"))]
    assert item_by_name == {"Alpha": "item-a"}
    assert preparation.rows_snapshot == {"Alpha": ("Alpha", "new")}
    assert preparation.pending_insert == [
        ("Beta", ("Beta", "changed")),
        ("Gamma", ("Gamma", "fresh")),
    ]


def test_build_server_display_row_formats_unknown_mc_version_with_loader_version() -> None:
    config = ServerConfig(
        name="Alpha",
        minecraft_version="unknown",
        loader_type="fabric",
        loader_version="0.16.10",
        memory_max_mb=4096,
        path="servers\\Alpha",
    )

    row = manage_server_service_module.ManageServerService._build_server_display_row(
        name="Alpha",
        config=config,
        status="已停止",
        backup_status="未備份",
        display_path="servers\\Alpha",
    )

    assert row == ["Alpha", "未知", "Fabric v0.16.10", "已停止", "未備份", "servers\\Alpha"]


def test_build_server_display_row_formats_vanilla_loader() -> None:
    config = ServerConfig(
        name="Beta",
        minecraft_version="1.21.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path="servers\\Beta",
    )

    row = manage_server_service_module.ManageServerService._build_server_display_row(
        name="Beta",
        config=config,
        status="運行中",
        backup_status="已備份",
        display_path="servers\\Beta",
    )

    assert row == ["Beta", "1.21.1", "原版", "運行中", "已備份", "servers\\Beta"]


def test_build_server_refresh_execution_plan_skips_apply_when_payload_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = object.__new__(manage_server_service_module.ManageServerService)
    payload = manage_server_service_module.ManageServerService._build_server_refresh_payload(
        [["Alpha", "1.21", "Fabric", "運行中", "已備份", "servers\\Alpha"]]
    )

    monkeypatch.setattr(service, "_should_apply_server_refresh", lambda _payload: False)

    plan = service.build_server_refresh_execution_plan(payload, 6, "Alpha")

    assert plan.should_apply is False
    assert plan.refresh_context is None


def test_build_server_refresh_execution_plan_returns_refresh_context_when_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = object.__new__(manage_server_service_module.ManageServerService)
    payload = manage_server_service_module.ManageServerService._build_server_refresh_payload(
        [["Alpha", "1.21", "Fabric", "運行中", "已備份", "servers\\Alpha"]]
    )
    expected_context = manage_server_service_module.ServerRefreshContext(refresh_token=6, previous_selection="Alpha")

    monkeypatch.setattr(service, "_should_apply_server_refresh", lambda _payload: True)

    plan = service.build_server_refresh_execution_plan(payload, 6, "Alpha")

    assert plan.should_apply is True
    assert plan.refresh_context == expected_context


def test_refresh_servers_callback_applies_payload_with_execution_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = _DummyFrame()
    frame.server_tree = cast(Any, object())
    payload = manage_server_service_module.ManageServerService._build_server_refresh_payload(
        [["Alpha", "1.21", "Fabric", "運行中", "已備份", "servers\\Alpha"]]
    )
    execution_plan = manage_server_service_module.ServerRefreshExecutionPlan(
        should_apply=True,
        refresh_context=manage_server_service_module.ServerRefreshContext(refresh_token=3, previous_selection="Alpha"),
    )
    calls: list[
        tuple[manage_server_service_module.ServerRefreshPayload, manage_server_service_module.ServerRefreshContext]
    ] = []

    frame.service = object.__new__(manage_server_service_module.ManageServerService)
    monkeypatch.setattr(frame.service, "build_server_refresh_execution_plan", lambda _p, _t, _s: execution_plan)
    monkeypatch.setattr(
        frame, "_apply_server_refresh_payload", lambda _payload, context: calls.append((_payload, context))
    )

    manage_server_frame_module.ManageServerFrame._refresh_servers_callback(frame, payload)  # type: ignore[arg-type]

    assert calls == [(payload, execution_plan.refresh_context)]
