"""下載來源驗證與警示策略"""

from __future__ import annotations

from urllib.parse import urlparse

OFFICIAL_DOWNLOAD_HOSTS: dict[str, frozenset[str]] = {
    "modrinth": frozenset({"api.modrinth.com", "cdn.modrinth.com", "modrinth.com"}),
}


def normalize_download_provider(provider: str | None) -> str:
    """
    正規化下載來源 provider 名稱

    Args:
        provider: 原始 provider 名稱

    Returns:
        正規化後的 provider 名稱；空值時回傳 unknown
    """

    return str(provider or "").strip().lower() or "unknown"


def _extract_download_host(download_url: str | None) -> str:
    """
    從下載網址擷取 host

    Args:
        download_url: 原始下載網址

    Returns:
        下載網址中的 host；解析失敗時回傳空字串
    """

    try:
        parsed_url = urlparse(str(download_url or "").strip())
        return str(parsed_url.hostname or "").strip().rstrip(".").lower()
    except Exception:
        return ""


def get_non_official_download_host(download_url: str | None, provider: str | None) -> str:
    """
    若下載來源不是官方網域，回傳其 host，否則回傳空字串

    Args:
        download_url: 原始下載網址
        provider: 來源 provider 名稱

    Returns:
        非官方來源的 host；若為官方來源則回傳空字串
    """

    host = _extract_download_host(download_url)
    if not host or host in OFFICIAL_DOWNLOAD_HOSTS.get(normalize_download_provider(provider), frozenset()):
        return ""
    return host


def build_non_official_source_warning(download_url: str | None, provider: str | None) -> str:
    """
    建立 core 層用的非官方下載來源警示字串

    Args:
        download_url: 原始下載網址
        provider: 來源 provider 名稱

    Returns:
        非官方來源警示字串；若為官方來源則回傳空字串
    """

    host = get_non_official_download_host(download_url, provider)
    if not host:
        return ""
    provider_label = str(provider or "unknown").strip() or "unknown"
    normalized_url = str(download_url or "").strip()
    return f"偵測到非官方下載來源：provider={provider_label} host={host} url={normalized_url}"


def build_non_official_source_warning_message(
    item_label: str,
    download_url: str | None,
    provider: str | None,
    *,
    provider_label: str | None = None,
) -> str:
    """
    建立 UI 顯示用的非官方下載來源提醒

    Args:
        item_label: 顯示在 UI 的項目名稱
        download_url: 原始下載網址
        provider: 來源 provider 名稱
        provider_label: 顯示在 UI 的 provider 名稱

    Returns:
        UI 用的非官方來源提醒文字；若為官方來源則回傳空字串
    """

    host = get_non_official_download_host(download_url, provider)
    if not host:
        return ""
    normalized_label = str(item_label or "未知項目").strip() or "未知項目"
    display_provider_label = str(provider_label or provider or "未知來源").strip() or "未知來源"
    return (
        f"非官方下載來源：{normalized_label} 將從 {host} 下載，"
        f"非 {display_provider_label} 官方網域，請再次確認來源可信度"
    )


__all__ = [
    "build_non_official_source_warning",
    "build_non_official_source_warning_message",
    "get_non_official_download_host",
]
