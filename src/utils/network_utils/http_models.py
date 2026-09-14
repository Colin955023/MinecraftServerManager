"""HTTP 傳輸結果"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

type JSONContainer = dict[str, Any] | list[Any]


@dataclass(frozen=True, slots=True)
class HTTPJSONResponse:
    """保留 HTTP 狀態與失敗類型的 JSON 結果"""

    status_code: int | None
    payload: JSONContainer | None = None
    error_kind: str = ""


__all__ = ["HTTPJSONResponse", "JSONContainer"]
