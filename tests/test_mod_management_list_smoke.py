from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import src.models as models_module
import src.ui as ui_module
import src.ui.mods.online_mod_queue as online_mod_queue_module
import src.utils as utils_module
import src.utils.ui_support.ui_utils as ui_utils_module
from src.core import ModPlanning
from src.models import ModrinthVersionLookupResult, OnlineModVersion
from src.ui import (
    ModManagementSession,
    ModReviewWorkflow,
    format_online_version_report,
    get_online_version_status_text,
    sort_online_versions_for_server,
)


class _EmptyPlanningProvider:
    def resolve_project_names(self, project_ids: Iterable[str]) -> dict[str, str]:
        del project_ids
        return {}

    def get_version_details(self, version_id: str) -> tuple[str, OnlineModVersion | None]:
        del version_id
        return ("", None)

    def fetch_project_name(self, project_id: str) -> str | None:
        del project_id
        return None

    def get_versions(
        self,
        project_id: str,
        minecraft_version: str | None = None,
        loader: str | None = None,
    ) -> list[OnlineModVersion]:
        del project_id, minecraft_version, loader
        return []

    def get_current_versions_by_hashes(
        self, hashes: list[str], algorithm: str
    ) -> dict[str, ModrinthVersionLookupResult]:
        del hashes, algorithm
        return {}

    def get_latest_versions_by_hashes(
        self,
        hashes: list[str],
        algorithm: str,
        minecraft_version: str | None = None,
        loader: str | None = None,
    ) -> dict[str, ModrinthVersionLookupResult]:
        del hashes, algorithm, minecraft_version, loader
        return {}

    def get_recommended_version(
        self,
        project_id: str,
        minecraft_version: str | None,
        loader: str | None,
    ) -> OnlineModVersion | None:
        del project_id, minecraft_version, loader
        return None


class _EmptyLoaderRules:
    def compatible_versions(self, minecraft_version: str, loader: str) -> list[str]:
        del minecraft_version, loader
        return []


def _search_filter():
    return ui_module.OnlineBrowsePresenter(cast(Any, SimpleNamespace())).online_search_filter


def _review_server() -> SimpleNamespace:
    return SimpleNamespace(
        name="Test Server",
        path="C:/servers/Test",
        minecraft_version="1.21.1",
        loader_type="fabric",
        loader_version="0.16.0",
    )


def _empty_planning() -> ModPlanning:
    return ModPlanning(_EmptyPlanningProvider(), _EmptyLoaderRules())


