from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import src.models as models_module
import src.ui as ui_module
import src.ui.mods.online_mod_queue as online_mod_queue_module
import src.ui.mods.review_contracts as review_contracts_module
import src.ui.mods.review_workflow as review_workflow_module
import src.utils as utils_module
import src.utils.ui_support.ui_utils as ui_utils_module
from src.ui import (
    LocalReviewSnapshotStore,
    ModManagementSession,
    ModReviewWorkflow,
    build_dependency_status_text,
    build_local_update_execution_prompt,
    build_local_update_review_key,
    build_local_update_review_subtitle,
    build_online_install_execution_prompt,
    build_online_review_root_status_text,
    build_review_context_stamp,
    count_enabled_runnable_entries,
    count_online_install_review_groups,
    format_completion_notes,
    format_local_update_review_text,
    format_online_version_report,
    format_pending_install_review_text,
    format_review_overview_text,
    get_online_install_review_group_key,
    get_online_version_status_text,
    resolve_local_update_review_project_page_url,
    resolve_pending_install_review_project_page_url,
    set_review_entries_enabled,
    sort_online_versions_for_server,
)


def _review_presentation(
    telemetry: dict[str, int] | None = None,
) -> review_workflow_module._ReviewPresentation:
    return review_workflow_module._ReviewPresentation(
        telemetry or {"checked": 0, "migrated": 0, "replayed": 0, "fallback_rebuild": 0}
    )


def _review_server() -> SimpleNamespace:
    return SimpleNamespace(
        name="Test Server",
        path="C:/servers/Test",
        minecraft_version="1.21.1",
        loader_type="fabric",
        loader_version="0.16.0",
    )


def _mod_session(
    server: Any | None = None,
    *,
    local_mods: list[Any] | None = None,
    online_mods: list[Any] | None = None,
    pending: list[models_module.PendingOnlineInstall] | None = None,
) -> ModManagementSession:
    session = ModManagementSession(cast(Any, server))
    if local_mods is not None:
        scope = session.begin_local_scan()
        assert session.accept_local_results(scope, local_mods)
    if online_mods is not None:
        request = models_module.OnlineBrowseRequest("test", "1.21.1", "fabric", "relevance")
        scope = session.begin_online_search(request)
        assert session.accept_online_results(scope, request, online_mods)
    for item in pending or []:
        session.add_pending_install(item)
    return session


class _MockTreeWidgetItem:
    def __init__(self, values: list[str], tags: list[str]):
        self._id = tags[0]
        self._name = values[1]

    def data(self, _column: int, _role: Any) -> str:
        return self._id

    def text(self, _column: int) -> str:
        return self._name


class _DeleteTree:
    def __init__(self) -> None:
        self._items = [
            _MockTreeWidgetItem(["✅ 已啟用", "Clumps"], ["clumps", "odd"]),
            _MockTreeWidgetItem(["✅ 已啟用", "Fabric API"], ["fabric-api", "even"]),
        ]

    def selectedItems(self) -> list[_MockTreeWidgetItem]:
        return self._items


class _StatusLabel:
    def __init__(self) -> None:
        self.text = ""

    def is_alive(self) -> bool:
        return True

    def configure(self, **kwargs) -> None:
        self.text = str(kwargs.get("text", self.text))

    def setText(self, text: str) -> None:
        self.text = text


class _DummyTreeItem:
    def __init__(self, key: str, parent_key: str = ""):
        self._key = key
        self._parent_key = parent_key

    def data(self, _column: int, _role: Any) -> str:
        return self._key

    def parent(self) -> _DummyTreeItem | None:
        if self._parent_key:
            return _DummyTreeItem(self._parent_key)
        return None


def _pending_install(project_id: str, project_name: str, version_id: str) -> models_module.PendingOnlineInstall:
    return models_module.PendingOnlineInstall(
        project_id=project_id,
        project_name=project_name,
        version=cast(Any, SimpleNamespace(version_id=version_id)),
    )


def test_build_online_browse_request_returns_warning_when_query_empty() -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    frame_any = cast(Any, frame)
    frame_any.browse_sort_var = SimpleNamespace(get=lambda: "相關性")
    frame_any.browse_sort_options = {"相關性": "relevance"}
    frame_any.search_var = SimpleNamespace(get=lambda: "")
    frame.mod_session = _mod_session(
        SimpleNamespace(minecraft_version="1.21.1", loader_type="fabric", loader_version="0.16.10")
    )

    request, warning_message = frame._build_online_browse_request()

    assert request is None
    assert warning_message == "請先輸入關鍵字再搜尋模組"


def test_get_online_version_dialog_hint_text_uses_server_context() -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    frame.mod_session = _mod_session(
        SimpleNamespace(minecraft_version="1.21.1", loader_type="fabric", loader_version="0.16.10")
    )

    hint_text = frame._get_online_version_dialog_hint_text()

    assert hint_text == "相容性條件：MC 1.21.1 / fabric / 0.16.10"
    assert "留空" not in hint_text


def test_on_online_browse_filters_changed_refreshes_hint_and_reloads(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    called: list[tuple[bool, bool] | str] = []

    monkeypatch.setattr(frame, "_refresh_online_filter_hint", lambda: called.append("hint"))
    monkeypatch.setattr(frame, "_refresh_online_results_summary", lambda: called.append("summary"))
    monkeypatch.setattr(
        frame,
        "_load_online_mods",
        lambda *, force=False, show_warning=True: called.append((force, show_warning)),
    )

    frame.on_online_browse_filters_changed("效能優化")

    assert called == ["hint", "summary", (True, False)]


def test_build_online_results_summary_text_shows_mode_sort_and_count() -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    frame_any = cast(Any, frame)
    frame_any.search_var = SimpleNamespace(get=lambda: "sodium")
    frame_any.browse_sort_var = SimpleNamespace(get=lambda: "下載量")
    frame.mod_session = _mod_session(online_mods=[object(), object()])

    summary = frame._build_online_results_summary_text()

    assert summary == "搜尋 sodium｜2 筆｜排序 下載量"


def test_build_online_results_summary_text_prompts_keyword_when_query_empty() -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    frame_any = cast(Any, frame)
    frame_any.search_var = SimpleNamespace(get=lambda: "")
    frame_any.browse_sort_var = SimpleNamespace(get=lambda: "相關性")
    frame.mod_session = _mod_session(online_mods=[])

    summary = frame._build_online_results_summary_text()

    assert summary == "請輸入關鍵字搜尋｜0 筆｜排序 相關性"


def test_build_online_browse_row_includes_prism_style_metadata() -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)

    mod = SimpleNamespace(
        name="Sodium",
        author="jellysquid3",
        latest_version="mc1.21-0.6.0",
        download_count=1234567,
        categories=["fabric", "optimization"],
        description="Client and server rendering optimizations.",
        slug="sodium",
    )

    row = frame._build_online_browse_row(mod)

    assert row == (
        "Sodium",
        "jellysquid3",
        "1,234,567",
        "Modrinth",
        "未知",
        "Client and server rendering optimizations.",
    )


def test_build_online_browse_row_keeps_full_description() -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)

    long_description = (
        "You can drink from a water source, cauldron or with vanilla items.\n"
        "Items have fluid compatibility and the full description should stay intact."
    )
    mod = SimpleNamespace(
        name="Vanilla Thirst Bar",
        author="whilem.nm",
        latest_version="8rd9sFlD",
        download_count=843,
        categories=["fabric", "adventure"],
        description=long_description,
        slug="vanilla-thirst-bar",
    )

    row = frame._build_online_browse_row(mod)

    assert row[5] == (
        "You can drink from a water source, cauldron or with vanilla items. "
        "Items have fluid compatibility and the full description should stay intact."
    )


def test_copy_online_mod_info_handles_clipboard_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    frame_any = cast(Any, frame)
    selected_mod = SimpleNamespace(
        name="Fabric API",
        author="FabricMC",
        download_count=1234,
        source="modrinth",
        url="https://example.invalid/fabric-api",
    )
    frame_any.parent = SimpleNamespace()
    frame_any.update_status = lambda _message: None
    frame_any._format_online_environment_text = lambda _mod: "Fabric / server"
    frame_any._get_selected_online_mod_context = lambda: (True, "fabric-api", selected_mod)

    class _BrokenClipboard:
        def setText(self, _text: str) -> None:
            raise RuntimeError("clipboard unavailable")

    class _BrokenApp:
        @staticmethod
        def clipboard():
            return _BrokenClipboard()

        @staticmethod
        def processEvents() -> None:
            raise RuntimeError("processEvents unavailable")

    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(online_mod_queue_module, "QApplication", _BrokenApp)
    monkeypatch.setattr(
        utils_module.UIUtils,
        "show_message",
        lambda title, message, _parent=None, message_level="info": (
            errors.append((title, message)) if message_level == "error" else None
        ),
    )

    frame.copy_online_mod_info()

    assert errors == [("複製失敗", "無法將模組資訊複製到剪貼簿：clipboard unavailable")]


