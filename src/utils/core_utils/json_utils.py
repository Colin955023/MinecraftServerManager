"""JSON 讀取與序列化工具"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import orjson

from .filesystem_utils import SAFE_TEXT_FILE_MAX_BYTES, read_bytes_file


def read_json(
    path: Path | str,
    default: Any = None,
    *,
    max_bytes: int | None = SAFE_TEXT_FILE_MAX_BYTES,
    allowed_root: Path | str | None = None,
) -> Any:
    """
    讀取 JSON；檔案不存在、無法讀取或格式錯誤時回傳預設值

    Args:
        path: JSON 檔案路徑
        default: 讀取失敗時的預設值
        max_bytes: JSON 檔案大小上限；未指定或傳入 None 時使用安全預設值
        allowed_root: 可選的實際路徑根目錄

    Returns:
        解析後的資料，失敗時回傳 default
    """
    try:
        limit = SAFE_TEXT_FILE_MAX_BYTES if max_bytes is None else int(max_bytes)
        if limit < 0:
            return default
        payload = read_bytes_file(path, max_bytes=limit, allowed_root=allowed_root)
        if payload is None:
            return default
        return orjson.loads(payload)
    except OSError, TypeError, ValueError, orjson.JSONDecodeError:
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
