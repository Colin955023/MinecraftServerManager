"""Review 格式化工具 — 從 ModManagementReviewMixin 提取的純格式化靜態方法。"""

from __future__ import annotations

from ...utils import (
    METADATA_SOURCE_LABELS,
    METADATA_SOURCE_SHORT_LABELS,
    RECOMMENDATION_CONFIDENCE_LABELS,
    RECOMMENDATION_SOURCE_LABELS,
    RECOMMENDATION_SOURCE_SHORT_LABELS,
)
from .constants import MODRINTH_PROJECT_PAGE_BASE_URL


def format_review_provider_label(provider: str | None) -> str:
    """格式化 provider 標籤。

    Args:
        provider: provider 名稱字串（如 "modrinth"）或 None。

    Returns:
        格式化後的 provider 顯示名稱；未知時回傳 "未知來源"。
    """
    normalized = str(provider or "").strip().lower()
    if normalized == "modrinth":
        return "Modrinth"
    return str(provider or "未知來源").strip() or "未知來源"


def format_metadata_source_label(source: str | None) -> str:
    """格式化 metadata 來源標籤。

    Args:
        source: metadata 來源字串（如 "modrinth"、"local"）或 None。

    Returns:
        對應的顯示標籤；未知時回傳 "未知"。
    """
    normalized = str(source or "").strip().lower()
    return METADATA_SOURCE_LABELS.get(normalized, "未知")


def format_metadata_source_short_label(source: str | None) -> str:
    """格式化 metadata 來源短標籤。

    Args:
        source: metadata 來源字串（如 "modrinth"、"local"）或 None。

    Returns:
        對應的簡短顯示標籤；未知時回傳 "未知"。
    """
    normalized = str(source or "").strip().lower()
    return METADATA_SOURCE_SHORT_LABELS.get(normalized, "未知")


def format_recommendation_source_label(source: str | None) -> str:
    """格式化推薦來源標籤。

    Args:
        source: 推薦來源字串（如 "modrinth"、"local"）或 None。

    Returns:
        對應的顯示標籤；未知時回傳 "未知"。
    """
    normalized = str(source or "").strip().lower()
    return RECOMMENDATION_SOURCE_LABELS.get(normalized, "未知")


def format_recommendation_source_short_label(source: str | None) -> str:
    """格式化推薦來源短標籤。

    Args:
        source: 推薦來源字串（如 "modrinth"、"local"）或 None。

    Returns:
        對應的簡短顯示標籤；未知時回傳 "未知"。
    """
    normalized = str(source or "").strip().lower()
    return RECOMMENDATION_SOURCE_SHORT_LABELS.get(normalized, "未知")


def format_recommendation_confidence_label(confidence: str | None) -> str:
    """格式化推薦信心標籤。

    Args:
        confidence: 信心等級字串（如 "high"、"medium"、"low"）或 None。

    Returns:
        對應的顯示標籤；未知時回傳 "未知"。
    """
    normalized = str(confidence or "").strip().lower()
    return RECOMMENDATION_CONFIDENCE_LABELS.get(normalized, "未知")


def build_modrinth_project_page_url(identifier: str | None) -> str:
    """建立 Modrinth 專案頁面 URL。

    Args:
        identifier: Modrinth 專案 slug 或 ID 字串，或 None。

    Returns:
        完整的 Modrinth 專案頁面 URL；無效輸入時回傳空字串。
    """
    normalized = str(identifier or "").strip().strip("/")
    if not normalized:
        return ""
    return f"{MODRINTH_PROJECT_PAGE_BASE_URL}/{normalized}"


def format_review_published_at(value: str | None) -> str:
    """格式化發布時間。

    Args:
        value: ISO 8601 時間字串（如 "2024-01-15T12:00:00Z"）或 None。

    Returns:
        格式化後的時間字串（YYYY-MM-DD HH:MM）；無效輸入時回傳空字串。
    """
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    return raw_value.replace("T", " ").replace("Z", "")[:16]


def summarize_review_changelog(value: str | None, max_length: int = 420) -> str:
    """摘要 changelog 內容。

    Args:
        value: 原始 changelog 文字或 None。
        max_length: 最大輸出長度（字元數），預設 420。

    Returns:
        截斷後的 changelog 摘要；無內容時回傳空字串。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length].rsplit("\n", 1)[0].rstrip() + "\n..."
