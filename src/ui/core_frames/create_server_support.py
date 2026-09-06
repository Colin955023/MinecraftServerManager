"""建立伺服器表單的純資料轉換"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def compose_server_name(loader_type: str, minecraft_version: str, suffix: str = "") -> str:
    """
    依 Loader 類型與版本組合標準伺服器名稱

    Args:
        loader_type: Loader 類型
        minecraft_version: Minecraft 版本
        suffix: 使用者自訂尾字

    Returns:
        組合後的伺服器名稱
    """
    base_name = f"{minecraft_version}{suffix}"
    if loader_type in ("Fabric", "Forge", "Quilt", "NeoForge"):
        return f"{loader_type} {base_name}"
    return base_name


def extract_server_name_suffix(name: str, version_candidates: Iterable[str]) -> str | None:
    """
    解析「Loader 前綴 + 版本 + 自訂尾字」中的尾字

    Args:
        name: 既有伺服器名稱
        version_candidates: 可接受的 Minecraft 版本候選

    Returns:
        自訂尾字，格式不符合時回傳 None
    """
    normalized = name.strip()
    if not normalized:
        return None
    for prefix in ("Fabric ", "Forge ", "Quilt ", "NeoForge "):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    for version in version_candidates:
        if version and normalized.startswith(version):
            return normalized[len(version) :]
    return None


def version_names(versions: Iterable[Any]) -> list[str]:
    """
    將 Loader 版本結果統一轉為 UI 可顯示文字

    Args:
        versions: Loader 版本物件或字串

    Returns:
        對應的版本名稱列表
    """
    return [
        value.version if hasattr(value, "version") else value if isinstance(value, str) else str(value)
        for value in versions
    ]


__all__ = ["compose_server_name", "extract_server_name_suffix", "version_names"]
