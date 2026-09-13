"""
伺服器名稱安全政策

集中管理 Windows 路徑元件、專案內部保留名稱與長度限制
"""

from __future__ import annotations

import ntpath
from pathlib import PureWindowsPath

MAX_SERVER_NAME_LENGTH = 100

_LEGACY_WINDOWS_DEVICE_NAMES = frozenset({"clock$"})
_INTERNAL_EXACT_NAMES = frozenset({".issues", "servers_config.json"})
_INTERNAL_PREFIXES = (".msm-",)


def validate_server_name(name: str, *, max_length: int = MAX_SERVER_NAME_LENGTH) -> str:
    """
    驗證伺服器名稱可安全作為 servers root 的直接子目錄

    Args:
        name: 要驗證的名稱
        max_length: 允許的最大字元數

    Returns:
        驗證後且不變更內容的名稱

    Raises:
        ValueError: 名稱不符合 Windows 或專案路徑政策
    """
    normalized = str(name or "")
    if not normalized or normalized != normalized.strip():
        raise ValueError("伺服器名稱不可為空白或包含前後空白")
    if len(normalized) > max(1, int(max_length)):
        raise ValueError(f"伺服器名稱過長（上限 {max(1, int(max_length))} 字元）")
    if normalized in {".", ".."} or PureWindowsPath(normalized).name != normalized:
        raise ValueError("伺服器名稱不可包含路徑片段")
    if ntpath.isreserved(f"X:\\{normalized}"):
        raise ValueError("伺服器名稱不符合 Windows 檔名規則")

    normalized_casefold = normalized.casefold()
    base_name = normalized.rstrip(" .").partition(".")[0].casefold()
    if base_name in _LEGACY_WINDOWS_DEVICE_NAMES:
        raise ValueError("伺服器名稱使用 Windows 保留裝置名稱")
    if normalized_casefold in _INTERNAL_EXACT_NAMES or normalized_casefold.startswith(_INTERNAL_PREFIXES):
        raise ValueError("伺服器名稱與程式內部保留路徑衝突")
    return normalized


__all__ = ["MAX_SERVER_NAME_LENGTH", "validate_server_name"]
