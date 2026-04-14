from __future__ import annotations

from tkinter import ttk
from typing import Any, cast

import pytest
import src.ui.manage_server_frame as manage_server_frame_module
from src.models import ServerConfig


class FakeTreeview(ttk.Treeview):
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


@pytest.mark.smoke
def test_build_server_tree_payload_skips_empty_rows_and_preserves_order() -> None:
    server_data = [
        ["Alpha", "1.21", "Fabric", "運行中", "已備份", "servers\\Alpha"],
        [],
        ["Beta", "1.20.6", "Forge", "已停止", "未備份", "servers\\Beta"],
    ]

    server_order, server_rows = manage_server_frame_module.ManageServerFrame._build_server_tree_payload(server_data)

    assert server_order == ["Alpha", "Beta"]
    assert server_rows["Alpha"] == tuple(server_data[0])
    assert server_rows["Beta"] == tuple(server_data[2])


@pytest.mark.smoke
def test_build_server_tree_payload_last_duplicate_name_wins_values() -> None:
    server_data = [
        ["Alpha", "1.21", "Fabric", "運行中", "已備份", "servers\\Alpha"],
        ["Alpha", "1.21.1", "Fabric", "已停止", "未備份", "servers\\Alpha"],
    ]

    server_order, server_rows = manage_server_frame_module.ManageServerFrame._build_server_tree_payload(server_data)

    assert server_order == ["Alpha", "Alpha"]
    assert server_rows["Alpha"] == tuple(server_data[1])


@pytest.mark.smoke
def test_build_server_refresh_payload_combines_signature_order_and_rows() -> None:
    server_data = [
        ["Alpha", "1.21", "Fabric", "運行中", "已備份", "servers\\Alpha"],
        ["Beta", "1.20.6", "Forge", "已停止", "未備份", "servers\\Beta"],
    ]

    payload = manage_server_frame_module.ManageServerFrame._build_server_refresh_payload(server_data)

    assert payload.signature == (
        ("Alpha", tuple(server_data[0])),
        ("Beta", tuple(server_data[1])),
    )
    assert payload.server_order == ["Alpha", "Beta"]
    assert payload.server_rows == {
        "Alpha": tuple(server_data[0]),
        "Beta": tuple(server_data[1]),
    }


@pytest.mark.smoke
def test_should_apply_server_refresh_updates_hash_only_when_changed() -> None:
    frame = object.__new__(manage_server_frame_module.ManageServerFrame)
    frame.__dict__["_last_server_data_hash"] = None
    payload = manage_server_frame_module.ManageServerFrame._build_server_refresh_payload(
        [["Alpha", "1.21", "Fabric", "運行中", "已備份", "servers\\Alpha"]]
    )

    assert frame._should_apply_server_refresh(payload) is True
    first_hash = frame._last_server_data_hash
    assert isinstance(first_hash, int)
    assert frame._should_apply_server_refresh(payload) is False
    assert frame._last_server_data_hash == first_hash


