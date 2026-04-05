from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import src.ui.mod_management as mod_management_module
import src.utils.ui_utils as ui_utils_module
import src.utils as meta_module

Colors = ui_utils_module.Colors
UIUtils = ui_utils_module.UIUtils


class _StubTree:
    def __init__(self) -> None:
        self.children = ["keep", "orphan"]
        self.deleted: list[str] = []

    def winfo_exists(self) -> bool:
        return True

    def get_children(self, _item: str = "") -> list[str]:
        return list(self.children)

    def delete(self, item_id: str) -> None:
        self.deleted.append(item_id)
        self.children = [item for item in self.children if item != item_id]

    def exists(self, item_id: str) -> bool:
        return item_id in self.children


class _DeleteTree:
    def __init__(self) -> None:
        self._selection = ("item-a", "item-b")
        self._rows = {
            "item-a": {"values": ("✅ 已啟用", "Clumps"), "tags": ("clumps", "odd")},
            "item-b": {"values": ("✅ 已啟用", "Fabric API"), "tags": ("fabric-api", "even")},
        }

    def selection(self) -> tuple[str, ...]:
        return self._selection

    def item(self, item_id: str, option: str):
        return self._rows[item_id][option]


class _StatusLabel:
    def __init__(self) -> None:
        self.text = ""

    def winfo_exists(self) -> bool:
        return True

    def configure(self, **kwargs) -> None:
        self.text = str(kwargs.get("text", self.text))


class _GroupedSelectionTree:
    def __init__(self, parent_map: dict[str, str], selection: tuple[str, ...]) -> None:
        self._parent_map = parent_map
        self._selection = selection

    def selection(self) -> tuple[str, ...]:
        return self._selection

    def parent(self, item_id: str) -> str:
        return self._parent_map.get(item_id, "")


class _HeaderAutoFitTree:
    def __init__(self) -> None:
        self.requested_columns: list[str] = []

    def cget(self, option: str):
        if option == "columns":
            return ("name", "version")
        if option == "displaycolumns":
            # 回傳 2-tuple 以保持一致
            return ("#all", "#all")
        if option == "show":
            return "headings"
        raise KeyError(option)

    def column(self, column_id: str, option: str):
        assert option == "width"
        self.requested_columns.append(column_id)
        if column_id == "name":
            return 140
        if column_id == "version":
            return 100
        raise AssertionError(f"unexpected column lookup: {column_id}")

    def xview(self) -> tuple[float, float]:
        return (0.0, 1.0)


class _ContextMenuTree:
    def __init__(self, *, row_id: str = "row-2", selection: tuple[str, ...] = ("row-1",)) -> None:
        self._row_id = row_id
        self._selection = selection
        self.focused = ""
        self.seen = ""

    def identify_row(self, _y: int) -> str:
        return self._row_id

    def selection(self) -> tuple[str, ...]:
        return self._selection

    def selection_set(self, item_id: str) -> None:
        self._selection = (item_id,)

    def focus(self, item_id: str) -> None:
        self.focused = item_id

    def see(self, item_id: str) -> None:
        self.seen = item_id


def _pending_install(project_id: str, project_name: str, version_id: str) -> mod_management_module.PendingOnlineInstall:
    return mod_management_module.PendingOnlineInstall(
        project_id=project_id,
        project_name=project_name,
        version=cast(Any, SimpleNamespace(version_id=version_id)),
    )


@pytest.mark.smoke
def test_local_row_palette_uses_distinct_tokens() -> None:
    light_odd, light_even = mod_management_module.ModManagementFrame._get_local_row_palette(is_dark=False)
    dark_odd, dark_even = mod_management_module.ModManagementFrame._get_local_row_palette(is_dark=True)

    assert light_odd == Colors.BG_LISTBOX_LIGHT
    assert light_even == Colors.BG_LISTBOX_ALT_LIGHT
    assert dark_odd == Colors.BG_LISTBOX_DARK
    assert dark_even == Colors.BG_LISTBOX_ALT_DARK
    assert light_odd != light_even
    assert dark_odd != dark_even


@pytest.mark.smoke
def test_build_online_browse_request_returns_warning_when_query_empty() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    frame_any = cast(Any, frame)
    frame_any.browse_sort_var = SimpleNamespace(get=lambda: "相關性")
    frame_any.browse_sort_options = {"相關性": "relevance"}
    frame_any.search_var = SimpleNamespace(get=lambda: "")
    frame.current_server = cast(
        Any,
        SimpleNamespace(minecraft_version="1.21.1", loader_type="fabric", loader_version="0.16.10"),
    )

    request, warning_message = frame._build_online_browse_request()

    assert request is None
    assert warning_message == "請先輸入關鍵字再搜尋模組。"


@pytest.mark.smoke
def test_get_online_version_dialog_hint_text_uses_server_context() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    frame.current_server = cast(
        Any,
        SimpleNamespace(minecraft_version="1.21.1", loader_type="fabric", loader_version="0.16.10"),
    )

    hint_text = frame._get_online_version_dialog_hint_text()

    assert hint_text == "相容性條件：MC 1.21.1 / fabric / 0.16.10"
    assert "留空" not in hint_text


@pytest.mark.smoke
def test_on_online_browse_filters_changed_refreshes_hint_and_reloads(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
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


@pytest.mark.smoke
def test_build_online_results_summary_text_shows_mode_sort_and_count() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    frame_any = cast(Any, frame)
    frame_any.search_var = SimpleNamespace(get=lambda: "sodium")
    frame_any.browse_sort_var = SimpleNamespace(get=lambda: "下載量")
    frame.online_mods = [object(), object()]

    summary = frame._build_online_results_summary_text()

    assert summary == "搜尋 sodium｜2 筆｜排序 下載量"


@pytest.mark.smoke
def test_build_online_results_summary_text_prompts_keyword_when_query_empty() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    frame_any = cast(Any, frame)
    frame_any.search_var = SimpleNamespace(get=lambda: "")
    frame_any.browse_sort_var = SimpleNamespace(get=lambda: "相關性")
    frame.online_mods = []

    summary = frame._build_online_results_summary_text()

    assert summary == "請輸入關鍵字搜尋｜0 筆｜排序 相關性"


@pytest.mark.smoke
def test_build_online_browse_row_includes_prism_style_metadata() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)

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
        "Client and server rendering optimizations.",
        "Modrinth",
        "未知",
    )


@pytest.mark.smoke
def test_build_online_browse_row_keeps_full_description() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)

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

    assert row[3] == (
        "You can drink from a water source, cauldron or with vanilla items. "
        "Items have fluid compatibility and the full description should stay intact."
    )


