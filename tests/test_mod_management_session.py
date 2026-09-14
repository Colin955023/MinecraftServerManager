from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from src.models import PendingOnlineInstall, ServerConfig
from src.ui.mods.mod_management_session import (
    ModListRow,
    ModManagementSession,
    OnlineBrowseRequest,
)


def _server(name: str) -> ServerConfig:
    return ServerConfig(
        name=name,
        path=f"C:/servers/{name}",
        minecraft_version="1.21.1",
        loader_type="fabric",
        loader_version="0.16.0",
        memory_max_mb=2048,
    )


def _request(query: str) -> OnlineBrowseRequest:
    return OnlineBrowseRequest(query=query, minecraft_version="1.21.1", loader_type="fabric", sort_by="relevance")


def _pending(project_id: str, version_id: str) -> PendingOnlineInstall:
    return PendingOnlineInstall(
        project_id=project_id,
        project_name=project_id,
        version=cast(Any, SimpleNamespace(version_id=version_id)),
    )


def test_out_of_order_online_result_cannot_overwrite_latest_search() -> None:
    session = ModManagementSession(_server("A"))
    first_request = _request("first")
    second_request = _request("second")
    first_scope = session.begin_online_search(first_request)
    second_scope = session.begin_online_search(second_request)

    assert session.accept_online_results(first_scope, first_request, [SimpleNamespace(project_id="old")]) is False
    assert session.accept_online_results(second_scope, second_request, [SimpleNamespace(project_id="new")]) is True
    assert [mod.project_id for mod in session.snapshot().online_mods] == ["new"]


def test_invalidated_session_rejects_local_and_online_results() -> None:
    session = ModManagementSession(_server("A"))
    local_scope = session.begin_local_scan()
    request = _request("sodium")
    online_scope = session.begin_online_search(request)

    session.invalidate()

    assert session.accept_local_results(local_scope, [SimpleNamespace(filename="old.jar")]) is False
    assert session.accept_online_results(online_scope, request, [SimpleNamespace(project_id="old")]) is False
    assert session.snapshot().active is False


def test_queue_is_bound_to_session_and_cleared_on_invalidation() -> None:
    old_session = ModManagementSession(_server("A"))
    old_session.add_pending_install(_pending("sodium", "v1"))

    old_session.invalidate()
    new_session = ModManagementSession(_server("B"))

    assert old_session.pending_online_installs == ()
    assert new_session.pending_online_installs == ()
    assert old_session.snapshot().server_identity != new_session.snapshot().server_identity


def test_pending_install_replaces_same_project_and_version_key() -> None:
    session = ModManagementSession(_server("A"))
    session.add_pending_install(_pending("sodium", "v1"))
    session.add_pending_install(_pending("sodium", "v1"))
    session.add_pending_install(_pending("sodium", "v2"))

    assert len(session.pending_online_installs) == 2


def test_snapshot_collections_are_immutable_views() -> None:
    session = ModManagementSession(_server("A"))
    scope = session.begin_local_scan()
    session.accept_local_results(scope, [SimpleNamespace(filename="sodium.jar")])
    session.replace_selection({"sodium"})
    session.replace_local_rows([ModListRow("sodium", ("Sodium", "Enabled"), "sodium")])

    snapshot = session.snapshot()

    assert isinstance(snapshot.local_mods, tuple)
    assert snapshot.local_rows == (ModListRow("sodium", ("Sodium", "Enabled"), "sodium"),)
    assert snapshot.selected_mod_ids == frozenset({"sodium"})


def test_install_scope_is_rejected_after_session_invalidation() -> None:
    session = ModManagementSession(_server("A"))
    scope = session.begin_install()

    session.invalidate()

    assert session.is_scope_current(scope) is False


def test_status_is_written_and_read_through_snapshot() -> None:
    session = ModManagementSession(_server("A"))

    session.set_status("正在掃描本地模組...")

    assert session.snapshot().status_message == "正在掃描本地模組..."


def test_version_load_scope_is_rejected_after_session_invalidation() -> None:
    session = ModManagementSession(_server("A"))
    scope = session.begin_version_load()

    assert session.is_scope_current(scope) is True
    session.invalidate()
    assert session.is_scope_current(scope) is False
