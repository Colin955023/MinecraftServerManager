"""Provider registry。

讓 UI / 核心流程以名稱取得 provider，而不是直接綁定單一模組來源。
"""

from __future__ import annotations

from .provider_protocol import ModProvider

_PROVIDERS: dict[str, ModProvider] = {}
_DEFAULT_PROVIDER_ID = "modrinth"


def register_mod_provider(provider: ModProvider) -> ModProvider:
    """
    註冊 provider 並回傳同一實例，方便模組初始化時串接。

    Args:
        provider: 要註冊的 provider 實例。

    Returns:
        原始 provider 實例，方便呼叫端直接串接初始化流程。
    """
    provider_id = str(getattr(provider, "provider_id", "") or "").strip().lower()
    if not provider_id:
        raise ValueError("provider_id 不可為空")
    _PROVIDERS[provider_id] = provider
    return provider


def get_mod_provider(provider_id: str | None = None) -> ModProvider:
    """
    依 provider id 取得 provider；未指定時回傳預設來源。

    Args:
        provider_id: 要取得的 provider id；未指定時使用預設來源。

    Returns:
        對應的 provider 實例。
    """
    normalized_provider_id = str(provider_id or _DEFAULT_PROVIDER_ID).strip().lower() or _DEFAULT_PROVIDER_ID
    provider = _PROVIDERS.get(normalized_provider_id)
    if provider is None:
        raise KeyError(f"找不到 provider: {normalized_provider_id}")
    return provider


def list_mod_providers() -> list[str]:
    """
    列出目前已註冊的 provider id。

    Returns:
        依字母排序的 provider id 清單。
    """
    return sorted(_PROVIDERS)


__all__ = [
    "get_mod_provider",
    "list_mod_providers",
    "register_mod_provider",
]
