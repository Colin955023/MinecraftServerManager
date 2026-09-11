"""Review 執行前確認提示組裝"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.utils import (
    LOCAL_UPDATE_PROMPT_ADVISORY_LINE_TEMPLATE,
    LOCAL_UPDATE_PROMPT_BLOCKED_LINE_TEMPLATE,
    LOCAL_UPDATE_PROMPT_RETRYABLE_LINE_TEMPLATE,
    LOCAL_UPDATE_PROMPT_UNKNOWN_LINE_TEMPLATE,
    ONLINE_INSTALL_PROMPT_ADVISORY_LINE_TEMPLATE,
    ONLINE_INSTALL_PROMPT_BLOCKED_LINE_TEMPLATE,
    build_non_official_source_warning_message,
    get_non_official_download_host,
)

from .mod_presentation import format_provider_label
from .review_dependency import get_selected_dependency_install_items, get_sorted_dependency_review_items
from .review_formatting import dedupe_review_messages
from .review_grouping import (
    count_local_update_review_groups,
    count_online_install_review_groups,
)
from .review_state import LocalUpdateReviewEntry, PendingInstallReviewEntry


class ReviewPrompts:
    """Review 執行前確認提示組裝"""

    @staticmethod
    def iter_download_source_records(review_entry: Any, *, selected_only: bool) -> list[tuple[str, str, str]]:
        """
        列出根項目與依賴的下載來源紀錄

        Args:
            review_entry: Review 項目
            selected_only: 是否只保留已選取依賴

        Returns:
            顯示名稱、網址與 provider 的紀錄
        """
        records: list[tuple[str, str, str]] = []
        if isinstance(review_entry, PendingInstallReviewEntry):
            pending = getattr(review_entry, "pending", None)
            version = getattr(pending, "version", None)
            primary_file = getattr(version, "primary_file", None) or {}
            version_name = str(
                getattr(version, "display_name", "") or getattr(version, "version_number", "") or ""
            ).strip()
            label = str(getattr(pending, "project_name", "") or "未知模組").strip() or "未知模組"
            records.append(
                (
                    f"{label} ({version_name})" if version_name else label,
                    str(primary_file.get("url", "") or "").strip(),
                    review_entry.provider,
                )
            )
        elif isinstance(review_entry, LocalUpdateReviewEntry):
            candidate = getattr(review_entry, "candidate", None)
            version_name = str(getattr(candidate, "target_version_name", "") or "").strip()
            label = str(getattr(candidate, "project_name", "") or "未知模組").strip() or "未知模組"
            records.append(
                (
                    f"{label} ({version_name})" if version_name else label,
                    str(getattr(candidate, "download_url", "") or "").strip(),
                    review_entry.provider,
                )
            )
        plan = getattr(review_entry, "dependency_plan", None)
        items = (
            get_selected_dependency_install_items(plan, review_entry.selected_dependency_keys)
            if selected_only
            else get_sorted_dependency_review_items(plan)
        )
        for item in items:
            provider = str(getattr(item, "provider", "") or review_entry.provider or "modrinth").strip()
            label = str(getattr(item, "project_name", "") or "未知依賴").strip() or "未知依賴"
            records.append((f"{label}（依賴）", str(getattr(item, "download_url", "") or "").strip(), provider))
        return records

    @staticmethod
    def collect_non_official_source_warning_messages(review_entry: Any, *, selected_only: bool) -> list[str]:
        """
        收集非官方下載來源的警告訊息

        Args:
            review_entry: Review 項目
            selected_only: 是否只檢查已選取依賴

        Returns:
            去重後的警告訊息
        """
        warnings = [
            build_non_official_source_warning_message(
                label, url, provider, provider_label=format_provider_label(provider)
            )
            for label, url, provider in ReviewPrompts.iter_download_source_records(
                review_entry, selected_only=selected_only
            )
        ]
        return dedupe_review_messages([warning for warning in warnings if warning])

    @staticmethod
    def build_non_official_source_confirmation_prompt(review_entries: list[Any], *, action_label: str) -> str:
        """
        建立非官方來源的繼續確認提示

        Args:
            review_entries: Review 項目清單
            action_label: 動作名稱

        Returns:
            確認提示或空字串
        """
        lines = [
            f"- {label}：{host}（非 {format_provider_label(provider)} 官方網域）"
            for entry in review_entries
            for label, url, provider in ReviewPrompts.iter_download_source_records(entry, selected_only=True)
            if (host := get_non_official_download_host(url, provider))
        ]
        lines = dedupe_review_messages(lines)
        return (
            ""
            if not lines
            else f"本次{action_label}包含非官方下載來源，系統已同步記錄風險日誌：\n"
            + "\n".join(lines)
            + "\n\n這些檔案不會從官方 provider 網域下載，請確認你信任這些來源\n\n是否仍要繼續？"
        )

    @staticmethod
    def build_execution_prompt(
        review_entries: list[Any],
        *,
        counts: dict[str, int],
        summary_title: str,
        continue_action_template: str,
        required_group_keys: Iterable[str],
        summary_templates: Iterable[tuple[str, str]],
    ) -> str | None:
        """
        依群組統計建立執行前確認提示

        Args:
            review_entries: Review 項目清單
            counts: 各群組數量
            summary_title: 摘要標題
            continue_action_template: 後續動作樣板
            required_group_keys: 需要確認的群組鍵
            summary_templates: 群組摘要樣板

        Returns:
            確認提示或 None
        """
        actionable_count = sum(1 for entry in review_entries if bool(getattr(entry, "actionable", False)))
        if actionable_count <= 0 or not any(counts.get(key, 0) > 0 for key in required_group_keys):
            return None
        summary_lines = [
            template.format(count=counts[key]) for key, template in summary_templates if counts.get(key, 0)
        ]
        return (
            None
            if not summary_lines
            else f"{summary_title}：\n"
            + "\n".join(summary_lines)
            + f"\n\n將繼續{continue_action_template.format(count=actionable_count)}\n\n是否繼續？"
        )

    @staticmethod
    def build_online_install_execution_prompt(review_entries: list[PendingInstallReviewEntry]) -> str | None:
        """
        建立線上安裝的執行前確認提示

        Args:
            review_entries: 線上安裝 Review 項目

        Returns:
            確認提示或 None
        """
        return ReviewPrompts.build_execution_prompt(
            review_entries,
            counts=count_online_install_review_groups(review_entries),
            summary_title="本次安裝摘要",
            continue_action_template="安裝其餘 {count} 個可安裝項目",
            required_group_keys=("blocked",),
            summary_templates=(
                ("advisory", ONLINE_INSTALL_PROMPT_ADVISORY_LINE_TEMPLATE),
                ("blocked", ONLINE_INSTALL_PROMPT_BLOCKED_LINE_TEMPLATE),
            ),
        )

    @staticmethod
    def build_local_update_execution_prompt(review_entries: list[LocalUpdateReviewEntry]) -> str | None:
        """
        建立本地更新的執行前確認提示

        Args:
            review_entries: 本地更新 Review 項目

        Returns:
            確認提示或 None
        """
        return ReviewPrompts.build_execution_prompt(
            review_entries,
            counts=count_local_update_review_groups(review_entries),
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


__all__ = ["ReviewPrompts"]
