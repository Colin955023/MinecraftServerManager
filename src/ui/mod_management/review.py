"""安裝與更新 review 流程。"""

from __future__ import annotations

import contextlib
import re
import tkinter.ttk as ttk
import traceback
from collections.abc import Callable, Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import customtkinter as ctk

from ...utils import (
    LOCAL_UPDATE_GROUP_DETAIL_RETRYABLE,
    LOCAL_UPDATE_PROMPT_ADVISORY_LINE_TEMPLATE,
    LOCAL_UPDATE_PROMPT_BLOCKED_LINE_TEMPLATE,
    LOCAL_UPDATE_PROMPT_RETRYABLE_LINE_TEMPLATE,
    LOCAL_UPDATE_PROMPT_UNKNOWN_LINE_TEMPLATE,
    LOCAL_UPDATE_REVIEW_PRECHECK_NOTE,
    METADATA_SOURCE_LABELS,
    METADATA_SOURCE_SHORT_LABELS,
    METADATA_SOURCE_STALE_PROVIDER,
    METADATA_SOURCE_UNRESOLVED,
    ONLINE_INSTALL_PROMPT_ADVISORY_LINE_TEMPLATE,
    ONLINE_INSTALL_PROMPT_BLOCKED_LINE_TEMPLATE,
    ONLINE_REVIEW_PRECHECK_NOTE,
    PROVIDER_LIFECYCLE_STALE,
    RECOMMENDATION_CONFIDENCE_ADVISORY,
    RECOMMENDATION_CONFIDENCE_LABELS,
    RECOMMENDATION_CONFIDENCE_RETRYABLE,
    RECOMMENDATION_SOURCE_LABELS,
    RECOMMENDATION_SOURCE_METADATA_UNRESOLVED,
    RECOMMENDATION_SOURCE_SHORT_LABELS,
    RECOMMENDATION_SOURCE_STALE_METADATA,
    Colors,
    FontSize,
    ProviderMetadataRecord,
    Sizes,
    Spacing,
    UIUtils,
    apply_provider_metadata,
    build_non_official_source_warning_message,
    cache_provider_metadata_record,
    deserialize_online_dependency_install_plan,
    ensure_local_mod_provider_record,
    get_non_official_download_host,
    migrate_online_dependency_install_plan_payload,
    register_provider_revalidation_success,
    serialize_online_dependency_install_plan,
    validate_online_dependency_install_plan_payload,
)
from .. import (
    DialogUtils,
    FontManager,
    LocalModUpdatePlan,
    ModManagementRuntimeBase,
    TaskUtils,
    TreeUtils,
    build_local_mod_update_plan,
)
from .constants import MODRINTH_PROJECT_PAGE_BASE_URL, logger
from .install_review_dialog_builder import InstallReviewDialogBuilder
from .models import (
    LocalUpdateReviewEntry,
    PendingInstallReviewEntry,
    ReviewTaskNode,
)


