"""
版本字串安全解析工具
統一 packaging.version.Version 的防呆包裝，供 core / utils 各模組共用

取代：
  - LoaderManager.parse_version_safe       (core/loader_manager.py)
  - ServerDetectionVersionUtils._parse_packaging_version  (utils/server_utils/server_detection_utils.py)
  - UpdateParsing.parse_version body       (utils/update_utils/update_parsing.py)
"""

from __future__ import annotations

import re
from contextlib import suppress

from packaging.version import InvalidVersion, Version


def parse_version_safe(
    version_str: str | None,
    *,
    fallback: Version | None = None,
) -> Version | None:
    """
    安全解析版本字串為 PEP 440 Version 物件

    解析流程：
    1. 去除前置 v/V（後接數字時）
    2. 嘗試 packaging.version.Version 直接解析
    3. 失敗時擷取最長數字片段（x.y.z.w）再解析
    4. 仍失敗時回傳 fallback

    Args:
        version_str: 原始版本字串，允許 None
        fallback:    解析失敗時的回傳值，預設 None

    Returns:
        解析後的 Version，或 fallback
    """
    candidate = str(version_str or "").strip()
    if not candidate:
        return fallback
    if candidate[:1].lower() == "v" and len(candidate) > 1 and candidate[1].isdigit():
        candidate = candidate[1:]
    try:
        return Version(candidate)
    except InvalidVersion:
        match = re.search(r"\d+(?:\.\d+){0,3}", candidate)
        if match:
            with suppress(InvalidVersion):
                return Version(match.group(0))
        return fallback


__all__ = ["parse_version_safe"]