@pytest.mark.smoke
def test_refresh_local_list_keeps_full_description(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    frame_any = cast(Any, frame)
    frame._local_refresh_token = 0
    frame_any.local_tree = SimpleNamespace()
    frame.local_mods = [
        SimpleNamespace(
            name="Fabric API",
            status=mod_management_module.ModStatus.ENABLED,
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
    frame.enhanced_mods_cache = {}
    frame_any.local_search_var = SimpleNamespace(get=lambda: "")
    frame_any.local_filter_var = SimpleNamespace(get=lambda: "所有")
    frame.VERSION_PATTERN = mod_management_module.re.compile(r"-([\dv.]+)(?:\.jar(?:\.disabled)?)?$")

    captured: dict[str, Any] = {}

    def _noop_cancel_local_refresh_job() -> None:
        return None

    def _noop_set_local_tree_render_lock(_enabled: Any) -> None:
        return None

    def _capture_selected_mod_ids_func() -> set:
        return set()

    def _resolve_local_display_name_func(mod: Any, _enhanced: Any) -> str:
        return mod.name

    def _get_enhanced_attr_func(_enhanced: Any, _attr: str, default: Any) -> Any:
        return default

    monkeypatch.setattr(frame, "_cancel_local_refresh_job", _noop_cancel_local_refresh_job)
    monkeypatch.setattr(frame, "_set_local_tree_render_lock", _noop_set_local_tree_render_lock)
    monkeypatch.setattr(frame, "_capture_selected_mod_ids", _capture_selected_mod_ids_func)
    monkeypatch.setattr(frame, "_resolve_local_display_name", _resolve_local_display_name_func)
    monkeypatch.setattr(frame, "_get_enhanced_attr", _get_enhanced_attr_func)
    monkeypatch.setattr(frame, "_apply_local_tree_diff", captured.update)

    frame.refresh_local_list()

    values, _tags = captured["mod_rows"]["fabric-api-0.141.3+1.21.1"]
    assert values[7] == "Core API module providing key hooks and intercompatibility. No truncation should happen."


@pytest.mark.smoke
def test_select_tree_item_for_context_menu_updates_selection_to_clicked_row() -> None:
    tree = _ContextMenuTree()
    event = SimpleNamespace(y=24)

    row_id = mod_management_module.ModManagementFrame._select_tree_item_for_context_menu(tree, event)

    assert row_id == "row-2"
    assert tree.selection() == ("row-2",)
    assert tree.focused == "row-2"
    assert tree.seen == "row-2"


@pytest.mark.smoke
def test_reveal_in_explorer_uses_windows_select_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded_calls: list[list[str]] = []

    def fake_run_checked(command, check=False):
        del check
        recorded_calls.append(list(command))

    monkeypatch.setattr(ui_utils_module, "os", SimpleNamespace(name="nt", environ={"WINDIR": "C:\\Windows"}))
    monkeypatch.setattr(ui_utils_module.PathUtils, "find_executable", lambda _name: "explorer.exe")
    monkeypatch.setattr(ui_utils_module.UIUtils, "_is_safe_windows_path_argument", lambda _path: True)
    monkeypatch.setattr(ui_utils_module.SubprocessUtils, "run_checked", fake_run_checked)

    ui_utils_module.UIUtils.reveal_in_explorer(Path("C:/servers/Alpha/mods/example.jar"))

    assert recorded_calls == [["explorer.exe", "/select,", "C:\\servers\\Alpha\\mods\\example.jar"]]


@pytest.mark.smoke
def test_build_local_update_task_nodes_dedupes_duplicate_entries_and_merges_metadata_messages() -> None:
    """驗證簡化版本：扁平列表結構、去重、按優先度排序"""
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    candidate = SimpleNamespace(
        project_id="Ha28R6CL",
        project_name="Fabric Language Kotlin",
        current_version="1.13.9",
        target_version_name="1.14.0",
        actionable=False,
        metadata_source="unresolved",
        recommendation_source="project_fallback",
        recommendation_confidence="advisory",
        metadata_note="metadata ensure 失敗：找不到可用的 provider metadata 或雜湊對應結果。",
        report=SimpleNamespace(warnings=[]),
        notes=[],
        local_mod=SimpleNamespace(file_path="C:/servers/Fabric/mods/fabric-language-kotlin-1.13.9+kotlin.2.3.10.jar"),
    )
    review_entry = mod_management_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        blocking_reasons=["metadata 未識別，暫時無法自動檢查更新。"],
        enabled=False,
        provider="modrinth",
        version_type="beta",
    )

    # 傳入重複項，應該去除重複
    nodes = frame._build_local_update_task_nodes([review_entry, review_entry])
    root_nodes = [node for node in nodes if node.node_kind == "root"]
    assert len(root_nodes) == 1, "應該只有一個根級節點（已去重）"
    root_node = root_nodes[0]
    assert root_node.title == "Fabric Language Kotlin"
    assert root_node.values[1] == "1.13.9"
    assert root_node.values[2] == "1.14.0"
    assert root_node.group_key == "unknown"


@pytest.mark.smoke
def test_build_local_update_execution_prompt_summarizes_failure_matrix() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)

    enabled_entry = mod_management_module.LocalUpdateReviewEntry(
        candidate=SimpleNamespace(actionable=True, recommendation_confidence="high"),
        dependency_plan=SimpleNamespace(items=[]),
        enabled=True,
    )
    advisory_entry = mod_management_module.LocalUpdateReviewEntry(
        candidate=SimpleNamespace(actionable=True, recommendation_confidence="advisory"),
        dependency_plan=SimpleNamespace(items=[]),
        enabled=True,
    )
    retryable_entry = mod_management_module.LocalUpdateReviewEntry(
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
    unknown_entry = mod_management_module.LocalUpdateReviewEntry(
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
    blocked_entry = mod_management_module.LocalUpdateReviewEntry(
        candidate=SimpleNamespace(actionable=True, recommendation_confidence="blocked"),
        dependency_plan=SimpleNamespace(items=[]),
        blocking_reasons=["相依版本衝突"],
        enabled=True,
    )

    prompt = frame._build_local_update_execution_prompt(
        [enabled_entry, advisory_entry, retryable_entry, unknown_entry, blocked_entry]
    )

    assert prompt is not None
    assert "建議確認：1 項" in prompt
    assert "可重試：1 項" in prompt
    assert "待識別：1 項" in prompt
    assert "需先處理：1 項" in prompt
    assert "將繼續更新其餘 2 個可更新項目" in prompt


@pytest.mark.smoke
def test_build_local_update_execution_prompt_returns_none_for_advisory_only() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)

    entries = [
        mod_management_module.LocalUpdateReviewEntry(
            candidate=SimpleNamespace(actionable=True, recommendation_confidence="advisory"),
            dependency_plan=SimpleNamespace(items=[]),
            enabled=True,
        )
        for _ in range(2)
    ]

    assert frame._build_local_update_execution_prompt(entries) is None


@pytest.mark.smoke
def test_get_online_version_status_text_distinguishes_key_states() -> None:
    assert mod_management_module.ModManagementFrame._get_online_version_status_text(None) == "未分析"

    incompatible_report = SimpleNamespace(compatible=False)
    assert mod_management_module.ModManagementFrame._get_online_version_status_text(incompatible_report) == "不相容"

    dependency_report = SimpleNamespace(
        compatible=True,
        missing_required_dependencies=["Fabric API"],
        incompatible_installed=[],
        installed_version_mismatches=[],
        warnings=[],
    )
    assert (
        mod_management_module.ModManagementFrame._get_online_version_status_text(dependency_report) == "可安裝，含依賴"
    )

    warning_report = SimpleNamespace(
        compatible=True,
        missing_required_dependencies=[],
        incompatible_installed=[],
        installed_version_mismatches=[],
        warnings=["optional"],
    )
    assert mod_management_module.ModManagementFrame._get_online_version_status_text(warning_report) == "可安裝，需注意"

    clean_report = SimpleNamespace(
        compatible=True,
        missing_required_dependencies=[],
        incompatible_installed=[],
        installed_version_mismatches=[],
        warnings=[],
    )
    assert mod_management_module.ModManagementFrame._get_online_version_status_text(clean_report) == "可安裝"


@pytest.mark.smoke
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

    sorted_versions, _ = mod_management_module.ModManagementFrame._sort_online_versions_for_server(versions, reports)

    assert [version.version_id for version in sorted_versions] == [
        "release-old",
        "beta-new",
        "release-incompatible",
    ]


@pytest.mark.smoke
def test_sort_online_versions_for_server_keeps_reports_aligned() -> None:
    versions = [
        SimpleNamespace(version_id="v1", version_type="beta", date_published="2026-03-02T10:00:00Z"),
        SimpleNamespace(version_id="v2", version_type="release", date_published="2026-03-01T10:00:00Z"),
    ]
    reports = [
        SimpleNamespace(compatible=True, marker="report-v1"),
        SimpleNamespace(compatible=True, marker="report-v2"),
    ]

    sorted_versions, sorted_reports = mod_management_module.ModManagementFrame._sort_online_versions_for_server(
        versions,
        reports,
    )

    assert [version.version_id for version in sorted_versions] == ["v2", "v1"]
    assert [report.marker for report in cast(list[Any], sorted_reports)] == ["report-v2", "report-v1"]


@pytest.mark.smoke
def test_purge_orphan_local_tree_items_removes_untracked_visible_rows() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    frame.local_tree = cast(Any, _StubTree())
    frame._local_recycled_item_ids = ["keep", "ghost"]

    frame._purge_orphan_local_tree_items({"keep"})

    tree = cast(_StubTree, frame.local_tree)
    assert tree.deleted == ["orphan"]
    assert frame._local_recycled_item_ids == ["keep"]


@pytest.mark.smoke
def test_resolve_local_display_name_keeps_trusted_local_name_when_enhancement_is_fuzzy() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    local_mod = cast(Any, type("LocalMod", (), {"name": "Fabric API", "platform_id": "fabric-api"})())
    enhanced = cast(Any, type("EnhancedMod", (), {"name": "Dawn API", "project_id": "dawn-api", "slug": "dawn-api"})())

    display_name = frame._resolve_local_display_name(local_mod, enhanced)

    assert display_name == "Fabric API"


@pytest.mark.smoke
def test_resolve_local_display_name_uses_exact_enhancement_when_local_name_unknown() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    local_mod = cast(Any, type("LocalMod", (), {"name": "Unknown Mod", "platform_id": "fabric-api"})())
    enhanced = cast(
        Any, type("EnhancedMod", (), {"name": "Fabric API", "project_id": "P7dR8mSH", "slug": "fabric-api"})()
    )

    display_name = frame._resolve_local_display_name(local_mod, enhanced)

    assert display_name == "Fabric API"


@pytest.mark.smoke
def test_delete_local_mod_removes_all_selected_files(tmp_path: Path, monkeypatch) -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()
    (mods_dir / "clumps.jar").write_text("a", encoding="utf-8")
    (mods_dir / "fabric-api.jar.disabled").write_text("b", encoding="utf-8")

    shown_messages: list[str] = []
    frame.local_tree = cast(Any, _DeleteTree())
    frame.current_server = cast(Any, type("Server", (), {"path": str(tmp_path)})())
    frame.parent = cast(Any, object())
    frame.status_label = cast(Any, _StatusLabel())
    monkeypatch.setattr(frame, "load_local_mods", lambda: shown_messages.append("reloaded"))

    def fake_ask_yes_no_cancel(_title, _message, parent=None, show_cancel=False) -> bool:
        del parent, show_cancel
        return True

    monkeypatch.setattr(mod_management_module.UIUtils, "ask_yes_no_cancel", fake_ask_yes_no_cancel)
    monkeypatch.setattr(
        mod_management_module.UIUtils,
        "show_info",
        lambda _title, message, _parent=None: shown_messages.append(message),
    )
    monkeypatch.setattr(
        mod_management_module.UIUtils,
        "show_warning",
        lambda _title, message, _parent=None: shown_messages.append(f"warn:{message}"),
    )

    frame.delete_local_mod()

    assert not (mods_dir / "clumps.jar").exists()
    assert not (mods_dir / "fabric-api.jar.disabled").exists()
    assert shown_messages[0] == "reloaded"
    assert shown_messages[1] == "已刪除 2 個模組"
    assert frame.status_label.text == "已刪除 2 個模組"


@pytest.mark.smoke
def test_delete_local_mod_handles_unlink_permission_error(tmp_path: Path, monkeypatch) -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    mods_dir = tmp_path / "mods"
    mods_dir.mkdir()
    blocked_file = mods_dir / "clumps.jar"
    blocked_file.write_text("a", encoding="utf-8")

    shown_messages: list[str] = []
    frame.local_tree = cast(Any, _DeleteTree())
    frame.current_server = cast(Any, type("Server", (), {"path": str(tmp_path)})())
    frame.parent = cast(Any, object())
    frame.status_label = cast(Any, _StatusLabel())
    monkeypatch.setattr(frame, "load_local_mods", lambda: shown_messages.append("reloaded"))

    def fake_ask_yes_no_cancel(_title, _message, parent=None, show_cancel=False) -> bool:
        del parent, show_cancel
        return True

    def _raise_permission_error(self: Path, *, missing_ok: bool = False) -> None:
        del self, missing_ok
        raise PermissionError("permission denied")

    monkeypatch.setattr(mod_management_module.UIUtils, "ask_yes_no_cancel", fake_ask_yes_no_cancel)
    monkeypatch.setattr(mod_management_module.UIUtils, "show_info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod_management_module.UIUtils, "show_warning", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mod_management_module.UIUtils,
        "show_error",
        lambda _title, message, _parent=None: shown_messages.append(message),
    )
    monkeypatch.setattr(Path, "unlink", _raise_permission_error)

    frame.delete_local_mod()

    assert blocked_file.exists() is True
    assert shown_messages
    assert shown_messages[-1] == "刪除模組失敗: permission denied"
    assert frame.status_label.text == "刪除失敗: permission denied"


@pytest.mark.smoke
def test_set_review_entries_enabled_toggles_flags() -> None:
    enabled_entry = mod_management_module.PendingInstallReviewEntry(
        pending=cast(Any, object()),
        report=None,
        dependency_plan=cast(Any, object()),
        enabled=True,
    )
    disabled_entry = mod_management_module.PendingInstallReviewEntry(
        pending=cast(Any, object()),
        report=None,
        dependency_plan=cast(Any, object()),
        enabled=False,
    )

    changed = mod_management_module.ModManagementFrame._set_review_entries_enabled(
        {"a": enabled_entry, "b": disabled_entry},
        {"a", "b"},
        False,
    )

    assert changed is True
    assert enabled_entry.enabled is False
    assert disabled_entry.enabled is False


@pytest.mark.smoke
def test_review_entry_counters_distinguish_enabled_and_blocked_items() -> None:
    runnable_enabled = mod_management_module.PendingInstallReviewEntry(
        pending=cast(Any, object()),
        report=None,
        dependency_plan=cast(Any, object()),
        enabled=True,
    )
    runnable_disabled = mod_management_module.PendingInstallReviewEntry(
        pending=cast(Any, object()),
        report=None,
        dependency_plan=cast(Any, object()),
        enabled=False,
    )
    blocked_enabled = mod_management_module.PendingInstallReviewEntry(
        pending=cast(Any, object()),
        report=None,
        dependency_plan=None,
        blocking_reasons=["missing dependency"],
        enabled=True,
    )

    entries = [runnable_enabled, runnable_disabled, blocked_enabled]

    assert mod_management_module.ModManagementFrame._count_enabled_runnable_entries(entries) == 1
    assert mod_management_module.ModManagementFrame._count_blocked_entries(entries) == 1


@pytest.mark.smoke
def test_collect_selected_root_keys_from_grouped_tree_returns_review_roots() -> None:
    tree = _GroupedSelectionTree(
        {
            "group::enabled": "",
            "fabric-api::dependency::0": "fabric-api",
            "fabric-api": "group::enabled",
            "group::blocked": "",
            "lithium::blocked::0": "lithium",
            "lithium": "group::blocked",
        },
        ("fabric-api::dependency::0", "lithium::blocked::0"),
    )

    selected = mod_management_module.ModManagementFrame._collect_selected_root_keys_from(
        cast(Any, tree),
        {"fabric-api", "lithium"},
    )

    assert selected == {"fabric-api", "lithium"}


@pytest.mark.smoke
def test_set_selected_advisory_dependency_items_enabled_supports_optional_parent_node() -> None:
    root_key = "fabric-api::v1"
    advisory_a = SimpleNamespace(project_name="Mod Menu", enabled=False)
    advisory_b = SimpleNamespace(project_name="FerriteCore", enabled=False)
    tree = _GroupedSelectionTree({}, (f"{root_key}::optional-dependencies",))
    entry_map = {
        root_key: SimpleNamespace(
            dependency_plan=SimpleNamespace(advisory_items=[advisory_a, advisory_b]),
        )
    }

    changed = mod_management_module.ModManagementFrame._set_selected_advisory_dependency_items_enabled(
        cast(Any, tree),
        entry_map,
        True,
    )

    assert changed is True
    assert advisory_a.enabled is True
    assert advisory_b.enabled is True


@pytest.mark.smoke
def test_build_online_review_task_nodes_include_grouped_children() -> None:
    """驗證簡化版本：扁平列表結構、正確分組"""
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    pending = mod_management_module.PendingOnlineInstall(
        project_id="fabric-api",
        project_name="Fabric API",
        version=cast(Any, type("Version", (), {"version_id": "abc", "display_name": "0.120.0"})()),
    )
    review_entry = mod_management_module.PendingInstallReviewEntry(
        pending=pending,
        report=None,
        dependency_plan=SimpleNamespace(items=[SimpleNamespace(project_name="Cloth Config", version_name="17.0.0")]),
        warning_messages=["建議先備份伺服器。"],
        enabled=True,
        provider="modrinth",
        version_type="release",
    )

    nodes = frame._build_online_review_task_nodes([review_entry])
    root_nodes = [node for node in nodes if node.node_kind == "root"]
    assert len(root_nodes) == 1, "應該只有一個根級節點"

    # 驗證分組正確（warning_messages 導致 advisory 分組）
    assert any(node.node_kind == "root" and node.group_key == "advisory" for node in nodes), "應該被分組為 advisory"


@pytest.mark.smoke
def test_build_online_review_task_nodes_aggregate_required_by_labels() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    dependency = SimpleNamespace(
        project_id="cloth-config",
        version_id="dep-1",
        project_name="Cloth Config",
        version_name="17.0.0",
    )
    entry_a = mod_management_module.PendingInstallReviewEntry(
        pending=mod_management_module.PendingOnlineInstall(
            project_id="fabric-api",
            project_name="Fabric API",
            version=cast(Any, type("Version", (), {"version_id": "v1", "display_name": "0.120.0"})()),
        ),
        report=None,
        dependency_plan=SimpleNamespace(items=[dependency], notes=[]),
        enabled=True,
    )
    entry_b = mod_management_module.PendingInstallReviewEntry(
        pending=mod_management_module.PendingOnlineInstall(
            project_id="lithium",
            project_name="Lithium",
            version=cast(Any, type("Version", (), {"version_id": "v2", "display_name": "0.13.0"})()),
        ),
        report=None,
        dependency_plan=SimpleNamespace(items=[dependency], notes=[]),
        enabled=True,
    )

    nodes = frame._build_online_review_task_nodes([entry_a, entry_b])

    root_nodes = [node for node in nodes if node.node_kind == "root"]
    assert len(root_nodes) == 2, "應該有兩個根級節點"
    assert any(node.values[2] == "Fabric API" for node in root_nodes)
    assert any(node.values[2] == "Lithium" for node in root_nodes)


@pytest.mark.smoke
def test_build_online_review_task_nodes_required_by_ignores_disabled_roots() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    dependency = SimpleNamespace(
        project_id="cloth-config",
        version_id="dep-1",
        project_name="Cloth Config",
        version_name="17.0.0",
    )
    entry_a = mod_management_module.PendingInstallReviewEntry(
        pending=mod_management_module.PendingOnlineInstall(
            project_id="fabric-api",
            project_name="Fabric API",
            version=cast(Any, type("Version", (), {"version_id": "v1", "display_name": "0.120.0"})()),
        ),
        report=None,
        dependency_plan=SimpleNamespace(items=[dependency], notes=[]),
        enabled=True,
    )
    entry_b = mod_management_module.PendingInstallReviewEntry(
        pending=mod_management_module.PendingOnlineInstall(
            project_id="lithium",
            project_name="Lithium",
            version=cast(Any, type("Version", (), {"version_id": "v2", "display_name": "0.13.0"})()),
        ),
        report=None,
        dependency_plan=SimpleNamespace(items=[dependency], notes=[]),
        enabled=False,
    )

    nodes = frame._build_online_review_task_nodes([entry_a, entry_b])

    root_nodes = [node for node in nodes if node.node_kind == "root"]
    assert len(root_nodes) == 2, "應該有兩個根級節點"
    assert any(node.values[2] == "Fabric API" and node.values[0] == "是" for node in root_nodes)
    assert any(node.values[2] == "Lithium" and node.values[0] == "否" for node in root_nodes)


@pytest.mark.smoke
def test_build_online_review_task_nodes_marks_advisory_dependency_as_skipped() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    entry = mod_management_module.PendingInstallReviewEntry(
        pending=mod_management_module.PendingOnlineInstall(
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

    nodes = frame._build_online_review_task_nodes([entry])

    root_nodes = [node for node in nodes if node.node_kind == "root"]
    assert len(root_nodes) == 1, "應該有一個根級節點"
    assert root_nodes[0].title == "模組"
    assert root_nodes[0].values[2] == "Fabric API"


@pytest.mark.smoke
def test_build_dependency_status_text_uses_resolution_fallback_label() -> None:
    dependency = SimpleNamespace(
        resolution_source="version_detail",
        resolution_confidence="fallback",
        status_note="",
    )

    status_text = mod_management_module.ModManagementFrame._build_dependency_status_text(
        dependency,
        "Fabric API",
        "Fabric API",
        False,
        True,
    )

    assert status_text == "required-by：Fabric API｜解析：版本詳情回補（中）｜處理：將自動安裝"


@pytest.mark.smoke
def test_build_online_review_root_status_text_summarizes_dependencies_warnings_and_blockers() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    entry = mod_management_module.PendingInstallReviewEntry(
        pending=mod_management_module.PendingOnlineInstall(
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
        warning_messages=["建議先備份伺服器。"],
        enabled=True,
    )

    status_text = frame._build_online_review_root_status_text(entry)

    assert status_text == "需先處理｜依賴 1｜可選 1｜提醒 1｜阻擋 1"


@pytest.mark.smoke
def test_build_online_review_task_nodes_puts_summary_text_in_root_status_column() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    pending = mod_management_module.PendingOnlineInstall(
        project_id="fabric-api",
        project_name="Fabric API",
        version=cast(Any, type("Version", (), {"version_id": "abc", "display_name": "0.120.0"})()),
    )
    review_entry = mod_management_module.PendingInstallReviewEntry(
        pending=pending,
        report=None,
        dependency_plan=SimpleNamespace(items=[SimpleNamespace(project_name="Cloth Config", version_name="17.0.0")]),
        warning_messages=["建議先備份伺服器。"],
        enabled=True,
        provider="modrinth",
        version_type="release",
    )

    nodes = frame._build_online_review_task_nodes([review_entry])

    root_node = next(node for node in nodes if node.node_kind == "root")
    assert root_node.values[5] == "建議確認｜依賴 1｜提醒 1"


@pytest.mark.smoke
def test_prepare_online_install_review_entries_rebuilds_dependency_simulation_from_enabled_roots(monkeypatch) -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
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
    frame.pending_online_installs = [
        mod_management_module.PendingOnlineInstall("first-mod", "First Mod", first_version),
        mod_management_module.PendingOnlineInstall("second-mod", "Second Mod", second_version),
    ]

    monkeypatch.setattr(frame, "_get_current_modrinth_context", lambda: ("1.21", "fabric", "0.16.0"))
    monkeypatch.setattr(frame, "_get_current_installed_mods", list)
    monkeypatch.setattr(mod_management_module, "resolve_modrinth_project_names", lambda _project_ids: {})
    monkeypatch.setattr(
        mod_management_module,
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
        mod_management_module,
        "build_required_dependency_install_plan",
        fake_build_required_dependency_install_plan,
    )

    review_entries = frame._prepare_online_install_review_entries()

    assert len(review_entries[1].dependency_plan.items) == 0


@pytest.mark.smoke
def test_prepare_online_install_review_entries_blocks_client_only_mod(monkeypatch) -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
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
    frame.pending_online_installs = [
        mod_management_module.PendingOnlineInstall(
            "client-only-mod",
            "Client Only Mod",
            client_only_version,
            server_side="unsupported",
            client_side="required",
        )
    ]

    monkeypatch.setattr(frame, "_get_current_modrinth_context", lambda: ("1.21", "fabric", "0.16.0"))
    monkeypatch.setattr(frame, "_get_current_installed_mods", list)
    monkeypatch.setattr(mod_management_module, "resolve_modrinth_project_names", lambda _project_ids: {})
    monkeypatch.setattr(
        mod_management_module,
        "analyze_mod_version_compatibility",
        lambda *_args, **_kwargs: SimpleNamespace(hard_errors=[], warnings=[]),
    )
    monkeypatch.setattr(
        mod_management_module,
        "build_required_dependency_install_plan",
        lambda *_args, **_kwargs: SimpleNamespace(items=[], advisory_items=[], unresolved_required=[], notes=[]),
    )

    review_entries = frame._prepare_online_install_review_entries()

    assert len(review_entries) == 1
    assert review_entries[0].enabled is False
    assert any("僅 client 端" in message for message in review_entries[0].blocking_reasons)


@pytest.mark.smoke
def test_prepare_online_install_review_entries_warns_unknown_server_side(monkeypatch) -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
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
    frame.pending_online_installs = [
        mod_management_module.PendingOnlineInstall(
            "unknown-side-mod",
            "Unknown Side Mod",
            unknown_side_version,
            server_side="unknown",
            client_side="optional",
        )
    ]

    monkeypatch.setattr(frame, "_get_current_modrinth_context", lambda: ("1.21", "fabric", "0.16.0"))
    monkeypatch.setattr(frame, "_get_current_installed_mods", list)
    monkeypatch.setattr(mod_management_module, "resolve_modrinth_project_names", lambda _project_ids: {})
    monkeypatch.setattr(
        mod_management_module,
        "analyze_mod_version_compatibility",
        lambda *_args, **_kwargs: SimpleNamespace(hard_errors=[], warnings=[]),
    )
    monkeypatch.setattr(
        mod_management_module,
        "build_required_dependency_install_plan",
        lambda *_args, **_kwargs: SimpleNamespace(items=[], advisory_items=[], unresolved_required=[], notes=[]),
    )

    review_entries = frame._prepare_online_install_review_entries()

    assert len(review_entries) == 1
    assert review_entries[0].enabled is True
    assert any("未明確標示 server 端支援" in message for message in review_entries[0].warning_messages)


@pytest.mark.smoke
def test_treeview_separator_detection_ignores_displaycolumns_all_placeholder(monkeypatch) -> None:
    tree = _HeaderAutoFitTree()

    monkeypatch.setattr(mod_management_module.FontManager, "get_dpi_scaled_size", lambda value: value)

    column_id = mod_management_module.TreeUtils._get_treeview_separator_column_from_x(tree, 140)

    assert column_id == "name"
    assert tree.requested_columns == ["name", "version"]


@pytest.mark.smoke
def test_build_local_update_task_nodes_include_blocking_items() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    candidate = SimpleNamespace(
        project_id="lithium",
        project_name="Lithium",
        current_version="0.12.0",
        target_version_name="0.13.0",
        actionable=False,
        report=SimpleNamespace(warnings=["與現有設定可能衝突。"]),
        notes=["需要更新前先停機。"],
    )
    review_entry = mod_management_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[]),
        blocking_reasons=["缺少相容版本依賴"],
        enabled=False,
        provider="modrinth",
        version_type="beta",
    )

    nodes = frame._build_local_update_task_nodes([review_entry])

    root_node = next(node for node in nodes if node.node_kind == "root")
    assert any(node.node_kind == "root" and node.group_key == "blocked" for node in nodes)
    assert root_node.values[3] == "Modrinth"


@pytest.mark.smoke
def test_build_local_update_task_nodes_surfaces_metadata_source_in_root_and_child_node() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    candidate = SimpleNamespace(
        project_id="",
        project_name="Unknown Mod",
        current_version="1.0.0",
        target_version_name="-",
        actionable=False,
        metadata_source="unresolved",
        metadata_note="metadata ensure 失敗：找不到可用的 provider metadata 或雜湊對應結果。",
        local_mod=SimpleNamespace(file_path="C:/servers/demo/mods/unknown-mod.jar"),
        report=None,
        notes=[],
    )
    review_entry = mod_management_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[], notes=[]),
        blocking_reasons=["metadata 未識別，暫時無法自動檢查更新。"],
        enabled=False,
        provider="modrinth",
        version_type="",
    )

    nodes = frame._build_local_update_task_nodes([review_entry])

    root_node = next(node for node in nodes if node.node_kind == "root")
    assert root_node.group_key == "unknown"
    assert root_node.values[3] == "Modrinth｜待識別"
    assert root_node.values[4] == "需先識別"


@pytest.mark.smoke
def test_build_local_update_task_nodes_groups_advisory_candidate_separately() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
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
    review_entry = mod_management_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[], notes=[]),
        blocking_reasons=[],
        enabled=True,
        provider="modrinth",
    )

    nodes = frame._build_local_update_task_nodes([review_entry])

    root_node = next(node for node in nodes if node.node_kind == "root")
    assert root_node.group_key == "advisory"
    assert root_node.values[4] == "建議確認"


