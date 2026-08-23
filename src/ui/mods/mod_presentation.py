"""Mod 瀏覽與 Review 共用、但不屬於 Review workflow 的呈現規則"""

from __future__ import annotations

import re
from typing import Any

from src.ui import MODRINTH_PROJECT_PAGE_BASE_URL


def format_provider_label(provider: str | None) -> str:
    """
    將 provider key 轉成使用者可讀標籤

    Args:
        provider: Provider key 或既有顯示文字

    Returns:
        正規化後的 provider 顯示名稱
    """
    normalized = str(provider or "").strip().lower()
    return "Modrinth" if normalized == "modrinth" else str(provider or "未知來源").strip() or "未知來源"


def format_published_at(value: str | None) -> str:
    """
    將 ISO 發布時間裁切為分鐘精度的顯示文字

    Args:
        value: Provider 回傳的時間字串

    Returns:
        適合 UI 顯示的時間；沒有值時回傳空字串
    """
    raw_value = str(value or "").strip()
    return raw_value.replace("T", " ").replace("Z", "")[:16] if raw_value else ""


def summarize_changelog(value: str | None, max_length: int = 420) -> str:
    """
    壓縮 changelog 空白並限制顯示長度

    Args:
        value: 原始 changelog
        max_length: 顯示字元上限

    Returns:
        單行且必要時帶省略號的摘要
    """
    normalized = re.sub(r"\s+", " ", str(value or "").strip())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max(0, max_length - 3)].rstrip() + "..."


def _summarize_messages(messages: list[str] | tuple[str, ...], max_items: int = 3) -> list[str]:
    values = list(dict.fromkeys(str(message or "").strip() for message in messages if str(message or "").strip()))
    if len(values) <= max_items:
        return values
    return [*values[:max_items], f"其餘 {len(values) - max_items} 項請於任務樹查看"]


def get_online_version_status_text(report: Any | None) -> str:
    """
    依相容性報告產生線上版本狀態文字

    Args:
        report: 版本相容性分析結果

    Returns:
        可直接顯示於列表的狀態文字
    """
    if report is None:
        return "未分析"
    if not getattr(report, "compatible", True):
        return "不相容"
    if list(getattr(report, "missing_required_dependencies", []) or []):
        return "可安裝，含依賴"
    has_warning = any(
        list(getattr(report, attr, []) or [])
        for attr in ("incompatible_installed", "installed_version_mismatches", "warnings")
    )
    return "可安裝，需注意" if has_warning else "可安裝"


def _online_version_type_rank(version_type: Any) -> int:
    normalized = str(version_type or "").strip().lower()
    return {
        "release": 0,
        "stable": 0,
        "beta": 1,
        "pre": 1,
        "preview": 1,
        "rc": 1,
        "alpha": 2,
        "snapshot": 2,
    }.get(normalized, 3)


def _online_version_compatibility_rank(report: Any | None) -> int:
    return 1 if report is None else (0 if bool(getattr(report, "compatible", True)) else 2)


def sort_online_versions_for_server(
    versions: list[Any], version_reports: list[Any] | None
) -> tuple[list[Any], list[Any] | None]:
    """
    依相容性、版本類型與發布時間排序線上版本

    Args:
        versions: Provider 回傳的版本清單
        version_reports: 與版本索引對齊的相容性報告

    Returns:
        保持版本與報告對齊的排序後清單
    """
    if not versions:
        return versions, version_reports
    reports = [
        version_reports[index] if version_reports is not None and index < len(version_reports) else None
        for index in range(len(versions))
    ]
    rows = list(zip(versions, reports, strict=False))
    rows.sort(
        key=lambda row: (
            _online_version_compatibility_rank(row[1]),
            _online_version_type_rank(getattr(row[0], "version_type", "")),
            str(getattr(row[0], "date_published", "") or ""),
        )
    )
    grouped: dict[tuple[int, int], list[tuple[Any, Any | None]]] = {}
    for row in rows:
        key = (
            _online_version_compatibility_rank(row[1]),
            _online_version_type_rank(getattr(row[0], "version_type", "")),
        )
        grouped.setdefault(key, []).append(row)
    sorted_rows: list[tuple[Any, Any | None]] = []
    for key in sorted(grouped):
        sorted_rows.extend(
            sorted(grouped[key], key=lambda row: str(getattr(row[0], "date_published", "") or ""), reverse=True)
        )
    return [row[0] for row in sorted_rows], None if version_reports is None else [row[1] for row in sorted_rows]


def build_modrinth_project_page_url(identifier: str | None) -> str:
    """
    由 Modrinth ID 或 slug 建立專案頁面網址

    Args:
        identifier: Modrinth 專案 ID 或 slug

    Returns:
        有效專案網址；本地識別或空值回傳空字串
    """
    normalized = str(identifier or "").strip().strip("/")
    if normalized.startswith(("local:", "file:")):
        return ""
    return f"{MODRINTH_PROJECT_PAGE_BASE_URL}/{normalized}" if normalized else ""