def test_refresh_local_list_keeps_full_description(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    frame_any = cast(Any, frame)

    from unittest.mock import MagicMock

    mock_tree = MagicMock()
    mock_item = MagicMock()
    mock_item.text.return_value = (
        "Core API module providing key hooks and intercompatibility. No truncation should happen."
    )
    mock_tree.topLevelItemCount.return_value = 1
    mock_tree.topLevelItem.return_value = mock_item

    frame_any.local_tree = mock_tree
    local_mods = [
        SimpleNamespace(
            name="Fabric API",
            status=models_module.ModStatus.ENABLED,
            filename="fabric-api-0.141.3+1.21.1.jar",
            version="0.141.3+1.21.1",
            author="FabricMC",
            loader_type="Fabric",
            file_size=2348810,
            file_path="C:/servers/Alpha/mods/fabric-api-0.141.3+1.21.1.jar",
            description="Core API module providing key hooks and intercompatibility.\nNo truncation should happen.",
            _cached_mtime=1743494400.0,
        )
    ]
    frame.mod_session = _mod_session(local_mods=local_mods)
    frame.local_mod_list_presenter = SimpleNamespace(
        apply_local_tree_theme=lambda: None,
        on_tree_selection_changed=lambda: None,
    )
    frame_any.local_search_var = SimpleNamespace(get=lambda: "")
    frame_any.local_filter_var = SimpleNamespace(get=lambda: "所有")
    frame.VERSION_PATTERN = re.compile(r"-([\dv.]+)(?:\.jar(?:\.disabled)?)?$")

    def _noop_format(text: str) -> str:
        return text.replace("\n", " ")

    frame._format_single_line_text = _noop_format

    def _capture_selected_mod_ids_func() -> set:
        return set()

    def _resolve_local_display_name_func(mod: Any, _enhanced: Any) -> str:
        return mod.name

    def _get_enhanced_attr_func(_enhanced: Any, _attr: str, default: Any) -> Any:
        return default

    monkeypatch.setattr(frame, "_capture_selected_mod_ids", _capture_selected_mod_ids_func)
    monkeypatch.setattr(frame, "_resolve_local_display_name", _resolve_local_display_name_func)
    monkeypatch.setattr(frame, "_get_enhanced_attr", _get_enhanced_attr_func)

    frame.refresh_local_list()


def test_reveal_in_explorer_uses_windows_select_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded_calls: list[list[str]] = []

    def fake_run_checked(command, check=False):
        del check
        recorded_calls.append(list(command))

    monkeypatch.setattr(ui_utils_module, "os", SimpleNamespace(name="nt", environ={"WINDIR": "C:\\Windows"}))
    monkeypatch.setattr(utils_module.PathUtils, "find_executable", lambda _name: "explorer.exe")
    monkeypatch.setattr(utils_module.UIUtils, "_is_safe_windows_path_argument", lambda _path: True)
    monkeypatch.setattr(utils_module.SubprocessUtils, "run_checked", fake_run_checked)

    utils_module.UIUtils.reveal_in_explorer(Path("C:/servers/Alpha/mods/example.jar"))

    assert recorded_calls == [["explorer.exe", "/select,", "C:\\servers\\Alpha\\mods\\example.jar"]]


def test_build_local_update_task_nodes_dedupes_duplicate_entries_and_merges_metadata_messages() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    candidate = SimpleNamespace(
        project_id="Ha28R6CL",
        project_name="Fabric Language Kotlin",
        current_version="1.13.9",
        target_version_name="1.14.0",
        actionable=False,
        metadata_source="unresolved",
        recommendation_source="project_fallback",
        recommendation_confidence="advisory",
        metadata_note="metadata ensure 失敗：找不到可用的 provider metadata 或雜湊對應結果",
        report=SimpleNamespace(warnings=[]),
        notes=[],
        local_mod=SimpleNamespace(file_path="C:/servers/Fabric/mods/fabric-language-kotlin-1.13.9+kotlin.2.3.10.jar"),
    )
    review_entry = models_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        blocking_reasons=["metadata 未識別，暫時無法自動檢查更新"],
        enabled=False,
        provider="modrinth",
        version_type="beta",
    )

    nodes = _review_presentation()._build_local_update_task_nodes([review_entry, review_entry])
    root_nodes = [node for node in nodes if node.node_kind == "root"]
    assert len(root_nodes) == 1, "應該只有一個根級節點（已去重）"
    root_node = root_nodes[0]
    assert root_node.title == "Fabric Language Kotlin"
    assert root_node.values[1] == "1.13.9"
    assert root_node.values[2] == "1.14.0"
    assert root_node.group_key == "unknown"


def test_build_local_update_execution_prompt_summarizes_failure_matrix() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)

    enabled_entry = models_module.LocalUpdateReviewEntry(
        candidate=SimpleNamespace(actionable=True, recommendation_confidence="high"),
        dependency_plan=SimpleNamespace(items=[]),
        enabled=True,
    )
    advisory_entry = models_module.LocalUpdateReviewEntry(
        candidate=SimpleNamespace(actionable=True, recommendation_confidence="advisory"),
        dependency_plan=SimpleNamespace(items=[]),
        enabled=True,
    )
    retryable_entry = models_module.LocalUpdateReviewEntry(
        candidate=SimpleNamespace(
            actionable=True,
            recommendation_confidence="retryable",
            recommendation_source="stale_metadata",
            metadata_source="stale_provider",
        ),
        dependency_plan=SimpleNamespace(items=[]),
        blocking_reasons=["metadata 過期"],
        enabled=True,
    )
    unknown_entry = models_module.LocalUpdateReviewEntry(
        candidate=SimpleNamespace(
            actionable=True,
            recommendation_confidence="blocked",
            recommendation_source="metadata_unresolved",
            metadata_source="unresolved",
        ),
        dependency_plan=SimpleNamespace(items=[]),
        blocking_reasons=["provider metadata 缺失"],
        enabled=True,
    )
    blocked_entry = models_module.LocalUpdateReviewEntry(
        candidate=SimpleNamespace(actionable=True, recommendation_confidence="blocked"),
        dependency_plan=SimpleNamespace(items=[]),
        blocking_reasons=["相依版本衝突"],
        enabled=True,
    )

    prompt = build_local_update_execution_prompt(
        [enabled_entry, advisory_entry, retryable_entry, unknown_entry, blocked_entry]
    )

    assert prompt is not None
    assert "建議確認：1 項" in prompt
    assert "可重試：1 項" in prompt
    assert "待識別：1 項" in prompt
    assert "需先處理：1 項" in prompt
    assert "將繼續更新其餘 2 個可更新項目" in prompt


def test_build_local_update_execution_prompt_returns_none_for_advisory_only() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)

    entries = [
        models_module.LocalUpdateReviewEntry(
            candidate=SimpleNamespace(actionable=True, recommendation_confidence="advisory"),
            dependency_plan=SimpleNamespace(items=[]),
            enabled=True,
        )
        for _ in range(2)
    ]

    assert build_local_update_execution_prompt(entries) is None


def test_get_online_version_status_text_distinguishes_key_states() -> None:
    assert get_online_version_status_text(None) == "未分析"

    incompatible_report = SimpleNamespace(compatible=False)
    assert get_online_version_status_text(incompatible_report) == "不相容"

    dependency_report = SimpleNamespace(
        compatible=True,
        missing_required_dependencies=["Fabric API"],
        incompatible_installed=[],
        installed_version_mismatches=[],
        warnings=[],
    )
    assert get_online_version_status_text(dependency_report) == "可安裝，含依賴"

    warning_report = SimpleNamespace(
        compatible=True,
        missing_required_dependencies=[],
        incompatible_installed=[],
        installed_version_mismatches=[],
        warnings=["optional"],
    )
    assert get_online_version_status_text(warning_report) == "可安裝，需注意"

    clean_report = SimpleNamespace(
        compatible=True,
        missing_required_dependencies=[],
        incompatible_installed=[],
        installed_version_mismatches=[],
        warnings=[],
    )
    assert get_online_version_status_text(clean_report) == "可安裝"


def test_sort_online_versions_for_server_prefers_compatible_then_stable_then_newer() -> None:
    versions = [
        SimpleNamespace(version_id="beta-new", version_type="beta", date_published="2026-03-03T10:00:00Z"),
        SimpleNamespace(version_id="release-old", version_type="release", date_published="2026-03-01T10:00:00Z"),
        SimpleNamespace(
            version_id="release-incompatible", version_type="release", date_published="2026-03-04T10:00:00Z"
        ),
    ]
    reports = [
        SimpleNamespace(compatible=True),
        SimpleNamespace(compatible=True),
        SimpleNamespace(compatible=False),
    ]

    sorted_versions, _ = sort_online_versions_for_server(versions, reports)

    assert [version.version_id for version in sorted_versions] == [
        "release-old",
        "beta-new",
        "release-incompatible",
    ]


def test_sort_online_versions_for_server_keeps_reports_aligned() -> None:
    versions = [
        SimpleNamespace(version_id="v1", version_type="beta", date_published="2026-03-02T10:00:00Z"),
        SimpleNamespace(version_id="v2", version_type="release", date_published="2026-03-01T10:00:00Z"),
    ]
    reports = [
        SimpleNamespace(compatible=True, marker="report-v1"),
        SimpleNamespace(compatible=True, marker="report-v2"),
    ]

    sorted_versions, sorted_reports = sort_online_versions_for_server(
        versions,
        reports,
    )

    assert [version.version_id for version in sorted_versions] == ["v2", "v1"]
    assert [report.marker for report in cast(list[Any], sorted_reports)] == ["report-v2", "report-v1"]


def test_resolve_local_display_name_keeps_trusted_local_name_when_enhancement_is_fuzzy() -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    local_mod = cast(Any, type("LocalMod", (), {"name": "Fabric API", "platform_id": "fabric-api"})())
    enhanced = cast(Any, type("EnhancedMod", (), {"name": "Dawn API", "project_id": "dawn-api", "slug": "dawn-api"})())

    display_name = frame._resolve_local_display_name(local_mod, enhanced)

    assert display_name == "Fabric API"


def test_resolve_local_display_name_uses_exact_enhancement_when_local_name_unknown() -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    local_mod = cast(Any, type("LocalMod", (), {"name": "Unknown Mod", "platform_id": "fabric-api"})())
    enhanced = cast(
        Any, type("EnhancedMod", (), {"name": "Fabric API", "project_id": "P7dR8mSH", "slug": "fabric-api"})()
    )

    display_name = frame._resolve_local_display_name(local_mod, enhanced)

    assert display_name == "Fabric API"