@pytest.mark.smoke
def test_begin_server_refresh_cycle_cancels_old_job_and_increments_token(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = object.__new__(manage_server_frame_module.ManageServerFrame)
    frame._server_refresh_token = 3
    frame.selected_server = "Alpha"
    cancel_calls: list[str] = []

    monkeypatch.setattr(
        frame,
        "_cancel_server_refresh_job",
        lambda: cancel_calls.append("cancelled"),
    )

    context = frame._begin_server_refresh_cycle()

    assert cancel_calls == ["cancelled"]
    assert context.refresh_token == 4
    assert context.previous_selection == "Alpha"
    assert frame._server_refresh_token == 4


@pytest.mark.smoke
def test_remove_stale_server_items_recycles_and_prunes_names(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = object.__new__(manage_server_frame_module.ManageServerFrame)
    frame._server_item_by_name = {"Alpha": "item-a", "Beta": "item-b", "Gamma": "item-c"}
    recycled: list[str] = []

    monkeypatch.setattr(
        frame,
        "_recycle_server_item",
        lambda item_id: recycled.append(item_id),
    )

    frame._remove_stale_server_items(
        {
            "Alpha": ("Alpha",),
            "Gamma": ("Gamma",),
        }
    )

    assert recycled == ["item-b"]
    assert frame._server_item_by_name == {"Alpha": "item-a", "Gamma": "item-c"}


@pytest.mark.smoke
def test_prepare_server_tree_diff_updates_existing_rows_and_collects_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = object.__new__(manage_server_frame_module.ManageServerFrame)
    frame._server_item_by_name = {"Alpha": "item-a", "Beta": "item-b"}
    frame._server_rows_snapshot = {
        "Alpha": ("Alpha", "old"),
        "Beta": ("Beta", "same"),
    }
    recycled: list[str] = []
    tree = FakeTreeview()
    tree.fail_item_ids.add("item-b")

    monkeypatch.setattr(
        frame,
        "_recycle_server_item",
        lambda item_id: recycled.append(item_id),
    )

    preparation = frame._prepare_server_tree_diff(
        tree=cast(manage_server_frame_module._ServerTreeItemUpdater, tree),
        server_order=["Alpha", "Beta", "Gamma"],
        server_rows={
            "Alpha": ("Alpha", "new"),
            "Beta": ("Beta", "changed"),
            "Gamma": ("Gamma", "fresh"),
        },
    )

    assert tree.updated == [("item-a", ("Alpha", "new"))]
    assert recycled == ["item-b"]
    assert frame._server_item_by_name == {"Alpha": "item-a"}
    assert preparation.rows_snapshot == {"Alpha": ("Alpha", "new")}
    assert preparation.pending_insert == [
        ("Beta", ("Beta", "changed")),
        ("Gamma", ("Gamma", "fresh")),
    ]


@pytest.mark.smoke
def test_build_server_display_row_formats_unknown_mc_version_with_loader_version() -> None:
    config = ServerConfig(
        name="Alpha",
        minecraft_version="unknown",
        loader_type="fabric",
        loader_version="0.16.10",
        memory_max_mb=4096,
        path="servers\\Alpha",
    )

    row = manage_server_frame_module.ManageServerFrame._build_server_display_row(
        name="Alpha",
        config=config,
        status="已停止",
        backup_status="未備份",
        display_path="servers\\Alpha",
    )

    assert row == ["Alpha", "未知", "Fabric v0.16.10", "已停止", "未備份", "servers\\Alpha"]


@pytest.mark.smoke
def test_build_server_display_row_formats_vanilla_loader() -> None:
    config = ServerConfig(
        name="Beta",
        minecraft_version="1.21.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path="servers\\Beta",
    )

    row = manage_server_frame_module.ManageServerFrame._build_server_display_row(
        name="Beta",
        config=config,
        status="運行中",
        backup_status="已備份",
        display_path="servers\\Beta",
    )

    assert row == ["Beta", "1.21.1", "原版", "運行中", "已備份", "servers\\Beta"]


@pytest.mark.smoke
def test_build_server_refresh_execution_plan_skips_apply_when_payload_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = object.__new__(manage_server_frame_module.ManageServerFrame)
    payload = manage_server_frame_module.ManageServerFrame._build_server_refresh_payload(
        [["Alpha", "1.21", "Fabric", "運行中", "已備份", "servers\\Alpha"]]
    )

    monkeypatch.setattr(frame, "_should_apply_server_refresh", lambda _payload: False)

    plan = frame._build_server_refresh_execution_plan(payload)

    assert plan.should_apply is False
    assert plan.refresh_context is None


@pytest.mark.smoke
def test_build_server_refresh_execution_plan_returns_refresh_context_when_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = object.__new__(manage_server_frame_module.ManageServerFrame)
    payload = manage_server_frame_module.ManageServerFrame._build_server_refresh_payload(
        [["Alpha", "1.21", "Fabric", "運行中", "已備份", "servers\\Alpha"]]
    )
    expected_context = manage_server_frame_module.ServerRefreshContext(refresh_token=7, previous_selection="Alpha")

    monkeypatch.setattr(frame, "_should_apply_server_refresh", lambda _payload: True)
    monkeypatch.setattr(frame, "_begin_server_refresh_cycle", lambda: expected_context)

    plan = frame._build_server_refresh_execution_plan(payload)

    assert plan.should_apply is True
    assert plan.refresh_context == expected_context


@pytest.mark.smoke
def test_refresh_servers_callback_applies_payload_with_execution_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = object.__new__(manage_server_frame_module.ManageServerFrame)
    frame.server_tree = cast(Any, object())
    payload = manage_server_frame_module.ManageServerFrame._build_server_refresh_payload(
        [["Alpha", "1.21", "Fabric", "運行中", "已備份", "servers\\Alpha"]]
    )
    execution_plan = manage_server_frame_module.ServerRefreshExecutionPlan(
        should_apply=True,
        refresh_context=manage_server_frame_module.ServerRefreshContext(refresh_token=3, previous_selection="Alpha"),
    )
    calls: list[
        tuple[manage_server_frame_module.ServerRefreshPayload, manage_server_frame_module.ServerRefreshContext]
    ] = []

    monkeypatch.setattr(frame, "_build_server_refresh_execution_plan", lambda _payload: execution_plan)
    monkeypatch.setattr(
        frame, "_apply_server_refresh_payload", lambda _payload, context: calls.append((_payload, context))
    )

    frame._refresh_servers_callback(payload)

    assert calls == [(payload, execution_plan.refresh_context)]