def resolve_project_page_url(*, urls: Any = (), identifiers: Any = ()) -> str:
    """
    優先從既有網址，其次從 Modrinth 識別碼解析專案頁面

    Args:
        urls: 依優先順序排列的網址候選
        identifiers: 依優先順序排列的 ID 或 slug 候選

    Returns:
        第一個可用網址；無候選時回傳空字串
    """
    for raw_url in urls:
        if clean_url := str(raw_url or "").strip():
            return clean_url
    for identifier in identifiers:
        if url := build_modrinth_project_page_url(identifier):
            return url
    return ""


def resolve_online_mod_project_page_url(mod: Any) -> str:
    """
    從線上 Mod 模型解析最合適的專案頁面

    Args:
        mod: 含網址、slug 或 project ID 的線上 Mod

    Returns:
        可開啟的專案網址；無法解析時回傳空字串
    """
    return resolve_project_page_url(
        urls=(getattr(mod, "homepage_url", ""), getattr(mod, "url", "")),
        identifiers=(getattr(mod, "slug", ""), getattr(mod, "project_id", "")),
    )


def format_online_version_report(version: Any, report: Any | None) -> str:
    """
    組合版本 metadata 與相容性分析的詳細文字

    Args:
        version: 線上 Mod 版本模型
        report: 選用的相容性分析結果

    Returns:
        Review 詳細資訊區使用的多行文字
    """
    lines = [
        f"版本：{getattr(version, 'display_name', '未知版本')}",
        f"來源：{format_provider_label(getattr(version, 'provider', 'modrinth'))}",
        f"Minecraft：{', '.join(getattr(version, 'game_versions', []) or []) or '-'}",
        f"Loader：{', '.join(getattr(version, 'loaders', []) or []) or '-'}",
    ]
    if version_type := str(getattr(version, "version_type", "") or "").strip():
        lines.append(f"版本類型：{version_type}")
    if published_text := format_published_at(getattr(version, "date_published", "")):
        lines.append(f"發布時間：{published_text}")
    if changelog_text := summarize_changelog(getattr(version, "changelog", "")):
        lines.extend(["", "更新內容：", changelog_text])
    if report is None:
        return "\n".join(lines)
    lines.insert(0, f"相容性結果：{('可安裝' if getattr(report, 'compatible', True) else '不符合目前伺服器條件')}")
    sections = (
        ("阻擋原因：", "hard_errors", 3),
        ("需要安裝的必要依賴：", "missing_required_dependencies", 3),
        ("已安裝但不相容的模組：", "incompatible_installed", 3),
        ("已安裝但版本不符的依賴：", "installed_version_mismatches", 3),
        ("可選依賴：", "optional_dependencies", 2),
        ("目前已安裝：", "already_installed", 2),
        ("補充說明：", "notes", 2),
    )
    for title, attr, max_items in sections:
        values = list(getattr(report, attr, []) or [])
        if values:
            lines.extend(["", title, *[f"- {item}" for item in _summarize_messages(values, max_items=max_items)]])
    return "\n".join(lines)


def normalize_side_support(value: Any) -> str:
    """
    正規化 client/server side support 值

    Args:
        value: Provider 回傳的 side support 值

    Returns:
        去除空白並轉為小寫的字串
    """
    return str(value or "").strip().lower()


def build_client_install_reminder_line(server_side: Any, client_side: Any) -> str | None:
    """
    依雙端支援狀態建立玩家端安裝提醒

    Args:
        server_side: Server side 支援狀態
        client_side: Client side 支援狀態

    Returns:
        需要雙端安裝時的提醒；否則回傳 None
    """
    supported = {"required", "optional"}
    if normalize_side_support(server_side) in supported and normalize_side_support(client_side) in supported:
        return "提醒：此模組同時支援 client 端，請提醒玩家端也安裝相同模組版本，以避免連線或功能不一致問題"
    return None


def build_server_install_blocking_reason(server_side: Any) -> str | None:
    """
    判斷 Mod 是否明確禁止安裝於伺服器

    Args:
        server_side: Server side 支援狀態

    Returns:
        阻擋原因；可安裝或未知時回傳 None
    """
    if normalize_side_support(server_side) == "unsupported":
        return "此模組標記為僅 client 端（server_side=unsupported），不可安裝到伺服器"
    return None


def build_server_install_warning_line(server_side: Any) -> str | None:
    """
    為未明確標示 server 支援的 Mod 建立警告

    Args:
        server_side: Server side 支援狀態

    Returns:
        需要再次確認時的警告；狀態明確時回傳 None
    """
    if normalize_side_support(server_side) in {"", "unknown"}:
        return "提醒：此模組未明確標示 server 端支援，建議安裝前再次確認"
    return None


__all__ = [
    "build_client_install_reminder_line",
    "build_server_install_blocking_reason",
    "build_server_install_warning_line",
    "format_online_version_report",
    "format_provider_label",
    "format_published_at",
    "get_online_version_status_text",
    "resolve_online_mod_project_page_url",
    "resolve_project_page_url",
    "sort_online_versions_for_server",
    "summarize_changelog",
]
