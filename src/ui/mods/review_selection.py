"""Review tree 的暫時選取狀態操作"""

from __future__ import annotations

from typing import Any


def set_review_entries_selected(entries: dict[str, Any], keys: set[str], selected: bool) -> bool:
    """
    設定指定 Review 項目的 selected 狀態

    Args:
        entries: 以根節點鍵對應 Review 項目的字典
        keys: 要更新的根節點鍵集合
        selected: 要設定的選取狀態

    Returns:
        至少有一個項目狀態被變更時回傳 True
    """
    changed = False
    for key in keys:
        entry = entries.get(key)
        if entry is None or bool(getattr(entry, "selected", True)) == selected:
            continue
        entry.selected = selected
        changed = True
    return changed


def count_selected_runnable_entries(entries: list[Any]) -> int:
    """
    計算已選取且可執行的 Review 項目數量

    Args:
        entries: 要檢查 selected 與 runnable 狀態的 Review 項目清單

    Returns:
        同時符合已選取與可執行條件的項目數量
    """
    return sum(
        1 for entry in entries if bool(getattr(entry, "selected", False)) and bool(getattr(entry, "runnable", False))
    )


def collect_review_entry_selected_overrides(entries: list[Any], root_keys: list[str]) -> dict[str, bool]:
    """
    建立根節點鍵對應的 selected 狀態覆寫字典

    Args:
        entries: 與 root_keys 依序對應的 Review 項目清單
        root_keys: Review 根節點鍵清單

    Returns:
        根節點鍵對應的 selected 狀態
    """
    return {
        root_key: bool(getattr(entry, "selected", False))
        for root_key, entry in zip(root_keys, entries, strict=False)
        if root_key
    }


__all__ = [
    "collect_review_entry_selected_overrides",
    "count_selected_runnable_entries",
    "set_review_entries_selected",
]
