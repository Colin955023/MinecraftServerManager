"""通用操作結果"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OperationResult:
    """不屬於特定領域的操作結果"""

    success: bool
    message: str = ""
    error: Exception | None = None


__all__ = ["OperationResult"]
