"""Review 項目的群組分類、統計與顯示文字"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from src.utils import (
    METADATA_SOURCE_STALE_PROVIDER,
    METADATA_SOURCE_UNRESOLVED,
    RECOMMENDATION_CONFIDENCE_ADVISORY,
    RECOMMENDATION_CONFIDENCE_RETRYABLE,
    RECOMMENDATION_SOURCE_METADATA_UNRESOLVED,
    RECOMMENDATION_SOURCE_STALE_METADATA,
)

from .mod_presentation import format_provider_label
from .review_dependency import (
    build_dependency_review_key,
    build_dependency_status_text,
    collect_dependency_required_by,
    count_dependency_plan_items,
    is_optional_dependency_item,
)
from .review_formatting import (
    dedupe_review_messages,
    format_local_update_source_text,
    format_required_by_list,
    mask_redundant_review_values,
)
from .review_state import LocalUpdateReviewEntry, PendingInstallReviewEntry, ReviewTaskNode


def build_pending_install_review_key(project_id: str, version_id: str) -> str:
    """
    建立線上安裝 Review 項目的穩定根鍵

    Args:
        project_id: 線上模組的 provider project ID
        version_id: 要安裝的版本 ID

    Returns:
        由 project ID 與 version ID 組成的穩定鍵
    """
    return f"{str(project_id or '').strip()}::{str(version_id or '').strip()}"


def get_online_install_review_group_key(entry: PendingInstallReviewEntry) -> str:
    """
    依線上安裝項目的狀態分類群組鍵

    Args:
        entry: 要分類的線上安裝 Review 項目

    Returns:
        selected、advisory、unselected 或 blocked 群組鍵
    """
    if not bool(getattr(entry, "runnable", False)):
        return "blocked"
    if not bool(getattr(entry, "selected", False)):
        return "unselected"
    if list(getattr(entry, "warning_messages", []) or []):
        return "advisory"
    return "selected"


def get_local_update_review_group_key(entry: LocalUpdateReviewEntry) -> str:
    """
    依本機更新項目的狀態分類群組鍵

    Args:
        entry: 要分類的本機更新 Review 項目

    Returns:
        selected、advisory、unselected、retryable、unknown 或 blocked 群組鍵
    """
    candidate = getattr(entry, "candidate", None)
    confidence = str(getattr(candidate, "recommendation_confidence", "") or "").strip().lower()
    source = str(getattr(candidate, "recommendation_source", "") or "").strip().lower()
    metadata = str(getattr(candidate, "metadata_source", "") or "").strip().lower()
    if not bool(getattr(entry, "runnable", False)):
        if (
            confidence == RECOMMENDATION_CONFIDENCE_RETRYABLE
            or source == RECOMMENDATION_SOURCE_STALE_METADATA
            or metadata == METADATA_SOURCE_STALE_PROVIDER
        ):
            return "retryable"
        if source == RECOMMENDATION_SOURCE_METADATA_UNRESOLVED or metadata == METADATA_SOURCE_UNRESOLVED:
            return "unknown"
        return "blocked"
    if not bool(getattr(entry, "selected", False)):
        return "unselected"
    return "advisory" if confidence == RECOMMENDATION_CONFIDENCE_ADVISORY else "selected"


def get_review_group_specs() -> tuple[tuple[str, str], ...]:
    """
    取得 Review 群組鍵與顯示標籤的對應清單

    Returns:
        群組鍵與顯示標籤的對應清單
    """
    return (
        ("selected", "已選取項目"),
        ("advisory", "建議確認項目"),
        ("unselected", "未選取項目"),
        ("retryable", "可重試項目"),
        ("unknown", "待識別項目"),
        ("blocked", "需先處理項目"),
    )


def count_review_groups(
    entries: list[Any], *, supported_group_keys: Iterable[str], group_key_getter: Callable[[Any], str]
) -> dict[str, int]:
    """
    依群組鍵統計 Review 項目數量

    Args:
        entries: 要分類統計的 Review 項目清單
        supported_group_keys: 要預先建立的群組鍵可迭代值
        group_key_getter: 從每個項目取得群組鍵的函式

    Returns:
        各群組鍵對應的項目數量
    """
    counts = dict.fromkeys(supported_group_keys, 0)
    for entry in entries:
        key = group_key_getter(entry)
        counts[key] = counts.get(key, 0) + 1
    return counts


def count_local_update_review_groups(entries: list[LocalUpdateReviewEntry]) -> dict[str, int]:
    """
    統計本機更新 Review 項目的各狀態群組數量

    Args:
        entries: 本機更新 Review 項目清單

    Returns:
        本機更新各群組鍵對應的數量
    """
    return count_review_groups(
        entries,
        supported_group_keys=("selected", "advisory", "unselected", "retryable", "unknown", "blocked"),
        group_key_getter=get_local_update_review_group_key,
    )


def count_online_install_review_groups(entries: list[PendingInstallReviewEntry]) -> dict[str, int]:
    """
    統計線上安裝 Review 項目的各狀態群組數量

    Args:
        entries: 線上安裝 Review 項目清單

    Returns:
        線上安裝各群組鍵對應的數量
    """
    return count_review_groups(
        entries,
        supported_group_keys=("selected", "advisory", "unselected", "blocked"),
        group_key_getter=get_online_install_review_group_key,
    )


def get_review_group_label(group_key: str, label_map: dict[str, str], *, default_label: str = "需先處理") -> str:
    """
    依群組鍵取得對應的顯示標籤

    Args:
        group_key: 群組鍵
        label_map: 群組鍵與顯示標籤的對應字典
        default_label: 預設顯示標籤

    Returns:
        對應的顯示標籤
    """
    return label_map.get(group_key, default_label)


def get_local_update_group_status_label(group_key: str) -> str:
    """
    依本機更新群組鍵取得對應的顯示標籤

    Args:
        group_key: 本機更新群組鍵

    Returns:
        對應的顯示標籤
    """
    return get_review_group_label(
        group_key,
        {
            "selected": "可更新",
            "advisory": "建議確認",
            "unselected": "未選取",
            "retryable": "可重試",
            "unknown": "需先識別",
            "blocked": "需先處理",
        },
    )


def get_online_install_group_status_label(group_key: str) -> str:
    """
    依線上安裝群組鍵取得對應的顯示標籤

    Args:
        group_key: 線上安裝群組鍵

    Returns:
        對應的顯示標籤
    """
    return get_review_group_label(
        group_key,
        {"selected": "可安裝", "advisory": "建議確認", "unselected": "未選取", "blocked": "需先處理"},
    )


def build_local_update_review_key(candidate: Any) -> str:
    """
    建立本機更新候選的穩定 Review 識別鍵

    Args:
        candidate: 提供 project_id、local_mod、filename 或 project_name 的更新候選

    Returns:
        由專案、檔案或名稱組成的 Review 識別鍵
    """
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
    return (
        f"local::{filename}"
        if filename
        else f"local::{str(getattr(candidate, 'project_name', '') or 'unknown').strip()}"
    )


def build_online_review_root_extra_segments(review_entry: PendingInstallReviewEntry) -> list[str]:
    """
    建立線上安裝根節點的依賴與警告數量片段

    Args:
        review_entry: 要產生摘要片段的線上安裝 Review 項目

    Returns:
        依賴、可選依賴、提醒與阻擋數量的文字片段
    """
    auto_count, optional_count = count_dependency_plan_items(getattr(review_entry, "dependency_plan", None))
    warning_count = len(dedupe_review_messages(list(getattr(review_entry, "warning_messages", []) or [])))
    blocking_count = len(dedupe_review_messages(list(getattr(review_entry, "blocking_reasons", []) or [])))
    segments = []
    if auto_count:
        segments.append(f"依賴 {auto_count}")
    if optional_count:
        segments.append(f"可選 {optional_count}")
    if warning_count:
        segments.append(f"提醒 {warning_count}")
    if blocking_count:
        segments.append(f"阻擋 {blocking_count}")
    return segments


def build_online_review_root_status_text(review_entry: PendingInstallReviewEntry) -> str:
    """
    建立線上安裝根節點的狀態摘要文字

    Args:
        review_entry: 要顯示狀態的線上安裝 Review 項目

    Returns:
        群組狀態與額外數量片段組成的摘要文字
    """
    return build_review_root_status_text(
        review_entry,
        group_key_getter=get_online_install_review_group_key,
        group_status_getter=get_online_install_group_status_label,
        extra_segment_getter=build_online_review_root_extra_segments,
    )


def build_review_root_status_text(
    review_entry: Any,
    *,
    group_key_getter: Callable[[Any], str],
    group_status_getter: Callable[[str], str],
    extra_segment_getter: Callable[[Any], list[str]] | None = None,
) -> str:
    """
    依群組與額外片段組合 Review 根節點狀態文字

    Args:
        review_entry: 要產生狀態文字的 Review 項目
        group_key_getter: 取得項目群組鍵的函式
        group_status_getter: 將群組鍵轉為顯示標籤的函式
        extra_segment_getter: 可選的額外狀態片段產生函式

    Returns:
        群組狀態與額外片段組成的狀態文字
    """
    segments = [group_status_getter(group_key_getter(review_entry))]
    if extra_segment_getter is not None:
        segments.extend(extra_segment_getter(review_entry))
    return "｜".join(segments)


class ReviewGroupingMixin:
    """Review 樹狀節點的分組與建立流程"""

    def _build_dependency_review_nodes(
        self,
        *,
        root_key: str,
        group_key: str,
        optional_group_values: tuple[str, ...],
        parent_name: str,
        dependency_plan: Any,
        selected_dependency_keys: set[tuple[str, str]],
        required_by_map: dict[tuple[str, str], list[str]],
        node_builder: Callable[[int, Any, str, bool, bool, str], ReviewTaskNode],
    ) -> list[ReviewTaskNode]:
        dependency_entries = [
            *((item, False) for item in list(getattr(dependency_plan, "items", []) or [])),
            *((item, True) for item in list(getattr(dependency_plan, "advisory_items", []) or [])),
        ]
        dependency_entries.sort(
            key=lambda entry: (
                str(getattr(entry[0], "project_name", "") or "").casefold(),
                str(getattr(entry[0], "version_name", "") or "").casefold(),
            )
        )
        nodes: list[ReviewTaskNode] = []
        optional_group_id = f"{root_key}::optional-dependencies"
        optional_group_added = False
        optional_count = sum(
            bool(getattr(item, "is_optional", is_advisory)) for item, is_advisory in dependency_entries
        )
        for index, (dependency_item, is_advisory) in enumerate(dependency_entries):
            dependency_key = build_dependency_review_key(dependency_item)
            required_by_text = format_required_by_list(required_by_map.get(dependency_key, [parent_name]))
            is_optional = bool(getattr(dependency_item, "is_optional", is_advisory))
            is_selected = dependency_key in selected_dependency_keys
            dependency_status = build_dependency_status_text(
                dependency_item, parent_name, required_by_text, is_optional, is_selected
            )
            parent_id = root_key
            if is_optional:
                if not optional_group_added:
                    optional_group_added = True
                    group_status = f"共 {optional_count} 項，可選取後一同安裝"
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
            nodes.append(node_builder(index, dependency_item, dependency_status, is_optional, is_selected, parent_id))
        return nodes

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
        is_selected: bool,
        parent_id: str,
    ) -> ReviewTaskNode:
        child_values = (
            "自動" if is_selected else "略過" if is_advisory else "自動",
            "Modrinth",
            dependency_item.project_name,
            dependency_item.version_name,
            "optional" if is_optional_dependency_item(dependency_item) else "required",
            dependency_status,
        )
        return ReviewTaskNode(
            node_id=f"{root_key}::dependency::{index}",
            root_key=root_key,
            group_key=group_key,
            parent_id=parent_id,
            title="依賴",
            values=mask_redundant_review_values(parent_values, child_values),
            node_kind="dependency",
            detail=dependency_status,
        )

    def _build_flat_review_task_nodes(
        self,
        review_entries: list[Any],
        get_entry_key: Callable[[Any], Any],
        get_root_key: Callable[[Any], str],
        get_group_key: Callable[[Any], str],
        get_title: Callable[[Any], str],
        get_status_text: Callable[[Any], str],
        get_root_values: Callable[[Any, str], tuple[str, ...]],
    ) -> list[ReviewTaskNode]:
        nodes: list[ReviewTaskNode] = []
        seen_root_keys: set[str] = set()
        for entry in sorted(review_entries, key=get_entry_key):
            root_key = get_root_key(entry)
            if root_key in seen_root_keys:
                continue
            seen_root_keys.add(root_key)
            status_text = get_status_text(entry)
            nodes.append(
                ReviewTaskNode(
                    node_id=root_key,
                    root_key=root_key,
                    group_key=get_group_key(entry),
                    title=get_title(entry),
                    values=get_root_values(entry, status_text),
                    node_kind="root",
                )
            )
        return nodes

    def _build_online_review_task_nodes(self, review_entries: list[PendingInstallReviewEntry]) -> list[ReviewTaskNode]:
        def sort_key(entry: PendingInstallReviewEntry) -> tuple[Any, ...]:
            pending = getattr(entry, "pending", None)
            version = getattr(pending, "version", None)
            return (
                {"blocked": 0, "advisory": 1, "unselected": 2, "selected": 3}.get(
                    get_online_install_review_group_key(entry), 99
                ),
                str(getattr(pending, "project_name", "") or "").casefold(),
                str(getattr(version, "display_name", "") or "").casefold(),
            )

        def root_key(entry: PendingInstallReviewEntry) -> str:
            pending = getattr(entry, "pending", None)
            version = getattr(pending, "version", None)
            return build_pending_install_review_key(
                getattr(pending, "project_id", ""), getattr(version, "version_id", "")
            )

        roots = self._build_flat_review_task_nodes(
            review_entries,
            sort_key,
            root_key,
            get_online_install_review_group_key,
            lambda entry: str(getattr(getattr(entry, "pending", None), "project_name", "") or "模組"),
            build_online_review_root_status_text,
            lambda entry, status: (
                "是" if entry.selected else "否",
                format_provider_label(entry.provider),
                str(getattr(getattr(entry, "pending", None), "project_name", "") or "未知模組"),
                str(
                    getattr(getattr(getattr(entry, "pending", None), "version", None), "display_name", "") or "未知版本"
                ),
                str(getattr(entry, "version_type", "") or "-"),
                status,
            ),
        )
        root_map = {node.root_key: node for node in roots}
        required_by = collect_dependency_required_by(
            review_entries,
            parent_name_getter=lambda entry: str(
                getattr(getattr(entry, "pending", None), "project_name", "") or ""
            ).strip(),
        )
        children: list[ReviewTaskNode] = []
        for entry in sorted(review_entries, key=sort_key):
            key = root_key(entry)
            root = root_map.get(key)
            if root is None:
                continue
            pending = getattr(entry, "pending", None)

            def build_node(
                index: int,
                item: Any,
                status: str,
                optional: bool,
                selected: bool,
                parent_id: str,
                bound_root: ReviewTaskNode = root,
            ) -> ReviewTaskNode:
                return self._build_online_dependency_task_node(
                    root_key=bound_root.root_key,
                    group_key=bound_root.group_key,
                    parent_values=bound_root.values,
                    index=index,
                    dependency_item=item,
                    dependency_status=status,
                    is_advisory=optional,
                    is_selected=selected,
                    parent_id=parent_id,
                )

            children.extend(
                self._build_dependency_review_nodes(
                    root_key=key,
                    group_key=root.group_key,
                    optional_group_values=root.values,
                    parent_name=str(getattr(pending, "project_name", "") or "模組"),
                    dependency_plan=getattr(entry, "dependency_plan", None),
                    selected_dependency_keys=entry.selected_dependency_keys,
                    required_by_map=required_by,
                    node_builder=build_node,
                )
            )
        return [*roots, *children]

    def _build_local_update_task_nodes(self, review_entries: list[LocalUpdateReviewEntry]) -> list[ReviewTaskNode]:
        return self._build_flat_review_task_nodes(
            review_entries,
            lambda entry: (
                {"blocked": 0, "advisory": 1, "retryable": 2, "unknown": 3, "unselected": 4, "selected": 5}.get(
                    get_local_update_review_group_key(entry), 99
                ),
                str(getattr(getattr(entry, "candidate", None), "project_name", "") or "").casefold(),
            ),
            lambda entry: build_local_update_review_key(entry.candidate),
            get_local_update_review_group_key,
            lambda entry: str(getattr(getattr(entry, "candidate", None), "project_name", "") or "模組"),
            lambda entry: build_review_root_status_text(
                entry,
                group_key_getter=get_local_update_review_group_key,
                group_status_getter=get_local_update_group_status_label,
            ),
            lambda entry, status: (
                "是" if entry.selected else "否",
                str(getattr(getattr(entry, "candidate", None), "current_version", "") or "未知"),
                str(getattr(getattr(entry, "candidate", None), "target_version_name", "") or "-"),
                format_local_update_source_text(entry),
                status,
            ),
        )


__all__ = [
    "ReviewGroupingMixin",
    "build_local_update_review_key",
    "build_online_review_root_status_text",
    "build_pending_install_review_key",
    "build_review_root_status_text",
    "count_local_update_review_groups",
    "count_online_install_review_groups",
    "get_local_update_group_status_label",
    "get_local_update_review_group_key",
    "get_online_install_group_status_label",
    "get_online_install_review_group_key",
    "get_review_group_specs",
]