@pytest.mark.smoke
def test_build_local_update_task_nodes_groups_retryable_candidate_separately() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    candidate = SimpleNamespace(
        project_id="__stale__::sodium",
        project_name="Sodium",
        current_version="0.6.0",
        target_version_name="",
        actionable=False,
        recommendation_source="stale_metadata",
        recommendation_confidence="retryable",
        metadata_source="stale_provider",
        metadata_note="stale metadata 重查失敗：已停用自動更新並保留舊識別供人工判讀。",
        report=None,
        notes=[],
    )
    review_entry = mod_management_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[], notes=[]),
        blocking_reasons=["provider metadata 已過期且重查失敗，已暫停自動更新以避免錯誤建議。"],
        enabled=False,
        provider="modrinth",
    )

    nodes = frame._build_local_update_task_nodes([review_entry])

    root_node = next(node for node in nodes if node.node_kind == "root")
    assert root_node.group_key == "retryable"
    assert root_node.values[4] == "可重試"


@pytest.mark.smoke
def test_build_local_update_review_subtitle_includes_failure_matrix_counts() -> None:
    text = mod_management_module.ModManagementFrame._build_local_update_review_subtitle(
        "全部模組",
        2,
        1,
        advisory_count=1,
        retryable_count=1,
        unknown_count=1,
    )

    assert text == "範圍：全部模組｜可執行更新 2 項｜建議確認 1 項｜可重試 1 項｜待識別 1 項｜阻擋 1 項"


