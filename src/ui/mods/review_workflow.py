"""Mod Review workflow 的單一外部 seam"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from src.core import ModPlanning
from src.models import (
    LocalModUpdatePlan,
    PendingOnlineInstall,
)
from src.utils import (
    LOCAL_UPDATE_SKIPPED_BLOCKED_TEMPLATE,
    LOCAL_UPDATE_SKIPPED_RETRYABLE_TEMPLATE,
    LOCAL_UPDATE_SKIPPED_UNKNOWN_TEMPLATE,
    extract_primary_file_hash,
)

from .mod_presentation import build_server_install_blocking_reason, build_server_install_warning_line
from .review_contracts import (
    ReviewExecutionHandoff,
    ReviewInstallStep,
    ReviewRootView,
    ReviewTaskView,
    ReviewViewSnapshot,
    build_review_context_stamp,
    describe_context_mismatch,
    normalize_status_value,
)
from .review_dependency import (
    append_selected_dependency_simulations,
    build_dependency_review_key,
    build_installed_mod_simulation_item,
    get_selected_dependency_install_items,
)
from .review_details import format_local_update_review_text, format_pending_install_review_text
from .review_formatting import (
    ReviewFormattingMixin,
    build_review_subtitle,
    dedupe_review_messages,
    format_completion_notes,
    format_review_overview_text,
    resolve_local_update_review_project_page_url,
    resolve_pending_install_review_project_page_url,
)
from .review_grouping import (
    ReviewGroupingMixin,
    build_local_update_review_key,
    build_pending_install_review_key,
    count_local_update_review_groups,
    count_online_install_review_groups,
    get_review_group_specs,
)
from .review_prompts import (
    build_local_update_execution_prompt,
    build_non_official_source_confirmation_prompt,
    build_online_install_execution_prompt,
    collect_non_official_source_warning_messages,
)
from .review_selection import (
    collect_review_entry_selected_overrides,
    count_selected_runnable_entries,
    set_review_entries_selected,
)
from .review_snapshot_store import LocalReviewSnapshotStore
from .review_state import LocalUpdateReviewEntry, PendingInstallReviewEntry


class _ReviewPresentation(ReviewGroupingMixin, ReviewFormattingMixin):
    """只供 workflow 使用的 presentation implementation"""

    def __init__(self, telemetry: dict[str, int]) -> None:
        self._dependency_snapshot_migration_totals = telemetry


def _freeze_node(node: Any) -> ReviewTaskView:
    return ReviewTaskView(
        node_id=node.node_id,
        root_key=node.root_key,
        group_key=node.group_key,
        title=node.title,
        values=tuple(node.values),
        node_kind=node.node_kind,
        parent_id=node.parent_id,
        detail=node.detail,
    )


def _dependency_step(item: Any, root_key: str) -> ReviewInstallStep:
    return ReviewInstallStep(
        kind="dependency",
        root_key=root_key,
        project_name=str(getattr(item, "project_name", "") or "未知依賴"),
        version_name=str(getattr(item, "version_name", "") or ""),
        download_url=str(getattr(item, "download_url", "") or ""),
        filename=str(getattr(item, "filename", "") or ""),
        expected_hash=str(getattr(item, "expected_hash", "") or ""),
        provider=str(getattr(item, "provider", "modrinth") or "modrinth"),
    )


def _default_dependency_selected_keys(dependency_plan: Any) -> set[tuple[str, str]]:
    return {
        build_dependency_review_key(item)
        for item in [
            *list(getattr(dependency_plan, "items", []) or []),
            *list(getattr(dependency_plan, "advisory_items", []) or []),
        ]
        if bool(getattr(item, "included_by_default", True))
    }


class ModReviewWorkflow:
    """建立 Review session、view snapshot 與 immutable execution handoff"""

    def __init__(
        self,
        *,
        mod_planning: ModPlanning,
        server: Any,
        installed_mods: list[Any],
        telemetry: dict[str, int] | None = None,
        mod_manager: Any | None = None,
    ) -> None:
        self.context_stamp = build_review_context_stamp(server, installed_mods)
        self._mod_planning = mod_planning
        self._server = server
        self._installed_mods = deepcopy(installed_mods)
        self._telemetry = (
            telemetry if telemetry is not None else {"checked": 0, "migrated": 0, "replayed": 0, "fallback_rebuild": 0}
        )
        self._snapshot_store = (
            LocalReviewSnapshotStore(mod_manager, self._telemetry) if mod_manager is not None else None
        )
        self._presentation = _ReviewPresentation(self._telemetry)

    @staticmethod
    def validate_handoff_context(
        handoff: ReviewExecutionHandoff,
        server: Any,
        installed_mods: list[Any],
    ) -> str:
        """
        比對 handoff 與目前伺服器內容

        Args:
            handoff: Review session 產生的不可變執行契約
            server: 執行前重新取得的目標伺服器
            installed_mods: 執行前重新掃描的已安裝 Mod

        Returns:
            最先出現的失效原因；context 相符時為空字串
        """
        actual = build_review_context_stamp(server, installed_mods)
        return describe_context_mismatch(handoff.context_stamp, actual)

    @property
    def _context(self) -> tuple[str, str, str]:
        return (
            self.context_stamp.minecraft_version,
            self.context_stamp.loader_type,
            self.context_stamp.loader_version,
        )

    def start_online_session(self, pending_items: list[PendingOnlineInstall]) -> OnlineReviewSession:
        """
        建立線上待安裝項目的 Review session

        Args:
            pending_items: 工作階段目前的待安裝清單

        Returns:
            持有深拷貝分析結果的線上 Review session
        """
        entries = self._prepare_online_entries(deepcopy(pending_items))
        return OnlineReviewSession(self, tuple(entries))

    def start_local_update_session(self, update_plan: LocalModUpdatePlan, scope_text: str) -> LocalReviewSession:
        """
        建立本地更新計畫的 Review session

        Args:
            update_plan: 已完成相容性與版本分析的更新計畫
            scope_text: Review subtitle 使用的範圍描述

        Returns:
            可操作選取狀態的本地 Review session
        """
        plan = deepcopy(update_plan)
        entries = self._prepare_local_entries(plan)
        return LocalReviewSession(self, plan, scope_text, tuple(entries))

    def _prepare_online_entries(self, pending_items: list[PendingOnlineInstall]) -> list[PendingInstallReviewEntry]:
        minecraft_version, loader_type, loader_version = self._context
        simulated_installed_mods = deepcopy(self._installed_mods)
        entries: list[PendingInstallReviewEntry] = []
        for pending in pending_items:
            report = self._mod_planning.analyze_version(
                pending.version,
                project_id=pending.project_id,
                project_name=pending.project_name,
                minecraft_version=minecraft_version,
                loader=loader_type,
                loader_version=loader_version,
                installed_mods=simulated_installed_mods,
            )
            dependency_plan = self._mod_planning.build_dependency_plan(
                pending.version,
                minecraft_version=minecraft_version,
                loader=loader_type,
                loader_version=loader_version,
                installed_mods=simulated_installed_mods,
                root_project_id=pending.project_id,
                root_project_name=pending.project_name,
            )
            blocking_reasons = [
                *list(getattr(report, "hard_errors", []) or []),
                *list(getattr(dependency_plan, "unresolved_required", []) or []),
            ]
            server_block = build_server_install_blocking_reason(pending.server_side)
            if server_block:
                blocking_reasons.append(server_block)
            warnings = list(getattr(report, "warnings", []) or [])
            server_warning = build_server_install_warning_line(pending.server_side)
            if server_warning:
                warnings.append(server_warning)
            entry = PendingInstallReviewEntry(
                pending=pending,
                report=report,
                dependency_plan=dependency_plan,
                blocking_reasons=blocking_reasons,
                warning_messages=warnings,
                selected=not blocking_reasons,
                selected_dependency_keys=_default_dependency_selected_keys(dependency_plan),
                provider=str(getattr(pending.version, "provider", "modrinth") or "modrinth"),
                version_type=str(getattr(pending.version, "version_type", "") or ""),
                date_published=str(getattr(pending.version, "date_published", "") or ""),
                changelog=str(getattr(pending.version, "changelog", "") or ""),
            )
            entry.warning_messages = dedupe_review_messages(
                [*warnings, *collect_non_official_source_warning_messages(entry, selected_only=True)]
            )
            entries.append(entry)
            if entry.actionable:
                append_selected_dependency_simulations(
                    simulated_installed_mods,
                    dependency_plan,
                    entry.selected_dependency_keys,
                    build_installed_mod_simulation_item,
                )
                primary_file = getattr(pending.version, "primary_file", None) or {}
                simulated_installed_mods.append(
                    build_installed_mod_simulation_item(
                        pending.project_id,
                        pending.project_name,
                        str(primary_file.get("filename", "") or pending.project_name),
                        str(
                            getattr(pending.version, "version_number", "")
                            or getattr(pending.version, "display_name", "")
                        ),
                    )
                )
        return entries

    def _prepare_local_entries(
        self,
        update_plan: LocalModUpdatePlan,
        root_selected_overrides: dict[str, bool] | None = None,
        dependency_selected_overrides: dict[tuple[str, tuple[str, str]], bool] | None = None,
    ) -> list[LocalUpdateReviewEntry]:
        minecraft_version, loader_type, loader_version = self._context
        simulated_installed_mods = deepcopy(self._installed_mods)
        entries: list[LocalUpdateReviewEntry] = []
        for candidate in update_plan.candidates:
            root_key = build_local_update_review_key(candidate)
            dependency_plan: Any = SimpleNamespace(items=[], advisory_items=[], unresolved_required=[], notes=[])
            blocking_reasons = list(getattr(candidate, "hard_errors", []) or [])
            warnings = dedupe_review_messages(
                [
                    *list(getattr(candidate, "current_issues", []) or []),
                    *list(getattr(candidate, "dependency_issues", []) or []),
                ]
            )
            target_version = getattr(candidate, "target_version", None)
            cached_plan: Any | None = None
            cached_root_selected: bool | None = None
            cached_dependency_selected_keys: set[tuple[str, str]] | None = None
            if getattr(candidate, "update_available", False) and target_version is not None:
                cached_plan, cached_root_selected, cached_dependency_selected_keys = (
                    self._snapshot_store.load(candidate) if self._snapshot_store else (None, None, None)
                )
                dependency_plan = cached_plan or self._mod_planning.build_dependency_plan(
                    target_version,
                    minecraft_version=minecraft_version,
                    loader=loader_type,
                    loader_version=loader_version,
                    installed_mods=simulated_installed_mods,
                    root_project_id=candidate.project_id,
                    root_project_name=candidate.project_name,
                )
                dependency_selected_keys = (
                    set(cached_dependency_selected_keys)
                    if cached_plan is not None and cached_dependency_selected_keys is not None
                    else _default_dependency_selected_keys(dependency_plan)
                )
                for item in [
                    *list(getattr(dependency_plan, "items", []) or []),
                    *list(getattr(dependency_plan, "advisory_items", []) or []),
                ]:
                    override_key = (root_key, build_dependency_review_key(item))
                    if dependency_selected_overrides and override_key in dependency_selected_overrides:
                        if dependency_selected_overrides[override_key]:
                            dependency_selected_keys.add(override_key[1])
                        else:
                            dependency_selected_keys.discard(override_key[1])
                blocking_reasons.extend(list(getattr(dependency_plan, "unresolved_required", []) or []))
            else:
                dependency_selected_keys = set()
            default_selected = bool(getattr(candidate, "actionable", False)) and not blocking_reasons
            if not blocking_reasons and root_selected_overrides is None and cached_root_selected is not None:
                default_selected = cached_root_selected
            selected = (
                root_selected_overrides.get(root_key, default_selected) if root_selected_overrides else default_selected
            )
            entry = LocalUpdateReviewEntry(
                candidate=candidate,
                dependency_plan=dependency_plan,
                blocking_reasons=blocking_reasons,
                selected=selected,
                selected_dependency_keys=dependency_selected_keys,
                provider=str(getattr(target_version, "provider", "modrinth") or "modrinth")
                if target_version
                else "modrinth",
                version_type=str(getattr(target_version, "version_type", "") or "") if target_version else "",
                date_published=str(getattr(target_version, "date_published", "") or "") if target_version else "",
                changelog=str(getattr(target_version, "changelog", "") or "") if target_version else "",
            )
            entry.warning_messages = collect_non_official_source_warning_messages(entry, selected_only=True)
            entries.append(entry)
            if cached_plan is None and self._snapshot_store:
                self._snapshot_store.save(
                    candidate,
                    dependency_plan,
                    root_selected=selected,
                    selected_dependency_keys=dependency_selected_keys,
                )
            if warnings:
                candidate.notes = dedupe_review_messages([*warnings, *list(getattr(candidate, "notes", []) or [])])
            if entry.actionable:
                append_selected_dependency_simulations(
                    simulated_installed_mods,
                    dependency_plan,
                    entry.selected_dependency_keys,
                    build_installed_mod_simulation_item,
                )
                simulated_installed_mods.append(
                    build_installed_mod_simulation_item(
                        candidate.project_id,
                        candidate.project_name,
                        candidate.target_filename or candidate.filename,
                        candidate.target_version_name,
                    )
                )
        return entries


class OnlineReviewSession:
    """線上安裝 Review 的 entries、呈現快照與執行 handoff owner"""

    def __init__(self, workflow: ModReviewWorkflow, entries: tuple[PendingInstallReviewEntry, ...]) -> None:
        self._workflow = workflow
        self._entries = entries

    def snapshot(self) -> ReviewViewSnapshot:
        """
        建立目前線上 Review 狀態的 UI 快照

        Returns:
            完整任務樹、摘要與計數的不可變投影
        """
        presentation = self._workflow._presentation
        entries = list(self._entries)
        nodes = presentation._build_online_review_task_nodes(entries)
        counts = count_online_install_review_groups(entries)
        actionable_count = sum(entry.actionable for entry in entries)
        _, duplicate_count = _collect_dependency_keys(entries)
        notes = presentation._collect_online_review_global_notes(entries)
        return ReviewViewSnapshot(
            mode="online_install",
            subtitle=build_review_subtitle(
                prefix_segments=["已重驗證可安裝性與必要依賴", f"可安裝 {actionable_count} 項"],
                count_segments=((counts.get("advisory", 0), "建議確認"),),
                blocked_count=counts.get("blocked", 0),
                blocked_label="待處理",
                migrated_snapshot_count=self._workflow._telemetry.get("migrated", 0),
                migrated_snapshot_label="快照自動遷移",
            ),
            overview=format_review_overview_text(
                entries,
                nodes,
                action_label="安裝",
                global_notes=notes,
                deduped_dependency_count=duplicate_count,
            ),
            task_nodes=tuple(_freeze_node(node) for node in nodes),
            roots=tuple(
                ReviewRootView(
                    build_pending_install_review_key(
                        entry.pending.project_id, getattr(entry.pending.version, "version_id", "")
                    ),
                    format_pending_install_review_text(entry),
                    resolve_pending_install_review_project_page_url(entry),
                )
                for entry in entries
            ),
            group_specs=get_review_group_specs(),
            action_label="安裝",
            selected_count=actionable_count,
            actionable_count=actionable_count,
            blocked_count=counts.get("blocked", 0),
        )

    def build_handoff(self) -> ReviewExecutionHandoff:
        """
        將可執行 entries 轉為去重後的安裝 handoff

        Returns:
            含 context stamp、依賴步驟與確認文字的執行契約
        """
        entries = list(self._entries)
        actionable = [entry for entry in entries if entry.actionable]
        counts = count_online_install_review_groups(entries)
        unique_dependencies: set[tuple[str, str, str, str]] = set()
        steps: list[ReviewInstallStep] = []
        duplicate_count = 0
        root_keys: list[str] = []
        for entry in actionable:
            root_key = build_pending_install_review_key(
                entry.pending.project_id, getattr(entry.pending.version, "version_id", "")
            )
            for item in get_selected_dependency_install_items(entry.dependency_plan, entry.selected_dependency_keys):
                key = _dependency_key(item)
                if key in unique_dependencies:
                    duplicate_count += 1
                    continue
                unique_dependencies.add(key)
                steps.append(_dependency_step(item, root_key))
            primary_file = getattr(entry.pending.version, "primary_file", None) or {}
            root_keys.append(root_key)
            steps.append(
                ReviewInstallStep(
                    kind="online_root",
                    root_key=root_key,
                    project_name=entry.pending.project_name,
                    version_name=str(getattr(entry.pending.version, "display_name", "") or ""),
                    download_url=str(primary_file.get("url", "") or ""),
                    filename=str(primary_file.get("filename", "") or ""),
                    expected_hash=extract_primary_file_hash(entry.pending.version)
                    or extract_primary_file_hash(entry.pending.version, "sha256"),
                    provider=entry.provider,
                )
            )
        skipped = []
        if counts.get("unselected", 0):
            skipped.append(f"未選取 {counts['unselected']} 項")
        if counts.get("blocked", 0):
            skipped.append(f"需先處理 {counts['blocked']} 項")
        completion_notes = format_completion_notes(
            [
                *[message for entry in actionable for message in entry.warning_messages],
                *[message for entry in actionable for message in list(getattr(entry.report, "notes", []) or [])],
                *[
                    message
                    for entry in actionable
                    for message in list(getattr(entry.dependency_plan, "notes", []) or [])
                ],
            ]
        )
        return ReviewExecutionHandoff(
            mode="online_install",
            context_stamp=self._workflow.context_stamp,
            steps=tuple(steps),
            root_keys=tuple(root_keys),
            confirmation_prompt=build_online_install_execution_prompt(entries) or "",
            source_confirmation_prompt=build_non_official_source_confirmation_prompt(actionable, action_label="安裝"),
            skipped_text="\n略過項目：\n- " + "\n- ".join(skipped) if skipped else "",
            completion_notes=completion_notes,
            unselected_count=counts.get("unselected", 0),
            dependency_count=len(unique_dependencies),
            duplicate_dependency_count=duplicate_count,
        )


class LocalReviewSession:
    """本地更新 Review 的選取狀態、快照與執行 handoff owner"""

    def __init__(
        self,
        workflow: ModReviewWorkflow,
        update_plan: LocalModUpdatePlan,
        scope_text: str,
        entries: tuple[LocalUpdateReviewEntry, ...],
    ) -> None:
        self._workflow = workflow
        self._update_plan = update_plan
        self._scope_text = scope_text
        self._entries = entries

    @property
    def empty(self) -> bool:
        return not self._entries

    def empty_message(self) -> str:
        """
        取得本地 Review 沒有項目時的說明

        Returns:
            計畫附註或依 scope 產生的預設訊息
        """
        notes = list(getattr(self._update_plan, "notes", []) or [])
        return notes[0] if notes else f"{self._scope_text}目前沒有可更新或需處理的模組"

    def snapshot(self) -> ReviewViewSnapshot:
        """
        建立目前本地更新 Review 的 UI 快照

        Returns:
            完整任務樹、摘要、選取與分組計數
        """
        presentation = self._workflow._presentation
        entries = list(self._entries)
        nodes = presentation._build_local_update_task_nodes(entries)
        counts = count_local_update_review_groups(entries)
        selected_count = count_selected_runnable_entries(entries)
        notes = presentation._collect_local_update_global_notes(self._update_plan, entries)
        return ReviewViewSnapshot(
            mode="local_update",
            subtitle=build_review_subtitle(
                prefix_segments=[f"範圍：{self._scope_text}", f"已選取更新 {selected_count} 項"],
                count_segments=(
                    (counts["advisory"], "建議確認"),
                    (counts["retryable"], "可重試"),
                    (counts["unknown"], "待識別"),
                ),
                blocked_count=counts["blocked"],
                blocked_label="阻擋",
                migrated_snapshot_count=self._workflow._telemetry.get("migrated", 0),
            ),
            overview=format_review_overview_text(entries, nodes, action_label="更新", global_notes=notes),
            task_nodes=tuple(_freeze_node(node) for node in nodes),
            roots=tuple(
                ReviewRootView(
                    build_local_update_review_key(entry.candidate),
                    format_local_update_review_text(entry),
                    resolve_local_update_review_project_page_url(entry),
                )
                for entry in entries
            ),
            group_specs=get_review_group_specs(),
            action_label="更新",
            selected_count=selected_count,
            actionable_count=sum(entry.actionable for entry in entries),
            blocked_count=counts["blocked"],
        )

    def apply_selection(self, selected_node_ids: set[str], selected: bool) -> bool:
        """
        套用 root 或可選依賴節點的選取狀態

        Args:
            selected_node_ids: 使用者選取的任務樹節點 ID
            selected: 要套用的新選取狀態

        Returns:
            狀態有變更並完成重新規劃時為 True
        """
        if not selected_node_ids:
            return False
        changed = self._apply_dependency_selection(selected_node_ids, selected)
        if not changed:
            entry_map = {build_local_update_review_key(entry.candidate): entry for entry in self._entries}
            changed = set_review_entries_selected(entry_map, selected_node_ids, selected)
        if not changed:
            return False
        if self._workflow._snapshot_store:
            self._workflow._snapshot_store.save_entries(self._entries)
        root_keys = [build_local_update_review_key(entry.candidate) for entry in self._entries]
        root_overrides = collect_review_entry_selected_overrides(list(self._entries), root_keys)
        dependency_overrides = {
            (root_key, build_dependency_review_key(item)): build_dependency_review_key(item)
            in entry.selected_dependency_keys
            for root_key, entry in zip(root_keys, self._entries, strict=False)
            for item in [
                *list(getattr(entry.dependency_plan, "items", []) or []),
                *list(getattr(entry.dependency_plan, "advisory_items", []) or []),
            ]
        }
        self._entries = tuple(
            self._workflow._prepare_local_entries(
                self._update_plan,
                root_selected_overrides=root_overrides,
                dependency_selected_overrides=dependency_overrides,
            )
        )
        return True

    def _apply_dependency_selection(self, selected_node_ids: set[str], selected: bool) -> bool:
        changed = False
        entry_map = {build_local_update_review_key(entry.candidate): entry for entry in self._entries}
        for root_key, entry in entry_map.items():
            advisory_items = list(getattr(entry.dependency_plan, "advisory_items", []) or [])
            if f"{root_key}::optional-dependencies" in selected_node_ids:
                for item in advisory_items:
                    dependency_key = build_dependency_review_key(item)
                    if (dependency_key in entry.selected_dependency_keys) != selected:
                        if selected:
                            entry.selected_dependency_keys.add(dependency_key)
                        else:
                            entry.selected_dependency_keys.discard(dependency_key)
                        changed = True
            dependency_items = [
                *((item, False) for item in list(getattr(entry.dependency_plan, "items", []) or [])),
                *((item, True) for item in advisory_items),
            ]
            dependency_items.sort(
                key=lambda value: (
                    str(getattr(value[0], "project_name", "") or "").casefold(),
                    str(getattr(value[0], "version_name", "") or "").casefold(),
                )
            )
            for index, (item, is_advisory) in enumerate(dependency_items):
                if not is_advisory or f"{root_key}::dependency::{index}" not in selected_node_ids:
                    continue
                dependency_key = build_dependency_review_key(item)
                if (dependency_key in entry.selected_dependency_keys) != selected:
                    if selected:
                        entry.selected_dependency_keys.add(dependency_key)
                    else:
                        entry.selected_dependency_keys.discard(dependency_key)
                    changed = True
        return changed

    def build_handoff(self) -> ReviewExecutionHandoff:
        """
        將已選取且可執行的更新項目轉為 handoff

        Returns:
            含更新與依賴步驟、context stamp 及提示文字的執行契約
        """
        entries = list(self._entries)
        actionable = [entry for entry in entries if entry.actionable]
        unselected = [entry for entry in entries if entry.runnable and not entry.selected]
        counts = count_local_update_review_groups(entries)
        steps: list[ReviewInstallStep] = []
        root_keys: list[str] = []
        dependency_count = 0
        for entry in actionable:
            root_key = build_local_update_review_key(entry.candidate)
            for item in get_selected_dependency_install_items(entry.dependency_plan, entry.selected_dependency_keys):
                steps.append(_dependency_step(item, root_key))
                dependency_count += 1
            candidate = entry.candidate
            local_mod = candidate.local_mod
            root_keys.append(root_key)
            steps.append(
                ReviewInstallStep(
                    kind="local_root",
                    root_key=root_key,
                    project_name=candidate.project_name,
                    version_name=candidate.target_version_name,
                    download_url=candidate.download_url,
                    filename=candidate.target_filename,
                    expected_hash=extract_primary_file_hash(candidate.target_version)
                    or extract_primary_file_hash(candidate.target_version, "sha256"),
                    provider=entry.provider,
                    local_file_path=str(getattr(local_mod, "file_path", "") or ""),
                    local_status=normalize_status_value(getattr(local_mod, "status", "enabled")) or "enabled",
                )
            )
        skipped = []
        if counts["retryable"]:
            skipped.append(LOCAL_UPDATE_SKIPPED_RETRYABLE_TEMPLATE.format(count=counts["retryable"]))
        if counts["unknown"]:
            skipped.append(LOCAL_UPDATE_SKIPPED_UNKNOWN_TEMPLATE.format(count=counts["unknown"]))
        if counts["blocked"]:
            skipped.append(LOCAL_UPDATE_SKIPPED_BLOCKED_TEMPLATE.format(count=counts["blocked"]))
        completion_notes = format_completion_notes(
            [
                *[message for entry in actionable for message in entry.warning_messages],
                *[
                    message
                    for entry in actionable
                    for message in list(getattr(getattr(entry.candidate, "report", None), "warnings", []) or [])
                ],
                *[message for entry in actionable for message in list(getattr(entry.candidate, "notes", []) or [])],
                *[
                    message
                    for entry in actionable
                    for message in list(getattr(entry.dependency_plan, "notes", []) or [])
                ],
            ]
        )
        return ReviewExecutionHandoff(
            mode="local_update",
            context_stamp=self._workflow.context_stamp,
            steps=tuple(steps),
            root_keys=tuple(root_keys),
            confirmation_prompt=build_local_update_execution_prompt(entries) or "",
            source_confirmation_prompt=build_non_official_source_confirmation_prompt(actionable, action_label="更新"),
            skipped_text="\n略過項目：\n- " + "\n- ".join(skipped) if skipped else "",
            completion_notes=completion_notes,
            unselected_count=len(unselected),
            dependency_count=dependency_count,
            duplicate_dependency_count=0,
        )


def _dependency_key(item: Any) -> tuple[str, str, str, str]:
    return (
        str(getattr(item, "project_id", "") or "").strip(),
        str(getattr(item, "version_id", "") or "").strip(),
        str(getattr(item, "download_url", "") or "").strip(),
        str(getattr(item, "filename", "") or "").strip(),
    )


def _collect_dependency_keys(entries: list[Any]) -> tuple[set[tuple[str, str, str, str]], int]:
    keys: set[tuple[str, str, str, str]] = set()
    duplicate_count = 0
    for entry in entries:
        for item in get_selected_dependency_install_items(entry.dependency_plan, entry.selected_dependency_keys):
            key = _dependency_key(item)
            if key in keys:
                duplicate_count += 1
            else:
                keys.add(key)
    return (keys, duplicate_count)


__all__ = ["LocalReviewSession", "ModReviewWorkflow", "OnlineReviewSession"]
