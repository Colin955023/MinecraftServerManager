"""JSON 讀取與序列化工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import orjson


def read_json(path: Path | str, default: Any = None) -> Any:
    """
    讀取 JSON；檔案不存在、無法讀取或格式錯誤時回傳預設值

    Args:
        path: JSON 檔案路徑
        default: 讀取失敗時的預設值

    Returns:
        解析後的資料，失敗時回傳 default
    """
    try:
        target = Path(path)
        if not target.exists():
            return default
        return orjson.loads(target.read_bytes())
    except OSError, orjson.JSONDecodeError:
        return default


def serialize_json(data: Any, indent: int | None = None) -> str:
    """
    將資料序列化為 JSON 字串

    Args:
        data: 待序列化資料
        indent: 縮排層級，目前支援 2 或無縮排

    Returns:
        JSON 字串；不可序列化時回傳空字串
    """
    option = orjson.OPT_INDENT_2 if indent == 2 else 0
    option |= orjson.OPT_NON_STR_KEYS
    try:
        return orjson.dumps(data, option=option).decode("utf-8")
    except TypeError:
        return ""


__all__ = ["read_json", "serialize_json"]