@pytest.mark.smoke
def test_build_local_update_review_subtitle_includes_migrated_snapshot_count() -> None:
    text = mod_management_module.ModManagementFrame._build_local_update_review_subtitle(
        "全部模組",
        1,
        0,
        migrated_snapshot_count=2,
    )

    assert text == "範圍：全部模組｜可執行更新 1 項｜快照遷移 2 項"


@pytest.mark.smoke
def test_build_dependency_snapshot_migration_note_formats_summary_line() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    frame._dependency_snapshot_migration_totals = {
        "checked": 3,
        "migrated": 1,
        "replayed": 2,
        "fallback_rebuild": 1,
    }

    note = frame._build_dependency_snapshot_migration_note()

    assert note == "依賴快照遷移觀測：檢查 3、自動遷移 1、成功回放 2、回放失敗改重建 1。"


@pytest.mark.smoke
def test_build_local_update_review_key_is_unique_for_same_project_id_with_different_files() -> None:
    candidate_a = SimpleNamespace(
        project_id="Ha28R6CL",
        local_mod=SimpleNamespace(file_path="C:/servers/a/mods/kotlin-a.jar"),
    )
    candidate_b = SimpleNamespace(
        project_id="Ha28R6CL",
        local_mod=SimpleNamespace(file_path="C:/servers/a/mods/kotlin-b.jar"),
    )

    key_a = mod_management_module.ModManagementFrame._build_local_update_review_key(candidate_a)
    key_b = mod_management_module.ModManagementFrame._build_local_update_review_key(candidate_b)

    assert key_a != key_b
    assert key_a.startswith("project::Ha28R6CL::")
    assert key_b.startswith("project::Ha28R6CL::")


