"""
UI 狀態綁定與搜尋篩選工具
合併自 state_utils.py 與 search_utils.py
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .qt_runtime import ValueState


class Variable(ValueState):
    """
    通用變數狀態綁定
    支援當值改變時觸發註冊的回呼函式
    """

    def __init__(self, value: Any = None) -> None:
        super().__init__(value)
        self._callbacks: list[Callable[..., Any]] = []

    def set(self, value: Any) -> None:
        """
        設定目前值或顯示狀態

        Args:
            value: 要設定的新值
        """
        if self._value == value:
            return
        super().set(value)
        for callback in list(self._callbacks):
            callback()

    def trace_add(self, _mode: str, callback: Callable[..., Any]) -> str:
        """
        將回呼函式新增至監聽清單中

        Args:
            _mode: 監聽模式(未使用)
            callback: 要註冊的回呼函式，當值改變時會被呼叫

        Returns:
            str: 該回呼函式的唯一識別碼（ID）
        """
        self._callbacks.append(callback)
        return str(id(callback))

    def trace(self, mode: str, callback: Callable[..., Any]) -> str:
        """
        註冊變數變更監聽器

        Args:
            mode: 監聽模式
            callback: 要註冊的回呼函式，當值改變時會被呼叫

        Returns:
            str: 該回呼函式的唯一識別碼（ID）
        """
        return self.trace_add(mode, callback)


class TextState(Variable):
    """字串狀態變數"""

    def __init__(self, value: str = "") -> None:
        super().__init__(value)


class BoolState(Variable):
    """布林狀態變數"""

    def __init__(self, value: bool = False) -> None:
        super().__init__(bool(value))


class FloatState(Variable):
    """浮點數狀態變數"""

    def __init__(self, value: float = 0.0) -> None:
        super().__init__(float(value))


@dataclass(slots=True)
class SearchFilter:
    """搜尋元件共用的文字篩選器"""

    case_sensitive: bool = False
    normalize_whitespace: bool = True
    require_all_terms: bool = True

    def normalize(self, value: Any) -> str:
        """
        正規化搜尋文字

        Args:
            value: 要轉成搜尋字串的任意值

        Returns:
            正規化後的搜尋字串
        """
        text = str(value or "").strip()
        if self.normalize_whitespace:
            text = re.sub(r"\s+", " ", text)
        return text if self.case_sensitive else text.lower()

    def matches(self, candidate: Any, query: Any) -> bool:
        """
        判斷候選文字是否符合查詢字串

        Args:
            candidate: 被比對的候選值；可為字串、序列或 dict
            query: 使用者輸入的查詢值

        Returns:
            候選值符合查詢時回傳 True
        """
        normalized_query = self.normalize(query)
        if not normalized_query:
            return True
        candidate_text = " ".join(self.normalize(value) for value in self._candidate_values(candidate))
        if not candidate_text:
            return False
        if not self.require_all_terms:
            return normalized_query in candidate_text
        return all(term in candidate_text for term in normalized_query.split())

    def matches_any(self, candidates: Any, query: Any) -> bool:
        """
        判斷多個候選欄位是否符合查詢

        Args:
            candidates: 字串、序列或 dict 候選欄位
            query: 使用者輸入的搜尋字串

        Returns:
            任一候選欄位符合查詢時回傳 True
        """
        return self.matches(candidates, query)

    def _candidate_values(self, candidate: Any) -> list[Any]:
        if isinstance(candidate, Mapping):
            return list(candidate.values())
        if isinstance(candidate, (list, tuple, set, frozenset)):
            return list(candidate)
        return [candidate]


__all__ = ["BoolState", "FloatState", "SearchFilter", "TextState", "Variable"]