class ModManagementReviewMixin(ModManagementRuntimeBase):
    """整理線上安裝與本地更新的 review / 相依分析流程。"""

    def _get_install_review_dialog_builder(self) -> InstallReviewDialogBuilder:
        """取得 review 對話框 builder；支援 __new__ 建立的測試物件。"""
        builder = getattr(self, "install_review_dialog_builder", None)
        if builder is None:
            builder = InstallReviewDialogBuilder(self)
            self.install_review_dialog_builder = builder
        return builder

    @staticmethod
    def _get_online_version_status_text(report: Any | None) -> str:
        """將版本分析結果轉成簡短狀態，供列表快速判讀。"""
        if report is None:
            return "未分析"
        if not getattr(report, "compatible", True):
            return "不相容"
        if list(getattr(report, "missing_required_dependencies", []) or []):
            return "可安裝，含依賴"
        if list(getattr(report, "incompatible_installed", []) or []) or list(
            getattr(report, "installed_version_mismatches", []) or []
        ):
            return "可安裝，需注意"
        if list(getattr(report, "warnings", []) or []):
            return "可安裝，需注意"
        return "可安裝"

    @staticmethod
    def _normalize_online_version_type(value: Any) -> str:
        """正規化版本類型，避免不同 provider 字串差異造成排序飄移。"""
        return str(value or "").strip().lower()

    @classmethod
    def _get_online_version_type_rank(cls, version_type: Any) -> int:
        """回傳版本穩定度排名（數字越小越優先）。"""
        normalized = cls._normalize_online_version_type(version_type)
        if normalized in {"release", "stable"}:
            return 0
        if normalized in {"beta", "pre", "preview", "rc"}:
            return 1
        if normalized in {"alpha", "snapshot"}:
            return 2
        return 3

    @staticmethod
    def _get_online_version_compatibility_rank(report: Any | None) -> int:
        """相容性排名（數字越小越優先）。"""
        if report is None:
            return 1
        return 0 if bool(getattr(report, "compatible", True)) else 2

    @classmethod
    def _sort_online_versions_for_server(
        cls, versions: list[Any], version_reports: list[Any] | None
    ) -> tuple[list[Any], list[Any] | None]:
        """伺服器安裝場景排序：相容性 > 穩定度 > 發布時間。"""
        if not versions:
            return (versions, version_reports)
        indexed_reports: list[Any | None]
        if version_reports is None:
            indexed_reports = [None] * len(versions)
        else:
            indexed_reports = [
                version_reports[index] if index < len(version_reports) else None for index in range(len(versions))
            ]
        merged = list(zip(versions, indexed_reports, strict=False))

        def _published_sort_value(version: Any) -> tuple[int, str]:
            published = str(getattr(version, "date_published", "") or "")
            return (0 if published else 1, published)

        merged.sort(
            key=lambda item: (
                cls._get_online_version_compatibility_rank(item[1]),
                cls._get_online_version_type_rank(getattr(item[0], "version_type", "")),
                _published_sort_value(item[0]),
            )
        )
        grouped: dict[tuple[int, int], list[tuple[Any, Any | None]]] = {}
        for row in merged:
            group_key = (
                cls._get_online_version_compatibility_rank(row[1]),
                cls._get_online_version_type_rank(getattr(row[0], "version_type", "")),
            )
            grouped.setdefault(group_key, []).append(row)
        merged = []
        for group_key in sorted(grouped):
            group_rows = grouped[group_key]
            group_rows.sort(key=lambda row: str(getattr(row[0], "date_published", "") or ""), reverse=True)
            merged.extend(group_rows)
        sorted_versions = [item[0] for item in merged]
        if version_reports is None:
            return (sorted_versions, None)
        sorted_reports = [item[1] for item in merged]
        return (sorted_versions, sorted_reports)

    def _format_online_version_report(self, version: Any, report: Any | None) -> str:
        """格式化版本相容性與依賴分析結果。"""
        lines = [
            f"版本：{getattr(version, 'display_name', '未知版本')}",
            f"來源：{self._format_review_provider_label(getattr(version, 'provider', 'modrinth'))}",
            f"Minecraft：{', '.join(getattr(version, 'game_versions', []) or []) or '-'}",
            f"Loader：{', '.join(getattr(version, 'loaders', []) or []) or '-'}",
        ]
        version_type = str(getattr(version, "version_type", "") or "").strip()
        if version_type:
            lines.append(f"版本類型：{version_type}")
        published_text = self._format_review_published_at(getattr(version, "date_published", ""))
        if published_text:
            lines.append(f"發布時間：{published_text}")
        changelog_text = self._summarize_review_changelog(getattr(version, "changelog", ""))
        if changelog_text:
            lines.append("")
            lines.append("更新內容：")
            lines.append(changelog_text)
        if report is None:
            return "\n".join(lines)
        lines.insert(0, f"相容性結果：{('可安裝' if getattr(report, 'compatible', True) else '不符合目前伺服器條件')}")
        hard_errors = list(getattr(report, "hard_errors", []) or [])
        if hard_errors:
            lines.append("")
            lines.append("阻擋原因：")
            lines.extend(f"- {item}" for item in self._summarize_review_messages(hard_errors, max_items=3))
        missing_required = list(getattr(report, "missing_required_dependencies", []) or [])
        if missing_required:
            lines.append("")
            lines.append("需要安裝的必要依賴：")
            lines.extend(f"- {item}" for item in self._summarize_review_messages(missing_required, max_items=3))
        incompatible_installed = list(getattr(report, "incompatible_installed", []) or [])
        if incompatible_installed:
            lines.append("")
            lines.append("已安裝但不相容的模組：")
            lines.extend(f"- {item}" for item in self._summarize_review_messages(incompatible_installed, max_items=3))
        installed_version_mismatches = list(getattr(report, "installed_version_mismatches", []) or [])
        if installed_version_mismatches:
            lines.append("")
            lines.append("已安裝但版本不符的依賴：")
            lines.extend(
                f"- {item}" for item in self._summarize_review_messages(installed_version_mismatches, max_items=3)
            )
        optional_dependencies = list(getattr(report, "optional_dependencies", []) or [])
        if optional_dependencies:
            lines.append("")
            lines.append("可選依賴：")
            lines.extend(f"- {item}" for item in self._summarize_review_messages(optional_dependencies, max_items=2))
        already_installed = list(getattr(report, "already_installed", []) or [])
        if already_installed:
            lines.append("")
            lines.append("目前已安裝：")
            lines.extend(f"- {item}" for item in self._summarize_review_messages(already_installed, max_items=2))
        notes = list(getattr(report, "notes", []) or [])
        if notes:
            lines.append("")
            lines.append("補充說明：")
            lines.extend(f"- {item}" for item in self._summarize_review_messages(notes, max_items=2))
        return "\n".join(lines)

    def _build_online_install_warning_message(self, report: Any | None) -> str:
        """整理需要使用者確認的安裝前提醒。"""
        if report is None:
            return ""
        sections: list[str] = []
        already_installed = list(getattr(report, "already_installed", []) or [])
        if already_installed:
            sections.append("已安裝相同模組：\n" + "\n".join(f"- {item}" for item in already_installed))
        missing_required = list(getattr(report, "missing_required_dependencies", []) or [])
        if missing_required:
            sections.append("將自動安裝的必要依賴：\n" + "\n".join(f"- {item}" for item in missing_required))
        incompatible_installed = list(getattr(report, "incompatible_installed", []) or [])
        if incompatible_installed:
            sections.append("已安裝的不相容模組：\n" + "\n".join(f"- {item}" for item in incompatible_installed))
        installed_version_mismatches = list(getattr(report, "installed_version_mismatches", []) or [])
        if installed_version_mismatches:
            sections.append(
                "已安裝但版本不符的依賴：\n" + "\n".join(f"- {item}" for item in installed_version_mismatches)
            )
        return "\n\n".join(sections)

    @staticmethod
    def _format_review_provider_label(provider: str | None) -> str:
        normalized = str(provider or "").strip().lower()
        if normalized == "modrinth":
            return "Modrinth"
        return str(provider or "未知來源").strip() or "未知來源"

    @classmethod
    def _iter_review_download_source_records(
        cls,
        review_entry: Any,
        *,
        enabled_only: bool,
    ) -> list[tuple[str, str, str]]:
        records: list[tuple[str, str, str]] = []
        if isinstance(review_entry, PendingInstallReviewEntry):
            pending = getattr(review_entry, "pending", None)
            version = getattr(pending, "version", None)
            primary_file = getattr(version, "primary_file", None) or {}
            version_name = str(
                getattr(version, "display_name", "") or getattr(version, "version_number", "") or ""
            ).strip()
            root_label = str(getattr(pending, "project_name", "") or "未知模組").strip() or "未知模組"
            if version_name:
                root_label = f"{root_label} ({version_name})"
            records.append((root_label, str(primary_file.get("url", "") or "").strip(), review_entry.provider))
        elif isinstance(review_entry, LocalUpdateReviewEntry):
            candidate = getattr(review_entry, "candidate", None)
            target_version_name = str(getattr(candidate, "target_version_name", "") or "").strip()
            root_label = str(getattr(candidate, "project_name", "") or "未知模組").strip() or "未知模組"
            if target_version_name:
                root_label = f"{root_label} ({target_version_name})"
            records.append(
                (root_label, str(getattr(candidate, "download_url", "") or "").strip(), review_entry.provider)
            )
        dependency_plan = getattr(review_entry, "dependency_plan", None)
        dependency_items = (
            cls._get_enabled_dependency_install_items(dependency_plan)
            if enabled_only
            else cls._get_sorted_dependency_review_items(dependency_plan)
        )
        for dependency_item in dependency_items:
            provider = str(getattr(dependency_item, "provider", "") or review_entry.provider or "modrinth").strip()
            label = str(getattr(dependency_item, "project_name", "") or "未知依賴").strip() or "未知依賴"
            records.append(
                (f"{label}（依賴）", str(getattr(dependency_item, "download_url", "") or "").strip(), provider)
            )
        return records

    @classmethod
    def _collect_non_official_source_warning_messages(
        cls,
        review_entry: Any,
        *,
        enabled_only: bool,
    ) -> list[str]:
        warnings: list[str] = []
        for item_label, download_url, provider in cls._iter_review_download_source_records(
            review_entry,
            enabled_only=enabled_only,
        ):
            warning_message = build_non_official_source_warning_message(
                item_label,
                download_url,
                provider,
                provider_label=cls._format_review_provider_label(provider),
            )
            if warning_message:
                warnings.append(warning_message)
        return cls._dedupe_review_messages(warnings)

    @classmethod
    def _build_non_official_source_confirmation_prompt(
        cls,
        review_entries: list[Any],
        *,
        action_label: str,
    ) -> str:
        lines: list[str] = []
        for review_entry in review_entries:
            for item_label, download_url, provider in cls._iter_review_download_source_records(
                review_entry,
                enabled_only=True,
            ):
                host = get_non_official_download_host(download_url, provider)
                if not host:
                    continue
                provider_label = cls._format_review_provider_label(provider)
                lines.append(f"- {item_label}：{host}（非 {provider_label} 官方網域）")
        deduped_lines = cls._dedupe_review_messages(lines)
        if not deduped_lines:
            return ""
        return (
            f"本次{action_label}包含非官方下載來源，系統已同步記錄風險日誌：\n"
            + "\n".join(deduped_lines)
            + "\n\n這些檔案不會從官方 provider 網域下載，請確認你信任這些來源。\n\n是否仍要繼續？"
        )

    @staticmethod
    def _format_metadata_source_label(source: str | None) -> str:
        normalized = str(source or "").strip().lower()
        return METADATA_SOURCE_LABELS.get(normalized, "未知")

    @staticmethod
    def _format_metadata_source_short_label(source: str | None) -> str:
        normalized = str(source or "").strip().lower()
        return METADATA_SOURCE_SHORT_LABELS.get(normalized, "未知")

    @staticmethod
    def _format_recommendation_source_label(source: str | None) -> str:
        normalized = str(source or "").strip().lower()
        return RECOMMENDATION_SOURCE_LABELS.get(normalized, "未知")

    @staticmethod
    def _format_recommendation_source_short_label(source: str | None) -> str:
        normalized = str(source or "").strip().lower()
        return RECOMMENDATION_SOURCE_SHORT_LABELS.get(normalized, "未知")

    @staticmethod
    def _format_recommendation_confidence_label(confidence: str | None) -> str:
        normalized = str(confidence or "").strip().lower()
        return RECOMMENDATION_CONFIDENCE_LABELS.get(normalized, "未知")

    @staticmethod
    def _build_modrinth_project_page_url(identifier: str | None) -> str:
        normalized = str(identifier or "").strip().strip("/")
        if not normalized:
            return ""
        return f"{MODRINTH_PROJECT_PAGE_BASE_URL}/{normalized}"

    @classmethod
    def _resolve_project_page_url_from_candidates(
        cls, *, url_candidates: Iterable[Any] = (), identifier_candidates: Iterable[Any] = ()
    ) -> str:
        for raw_url in url_candidates:
            clean_url = str(raw_url or "").strip()
            if clean_url:
                return clean_url
        for raw_identifier in identifier_candidates:
            project_page_url = cls._build_modrinth_project_page_url(str(raw_identifier or "").strip())
            if project_page_url:
                return project_page_url
        return ""

    @classmethod
    def _resolve_online_mod_project_page_url(cls, mod: Any) -> str:
        return cls._resolve_project_page_url_from_candidates(
            url_candidates=(getattr(mod, "homepage_url", ""), getattr(mod, "url", "")),
            identifier_candidates=(getattr(mod, "slug", ""), getattr(mod, "project_id", "")),
        )

    def _make_step_progress_callback(self, step_index: int, total_steps: int):
        """回傳一個 progress callback；將進度換算成整體步驟的 fraction。"""

        def _callback(downloaded: int, total: int) -> None:
            fraction = downloaded / total if total > 0 else 0.0
            self.update_progress_safe((step_index + fraction) / max(1, total_steps))

        return _callback

    @classmethod
    def _resolve_pending_install_review_project_page_url(cls, review_entry: PendingInstallReviewEntry) -> str:
        pending = getattr(review_entry, "pending", None)
        if pending is None:
            return ""
        return cls._resolve_project_page_url_from_candidates(
            url_candidates=(getattr(pending, "homepage_url", ""), getattr(pending, "source_url", "")),
            identifier_candidates=(getattr(pending, "project_id", ""),),
        )

    @classmethod
    def _resolve_local_update_review_project_page_url(cls, review_entry: LocalUpdateReviewEntry) -> str:
        candidate = getattr(review_entry, "candidate", None)
        if candidate is None:
            return ""
        local_mod = getattr(candidate, "local_mod", None)
        return cls._resolve_project_page_url_from_candidates(
            identifier_candidates=(
                getattr(local_mod, "platform_slug", ""),
                getattr(candidate, "project_id", ""),
                getattr(local_mod, "platform_id", ""),
            )
        )

    @staticmethod
    def _format_review_published_at(value: str | None) -> str:
        raw_value = str(value or "").strip()
        if not raw_value:
            return ""
        return raw_value.replace("T", " ").replace("Z", "")[:16]

    def _open_project_page(self, url: str, parent: Any, *, title: str = "沒有可開啟的專案頁面") -> None:
        clean_url = str(url or "").strip()
        if not clean_url:
            UIUtils.show_warning(title, "目前無法判定這個項目的專案頁面。", parent)
            return
        UIUtils.open_external(clean_url)

    @staticmethod
    def _create_review_summary_box(parent: Any, *, height: int) -> ctk.CTkTextbox:
        return InstallReviewDialogBuilder.create_review_summary_box(parent, height=height)

    @classmethod
    def _bind_vertical_mousewheel(cls, widget: Any, *, scroll_callback: Callable[..., Any]) -> None:
        try:
            widget.bind(
                "<MouseWheel>",
                lambda event: cls._scroll_widget_vertical(event, scroll_callback=scroll_callback),
                add="+",
            )
        except Exception:
            return

    @classmethod
    def _scroll_widget_vertical(cls, event: Any, *, scroll_callback: Callable[..., Any]) -> str | None:
        units = UIUtils.get_mousewheel_units(int(getattr(event, "delta", 0)))
        if units == 0:
            return None
        scroll_callback(units, "units")
        return "break"

    @staticmethod
    def _select_tree_item_for_context_menu(tree: Any, event: Any) -> str:
        row_id = str(tree.identify_row(int(getattr(event, "y", 0))) or "").strip()
        if not row_id:
            return ""
        selection = set(tree.selection())
        if row_id not in selection:
            tree.selection_set(row_id)
        tree.focus(row_id)
        tree.see(row_id)
        return row_id

    @staticmethod
    def _build_review_subtitle(
        *,
        prefix_segments: list[str],
        count_segments: Iterable[tuple[int, str]],
        blocked_count: int,
        blocked_label: str,
        migrated_snapshot_count: int = 0,
        migrated_snapshot_label: str = "快照遷移",
    ) -> str:
        segments = list(prefix_segments)
        for count, label in count_segments:
            if count:
                segments.append(f"{label} {count} 項")
        if migrated_snapshot_count:
            segments.append(f"{migrated_snapshot_label} {migrated_snapshot_count} 項")
        if blocked_count:
            segments.append(f"{blocked_label} {blocked_count} 項")
        return "｜".join(segments)

    @staticmethod
    def _build_online_install_review_subtitle(
        actionable_count: int, blocked_count: int, *, advisory_count: int = 0, migrated_snapshot_count: int = 0
    ) -> str:
        return ModManagementReviewMixin._build_review_subtitle(
            prefix_segments=["已重驗證可安裝性與必要依賴", f"可安裝 {actionable_count} 項"],
            count_segments=((advisory_count, "建議確認"),),
            blocked_count=blocked_count,
            blocked_label="待處理",
            migrated_snapshot_count=migrated_snapshot_count,
            migrated_snapshot_label="快照自動遷移",
        )

    @staticmethod
    def _build_local_update_review_subtitle(
        scope_text: str,
        enabled_count: int,
        blocked_count: int,
        *,
        advisory_count: int = 0,
        retryable_count: int = 0,
        unknown_count: int = 0,
        migrated_snapshot_count: int = 0,
    ) -> str:
        return ModManagementReviewMixin._build_review_subtitle(
            prefix_segments=[f"範圍：{scope_text}", f"可執行更新 {enabled_count} 項"],
            count_segments=(
                (advisory_count, "建議確認"),
                (retryable_count, "可重試"),
                (unknown_count, "待識別"),
            ),
            blocked_count=blocked_count,
            blocked_label="阻擋",
            migrated_snapshot_count=migrated_snapshot_count,
        )

    def _format_local_update_source_text(self, review_entry: LocalUpdateReviewEntry) -> str:
        provider_label = self._format_review_provider_label(review_entry.provider)
        metadata_source = str(getattr(review_entry.candidate, "metadata_source", "") or "").strip()
        recommendation_source = str(getattr(review_entry.candidate, "recommendation_source", "") or "").strip()
        segments = [provider_label]
        if metadata_source:
            segments.append(self._format_metadata_source_short_label(metadata_source))
        if recommendation_source:
            segments.append(self._format_recommendation_source_short_label(recommendation_source))
        if not segments:
            return provider_label
        return "｜".join(segments)

    def _build_local_update_metadata_detail(self, review_entry: LocalUpdateReviewEntry) -> str:
        candidate = review_entry.candidate
        lines = [f"Metadata 來源：{self._format_metadata_source_label(getattr(candidate, 'metadata_source', ''))}"]
        recommendation_source = str(getattr(candidate, "recommendation_source", "") or "").strip()
        recommendation_confidence = str(getattr(candidate, "recommendation_confidence", "") or "").strip()
        if recommendation_source:
            lines.append(f"更新建議來源：{self._format_recommendation_source_label(recommendation_source)}")
        if recommendation_confidence:
            lines.append(f"更新建議可信度：{self._format_recommendation_confidence_label(recommendation_confidence)}")
        metadata_note = str(getattr(candidate, "metadata_note", "") or "").strip()
        if metadata_note:
            lines.append(f"Metadata 狀態：{metadata_note}")
        return "\n".join(lines)

    @staticmethod
    def _summarize_review_changelog(value: str | None, max_length: int = 420) -> str:
        raw_value = str(value or "").strip()
        if not raw_value:
            return ""
        normalized = re.sub("\\s+", " ", raw_value).strip()
        if len(normalized) <= max_length:
            return normalized
        return normalized[: max(0, max_length - 3)].rstrip() + "..."

    @staticmethod
    def _collect_selected_root_keys(tree: ttk.Treeview) -> set[str]:
        return ModManagementReviewMixin._collect_selected_root_keys_from(tree, None)

    @staticmethod
    def _collect_selected_root_keys_from(tree: ttk.Treeview, valid_keys: set[str] | None) -> set[str]:
        selected_root_keys: set[str] = set()
        for item_id in tree.selection():
            current_item = item_id
            matched_valid_key = False
            while current_item:
                if valid_keys is not None and current_item in valid_keys:
                    matched_valid_key = True
                    break
                parent_id = tree.parent(current_item)
                if not parent_id:
                    break
                current_item = parent_id
            if valid_keys is not None and (not matched_valid_key):
                continue
            selected_root_keys.add(current_item)
        return selected_root_keys

    @staticmethod
    def _get_selected_review_key(tree: ttk.Treeview, valid_keys: set[str]) -> str:
        selected_root_keys = ModManagementReviewMixin._collect_selected_root_keys_from(tree, valid_keys)
        if selected_root_keys:
            return next(iter(sorted(selected_root_keys)))
        return next(iter(sorted(valid_keys)), "")

    @staticmethod
    def _set_review_entries_enabled(entries: dict[str, Any], keys: set[str], enabled: bool) -> bool:
        changed = False
        for key in keys:
            entry = entries.get(key)
            if entry is None or bool(getattr(entry, "enabled", True)) == enabled:
                continue
            entry.enabled = enabled
            changed = True
        return changed

    @staticmethod
    def _build_dependency_review_key(dependency_item: Any) -> tuple[str, str]:
        return (
            str(getattr(dependency_item, "project_id", "") or "").strip(),
            str(
                getattr(dependency_item, "version_id", "") or getattr(dependency_item, "version_name", "") or ""
            ).strip(),
        )

    @staticmethod
    def _is_optional_dependency_item(dependency_item: Any) -> bool:
        marker = getattr(dependency_item, "is_optional", None)
        if marker is None:
            return True
        return bool(marker)

    @staticmethod
    def _collect_review_entry_enabled_overrides(entries: list[Any], root_keys: list[str]) -> dict[str, bool]:
        return {
            root_key: bool(getattr(entry, "enabled", False))
            for root_key, entry in zip(root_keys, entries, strict=False)
            if root_key
        }

    def _collect_review_advisory_enabled_overrides(
        self, entries: list[Any], root_keys: list[str]
    ) -> dict[tuple[str, tuple[str, str]], bool]:
        overrides: dict[tuple[str, tuple[str, str]], bool] = {}
        for root_key, entry in zip(root_keys, entries, strict=False):
            if not root_key:
                continue
            dependency_plan = getattr(entry, "dependency_plan", None)
            for dependency_item in list(getattr(dependency_plan, "advisory_items", []) or []):
                dependency_key = self._build_dependency_review_key(dependency_item)
                overrides[root_key, dependency_key] = bool(getattr(dependency_item, "enabled", False))
        return overrides

    def _apply_review_advisory_enabled_overrides(
        self,
        dependency_plan: Any,
        root_key: str,
        advisory_enabled_overrides: dict[tuple[str, tuple[str, str]], bool] | None,
    ) -> None:
        if not advisory_enabled_overrides:
            return
        for dependency_item in list(getattr(dependency_plan, "advisory_items", []) or []):
            dependency_key = self._build_dependency_review_key(dependency_item)
            override_key = (root_key, dependency_key)
            if override_key not in advisory_enabled_overrides:
                continue
            dependency_item.enabled = advisory_enabled_overrides[override_key]

    @staticmethod
    def _count_enabled_runnable_entries(entries: list[Any]) -> int:
        return sum(
            1 for entry in entries if bool(getattr(entry, "enabled", False)) and bool(getattr(entry, "runnable", False))
        )

    @staticmethod
    def _count_blocked_entries(entries: list[Any]) -> int:
        return sum(1 for entry in entries if not bool(getattr(entry, "runnable", False)))

    @staticmethod
    def _count_dependency_plan_items(dependency_plan: Any) -> tuple[int, int]:
        """回傳必要依賴數與可選依賴數。"""
        auto_install_count = len(list(getattr(dependency_plan, "items", []) or []))
        advisory_items = list(getattr(dependency_plan, "advisory_items", []) or [])
        optional_count = sum(
            1 for item in advisory_items if ModManagementReviewMixin._is_optional_dependency_item(item)
        )
        return (auto_install_count, optional_count)

    def _build_online_review_root_extra_segments(self, review_entry: PendingInstallReviewEntry) -> list[str]:
        auto_dependency_count, optional_dependency_count = self._count_dependency_plan_items(
            getattr(review_entry, "dependency_plan", None)
        )
        warning_count = len(self._dedupe_review_messages(list(getattr(review_entry, "warning_messages", []) or [])))
        blocking_count = len(self._dedupe_review_messages(list(getattr(review_entry, "blocking_reasons", []) or [])))
        segments: list[str] = []
        if auto_dependency_count:
            segments.append(f"依賴 {auto_dependency_count}")
        if optional_dependency_count:
            segments.append(f"可選 {optional_dependency_count}")
        if warning_count:
            segments.append(f"提醒 {warning_count}")
        if blocking_count:
            segments.append(f"阻擋 {blocking_count}")
        return segments

    @staticmethod
    def _build_review_root_status_text(
        review_entry: Any,
        *,
        group_key_getter: Callable[[Any], str],
        group_status_getter: Callable[[str], str],
        extra_segment_getter: Callable[[Any], list[str]] | None = None,
    ) -> str:
        segments = [group_status_getter(group_key_getter(review_entry))]
        if extra_segment_getter is not None:
            segments.extend(extra_segment_getter(review_entry))
        return "｜".join(segments)

    def _build_online_review_root_status_text(self, review_entry: PendingInstallReviewEntry) -> str:
        """建立線上安裝 review 根節點摘要，供 task tree 快速判讀。"""
        return self._build_review_root_status_text(
            review_entry,
            group_key_getter=self._get_online_install_review_group_key,
            group_status_getter=self._get_online_install_group_status_label,
            extra_segment_getter=self._build_online_review_root_extra_segments,
        )

    def _build_pending_install_summary_lines(self, review_entry: PendingInstallReviewEntry) -> list[str]:
        """建立待安裝 review 詳細文字頂部摘要。"""
        lines = [f"摘要：{self._build_online_review_root_status_text(review_entry)}"]
        dependency_plan = getattr(review_entry, "dependency_plan", None)
        auto_dependency_count, optional_dependency_count = self._count_dependency_plan_items(dependency_plan)
        if auto_dependency_count:
            lines.append(f"- 將自動補裝 {auto_dependency_count} 個必要依賴")
        if optional_dependency_count:
            enabled_optional = sum(
                1
                for item in list(getattr(dependency_plan, "advisory_items", []) or [])
                if self._is_optional_dependency_item(item) and bool(getattr(item, "enabled", False))
            )
            lines.append(f"- 可選依賴 {optional_dependency_count} 項（已選 {enabled_optional} 項）")
        if review_entry.blocking_reasons:
            lines.append(
                f"- 目前有 {len(self._dedupe_review_messages(review_entry.blocking_reasons))} 個阻擋原因需先處理"
            )
        elif review_entry.warning_messages:
            lines.append(f"- 目前有 {len(self._dedupe_review_messages(review_entry.warning_messages))} 個提醒需留意")
        return lines

    @staticmethod
    def _normalize_side_support(value: Any) -> str:
        return str(value or "").strip().lower()

    @classmethod
    def _is_client_side_supported_mod(cls, server_side: Any, client_side: Any) -> bool:
        normalized_server_side = cls._normalize_side_support(server_side)
        normalized_client_side = cls._normalize_side_support(client_side)
        server_supported = normalized_server_side in {"required", "optional"}
        client_supported = normalized_client_side in {"required", "optional"}
        return server_supported and client_supported

    @classmethod
    def _build_client_install_reminder_line(cls, server_side: Any, client_side: Any) -> str | None:
        if not cls._is_client_side_supported_mod(server_side, client_side):
            return None
        return "提醒：此模組同時支援 client 端，請提醒玩家端也安裝相同模組版本，以避免連線或功能不一致問題。"

    @classmethod
    def _build_server_install_blocking_reason(cls, server_side: Any) -> str | None:
        """伺服器安裝前檢查：若明確標示不支援 server 端，必須阻擋安裝。"""
        normalized_server_side = cls._normalize_side_support(server_side)
        if normalized_server_side == "unsupported":
            return "此模組標記為僅 client 端（server_side=unsupported），不可安裝到伺服器。"
        return None

    @classmethod
    def _build_server_install_warning_line(cls, server_side: Any) -> str | None:
        """server_side 未明確標示時給出提醒，但不阻擋安裝。"""
        normalized_server_side = cls._normalize_side_support(server_side)
        if normalized_server_side in {"", "unknown"}:
            return "提醒：此模組未明確標示 server 端支援，建議安裝前再次確認。"
        return None

    @staticmethod
    def _dedupe_review_messages(messages: list[str] | tuple[str, ...]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for message in messages:
            normalized = str(message or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    @staticmethod
    def _summarize_review_messages(messages: list[str] | tuple[str, ...], max_items: int = 3) -> list[str]:
        deduped = ModManagementReviewMixin._dedupe_review_messages(messages)
        if len(deduped) <= max_items:
            return deduped
        return [*deduped[:max_items], f"其餘 {len(deduped) - max_items} 項請於任務樹查看。"]

    @staticmethod
    def _summarize_review_note(value: str | None, max_length: int = 140) -> str:
        normalized = re.sub("\\s+", " ", str(value or "").strip())
        if len(normalized) <= max_length:
            return normalized
        return normalized[: max(0, max_length - 3)].rstrip() + "..."

    @staticmethod
    def _format_required_by_list(required_by: list[str]) -> str:
        deduped = ModManagementReviewMixin._dedupe_review_messages(required_by)
        if not deduped:
            return ""
        if len(deduped) <= 3:
            return "、".join(deduped)
        return f"{'、'.join(deduped[:3])} 等 {len(deduped)} 個項目"

    @staticmethod
    def _format_dependency_resolution_label(source: str | None, confidence: str | None) -> str:
        normalized_source = str(source or "").strip().lower()
        normalized_confidence = str(confidence or "").strip().lower()
        source_label = "project id 直連"
        if normalized_source == "version_detail":
            source_label = "版本詳情回補"
        elif normalized_source == "loader_override":
            source_label = "loader 覆寫"
        elif normalized_source == "version_id":
            source_label = "version id 線索"
        confidence_label = "高"
        if normalized_confidence == "fallback":
            confidence_label = "中"
        elif normalized_confidence in {"heuristic", "manual"}:
            confidence_label = "需確認"
        return f"{source_label}（{confidence_label}）"

    @staticmethod
    def _format_dependency_action_label(dependency_item: Any, is_advisory: bool, is_enabled: bool) -> str:
        if is_advisory and is_enabled:
            return "可選依賴，已啟用安裝"
        if is_advisory:
            return "可選依賴，預設略過"
        if bool(getattr(dependency_item, "maybe_installed", False)) and is_enabled:
            return "疑似已安裝，已改為安裝"
        if bool(getattr(dependency_item, "maybe_installed", False)):
            return "疑似已安裝，預設略過"
        status_note = str(getattr(dependency_item, "status_note", "") or "").strip()
        if status_note:
            return status_note
        return "將自動安裝"

    @staticmethod
    def _count_review_nodes(nodes: list[ReviewTaskNode], node_kind: str) -> int:
        return sum(1 for node in nodes if node.node_kind == node_kind)

    def _format_review_overview_text(
        self,
        entries: list[Any],
        nodes: list[ReviewTaskNode],
        *,
        action_label: str,
        global_notes: list[str] | None = None,
        deduped_dependency_count: int = 0,
    ) -> str:
        _ = global_notes
        root_count = len(entries)
        dependency_count = self._count_review_nodes(nodes, "dependency")
        issue_count = self._count_review_nodes(nodes, "issue")
        warning_count = self._count_review_nodes(nodes, "warning")
        enabled_count = self._count_enabled_runnable_entries(entries)
        disabled_count = sum(
            1 for entry in entries if getattr(entry, "runnable", False) and (not getattr(entry, "enabled", False))
        )
        segments = [f"Task graph：{root_count} 個根任務", f"目前將{action_label} {enabled_count} 個根項目"]
        if dependency_count:
            segments.append(f"{dependency_count} 個依賴")
        if issue_count:
            segments.append(f"{issue_count} 個待處理")
        if warning_count:
            segments.append(f"{warning_count} 個提醒")
        if deduped_dependency_count:
            segments.append(f"已合併 {deduped_dependency_count} 個重複依賴")
        if disabled_count:
            segments.append(f"另有 {disabled_count} 個已停用項目")
        notes = self._dedupe_review_messages(list(global_notes or []))
        if notes:
            segments.append("預檢：" + self._summarize_review_note(notes[0], max_length=40))
        return "｜".join(segments)

    def _record_dependency_snapshot_migration_telemetry(self, event: str) -> None:
        telemetry = getattr(self, "_dependency_snapshot_migration_totals", None)
        if not isinstance(telemetry, dict):
            telemetry = {"checked": 0, "migrated": 0, "replayed": 0, "fallback_rebuild": 0}
            self._dependency_snapshot_migration_totals = telemetry
        if event not in telemetry:
            return
        telemetry[event] += 1

    def _build_dependency_snapshot_migration_note(self) -> str:
        telemetry = getattr(self, "_dependency_snapshot_migration_totals", None)
        if not isinstance(telemetry, dict):
            return ""
        checked_count = telemetry.get("checked", 0)
        if checked_count <= 0:
            return ""
        migrated_count = telemetry.get("migrated", 0)
        replayed_count = telemetry.get("replayed", 0)
        fallback_rebuild_count = telemetry.get("fallback_rebuild", 0)
        return (
            f"依賴快照遷移觀測：檢查 {checked_count}、自動遷移 {migrated_count}、成功回放 {replayed_count}"
            + (f"、回放失敗改重建 {fallback_rebuild_count}" if fallback_rebuild_count else "")
            + "。"
        )

    def _collect_review_global_notes(
        self, *, base_notes: Iterable[str], review_entries: list[Any], extra_note_groups: Iterable[Iterable[str]] = ()
    ) -> list[str]:
        notes = list(base_notes)
        migration_note = self._build_dependency_snapshot_migration_note()
        if migration_note:
            notes.append(migration_note)
        for note_group in extra_note_groups:
            notes.extend(list(note_group or []))
        for entry in review_entries:
            notes.extend(list(getattr(getattr(entry, "dependency_plan", None), "notes", []) or []))
        return ModManagementReviewMixin._dedupe_review_messages(notes)

    def _collect_online_review_global_notes(self, review_entries: list[PendingInstallReviewEntry]) -> list[str]:
        return self._collect_review_global_notes(
            base_notes=[ONLINE_REVIEW_PRECHECK_NOTE],
            review_entries=review_entries,
        )

    def _collect_local_update_global_notes(
        self, update_plan: LocalModUpdatePlan, review_entries: list[LocalUpdateReviewEntry]
    ) -> list[str]:
        return self._collect_review_global_notes(
            base_notes=[LOCAL_UPDATE_REVIEW_PRECHECK_NOTE],
            review_entries=review_entries,
            extra_note_groups=(
                list(getattr(update_plan, "notes", []) or []),
                list(getattr(getattr(update_plan, "metadata_summary", None), "notes", []) or []),
            ),
        )

    def _persist_local_update_plan_metadata(self, update_plan: LocalModUpdatePlan) -> None:
        """將更新檢查得到的 metadata / hash 回寫索引，接近 Prism 的 ensure metadata 流程。"""
        manager = self.mod_manager
        if not manager:
            return
        processed_paths: set[str] = set()
        for candidate in getattr(update_plan, "candidates", []) or []:
            local_mod = getattr(candidate, "local_mod", None)
            file_path_raw = str(getattr(local_mod, "file_path", "") or "").strip()
            if not file_path_raw:
                continue
            file_path = Path(file_path_raw)
            processed_paths.add(str(file_path))
            current_hash = str(getattr(candidate, "current_hash", "") or "").strip()
            if current_hash:
                manager.index_manager.cache_file_hash(
                    file_path, str(getattr(candidate, "hash_algorithm", "sha512") or "sha512"), current_hash
                )
            project_id = str(getattr(candidate, "project_id", "") or "").strip()
            cached_provider = manager.index_manager.get_cached_provider_metadata(file_path) or {}
            if project_id.startswith("__stale__::"):
                # 策略性延後處理應標記為過期（Stale），而不視為重新驗證失敗。
                payload = dict(cached_provider) if isinstance(cached_provider, dict) else {}
                payload["lifecycle_state"] = PROVIDER_LIFECYCLE_STALE
                manager.index_manager.cache_provider_metadata(file_path, payload)
                continue
            if not project_id or project_id.startswith("__unresolved__::"):
                continue
            success_payload = register_provider_revalidation_success(cached_provider)
            manager.index_manager.cache_provider_metadata(file_path, success_payload)
            cache_provider_metadata_record(
                manager.index_manager,
                file_path,
                ProviderMetadataRecord.from_values(
                    project_id=project_id,
                    slug=str(getattr(local_mod, "platform_slug", "") or "").strip(),
                    project_name=str(getattr(candidate, "project_name", "") or project_id).strip(),
                ),
                metadata_source=str(getattr(candidate, "metadata_source", "") or "").strip() or "update_review",
            )
        # 強制回寫掃描結果的 Metadata 與 Hash，以確保增強資料的持久化。
        try:
            scanned = manager.get_mod_list()
            for local_mod in scanned:
                file_path_raw = str(getattr(local_mod, "file_path", "") or "").strip()
                if not file_path_raw:
                    continue
                fp = Path(file_path_raw)
                if str(fp) in processed_paths:
                    continue
                # 若 local_mod 有 hash，則回寫
                current_hash = str(getattr(local_mod, "current_hash", "") or "").strip()
                if current_hash:
                    alg = str(getattr(local_mod, "hash_algorithm", "sha512") or "sha512")
                    manager.index_manager.cache_file_hash(fp, alg, current_hash)
                # 若 local_mod 有 provider metadata，則回寫
                project_id = str(getattr(local_mod, "platform_id", "") or "").strip()
                slug = str(getattr(local_mod, "platform_slug", "") or "").strip()
                if project_id or slug:
                    # 對於掃描時的增強解析，使用 scan_detect 作為 metadata_source
                    cache_provider_metadata_record(
                        manager.index_manager,
                        fp,
                        ProviderMetadataRecord.from_values(
                            project_id=project_id,
                            slug=slug,
                            project_name=str(getattr(local_mod, "name", "") or "").strip(),
                        ),
                        metadata_source="scan_detect",
                    )
        except Exception:
            logger.debug("在回寫掃描結果時發生錯誤，已忽略。")
        manager.index_manager.flush()

    def _cache_local_dependency_plan_snapshot(
        self, candidate: Any, dependency_plan: Any, *, root_enabled: bool | None = None
    ) -> None:
        """將 local update review 的 dependency plan 快照寫回索引，供後續重用/追蹤。"""
        manager = self.mod_manager
        if not manager:
            return
        local_mod = getattr(candidate, "local_mod", None)
        file_path_raw = str(getattr(local_mod, "file_path", "") or "").strip()
        if not file_path_raw:
            return
        snapshot = serialize_online_dependency_install_plan(
            dependency_plan,
            root_project_id=str(getattr(candidate, "project_id", "") or "").strip(),
            root_project_name=str(getattr(candidate, "project_name", "") or "").strip(),
            root_target_version_id=str(getattr(candidate, "target_version_id", "") or "").strip(),
            root_target_version_name=str(getattr(candidate, "target_version_name", "") or "").strip(),
            root_enabled=root_enabled,
            plan_source="local_update_review",
        )
        has_content = any(
            [
                snapshot.get("items"),
                snapshot.get("advisory_items"),
                snapshot.get("unresolved_required"),
                snapshot.get("notes"),
            ]
        )
        if not has_content:
            return
        manager.index_manager.cache_provider_metadata(Path(file_path_raw), {"dependency_plan_v1": snapshot})

    def _load_local_dependency_plan_snapshot(self, candidate: Any) -> tuple[Any | None, bool | None]:
        """自 index 讀回 local update review 的 dependency plan 快照。"""
        manager = self.mod_manager
        if not manager:
            return (None, None)
        local_mod = getattr(candidate, "local_mod", None)
        file_path_raw = str(getattr(local_mod, "file_path", "") or "").strip()
        if not file_path_raw:
            return (None, None)
        provider_metadata = manager.index_manager.get_cached_provider_metadata(Path(file_path_raw)) or {}
        snapshot_raw = provider_metadata.get("dependency_plan_v1")
        if not isinstance(snapshot_raw, dict):
            return (None, None)
        self._record_dependency_snapshot_migration_telemetry("checked")
        migrated_snapshot, migration_state = migrate_online_dependency_install_plan_payload(snapshot_raw)
        if migrated_snapshot is None:
            self._record_dependency_snapshot_migration_telemetry("fallback_rebuild")
            return (None, None)
        if migration_state == "migrated":
            self._record_dependency_snapshot_migration_telemetry("migrated")
            manager.index_manager.cache_provider_metadata(
                Path(file_path_raw), {"dependency_plan_v1": migrated_snapshot}
            )
            logger.info(f"已遷移 dependency_plan_v1 快照並回寫：{file_path_raw}")
            snapshot_raw = migrated_snapshot
        snapshot_valid, _snapshot_reason = validate_online_dependency_install_plan_payload(snapshot_raw)
        if not snapshot_valid:
            self._record_dependency_snapshot_migration_telemetry("fallback_rebuild")
            return (None, None)
        candidate_project_id = str(getattr(candidate, "project_id", "") or "").strip()
        candidate_target_version_id = str(getattr(candidate, "target_version_id", "") or "").strip()
        snapshot_project_id = str(snapshot_raw.get("root_project_id", "") or "").strip()
        snapshot_target_version_id = str(snapshot_raw.get("root_target_version_id", "") or "").strip()
        snapshot_root_enabled_raw = snapshot_raw.get("root_enabled")
        snapshot_root_enabled = snapshot_root_enabled_raw if isinstance(snapshot_root_enabled_raw, bool) else None
        if candidate_project_id and snapshot_project_id and (candidate_project_id != snapshot_project_id):
            self._record_dependency_snapshot_migration_telemetry("fallback_rebuild")
            return (None, snapshot_root_enabled)
        if (
            candidate_target_version_id
            and snapshot_target_version_id
            and (candidate_target_version_id != snapshot_target_version_id)
        ):
            self._record_dependency_snapshot_migration_telemetry("fallback_rebuild")
            return (None, snapshot_root_enabled)
        restored = deserialize_online_dependency_install_plan(snapshot_raw)
        has_content = bool(
            list(getattr(restored, "items", []) or [])
            or list(getattr(restored, "advisory_items", []) or [])
            or list(getattr(restored, "unresolved_required", []) or [])
            or list(getattr(restored, "notes", []) or [])
        )
        if has_content:
            self._record_dependency_snapshot_migration_telemetry("replayed")
        return (restored if has_content else None, snapshot_root_enabled)

    def _persist_local_update_dependency_plan_snapshots(self, review_entries: list[LocalUpdateReviewEntry]) -> None:
        """將目前 review 中的依賴勾選狀態回寫快照，供下次回放。"""
        for review_entry in review_entries:
            candidate = getattr(review_entry, "candidate", None)
            dependency_plan = getattr(review_entry, "dependency_plan", None)
            if candidate is None or dependency_plan is None:
                continue
            self._cache_local_dependency_plan_snapshot(
                candidate, dependency_plan, root_enabled=bool(getattr(review_entry, "enabled", False))
            )

    @staticmethod
    def _collect_online_dependency_required_by(
        review_entries: list[PendingInstallReviewEntry],
    ) -> dict[tuple[str, str], list[str]]:
        return ModManagementReviewMixin._collect_dependency_required_by(
            review_entries,
            parent_name_getter=lambda entry: str(
                getattr(getattr(entry, "pending", None), "project_name", "") or ""
            ).strip(),
        )

    @staticmethod
    def _collect_local_dependency_required_by(
        review_entries: list[LocalUpdateReviewEntry],
    ) -> dict[tuple[str, str], list[str]]:
        return ModManagementReviewMixin._collect_dependency_required_by(
            review_entries,
            parent_name_getter=lambda entry: str(
                getattr(getattr(entry, "candidate", None), "project_name", "") or ""
            ).strip(),
        )

    @staticmethod
    def _build_local_update_review_key(candidate: Any) -> str:
        project_id = str(getattr(candidate, "project_id", "") or "").strip()
        local_mod = getattr(candidate, "local_mod", None)
        file_path = str(getattr(local_mod, "file_path", "") or "").strip()
        if project_id and file_path:
            return f"project::{project_id}::{file_path}"
        if project_id:
            return project_id
        if file_path:
            return f"local::{file_path}"
        filename = str(getattr(candidate, "filename", "") or getattr(local_mod, "filename", "") or "").strip()
        if filename:
            return f"local::{filename}"
        project_name = str(getattr(candidate, "project_name", "") or "unknown").strip()
        return f"local::{project_name}"

    @staticmethod
    def _build_dependency_key(dependency_item: Any) -> tuple[str, str]:
        return (
            str(getattr(dependency_item, "project_id", "") or "").strip(),
            str(
                getattr(dependency_item, "version_id", "") or getattr(dependency_item, "version_name", "") or ""
            ).strip(),
        )

    @staticmethod
    def _collect_dependency_required_by(
        review_entries: list[Any], *, parent_name_getter: Callable[[Any], str]
    ) -> dict[tuple[str, str], list[str]]:
        required_by: dict[tuple[str, str], list[str]] = {}
        for entry in review_entries:
            if not bool(getattr(entry, "enabled", False)) or not bool(getattr(entry, "runnable", False)):
                continue
            parent_name = parent_name_getter(entry)
            if not parent_name:
                continue
            dependency_entries = ModManagementReviewMixin._get_sorted_dependency_review_items(entry.dependency_plan)
            for dependency_item in dependency_entries:
                dependency_key = ModManagementReviewMixin._build_dependency_key(dependency_item)
                required_by.setdefault(dependency_key, []).append(parent_name)
        return required_by

    @staticmethod
    def _format_completion_notes(messages: list[str], max_items: int = 4) -> str:
        deduped = ModManagementReviewMixin._dedupe_review_messages(messages)
        if not deduped:
            return ""
        preview = deduped[:max_items]
        suffix = f"\n另有 {len(deduped) - len(preview)} 則提醒。" if len(deduped) > len(preview) else ""
        return "\n提醒：\n- " + "\n- ".join(preview) + suffix

    @staticmethod
    def _get_sorted_dependency_review_items(dependency_plan: Any) -> list[Any]:
        dependency_entries = [
            *list(getattr(dependency_plan, "items", []) or []),
            *list(getattr(dependency_plan, "advisory_items", []) or []),
        ]
        dependency_entries.sort(
            key=lambda item: (
                str(getattr(item, "project_name", "") or "").casefold(),
                str(getattr(item, "version_name", "") or "").casefold(),
            )
        )
        return dependency_entries

    @staticmethod
    def _get_enabled_dependency_install_items(dependency_plan: Any) -> list[Any]:
        return [
            *list(getattr(dependency_plan, "items", []) or []),
            *[
                item
                for item in list(getattr(dependency_plan, "advisory_items", []) or [])
                if bool(getattr(item, "enabled", False))
            ],
        ]

    @staticmethod
    def _set_selected_advisory_dependency_items_enabled(
        tree: ttk.Treeview, entry_map: dict[str, Any], enabled: bool
    ) -> bool:
        changed = False
        for item_id in tree.selection():
            normalized_item_id = str(item_id or "").strip()
            if normalized_item_id.endswith("::optional-dependencies"):
                root_key = normalized_item_id.rsplit("::optional-dependencies", 1)[0]
                if root_key not in entry_map:
                    continue
                advisory_items = list(
                    getattr(getattr(entry_map[root_key], "dependency_plan", None), "advisory_items", []) or []
                )
                for dependency_item in advisory_items:
                    if bool(getattr(dependency_item, "enabled", False)) == enabled:
                        continue
                    dependency_item.enabled = enabled
                    changed = True
                continue
            if "::dependency::" not in normalized_item_id:
                continue
            root_key, dependency_index_text = normalized_item_id.rsplit("::dependency::", 1)
            if root_key not in entry_map:
                continue
            try:
                dependency_index = int(dependency_index_text)
            except ValueError:
                continue
            dependency_items = ModManagementReviewMixin._get_sorted_dependency_review_items(
                getattr(entry_map[root_key], "dependency_plan", None)
            )
            advisory_items = list(
                getattr(getattr(entry_map[root_key], "dependency_plan", None), "advisory_items", []) or []
            )
            advisory_item_ids = {id(item) for item in advisory_items}
            if dependency_index < 0 or dependency_index >= len(dependency_items):
                continue
            dependency_item = dependency_items[dependency_index]
            if not (
                bool(getattr(dependency_item, "maybe_installed", False))
                or bool(getattr(dependency_item, "is_optional", False))
                or id(dependency_item) in advisory_item_ids
            ):
                continue
            if bool(getattr(dependency_item, "enabled", False)) == enabled:
                continue
            dependency_item.enabled = enabled
            changed = True
        return changed

    @staticmethod
    def _get_review_entry_group_key(entry: Any) -> str:
        if isinstance(entry, PendingInstallReviewEntry):
            return ModManagementReviewMixin._get_online_install_review_group_key(entry)
        if not bool(getattr(entry, "runnable", False)):
            return "blocked"
        if not bool(getattr(entry, "enabled", False)):
            return "disabled"
        return "enabled"

    @staticmethod
    def _get_online_install_review_group_key(entry: PendingInstallReviewEntry) -> str:
        """將線上安裝 review 項目分類為與本地更新 review 共用的 group key。"""
        if not bool(getattr(entry, "runnable", False)):
            return "blocked"
        if not bool(getattr(entry, "enabled", False)):
            return "disabled"
        if list(getattr(entry, "warning_messages", []) or []):
            return "advisory"
        return "enabled"

    @staticmethod
    def _get_local_update_review_group_key(entry: LocalUpdateReviewEntry) -> str:
        candidate = getattr(entry, "candidate", None)
        recommendation_confidence = str(getattr(candidate, "recommendation_confidence", "") or "").strip().lower()
        recommendation_source = str(getattr(candidate, "recommendation_source", "") or "").strip().lower()
        metadata_source = str(getattr(candidate, "metadata_source", "") or "").strip().lower()
        if not bool(getattr(entry, "runnable", False)):
            if (
                recommendation_confidence == RECOMMENDATION_CONFIDENCE_RETRYABLE
                or recommendation_source == RECOMMENDATION_SOURCE_STALE_METADATA
                or metadata_source == METADATA_SOURCE_STALE_PROVIDER
            ):
                return "retryable"
            if (
                recommendation_source == RECOMMENDATION_SOURCE_METADATA_UNRESOLVED
                or metadata_source == METADATA_SOURCE_UNRESOLVED
            ):
                return "unknown"
            return "blocked"
        if not bool(getattr(entry, "enabled", False)):
            return "disabled"
        if recommendation_confidence == RECOMMENDATION_CONFIDENCE_ADVISORY:
            return "advisory"
        return "enabled"

    @staticmethod
    def _get_review_group_specs() -> tuple[tuple[str, str], ...]:
        return (
            ("enabled", "已啟用項目"),
            ("advisory", "建議確認項目"),
            ("disabled", "已停用項目"),
            ("retryable", "可重試項目"),
            ("unknown", "待識別項目"),
            ("blocked", "需先處理項目"),
        )

    @staticmethod
    def _count_review_groups(
        entries: list[Any], *, supported_group_keys: Iterable[str], group_key_getter: Callable[[Any], str]
    ) -> dict[str, int]:
        counts = dict.fromkeys(supported_group_keys, 0)
        for entry in entries:
            group_key = group_key_getter(entry)
            counts[group_key] = counts.get(group_key, 0) + 1
        return counts

    @staticmethod
    def _count_local_update_review_groups(entries: list[LocalUpdateReviewEntry]) -> dict[str, int]:
        return ModManagementReviewMixin._count_review_groups(
            entries,
            supported_group_keys=("enabled", "advisory", "disabled", "retryable", "unknown", "blocked"),
            group_key_getter=ModManagementReviewMixin._get_local_update_review_group_key,
        )

    @staticmethod
    def _build_local_update_root_status_text(review_entry: LocalUpdateReviewEntry) -> str:
        return ModManagementReviewMixin._build_review_root_status_text(
            review_entry,
            group_key_getter=ModManagementReviewMixin._get_local_update_review_group_key,
            group_status_getter=ModManagementReviewMixin._get_local_update_group_status_label,
        )

    @staticmethod
    def _get_review_group_label(group_key: str, label_map: dict[str, str], *, default_label: str = "需先處理") -> str:
        return label_map.get(group_key, default_label)

    @staticmethod
    def _get_local_update_group_status_label(group_key: str) -> str:
        return ModManagementReviewMixin._get_review_group_label(
            group_key,
            {
                "enabled": "可更新",
                "advisory": "建議確認",
                "disabled": "已停用",
                "retryable": "可重試",
                "unknown": "需先識別",
                "blocked": "需先處理",
            },
        )

    @staticmethod
    def _get_online_install_group_status_label(group_key: str) -> str:
        """線上安裝用 group 標籤；與本地更新共用 group key，但 enabled 標籤不同。"""
        return ModManagementReviewMixin._get_review_group_label(
            group_key,
            {"enabled": "可安裝", "advisory": "建議確認", "disabled": "已停用", "blocked": "需先處理"},
        )

    @staticmethod
    def _count_online_install_review_groups(entries: list[PendingInstallReviewEntry]) -> dict[str, int]:
        return ModManagementReviewMixin._count_review_groups(
            entries,
            supported_group_keys=("enabled", "advisory", "disabled", "blocked"),
            group_key_getter=ModManagementReviewMixin._get_online_install_review_group_key,
        )

    @staticmethod
    def _build_review_execution_prompt(
        review_entries: list[Any],
        *,
        counts: dict[str, int],
        summary_title: str,
        continue_action_template: str,
        required_group_keys: Iterable[str],
        summary_templates: Iterable[tuple[str, str]],
    ) -> str | None:
        actionable_count = sum(1 for entry in review_entries if bool(getattr(entry, "actionable", False)))
        if actionable_count <= 0:
            return None
        if not any(counts.get(group_key, 0) > 0 for group_key in required_group_keys):
            return None
        summary_lines = [
            line_template.format(count=counts[group_key])
            for group_key, line_template in summary_templates
            if counts.get(group_key, 0)
        ]
        if not summary_lines:
            return None
        return (
            f"{summary_title}：\n"
            + "\n".join(summary_lines)
            + f"\n\n將繼續{continue_action_template.format(count=actionable_count)}。\n\n是否繼續？"
        )

    @staticmethod
    def _build_online_install_execution_prompt(review_entries: list[PendingInstallReviewEntry]) -> str | None:
        """與 _build_local_update_execution_prompt 共用語意，建立線上安裝前確認提示。"""
        counts = ModManagementReviewMixin._count_online_install_review_groups(review_entries)
        return ModManagementReviewMixin._build_review_execution_prompt(
            review_entries,
            counts=counts,
            summary_title="本次安裝摘要",
            continue_action_template="安裝其餘 {count} 個可安裝項目",
            required_group_keys=("blocked",),
            summary_templates=(
                ("advisory", ONLINE_INSTALL_PROMPT_ADVISORY_LINE_TEMPLATE),
                ("blocked", ONLINE_INSTALL_PROMPT_BLOCKED_LINE_TEMPLATE),
            ),
        )

    @staticmethod
    def _build_local_update_group_detail_text(group_key: str) -> str:
        return ModManagementReviewMixin._get_review_group_label(
            group_key,
            {
                "enabled": "處理等級：可更新",
                "advisory": "處理等級：建議確認，將依目前啟用狀態一併更新",
                "disabled": "處理等級：已停用，這次不會執行",
                "retryable": LOCAL_UPDATE_GROUP_DETAIL_RETRYABLE,
                "unknown": "處理等級：需先識別，尚未建立可靠的 provider metadata",
                "blocked": "處理等級：需先處理，仍有相容性或依賴阻擋",
            },
            default_label="處理等級：需先處理",
        )

    @staticmethod
    def _build_local_update_execution_prompt(review_entries: list[LocalUpdateReviewEntry]) -> str | None:
        counts = ModManagementReviewMixin._count_local_update_review_groups(review_entries)
        return ModManagementReviewMixin._build_review_execution_prompt(
            review_entries,
            counts=counts,
            summary_title="本次更新摘要",
            continue_action_template="更新其餘 {count} 個可更新項目",
            required_group_keys=("retryable", "unknown", "blocked"),
            summary_templates=(
                ("advisory", LOCAL_UPDATE_PROMPT_ADVISORY_LINE_TEMPLATE),
                ("retryable", LOCAL_UPDATE_PROMPT_RETRYABLE_LINE_TEMPLATE),
                ("unknown", LOCAL_UPDATE_PROMPT_UNKNOWN_LINE_TEMPLATE),
                ("blocked", LOCAL_UPDATE_PROMPT_BLOCKED_LINE_TEMPLATE),
            ),
        )

    def _confirm_non_official_download_sources(
        self,
        review_entries: list[Any],
        *,
        action_label: str,
        parent: Any,
    ) -> bool:
        confirmation_prompt = self._build_non_official_source_confirmation_prompt(
            review_entries,
            action_label=action_label,
        )
        if not confirmation_prompt:
            return True
        logger.warning("偵測到非官方下載來源，進入二次確認流程: action=%s", action_label)
        proceed = UIUtils.ask_yes_no_cancel(
            "非官方來源二次確認",
            confirmation_prompt,
            parent=parent,
            show_cancel=False,
        )
        logger.info(
            "非官方下載來源二次確認完成: action=%s proceed=%s",
            action_label,
            proceed is True,
        )
        return proceed is True

    @staticmethod
    def _build_group_node_id(group_key: str) -> str:
        return f"group::{group_key}"

    @staticmethod
    def _build_dependency_status_text(
        dependency_item: Any, parent_name: str, required_by_text: str, is_advisory: bool, is_enabled: bool
    ) -> str:
        resolved_required_by = required_by_text or parent_name
        resolution_label = ModManagementReviewMixin._format_dependency_resolution_label(
            getattr(dependency_item, "resolution_source", "project_id"),
            getattr(dependency_item, "resolution_confidence", "direct"),
        )
        action_label = ModManagementReviewMixin._format_dependency_action_label(
            dependency_item, is_advisory, is_enabled
        )
        return f"required-by：{resolved_required_by}｜解析：{resolution_label}｜處理：{action_label}"

    def _build_dependency_review_nodes(
        self,
        *,
        root_key: str,
        group_key: str,
        optional_group_values: tuple[str, ...],
        parent_name: str,
        dependency_plan: Any,
        required_by_map: dict[tuple[str, str], list[str]],
        node_builder: Callable[[int, Any, str, bool, bool, str], ReviewTaskNode],
    ) -> list[ReviewTaskNode]:
        nodes: list[ReviewTaskNode] = []
        dependency_entries: list[tuple[Any, bool]] = [
            *((item, False) for item in list(getattr(dependency_plan, "items", []) or [])),
            *((item, True) for item in list(getattr(dependency_plan, "advisory_items", []) or [])),
        ]
        dependency_entries.sort(
            key=lambda entry: (
                str(getattr(entry[0], "project_name", "") or "").casefold(),
                str(getattr(entry[0], "version_name", "") or "").casefold(),
            )
        )
        optional_group_id = f"{root_key}::optional-dependencies"
        optional_group_added = False
        optional_count = sum(
            (1 for item, is_from_advisory in dependency_entries if bool(getattr(item, "is_optional", is_from_advisory)))
        )
        for index, (dependency_item, is_from_advisory) in enumerate(dependency_entries):
            dependency_key = self._build_dependency_key(dependency_item)
            required_by_text = self._format_required_by_list(required_by_map.get(dependency_key, [parent_name]))
            is_optional = bool(getattr(dependency_item, "is_optional", is_from_advisory))
            maybe_installed = bool(getattr(dependency_item, "maybe_installed", False))
            is_enabled = bool(getattr(dependency_item, "enabled", not (is_optional or maybe_installed)))
            dependency_status = self._build_dependency_status_text(
                dependency_item, parent_name, required_by_text, is_optional, is_enabled
            )
            parent_id = root_key
            if is_optional:
                if not optional_group_added:
                    optional_group_added = True
                    group_status = f"共 {optional_count} 項，可啟用後一同安裝"
                    nodes.append(
                        ReviewTaskNode(
                            node_id=optional_group_id,
                            root_key=root_key,
                            group_key=group_key,
                            parent_id=root_key,
                            title="可選依賴",
                            values=(*optional_group_values[:-1], group_status),
                            node_kind="dependency-group",
                            detail=group_status,
                        )
                    )
                parent_id = optional_group_id
            nodes.append(node_builder(index, dependency_item, dependency_status, is_optional, is_enabled, parent_id))
        return nodes

    @staticmethod
    def _append_review_message_nodes(
        nodes: list[ReviewTaskNode], *, messages: list[str], node_factory: Callable[[int, str], ReviewTaskNode]
    ) -> None:
        for index, message in enumerate(messages):
            nodes.append(node_factory(index, message))

    @staticmethod
    def _mask_redundant_review_values(parent_values: tuple[str, ...], child_values: tuple[str, ...]) -> tuple[str, ...]:
        """將與父節點相同的欄位值改以 '-' 顯示。"""
        masked_values: list[str] = []
        for index, raw_child in enumerate(child_values):
            child_text = str(raw_child or "").strip() or "-"
            parent_text = str(parent_values[index] if index < len(parent_values) else "").strip() or "-"
            if child_text != "-" and child_text == parent_text:
                masked_values.append("-")
            else:
                masked_values.append(child_text)
        return tuple(masked_values)

    def _build_dependency_task_node(
        self,
        *,
        root_key: str,
        group_key: str,
        parent_values: tuple[str, ...],
        index: int,
        dependency_item: Any,
        dependency_status: str,
        is_advisory: bool,
        is_enabled: bool,
        parent_id: str,
        title_getter: Callable[[Any], str],
        values_getter: Callable[[Any, bool, bool, str], tuple[str, ...]],
        detail_getter: Callable[[str, str], str] | None = None,
    ) -> ReviewTaskNode:
        child_values = values_getter(dependency_item, is_advisory, is_enabled, dependency_status)
        detail_text = detail_getter(group_key, dependency_status) if detail_getter is not None else dependency_status
        return ReviewTaskNode(
            node_id=f"{root_key}::dependency::{index}",
            root_key=root_key,
            group_key=group_key,
            parent_id=parent_id,
            title=title_getter(dependency_item),
            values=self._mask_redundant_review_values(parent_values, child_values),
            node_kind="dependency",
            detail=detail_text,
        )

    def _build_online_dependency_task_node(
        self,
        *,
        root_key: str,
        group_key: str,
        parent_values: tuple[str, ...],
        index: int,
        dependency_item: Any,
        dependency_status: str,
        is_advisory: bool,
        is_enabled: bool,
        parent_id: str,
    ) -> ReviewTaskNode:
        return self._build_dependency_task_node(
            root_key=root_key,
            group_key=group_key,
            parent_values=parent_values,
            index=index,
            dependency_item=dependency_item,
            dependency_status=dependency_status,
            is_advisory=is_advisory,
            is_enabled=is_enabled,
            parent_id=parent_id,
            title_getter=lambda _item: "依賴",
            values_getter=lambda item, advisory, enabled, status: (
                "自動" if enabled else "略過" if advisory else "自動",
                "Modrinth",
                item.project_name,
                item.version_name,
                "optional" if self._is_optional_dependency_item(item) else "required",
                status,
            ),
        )

    def _build_local_dependency_task_node(
        self,
        *,
        root_key: str,
        group_key: str,
        parent_values: tuple[str, ...],
        index: int,
        dependency_item: Any,
        dependency_status: str,
        is_advisory: bool,
        is_enabled: bool,
        parent_id: str,
    ) -> ReviewTaskNode:
        return self._build_dependency_task_node(
            root_key=root_key,
            group_key=group_key,
            parent_values=parent_values,
            index=index,
            dependency_item=dependency_item,
            dependency_status=dependency_status,
            is_advisory=is_advisory,
            is_enabled=is_enabled,
            parent_id=parent_id,
            title_getter=lambda item: f"依賴：{item.project_name}",
            values_getter=lambda item, advisory, enabled, status: (
                "自動" if enabled else "略過" if advisory else "自動",
                "-",
                item.version_name,
                "可選依賴" if self._is_optional_dependency_item(item) else "Modrinth",
                status,
            ),
            detail_getter=lambda current_group_key, status: (
                f"{self._build_local_update_group_detail_text(current_group_key)}\n{status}"
            ),
        )

    def _build_issue_task_node(
        self,
        *,
        root_key: str,
        group_key: str,
        parent_values: tuple[str, ...],
        index: int,
        message: str,
        value_suffix: tuple,
    ) -> ReviewTaskNode:
        return ReviewTaskNode(
            node_id=f"{root_key}::blocked::{index}",
            root_key=root_key,
            group_key=group_key,
            parent_id=root_key,
            title="需處理",
            values=self._mask_redundant_review_values(parent_values, (*value_suffix, message)),
            node_kind="issue",
        )

    @staticmethod
    def _append_simulated_installed_mod(simulated_installed_mods: list[Any], simulation_item: Any) -> None:
        simulated_installed_mods.append(simulation_item)

    def _append_enabled_dependency_simulations(self, simulated_installed_mods: list[Any], dependency_plan: Any) -> None:
        for dependency_item in self._get_enabled_dependency_install_items(dependency_plan):
            self._append_simulated_installed_mod(
                simulated_installed_mods,
                self._build_installed_mod_simulation_item(
                    dependency_item.project_id,
                    dependency_item.project_name,
                    dependency_item.filename,
                    dependency_item.version_name,
                ),
            )

    @staticmethod
    def _append_review_section(lines: list[str], title: str, messages: list[str], *, max_items: int) -> None:
        summarized = ModManagementReviewMixin._summarize_review_messages(messages, max_items=max_items)
        if not summarized:
            return
        lines.append("")
        lines.append(title)
        lines.extend(f"- {item}" for item in summarized)

    @staticmethod
    def _append_dependency_review_sections(lines: list[str], dependency_plan: Any, required_heading: str) -> None:
        dependency_items = list(getattr(dependency_plan, "items", []) or [])
        advisory_items = list(getattr(dependency_plan, "advisory_items", []) or [])
        if dependency_items:
            lines.append("")
            lines.append(required_heading)
            lines.extend(f"- {item.project_name} ({item.version_name})" for item in dependency_items[:3])
            if len(dependency_items) > 3:
                lines.append(f"- 其餘 {len(dependency_items) - 3} 項請於任務樹查看。")
        if advisory_items:
            optional_items = [
                item for item in advisory_items if ModManagementReviewMixin._is_optional_dependency_item(item)
            ]
            maybe_installed_items = [
                item for item in advisory_items if not ModManagementReviewMixin._is_optional_dependency_item(item)
            ]
            if optional_items:
                lines.append("")
                lines.append("可選依賴（可啟用後一同安裝）：")
                lines.extend(
                    f"- {item.project_name}{('（已啟用）' if getattr(item, 'enabled', False) else '（預設略過）')}"
                    for item in optional_items[:2]
                )
                if len(optional_items) > 2:
                    lines.append(f"- 其餘 {len(optional_items) - 2} 項請於任務樹查看。")
            if maybe_installed_items:
                lines.append("")
                lines.append("疑似已安裝、預設略過的必要依賴：")
                lines.extend(
                    f"- {item.project_name}{('（已改為安裝）' if getattr(item, 'enabled', False) else '')}"
                    for item in maybe_installed_items[:2]
                )
                if len(maybe_installed_items) > 2:
                    lines.append(f"- 其餘 {len(maybe_installed_items) - 2} 項請於任務樹查看。")

    def _append_plan_note_section(self, lines: list[str], dependency_plan: Any, *, max_items: int = 2) -> None:
        plan_notes = self._dedupe_review_messages(list(getattr(dependency_plan, "notes", []) or []))
        self._append_review_section(lines, "預檢補充：", plan_notes, max_items=max_items)

    @staticmethod
    def _configure_review_action_button(button: ctk.CTkButton, review_entries: list[Any], action_label: str) -> None:
        runnable_enabled = ModManagementReviewMixin._count_enabled_runnable_entries(review_entries)
        button.configure(
            text=f"⬇️ {action_label} {runnable_enabled} 個已啟用項目", state="normal" if runnable_enabled else "disabled"
        )

    def _toggle_review_selection(
        self,
        *,
        tree: ttk.Treeview,
        entry_map: dict[str, Any],
        review_root_keys: set[str],
        enabled: bool,
        rebuild_entries: Callable[[], None],
        refresh_tree: Callable[[], None],
        refresh_summary: Callable[[], None],
        refresh_status_banner: Callable[[], None],
        refresh_action_button: Callable[[], None],
    ) -> None:
        if self._set_selected_advisory_dependency_items_enabled(tree, entry_map, enabled):
            rebuild_entries()
            refresh_tree()
            refresh_summary()
            refresh_status_banner()
            refresh_action_button()
            return
        selected_root_keys = self._collect_selected_root_keys_from(tree, review_root_keys)
        if not selected_root_keys:
            return
        if not self._set_review_entries_enabled(entry_map, selected_root_keys, enabled):
            return
        rebuild_entries()
        refresh_tree()
        refresh_summary()
        refresh_status_banner()
        refresh_action_button()

    def _create_review_action_button(
        self,
        parent,
        *,
        text: str,
        fg_color: Any,
        hover_color: Any,
        command: Callable[[], None],
        padx: tuple[int, int] | None = None,
        side: str = "left",
        bold: bool = False,
    ) -> ctk.CTkButton:
        button = ctk.CTkButton(
            parent,
            text=text,
            font=FontManager.get_font(size=FontSize.LARGE, weight="bold" if bold else "normal"),
            fg_color=fg_color,
            hover_color=hover_color,
            text_color=Colors.TEXT_ON_DARK,
            command=command,
            width=Sizes.BUTTON_WIDTH_COMPACT,
            height=Sizes.BUTTON_HEIGHT,
        )
        pack_kwargs: dict[str, Any] = {"side": side}
        if padx is not None:
            pack_kwargs["padx"] = padx
        button.pack(**pack_kwargs)
        return button

    def _render_review_task_tree(self, tree: ttk.Treeview, nodes: list[ReviewTaskNode], column_count: int) -> None:
        selected_key = self._get_selected_review_key(
            tree, {node.root_key for node in nodes if node.node_kind == "root"}
        )
        for item_id in tree.get_children():
            tree.delete(item_id)
        blank_values = tuple("" for _ in range(column_count))
        group_parent_ids: dict[str, str] = {}
        for group_key, label in self._get_review_group_specs():
            if not any(node.node_kind == "root" and node.group_key == group_key for node in nodes):
                continue
            group_id = self._build_group_node_id(group_key)
            group_parent_ids[group_key] = group_id
            tree.insert("", "end", iid=group_id, text=label, values=blank_values, open=True, tags=("group", group_key))
        for node in nodes:
            parent_id = group_parent_ids.get(node.group_key, "") if node.parent_id is None else node.parent_id
            tree.insert(
                parent_id,
                "end",
                iid=node.node_id,
                text=node.title,
                values=node.values,
                open=node.node_kind in {"root", "dependency-group"},
                tags=(node.node_kind, node.root_key, node.group_key),
            )
        TreeUtils.refresh_treeview_alternating_rows(tree)
        if selected_key and tree.exists(selected_key):
            tree.selection_set(selected_key)
        else:
            first_root = next((node.root_key for node in nodes if node.node_kind == "root"), "")
            if first_root and tree.exists(first_root):
                tree.selection_set(first_root)

    def _build_flat_review_task_nodes(
        self,
        review_entries: list,
        get_entry_key,
        get_root_key,
        get_group_key,
        get_title,
        get_status_text,
        get_root_values,
    ) -> list[ReviewTaskNode]:
        """
        通用化：建立根級節點（扁平列表），排序與欄位由 callback 控制。
        """
        nodes: list[ReviewTaskNode] = []
        sorted_entries = sorted(
            review_entries,
            key=get_entry_key,
        )
        seen_root_keys: set[str] = set()
        for review_entry in sorted_entries:
            root_key = get_root_key(review_entry)
            if root_key in seen_root_keys:
                continue
            seen_root_keys.add(root_key)
            group_key = get_group_key(review_entry)
            status_text = get_status_text(review_entry)
            root_values = get_root_values(review_entry, status_text)
            nodes.append(
                ReviewTaskNode(
                    node_id=root_key,
                    root_key=root_key,
                    group_key=group_key,
                    title=get_title(review_entry),
                    values=root_values,
                    node_kind="root",
                )
            )
        return nodes

    def _build_online_review_task_nodes(self, review_entries: list[PendingInstallReviewEntry]) -> list[ReviewTaskNode]:
        """建立線上安裝 review 的 task nodes，包含必要依賴子節點。"""

        def _entry_sort_key(entry: PendingInstallReviewEntry) -> tuple[Any, ...]:
            return (
                {"blocked": 0, "advisory": 1, "disabled": 2, "enabled": 3}.get(
                    self._get_online_install_review_group_key(entry), 99
                ),
                str(getattr(getattr(entry, "pending", None), "project_name", "") or "").casefold(),
                str(
                    getattr(getattr(getattr(entry, "pending", None), "version", None), "display_name", "") or ""
                ).casefold(),
            )

        root_nodes = self._build_flat_review_task_nodes(
            review_entries,
            get_entry_key=_entry_sort_key,
            get_root_key=lambda entry: self._build_pending_install_key(
                getattr(getattr(entry, "pending", None), "project_id", ""),
                getattr(getattr(getattr(entry, "pending", None), "version", None), "version_id", ""),
            ),
            get_group_key=self._get_online_install_review_group_key,
            get_title=lambda _entry: "模組",
            get_status_text=self._build_online_review_root_status_text,
            get_root_values=lambda entry, status_text: (
                "是" if entry.enabled else "否",
                self._format_review_provider_label(entry.provider),
                str(getattr(getattr(entry, "pending", None), "project_name", "") or "未知模組"),
                str(
                    getattr(getattr(getattr(entry, "pending", None), "version", None), "display_name", "") or "未知版本"
                ),
                str(getattr(entry, "version_type", "") or "-"),
                status_text,
            ),
        )
        root_node_map = {node.root_key: node for node in root_nodes if node.node_kind == "root"}
        required_by_map = self._collect_dependency_required_by(
            review_entries,
            parent_name_getter=lambda entry: str(
                getattr(getattr(entry, "pending", None), "project_name", "") or ""
            ).strip(),
        )
        dependency_nodes: list[ReviewTaskNode] = []
        for review_entry in sorted(review_entries, key=_entry_sort_key):
            pending = getattr(review_entry, "pending", None)
            root_key = self._build_pending_install_key(
                getattr(pending, "project_id", ""),
                getattr(getattr(pending, "version", None), "version_id", ""),
            )
            root_node = root_node_map.get(root_key)
            if root_node is None:
                continue
            root_group_key = root_node.group_key
            root_values = root_node.values

            def _build_online_dependency_node(
                index: int,
                dependency_item: Any,
                dependency_status: str,
                is_optional: bool,
                is_enabled: bool,
                parent_id: str,
                *,
                _root_key: str = root_key,
                _group_key: str = root_group_key,
                _parent_values: tuple[str, ...] = root_values,
            ) -> ReviewTaskNode:
                return self._build_online_dependency_task_node(
                    root_key=_root_key,
                    group_key=_group_key,
                    parent_values=_parent_values,
                    index=index,
                    dependency_item=dependency_item,
                    dependency_status=dependency_status,
                    is_advisory=is_optional,
                    is_enabled=is_enabled,
                    parent_id=parent_id,
                )

            dependency_nodes.extend(
                self._build_dependency_review_nodes(
                    root_key=root_key,
                    group_key=root_node.group_key,
                    optional_group_values=root_node.values,
                    parent_name=str(getattr(pending, "project_name", "") or "模組"),
                    dependency_plan=getattr(review_entry, "dependency_plan", None),
                    required_by_map=required_by_map,
                    node_builder=_build_online_dependency_node,
                )
            )
        return [*root_nodes, *dependency_nodes]

    def _build_local_update_task_nodes(self, review_entries: list[LocalUpdateReviewEntry]) -> list[ReviewTaskNode]:
        """相容層：建立本地更新 review 的根級 task nodes。"""
        return self._build_flat_review_task_nodes(
            review_entries,
            get_entry_key=lambda entry: (
                {"blocked": 0, "advisory": 1, "retryable": 2, "unknown": 3, "disabled": 4, "enabled": 5}.get(
                    self._get_local_update_review_group_key(entry), 99
                ),
                str(getattr(getattr(entry, "candidate", None), "project_name", "") or "").casefold(),
            ),
            get_root_key=lambda entry: self._build_local_update_review_key(entry.candidate),
            get_group_key=self._get_local_update_review_group_key,
            get_title=lambda entry: str(getattr(getattr(entry, "candidate", None), "project_name", "") or "模組"),
            get_status_text=self._build_local_update_root_status_text,
            get_root_values=lambda entry, status_text: (
                "是" if entry.enabled else "否",
                str(getattr(getattr(entry, "candidate", None), "current_version", "") or "未知"),
                str(getattr(getattr(entry, "candidate", None), "target_version_name", "") or "-"),
                self._format_local_update_source_text(entry),
                status_text,
            ),
        )

    def _format_pending_install_review_text(self, review_entry: PendingInstallReviewEntry) -> str:
        """格式化待安裝項目的 review 內容。"""
        lines = [self._format_online_version_report(review_entry.pending.version, review_entry.report)]
        lines.append("")
        lines.extend(self._build_pending_install_summary_lines(review_entry))
        client_install_reminder = self._build_client_install_reminder_line(
            getattr(review_entry.pending, "server_side", ""), getattr(review_entry.pending, "client_side", "")
        )
        if client_install_reminder:
            lines.append(client_install_reminder)
        lines.append("")
        lines.append(f"執行狀態：{('已啟用' if review_entry.enabled else '已停用')}")
        lines.append(
            "處理等級："
            + self._get_online_install_group_status_label(self._get_online_install_review_group_key(review_entry))
        )
        dependency_plan = getattr(review_entry, "dependency_plan", None)
        self._append_dependency_review_sections(lines, dependency_plan, "將自動安裝的必要依賴：")
        if review_entry.blocking_reasons:
            self._append_review_section(lines, "需先處理：", review_entry.blocking_reasons, max_items=3)
        elif review_entry.warning_messages:
            self._append_review_section(lines, "安裝前提醒：", review_entry.warning_messages, max_items=3)
        self._append_plan_note_section(lines, dependency_plan)
        return "\n".join(lines)

    def _create_review_shared_ui(self, main_frame: ctk.CTkFrame, wraplength: int) -> tuple[ctk.CTkLabel, ctk.CTkFrame]:
        """建立 Review 對話框中重複使用的概覽標籤與樹狀視圖容器。

        Args:
            main_frame: 父框架
            wraplength: 換行寬度限制

        Returns:
            包含建立好的標籤與框架組合的元組
        """
        return self._get_install_review_dialog_builder().create_review_shared_ui(main_frame, wraplength)

    def show_online_install_queue(self) -> None:
        """顯示待安裝清單與最終 review。"""
        if not self.pending_online_installs:
            UIUtils.show_info("安裝清單", "目前安裝清單是空的。", self.parent)
            return
        review_entries = self._prepare_online_install_review_entries()
        actionable_entries = [entry for entry in review_entries if entry.actionable]
        _, duplicate_dependency_count = self._collect_unique_dependency_install_keys(actionable_entries)
        review_entry_map = {
            self._build_pending_install_key(
                entry.pending.project_id, getattr(entry.pending.version, "version_id", "")
            ): entry
            for entry in review_entries
        }
        global_review_notes = self._collect_online_review_global_notes(review_entries)
        dialog = DialogUtils.create_toplevel_dialog(
            self.parent,
            "安裝清單 Review",
            width=Sizes.DIALOG_LARGE_WIDTH,
            height=Sizes.DIALOG_LARGE_HEIGHT,
            make_modal=True,
            bind_icon=True,
            center_on_parent=True,
            delay_ms=250,
            min_width=1000,
            min_height=820,
            max_width=FontManager.get_dpi_scaled_size(1280),
            max_height=FontManager.get_dpi_scaled_size(960),
            native_window=True,
            use_transient_for_modal=False,
        )
        main_frame = ctk.CTkFrame(dialog)
        main_frame.pack(fill="both", expand=True, padx=Spacing.LARGE, pady=Spacing.LARGE)
        title = ctk.CTkLabel(
            main_frame,
            text="待安裝模組與依賴檢查",
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
        )
        title.pack(anchor="w", padx=Spacing.MEDIUM, pady=(Spacing.MEDIUM, Spacing.SMALL))
        subtitle = ctk.CTkLabel(
            main_frame,
            text=self._build_online_install_review_subtitle(
                sum(1 for entry in review_entries if entry.actionable),
                self._count_blocked_entries(review_entries),
                advisory_count=self._count_online_install_review_groups(review_entries).get("advisory", 0),
                migrated_snapshot_count=self._dependency_snapshot_migration_totals.get("migrated", 0),
            ),
            font=FontManager.get_font(size=FontSize.SMALL_PLUS),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=FontManager.get_dpi_scaled_size(860),
        )
        subtitle.pack(fill="x", padx=Spacing.MEDIUM, pady=(0, Spacing.TINY))
        overview_label, tree_container = self._create_review_shared_ui(main_frame, 860)
        queue_tree = ttk.Treeview(
            tree_container,
            columns=("run", "source", "name", "version", "channel", "status"),
            show="tree headings",
            height=Spacing.MEDIUM,
            style=TreeUtils.configure_treeview_list_style(
                "InstallQueueList",
                body_font=FontManager.get_font(size=FontSize.INPUT),
                heading_font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
                rowheight=int(25 * FontManager.get_scale_factor()),
            ),
        )
        queue_tree.heading("#0", text="項目")
        queue_tree.column("#0", width=Sizes.BUTTON_WIDTH_SECONDARY, minwidth=90, anchor="w", stretch=False)
        queue_tree.heading("run", text="執行")
        queue_tree.column("run", width=Sizes.BUTTON_WIDTH_COMPACT, minwidth=60, anchor="center", stretch=False)
        queue_tree.heading("source", text="來源")
        queue_tree.column("source", width=Sizes.BUTTON_WIDTH_SMALL, minwidth=80, anchor="w", stretch=False)
        queue_tree.heading("name", text="名稱")
        queue_tree.column("name", width=Sizes.CONSOLE_PANEL_HEIGHT, minwidth=160, anchor="w", stretch=False)
        queue_tree.heading("version", text="版本")
        queue_tree.column("version", width=Sizes.DIALOG_SMALL_HEIGHT, minwidth=120, anchor="w", stretch=False)
        queue_tree.heading("channel", text="類型")
        queue_tree.column("channel", width=Sizes.BUTTON_WIDTH_SMALL, minwidth=80, anchor="w", stretch=False)
        queue_tree.heading("status", text="狀態")
        queue_tree.column("status", width=Sizes.SERVER_TREE_COL_LOADER + 20, minwidth=130, anchor="w", stretch=True)
        TreeUtils.bind_treeview_header_auto_fit(
            queue_tree,
            include_tree_column=True,
            heading_font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            body_font=FontManager.get_font(size=FontSize.INPUT),
            stretch_columns={"status"},
        )
        queue_scroll = ttk.Scrollbar(tree_container, orient="vertical", command=queue_tree.yview)
        queue_tree.configure(yscrollcommand=queue_scroll.set)
        queue_tree.grid(row=0, column=0, sticky="nsew")
        queue_scroll.grid(row=0, column=1, sticky="ns")
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)
        review_root_keys = set(review_entry_map)

        def refresh_queue_tree() -> None:
            self._render_review_task_tree(
                queue_tree, self._build_online_review_task_nodes(review_entries), column_count=6
            )

        summary_box = self._create_review_summary_box(main_frame, height=Sizes.SERVER_TREE_COL_LOADER)
        self._bind_vertical_mousewheel(queue_tree, scroll_callback=queue_tree.yview_scroll)
        summary_text_widget = getattr(summary_box, "_textbox", summary_box)
        self._bind_vertical_mousewheel(summary_box, scroll_callback=summary_text_widget.yview_scroll)
        self._bind_vertical_mousewheel(summary_text_widget, scroll_callback=summary_text_widget.yview_scroll)

        def refresh_queue_status_banner() -> None:
            review_nodes = self._build_online_review_task_nodes(review_entries)
            counts = self._count_online_install_review_groups(review_entries)
            actionable_count = sum(1 for entry in review_entries if entry.actionable)
            blocked_count = counts.get("blocked", 0)
            advisory_count = counts.get("advisory", 0)
            subtitle.configure(
                text=self._build_online_install_review_subtitle(
                    actionable_count,
                    blocked_count,
                    advisory_count=advisory_count,
                    migrated_snapshot_count=self._dependency_snapshot_migration_totals.get("migrated", 0),
                )
            )
            overview_label.configure(
                text=self._format_review_overview_text(
                    review_entries,
                    review_nodes,
                    action_label="安裝",
                    global_notes=global_review_notes,
                    deduped_dependency_count=duplicate_dependency_count,
                )
            )

        def refresh_queue_summary(_event=None) -> None:
            selected_root_key = self._get_selected_review_key(queue_tree, review_root_keys)
            review_entry = review_entry_map.get(selected_root_key)
            if not review_entry:
                return
            summary_box.configure(state="normal")
            summary_box.delete("1.0", "end")
            summary_box.insert("1.0", self._format_pending_install_review_text(review_entry))
            with contextlib.suppress(Exception):
                summary_box.yview_moveto(0.0)
            summary_box.configure(state="disabled")

        def open_selected_queue_project_page() -> None:
            selected_root_key = self._get_selected_review_key(queue_tree, review_root_keys)
            review_entry = review_entry_map.get(selected_root_key)
            project_page_url = (
                self._resolve_pending_install_review_project_page_url(review_entry) if review_entry else ""
            )
            self._open_project_page(project_page_url, dialog)

        queue_tree.bind("<<TreeviewSelect>>", refresh_queue_summary)
        refresh_queue_tree()
        refresh_queue_summary()
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x", padx=Spacing.MEDIUM, pady=(0, Spacing.SMALL))
        install_button = self._create_review_action_button(
            button_frame,
            text="",
            fg_color=Colors.BUTTON_SUCCESS,
            hover_color=Colors.BUTTON_SUCCESS_HOVER,
            command=lambda: self._install_pending_online_install_queue(dialog, review_entries),
            bold=True,
        )

        def refresh_queue_action_button() -> None:
            actionable_count = sum(1 for entry in review_entries if entry.actionable)
            install_button.configure(
                text=f"⬇️ 安裝 {actionable_count} 個可安裝項目", state="normal" if actionable_count else "disabled"
            )

        def refresh_queue_project_page_button(_event=None) -> None:
            selected_root_key = self._get_selected_review_key(queue_tree, review_root_keys)
            review_entry = review_entry_map.get(selected_root_key)
            project_page_button.configure(
                state="normal"
                if review_entry and self._resolve_pending_install_review_project_page_url(review_entry)
                else "disabled"
            )

        self._create_review_action_button(
            button_frame,
            text="移除選取項目",
            fg_color=Colors.BUTTON_WARNING,
            hover_color=Colors.BUTTON_WARNING_HOVER,
            command=lambda: self._remove_selected_pending_online_installs(queue_tree, dialog, review_root_keys),
            padx=(Spacing.SMALL_PLUS, 0),
        )
        self._create_review_action_button(
            button_frame,
            text="清空清單",
            fg_color=Colors.BUTTON_SECONDARY,
            hover_color=Colors.BUTTON_SECONDARY_HOVER,
            command=lambda: self._clear_pending_online_installs(dialog),
            padx=(Spacing.SMALL_PLUS, 0),
        )
        project_page_button = self._create_review_action_button(
            button_frame,
            text="開啟專案頁面",
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            command=open_selected_queue_project_page,
            padx=(Spacing.SMALL_PLUS, 0),
        )
        self._create_review_action_button(
            button_frame,
            text="關閉",
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            command=dialog.destroy,
            side="right",
        )
        refresh_queue_status_banner()
        refresh_queue_action_button()
        refresh_queue_project_page_button()
        queue_tree.bind("<<TreeviewSelect>>", refresh_queue_project_page_button, add="+")
        DialogUtils.schedule_toplevel_layout_refresh(
            dialog,
            min_width=1000,
            min_height=820,
            max_width=FontManager.get_dpi_scaled_size(1280),
            max_height=FontManager.get_dpi_scaled_size(960),
            parent=self.parent,
        )

    def _ensure_local_mod_project_ids(self, local_mods: list[Any]) -> None:
        """盡量補齊本地模組的 Modrinth project id / slug，供更新檢查使用。"""
        from .. import enhance_local_mod, resolve_modrinth_provider_record

        for local_mod in local_mods:
            current_project_id = str(getattr(local_mod, "platform_id", "") or "").strip()
            current_slug = str(getattr(local_mod, "platform_slug", "") or "").strip()
            if current_project_id and current_slug:
                continue
            enhanced = self.enhanced_mods_cache.get(getattr(local_mod, "filename", ""))

            def _enhance_local_mod_fallback_resolver() -> ProviderMetadataRecord | None:
                nonlocal enhanced
                if enhanced is None:
                    enhanced = enhance_local_mod(
                        getattr(local_mod, "filename", ""),
                        platform_id=getattr(local_mod, "platform_id", ""),
                        platform_slug=getattr(local_mod, "platform_slug", ""),
                        local_name=getattr(local_mod, "name", ""),
                    )
                    if enhanced:
                        self.enhanced_mods_cache[getattr(local_mod, "filename", "")] = enhanced
                if not enhanced:
                    return None
                return ProviderMetadataRecord.from_values(
                    project_id=str(getattr(enhanced, "project_id", "") or "").strip(),
                    slug=str(getattr(enhanced, "slug", "") or "").strip(),
                    project_name=str(getattr(enhanced, "name", "") or "").strip(),
                )

            ensured = ensure_local_mod_provider_record(
                platform_id=current_project_id,
                platform_slug=current_slug,
                project_name=str(getattr(local_mod, "name", "") or "").strip(),
                identifier_resolver=resolve_modrinth_provider_record,
                fallback_resolver=_enhance_local_mod_fallback_resolver,
            )
            if ensured.record.project_id or ensured.record.slug:
                apply_provider_metadata(local_mod, ensured.record)
                self._cache_local_provider_metadata(local_mod, enhanced, provider_record=ensured.record)

    def _cache_local_provider_metadata(
        self, mod: Any, enhanced: Any | None = None, *, provider_record: ProviderMetadataRecord | None = None
    ) -> None:
        """將本地模組已解析出的 provider metadata 回寫到索引。"""
        manager = self.mod_manager
        if not manager:
            return
        file_path_raw = str(getattr(mod, "file_path", "") or "").strip()
        if not file_path_raw:
            return
        normalized_record = provider_record or ProviderMetadataRecord.from_values(
            project_id=str(getattr(enhanced, "project_id", "") or getattr(mod, "platform_id", "") or "").strip(),
            slug=str(getattr(enhanced, "slug", "") or getattr(mod, "platform_slug", "") or "").strip(),
            project_name=str(getattr(enhanced, "name", "") or getattr(mod, "name", "") or "").strip(),
        )
        apply_provider_metadata(mod, normalized_record)
        # 回寫已增強的 provider metadata 並帶上來源，以便記錄 resolved_at 時間戳
        cache_provider_metadata_record(
            manager.index_manager,
            Path(file_path_raw),
            normalized_record,
            metadata_source="scan_detect",
        )

    def _prepare_local_update_review_entries(
        self,
        update_plan: LocalModUpdatePlan,
        root_enabled_overrides: dict[str, bool] | None = None,
        advisory_enabled_overrides: dict[tuple[str, tuple[str, str]], bool] | None = None,
    ) -> list[LocalUpdateReviewEntry]:
        """建立本地模組更新 review 項目，並依序模擬更新後狀態避免重複依賴。"""
        from .. import build_required_dependency_install_plan

        minecraft_version, loader_type, loader_version = self._get_current_modrinth_context()
        simulated_installed_mods = list(self._get_current_installed_mods())
        review_entries: list[LocalUpdateReviewEntry] = []
        for candidate in update_plan.candidates:
            root_key = str(candidate.project_id or "").strip()
            dependency_plan = SimpleNamespace(items=[], unresolved_required=[])
            blocking_reasons = [*list(getattr(candidate, "hard_errors", []) or [])]
            non_blocking_warnings = self._dedupe_review_messages(
                [
                    *list(getattr(candidate, "current_issues", []) or []),
                    *list(getattr(candidate, "dependency_issues", []) or []),
                ]
            )
            target_version = getattr(candidate, "target_version", None)
            cached_root_enabled: bool | None = None
            if getattr(candidate, "update_available", False) and target_version is not None:
                cached_dependency_plan, cached_root_enabled = self._load_local_dependency_plan_snapshot(candidate)
                if cached_dependency_plan is not None:
                    dependency_plan = cached_dependency_plan
                else:
                    dependency_plan = build_required_dependency_install_plan(
                        target_version,
                        minecraft_version=minecraft_version,
                        loader=loader_type,
                        loader_version=loader_version,
                        installed_mods=simulated_installed_mods,
                        root_project_id=candidate.project_id,
                        root_project_name=candidate.project_name,
                    )
                    self._cache_local_dependency_plan_snapshot(
                        candidate,
                        dependency_plan,
                        root_enabled=bool(getattr(candidate, "actionable", False)) and (not bool(blocking_reasons)),
                    )
                self._apply_review_advisory_enabled_overrides(dependency_plan, root_key, advisory_enabled_overrides)
                blocking_reasons.extend(list(getattr(dependency_plan, "unresolved_required", []) or []))
            default_enabled = bool(getattr(candidate, "actionable", False)) and (not blocking_reasons)
            if not blocking_reasons and root_enabled_overrides is None and (cached_root_enabled is not None):
                default_enabled = cached_root_enabled
            effective_enabled = (
                root_enabled_overrides.get(root_key, default_enabled)
                if root_enabled_overrides is not None
                else default_enabled
            )
            review_entry = LocalUpdateReviewEntry(
                candidate=candidate,
                dependency_plan=dependency_plan,
                blocking_reasons=blocking_reasons,
                enabled=effective_enabled,
                provider=str(getattr(target_version, "provider", "modrinth") or "modrinth")
                if target_version
                else "modrinth",
                version_type=str(getattr(target_version, "version_type", "") or "") if target_version else "",
                date_published=str(getattr(target_version, "date_published", "") or "") if target_version else "",
                changelog=str(getattr(target_version, "changelog", "") or "") if target_version else "",
            )
            review_entry.warning_messages = self._collect_non_official_source_warning_messages(
                review_entry,
                enabled_only=True,
            )
            review_entries.append(review_entry)
            if non_blocking_warnings:
                existing_notes = list(getattr(candidate, "notes", []) or [])
                candidate.notes = self._dedupe_review_messages([*non_blocking_warnings, *existing_notes])
            if review_entry.actionable:
                self._append_enabled_dependency_simulations(simulated_installed_mods, dependency_plan)
                self._append_simulated_installed_mod(
                    simulated_installed_mods,
                    self._build_installed_mod_simulation_item(
                        candidate.project_id,
                        candidate.project_name,
                        candidate.target_filename or candidate.filename,
                        candidate.target_version_name,
                    ),
                )
        return review_entries

    def _format_local_update_review_text(self, review_entry: LocalUpdateReviewEntry) -> str:
        """格式化本地模組更新 review 內容。"""
        candidate = review_entry.candidate
        lines = [
            f"模組：{candidate.project_name}",
            f"來源：{self._format_review_provider_label(review_entry.provider)}",
            f"Metadata 來源：{self._format_metadata_source_label(getattr(candidate, 'metadata_source', ''))}",
            f"更新建議來源：{self._format_recommendation_source_label(getattr(candidate, 'recommendation_source', ''))}",
            f"更新建議可信度：{self._format_recommendation_confidence_label(getattr(candidate, 'recommendation_confidence', ''))}",
            f"目前版本：{candidate.current_version or '未知'}",
            f"推薦版本：{candidate.target_version_name or '查無可用版本'}",
        ]
        metadata_note = str(getattr(candidate, "metadata_note", "") or "").strip()
        if metadata_note:
            lines.append(f"Metadata 狀態：{metadata_note}")
        published_text = self._format_review_published_at(review_entry.date_published)
        if published_text:
            lines.append(f"發布時間：{published_text}")
        client_install_reminder = self._build_client_install_reminder_line(
            getattr(candidate, "server_side", ""), getattr(candidate, "client_side", "")
        )
        if client_install_reminder:
            lines.append(client_install_reminder)
        lines.append(f"執行狀態：{('已啟用' if review_entry.enabled else '已停用')}")
        lines.append(f"處理等級：{self._build_local_update_root_status_text(review_entry)}")
        if review_entry.blocking_reasons:
            self._append_review_section(lines, "需先處理：", review_entry.blocking_reasons, max_items=3)
        self._append_dependency_review_sections(lines, review_entry.dependency_plan, "更新時將一併安裝的必要依賴：")
        if review_entry.warning_messages:
            self._append_review_section(lines, "執行前提醒：", review_entry.warning_messages, max_items=3)
        notes = list(getattr(candidate, "notes", []) or [])
        warnings = list(getattr(getattr(candidate, "report", None), "warnings", []) or [])
        if warnings:
            self._append_review_section(lines, "提醒：", warnings, max_items=3)
        if notes:
            self._append_review_section(lines, "補充說明：", notes, max_items=2)
        changelog_text = self._summarize_review_changelog(review_entry.changelog)
        if changelog_text:
            lines.append("")
            lines.append("更新內容：")
            lines.append(changelog_text)
        self._append_plan_note_section(lines, getattr(review_entry, "dependency_plan", None))
        return "\n".join(lines)

    def _show_local_update_review_dialog(self, update_plan: LocalModUpdatePlan, scope_text: str) -> None:
        """顯示本地模組更新檢查結果。"""
        review_entries = self._prepare_local_update_review_entries(update_plan)
        if not review_entries:
            message = update_plan.notes[0] if update_plan.notes else f"{scope_text}目前沒有可更新或需處理的模組。"
            UIUtils.show_info("更新檢查", message, self.parent)
            return
        entry_map = {self._build_local_update_review_key(entry.candidate): entry for entry in review_entries}
        review_root_keys = set(entry_map)
        global_review_notes = self._collect_local_update_global_notes(update_plan, review_entries)

        def rebuild_update_review_entries() -> None:
            nonlocal review_entries, entry_map, review_root_keys
            self._persist_local_update_dependency_plan_snapshots(review_entries)
            root_keys = [self._build_local_update_review_key(entry.candidate) for entry in review_entries]
            root_enabled_overrides = self._collect_review_entry_enabled_overrides(review_entries, root_keys)
            advisory_enabled_overrides = self._collect_review_advisory_enabled_overrides(review_entries, root_keys)
            review_entries = self._prepare_local_update_review_entries(
                update_plan,
                root_enabled_overrides=root_enabled_overrides,
                advisory_enabled_overrides=advisory_enabled_overrides,
            )
            entry_map = {self._build_local_update_review_key(entry.candidate): entry for entry in review_entries}
            review_root_keys = set(entry_map)

        dialog = DialogUtils.create_toplevel_dialog(
            self.parent,
            "本地模組更新檢查",
            width=Sizes.DIALOG_LARGE_WIDTH,
            height=Sizes.DIALOG_LARGE_HEIGHT,
            make_modal=True,
            bind_icon=True,
            center_on_parent=True,
            delay_ms=250,
            min_width=1060,
            min_height=860,
            max_width=FontManager.get_dpi_scaled_size(1280),
            max_height=FontManager.get_dpi_scaled_size(980),
            native_window=True,
            use_transient_for_modal=False,
        )
        main_frame = ctk.CTkFrame(dialog)
        main_frame.pack(fill="both", expand=True, padx=Spacing.LARGE, pady=Spacing.LARGE)
        title = ctk.CTkLabel(
            main_frame,
            text="本地模組更新與相容性 Review",
            font=FontManager.get_font(size=FontSize.HEADING_LARGE, weight="bold"),
        )
        title.pack(anchor="w", padx=Spacing.MEDIUM, pady=(Spacing.MEDIUM, Spacing.SMALL))
        local_group_counts = self._count_local_update_review_groups(review_entries)
        subtitle = ctk.CTkLabel(
            main_frame,
            text=self._build_local_update_review_subtitle(
                scope_text,
                self._count_enabled_runnable_entries(review_entries),
                local_group_counts["blocked"],
                advisory_count=local_group_counts["advisory"],
                retryable_count=local_group_counts["retryable"],
                unknown_count=local_group_counts["unknown"],
                migrated_snapshot_count=self._dependency_snapshot_migration_totals.get("migrated", 0),
            ),
            font=FontManager.get_font(size=FontSize.SMALL_PLUS),
            text_color=Colors.TEXT_SECONDARY,
            justify="left",
            anchor="w",
            wraplength=FontManager.get_dpi_scaled_size(880),
        )
        subtitle.pack(fill="x", padx=Spacing.MEDIUM, pady=(0, Spacing.TINY))
        overview_label, tree_container = self._create_review_shared_ui(main_frame, 880)
        update_tree = ttk.Treeview(
            tree_container,
            columns=("run", "current", "target", "source", "status"),
            show="tree headings",
            height=Spacing.MEDIUM,
            style=TreeUtils.configure_treeview_list_style(
                "LocalUpdateList",
                body_font=FontManager.get_font(size=FontSize.INPUT),
                heading_font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
                rowheight=int(25 * FontManager.get_scale_factor()),
            ),
        )
        update_tree.heading("#0", text="模組")
        update_tree.column("#0", width=Sizes.SERVER_TREE_COL_NAME - 50, minwidth=170, anchor="w", stretch=False)
        update_tree.heading("run", text="套用")
        update_tree.column("run", width=Spacing.XXL, minwidth=48, anchor="center", stretch=False)
        update_tree.heading("current", text="目前版本")
        update_tree.column("current", width=Sizes.BUTTON_WIDTH_SECONDARY, minwidth=96, anchor="w", stretch=False)
        update_tree.heading("target", text="建議版本")
        update_tree.column("target", width=Sizes.SERVER_TREE_COL_LOADER + 5, minwidth=120, anchor="w", stretch=False)
        update_tree.heading("source", text="來源 / 識別")
        update_tree.column("source", width=Sizes.SERVER_TREE_COL_LOADER + 20, minwidth=130, anchor="w", stretch=False)
        update_tree.heading("status", text="檢查狀態")
        update_tree.column("status", width=Sizes.INPUT_WIDTH, minwidth=240, anchor="w", stretch=True)
        TreeUtils.bind_treeview_header_auto_fit(
            update_tree,
            include_tree_column=True,
            heading_font=FontManager.get_font(size=FontSize.LARGE, weight="bold"),
            body_font=FontManager.get_font(size=FontSize.INPUT),
            stretch_columns={"status"},
        )
        update_scroll = ttk.Scrollbar(tree_container, orient="vertical", command=update_tree.yview)
        update_tree.configure(yscrollcommand=update_scroll.set)
        update_tree.grid(row=0, column=0, sticky="nsew")
        update_scroll.grid(row=0, column=1, sticky="ns")
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        def refresh_update_tree() -> None:
            nodes = self._build_local_update_task_nodes(review_entries)
            self._render_review_task_tree(update_tree, nodes, column_count=5)

        summary_box = self._create_review_summary_box(main_frame, height=Sizes.SERVER_TREE_COL_LOADER)

        def refresh_update_status_banner() -> None:
            review_nodes = self._build_local_update_task_nodes(review_entries)
            enabled_count = self._count_enabled_runnable_entries(review_entries)
            local_group_counts = self._count_local_update_review_groups(review_entries)
            subtitle.configure(
                text=self._build_local_update_review_subtitle(
                    scope_text,
                    enabled_count,
                    local_group_counts["blocked"],
                    advisory_count=local_group_counts["advisory"],
                    retryable_count=local_group_counts["retryable"],
                    unknown_count=local_group_counts["unknown"],
                    migrated_snapshot_count=self._dependency_snapshot_migration_totals.get("migrated", 0),
                )
            )
            overview_label.configure(
                text=self._format_review_overview_text(
                    review_entries, review_nodes, action_label="更新", global_notes=global_review_notes
                )
            )

        def refresh_update_summary(_event=None) -> None:
            selected_key = self._get_selected_review_key(update_tree, review_root_keys)
            review_entry = entry_map.get(selected_key)
            if not review_entry:
                return
            summary_box.configure(state="normal")
            summary_box.delete("1.0", "end")
            summary_box.insert("1.0", self._format_local_update_review_text(review_entry))
            summary_box.configure(state="disabled")

        def toggle_update_selection(enabled: bool) -> None:
            self._toggle_review_selection(
                tree=update_tree,
                entry_map=entry_map,
                review_root_keys=review_root_keys,
                enabled=enabled,
                rebuild_entries=rebuild_update_review_entries,
                refresh_tree=refresh_update_tree,
                refresh_summary=refresh_update_summary,
                refresh_status_banner=refresh_update_status_banner,
                refresh_action_button=refresh_update_action_button,
            )

        def open_selected_update_project_page() -> None:
            selected_key = self._get_selected_review_key(update_tree, review_root_keys)
            review_entry = entry_map.get(selected_key)
            project_page_url = self._resolve_local_update_review_project_page_url(review_entry) if review_entry else ""
            self._open_project_page(project_page_url, dialog)

        update_tree.bind("<<TreeviewSelect>>", refresh_update_summary)
        refresh_update_tree()
        refresh_update_summary()
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x", padx=Spacing.MEDIUM, pady=(0, Spacing.SMALL))
        update_button = self._create_review_action_button(
            button_frame,
            text="",
            fg_color=Colors.BUTTON_SUCCESS,
            hover_color=Colors.BUTTON_SUCCESS_HOVER,
            command=lambda: self._install_local_update_review_entries(dialog, review_entries),
            bold=True,
        )
        self._create_review_action_button(
            button_frame,
            text="啟用選取項目",
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            command=lambda: toggle_update_selection(True),
            padx=(Spacing.SMALL_PLUS, 0),
        )
        self._create_review_action_button(
            button_frame,
            text="停用選取項目",
            fg_color=Colors.BUTTON_SECONDARY,
            hover_color=Colors.BUTTON_SECONDARY_HOVER,
            command=lambda: toggle_update_selection(False),
            padx=(Spacing.SMALL_PLUS, 0),
        )
        project_page_button = self._create_review_action_button(
            button_frame,
            text="開啟專案頁面",
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            command=open_selected_update_project_page,
            padx=(Spacing.SMALL_PLUS, 0),
        )

        def refresh_update_action_button() -> None:
            self._configure_review_action_button(update_button, review_entries, "更新")

        def refresh_update_project_page_button(_event=None) -> None:
            selected_key = self._get_selected_review_key(update_tree, review_root_keys)
            review_entry = entry_map.get(selected_key)
            project_page_button.configure(
                state="normal"
                if review_entry and self._resolve_local_update_review_project_page_url(review_entry)
                else "disabled"
            )

        self._create_review_action_button(
            button_frame,
            text="關閉",
            fg_color=Colors.BUTTON_INFO,
            hover_color=Colors.BUTTON_INFO_HOVER,
            command=dialog.destroy,
            side="right",
        )
        update_tree.bind("<<TreeviewSelect>>", refresh_update_project_page_button, add="+")
        refresh_update_status_banner()
        refresh_update_action_button()
        refresh_update_project_page_button()
        DialogUtils.schedule_toplevel_layout_refresh(
            dialog,
            min_width=1060,
            min_height=860,
            max_width=FontManager.get_dpi_scaled_size(1280),
            max_height=FontManager.get_dpi_scaled_size(980),
            parent=self.parent,
        )

    def check_local_mod_updates(self) -> None:
        """檢查本地模組是否有可用更新與相容性問題。"""
        manager = self.mod_manager
        if not self.current_server or not manager:
            UIUtils.show_warning("警告", "請先選擇伺服器後再檢查模組更新", self.parent)
            return
        selected_mod_ids = self._capture_selected_mod_ids()
        minecraft_version, loader_type, loader_version = self._get_current_modrinth_context()

        def check_task() -> None:
            try:
                self.update_status_safe("正在掃描本地模組更新與相容性...")
                self.update_progress_safe(0.0)
                installed_mods = manager.get_mod_list()
                target_mods = installed_mods
                scope_text = "全部模組"
                if selected_mod_ids:
                    target_mods = [
                        mod
                        for mod in installed_mods
                        if mod.filename.replace(".jar.disabled", "").replace(".jar", "") in selected_mod_ids
                    ]
                    scope_text = f"已選取的 {len(target_mods)} 個模組"
                last_hash_progress_percent = -1

                def on_hash_progress(completed: int, total: int) -> None:
                    nonlocal last_hash_progress_percent
                    if total <= 0:
                        return
                    fraction = max(0.0, min(1.0, completed / total))
                    progress_percent = int(fraction * 100)
                    if progress_percent == last_hash_progress_percent:
                        return
                    last_hash_progress_percent = progress_percent
                    self.update_progress_safe(fraction)
                    self.update_status_safe(f"正在計算本地模組雜湊... {completed}/{total}")

                update_plan = build_local_mod_update_plan(
                    target_mods,
                    minecraft_version=minecraft_version,
                    loader=loader_type,
                    loader_version=loader_version,
                    hash_progress_callback=on_hash_progress,
                )
                self._persist_local_update_plan_metadata(update_plan)
                self._latest_local_update_plan = update_plan
                self.update_progress_safe(1.0)
                self.update_status_safe(
                    f"更新檢查完成：{update_plan.actionable_count} 個可更新，{len(update_plan.candidates)} 個需 review"
                )
                self.ui_queue.put(lambda: self._show_local_update_review_dialog(update_plan, scope_text))
            except Exception as e:
                logger.error(f"檢查本地模組更新失敗: {e}\n{traceback.format_exc()}")
                self.update_progress_safe(0)
                self.update_status_safe(f"檢查本地模組更新失敗: {e}")
                self.ui_queue.put(lambda msg=str(e): UIUtils.show_error("更新檢查失敗", msg, self.parent))

        TaskUtils.run_async(check_task)


__all__ = ["ModManagementReviewMixin"]