def test_delete_local_mod_delegates_to_mod_manager_and_refreshes(tmp_path: Path, monkeypatch) -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    deleted_ids: list[list[str]] = []
    shown_messages: list[str] = []
    frame.local_tree = cast(Any, _DeleteTree())
    frame.mod_session = _mod_session(type("Server", (), {"path": str(tmp_path)})())
    frame.parent = cast(Any, object())
    frame.status_label = cast(Any, _StatusLabel())

    def _delete_local_mods_result(ids: list[str]) -> SimpleNamespace:
        deleted_ids.append(list(ids))
        return SimpleNamespace(
            affected_count=2,
            completed=True,
            partial=False,
            message="已刪除 2 個模組檔案",
            title="",
            missing_ids=(),
        )

    frame.mod_manager = cast(
        Any,
        SimpleNamespace(delete_local_mods_result=_delete_local_mods_result),
    )
    frame.local_mod_list_presenter = SimpleNamespace(load_local_mods=lambda: shown_messages.append("reloaded"))

    def fake_ask_yes_no_cancel(_title, _message, parent=None, show_cancel=False) -> bool:
        del parent, show_cancel
        return True

    monkeypatch.setattr(utils_module.UIUtils, "ask_yes_no_cancel", fake_ask_yes_no_cancel)
    monkeypatch.setattr(
        utils_module.UIUtils,
        "show_message",
        lambda _title, message, _parent=None, message_level="info": (
            shown_messages.append(message) if message_level == "info" else shown_messages.append(f"warn:{message}")
        ),
    )

    frame.delete_local_mod()

    assert deleted_ids == [["clumps", "fabric-api"]]
    assert shown_messages[0] == "reloaded"
    assert shown_messages[1] == "已刪除 2 個模組檔案"
    assert frame.status_label.text == "已刪除 2 個模組"


def test_delete_local_mod_shows_manager_failure_message(tmp_path: Path, monkeypatch) -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    shown_messages: list[str] = []
    frame.local_tree = cast(Any, _DeleteTree())
    frame.mod_session = _mod_session(type("Server", (), {"path": str(tmp_path)})())
    frame.parent = cast(Any, object())
    frame.status_label = cast(Any, _StatusLabel())
    frame.mod_manager = cast(
        Any,
        SimpleNamespace(
            delete_local_mods_result=lambda _ids: SimpleNamespace(
                affected_count=0,
                completed=False,
                partial=False,
                message="刪除模組失敗: permission denied",
                title="刪除失敗",
                missing_ids=(),
            )
        ),
    )
    frame.local_mod_list_presenter = SimpleNamespace(load_local_mods=lambda: shown_messages.append("reloaded"))

    def fake_ask_yes_no_cancel(_title, _message, parent=None, show_cancel=False) -> bool:
        del parent, show_cancel
        return True

    monkeypatch.setattr(utils_module.UIUtils, "ask_yes_no_cancel", fake_ask_yes_no_cancel)
    monkeypatch.setattr(
        utils_module.UIUtils,
        "show_message",
        lambda _title, message, _parent=None, message_level="info": (
            shown_messages.append(message) if message_level == "warning" else None
        ),
    )

    frame.delete_local_mod()

    assert shown_messages
    assert shown_messages[-1] == "刪除模組失敗: permission denied"
    assert frame.status_label.text == "刪除模組失敗: permission denied"


def test_set_review_entries_enabled_toggles_flags() -> None:
    enabled_entry = models_module.PendingInstallReviewEntry(
        pending=cast(Any, object()),
        report=None,
        dependency_plan=cast(Any, object()),
        enabled=True,
    )
    disabled_entry = models_module.PendingInstallReviewEntry(
        pending=cast(Any, object()),
        report=None,
        dependency_plan=cast(Any, object()),
        enabled=False,
    )

    changed = set_review_entries_enabled(
        {"a": enabled_entry, "b": disabled_entry},
        {"a", "b"},
        False,
    )

    assert changed is True
    assert enabled_entry.enabled is False
    assert disabled_entry.enabled is False


def test_review_entry_counters_distinguish_enabled_and_blocked_items() -> None:
    runnable_enabled = models_module.PendingInstallReviewEntry(
        pending=cast(Any, object()),
        report=None,
        dependency_plan=cast(Any, object()),
        enabled=True,
    )
    runnable_disabled = models_module.PendingInstallReviewEntry(
        pending=cast(Any, object()),
        report=None,
        dependency_plan=cast(Any, object()),
        enabled=False,
    )
    blocked_enabled = models_module.PendingInstallReviewEntry(
        pending=cast(Any, object()),
        report=None,
        dependency_plan=None,
        blocking_reasons=["missing dependency"],
        enabled=True,
    )

    entries = [runnable_enabled, runnable_disabled, blocked_enabled]

    assert count_enabled_runnable_entries(entries) == 1


def test_build_online_review_task_nodes_include_grouped_children() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    pending = models_module.PendingOnlineInstall(
        project_id="fabric-api",
        project_name="Fabric API",
        version=cast(Any, type("Version", (), {"version_id": "abc", "display_name": "0.120.0"})()),
    )
    review_entry = models_module.PendingInstallReviewEntry(
        pending=pending,
        report=None,
        dependency_plan=SimpleNamespace(items=[SimpleNamespace(project_name="Cloth Config", version_name="17.0.0")]),
        warning_messages=["建議先備份伺服器"],
        enabled=True,
        provider="modrinth",
        version_type="release",
    )

    nodes = _review_presentation()._build_online_review_task_nodes([review_entry])
    root_nodes = [node for node in nodes if node.node_kind == "root"]
    assert len(root_nodes) == 1, "應該只有一個根級節點"

    dependency_nodes = [node for node in nodes if node.node_kind == "dependency"]
    assert len(dependency_nodes) == 1, "應該把必要依賴列為子節點"
    assert dependency_nodes[0].values[2] == "Cloth Config"
    assert "required-by：Fabric API" in dependency_nodes[0].detail

    assert any(node.node_kind == "root" and node.group_key == "advisory" for node in nodes), "應該被分組為 advisory"


def test_build_online_review_task_nodes_aggregate_required_by_labels() -> None:
    dependency = SimpleNamespace(
        project_id="cloth-config",
        version_id="dep-1",
        project_name="Cloth Config",
        version_name="17.0.0",
    )
    entry_a = models_module.PendingInstallReviewEntry(
        pending=models_module.PendingOnlineInstall(
            project_id="fabric-api",
            project_name="Fabric API",
            version=cast(Any, type("Version", (), {"version_id": "v1", "display_name": "0.120.0"})()),
        ),
        report=None,
        dependency_plan=SimpleNamespace(items=[dependency], notes=[]),
        enabled=True,
    )
    entry_b = models_module.PendingInstallReviewEntry(
        pending=models_module.PendingOnlineInstall(
            project_id="lithium",
            project_name="Lithium",
            version=cast(Any, type("Version", (), {"version_id": "v2", "display_name": "0.13.0"})()),
        ),
        report=None,
        dependency_plan=SimpleNamespace(items=[dependency], notes=[]),
        enabled=True,
    )

    nodes = _review_presentation()._build_online_review_task_nodes([entry_a, entry_b])

    root_nodes = [node for node in nodes if node.node_kind == "root"]
    assert len(root_nodes) == 2, "應該有兩個根級節點"
    assert any(node.values[2] == "Fabric API" for node in root_nodes)
    assert any(node.values[2] == "Lithium" for node in root_nodes)

    dependency_nodes = [node for node in nodes if node.node_kind == "dependency"]
    assert len(dependency_nodes) == 2, "兩個根項目都應該顯示依賴子節點"
    assert all("required-by：Fabric API、Lithium" in node.detail for node in dependency_nodes)


def test_build_online_review_task_nodes_required_by_ignores_disabled_roots() -> None:
    dependency = SimpleNamespace(
        project_id="cloth-config",
        version_id="dep-1",
        project_name="Cloth Config",
        version_name="17.0.0",
    )
    entry_a = models_module.PendingInstallReviewEntry(
        pending=models_module.PendingOnlineInstall(
            project_id="fabric-api",
            project_name="Fabric API",
            version=cast(Any, type("Version", (), {"version_id": "v1", "display_name": "0.120.0"})()),
        ),
        report=None,
        dependency_plan=SimpleNamespace(items=[dependency], notes=[]),
        enabled=True,
    )
    entry_b = models_module.PendingInstallReviewEntry(
        pending=models_module.PendingOnlineInstall(
            project_id="lithium",
            project_name="Lithium",
            version=cast(Any, type("Version", (), {"version_id": "v2", "display_name": "0.13.0"})()),
        ),
        report=None,
        dependency_plan=SimpleNamespace(items=[dependency], notes=[]),
        enabled=False,
    )

    nodes = _review_presentation()._build_online_review_task_nodes([entry_a, entry_b])

    root_nodes = [node for node in nodes if node.node_kind == "root"]
    assert len(root_nodes) == 2, "應該有兩個根級節點"
    assert any(node.values[2] == "Fabric API" and node.values[0] == "是" for node in root_nodes)
    assert any(node.values[2] == "Lithium" and node.values[0] == "否" for node in root_nodes)

    dependency_nodes = [node for node in nodes if node.node_kind == "dependency"]
    enabled_dependency = next(node for node in dependency_nodes if node.root_key == "fabric-api::v1")
    disabled_dependency = next(node for node in dependency_nodes if node.root_key == "lithium::v2")
    assert "required-by：Fabric API" in enabled_dependency.detail
    assert "Lithium" not in disabled_dependency.detail


def test_build_online_review_task_nodes_marks_advisory_dependency_as_skipped() -> None:
    entry = models_module.PendingInstallReviewEntry(
        pending=models_module.PendingOnlineInstall(
            project_id="fabric-api",
            project_name="Fabric API",
            version=cast(Any, type("Version", (), {"version_id": "v1", "display_name": "0.120.0"})()),
        ),
        report=None,
        dependency_plan=SimpleNamespace(
            items=[],
            advisory_items=[
                SimpleNamespace(
                    project_id="cloth-config",
                    version_id="dep-v1",
                    project_name="Cloth Config",
                    version_name="17.0.0",
                    maybe_installed=True,
                )
            ],
            notes=[],
        ),
        enabled=True,
    )

    nodes = _review_presentation()._build_online_review_task_nodes([entry])

    root_nodes = [node for node in nodes if node.node_kind == "root"]
    assert len(root_nodes) == 1, "應該有一個根級節點"
    assert root_nodes[0].title == "Fabric API"
    assert root_nodes[0].values[2] == "Fabric API"