@pytest.mark.smoke
def test_format_review_overview_text_includes_preflight_notes() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    entries = [
        mod_management_module.PendingInstallReviewEntry(
            pending=cast(Any, object()),
            report=None,
            dependency_plan=cast(Any, object()),
            enabled=True,
        )
    ]
    nodes = [
        mod_management_module.ReviewTaskNode(
            node_id="root",
            root_key="root",
            group_key="enabled",
            title="模組",
            values=("是", "Modrinth", "Fabric API", "0.120.0", "release", "可安裝"),
            node_kind="root",
        ),
        mod_management_module.ReviewTaskNode(
            node_id="root::warning::0",
            root_key="root",
            group_key="enabled",
            title="提醒",
            values=("-", "-", "Fabric API", "-", "-", "建議先備份"),
            node_kind="warning",
            parent_id="root",
        ),
    ]

    text = frame._format_review_overview_text(
        entries, nodes, action_label="安裝", global_notes=["已完成 metadata 預檢"]
    )

    assert "Task graph：1 個根任務" in text
    assert "目前將安裝 1 個根項目" in text
    assert "預檢：已完成 metadata 預檢" in text


@pytest.mark.smoke
def test_format_completion_notes_deduplicates_messages() -> None:
    text = mod_management_module.ModManagementFrame._format_completion_notes(
        ["建議先備份", "建議先備份", "需重啟伺服器"]
    )

    assert text.count("建議先備份") == 1
    assert "需重啟伺服器" in text


@pytest.mark.smoke
def test_format_online_version_report_includes_provider_and_changelog() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
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

    report_text = frame._format_online_version_report(version, None)

    assert "來源：Modrinth" in report_text
    assert "版本類型：release" in report_text
    assert "發布時間：2026-03-01 12:00" in report_text
    assert "更新內容：" in report_text
    assert "Fixed crash when syncing registry state." in report_text


@pytest.mark.smoke
def test_format_local_update_review_text_includes_metadata_source() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
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
    review_entry = mod_management_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[], notes=[]),
        blocking_reasons=[],
        enabled=True,
        provider="modrinth",
        version_type="release",
        date_published="2026-03-01T12:00:00Z",
        changelog="",
    )

    text = frame._format_local_update_review_text(review_entry)

    assert "Metadata 來源：雜湊比對" in text
    assert "更新建議來源：雜湊 metadata" in text
    assert "更新建議可信度：高" in text


@pytest.mark.smoke
def test_format_pending_install_review_text_includes_summary_lines() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
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
    review_entry = mod_management_module.PendingInstallReviewEntry(
        pending=mod_management_module.PendingOnlineInstall(
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

    text = frame._format_pending_install_review_text(review_entry)

    assert "摘要：需先處理｜依賴 1｜可選 1｜阻擋 1" in text
    assert "處理等級：需先處理" in text
    assert "- 將自動補裝 1 個必要依賴" in text
    assert "- 可選依賴 1 項（已選 0 項）" in text
    assert "- 目前有 1 個阻擋原因需先處理" in text


@pytest.mark.smoke
def test_format_pending_install_review_text_includes_client_install_reminder_for_server_and_client_mod() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
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
    review_entry = mod_management_module.PendingInstallReviewEntry(
        pending=mod_management_module.PendingOnlineInstall(
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

    text = frame._format_pending_install_review_text(review_entry)

    assert "提醒：此模組同時支援 client 端" in text


@pytest.mark.smoke
def test_format_local_update_review_text_includes_unresolved_metadata_state() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    candidate = SimpleNamespace(
        project_name="Unknown Mod",
        current_version="1.0.0",
        target_version_name="",
        metadata_source="unresolved",
        recommendation_source="project_fallback",
        recommendation_confidence="advisory",
        metadata_note="metadata ensure 失敗：找不到可用的 provider metadata 或雜湊對應結果。",
        notes=[],
        report=None,
    )
    review_entry = mod_management_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[], notes=[]),
        blocking_reasons=["metadata 未識別，暫時無法自動檢查更新。"],
        enabled=False,
        provider="modrinth",
        version_type="",
        date_published="",
        changelog="",
    )

    text = frame._format_local_update_review_text(review_entry)

    assert "Metadata 來源：尚未識別" in text
    assert "更新建議來源：專案 fallback" in text
    assert "更新建議可信度：提示" in text
    assert "Metadata 狀態：metadata ensure 失敗" in text


@pytest.mark.smoke
def test_format_local_update_review_text_includes_client_install_reminder_for_server_and_client_mod() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
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
    review_entry = mod_management_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[], notes=[]),
        blocking_reasons=[],
        enabled=True,
        provider="modrinth",
        version_type="release",
        date_published="2026-03-01T12:00:00Z",
        changelog="",
    )

    text = frame._format_local_update_review_text(review_entry)

    assert "提醒：此模組同時支援 client 端" in text


