"""伺服器版本/載入器文字解析工具。

這個模組只負責「字串與版本資訊」相關的判斷，
避免與檔案掃描、啟動參數偵測邏輯混在同一檔案。
"""

from __future__ import annotations

import re

from . import get_logger

logger = get_logger().bind(component="ServerDetectionVersionUtils")

__all__ = ["ServerDetectionVersionUtils"]


class ServerDetectionVersionUtils:
    """版本與載入器文字解析工具。"""

    @staticmethod
    def parse_mc_version(version_str: str) -> list[int]:
        """版本數字列表，如 [1, 20, 1]。"""
        if not version_str or not isinstance(version_str, str):
            logger.debug(f"無效的 MC 版本字串: {version_str!r}")
            return []
        try:
            matches = re.findall(r"\d+", version_str)
            return [int(x) for x in matches] if matches else []
        except Exception as e:
            logger.exception(f"解析 MC 版本時發生錯誤: {e}")
            return []

    @staticmethod
    def is_fabric_compatible_version(mc_version: str) -> bool:
        """檢查 MC 版本是否與 Fabric 相容（1.14+）。"""
        try:
            version_parts = ServerDetectionVersionUtils.parse_mc_version(mc_version)
            if not version_parts:
                return False

            major = version_parts[0]
            minor = version_parts[1] if len(version_parts) > 1 else 0
            return bool(major > 1 or (major == 1 and minor >= 14))
        except Exception as e:
            logger.exception(f"檢查 Fabric 相容性時發生錯誤: {e}")
            return False

    @staticmethod
    def standardize_loader_type(loader_type: str, loader_version: str = "") -> str:
        """標準化載入器類型：將輸入轉為小寫並進行基本推斷。"""
        lt_low = loader_type.lower()
        if lt_low not in ["unknown", "未知"]:
            return lt_low

        if loader_version and loader_version.replace(".", "").isdigit():
            return "forge"
        if loader_version and "fabric" in loader_version.lower():
            return "fabric"
        return "vanilla"

    @staticmethod
    def normalize_mc_version(mc_version) -> str:
        """標準化 Minecraft 版本字串。"""
        if isinstance(mc_version, list) and mc_version:
            mc_version = str(mc_version[0])
        if isinstance(mc_version, str) and mc_version.startswith(("[", "(")):
            m = re.search(r"(\d+\.\d+)", mc_version)
            if m:
                mc_version = m.group(1)
        return mc_version

    @staticmethod
    def clean_version(version: str) -> str:
        """清理後的版本字串。"""
        if not version or version == "未知":
            return version

        cleaned = re.split(
            r"[+]|-mc|-fabric|-forge|-kotlin|-api|-universal|-common|-b[0-9]*|-beta|-alpha|-snapshot",
            version,
            flags=re.IGNORECASE,
        )[0]
        cleaned = re.sub(r"[^\w\d.]+$", "", cleaned)
        return cleaned.strip()

    @staticmethod
    def extract_mc_version_from_text(text: str) -> str | None:
        """從文本中提取 Minecraft 版本。"""
        if not text:
            return None

        patterns = [
            (r"minecraft[:\s]+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", 1),
            (r"mc[:\s]+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", 1),
            (r"version[:\s]+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", 1),
            (r"\b([0-9]+\.[0-9]+(?:\.[0-9]+)?-(?:pre|rc)[0-9]+)\b", 2),
            (r"\b([0-9]+\.[0-9]+-snapshot-[0-9]+)\b", 3),
            (r"\b(2[0-9]w[0-9]{1,2}[a-z])\b", 3),
            (r"\b([0-9]+\.[0-9]+(?:\.[0-9]+)?)\b", 4),
        ]

        matches = []
        for pattern, priority in patterns:
            found = re.search(pattern, text, re.IGNORECASE)
            if found:
                matches.append((found.group(1), priority))

        if matches:
            matches.sort(key=lambda item: item[1])
            return matches[0][0]
        return None

    @staticmethod
    def detect_loader_from_text(text: str) -> str:
        """從文本中偵測載入器類型。"""
        if not text:
            return "vanilla"

        text_lower = text.lower()
        if "fabric" in text_lower:
            return "fabric"
        if "forge" in text_lower:
            return "forge"
        return "vanilla"

    @staticmethod
    def extract_version_from_forge_path(path_str: str) -> tuple[str | None, str | None]:
        """從 Forge 路徑字串提取 (minecraft_version, forge_version)。"""
        if not path_str:
            return None, None

        clean_str = path_str
        if clean_str.endswith(".jar"):
            clean_str = clean_str[:-4]
        if clean_str.startswith("forge-"):
            clean_str = clean_str[6:]

        patterns = [
            r"^(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?(?:\.\d+)?)$",
            r"^(\d+\.\d+(?:\.\d+)?)-(\d+\.\d+(?:\.\d+)?(?:\.\d+)?)-.*$",
        ]

        for pattern in patterns:
            match = re.match(pattern, clean_str)
            if match:
                mc_ver = match.group(1)
                forge_ver = match.group(2)
                if mc_ver and forge_ver and len(mc_ver.split(".")) >= 2 and len(forge_ver.split(".")) >= 2:
                    return mc_ver, forge_ver
        return None, None