def test_build_dependency_status_text_uses_resolution_fallback_label() -> None:
    dependency = SimpleNamespace(
        resolution_source="version_detail",
        resolution_confidence="fallback",
        status_note="",
    )

    status_text = build_dependency_status_text(
        dependency,
        "Fabric API",
        "Fabric API",
        False,
        True,
    )

    assert status_text == "required-by：Fabric API｜解析：版本詳情回補（中）｜處理：將自動安裝"


def test_build_online_review_root_status_text_summarizes_dependencies_warnings_and_blockers() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    entry = models_module.PendingInstallReviewEntry(
        pending=models_module.PendingOnlineInstall(
            project_id="fabric-api",
            project_name="Fabric API",
            version=cast(Any, type("Version", (), {"version_id": "v1", "display_name": "0.120.0"})()),
        ),
        report=None,
        dependency_plan=SimpleNamespace(
            items=[SimpleNamespace(project_name="Cloth Config")],
            advisory_items=[SimpleNamespace(project_name="Mod Menu", enabled=False)],
        ),
        blocking_reasons=["缺少相容版本依賴"],
        warning_messages=["建議先備份伺服器"],
        enabled=True,
    )

    status_text = build_online_review_root_status_text(entry)

    assert status_text == "需先處理｜依賴 1｜可選 1｜提醒 1｜阻擋 1"


def test_build_online_review_task_nodes_puts_summary_text_in_root_status_column() -> None:
    pending = models_module.PendingOnlineInstall(
        project_id="fabric-api",
        project_name="Fabric API",
        version=cast(Any, type("Version", (), {"version_id": "abc", "display_name": "0.120.0"})()),
    )
    review_entry = models_module.PendingInstallReviewEntry(
        pending=pending,
        report=None,
        dependency_plan=SimpleNamespace(items=[SimpleNamespace(project_name="Cloth Config", version_name="17.0.0")]),
        warning_messages=["建議先備份伺服器"],
        enabled=True,
        provider="modrinth",
        version_type="release",
    )

    nodes = _review_presentation()._build_online_review_task_nodes([review_entry])

    root_node = next(node for node in nodes if node.node_kind == "root")
    assert root_node.values[5] == "建議確認｜依賴 1｜提醒 1"


def test_install_pending_online_install_queue_deduplicates_shared_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    frame_any = cast(Any, frame)
    frame_any.parent = SimpleNamespace()

    first_version = SimpleNamespace(
        version_id="v1",
        display_name="1.0.0",
        primary_file={"filename": "first.jar", "url": "https://example.com/first.jar"},
    )
    second_version = SimpleNamespace(
        version_id="v2",
        display_name="1.0.0",
        primary_file={"filename": "second.jar", "url": "https://example.com/second.jar"},
    )
    first_pending = models_module.PendingOnlineInstall("first-mod", "First Mod", first_version)
    second_pending = models_module.PendingOnlineInstall("second-mod", "Second Mod", second_version)
    frame_any.mod_session = _mod_session(_review_server(), pending=[first_pending, second_pending])

    shared_dependency = SimpleNamespace(
        project_id="cloth-config",
        version_id="dep-v1",
        project_name="Cloth Config",
        version_name="17.0.0",
        filename="cloth-config.jar",
        download_url="https://example.com/cloth-config.jar",
    )
    handoff = review_contracts_module.ReviewExecutionHandoff(
        mode="online_install",
        context_stamp=build_review_context_stamp(_review_server(), []),
        steps=(
            review_contracts_module.ReviewInstallStep(
                kind="dependency",
                root_key="first-mod::v1",
                project_name=shared_dependency.project_name,
                version_name=shared_dependency.version_name,
                download_url=shared_dependency.download_url,
                filename=shared_dependency.filename,
                expected_hash="",
                provider="modrinth",
            ),
            review_contracts_module.ReviewInstallStep(
                kind="online_root",
                root_key="first-mod::v1",
                project_name="First Mod",
                version_name="1.0.0",
                download_url="https://example.com/first.jar",
                filename="first.jar",
                expected_hash="",
                provider="modrinth",
            ),
            review_contracts_module.ReviewInstallStep(
                kind="online_root",
                root_key="second-mod::v2",
                project_name="Second Mod",
                version_name="1.0.0",
                download_url="https://example.com/second.jar",
                filename="second.jar",
                expected_hash="",
                provider="modrinth",
            ),
        ),
        root_keys=("first-mod::v1", "second-mod::v2"),
        confirmation_prompt="",
        source_confirmation_prompt="",
        skipped_text="",
        completion_notes="",
        disabled_count=0,
        dependency_count=1,
        duplicate_dependency_count=1,
    )

    install_calls: list[tuple[str, str]] = []
    shown_messages: list[tuple[str, str]] = []
    dialog_destroyed: list[bool] = []
    queued_items: list[Any] = []

    class _ImmediateQueue:
        def put(self, item) -> None:
            queued_items.append(item)
            if callable(item):
                item()

    def _record_install(
        download_url: str,
        filename: str,
        progress_callback=None,
        provider="modrinth",
        cancel_check=None,
    ) -> str:
        _ = (progress_callback, provider, cancel_check)
        install_calls.append((download_url, filename))
        return f"/tmp/{filename}"

    frame_any.ui_queue = _ImmediateQueue()
    frame_any.local_mod_list_presenter = SimpleNamespace(load_local_mods=lambda: queued_items.append("load_local_mods"))
    frame_any._refresh_online_queue_button = lambda: None
    frame_any.update_status_safe = lambda _message: None
    frame_any.update_progress_safe = lambda _value: None
    frame_any._make_step_progress_callback = lambda *_args, **_kwargs: lambda *_inner_args, **_inner_kwargs: None
    frame_any._validate_review_handoff = lambda *_args, **_kwargs: True
    frame_any.mod_manager = SimpleNamespace(install_remote_mod_file=_record_install)

    class _ImmediateScope:
        def submit(self, work, **_kwargs):
            work()
            return

    frame_any.scope = _ImmediateScope()

    def _show_message(title: str, message: str, parent=None, message_level="info", **_kwargs) -> None:
        _ = parent
        if message_level == "info":
            shown_messages.append((title, message))

    def _confirm_dialog(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(utils_module.UIUtils, "ask_yes_no_cancel", _confirm_dialog)
    monkeypatch.setattr(utils_module.UIUtils, "show_message", _show_message)

    dialog = SimpleNamespace(destroy=lambda: dialog_destroyed.append(True))

    frame._install_pending_online_install_queue(dialog, handoff)

    assert dialog_destroyed == [True]
    assert install_calls == [
        (shared_dependency.download_url, shared_dependency.filename),
        ("https://example.com/first.jar", "first.jar"),
        ("https://example.com/second.jar", "second.jar"),
    ]
    assert any("必要依賴：已補裝 1 個" in message for _title, message in shown_messages)
    assert any("已合併 1 個重複項目，避免重複下載" in message for _title, message in shown_messages)


def test_prepare_online_install_review_entries_rebuilds_dependency_simulation_from_enabled_roots(monkeypatch) -> None:
    first_version = SimpleNamespace(
        version_id="v1",
        display_name="1.0.0",
        version_number="1.0.0",
        provider="modrinth",
        version_type="release",
        date_published="",
        changelog="",
        dependencies=[],
        primary_file={"filename": "first.jar"},
    )
    second_version = SimpleNamespace(
        version_id="v2",
        display_name="1.0.0",
        version_number="1.0.0",
        provider="modrinth",
        version_type="release",
        date_published="",
        changelog="",
        dependencies=[],
        primary_file={"filename": "second.jar"},
    )
    pending_items = [
        models_module.PendingOnlineInstall("first-mod", "First Mod", first_version),
        models_module.PendingOnlineInstall("second-mod", "Second Mod", second_version),
    ]

    monkeypatch.setattr(review_workflow_module, "resolve_modrinth_project_names", lambda _project_ids: {})
    monkeypatch.setattr(
        review_workflow_module,
        "analyze_mod_version_compatibility",
        lambda *_args, **_kwargs: SimpleNamespace(hard_errors=[], warnings=[]),
    )

    dependency_item = SimpleNamespace(
        project_id="dep-1",
        project_name="Shared Dependency",
        version_id="dep-v1",
        version_name="1.0.0",
        filename="shared-dependency.jar",
        enabled=True,
    )

    def fake_build_required_dependency_install_plan(_version, **kwargs):
        installed_mods = kwargs.get("installed_mods", [])
        root_project_name = kwargs.get("root_project_name", "")
        if root_project_name == "First Mod":
            return SimpleNamespace(items=[dependency_item], advisory_items=[], unresolved_required=[], notes=[])
        if any(getattr(mod, "platform_id", "") == "dep-1" for mod in installed_mods):
            return SimpleNamespace(items=[], advisory_items=[], unresolved_required=[], notes=[])
        return SimpleNamespace(items=[dependency_item], advisory_items=[], unresolved_required=[], notes=[])

    monkeypatch.setattr(
        review_workflow_module,
        "build_required_dependency_install_plan",
        fake_build_required_dependency_install_plan,
    )

    handoff = (
        ModReviewWorkflow(server=_review_server(), installed_mods=[])
        .start_online_session(pending_items)
        .build_handoff()
    )

    assert handoff.dependency_count == 1
    assert handoff.duplicate_dependency_count == 0


def test_prepare_online_install_review_entries_blocks_client_only_mod(monkeypatch) -> None:
    client_only_version = SimpleNamespace(
        version_id="v-client-only",
        display_name="1.0.0",
        version_number="1.0.0",
        provider="modrinth",
        version_type="release",
        date_published="",
        changelog="",
        dependencies=[],
        primary_file={"filename": "client-only.jar"},
    )
    pending_items = [
        models_module.PendingOnlineInstall(
            "client-only-mod",
            "Client Only Mod",
            client_only_version,
            server_side="unsupported",
            client_side="required",
        )
    ]

    monkeypatch.setattr(review_workflow_module, "resolve_modrinth_project_names", lambda _project_ids: {})
    monkeypatch.setattr(
        review_workflow_module,
        "analyze_mod_version_compatibility",
        lambda *_args, **_kwargs: SimpleNamespace(hard_errors=[], warnings=[]),
    )
    monkeypatch.setattr(
        review_workflow_module,
        "build_required_dependency_install_plan",
        lambda *_args, **_kwargs: SimpleNamespace(items=[], advisory_items=[], unresolved_required=[], notes=[]),
    )

    snapshot = (
        ModReviewWorkflow(server=_review_server(), installed_mods=[]).start_online_session(pending_items).snapshot()
    )

    assert snapshot.actionable_count == 0
    assert snapshot.roots[0].root_key == "client-only-mod::v-client-only"
    assert "僅 client 端" in snapshot.roots[0].summary


def test_prepare_online_install_review_entries_warns_unknown_server_side(monkeypatch) -> None:
    unknown_side_version = SimpleNamespace(
        version_id="v-unknown",
        display_name="1.0.1",
        version_number="1.0.1",
        provider="modrinth",
        version_type="release",
        date_published="",
        changelog="",
        dependencies=[],
        primary_file={"filename": "unknown-side.jar"},
    )
    pending_items = [
        models_module.PendingOnlineInstall(
            "unknown-side-mod",
            "Unknown Side Mod",
            unknown_side_version,
            server_side="unknown",
            client_side="optional",
        )
    ]

    monkeypatch.setattr(review_workflow_module, "resolve_modrinth_project_names", lambda _project_ids: {})
    monkeypatch.setattr(
        review_workflow_module,
        "analyze_mod_version_compatibility",
        lambda *_args, **_kwargs: SimpleNamespace(hard_errors=[], warnings=[]),
    )
    monkeypatch.setattr(
        review_workflow_module,
        "build_required_dependency_install_plan",
        lambda *_args, **_kwargs: SimpleNamespace(items=[], advisory_items=[], unresolved_required=[], notes=[]),
    )

    snapshot = (
        ModReviewWorkflow(server=_review_server(), installed_mods=[]).start_online_session(pending_items).snapshot()
    )

    assert snapshot.actionable_count == 1
    assert "未明確標示 server 端支援" in snapshot.roots[0].summary


def test_build_local_update_task_nodes_include_blocking_items() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    candidate = SimpleNamespace(
        project_id="lithium",
        project_name="Lithium",
        current_version="0.12.0",
        target_version_name="0.13.0",
        actionable=False,
        report=SimpleNamespace(warnings=["與現有設定可能衝突"]),
        notes=["需要更新前先停機"],
    )
    review_entry = models_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[]),
        blocking_reasons=["缺少相容版本依賴"],
        enabled=False,
        provider="modrinth",
        version_type="beta",
    )

    nodes = _review_presentation()._build_local_update_task_nodes([review_entry])

    root_node = next(node for node in nodes if node.node_kind == "root")
    assert any(node.node_kind == "root" and node.group_key == "blocked" for node in nodes)
    assert root_node.values[3] == "Modrinth"


