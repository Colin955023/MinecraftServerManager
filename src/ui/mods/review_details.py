"""Review root detail 文字；只由 workflow 與 internal tests 使用"""

from __future__ import annotations

from src.models import LocalUpdateReviewEntry, PendingInstallReviewEntry
from src.ui import (
    append_dependency_review_sections,
    append_plan_note_section,
    append_review_section,
    build_client_install_reminder_line,
    build_online_review_root_status_text,
    build_review_root_status_text,
    count_dependency_plan_items,
    dedupe_review_messages,
    format_metadata_source_label,
    format_online_version_report,
    format_provider_label,
    format_published_at,
    format_recommendation_confidence_label,
    format_recommendation_source_label,
    get_local_update_group_status_label,
    get_local_update_review_group_key,
    get_online_install_group_status_label,
    get_online_install_review_group_key,
    is_optional_dependency_item,
    summarize_changelog,
)


def build_pending_install_summary_lines(review_entry: PendingInstallReviewEntry) -> list[str]:
    """
    建立線上安裝 root 的精簡摘要行

    Args:
        review_entry: 已完成依賴與相容性分析的安裝項目

    Returns:
        可直接加入詳細資訊區的文字行
    """
    lines = [f"摘要：{build_online_review_root_status_text(review_entry)}"]
    dependency_plan = review_entry.dependency_plan
    auto_count, optional_count = count_dependency_plan_items(dependency_plan)
    if auto_count:
        lines.append(f"- 將自動補裝 {auto_count} 個必要依賴")
    if optional_count:
        enabled_optional = sum(
            1
            for item in list(getattr(dependency_plan, "advisory_items", []) or [])
            if is_optional_dependency_item(item) and bool(getattr(item, "enabled", False))
        )
        lines.append(f"- 可選依賴 {optional_count} 項（已選 {enabled_optional} 項）")
    if review_entry.blocking_reasons:
        lines.append(f"- 目前有 {len(dedupe_review_messages(review_entry.blocking_reasons))} 個阻擋原因需先處理")
    elif review_entry.warning_messages:
        lines.append(f"- 目前有 {len(dedupe_review_messages(review_entry.warning_messages))} 個提醒需留意")
    return lines


def format_pending_install_review_text(review_entry: PendingInstallReviewEntry) -> str:
    """
    格式化線上安裝項目的完整 Review 詳細資訊

    Args:
        review_entry: 線上安裝 Review 項目

    Returns:
        包含版本、依賴、阻擋與提醒的多行文字
    """
    lines = [format_online_version_report(review_entry.pending.version, review_entry.report), ""]
    lines.extend(build_pending_install_summary_lines(review_entry))
    reminder = build_client_install_reminder_line(review_entry.pending.server_side, review_entry.pending.client_side)
    if reminder:
        lines.append(reminder)
    lines.extend(
        [
            "",
            f"執行狀態：{('已啟用' if review_entry.enabled else '已停用')}",
            "處理等級：" + get_online_install_group_status_label(get_online_install_review_group_key(review_entry)),
        ]
    )
    append_dependency_review_sections(lines, review_entry.dependency_plan, "將自動安裝的必要依賴：")
    if review_entry.blocking_reasons:
        append_review_section(lines, "需先處理：", review_entry.blocking_reasons, max_items=3)
    elif review_entry.warning_messages:
        append_review_section(lines, "安裝前提醒：", review_entry.warning_messages, max_items=3)
    append_plan_note_section(lines, review_entry.dependency_plan)
    return "\n".join(lines)


def format_local_update_review_text(review_entry: LocalUpdateReviewEntry) -> str:
    """
    格式化本地更新項目的完整 Review 詳細資訊

    Args:
        review_entry: 本地更新 Review 項目

    Returns:
        包含版本、metadata、依賴與警告的多行文字
    """
    candidate = review_entry.candidate
    lines = [
        f"模組：{candidate.project_name}",
        f"來源：{format_provider_label(review_entry.provider)}",
        f"Metadata 來源：{format_metadata_source_label(getattr(candidate, 'metadata_source', ''))}",
        "更新建議來源：" + format_recommendation_source_label(getattr(candidate, "recommendation_source", "")),
        "更新建議可信度："
        + format_recommendation_confidence_label(getattr(candidate, "recommendation_confidence", "")),
        f"目前版本：{candidate.current_version or '未知'}",
        f"推薦版本：{candidate.target_version_name or '查無可用版本'}",
    ]
    metadata_note = str(getattr(candidate, "metadata_note", "") or "").strip()
    if metadata_note:
        lines.append(f"Metadata 狀態：{metadata_note}")
    published_text = format_published_at(review_entry.date_published)
    if published_text:
        lines.append(f"發布時間：{published_text}")
    reminder = build_client_install_reminder_line(
        getattr(candidate, "server_side", ""), getattr(candidate, "client_side", "")
    )
    if reminder:
        lines.append(reminder)
    lines.extend(
        [
            f"執行狀態：{('已啟用' if review_entry.enabled else '已停用')}",
            "處理等級："
            + build_review_root_status_text(
                review_entry,
                group_key_getter=get_local_update_review_group_key,
                group_status_getter=get_local_update_group_status_label,
            ),
        ]
    )
    if review_entry.blocking_reasons:
        append_review_section(lines, "需先處理：", review_entry.blocking_reasons, max_items=3)
    append_dependency_review_sections(lines, review_entry.dependency_plan, "更新時將一併安裝的必要依賴：")
    if review_entry.warning_messages:
        append_review_section(lines, "執行前提醒：", review_entry.warning_messages, max_items=3)
    warnings = list(getattr(getattr(candidate, "report", None), "warnings", []) or [])
    if warnings:
        append_review_section(lines, "提醒：", warnings, max_items=3)
    notes = list(getattr(candidate, "notes", []) or [])
    if notes:
        append_review_section(lines, "補充說明：", notes, max_items=2)
    changelog = summarize_changelog(review_entry.changelog)
    if changelog:
        lines.extend(["", "更新內容：", changelog])
    append_plan_note_section(lines, review_entry.dependency_plan)
    return "\n".join(lines)


__all__ = ["format_local_update_review_text", "format_pending_install_review_text"]
