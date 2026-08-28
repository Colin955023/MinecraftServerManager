"""Review 純文字、標籤與版本欄位格式化工具"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.models import LocalModUpdatePlan
from src.utils import (
    LOCAL_UPDATE_REVIEW_PRECHECK_NOTE,
    METADATA_SOURCE_LABELS,
    METADATA_SOURCE_SHORT_LABELS,
    ONLINE_REVIEW_PRECHECK_NOTE,
    RECOMMENDATION_CONFIDENCE_LABELS,
    RECOMMENDATION_SOURCE_LABELS,
    RECOMMENDATION_SOURCE_SHORT_LABELS,
)

from .mod_presentation import format_provider_label, resolve_project_page_url, summarize_text
from .review_dependency import count_review_nodes
from .review_selection import count_selected_runnable_entries
from .review_state import LocalUpdateReviewEntry, PendingInstallReviewEntry


def mask_redundant_review_values(parent_values: tuple[str, ...], child_values: tuple[str, ...]) -> tuple[str, ...]:
    """
    將與父節點相同的欄位值改為佔位文字

    Args:
        parent_values: 父節點各欄位的值
        child_values: 子節點各欄位的值

    Returns:
        相同欄位改為「-」後的子節點值
    """
    masked_values: list[str] = []
    for index, raw_child in enumerate(child_values):
        child_text = str(raw_child or "").strip() or "-"
        parent_text = str(parent_values[index] if index < len(parent_values) else "").strip() or "-"
        if child_text != "-" and child_text == parent_text:
            masked_values.append("-")
        else:
            masked_values.append(child_text)
    return tuple(masked_values)


def format_local_update_source_text(review_entry: LocalUpdateReviewEntry) -> str:
    """
    格式化本地更新項目的來源與推薦來源文字

    Args:
        review_entry: 包含 provider 與候選版本來源資訊的本地更新項目

    Returns:
        以分隔符串接的來源標籤文字
    """
    segments = [format_provider_label(review_entry.provider)]
    metadata_source = str(getattr(review_entry.candidate, "metadata_source", "") or "").strip()
    recommendation_source = str(getattr(review_entry.candidate, "recommendation_source", "") or "").strip()
    if metadata_source:
        segments.append(format_metadata_source_short_label(metadata_source))
    if recommendation_source:
        segments.append(format_recommendation_source_short_label(recommendation_source))
    return "｜".join(segments)


def format_review_overview_text(
    entries: list[Any],
    nodes: list[Any],
    *,
    action_label: str,
    global_notes: list[str] | None = None,
    deduped_dependency_count: int = 0,
) -> str:
    """
    格式化 Review 工作樹的數量摘要與預檢提示

    Args:
        entries: Review 根項目清單
        nodes: 工作樹節點清單
        action_label: 摘要中要顯示的後續動作名稱
        global_notes: 要去重後加入摘要的全域提示
        deduped_dependency_count: 已合併的重複依賴數量

    Returns:
        顯示根工作、依賴、問題、提醒與未選取項目的摘要文字
    """
    root_count = len(entries)
    dependency_count = count_review_nodes(nodes, "dependency")
    issue_count = count_review_nodes(nodes, "issue")
    warning_count = count_review_nodes(nodes, "warning")
    selected_count = count_selected_runnable_entries(entries)
    unselected_count = sum(
        1 for entry in entries if getattr(entry, "runnable", False) and not getattr(entry, "selected", False)
    )
    segments = [f"Task graph：{root_count} 個根工作", f"目前將{action_label} {selected_count} 個根項目"]
    if dependency_count:
        segments.append(f"{dependency_count} 個依賴")
    if issue_count:
        segments.append(f"{issue_count} 個待處理")
    if warning_count:
        segments.append(f"{warning_count} 個提醒")
    if deduped_dependency_count:
        segments.append(f"已合併 {deduped_dependency_count} 個重複依賴")
    if unselected_count:
        segments.append(f"另有 {unselected_count} 個未選取項目")
    notes = dedupe_review_messages(list(global_notes or []))
    if notes:
        segments.append("預檢：" + summarize_text(notes[0], 40))
    return "｜".join(segments)


def resolve_pending_install_review_project_page_url(review_entry: PendingInstallReviewEntry) -> str:
    """
    解析待安裝線上 Review 項目的專案頁面網址

    Args:
        review_entry: 包含待安裝模組資料的 Review 項目

    Returns:
        待安裝模組專案頁面網址，資料不存在或無法解析時回傳空字串
    """
    pending = getattr(review_entry, "pending", None)
    return (
        ""
        if pending is None
        else resolve_project_page_url(
            urls=(getattr(pending, "homepage_url", ""), getattr(pending, "source_url", "")),
            identifiers=(getattr(pending, "project_id", ""),),
        )
    )


def resolve_local_update_review_project_page_url(review_entry: LocalUpdateReviewEntry) -> str:
    """
    解析本地更新 Review 項目的專案頁面網址

    Args:
        review_entry: 包含本地模組與更新候選資料的 Review 項目

    Returns:
        更新候選專案頁面網址，無法解析時回傳空字串
    """
    candidate = getattr(review_entry, "candidate", None)
    local_mod = getattr(candidate, "local_mod", None)
    return (
        ""
        if candidate is None
        else resolve_project_page_url(
            identifiers=(
                getattr(local_mod, "platform_slug", ""),
                getattr(candidate, "project_id", ""),
                getattr(local_mod, "platform_id", ""),
            )
        )
    )


def format_metadata_source_label(source: str | None) -> str:
    """
    將 metadata 來源識別值轉為完整顯示標籤

    Args:
        source: metadata 來源識別值，可為 None

    Returns:
        對應的完整來源標籤，無對應值時回傳「未知」
    """
    return METADATA_SOURCE_LABELS.get(str(source or "").strip().lower(), "未知")


def format_metadata_source_short_label(source: str | None) -> str:
    """
    將 metadata 來源識別值轉為短顯示標籤

    Args:
        source: metadata 來源識別值，可為 None

    Returns:
        對應的短來源標籤，無對應值時回傳「未知」
    """
    return METADATA_SOURCE_SHORT_LABELS.get(str(source or "").strip().lower(), "未知")


def format_recommendation_source_label(source: str | None) -> str:
    """
    將更新推薦來源識別值轉為完整顯示標籤

    Args:
        source: 更新推薦來源識別值，可為 None

    Returns:
        對應的完整推薦來源標籤，無對應值時回傳「未知」
    """
    return RECOMMENDATION_SOURCE_LABELS.get(str(source or "").strip().lower(), "未知")


def format_recommendation_source_short_label(source: str | None) -> str:
    """
    將更新推薦來源識別值轉為短顯示標籤

    Args:
        source: 更新推薦來源識別值，可為 None

    Returns:
        對應的短推薦來源標籤，無對應值時回傳「未知」
    """
    return RECOMMENDATION_SOURCE_SHORT_LABELS.get(str(source or "").strip().lower(), "未知")


def format_recommendation_confidence_label(confidence: str | None) -> str:
    """
    將更新推薦可信度識別值轉為顯示標籤

    Args:
        confidence: 更新推薦可信度識別值，可為 None

    Returns:
        對應的可信度標籤，無對應值時回傳「未知」
    """
    return RECOMMENDATION_CONFIDENCE_LABELS.get(str(confidence or "").strip().lower(), "未知")


def dedupe_review_messages(messages: list[str] | tuple[str, ...]) -> list[str]:
    """
    移除空白與重複的 Review 訊息並保留原順序

    Args:
        messages: 要整理的訊息清單或 tuple

    Returns:
        去除空白項目與重複內容後的訊息清單
    """
    deduped: list[str] = []
    seen: set[str] = set()
    for message in messages:
        normalized = str(message or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def summarize_review_messages(messages: list[str] | tuple[str, ...], max_items: int = 3) -> list[str]:
    """
    去重並限制 Review 訊息顯示數量

    Args:
        messages: 要整理的訊息清單或 tuple
        max_items: 最多直接顯示的訊息數量

    Returns:
        摘要訊息清單，超出數量時追加其餘項目提示
    """
    deduped = dedupe_review_messages(messages)
    if len(deduped) <= max_items:
        return deduped
    return [*deduped[:max_items], f"其餘 {len(deduped) - max_items} 項請於工作樹查看"]


def format_required_by_list(required_by: list[str]) -> str:
    """
    格式化依賴要求者名稱清單

    Args:
        required_by: 要求此依賴的項目名稱清單

    Returns:
        以頓號串接的名稱，超過三項時顯示前三項及總數
    """
    deduped = dedupe_review_messages(required_by)
    if not deduped:
        return ""
    if len(deduped) <= 3:
        return "、".join(deduped)
    return f"{'、'.join(deduped[:3])} 等 {len(deduped)} 個項目"


def format_completion_notes(messages: list[str], max_items: int = 4) -> str:
    """
    格式化完成後要顯示的提醒訊息

    Args:
        messages: 完成流程產生的提醒訊息清單
        max_items: 最多直接顯示的提醒數量

    Returns:
        帶有提醒標題的多行文字，沒有訊息時回傳空字串
    """
    deduped = dedupe_review_messages(messages)
    if not deduped:
        return ""
    preview = deduped[:max_items]
    suffix = f"\n另有 {len(deduped) - len(preview)} 則提醒" if len(deduped) > len(preview) else ""
    return "\n提醒：\n- " + "\n- ".join(preview) + suffix


def build_review_subtitle(
    *,
    prefix_segments: list[str],
    count_segments: list[tuple[int, str]] | tuple[tuple[int, str], ...],
    blocked_count: int,
    blocked_label: str,
    migrated_snapshot_count: int = 0,
    migrated_snapshot_label: str = "快照遷移",
) -> str:
    """
    依各類數量組合 Review 子標題

    Args:
        prefix_segments: 子標題開頭的固定文字片段
        count_segments: 由數量與標籤組成的可選片段
        blocked_count: 被阻擋項目的數量
        blocked_label: 阻擋數量的顯示標籤
        migrated_snapshot_count: 自快照遷移的項目數量
        migrated_snapshot_label: 快照遷移數量的顯示標籤

    Returns:
        以分隔符串接的 Review 子標題
    """
    segments = list(prefix_segments)
    for count, label in count_segments:
        if count:
            segments.append(f"{label} {count} 項")
    if migrated_snapshot_count:
        segments.append(f"{migrated_snapshot_label} {migrated_snapshot_count} 項")
    if blocked_count:
        segments.append(f"{blocked_label} {blocked_count} 項")
    return "｜".join(segments)


def append_review_section(lines: list[str], title: str, messages: list[str], *, max_items: int) -> None:
    """
    將整理後的 Review 訊息區段追加到文字清單

    Args:
        lines: 要追加顯示內容的文字清單
        title: 區段標題
        messages: 要摘要的訊息清單
        max_items: 最多顯示的訊息數量
    """
    summarized = summarize_review_messages(messages, max_items=max_items)
    if not summarized:
        return
    lines.append("")
    lines.append(title)
    lines.extend(f"- {item}" for item in summarized)


def append_plan_note_section(lines: list[str], dependency_plan: Any, *, max_items: int = 2) -> None:
    """
    將依賴計畫的備註以摘要區段追加到文字清單

    Args:
        lines: 要追加顯示內容的文字清單
        dependency_plan: 提供 notes 屬性的依賴計畫
        max_items: 最多顯示的備註數量
    """
    append_review_section(
        lines,
        "預檢補充：",
        dedupe_review_messages(list(getattr(dependency_plan, "notes", []) or [])),
        max_items=max_items,
    )


class ReviewFormattingMixin:
    """Review 全域提示與摘要狀態格式化"""

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
        return f"依賴快照遷移觀測：檢查 {checked_count}、自動遷移 {migrated_count}、成功回放 {replayed_count}" + (
            f"、回放失敗改重建 {fallback_rebuild_count}" if fallback_rebuild_count else ""
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
        return dedupe_review_messages(notes)

    def _collect_online_review_global_notes(self, review_entries: list[PendingInstallReviewEntry]) -> list[str]:
        return self._collect_review_global_notes(
            base_notes=[ONLINE_REVIEW_PRECHECK_NOTE], review_entries=review_entries
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


__all__ = [
    "ReviewFormattingMixin",
    "append_plan_note_section",
    "append_review_section",
    "dedupe_review_messages",
    "format_completion_notes",
    "format_local_update_source_text",
    "format_metadata_source_label",
    "format_recommendation_confidence_label",
    "format_recommendation_source_label",
    "format_required_by_list",
    "format_review_overview_text",
    "mask_redundant_review_values",
    "resolve_local_update_review_project_page_url",
    "resolve_pending_install_review_project_page_url",
]