def test_build_local_update_task_nodes_surfaces_metadata_source_in_root_and_child_node() -> None:
    candidate = SimpleNamespace(
        project_id="",
        project_name="Unknown Mod",
        current_version="1.0.0",
        target_version_name="-",
        actionable=False,
        metadata_source="unresolved",
        metadata_note="metadata ensure 失敗：找不到可用的 provider metadata 或雜湊對應結果",
        local_mod=SimpleNamespace(file_path="C:/servers/demo/mods/unknown-mod.jar"),
        report=None,
        notes=[],
    )
    review_entry = models_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[], notes=[]),
        blocking_reasons=["metadata 未識別，暫時無法自動檢查更新"],
        enabled=False,
        provider="modrinth",
        version_type="",
    )

    nodes = _review_presentation()._build_local_update_task_nodes([review_entry])

    root_node = next(node for node in nodes if node.node_kind == "root")
    assert root_node.group_key == "unknown"
    assert root_node.values[3] == "Modrinth｜待識別"
    assert root_node.values[4] == "需先識別"


def test_build_local_update_task_nodes_groups_advisory_candidate_separately() -> None:
    candidate = SimpleNamespace(
        project_id="sodium",
        project_name="Sodium",
        current_version="0.6.0",
        target_version_name="0.6.1",
        actionable=True,
        recommendation_source="project_fallback",
        recommendation_confidence="advisory",
        metadata_source="lookup",
        report=None,
        notes=[],
    )
    review_entry = models_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[], notes=[]),
        blocking_reasons=[],
        enabled=True,
        provider="modrinth",
    )

    nodes = _review_presentation()._build_local_update_task_nodes([review_entry])

    root_node = next(node for node in nodes if node.node_kind == "root")
    assert root_node.group_key == "advisory"
    assert root_node.values[4] == "建議確認"


def test_build_local_update_task_nodes_groups_retryable_candidate_separately() -> None:
    candidate = SimpleNamespace(
        project_id="",
        project_name="Sodium",
        current_version="0.6.0",
        target_version_name="",
        actionable=False,
        recommendation_source="stale_metadata",
        recommendation_confidence="retryable",
        metadata_source="stale_provider",
        metadata_note="stale metadata 重查失敗：已停用自動更新並保留舊識別供人工判讀",
        report=None,
        notes=[],
    )
    review_entry = models_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[], notes=[]),
        blocking_reasons=["provider metadata 已過期且重查失敗，已暫停自動更新以避免錯誤建議"],
        enabled=False,
        provider="modrinth",
    )

    nodes = _review_presentation()._build_local_update_task_nodes([review_entry])

    root_node = next(node for node in nodes if node.node_kind == "root")
    assert root_node.group_key == "retryable"
    assert root_node.values[4] == "可重試"


def test_build_local_update_review_subtitle_includes_failure_matrix_counts() -> None:
    text = build_local_update_review_subtitle(
        "全部模組",
        2,
        1,
        advisory_count=1,
        retryable_count=1,
        unknown_count=1,
    )

    assert text == "範圍：全部模組｜可執行更新 2 項｜建議確認 1 項｜可重試 1 項｜待識別 1 項｜阻擋 1 項"


def test_add_pending_online_install_blocks_client_only_mod(monkeypatch) -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    frame_any = cast(Any, frame)
    frame_any.mod_session = _mod_session()
    frame_any.parent = SimpleNamespace()
    frame_any.update_status = lambda _message: None
    frame_any.update_status_safe = lambda _message: None
    frame_any._refresh_online_queue_button = lambda: None

    messages: list[tuple[str, str]] = []

    def _show_message(title: str, message: str, _parent=None, message_level="info", **_kwargs) -> None:
        if message_level == "warning":
            messages.append((title, message))

    monkeypatch.setattr(utils_module.UIUtils, "show_message", _show_message)

    blocked_version = SimpleNamespace(version_id="v-client-only", display_name="1.0.0")
    added = frame._add_pending_online_install(
        models_module.PendingOnlineInstall(
            "client-only-mod",
            "Client Only Mod",
            blocked_version,
            server_side="unsupported",
            client_side="required",
        )
    )

    assert added is False
    assert frame_any.mod_session.pending_online_installs == ()
    assert messages == [
        (
            "無法加入安裝清單",
            "此模組標記為僅 client 端（server_side=unsupported），不可安裝到伺服器",
        )
    ]


def test_add_pending_online_install_replaces_same_version_item(monkeypatch) -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    frame_any = cast(Any, frame)
    frame_any.mod_session = _mod_session()
    frame_any.parent = SimpleNamespace()
    frame_any.update_status = lambda _message: None
    frame_any.update_status_safe = lambda _message: None
    frame_any._refresh_online_queue_button = lambda: None
    monkeypatch.setattr(utils_module.UIUtils, "show_message", lambda *_args, **_kwargs: None)

    first_version = SimpleNamespace(version_id="v1", display_name="1.0.0")
    second_version = SimpleNamespace(version_id="v1", display_name="1.0.1")

    first_added = frame._add_pending_online_install(
        models_module.PendingOnlineInstall("fabric-api", "Fabric API", first_version)
    )
    second_added = frame._add_pending_online_install(
        models_module.PendingOnlineInstall("fabric-api", "Fabric API Updated", second_version)
    )

    assert first_added is True
    assert second_added is True
    assert len(frame_any.mod_session.pending_online_installs) == 1
    assert frame_any.mod_session.pending_online_installs[0].project_name == "Fabric API Updated"


def test_build_local_update_review_subtitle_includes_migrated_snapshot_count() -> None:
    text = build_local_update_review_subtitle(
        "全部模組",
        1,
        0,
        migrated_snapshot_count=2,
    )

    assert text == "範圍：全部模組｜可執行更新 1 項｜快照遷移 2 項"


def test_build_dependency_snapshot_migration_note_formats_summary_line() -> None:
    telemetry = {
        "checked": 3,
        "migrated": 1,
        "replayed": 2,
        "fallback_rebuild": 1,
    }

    note = _review_presentation(telemetry)._build_dependency_snapshot_migration_note()

    assert note == "依賴快照遷移觀測：檢查 3、自動遷移 1、成功回放 2、回放失敗改重建 1"


def test_build_local_update_review_key_is_unique_for_same_project_id_with_different_files() -> None:
    candidate_a = SimpleNamespace(
        project_id="Ha28R6CL",
        local_mod=SimpleNamespace(file_path="C:/servers/a/mods/kotlin-a.jar"),
    )
    candidate_b = SimpleNamespace(
        project_id="Ha28R6CL",
        local_mod=SimpleNamespace(file_path="C:/servers/a/mods/kotlin-b.jar"),
    )

    key_a = build_local_update_review_key(candidate_a)
    key_b = build_local_update_review_key(candidate_b)

    assert key_a != key_b
    assert key_a.startswith("project::Ha28R6CL::")
    assert key_b.startswith("project::Ha28R6CL::")