def _review_planning(build_dependency_plan=None) -> Any:
    def empty_plan(*_args, **_kwargs) -> SimpleNamespace:
        return SimpleNamespace(items=[], advisory_items=[], unresolved_required=[], notes=[])

    return SimpleNamespace(
        provider=SimpleNamespace(resolve_project_names=lambda _project_ids: {}),
        analyze_version=lambda *_args, **_kwargs: SimpleNamespace(hard_errors=[], warnings=[]),
        build_dependency_plan=build_dependency_plan or empty_plan,
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
        request = ui_module.OnlineBrowseRequest("test", "1.21.1", "fabric", "relevance")
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


def _queue_feature(
    session: ModManagementSession,
    *,
    query: str = "",
    sort_label: str = "相關性",
) -> tuple[Any, SimpleNamespace]:
    presenter = SimpleNamespace(
        browse_search_entry=None,
        search_var=SimpleNamespace(get=lambda: query),
        browse_sort_var=SimpleNamespace(get=lambda: sort_label),
        browse_sort_options={"相關性": "relevance", "下載量": "downloads"},
        online_search_filter=_search_filter(),
    )
    controller = SimpleNamespace(mod_session=session, online_browse_presenter=presenter)
    feature = ui_module.ModManagementQueueOps(cast(Any, controller))
    controller.queue_ops = feature
    return feature, controller


def test_build_online_browse_request_returns_warning_when_query_empty() -> None:
    feature, _ = _queue_feature(
        _mod_session(SimpleNamespace(minecraft_version="1.21.1", loader_type="fabric", loader_version="0.16.10"))
    )

    request, warning_message = feature._build_online_browse_request()

    assert request is None
    assert warning_message == "請先輸入關鍵字再搜尋模組"


def test_get_online_version_dialog_hint_text_uses_server_context() -> None:
    feature, _ = _queue_feature(
        _mod_session(SimpleNamespace(minecraft_version="1.21.1", loader_type="fabric", loader_version="0.16.10"))
    )

    hint_text = feature._get_online_version_dialog_hint_text()

    assert hint_text == "相容性條件：MC 1.21.1 / fabric / 0.16.10"
    assert "留空" not in hint_text


def test_on_online_browse_filters_changed_refreshes_hint_and_reloads(monkeypatch: pytest.MonkeyPatch) -> None:
    feature, _ = _queue_feature(_mod_session())
    called: list[tuple[bool, bool] | str] = []

    monkeypatch.setattr(feature, "_refresh_online_filter_hint", lambda: called.append("hint"))
    monkeypatch.setattr(feature, "_refresh_online_results_summary", lambda: called.append("summary"))
    monkeypatch.setattr(
        feature,
        "_load_online_mods",
        lambda *, force=False, show_warning=True: called.append((force, show_warning)),
    )

    feature.on_online_browse_filters_changed("效能優化")

    assert called == ["hint", "summary", (True, False)]


def test_build_online_results_summary_text_shows_mode_sort_and_count() -> None:
    feature, _ = _queue_feature(_mod_session(online_mods=[object(), object()]), query="sodium", sort_label="下載量")

    summary = feature._build_online_results_summary_text()

    assert summary == "搜尋 sodium｜2 筆｜排序 下載量"


def test_build_online_results_summary_text_prompts_keyword_when_query_empty() -> None:
    feature, _ = _queue_feature(_mod_session(online_mods=[]))

    summary = feature._build_online_results_summary_text()

    assert summary == "請輸入關鍵字搜尋｜0 筆｜排序 相關性"


def test_build_online_browse_row_includes_prism_style_metadata() -> None:
    controller = SimpleNamespace()
    projection = ui_module.ModManagementTreeSyncOps(cast(Any, controller))

    mod = SimpleNamespace(
        name="Sodium",
        author="jellysquid3",
        latest_version="mc1.21-0.6.0",
        download_count=1234567,
        categories=["fabric", "optimization"],
        description="Client and server rendering optimizations.",
        slug="sodium",
    )

    row = projection._build_online_browse_row(mod)

    assert row == (
        "Sodium",
        "jellysquid3",
        "1,234,567",
        "Modrinth",
        "未知",
        "Client and server rendering optimizations.",
    )


def test_build_online_browse_row_keeps_full_description() -> None:
    controller = SimpleNamespace()
    projection = ui_module.ModManagementTreeSyncOps(cast(Any, controller))

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

    row = projection._build_online_browse_row(mod)

    assert row[5] == (
        "You can drink from a water source, cauldron or with vanilla items. "
        "Items have fluid compatibility and the full description should stay intact."
    )


def test_copy_online_mod_info_handles_clipboard_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    feature, controller = _queue_feature(_mod_session())
    selected_mod = SimpleNamespace(
        name="Fabric API",
        author="FabricMC",
        download_count=1234,
        source="modrinth",
        url="https://example.invalid/fabric-api",
    )
    controller.parent = SimpleNamespace()
    controller.update_status = lambda _message: None
    controller.tree_sync = SimpleNamespace(_format_online_environment_text=lambda _mod: "Fabric / server")
    monkeypatch.setattr(feature, "_get_selected_online_mod_context", lambda: (True, "fabric-api", selected_mod))

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

    feature.copy_online_mod_info()

    assert errors == [("複製失敗", "無法將模組資訊複製到剪貼簿：clipboard unavailable")]


def test_refresh_local_list_keeps_full_description(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    mock_tree = MagicMock()
    mock_item = MagicMock()
    mock_item.text.return_value = (
        "Core API module providing key hooks and intercompatibility. No truncation should happen."
    )
    mock_tree.topLevelItemCount.return_value = 1
    mock_tree.topLevelItem.return_value = mock_item

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
    session = _mod_session(local_mods=local_mods)
    presenter = SimpleNamespace(
        local_tree=mock_tree,
        local_search_var=SimpleNamespace(get=lambda: ""),
        local_filter_var=SimpleNamespace(get=lambda: "所有"),
        local_search_filter=_search_filter(),
        on_tree_selection_changed=lambda: None,
    )
    controller = SimpleNamespace(
        mod_session=session,
        local_mod_list_presenter=presenter,
        queue_ops=SimpleNamespace(_format_single_line_text=lambda text: text.replace("\n", " ")),
    )
    projection = ui_module.ModManagementTreeSyncOps(cast(Any, controller))

    def _capture_selected_mod_ids_func() -> set:
        return set()

    def _resolve_local_display_name_func(mod: Any, _enhanced: Any) -> str:
        return mod.name

    def _get_enhanced_attr_func(_enhanced: Any, _attr: str, default: Any) -> Any:
        return default

    monkeypatch.setattr(projection, "_capture_selected_mod_ids", _capture_selected_mod_ids_func)
    monkeypatch.setattr(projection, "_resolve_local_display_name", _resolve_local_display_name_func)
    monkeypatch.setattr(projection, "_get_enhanced_attr", _get_enhanced_attr_func)

    projection.refresh_local_list()

    assert session.snapshot().local_rows[0].values[-1] == (
        "Core API module providing key hooks and intercompatibility. No truncation should happen."
    )


def test_reveal_in_explorer_uses_windows_select_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded_calls: list[list[str]] = []

    def fake_run_checked(command, check=False):
        del check
        recorded_calls.append(list(command))

    monkeypatch.setattr(ui_utils_module, "os", SimpleNamespace(name="nt", environ={"WINDIR": "C:\\Windows"}))
    monkeypatch.setattr(ui_utils_module.shutil, "which", lambda _name: "explorer.exe")
    monkeypatch.setattr(utils_module.UIUtils, "_is_safe_windows_path_argument", lambda _path: True)
    monkeypatch.setattr(utils_module.SubprocessUtils, "run_checked", fake_run_checked)

    utils_module.UIUtils.reveal_in_explorer(Path("C:/servers/Alpha/mods/example.jar"))

    assert recorded_calls == [["explorer.exe", "/select,", "C:\\servers\\Alpha\\mods\\example.jar"]]


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
    projection = ui_module.ModManagementTreeSyncOps(cast(Any, SimpleNamespace()))
    local_mod = cast(Any, type("LocalMod", (), {"name": "Fabric API", "platform_id": "fabric-api"})())
    enhanced = cast(Any, type("EnhancedMod", (), {"name": "Dawn API", "project_id": "dawn-api", "slug": "dawn-api"})())

    display_name = projection._resolve_local_display_name(local_mod, enhanced)

    assert display_name == "Fabric API"


def test_resolve_local_display_name_uses_exact_enhancement_when_local_name_unknown() -> None:
    projection = ui_module.ModManagementTreeSyncOps(cast(Any, SimpleNamespace()))
    local_mod = cast(Any, type("LocalMod", (), {"name": "Unknown Mod", "platform_id": "fabric-api"})())
    enhanced = cast(
        Any, type("EnhancedMod", (), {"name": "Fabric API", "project_id": "P7dR8mSH", "slug": "fabric-api"})()
    )

    display_name = projection._resolve_local_display_name(local_mod, enhanced)

    assert display_name == "Fabric API"


def test_delete_local_mod_delegates_to_mod_manager_and_refreshes(tmp_path: Path, monkeypatch) -> None:
    frame = object.__new__(ui_module.ModManagementFrame)
    deleted_ids: list[list[str]] = []
    shown_messages: list[str] = []
    frame.mod_session = _mod_session(type("Server", (), {"path": str(tmp_path)})())
    frame.parent = cast(Any, object())
    frame.status_label = cast(Any, _StatusLabel())
    frame.update_status = frame.status_label.setText

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
        SimpleNamespace(
            mod_file_installer=SimpleNamespace(delete_local_mods_result=_delete_local_mods_result),
        ),
    )
    presenter = ui_module.LocalModListPresenter(cast(Any, frame))
    presenter.local_tree = cast(Any, _DeleteTree())
    presenter.load_local_mods = lambda: shown_messages.append("reloaded")

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

    presenter.delete_local_mod()

    assert deleted_ids == [["clumps", "fabric-api"]]
    assert shown_messages[0] == "reloaded"
    assert shown_messages[1] == "已刪除 2 個模組檔案"
    assert frame.status_label.text == "已刪除 2 個模組"


def test_delete_local_mod_shows_manager_failure_message(tmp_path: Path, monkeypatch) -> None:
    frame = object.__new__(ui_module.ModManagementFrame)
    shown_messages: list[str] = []
    frame.mod_session = _mod_session(type("Server", (), {"path": str(tmp_path)})())
    frame.parent = cast(Any, object())
    frame.status_label = cast(Any, _StatusLabel())
    frame.update_status = frame.status_label.setText
    frame.mod_manager = cast(
        Any,
        SimpleNamespace(
            mod_file_installer=SimpleNamespace(
                delete_local_mods_result=lambda _ids: SimpleNamespace(
                    affected_count=0,
                    completed=False,
                    partial=False,
                    message="刪除模組失敗: permission denied",
                    title="刪除失敗",
                    missing_ids=(),
                )
            ),
        ),
    )
    presenter = ui_module.LocalModListPresenter(cast(Any, frame))
    presenter.local_tree = cast(Any, _DeleteTree())
    presenter.load_local_mods = lambda: shown_messages.append("reloaded")

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

    presenter.delete_local_mod()

    assert shown_messages
    assert shown_messages[-1] == "刪除模組失敗: permission denied"
    assert frame.status_label.text == "刪除模組失敗: permission denied"


def test_install_pending_online_install_queue_deduplicates_shared_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = SimpleNamespace(parent=SimpleNamespace())

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
    controller.mod_session = _mod_session(_review_server(), pending=[first_pending, second_pending])

    shared_dependency = SimpleNamespace(
        project_id="cloth-config",
        version_id="dep-v1",
        project_name="Cloth Config",
        version_name="17.0.0",
        filename="cloth-config.jar",
        download_url="https://example.com/cloth-config.jar",
    )
    handoff = ui_module.ReviewExecutionHandoff(
        mode="online_install",
        context_stamp=ModReviewWorkflow(
            mod_planning=_empty_planning(),
            server=_review_server(),
            installed_mods=[],
        ).context_stamp,
        steps=(
            ui_module.ReviewInstallStep(
                kind="dependency",
                root_key="first-mod::v1",
                project_name=shared_dependency.project_name,
                version_name=shared_dependency.version_name,
                download_url=shared_dependency.download_url,
                filename=shared_dependency.filename,
                expected_hash="",
                provider="modrinth",
            ),
            ui_module.ReviewInstallStep(
                kind="online_root",
                root_key="first-mod::v1",
                project_name="First Mod",
                version_name="1.0.0",
                download_url="https://example.com/first.jar",
                filename="first.jar",
                expected_hash="",
                provider="modrinth",
            ),
            ui_module.ReviewInstallStep(
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
        unselected_count=0,
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

    controller.ui_queue = _ImmediateQueue()
    controller.local_mod_list_presenter = SimpleNamespace(
        load_local_mods=lambda: queued_items.append("load_local_mods")
    )
    controller.queue_ops = SimpleNamespace(_refresh_online_queue_button=lambda: None)
    controller.update_status_safe = lambda _message: None
    controller.update_progress_safe = lambda _value: None
    controller.mod_manager = SimpleNamespace(install_remote_mod_file=_record_install)
    executor = ui_module.ModManagementInstallExecutor(cast(Any, controller))
    monkeypatch.setattr(
        executor,
        "_make_step_progress_callback",
        lambda *_args, **_kwargs: lambda *_inner_args, **_inner_kwargs: None,
    )
    monkeypatch.setattr(executor, "_validate_review_handoff", lambda *_args, **_kwargs: True)

    class _ImmediateScope:
        def submit(self, work, **_kwargs):
            work()
            return

    controller.scope = _ImmediateScope()

    def _show_message(title: str, message: str, parent=None, message_level="info", **_kwargs) -> None:
        _ = parent
        if message_level == "info":
            shown_messages.append((title, message))

    def _confirm_dialog(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(utils_module.UIUtils, "ask_yes_no_cancel", _confirm_dialog)
    monkeypatch.setattr(utils_module.UIUtils, "show_message", _show_message)

    dialog = SimpleNamespace(destroy=lambda: dialog_destroyed.append(True))

    executor.execute_online_review(dialog, handoff)

    assert dialog_destroyed == [True]
    assert install_calls == [
        (shared_dependency.download_url, shared_dependency.filename),
        ("https://example.com/first.jar", "first.jar"),
        ("https://example.com/second.jar", "second.jar"),
    ]
    assert any("必要依賴：已補裝 1 個" in message for _title, message in shown_messages)
    assert any("已合併 1 個重複項目，避免重複下載" in message for _title, message in shown_messages)


def test_prepare_online_install_review_entries_rebuilds_dependency_simulation_from_selected_roots() -> None:
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

    dependency_item = SimpleNamespace(
        project_id="dep-1",
        project_name="Shared Dependency",
        version_id="dep-v1",
        version_name="1.0.0",
        filename="shared-dependency.jar",
        included_by_default=True,
    )

    def fake_build_dependency_plan(_version, **kwargs):
        installed_mods = kwargs.get("installed_mods", [])
        root_project_name = kwargs.get("root_project_name", "")
        if root_project_name == "First Mod":
            return SimpleNamespace(items=[dependency_item], advisory_items=[], unresolved_required=[], notes=[])
        if any(getattr(mod, "platform_id", "") == "dep-1" for mod in installed_mods):
            return SimpleNamespace(items=[], advisory_items=[], unresolved_required=[], notes=[])
        return SimpleNamespace(items=[dependency_item], advisory_items=[], unresolved_required=[], notes=[])

    handoff = (
        ModReviewWorkflow(
            mod_planning=_review_planning(fake_build_dependency_plan),
            server=_review_server(),
            installed_mods=[],
        )
        .start_online_session(pending_items)
        .build_handoff()
    )

    assert handoff.dependency_count == 1
    assert handoff.duplicate_dependency_count == 0


def test_prepare_online_install_review_entries_blocks_client_only_mod() -> None:
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

    snapshot = (
        ModReviewWorkflow(mod_planning=_review_planning(), server=_review_server(), installed_mods=[])
        .start_online_session(pending_items)
        .snapshot()
    )

    assert snapshot.actionable_count == 0
    assert snapshot.roots[0].root_key == "client-only-mod::v-client-only"
    assert "僅 client 端" in snapshot.roots[0].summary


def test_prepare_online_install_review_entries_warns_unknown_server_side() -> None:
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

    snapshot = (
        ModReviewWorkflow(mod_planning=_review_planning(), server=_review_server(), installed_mods=[])
        .start_online_session(pending_items)
        .snapshot()
    )

    assert snapshot.actionable_count == 1
    assert "未明確標示 server 端支援" in snapshot.roots[0].summary


def test_add_pending_online_install_blocks_client_only_mod(monkeypatch) -> None:
    feature, controller = _queue_feature(_mod_session())
    controller.parent = SimpleNamespace()
    controller.update_status_safe = lambda _message: None
    monkeypatch.setattr(feature, "_refresh_online_queue_button", lambda: None)

    messages: list[tuple[str, str]] = []

    def _show_message(title: str, message: str, _parent=None, message_level="info", **_kwargs) -> None:
        if message_level == "warning":
            messages.append((title, message))

    monkeypatch.setattr(utils_module.UIUtils, "show_message", _show_message)

    blocked_version = SimpleNamespace(version_id="v-client-only", display_name="1.0.0")
    added = feature._add_pending_online_install(
        models_module.PendingOnlineInstall(
            "client-only-mod",
            "Client Only Mod",
            blocked_version,
            server_side="unsupported",
            client_side="required",
        )
    )

    assert added is False
    assert controller.mod_session.pending_online_installs == ()
    assert messages == [
        (
            "無法加入安裝清單",
            "此模組標記為僅 client 端（server_side=unsupported），不可安裝到伺服器",
        )
    ]


def test_add_pending_online_install_replaces_same_version_item(monkeypatch) -> None:
    feature, controller = _queue_feature(_mod_session())
    controller.parent = SimpleNamespace()
    controller.update_status_safe = lambda _message: None
    monkeypatch.setattr(feature, "_refresh_online_queue_button", lambda: None)
    monkeypatch.setattr(utils_module.UIUtils, "show_message", lambda *_args, **_kwargs: None)

    first_version = SimpleNamespace(version_id="v1", display_name="1.0.0")
    second_version = SimpleNamespace(version_id="v1", display_name="1.0.1")

    first_added = feature._add_pending_online_install(
        models_module.PendingOnlineInstall("fabric-api", "Fabric API", first_version)
    )
    second_added = feature._add_pending_online_install(
        models_module.PendingOnlineInstall("fabric-api", "Fabric API Updated", second_version)
    )

    assert first_added is True
    assert second_added is True
    assert len(controller.mod_session.pending_online_installs) == 1
    assert controller.mod_session.pending_online_installs[0].project_name == "Fabric API Updated"


def test_format_online_version_report_includes_provider_and_changelog() -> None:
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

    session = ModReviewWorkflow(
        mod_planning=_empty_planning(), server=_review_server(), installed_mods=[]
    ).start_local_update_session(
        SimpleNamespace(candidates=[candidate], notes=[], metadata_summary=SimpleNamespace(notes=[])),
        "全部模組",
    )
    root_key = "local::C:/servers/demo/mods/unknown-mod.jar"
    assert session.apply_selection({root_key}, False) is True
    snapshot = session.snapshot()

    assert snapshot.roots[0].root_key == root_key
    assert snapshot.selected_count == 0


def test_load_local_mods_discards_stale_scan_results(tmp_path: Path) -> None:
    controller = SimpleNamespace()
    server_a = SimpleNamespace(name="server-a", path=str(tmp_path / "server-a"))
    server_b = SimpleNamespace(name="server-b", path=str(tmp_path / "server-b"))
    sentinel_mods = [SimpleNamespace(filename="sentinel.jar")]
    enhancement_calls: list[str] = []
    queued_items: list[Any] = []

    old_session = _mod_session(server_a, local_mods=sentinel_mods)
    controller.mod_session = old_session
    controller.mod_manager = SimpleNamespace()
    controller.update_status_safe = lambda _message: None
    controller.update_progress_safe = lambda _value: None
    controller.tree_sync = SimpleNamespace(refresh_local_list=lambda: queued_items.append("refresh_local_list"))
    controller.ui_queue = SimpleNamespace(put=lambda item: queued_items.append(item))
    presenter = ui_module.LocalModListPresenter(cast(Any, controller))
    presenter.enhance_local_mods = lambda _scope=None: enhancement_calls.append("called")

    def _scan_mods() -> list[Any]:
        old_session.invalidate()
        controller.mod_session = _mod_session(server_b, local_mods=sentinel_mods)
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

    controller.mod_manager.scan_mods = _scan_mods

    class _ImmediateScope:
        def submit(self, work, **_kwargs):
            work()
            return

    controller.scope = _ImmediateScope()

    presenter.load_local_mods()

    assert controller.mod_session.local_mods == tuple(sentinel_mods)
    assert enhancement_calls == []
    assert queued_items == []


def test_prepare_local_update_review_entries_replays_cached_dependency_plan_snapshot() -> None:
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

        def replace_review_metadata(self, _file_path: Path, _provider_metadata: dict[str, Any]) -> None:
            return

    telemetry = {"checked": 0, "migrated": 0, "replayed": 0, "fallback_rebuild": 0}
    manager = SimpleNamespace(index_manager=_StubIndexManager())
    planning = _review_planning(
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should use cached dependency plan snapshot"))
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
        mod_planning=planning,
        server=_review_server(),
        installed_mods=[],
        telemetry=telemetry,
        mod_manager=manager,
    ).start_local_update_session(
        SimpleNamespace(candidates=[candidate], notes=[], metadata_summary=SimpleNamespace(notes=[])),
        "全部模組",
    )
    snapshot = session.snapshot()

    assert snapshot.selected_count == 0
    assert "Fabric API" in snapshot.roots[0].summary
    assert telemetry["replayed"] == 1


def test_prepare_local_update_review_entries_rebuilds_when_cached_snapshot_version_mismatch() -> None:
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
                    included_by_default=True,
                    is_optional=False,
                )
            ],
            advisory_items=[],
            unresolved_required=[],
            notes=[],
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
        mod_planning=_review_planning(_rebuilt_dependency_plan),
        server=_review_server(),
        installed_mods=[],
        telemetry=telemetry,
        mod_manager=manager,
    ).start_local_update_session(
        SimpleNamespace(candidates=[candidate], notes=[], metadata_summary=SimpleNamespace(notes=[])),
        "全部模組",
    )

    assert calls["count"] == 1
    assert "Rebuilt Dependency" in session.snapshot().roots[0].summary
    assert telemetry["fallback_rebuild"] == 1


def test_prepare_local_update_review_entries_migrates_legacy_snapshot_and_persists() -> None:
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
    planning = _review_planning(
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("should replay migrated snapshot instead of rebuilding")
        )
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
        mod_planning=planning,
        server=_review_server(),
        installed_mods=[],
        telemetry=telemetry,
        mod_manager=manager,
    ).start_local_update_session(
        SimpleNamespace(candidates=[candidate], notes=[], metadata_summary=SimpleNamespace(notes=[])),
        "全部模組",
    )

    assert "Fabric API" in session.snapshot().roots[0].summary
    assert any("dependency_plan_v2" in payload and "dependency_plan_v1" not in payload for payload in captured_writes)
    migrated_snapshot = captured_writes[0]["dependency_plan_v2"]
    assert migrated_snapshot["schema_version"] == 2
    assert "root_enabled" not in migrated_snapshot
    assert "enabled" not in migrated_snapshot["items"][0]
    assert migrated_snapshot["items"][0]["included_by_default"] is True
    assert isinstance(migrated_snapshot.get("graph_edges"), list)
    assert migrated_snapshot["graph_edges"][0]["edge"] == "required"
    assert telemetry.get("checked", 0) == 1
    assert telemetry.get("migrated", 0) == 1
    assert telemetry.get("replayed", 0) == 1
    assert telemetry.get("fallback_rebuild", 0) == 0
