"""Mod Review workflow 的單一外部 seam"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from src.core import (
    analyze_mod_version_compatibility,
    build_required_dependency_install_plan,
    resolve_modrinth_project_names,
)
from src.models import LocalModUpdatePlan, LocalUpdateReviewEntry, PendingInstallReviewEntry, PendingOnlineInstall
from src.ui import (
    LocalReviewSnapshotStore,
    ReviewExecutionHandoff,
    ReviewFormattingMixin,
    ReviewGroupingMixin,
    ReviewInstallStep,
    ReviewRootView,
    ReviewTaskView,
    ReviewViewSnapshot,
    append_enabled_dependency_simulations,
    build_dependency_review_key,
    build_installed_mod_simulation_item,
    build_local_update_execution_prompt,
    build_local_update_review_key,
    build_local_update_review_subtitle,
    build_non_official_source_confirmation_prompt,
    build_online_install_execution_prompt,
    build_online_install_review_subtitle,
    build_pending_install_review_key,
    build_review_context_stamp,
    build_server_install_blocking_reason,
    build_server_install_warning_line,
    collect_non_official_source_warning_messages,
    collect_review_entry_enabled_overrides,
    count_enabled_runnable_entries,
    count_local_update_review_groups,
    count_online_install_review_groups,
    dedupe_review_messages,
    format_completion_notes,
    format_local_update_review_text,
    format_pending_install_review_text,
    format_review_overview_text,
    get_enabled_dependency_install_items,
    get_review_group_specs,
    normalize_status_value,
    resolve_local_update_review_project_page_url,
    resolve_pending_install_review_project_page_url,
    set_review_entries_enabled,
)
from src.utils import (
    LOCAL_UPDATE_SKIPPED_BLOCKED_TEMPLATE,
    LOCAL_UPDATE_SKIPPED_RETRYABLE_TEMPLATE,
    LOCAL_UPDATE_SKIPPED_UNKNOWN_TEMPLATE,
    extract_primary_file_hash,
)


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


class ModReviewWorkflow:
    """建立 Review session、view snapshot 與 immutable execution handoff"""

    def __init__(
        self,
        *,
        server: Any,
        installed_mods: list[Any],
        telemetry: dict[str, int] | None = None,
        snapshot_store: LocalReviewSnapshotStore | None = None,
    ) -> None:
        self.context_stamp = build_review_context_stamp(server, installed_mods)
        self._server = server
        self._installed_mods = deepcopy(installed_mods)
        self._telemetry = (
            telemetry if telemetry is not None else {"checked": 0, "migrated": 0, "replayed": 0, "fallback_rebuild": 0}
        )
        self._snapshot_store = snapshot_store
        self._presentation = _ReviewPresentation(self._telemetry)

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
            dependency_project_ids = {
                str(dependency.get("project_id", "") or "").strip()
                for dependency in getattr(pending.version, "dependencies", []) or []
                if isinstance(dependency, dict) and str(dependency.get("project_id", "") or "").strip()
            }
            dependency_names = resolve_modrinth_project_names(dependency_project_ids)
            report = analyze_mod_version_compatibility(
                pending.version,
                project_id=pending.project_id,
                project_name=pending.project_name,
                minecraft_version=minecraft_version,
                loader=loader_type,
                loader_version=loader_version,
                installed_mods=simulated_installed_mods,
                dependency_names=dependency_names,
            )
            dependency_plan = build_required_dependency_install_plan(
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
                enabled=not blocking_reasons,
                provider=str(getattr(pending.version, "provider", "modrinth") or "modrinth"),
                version_type=str(getattr(pending.version, "version_type", "") or ""),
                date_published=str(getattr(pending.version, "date_published", "") or ""),
                changelog=str(getattr(pending.version, "changelog", "") or ""),
            )
            entry.warning_messages = dedupe_review_messages(
                [*warnings, *collect_non_official_source_warning_messages(entry, enabled_only=True)]
            )
            entries.append(entry)
            if entry.actionable:
                append_enabled_dependency_simulations(
                    simulated_installed_mods,
                    dependency_plan,
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
        root_enabled_overrides: dict[str, bool] | None = None,
        advisory_enabled_overrides: dict[tuple[str, tuple[str, str]], bool] | None = None,
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
            cached_root_enabled: bool | None = None
            if getattr(candidate, "update_available", False) and target_version is not None:
                cached_plan, cached_root_enabled = (
                    self._snapshot_store.load(candidate) if self._snapshot_store else (None, None)
                )
                dependency_plan = cached_plan or build_required_dependency_install_plan(
                    target_version,
                    minecraft_version=minecraft_version,
                    loader=loader_type,
                    loader_version=loader_version,
                    installed_mods=simulated_installed_mods,
                    root_project_id=candidate.project_id,
                    root_project_name=candidate.project_name,
                )
                if cached_plan is None and self._snapshot_store:
                    self._snapshot_store.save(
                        candidate,
                        dependency_plan,
                        root_enabled=bool(getattr(candidate, "actionable", False)) and not blocking_reasons,
                    )
                for item in list(getattr(dependency_plan, "advisory_items", []) or []):
                    override_key = (root_key, build_dependency_review_key(item))
                    if advisory_enabled_overrides and override_key in advisory_enabled_overrides:
                        item.enabled = advisory_enabled_overrides[override_key]
                blocking_reasons.extend(list(getattr(dependency_plan, "unresolved_required", []) or []))
            default_enabled = bool(getattr(candidate, "actionable", False)) and not blocking_reasons
            if not blocking_reasons and root_enabled_overrides is None and cached_root_enabled is not None:
                default_enabled = cached_root_enabled
            enabled = (
                root_enabled_overrides.get(root_key, default_enabled) if root_enabled_overrides else default_enabled
            )
            entry = LocalUpdateReviewEntry(
                candidate=candidate,
                dependency_plan=dependency_plan,
                blocking_reasons=blocking_reasons,
                enabled=enabled,
                provider=str(getattr(target_version, "provider", "modrinth") or "modrinth")
                if target_version
                else "modrinth",
                version_type=str(getattr(target_version, "version_type", "") or "") if target_version else "",
                date_published=str(getattr(target_version, "date_published", "") or "") if target_version else "",
                changelog=str(getattr(target_version, "changelog", "") or "") if target_version else "",
            )
            entry.warning_messages = collect_non_official_source_warning_messages(entry, enabled_only=True)
            entries.append(entry)
            if warnings:
                candidate.notes = dedupe_review_messages([*warnings, *list(getattr(candidate, "notes", []) or [])])
            if entry.actionable:
                append_enabled_dependency_simulations(
                    simulated_installed_mods,
                    dependency_plan,
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
            subtitle=build_online_install_review_subtitle(
                actionable_count,
                counts.get("blocked", 0),
                advisory_count=counts.get("advisory", 0),
                migrated_snapshot_count=self._workflow._telemetry.get("migrated", 0),
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
            enabled_count=actionable_count,
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
            for item in get_enabled_dependency_install_items(entry.dependency_plan):
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
        if counts.get("disabled", 0):
            skipped.append(f"已停用 {counts['disabled']} 項")
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
            disabled_count=counts.get("disabled", 0),
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
        enabled_count = count_enabled_runnable_entries(entries)
        notes = presentation._collect_local_update_global_notes(self._update_plan, entries)
        return ReviewViewSnapshot(
            mode="local_update",
            subtitle=build_local_update_review_subtitle(
                self._scope_text,
                enabled_count,
                counts["blocked"],
                advisory_count=counts["advisory"],
                retryable_count=counts["retryable"],
                unknown_count=counts["unknown"],
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
            enabled_count=enabled_count,
            actionable_count=sum(entry.actionable for entry in entries),
            blocked_count=counts["blocked"],
        )

    def apply_selection(self, selected_node_ids: set[str], enabled: bool) -> bool:
        """
        套用 root 或可選依賴節點的啟用狀態

        Args:
            selected_node_ids: 使用者選取的任務樹節點 ID
            enabled: 要套用的新啟用狀態

        Returns:
            狀態有變更並完成重新規劃時為 True
        """
        if not selected_node_ids:
            return False
        changed = self._apply_advisory_selection(selected_node_ids, enabled)
        if not changed:
            entry_map = {build_local_update_review_key(entry.candidate): entry for entry in self._entries}
            changed = set_review_entries_enabled(entry_map, selected_node_ids, enabled)
        if not changed:
            return False
        if self._workflow._snapshot_store:
            self._workflow._snapshot_store.save_entries(self._entries)
        root_keys = [build_local_update_review_key(entry.candidate) for entry in self._entries]
        root_overrides = collect_review_entry_enabled_overrides(list(self._entries), root_keys)
        advisory_overrides = {
            (root_key, build_dependency_review_key(item)): bool(getattr(item, "enabled", False))
            for root_key, entry in zip(root_keys, self._entries, strict=False)
            for item in list(getattr(entry.dependency_plan, "advisory_items", []) or [])
        }
        self._entries = tuple(
            self._workflow._prepare_local_entries(
                self._update_plan,
                root_enabled_overrides=root_overrides,
                advisory_enabled_overrides=advisory_overrides,
            )
        )
        return True

    def _apply_advisory_selection(self, selected_node_ids: set[str], enabled: bool) -> bool:
        changed = False
        entry_map = {build_local_update_review_key(entry.candidate): entry for entry in self._entries}
        for root_key, entry in entry_map.items():
            advisory_items = list(getattr(entry.dependency_plan, "advisory_items", []) or [])
            if f"{root_key}::optional-dependencies" in selected_node_ids:
                for item in advisory_items:
                    if bool(getattr(item, "enabled", False)) != enabled:
                        item.enabled = enabled
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
                if bool(getattr(item, "enabled", False)) != enabled:
                    item.enabled = enabled
                    changed = True
        return changed

    def build_handoff(self) -> ReviewExecutionHandoff:
        """
        將已啟用且可執行的更新項目轉為 handoff

        Returns:
            含更新與依賴步驟、context stamp 及提示文字的執行契約
        """
        entries = list(self._entries)
        actionable = [entry for entry in entries if entry.actionable]
        disabled = [entry for entry in entries if entry.runnable and not entry.enabled]
        counts = count_local_update_review_groups(entries)
        steps: list[ReviewInstallStep] = []
        root_keys: list[str] = []
        dependency_count = 0
        for entry in actionable:
            root_key = build_local_update_review_key(entry.candidate)
            for item in get_enabled_dependency_install_items(entry.dependency_plan):
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
            disabled_count=len(disabled),
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
        for item in get_enabled_dependency_install_items(entry.dependency_plan):
            key = _dependency_key(item)
            if key in keys:
                duplicate_count += 1
            else:
                keys.add(key)
    return (keys, duplicate_count)


__all__ = ["LocalReviewSession", "ModReviewWorkflow", "OnlineReviewSession"]