def test_format_review_overview_text_includes_preflight_notes() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    entries = [
        models_module.PendingInstallReviewEntry(
            pending=cast(Any, object()),
            report=None,
            dependency_plan=cast(Any, object()),
            enabled=True,
        )
    ]
    nodes = [
        models_module.ReviewTaskNode(
            node_id="root",
            root_key="root",
            group_key="enabled",
            title="模組",
            values=("是", "Modrinth", "Fabric API", "0.120.0", "release", "可安裝"),
            node_kind="root",
        ),
        models_module.ReviewTaskNode(
            node_id="root::warning::0",
            root_key="root",
            group_key="enabled",
            title="提醒",
            values=("-", "-", "Fabric API", "-", "-", "建議先備份"),
            node_kind="warning",
            parent_id="root",
        ),
    ]

    text = format_review_overview_text(
        entries,
        nodes,
        action_label="安裝",
        global_notes=["已完成 metadata 預檢"],
        deduped_dependency_count=2,
    )

    assert "Task graph：1 個根任務" in text
    assert "目前將安裝 1 個根項目" in text
    assert "已合併 2 個重複依賴" in text
    assert "預檢：已完成 metadata 預檢" in text


def test_format_completion_notes_deduplicates_messages() -> None:
    text = format_completion_notes(["建議先備份", "建議先備份", "需重啟伺服器"])

    assert text.count("建議先備份") == 1
    assert "需重啟伺服器" in text


def test_format_online_version_report_includes_provider_and_changelog() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    version = cast(
        Any,
        type(
            "Version",
            (),
            {
                "display_name": "1.2.0",
                "provider": "modrinth",
                "game_versions": ["1.21.1"],
                "loaders": ["fabric"],
                "version_type": "release",
                "date_published": "2026-03-01T12:00:00Z",
                "changelog": "Fixed crash when syncing registry state.",
            },
        )(),
    )

    report_text = format_online_version_report(version, None)

    assert "來源：Modrinth" in report_text
    assert "版本類型：release" in report_text
    assert "發布時間：2026-03-01 12:00" in report_text
    assert "更新內容：" in report_text
    assert "Fixed crash when syncing registry state." in report_text


def test_format_local_update_review_text_includes_metadata_source() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    candidate = SimpleNamespace(
        project_name="Sodium",
        current_version="0.6.0",
        target_version_name="0.6.1",
        metadata_source="hash",
        recommendation_source="hash_metadata",
        recommendation_confidence="high",
        notes=[],
        report=None,
    )
    review_entry = models_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[], notes=[]),
        blocking_reasons=[],
        enabled=True,
        provider="modrinth",
        version_type="release",
        date_published="2026-03-01T12:00:00Z",
        changelog="",
    )

    text = format_local_update_review_text(review_entry)

    assert "Metadata 來源：雜湊比對" in text
    assert "更新建議來源：雜湊 metadata" in text
    assert "更新建議可信度：高" in text


def test_format_pending_install_review_text_includes_summary_lines() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    version = cast(
        Any,
        type(
            "Version",
            (),
            {
                "display_name": "1.2.0",
                "provider": "modrinth",
                "game_versions": ["1.21.1"],
                "loaders": ["fabric"],
                "version_type": "release",
                "date_published": "2026-03-01T12:00:00Z",
                "changelog": "",
            },
        )(),
    )
    review_entry = models_module.PendingInstallReviewEntry(
        pending=models_module.PendingOnlineInstall(
            project_id="fabric-api",
            project_name="Fabric API",
            version=version,
        ),
        report=None,
        dependency_plan=SimpleNamespace(
            items=[SimpleNamespace(project_name="Cloth Config", version_name="17.0.0")],
            advisory_items=[SimpleNamespace(project_name="Mod Menu", version_name="12.0.0", enabled=False)],
            notes=[],
        ),
        blocking_reasons=["缺少相容版本依賴"],
        warning_messages=[],
        enabled=True,
        provider="modrinth",
        version_type="release",
    )

    text = format_pending_install_review_text(review_entry)

    assert "摘要：需先處理｜依賴 1｜可選 1｜阻擋 1" in text
    assert "處理等級：需先處理" in text
    assert "- 將自動補裝 1 個必要依賴" in text
    assert "- 可選依賴 1 項（已選 0 項）" in text
    assert "- 目前有 1 個阻擋原因需先處理" in text


def test_format_pending_install_review_text_includes_client_install_reminder_for_server_and_client_mod() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    version = cast(
        Any,
        type(
            "Version",
            (),
            {
                "display_name": "1.2.0",
                "provider": "modrinth",
                "game_versions": ["1.21.1"],
                "loaders": ["fabric"],
                "version_type": "release",
                "date_published": "2026-03-01T12:00:00Z",
                "changelog": "",
            },
        )(),
    )
    review_entry = models_module.PendingInstallReviewEntry(
        pending=models_module.PendingOnlineInstall(
            project_id="sodium",
            project_name="Sodium",
            version=version,
            server_side="required",
            client_side="optional",
        ),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        blocking_reasons=[],
        warning_messages=[],
        enabled=True,
        provider="modrinth",
        version_type="release",
    )

    text = format_pending_install_review_text(review_entry)

    assert "提醒：此模組同時支援 client 端" in text


def test_format_local_update_review_text_includes_unresolved_metadata_state() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    candidate = SimpleNamespace(
        project_name="Unknown Mod",
        current_version="1.0.0",
        target_version_name="",
        metadata_source="unresolved",
        recommendation_source="project_fallback",
        recommendation_confidence="advisory",
        metadata_note="metadata ensure 失敗：找不到可用的 provider metadata 或雜湊對應結果",
        notes=[],
        report=None,
    )
    review_entry = models_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[], notes=[]),
        blocking_reasons=["metadata 未識別，暫時無法自動檢查更新"],
        enabled=False,
        provider="modrinth",
        version_type="",
        date_published="",
        changelog="",
    )

    text = format_local_update_review_text(review_entry)

    assert "Metadata 來源：尚未識別" in text
    assert "更新建議來源：專案 fallback" in text
    assert "更新建議可信度：提示" in text
    assert "Metadata 狀態：metadata ensure 失敗" in text


def test_format_local_update_review_text_includes_client_install_reminder_for_server_and_client_mod() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    candidate = SimpleNamespace(
        project_name="Sodium",
        current_version="0.6.0",
        target_version_name="0.6.1",
        metadata_source="hash",
        recommendation_source="hash_metadata",
        recommendation_confidence="high",
        notes=[],
        report=None,
        server_side="required",
        client_side="optional",
    )
    review_entry = models_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[], notes=[]),
        blocking_reasons=[],
        enabled=True,
        provider="modrinth",
        version_type="release",
        date_published="2026-03-01T12:00:00Z",
        changelog="",
    )

    text = format_local_update_review_text(review_entry)

    assert "提醒：此模組同時支援 client 端" in text


def test_build_local_update_review_key_falls_back_to_file_path_when_project_id_missing() -> None:
    candidate = SimpleNamespace(
        project_id="",
        filename="unknown-mod.jar",
        local_mod=SimpleNamespace(file_path="C:/servers/demo/mods/unknown-mod.jar", filename="unknown-mod.jar"),
    )

    key = build_local_update_review_key(candidate)

    assert key == "local::C:/servers/demo/mods/unknown-mod.jar"


def test_prepare_local_update_review_entries_uses_fallback_root_key_when_project_id_missing() -> None:
    candidate = SimpleNamespace(
        project_id="",
        project_name="Unknown Mod",
        filename="unknown-mod.jar",
        local_mod=SimpleNamespace(file_path="C:/servers/demo/mods/unknown-mod.jar"),
        actionable=True,
        hard_errors=[],
        current_issues=[],
        dependency_issues=[],
        notes=[],
        update_available=False,
        target_filename="",
        target_version_name="",
        current_version="1.0.0",
        metadata_source="unresolved",
        metadata_note="",
        recommendation_source="metadata_unresolved",
        recommendation_confidence="blocked",
    )

    session = ModReviewWorkflow(server=_review_server(), installed_mods=[]).start_local_update_session(
        SimpleNamespace(candidates=[candidate], notes=[], metadata_summary=SimpleNamespace(notes=[])),
        "全部模組",
    )
    root_key = "local::C:/servers/demo/mods/unknown-mod.jar"
    assert session.apply_selection({root_key}, False) is True
    snapshot = session.snapshot()

    assert snapshot.roots[0].root_key == root_key
    assert snapshot.enabled_count == 0


def test_load_local_mods_discards_stale_scan_results(tmp_path: Path) -> None:
    frame = ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)
    server_a = SimpleNamespace(name="server-a", path=str(tmp_path / "server-a"))
    server_b = SimpleNamespace(name="server-b", path=str(tmp_path / "server-b"))
    sentinel_mods = [SimpleNamespace(filename="sentinel.jar")]
    enhancement_calls: list[str] = []
    queued_items: list[Any] = []

    old_session = _mod_session(server_a, local_mods=sentinel_mods)
    frame.mod_session = old_session
    frame.mod_manager = SimpleNamespace()
    frame.update_status_safe = lambda _message: None
    frame.update_progress_safe = lambda _value: None
    frame.refresh_local_list = lambda: queued_items.append("refresh_local_list")
    frame.ui_queue = SimpleNamespace(put=lambda item: queued_items.append(item))
    presenter = ui_module.LocalModListPresenter(frame)
    presenter.enhance_local_mods = lambda _scope=None: enhancement_calls.append("called")

    def _scan_mods() -> list[Any]:
        old_session.invalidate()
        frame.mod_session = _mod_session(server_b, local_mods=sentinel_mods)
        return [
            SimpleNamespace(
                filename="example.jar",
                status=models_module.ModStatus.ENABLED,
                file_path=str(tmp_path / "server-a" / "mods" / "example.jar"),
                name="Example Mod",
                author="Example",
                description="Example description",
                version="1.0.0",
                loader_type="fabric",
            )
        ]

    frame.mod_manager.scan_mods = _scan_mods

    class _ImmediateScope:
        def submit(self, work, **_kwargs):
            work()
            return

    frame.scope = _ImmediateScope()

    presenter.load_local_mods()

    assert frame.mod_session.local_mods == tuple(sentinel_mods)
    assert enhancement_calls == []
    assert queued_items == []


