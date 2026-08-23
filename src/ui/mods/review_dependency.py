"""Dependency review 的 key、required-by、排序與統計工具"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.models import ReviewTaskNode


def build_dependency_review_key(dependency_item: Any) -> tuple[str, str]:
    """
    建立依賴項目的穩定識別鍵

    Args:
        dependency_item: 提供 project_id、version_id 或 version_name 屬性的依賴項目

    Returns:
        由專案識別值與版本識別值組成的鍵
    """
    return (
        str(getattr(dependency_item, "project_id", "") or "").strip(),
        str(getattr(dependency_item, "version_id", "") or getattr(dependency_item, "version_name", "") or "").strip(),
    )


def build_dependency_key(dependency_item: Any) -> tuple[str, str]:
    """
    建立依賴項目用於彙整的識別鍵

    Args:
        dependency_item: 要轉換為識別鍵的依賴項目

    Returns:
        與 build_dependency_review_key 相同的專案及版本鍵
    """
    return build_dependency_review_key(dependency_item)


def is_optional_dependency_item(dependency_item: Any) -> bool:
    """
    判斷依賴項目是否被標記為可選

    Args:
        dependency_item: 要檢查的依賴項目

    Returns:
        如果被標記為可選則回傳 True，否則回傳 False
    """
    marker = getattr(dependency_item, "is_optional", None)
    return True if marker is None else bool(marker)


def get_sorted_dependency_review_items(dependency_plan: Any) -> list[Any]:
    """
    取得依賴計畫中已排序的依賴項目清單

    Args:
        dependency_plan: 提供 items 與 advisory_items 屬性的依賴計畫

    Returns:
        已排序的依賴項目清單
    """
    items = [
        *list(getattr(dependency_plan, "items", []) or []),
        *list(getattr(dependency_plan, "advisory_items", []) or []),
    ]
    items.sort(
        key=lambda item: (
            str(getattr(item, "project_name", "") or "").casefold(),
            str(getattr(item, "version_name", "") or "").casefold(),
        )
    )
    return items


def get_enabled_dependency_install_items(dependency_plan: Any) -> list[Any]:
    """
    取得依賴計畫中已啟用的依賴安裝項目清單

    Args:
        dependency_plan: 提供 items 與 advisory_items 屬性的依賴計畫

    Returns:
        已啟用的依賴安裝項目清單
    """
    return [
        *list(getattr(dependency_plan, "items", []) or []),
        *[
            item
            for item in list(getattr(dependency_plan, "advisory_items", []) or [])
            if bool(getattr(item, "enabled", False))
        ],
    ]


def collect_dependency_required_by(
    review_entries: list[Any], *, parent_name_getter: Callable[[Any], str]
) -> dict[tuple[str, str], list[str]]:
    """
    收集每個依賴項目被哪些根項目要求

    Args:
        review_entries: 要檢查的 Review 項目，僅處理已啟用且可執行的項目
        parent_name_getter: 從 Review 項目取得顯示名稱的函式

    Returns:
        依賴識別鍵對應的要求者名稱清單
    """
    required_by: dict[tuple[str, str], list[str]] = {}
    for entry in review_entries:
        if not bool(getattr(entry, "enabled", False)) or not bool(getattr(entry, "runnable", False)):
            continue
        parent_name = parent_name_getter(entry)
        if not parent_name:
            continue
        for dependency_item in get_sorted_dependency_review_items(entry.dependency_plan):
            required_by.setdefault(build_dependency_key(dependency_item), []).append(parent_name)
    return required_by


def count_dependency_plan_items(dependency_plan: Any) -> tuple[int, int]:
    """
    統計依賴計畫中的必要與可選依賴數量

    Args:
        dependency_plan: 提供 items 與 advisory_items 屬性的依賴計畫

    Returns:
        必要依賴數量與被標記為可選的依賴數量
    """
    items = len(list(getattr(dependency_plan, "items", []) or []))
    optional = sum(
        1 for item in list(getattr(dependency_plan, "advisory_items", []) or []) if is_optional_dependency_item(item)
    )
    return items, optional


def count_review_nodes(nodes: list[ReviewTaskNode], node_kind: str) -> int:
    """
    計算指定種類的 Review 任務節點數量

    Args:
        nodes: 要統計的 Review 任務節點清單
        node_kind: 要比對的節點種類名稱

    Returns:
        符合指定種類的節點數量
    """
    return sum(1 for node in nodes if node.node_kind == node_kind)


def build_dependency_status_text(
    dependency_item: Any, parent_name: str, required_by_text: str, is_advisory: bool, is_enabled: bool
) -> str:
    """
    組合依賴項目的來源、可信度與處理狀態文字

    Args:
        dependency_item: 提供解析與安裝狀態資訊的依賴項目
        parent_name: 主要要求此依賴的項目名稱
        required_by_text: 已整理的要求者文字，空白時使用 parent_name
        is_advisory: 是否為可選依賴
        is_enabled: 是否已啟用此依賴的安裝

    Returns:
        顯示 required-by、解析來源、可信度與處理方式的狀態文字
    """
    resolved_required_by = required_by_text or parent_name
    source = str(getattr(dependency_item, "resolution_source", "project_id") or "").strip().lower()
    source_label = {
        "version_detail": "版本詳情回補",
        "loader_override": "loader 覆寫",
        "version_id": "version id 線索",
    }.get(source, "project id 直連")
    confidence = str(getattr(dependency_item, "resolution_confidence", "direct") or "").strip().lower()
    confidence_label = "需確認" if confidence in {"heuristic", "manual"} else "中" if confidence == "fallback" else "高"
    if is_advisory and is_enabled:
        action = "可選依賴，已啟用安裝"
    elif is_advisory:
        action = "可選依賴，預設略過"
    elif bool(getattr(dependency_item, "maybe_installed", False)) and is_enabled:
        action = "疑似已安裝，已改為安裝"
    elif bool(getattr(dependency_item, "maybe_installed", False)):
        action = "疑似已安裝，預設略過"
    else:
        action = str(getattr(dependency_item, "status_note", "") or "").strip() or "將自動安裝"
    return f"required-by：{resolved_required_by}｜解析：{source_label}（{confidence_label}）｜處理：{action}"


def append_dependency_review_sections(lines: list[str], dependency_plan: Any, required_heading: str) -> None:
    """
    將依賴計畫的必要、可選與疑似已安裝項目追加到文字清單

    Args:
        lines: 要追加顯示內容的文字清單
        dependency_plan: 提供 items 與 advisory_items 的依賴計畫
        required_heading: 必要依賴區段的標題
    """
    dependency_items = list(getattr(dependency_plan, "items", []) or [])
    advisory_items = list(getattr(dependency_plan, "advisory_items", []) or [])
    if dependency_items:
        lines.append("")
        lines.append(required_heading)
        lines.extend(f"- {item.project_name} ({item.version_name})" for item in dependency_items[:3])
        if len(dependency_items) > 3:
            lines.append(f"- 其餘 {len(dependency_items) - 3} 項請於任務樹查看")
    if advisory_items:
        optional_items = [item for item in advisory_items if is_optional_dependency_item(item)]
        maybe_installed_items = [item for item in advisory_items if not is_optional_dependency_item(item)]
        if optional_items:
            lines.append("")
            lines.append("可選依賴（可啟用後一同安裝）：")
            lines.extend(
                f"- {item.project_name}{('（已啟用）' if getattr(item, 'enabled', False) else '（預設略過）')}"
                for item in optional_items[:2]
            )
            if len(optional_items) > 2:
                lines.append(f"- 其餘 {len(optional_items) - 2} 項請於任務樹查看")
        if maybe_installed_items:
            lines.append("")
            lines.append("疑似已安裝、預設略過的必要依賴：")
            lines.extend(
                f"- {item.project_name}{('（已改為安裝）' if getattr(item, 'enabled', False) else '')}"
                for item in maybe_installed_items[:2]
            )
            if len(maybe_installed_items) > 2:
                lines.append(f"- 其餘 {len(maybe_installed_items) - 2} 項請於任務樹查看")


def build_installed_mod_simulation_item(project_id: str, project_name: str, filename: str, version_name: str) -> Any:
    """
    建立供依賴規劃模擬使用的本機模組資料

    Args:
        project_id: 模組的專案識別值
        project_name: 模組的專案名稱
        filename: 模組檔案名稱
        version_name: 模組版本名稱

    Returns:
        可供依賴規劃器讀取的簡易模組物件
    """
    from types import SimpleNamespace

    normalized_name = str(project_name or project_id or filename or "未知模組").strip() or "未知模組"
    normalized_filename = str(filename or normalized_name).strip() or normalized_name
    return SimpleNamespace(
        platform_id=str(project_id or "").strip(),
        id=normalized_name,
        name=normalized_name,
        filename=normalized_filename,
        version=str(version_name or "").strip(),
    )


def append_enabled_dependency_simulations(
    simulated_installed_mods: list[Any], dependency_plan: Any, simulation_item_builder: Callable[..., Any]
) -> None:
    """
    將已啟用的依賴加入模擬安裝清單

    Args:
        simulated_installed_mods: 要追加模擬模組的清單
        dependency_plan: 提供必要與可選依賴項目的依賴計畫
        simulation_item_builder: 建立模擬模組物件的函式
    """
    for dependency_item in get_enabled_dependency_install_items(dependency_plan):
        simulated_installed_mods.append(
            simulation_item_builder(
                getattr(dependency_item, "project_id", ""),
                getattr(dependency_item, "project_name", ""),
                getattr(dependency_item, "filename", ""),
                getattr(dependency_item, "version_name", ""),
            )
        )


__all__ = [
    "append_dependency_review_sections",
    "append_enabled_dependency_simulations",
    "build_dependency_key",
    "build_dependency_review_key",
    "build_dependency_status_text",
    "build_installed_mod_simulation_item",
    "collect_dependency_required_by",
    "count_dependency_plan_items",
    "count_review_nodes",
    "get_enabled_dependency_install_items",
    "get_sorted_dependency_review_items",
    "is_optional_dependency_item",
]
