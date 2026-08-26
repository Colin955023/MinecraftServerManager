"""Minecraft 版本與載入器名稱的純語意函式"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from src.utils import parse_version_safe


def _parse_minecraft_version(version: str) -> list[int]:
    """
    將 Minecraft 版本字串解析為數字列表

    Args:
        version: 原始版本字串

    Returns:
        版本數字列表，例如 [1, 20, 1]
    """
    if not version or not isinstance(version, str):
        return []
    parsed = parse_version_safe(version)
    if parsed is not None and parsed.release:
        return [int(part) for part in parsed.release]
    matches = re.findall(r"\d+", version)
    return [int(part) for part in matches] if matches else []


def is_fabric_compatible_version(minecraft_version: str) -> bool:
    """
    判斷 Minecraft 版本是否支援 Fabric（1.14 以上）

    Args:
        minecraft_version: Minecraft 版本字串

    Returns:
        版本支援 Fabric 時回傳 True
    """
    parsed = parse_version_safe(minecraft_version)
    if parsed is not None:
        return parsed.release >= (1, 14)
    parts = _parse_minecraft_version(minecraft_version)
    if not parts:
        return False
    major = parts[0]
    minor = parts[1] if len(parts) > 1 else 0
    return major > 1 or (major == 1 and minor >= 14)


def standardize_loader_type(loader_type: str, loader_version: str = "") -> str:
    """
    將載入器名稱正規化為支援的領域值

    Args:
        loader_type: 原始載入器名稱
        loader_version: 可協助判定的載入器版本字串

    Returns:
        vanilla、fabric、forge、quilt、neoforge 或 unknown
    """
    normalized = str(loader_type or "").lower()
    if normalized in {"fabric", "forge", "quilt", "neoforge"}:
        return normalized
    if normalized in {"vanilla", "原版"}:
        return "vanilla"
    if normalized in {"unknown", "未知"}:
        version = str(loader_version or "").lower()
        if version and version.replace(".", "").isdigit():
            return "forge"
        for candidate in ("fabric", "quilt", "neoforge"):
            if candidate in version:
                return candidate
        return "unknown"
    if "vanilla" in normalized or "official" in normalized:
        return "vanilla"
    return "unknown"


def normalize_minecraft_version(value: Any) -> str:
    """
    將外部 metadata 的 Minecraft 版本值正規化為字串

    Args:
        value: 原始版本值

    Returns:
        正規化後的版本字串
    """
    if isinstance(value, list) and value:
        value = str(value[0])
    if isinstance(value, str) and value.startswith(("[", "(")):
        match = re.search(r"\d+\.\d+", value)
        if match:
            value = match.group(0)
    return str(value or "")


def clean_mod_version(version: str) -> str:
    """
    清除模組版本字串中的載入器與發行階段後綴

    Args:
        version: 原始模組版本字串

    Returns:
        清理後的版本字串
    """
    if not version or version == "未知":
        return version
    cleaned = re.split(
        r"[+]|-mc|-fabric|-forge|-kotlin|-api|-universal|-common|-b[0-9]*|-beta|-alpha|-snapshot",
        version,
        flags=re.IGNORECASE,
    )[0]
    return re.sub(r"[^\w\d.]+$", "", cleaned).strip()


def extract_minecraft_version_from_text(text: str) -> str | None:
    """
    從日誌、manifest 或檔名文字擷取 Minecraft 版本

    Args:
        text: 待分析文字

    Returns:
        找到的版本字串；無結果時為 None
    """
    if not text:
        return None
    patterns = (
        (r"minecraft[-_.:\s]+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", 1),
        (r"mc[-_.:\s]+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", 1),
        (r"version[-_.:\s]+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", 1),
        (r"\b([0-9]+\.[0-9]+(?:\.[0-9]+)?-(?:pre|rc)[0-9]+)\b", 2),
        (r"\b([0-9]+\.[0-9]+-snapshot-[0-9]+)\b", 3),
        (r"\b(2[0-9]w[0-9]{1,2}[a-z])\b", 3),
        (r"\b([0-9]+\.[0-9]+(?:\.[0-9]+)?)\b", 4),
    )
    matches = [
        (match.group(1), priority)
        for pattern, priority in patterns
        if (match := re.search(pattern, text, re.IGNORECASE)) is not None
    ]
    return min(matches, key=lambda item: item[1])[0] if matches else None


@lru_cache(maxsize=128)
def detect_loader_from_text(text: str) -> str:
    """
    從文字辨認受支援的伺服器載入器

    Args:
        text: 待分析文字

    Returns:
        載入器名稱；無法辨認時為 unknown
    """
    normalized = str(text or "").lower()
    if re.search(r"\bvanilla\b|\bofficial\b|\bminecraft server\b", normalized):
        return "vanilla"
    for loader in ("fabric", "neoforge", "forge", "quilt"):
        if re.search(rf"\b{loader}\b", normalized):
            return loader
    return "unknown"


@lru_cache(maxsize=128)
def extract_forge_versions(path_text: str) -> tuple[str | None, str | None]:
    """
    從 Forge library 路徑或 JAR 名稱擷取 Minecraft 與 Forge 版本

    Args:
        path_text: Forge 路徑或檔名

    Returns:
        (minecraft_version, forge_version)；無法解析時兩者皆為 None
    """
    value = str(path_text or "").removesuffix(".jar").removeprefix("forge-")
    for pattern in (
        r"^(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?(?:\.\d+)?)$",
        r"^(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?(?:\.\d+)?)-.*$",
    ):
        if match := re.match(pattern, value):
            minecraft_version, forge_version = match.groups()
            if len(minecraft_version.split(".")) >= 2 and len(forge_version.split(".")) >= 2:
                return (minecraft_version, forge_version)
    return (None, None)


__all__ = [
    "clean_mod_version",
    "detect_loader_from_text",
    "extract_forge_versions",
    "extract_minecraft_version_from_text",
    "is_fabric_compatible_version",
    "normalize_minecraft_version",
    "standardize_loader_type",
]