def test_resolve_pending_install_review_project_page_url_prefers_homepage_url() -> None:
    review_entry = models_module.PendingInstallReviewEntry(
        pending=models_module.PendingOnlineInstall(
            project_id="AABBCCDD",
            project_name="Sodium",
            version=SimpleNamespace(),
            homepage_url="https://example.com/sodium",
            source_url="https://modrinth.com/mod/sodium",
        ),
        report=None,
        dependency_plan=SimpleNamespace(items=[], notes=[]),
    )

    assert resolve_pending_install_review_project_page_url(review_entry) == "https://example.com/sodium"


def test_resolve_local_update_review_project_page_url_uses_slug_then_project_id() -> None:
    review_entry = models_module.LocalUpdateReviewEntry(
        candidate=SimpleNamespace(
            project_id="P7dR8mSH",
            local_mod=SimpleNamespace(platform_slug="fabric-api", platform_id="ignored-project-id"),
        ),
        dependency_plan=SimpleNamespace(items=[], notes=[]),
    )

    assert resolve_local_update_review_project_page_url(review_entry) == "https://modrinth.com/mod/fabric-api"


def test_resolve_local_update_review_project_page_url_skips_unresolved_candidates() -> None:
    review_entry = models_module.LocalUpdateReviewEntry(
        candidate=SimpleNamespace(
            project_id="",
            local_mod=SimpleNamespace(platform_slug="", platform_id=""),
        ),
        dependency_plan=SimpleNamespace(items=[], notes=[]),
    )

    assert resolve_local_update_review_project_page_url(review_entry) == ""


def test_cache_local_dependency_plan_snapshot_persists_provider_aware_payload() -> None:
    captured: dict[str, Any] = {}

    class _StubIndexManager:
        def get_review_metadata(self, _file_path: Path) -> dict[str, Any]:
            return {}

        def replace_review_metadata(self, file_path: Path, provider_metadata: dict[str, Any]) -> None:
            captured["file_path"] = file_path
            captured["provider_metadata"] = provider_metadata

    snapshot_store = LocalReviewSnapshotStore(
        SimpleNamespace(index_manager=_StubIndexManager()),
        {"checked": 0, "migrated": 0, "replayed": 0, "fallback_rebuild": 0},
    )
    candidate = SimpleNamespace(
        project_id="AANobbMI",
        project_name="Sodium",
        target_version_id="target-ver-1",
        target_version_name="1.0.0",
        local_mod=SimpleNamespace(file_path="C:/servers/Fabric/mods/sodium.jar"),
    )
    dependency_plan = SimpleNamespace(
        items=[
            SimpleNamespace(
                project_id="P7dR8mSH",
                project_name="Fabric API",
                version_id="dep-ver-1",
                version_name="0.100.0",
                filename="fabric-api.jar",
                download_url="https://cdn.example/fabric-api.jar",
                parent_name="Sodium",
                resolution_source="project_id",
                resolution_confidence="direct",
                enabled=True,
                is_optional=False,
            )
        ],
        advisory_items=[],
        unresolved_required=[],
        notes=["dep-note"],
    )

    snapshot_store.save(candidate, dependency_plan)

    payload = captured["provider_metadata"]["dependency_plan_v1"]
    assert captured["file_path"] == Path("C:/servers/Fabric/mods/sodium.jar")
    assert payload["root_project_id"] == "AANobbMI"
    assert payload["root_project_name"] == "Sodium"
    assert payload["root_target_version_id"] == "target-ver-1"
    assert payload["root_target_version_name"] == "1.0.0"
    assert "root_enabled" not in payload
    assert payload["plan_source"] == "local_update_review"
    assert payload["items"][0]["project_id"] == "P7dR8mSH"
    assert payload["items"][0]["provider"] == "modrinth"
    assert payload["items"][0]["required_by"] == ["Sodium"]
    assert payload["items"][0]["decision_source"] == "required:auto"
    assert payload["items"][0]["graph_depth"] == 1
    assert payload["items"][0]["edge_kind"] == "required"
    assert payload["graph_edges"][0]["edge"] == "required"
    assert payload["graph_edges"][0]["depth"] == 1


def test_prepare_local_update_review_entries_replays_cached_dependency_plan_snapshot(monkeypatch) -> None:
    class _StubIndexManager:
        def get_review_metadata(self, _file_path: Path) -> dict[str, Any]:
            return {
                "dependency_plan_v1": {
                    "schema_version": 1,
                    "plan_source": "local_update_review",
                    "root_project_id": "AANobbMI",
                    "root_project_name": "Sodium",
                    "root_target_version_id": "target-ver-1",
                    "root_target_version_name": "1.0.0",
                    "root_enabled": False,
                    "items": [
                        {
                            "project_id": "P7dR8mSH",
                            "project_name": "Fabric API",
                            "version_id": "dep-ver-1",
                            "version_name": "0.100.0",
                            "filename": "fabric-api.jar",
                            "download_url": "https://cdn.example/fabric-api.jar",
                            "provider": "modrinth",
                            "required_by": ["Sodium"],
                            "decision_source": "required:auto",
                            "enabled": True,
                            "is_optional": False,
                            "graph_depth": 1,
                            "edge_kind": "required",
                            "edge_source": "required:modrinth_dependency",
                        }
                    ],
                    "advisory_items": [],
                    "graph_edges": [
                        {
                            "to_project_id": "P7dR8mSH",
                            "to_version_id": "dep-ver-1",
                            "required_by": ["Sodium"],
                            "edge": "required",
                            "source": "required:modrinth_dependency",
                            "depth": 1,
                            "decision_source": "required:auto",
                            "is_optional": False,
                        }
                    ],
                    "unresolved_required": [],
                    "notes": ["restored"],
                }
            }

    telemetry = {"checked": 0, "migrated": 0, "replayed": 0, "fallback_rebuild": 0}
    manager = SimpleNamespace(index_manager=_StubIndexManager())
    monkeypatch.setattr(
        review_workflow_module,
        "build_required_dependency_install_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should use cached dependency plan snapshot")),
    )
    candidate = SimpleNamespace(
        project_id="AANobbMI",
        project_name="Sodium",
        target_version_id="target-ver-1",
        target_version_name="1.0.0",
        target_filename="sodium-new.jar",
        target_version=SimpleNamespace(provider="modrinth"),
        current_version="0.6.0",
        metadata_source="cached",
        metadata_note="",
        recommendation_source="hash_metadata",
        recommendation_confidence="high",
        update_available=True,
        actionable=True,
        hard_errors=[],
        current_issues=[],
        dependency_issues=[],
        notes=[],
        local_mod=SimpleNamespace(file_path="C:/servers/Fabric/mods/sodium.jar"),
        filename="sodium.jar",
    )
    session = ModReviewWorkflow(
        server=_review_server(),
        installed_mods=[],
        telemetry=telemetry,
        snapshot_store=LocalReviewSnapshotStore(manager, telemetry),
    ).start_local_update_session(
        SimpleNamespace(candidates=[candidate], notes=[], metadata_summary=SimpleNamespace(notes=[])),
        "全部模組",
    )
    snapshot = session.snapshot()

    assert snapshot.enabled_count == 0
    assert "Fabric API" in snapshot.roots[0].summary
    assert telemetry["replayed"] == 1


def test_prepare_local_update_review_entries_rebuilds_when_cached_snapshot_version_mismatch(monkeypatch) -> None:
    class _StubIndexManager:
        def get_review_metadata(self, _file_path: Path) -> dict[str, Any]:
            return {
                "dependency_plan_v1": {
                    "schema_version": 1,
                    "plan_source": "local_update_review",
                    "root_project_id": "AANobbMI",
                    "root_project_name": "Sodium",
                    "root_target_version_id": "another-target-version",
                    "items": [],
                    "advisory_items": [],
                    "graph_edges": [],
                    "unresolved_required": [],
                    "notes": ["stale"],
                }
            }

        def replace_review_metadata(self, _file_path: Path, _provider_metadata: dict[str, Any]) -> None:
            return

    telemetry = {"checked": 0, "migrated": 0, "replayed": 0, "fallback_rebuild": 0}
    manager = SimpleNamespace(index_manager=_StubIndexManager())
    calls = {"count": 0}

    def _rebuilt_dependency_plan(*_args, **_kwargs):
        calls["count"] += 1
        return SimpleNamespace(
            items=[
                SimpleNamespace(
                    project_id="rebuilt",
                    project_name="Rebuilt Dependency",
                    version_id="dep-v1",
                    version_name="1.0.0",
                    filename="rebuilt.jar",
                    download_url="https://example.com/rebuilt.jar",
                    enabled=True,
                    is_optional=False,
                )
            ],
            advisory_items=[],
            unresolved_required=[],
            notes=[],
        )

    monkeypatch.setattr(review_workflow_module, "build_required_dependency_install_plan", _rebuilt_dependency_plan)
    candidate = SimpleNamespace(
        project_id="AANobbMI",
        project_name="Sodium",
        target_version_id="target-ver-1",
        target_version_name="1.0.0",
        target_filename="sodium-new.jar",
        target_version=SimpleNamespace(provider="modrinth"),
        current_version="0.6.0",
        metadata_source="cached",
        metadata_note="",
        recommendation_source="hash_metadata",
        recommendation_confidence="high",
        update_available=True,
        actionable=True,
        hard_errors=[],
        current_issues=[],
        dependency_issues=[],
        notes=[],
        local_mod=SimpleNamespace(file_path="C:/servers/Fabric/mods/sodium.jar"),
        filename="sodium.jar",
    )
    session = ModReviewWorkflow(
        server=_review_server(),
        installed_mods=[],
        telemetry=telemetry,
        snapshot_store=LocalReviewSnapshotStore(manager, telemetry),
    ).start_local_update_session(
        SimpleNamespace(candidates=[candidate], notes=[], metadata_summary=SimpleNamespace(notes=[])),
        "全部模組",
    )

    assert calls["count"] == 1
    assert "Rebuilt Dependency" in session.snapshot().roots[0].summary
    assert telemetry["fallback_rebuild"] == 1


