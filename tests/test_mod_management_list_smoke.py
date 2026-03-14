from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import src.ui.mod_management as mod_management_module
import src.utils.ui_utils as ui_utils_module
from src.utils.ui_utils import Colors, UIUtils


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
            return ("#all",)
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
def test_get_selected_online_categories_returns_expected_facets() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    frame_any = cast(Any, frame)
    frame_any.browse_category_var = SimpleNamespace(get=lambda: "效能優化")

    assert frame._get_selected_online_categories() == ["optimization"]


@pytest.mark.smoke
def test_build_online_browse_request_uses_browse_mode_when_query_empty() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    frame_any = cast(Any, frame)
    frame_any.browse_category_var = SimpleNamespace(get=lambda: "效能優化")
    frame_any.browse_sort_var = SimpleNamespace(get=lambda: "相關性")
    frame_any.browse_sort_options = {"相關性": "relevance"}
    frame_any.search_var = SimpleNamespace(get=lambda: "")
    frame.current_server = cast(
        Any,
        SimpleNamespace(minecraft_version="1.21.1", loader_type="fabric", loader_version="0.16.10"),
    )

    request, warning_message = frame._build_online_browse_request()

    assert warning_message is None
    assert request is not None
    assert request.is_browse_mode is True
    assert request.query == ""
    assert request.categories == ("optimization",)
    assert request.sort_by == "relevance"


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
def test_build_online_results_summary_text_shows_mode_sort_category_and_count() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    frame_any = cast(Any, frame)
    frame_any.search_var = SimpleNamespace(get=lambda: "sodium")
    frame_any.browse_sort_var = SimpleNamespace(get=lambda: "下載量")
    frame_any.browse_category_var = SimpleNamespace(get=lambda: "效能優化")
    frame.online_mods = [object(), object()]

    summary = frame._build_online_results_summary_text()

    assert summary == "搜尋 sodium｜2 筆｜排序 下載量"


@pytest.mark.smoke
def test_build_online_results_summary_text_shows_browse_mode_when_query_empty() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    frame_any = cast(Any, frame)
    frame_any.search_var = SimpleNamespace(get=lambda: "")
    frame_any.browse_sort_var = SimpleNamespace(get=lambda: "相關性")
    frame_any.browse_category_var = SimpleNamespace(get=lambda: "全部分類")
    frame.online_mods = []

    summary = frame._build_online_results_summary_text()

    assert summary == "瀏覽｜0 筆｜排序 相關性"


@pytest.mark.smoke
def test_build_online_browse_row_uses_plain_description() -> None:
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
    )


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
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    candidate = SimpleNamespace(
        project_id="Ha28R6CL",
        project_name="Fabric Language Kotlin",
        current_version="1.13.9",
        target_version_name="1.14.0",
        actionable=False,
        metadata_source="unresolved",
        metadata_note="metadata ensure 失敗：找不到可用的 provider metadata 或雜湊對應結果。",
        report=SimpleNamespace(warnings=[]),
        notes=[],
        local_mod=SimpleNamespace(file_path="C:/servers/Fabric/mods/fabric-language-kotlin-1.13.9+kotlin.2.3.10.jar"),
    )
    review_entry = mod_management_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[], advisory_items=[], notes=[]),
        blocking_reasons=["無法建立可用的 Modrinth metadata，暫時無法自動檢查更新。"],
        enabled=False,
        provider="modrinth",
        version_type="beta",
    )

    nodes = frame._build_local_update_task_nodes([review_entry, review_entry])

    root_nodes = [node for node in nodes if node.node_kind == "root"]
    metadata_nodes = [node for node in nodes if node.node_id.endswith("::metadata")]
    assert len(root_nodes) == 1
    assert len(metadata_nodes) == 1
    assert "Metadata 來源：尚未識別" in metadata_nodes[0].detail
    assert "metadata ensure 失敗" in metadata_nodes[0].detail


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

    assert any(node.node_kind == "root" and node.group_key == "enabled" for node in nodes)
    assert any(node.node_kind == "dependency" and node.parent_id == "fabric-api::abc" for node in nodes)
    assert any(node.node_kind == "warning" and node.parent_id == "fabric-api::abc" for node in nodes)


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

    dependency_details = [node.detail for node in nodes if node.node_kind == "dependency"]
    assert any("Fabric API、Lithium" in detail for detail in dependency_details)
    assert any("解析：project id 直連（高）" in detail for detail in dependency_details)


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

    dependency_details = [node.detail for node in nodes if node.node_kind == "dependency"]
    assert any(detail.startswith("required-by：Fabric API｜") for detail in dependency_details)
    assert not any("Fabric API、Lithium" in detail for detail in dependency_details)


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

    optional_parent = next(node for node in nodes if node.node_kind == "dependency-group")
    advisory_node = next(node for node in nodes if node.node_kind == "dependency")
    assert optional_parent.title == "可選依賴"
    assert advisory_node.parent_id == optional_parent.node_id
    assert advisory_node.values[0] == "略過"
    assert advisory_node.values[4] == "optional"
    assert "解析：project id 直連（高）" in advisory_node.detail
    assert "處理：可選依賴，預設略過" in advisory_node.detail


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
    assert root_node.values[5] == "可安裝｜依賴 1｜提醒 1"


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
def test_treeview_separator_detection_ignores_displaycolumns_all_placeholder(monkeypatch) -> None:
    tree = _HeaderAutoFitTree()

    monkeypatch.setattr(mod_management_module.FontManager, "get_dpi_scaled_size", lambda value: value)

    column_id = UIUtils._get_treeview_separator_column_from_x(tree, 140)

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
    assert any(node.node_kind == "issue" and node.parent_id == root_node.root_key for node in nodes)
    assert any(node.node_kind == "warning" and node.parent_id == root_node.root_key for node in nodes)


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
        blocking_reasons=["無法建立可用的 Modrinth metadata，暫時無法自動檢查更新。"],
        enabled=False,
        provider="modrinth",
        version_type="",
    )

    nodes = frame._build_local_update_task_nodes([review_entry])

    root_node = next(node for node in nodes if node.node_kind == "root")
    metadata_node = next(node for node in nodes if node.node_id.endswith("::metadata"))
    assert root_node.values[3] == "Modrinth｜待綁定"
    assert metadata_node.values[3] == "尚未識別"
    assert metadata_node.detail.startswith("Metadata 來源：尚未識別")
    assert "Metadata 狀態：metadata ensure 失敗" in metadata_node.detail


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
        metadata_note="metadata ensure 失敗：找不到可用的 provider metadata 或雜湊對應結果。",
        notes=[],
        report=None,
    )
    review_entry = mod_management_module.LocalUpdateReviewEntry(
        candidate=candidate,
        dependency_plan=SimpleNamespace(items=[], notes=[]),
        blocking_reasons=["無法建立可用的 Modrinth metadata，暫時無法自動檢查更新。"],
        enabled=False,
        provider="modrinth",
        version_type="",
        date_published="",
        changelog="",
    )

    text = frame._format_local_update_review_text(review_entry)

    assert "Metadata 來源：尚未識別" in text
    assert "Metadata 狀態：metadata ensure 失敗" in text


@pytest.mark.smoke
def test_format_local_update_review_text_includes_client_install_reminder_for_server_and_client_mod() -> None:
    frame = mod_management_module.ModManagementFrame.__new__(mod_management_module.ModManagementFrame)
    candidate = SimpleNamespace(
        project_name="Sodium",
        current_version="0.6.0",
        target_version_name="0.6.1",
        metadata_source="hash",
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