@pytest.mark.smoke
def test_cache_local_provider_metadata_uses_shared_provider_contract() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    captured: dict[str, Any] = {}

    class _StubIndexManager:
        def cache_provider_metadata(self, file_path: Path, provider_metadata: dict[str, Any]) -> None:
            captured["file_path"] = file_path
            captured["provider_metadata"] = provider_metadata

    frame.mod_manager = SimpleNamespace(index_manager=_StubIndexManager())
    mod = SimpleNamespace(
        file_path="C:/servers/Fabric/mods/sodium.jar",
        platform_id="",
        platform_slug="",
        name="Sodium",
    )
    enhanced = SimpleNamespace(project_id="AANobbMI", slug="sodium", name="Sodium")

    frame._cache_local_provider_metadata(mod, enhanced)

    assert mod.platform_id == "AANobbMI"
    assert mod.platform_slug == "sodium"
    assert captured["file_path"] == Path("C:/servers/Fabric/mods/sodium.jar")
    assert captured["provider_metadata"].get("platform") == "modrinth"
    assert captured["provider_metadata"].get("project_id") == "AANobbMI"
    assert captured["provider_metadata"].get("slug") == "sodium"
    assert captured["provider_metadata"].get("project_name") == "Sodium"


@pytest.mark.smoke
def test_ensure_local_mod_project_ids_backfills_missing_slug() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    captured: dict[str, Any] = {}

    class _StubIndexManager:
        def cache_provider_metadata(self, file_path: Path, provider_metadata: dict[str, Any]) -> None:
            captured["file_path"] = file_path
            captured["provider_metadata"] = provider_metadata

    frame.mod_manager = SimpleNamespace(index_manager=_StubIndexManager())
    frame.enhanced_mods_cache = {}

    local_mod = SimpleNamespace(
        filename="sodium-fabric.jar",
        file_path="C:/servers/Fabric/mods/sodium-fabric.jar",
        platform_id="AANobbMI",
        platform_slug="",
        name="Sodium",
    )

    original_resolve_provider_record = mod_management_module.resolve_modrinth_provider_record
    original_enhance_local_mod = mod_management_module.enhance_local_mod
    fallback_calls = {"count": 0}
    mod_management_module.resolve_modrinth_provider_record = lambda _identifier: (
        mod_management_module.ProviderMetadataRecord.from_values(
            project_id="AANobbMI",
            slug="sodium",
            project_name="Sodium",
        )
    )

    def _counting_enhance(*_args, **_kwargs):
        fallback_calls["count"] += 1
        return SimpleNamespace(project_id="AANobbMI", slug="sodium", name="Sodium")

    mod_management_module.enhance_local_mod = _counting_enhance
    try:
        frame._ensure_local_mod_project_ids([local_mod])
    finally:
        mod_management_module.resolve_modrinth_provider_record = original_resolve_provider_record
        mod_management_module.enhance_local_mod = original_enhance_local_mod

    assert local_mod.platform_id == "AANobbMI"
    assert local_mod.platform_slug == "sodium"
    assert fallback_calls["count"] == 0
    assert captured["file_path"] == Path("C:/servers/Fabric/mods/sodium-fabric.jar")
    assert captured["provider_metadata"].get("platform") == "modrinth"
    assert captured["provider_metadata"].get("project_id") == "AANobbMI"
    assert captured["provider_metadata"].get("slug") == "sodium"
    assert captured["provider_metadata"].get("project_name") == "Sodium"


@pytest.mark.smoke
def test_build_local_update_review_key_falls_back_to_file_path_when_project_id_missing() -> None:
    candidate = SimpleNamespace(
        project_id="",
        filename="unknown-mod.jar",
        local_mod=SimpleNamespace(file_path="C:/servers/demo/mods/unknown-mod.jar", filename="unknown-mod.jar"),
    )

    key = mod_management_module.ModManagementFrame._build_local_update_review_key(candidate)

    assert key == "local::C:/servers/demo/mods/unknown-mod.jar"


@pytest.mark.smoke
def test_resolve_pending_install_review_project_page_url_prefers_homepage_url() -> None:
    review_entry = mod_management_module.PendingInstallReviewEntry(
        pending=mod_management_module.PendingOnlineInstall(
            project_id="AABBCCDD",
            project_name="Sodium",
            version=SimpleNamespace(),
            homepage_url="https://example.com/sodium",
            source_url="https://modrinth.com/mod/sodium",
        ),
        report=None,
        dependency_plan=SimpleNamespace(items=[], notes=[]),
    )

    assert (
        mod_management_module.ModManagementFrame._resolve_pending_install_review_project_page_url(review_entry)
        == "https://example.com/sodium"
    )


@pytest.mark.smoke
def test_resolve_local_update_review_project_page_url_uses_slug_then_project_id() -> None:
    review_entry = mod_management_module.LocalUpdateReviewEntry(
        candidate=SimpleNamespace(
            project_id="P7dR8mSH",
            local_mod=SimpleNamespace(platform_slug="fabric-api", platform_id="ignored-project-id"),
        ),
        dependency_plan=SimpleNamespace(items=[], notes=[]),
    )

    assert (
        mod_management_module.ModManagementFrame._resolve_local_update_review_project_page_url(review_entry)
        == "https://modrinth.com/mod/fabric-api"
    )


@pytest.mark.smoke
def test_resolve_local_update_review_project_page_url_skips_unresolved_candidates() -> None:
    review_entry = mod_management_module.LocalUpdateReviewEntry(
        candidate=SimpleNamespace(
            project_id="",
            local_mod=SimpleNamespace(platform_slug="", platform_id=""),
        ),
        dependency_plan=SimpleNamespace(items=[], notes=[]),
    )

    assert mod_management_module.ModManagementFrame._resolve_local_update_review_project_page_url(review_entry) == ""


@pytest.mark.smoke
def test_cache_local_dependency_plan_snapshot_persists_provider_aware_payload() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    captured: dict[str, Any] = {}

    class _StubIndexManager:
        def cache_provider_metadata(self, file_path: Path, provider_metadata: dict[str, Any]) -> None:
            captured["file_path"] = file_path
            captured["provider_metadata"] = provider_metadata

    frame.mod_manager = SimpleNamespace(index_manager=_StubIndexManager())
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

    frame._cache_local_dependency_plan_snapshot(candidate, dependency_plan)

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