def test_prepare_local_update_review_entries_migrates_legacy_snapshot_and_persists(monkeypatch) -> None:
    captured_writes: list[dict[str, Any]] = []

    class _StubIndexManager:
        def get_review_metadata(self, _file_path: Path) -> dict[str, Any]:
            return {
                "dependency_plan_v1": {
                    "schema_version": 1,
                    "plan_source": "local_update_review",
                    "root_project_id": "AANobbMI",
                    "root_project_name": "Sodium",
                    "root_target_version_id": "target-ver-1",
                    "root_target_version_name": "1.0.0",
                    "root_enabled": True,
                    "items": [
                        {
                            "project_id": "P7dR8mSH",
                            "project_name": "Fabric API",
                            "version_id": "dep-ver-1",
                            "version_name": "0.100.0",
                            "filename": "fabric-api.jar",
                            "download_url": "https://cdn.example/fabric-api.jar",
                            "required_by": ["Sodium"],
                            "enabled": True,
                            "is_optional": False,
                        }
                    ],
                    "advisory_items": [],
                    "unresolved_required": [],
                    "notes": ["legacy-snapshot"],
                }
            }

        def replace_review_metadata(self, _file_path: Path, provider_metadata: dict[str, Any]) -> None:
            captured_writes.append(provider_metadata)

    telemetry = {"checked": 0, "migrated": 0, "replayed": 0, "fallback_rebuild": 0}
    manager = SimpleNamespace(index_manager=_StubIndexManager())
    monkeypatch.setattr(
        review_workflow_module,
        "build_required_dependency_install_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("should replay migrated snapshot instead of rebuilding")
        ),
    )
    candidate = SimpleNamespace(
        project_id="AANobbMI",
        project_name="Sodium",
        target_version_id="target-ver-1",
        target_version_name="1.0.0",
        target_filename="sodium-new.jar",
        target_version=SimpleNamespace(provider="modrinth"),
        current_version="0.6.0",
        metadata_source="cached",
        metadata_note="",
        recommendation_source="hash_metadata",
        recommendation_confidence="high",
        update_available=True,
        actionable=True,
        hard_errors=[],
        current_issues=[],
        dependency_issues=[],
        notes=[],
        local_mod=SimpleNamespace(file_path="C:/servers/Fabric/mods/sodium.jar"),
        filename="sodium.jar",
    )
    session = ModReviewWorkflow(
        server=_review_server(),
        installed_mods=[],
        telemetry=telemetry,
        snapshot_store=LocalReviewSnapshotStore(manager, telemetry),
    ).start_local_update_session(
        SimpleNamespace(candidates=[candidate], notes=[], metadata_summary=SimpleNamespace(notes=[])),
        "全部模組",
    )

    assert "Fabric API" in session.snapshot().roots[0].summary
    assert any("dependency_plan_v1" in payload for payload in captured_writes)
    migrated_snapshot = captured_writes[0]["dependency_plan_v1"]
    assert isinstance(migrated_snapshot.get("graph_edges"), list)
    assert migrated_snapshot["graph_edges"][0]["edge"] == "required"
    assert telemetry.get("checked", 0) == 1
    assert telemetry.get("migrated", 0) == 1
    assert telemetry.get("replayed", 0) == 1
    assert telemetry.get("fallback_rebuild", 0) == 0


def test_persist_local_update_dependency_plan_snapshots_writes_current_advisory_enabled_state() -> None:
    captured: dict[str, Any] = {}

    class _StubIndexManager:
        def get_review_metadata(self, _file_path: Path) -> dict[str, Any]:
            return {}

        def replace_review_metadata(self, file_path: Path, provider_metadata: dict[str, Any]) -> None:
            captured["file_path"] = file_path
            captured["provider_metadata"] = provider_metadata

    snapshot_store = LocalReviewSnapshotStore(
        SimpleNamespace(index_manager=_StubIndexManager()),
        {"checked": 0, "migrated": 0, "replayed": 0, "fallback_rebuild": 0},
    )
    candidate = SimpleNamespace(
        project_id="AANobbMI",
        project_name="Sodium",
        target_version_id="target-ver-1",
        target_version_name="1.0.0",
        local_mod=SimpleNamespace(file_path="C:/servers/Fabric/mods/sodium.jar"),
    )
    dependency_plan = SimpleNamespace(
        items=[],
        advisory_items=[
            SimpleNamespace(
                project_id="P7dR8mSH",
                project_name="Fabric API",
                version_id="dep-ver-1",
                version_name="0.100.0",
                filename="fabric-api.jar",
                download_url="https://cdn.example/fabric-api.jar",
                parent_name="Sodium",
                resolution_source="project_id",
                resolution_confidence="direct",
                enabled=True,
                is_optional=True,
            )
        ],
        unresolved_required=[],
        notes=[],
    )
    review_entry = models_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=dependency_plan,
        blocking_reasons=[],
        enabled=True,
    )

    snapshot_store.save_entries((review_entry,))

    payload = captured["provider_metadata"]["dependency_plan_v1"]
    assert captured["file_path"] == Path("C:/servers/Fabric/mods/sodium.jar")
    assert payload["root_enabled"] is True
    assert payload["advisory_items"][0]["project_id"] == "P7dR8mSH"
    assert payload["advisory_items"][0]["enabled"] is True


def test_get_online_install_review_group_key_classifies_all_states() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)

    runnable_no_warn = models_module.PendingInstallReviewEntry(
        pending=_pending_install("a", "A", "v1"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        enabled=True,
        warning_messages=[],
    )
    runnable_with_warn = models_module.PendingInstallReviewEntry(
        pending=_pending_install("b", "B", "v2"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        enabled=True,
        warning_messages=["建議手動確認 server_side 支援"],
    )
    runnable_disabled = models_module.PendingInstallReviewEntry(
        pending=_pending_install("c", "C", "v3"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        enabled=False,
        warning_messages=[],
    )
    blocked_entry = models_module.PendingInstallReviewEntry(
        pending=_pending_install("d", "D", "v4"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        blocking_reasons=["載入器不相容"],
        enabled=False,
        warning_messages=[],
    )

    assert get_online_install_review_group_key(runnable_no_warn) == "enabled"
    assert get_online_install_review_group_key(runnable_with_warn) == "advisory"
    assert get_online_install_review_group_key(runnable_disabled) == "disabled"
    assert get_online_install_review_group_key(blocked_entry) == "blocked"


def test_count_online_install_review_groups_aggregates_correctly() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)

    entries = [
        models_module.PendingInstallReviewEntry(
            pending=_pending_install(f"mod{i}", f"Mod{i}", f"v{i}"),
            report=None,
            dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
            enabled=True,
            warning_messages=[],
        )
        for i in range(3)
    ] + [
        models_module.PendingInstallReviewEntry(
            pending=_pending_install("warn1", "Warn1", "vw1"),
            report=None,
            dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
            enabled=True,
            warning_messages=["注意相容性"],
        ),
        models_module.PendingInstallReviewEntry(
            pending=_pending_install("block1", "Block1", "vb1"),
            report=None,
            dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
            blocking_reasons=["缺少依賴"],
            enabled=False,
            warning_messages=[],
        ),
    ]

    counts = count_online_install_review_groups(entries)

    assert counts["enabled"] == 3
    assert counts["advisory"] == 1
    assert counts["blocked"] == 1
    assert counts.get("disabled", 0) == 0


def test_build_online_install_execution_prompt_advisory_and_blocked() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)

    actionable_entry = models_module.PendingInstallReviewEntry(
        pending=_pending_install("a", "A", "v1"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        enabled=True,
        warning_messages=[],
    )
    advisory_entry = models_module.PendingInstallReviewEntry(
        pending=_pending_install("b", "B", "v2"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        enabled=True,
        warning_messages=["client_side 支援請確認"],
    )
    blocked_entry = models_module.PendingInstallReviewEntry(
        pending=_pending_install("c", "C", "v3"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        blocking_reasons=["Minecraft 版本不相容"],
        enabled=False,
        warning_messages=[],
    )

    prompt = build_online_install_execution_prompt([actionable_entry, advisory_entry, blocked_entry])

    assert prompt is not None
    assert "建議確認：1 項" in prompt
    assert "需先處理：1 項" in prompt
    assert "將繼續安裝其餘 2 個可安裝項目" in prompt


def test_build_online_install_execution_prompt_returns_none_for_clean_queue() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)

    entries = [
        models_module.PendingInstallReviewEntry(
            pending=_pending_install(f"m{i}", f"M{i}", f"v{i}"),
            report=None,
            dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
            enabled=True,
            warning_messages=[],
        )
        for i in range(3)
    ]

    assert build_online_install_execution_prompt(entries) is None


def test_build_online_install_execution_prompt_returns_none_for_advisory_only() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)

    entries = [
        models_module.PendingInstallReviewEntry(
            pending=_pending_install(f"m{i}", f"M{i}", f"v{i}"),
            report=None,
            dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
            enabled=True,
            warning_messages=["相容性提醒"],
        )
        for i in range(2)
    ]

    assert build_online_install_execution_prompt(entries) is None


def test_build_online_review_root_status_text_uses_shared_group_label() -> None:
    ui_module.ModManagementFrame.__new__(ui_module.ModManagementFrame)

    clean_entry = models_module.PendingInstallReviewEntry(
        pending=_pending_install("a", "A", "v1"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        enabled=True,
        warning_messages=[],
    )
    advisory_entry = models_module.PendingInstallReviewEntry(
        pending=_pending_install("b", "B", "v2"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        enabled=True,
        warning_messages=["注意事項"],
    )
    blocked_entry = models_module.PendingInstallReviewEntry(
        pending=_pending_install("c", "C", "v3"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        blocking_reasons=["相容性阻擋"],
        enabled=False,
        warning_messages=[],
    )

    assert "可安裝" in build_online_review_root_status_text(clean_entry)
    assert "建議確認" in build_online_review_root_status_text(advisory_entry)
    assert "需先處理" in build_online_review_root_status_text(blocked_entry)