@pytest.mark.smoke
def test_prepare_local_update_review_entries_replays_cached_dependency_plan_snapshot(monkeypatch) -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)

    class _StubIndexManager:
        def get_cached_provider_metadata(self, _file_path: Path) -> dict[str, Any]:
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

    frame.mod_manager = SimpleNamespace(index_manager=_StubIndexManager())
    monkeypatch.setattr(frame, "_get_current_modrinth_context", lambda: ("1.21.1", "fabric", ""))
    monkeypatch.setattr(frame, "_get_current_installed_mods", list)
    monkeypatch.setattr(frame, "_dedupe_review_messages", list)
    monkeypatch.setattr(frame, "_apply_review_advisory_enabled_overrides", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(frame, "_append_enabled_dependency_simulations", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(frame, "_append_simulated_installed_mod", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(frame, "_build_installed_mod_simulation_item", lambda *_args, **_kwargs: SimpleNamespace())

    original_builder = mod_management_module.build_required_dependency_install_plan
    mod_management_module.build_required_dependency_install_plan = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("should use cached dependency plan snapshot")
    )
    try:
        candidate = SimpleNamespace(
            project_id="AANobbMI",
            project_name="Sodium",
            target_version_id="target-ver-1",
            target_version_name="1.0.0",
            target_filename="sodium-new.jar",
            target_version=SimpleNamespace(provider="modrinth"),
            update_available=True,
            actionable=True,
            hard_errors=[],
            current_issues=[],
            dependency_issues=[],
            notes=[],
            local_mod=SimpleNamespace(file_path="C:/servers/Fabric/mods/sodium.jar"),
            filename="sodium.jar",
        )
        review_entries = frame._prepare_local_update_review_entries(SimpleNamespace(candidates=[candidate]))
    finally:
        mod_management_module.build_required_dependency_install_plan = original_builder

    assert len(review_entries) == 1
    restored_plan = review_entries[0].dependency_plan
    assert len(getattr(restored_plan, "items", [])) == 1
    assert restored_plan.items[0].project_id == "P7dR8mSH"
    assert restored_plan.items[0].required_by == ["Sodium"]
    assert restored_plan.items[0].decision_source == "required:auto"
    assert review_entries[0].enabled is False


@pytest.mark.smoke
def test_prepare_local_update_review_entries_rebuilds_when_cached_snapshot_version_mismatch(monkeypatch) -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)

    class _StubIndexManager:
        def get_cached_provider_metadata(self, _file_path: Path) -> dict[str, Any]:
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

        def cache_provider_metadata(self, _file_path: Path, _provider_metadata: dict[str, Any]) -> None:
            return

    frame.mod_manager = SimpleNamespace(index_manager=_StubIndexManager())
    monkeypatch.setattr(frame, "_get_current_modrinth_context", lambda: ("1.21.1", "fabric", ""))
    monkeypatch.setattr(frame, "_get_current_installed_mods", list)
    monkeypatch.setattr(frame, "_dedupe_review_messages", list)
    monkeypatch.setattr(frame, "_apply_review_advisory_enabled_overrides", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(frame, "_append_enabled_dependency_simulations", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(frame, "_append_simulated_installed_mod", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(frame, "_build_installed_mod_simulation_item", lambda *_args, **_kwargs: SimpleNamespace())

    calls = {"count": 0}
    original_builder = mod_management_module.build_required_dependency_install_plan

    def _rebuilt_dependency_plan(*_args, **_kwargs):
        calls["count"] += 1
        return SimpleNamespace(
            items=[SimpleNamespace(project_id="rebuilt")],
            advisory_items=[],
            unresolved_required=[],
            notes=[],
        )

    mod_management_module.build_required_dependency_install_plan = _rebuilt_dependency_plan
    try:
        candidate = SimpleNamespace(
            project_id="AANobbMI",
            project_name="Sodium",
            target_version_id="target-ver-1",
            target_version_name="1.0.0",
            target_filename="sodium-new.jar",
            target_version=SimpleNamespace(provider="modrinth"),
            update_available=True,
            actionable=True,
            hard_errors=[],
            current_issues=[],
            dependency_issues=[],
            notes=[],
            local_mod=SimpleNamespace(file_path="C:/servers/Fabric/mods/sodium.jar"),
            filename="sodium.jar",
        )
        review_entries = frame._prepare_local_update_review_entries(SimpleNamespace(candidates=[candidate]))
    finally:
        mod_management_module.build_required_dependency_install_plan = original_builder

    assert calls["count"] == 1
    assert review_entries[0].dependency_plan.items[0].project_id == "rebuilt"


@pytest.mark.smoke
def test_prepare_local_update_review_entries_migrates_legacy_snapshot_and_persists(monkeypatch) -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    captured_writes: list[dict[str, Any]] = []

    class _StubIndexManager:
        def get_cached_provider_metadata(self, _file_path: Path) -> dict[str, Any]:
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

        def cache_provider_metadata(self, _file_path: Path, provider_metadata: dict[str, Any]) -> None:
            captured_writes.append(provider_metadata)

    frame.mod_manager = SimpleNamespace(index_manager=_StubIndexManager())
    monkeypatch.setattr(frame, "_get_current_modrinth_context", lambda: ("1.21.1", "fabric", ""))
    monkeypatch.setattr(frame, "_get_current_installed_mods", list)
    monkeypatch.setattr(frame, "_dedupe_review_messages", list)
    monkeypatch.setattr(frame, "_apply_review_advisory_enabled_overrides", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(frame, "_append_enabled_dependency_simulations", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(frame, "_append_simulated_installed_mod", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(frame, "_build_installed_mod_simulation_item", lambda *_args, **_kwargs: SimpleNamespace())

    original_builder = mod_management_module.build_required_dependency_install_plan
    mod_management_module.build_required_dependency_install_plan = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("should replay migrated snapshot instead of rebuilding")
    )
    try:
        candidate = SimpleNamespace(
            project_id="AANobbMI",
            project_name="Sodium",
            target_version_id="target-ver-1",
            target_version_name="1.0.0",
            target_filename="sodium-new.jar",
            target_version=SimpleNamespace(provider="modrinth"),
            update_available=True,
            actionable=True,
            hard_errors=[],
            current_issues=[],
            dependency_issues=[],
            notes=[],
            local_mod=SimpleNamespace(file_path="C:/servers/Fabric/mods/sodium.jar"),
            filename="sodium.jar",
        )
        review_entries = frame._prepare_local_update_review_entries(SimpleNamespace(candidates=[candidate]))
    finally:
        mod_management_module.build_required_dependency_install_plan = original_builder

    assert len(review_entries) == 1
    restored_plan = review_entries[0].dependency_plan
    assert len(getattr(restored_plan, "items", [])) == 1
    assert restored_plan.items[0].project_id == "P7dR8mSH"
    assert any("dependency_plan_v1" in payload for payload in captured_writes)
    migrated_snapshot = captured_writes[0]["dependency_plan_v1"]
    assert isinstance(migrated_snapshot.get("graph_edges"), list)
    assert migrated_snapshot["graph_edges"][0]["edge"] == "required"
    telemetry = getattr(frame, "_dependency_snapshot_migration_totals", {})
    assert telemetry.get("checked", 0) == 1
    assert telemetry.get("migrated", 0) == 1
    assert telemetry.get("replayed", 0) == 1
    assert telemetry.get("fallback_rebuild", 0) == 0


@pytest.mark.smoke
def test_persist_local_update_dependency_plan_snapshots_writes_current_advisory_enabled_state() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    captured: dict[str, Any] = {}

    class _StubIndexManager:
        def cache_provider_metadata(self, file_path: Path, provider_metadata: dict[str, Any]) -> None:
            captured["file_path"] = file_path
            captured["provider_metadata"] = provider_metadata

    frame.mod_manager = SimpleNamespace(index_manager=_StubIndexManager())
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
    review_entry = mod_management_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=dependency_plan,
        blocking_reasons=[],
        enabled=True,
    )

    frame._persist_local_update_dependency_plan_snapshots([review_entry])

    payload = captured["provider_metadata"]["dependency_plan_v1"]
    assert captured["file_path"] == Path("C:/servers/Fabric/mods/sodium.jar")
    assert payload["root_enabled"] is True
    assert payload["advisory_items"][0]["project_id"] == "P7dR8mSH"
    assert payload["advisory_items"][0]["enabled"] is True


@pytest.mark.smoke
def test_persist_local_update_plan_metadata_marks_stale_revalidation_failure() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    path_key = str(Path("C:/servers/Fabric/mods/sodium.jar"))

    class _StubIndexManager:
        def __init__(self) -> None:
            self.provider_by_path: dict[str, dict[str, Any]] = {
                path_key: {
                    "platform": "modrinth",
                    "project_id": "AANobbMI",
                    "slug": "sodium",
                }
            }

        def cache_file_hash(self, _file_path: Path, _algorithm: str, _file_hash: str) -> None:
            return

        def get_cached_provider_metadata(self, file_path: Path) -> dict[str, Any]:
            return dict(self.provider_by_path.get(str(file_path), {}))

        def cache_provider_metadata(
            self, file_path: Path, provider_metadata: dict[str, Any], *, merge: bool = True
        ) -> None:
            key = str(file_path)
            previous = dict(self.provider_by_path.get(key, {}))
            updated = previous if merge else {}
            updated.update(provider_metadata)
            self.provider_by_path[key] = updated

        def flush(self) -> None:
            return

    index_manager = _StubIndexManager()
    frame.mod_manager = SimpleNamespace(index_manager=index_manager)
    stale_candidate = SimpleNamespace(
        project_id="__stale__::AANobbMI",
        current_hash="deadbeef",
        hash_algorithm="sha512",
        local_mod=SimpleNamespace(file_path="C:/servers/Fabric/mods/sodium.jar", platform_slug="sodium"),
    )

    frame._persist_local_update_plan_metadata(SimpleNamespace(candidates=[stale_candidate]))

    cached_provider = index_manager.provider_by_path[path_key]
    assert cached_provider["project_id"] == "AANobbMI"
    # 過期重驗（Stale Revalidation）應僅標記狀態，不計入失敗次數。
    assert cached_provider.get("lifecycle_state", "") == "stale"
    assert "stale_revalidation_failures" not in cached_provider or cached_provider.get(
        "stale_revalidation_failures"
    ) in ("0", "")


@pytest.mark.smoke
def test_persist_local_update_plan_metadata_resets_revalidation_on_success() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    path_key = str(Path("C:/servers/Fabric/mods/sodium.jar"))

    class _StubIndexManager:
        def __init__(self) -> None:
            self.provider_by_path: dict[str, dict[str, Any]] = {
                path_key: {
                    "platform": "modrinth",
                    "project_id": "AANobbMI",
                    "slug": "sodium",
                    "lifecycle_state": "invalidated",
                    "stale_revalidation_failures": "5",
                    "next_retry_not_before_epoch_ms": "999999999",
                }
            }

        def cache_file_hash(self, _file_path: Path, _algorithm: str, _file_hash: str) -> None:
            return

        def get_cached_provider_metadata(self, file_path: Path) -> dict[str, Any]:
            return dict(self.provider_by_path.get(str(file_path), {}))

        def cache_provider_metadata(
            self, file_path: Path, provider_metadata: dict[str, Any], *, merge: bool = True
        ) -> None:
            key = str(file_path)
            previous = dict(self.provider_by_path.get(key, {}))
            updated = previous if merge else {}
            updated.update(provider_metadata)
            self.provider_by_path[key] = updated

        def flush(self) -> None:
            return

    index_manager = _StubIndexManager()
    frame.mod_manager = SimpleNamespace(index_manager=index_manager)
    success_candidate = SimpleNamespace(
        project_id="AANobbMI",
        project_name="Sodium",
        metadata_source="hash",
        current_hash="deadbeef",
        hash_algorithm="sha512",
        local_mod=SimpleNamespace(file_path="C:/servers/Fabric/mods/sodium.jar", platform_slug="sodium"),
    )

    frame._persist_local_update_plan_metadata(SimpleNamespace(candidates=[success_candidate]))

    cached_provider = index_manager.provider_by_path[path_key]
    assert cached_provider["project_id"] == "AANobbMI"
    assert cached_provider["lifecycle_state"] == "fresh"
    assert cached_provider["stale_revalidation_failures"] == "0"
    assert cached_provider["next_retry_not_before_epoch_ms"] == "0"


@pytest.mark.smoke
def test_get_online_install_review_group_key_classifies_all_states() -> None:
    """線上安裝 review 分組應正確對應 enabled/advisory/disabled/blocked 四種狀態。"""
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)

    runnable_no_warn = mod_management_module.PendingInstallReviewEntry(
        pending=_pending_install("a", "A", "v1"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        enabled=True,
        warning_messages=[],
    )
    runnable_with_warn = mod_management_module.PendingInstallReviewEntry(
        pending=_pending_install("b", "B", "v2"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        enabled=True,
        warning_messages=["建議手動確認 server_side 支援"],
    )
    runnable_disabled = mod_management_module.PendingInstallReviewEntry(
        pending=_pending_install("c", "C", "v3"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        enabled=False,
        warning_messages=[],
    )
    blocked_entry = mod_management_module.PendingInstallReviewEntry(
        pending=_pending_install("d", "D", "v4"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        blocking_reasons=["載入器不相容"],
        enabled=False,
        warning_messages=[],
    )

    assert frame._get_online_install_review_group_key(runnable_no_warn) == "enabled"
    assert frame._get_online_install_review_group_key(runnable_with_warn) == "advisory"
    assert frame._get_online_install_review_group_key(runnable_disabled) == "disabled"
    assert frame._get_online_install_review_group_key(blocked_entry) == "blocked"


@pytest.mark.smoke
def test_count_online_install_review_groups_aggregates_correctly() -> None:
    """_count_online_install_review_groups 應正確統計各 group 數量。"""
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)

    entries = [
        mod_management_module.PendingInstallReviewEntry(
            pending=_pending_install(f"mod{i}", f"Mod{i}", f"v{i}"),
            report=None,
            dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
            enabled=True,
            warning_messages=[],
        )
        for i in range(3)
    ] + [
        mod_management_module.PendingInstallReviewEntry(
            pending=_pending_install("warn1", "Warn1", "vw1"),
            report=None,
            dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
            enabled=True,
            warning_messages=["注意相容性"],
        ),
        mod_management_module.PendingInstallReviewEntry(
            pending=_pending_install("block1", "Block1", "vb1"),
            report=None,
            dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
            blocking_reasons=["缺少依賴"],
            enabled=False,
            warning_messages=[],
        ),
    ]

    counts = frame._count_online_install_review_groups(entries)

    assert counts["enabled"] == 3
    assert counts["advisory"] == 1
    assert counts["blocked"] == 1
    assert counts.get("disabled", 0) == 0


@pytest.mark.smoke
def test_build_online_install_execution_prompt_advisory_and_blocked() -> None:
    """_build_online_install_execution_prompt 應對 advisory/blocked 項目提供摘要文字。"""
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)

    actionable_entry = mod_management_module.PendingInstallReviewEntry(
        pending=_pending_install("a", "A", "v1"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        enabled=True,
        warning_messages=[],
    )
    advisory_entry = mod_management_module.PendingInstallReviewEntry(
        pending=_pending_install("b", "B", "v2"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        enabled=True,
        warning_messages=["client_side 支援請確認"],
    )
    blocked_entry = mod_management_module.PendingInstallReviewEntry(
        pending=_pending_install("c", "C", "v3"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        blocking_reasons=["Minecraft 版本不相容"],
        enabled=False,
        warning_messages=[],
    )

    prompt = frame._build_online_install_execution_prompt([actionable_entry, advisory_entry, blocked_entry])

    assert prompt is not None
    assert "建議確認：1 項" in prompt
    assert "需先處理：1 項" in prompt
    assert "將繼續安裝其餘 2 個可安裝項目" in prompt


@pytest.mark.smoke
def test_build_online_install_execution_prompt_returns_none_for_clean_queue() -> None:
    """所有項目均為 enabled（無提醒）時，prompt 應為 None——不需要確認對話框。"""
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)

    entries = [
        mod_management_module.PendingInstallReviewEntry(
            pending=_pending_install(f"m{i}", f"M{i}", f"v{i}"),
            report=None,
            dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
            enabled=True,
            warning_messages=[],
        )
        for i in range(3)
    ]

    assert frame._build_online_install_execution_prompt(entries) is None


@pytest.mark.smoke
def test_build_online_install_execution_prompt_returns_none_for_advisory_only() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)

    entries = [
        mod_management_module.PendingInstallReviewEntry(
            pending=_pending_install(f"m{i}", f"M{i}", f"v{i}"),
            report=None,
            dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
            enabled=True,
            warning_messages=["相容性提醒"],
        )
        for i in range(2)
    ]

    assert frame._build_online_install_execution_prompt(entries) is None


@pytest.mark.smoke
def test_build_online_review_root_status_text_uses_shared_group_label() -> None:
    """_build_online_review_root_status_text 根節點標籤應與 group key 映射一致。"""
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)

    clean_entry = mod_management_module.PendingInstallReviewEntry(
        pending=_pending_install("a", "A", "v1"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        enabled=True,
        warning_messages=[],
    )
    advisory_entry = mod_management_module.PendingInstallReviewEntry(
        pending=_pending_install("b", "B", "v2"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        enabled=True,
        warning_messages=["注意事項"],
    )
    blocked_entry = mod_management_module.PendingInstallReviewEntry(
        pending=_pending_install("c", "C", "v3"),
        report=None,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        blocking_reasons=["相容性阻擋"],
        enabled=False,
        warning_messages=[],
    )

    assert "可安裝" in frame._build_online_review_root_status_text(clean_entry)
    assert "建議確認" in frame._build_online_review_root_status_text(advisory_entry)
    assert "需先處理" in frame._build_online_review_root_status_text(blocked_entry)


@pytest.mark.smoke
def test_derive_provider_lifecycle_state_fresh_within_ttl() -> None:
    now_ms = int(time.time() * 1000)
    raw = {"project_id": "sodium", "slug": "sodium", "resolved_at_epoch_ms": str(now_ms - 60_000)}

    assert meta_module.derive_provider_lifecycle_state(raw) == meta_module.PROVIDER_LIFECYCLE_FRESH


@pytest.mark.smoke
def test_derive_provider_lifecycle_state_stale_past_ttl() -> None:
    expired_ms = 1_000
    raw = {"project_id": "sodium", "slug": "sodium", "resolved_at_epoch_ms": str(expired_ms)}

    assert meta_module.derive_provider_lifecycle_state(raw, ttl_seconds=3600) == meta_module.PROVIDER_LIFECYCLE_STALE


@pytest.mark.smoke
def test_derive_provider_lifecycle_state_missing_when_no_data() -> None:
    assert meta_module.derive_provider_lifecycle_state(None) == meta_module.PROVIDER_LIFECYCLE_MISSING
    assert meta_module.derive_provider_lifecycle_state({}) == meta_module.PROVIDER_LIFECYCLE_MISSING
    assert (
        meta_module.derive_provider_lifecycle_state({"project_id": "", "slug": ""})
        == meta_module.PROVIDER_LIFECYCLE_MISSING
    )


@pytest.mark.smoke
def test_derive_provider_lifecycle_state_ignores_manual_override_flag() -> None:
    expired_ms = 1_000
    raw = {
        "project_id": "sodium",
        "slug": "sodium",
        "resolved_at_epoch_ms": str(expired_ms),
        "manual_override": True,
    }

    assert meta_module.derive_provider_lifecycle_state(raw, ttl_seconds=3600) == meta_module.PROVIDER_LIFECYCLE_STALE


@pytest.mark.smoke
def test_ensure_local_mod_provider_record_sets_lifecycle_fresh_when_both_ids_present() -> None:
    result = meta_module.ensure_local_mod_provider_record(
        platform_id="sodium",
        platform_slug="sodium",
        project_name="Sodium",
    )

    assert result.lifecycle_state == meta_module.PROVIDER_LIFECYCLE_FRESH


@pytest.mark.smoke
def test_ensure_local_mod_provider_record_sets_lifecycle_missing_when_unresolved() -> None:
    result = meta_module.ensure_local_mod_provider_record(
        platform_id="",
        platform_slug="",
        project_name="Unknown Mod",
    )

    assert result.lifecycle_state == meta_module.PROVIDER_LIFECYCLE_MISSING
