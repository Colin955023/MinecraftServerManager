"""PySide6 Fluent Widgets 整合工具。"""

from __future__ import annotations

import importlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from PySide6 import QtCore, QtWidgets

from .ui_tokens import Colors

FLUENT_AVAILABLE = False

try:
    _qfluentwidgets = importlib.import_module("qfluentwidgets")
    _FluentLineEdit = _qfluentwidgets.LineEdit
    _FluentProgressBar = _qfluentwidgets.ProgressBar
    _FluentPushButton = _qfluentwidgets.PushButton
    _FluentSearchLineEdit = _qfluentwidgets.SearchLineEdit
    _Theme = _qfluentwidgets.Theme
    _setTheme = _qfluentwidgets.setTheme
    _setThemeColor = _qfluentwidgets.setThemeColor

    FLUENT_AVAILABLE = True
except Exception:
    _FluentLineEdit = QtWidgets.QLineEdit
    _FluentPushButton = QtWidgets.QPushButton
    _FluentProgressBar = QtWidgets.QProgressBar
    _Theme = None
    _setTheme = None
    _setThemeColor = None

    class _FallbackSearchLineEdit(QtWidgets.QLineEdit):
        """相容 qfluentwidgets signal 的後備搜尋輸入框。"""

        searchSignal = QtCore.Signal(str)
        clearSignal = QtCore.Signal()

        def __init__(self, parent: Any = None) -> None:
            super().__init__(parent)
            self.returnPressed.connect(self.search)

        def search(self) -> None:
            """將搜尋文字更新到輸入框。"""
            self.searchSignal.emit(self.text())

        def clear(self) -> None:
            """清除目前輸入內容。"""
            super().clear()
            self.clearSignal.emit()

        def setClearButtonEnabled(self, enable: bool) -> None:
            """設定清除按鈕是否可用。"""
            super().setClearButtonEnabled(enable)

    _FluentSearchLineEdit = _FallbackSearchLineEdit


FluentLineEdit = _FluentLineEdit
FluentPushButton = _FluentPushButton
FluentProgressBar = _FluentProgressBar
FluentSearchLineEdit = _FluentSearchLineEdit
Theme = _Theme
setTheme = _setTheme
setThemeColor = _setThemeColor


@dataclass(slots=True)
class SearchFilter:
    """搜尋元件共用的文字篩選器。"""

    case_sensitive: bool = False
    normalize_whitespace: bool = True
    require_all_terms: bool = True

    def normalize(self, value: Any) -> str:
        """正規化搜尋文字。

        Args:
            value: 要轉成搜尋字串的任意值。

        Returns:
            正規化後的搜尋字串。
        """
        text = str(value or "").strip()
        if self.normalize_whitespace:
            text = re.sub(r"\s+", " ", text)
        return text if self.case_sensitive else text.lower()

    def matches(self, candidate: Any, query: Any) -> bool:
        """判斷候選文字是否符合查詢字串。

        Args:
            candidate: 被比對的候選值；可為字串、序列或 dict。
            query: 使用者輸入的查詢值。

        Returns:
            候選值符合查詢時回傳 True。
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
        """判斷多個候選欄位是否符合查詢。

        Args:
            candidates: 字串、序列或 dict 候選欄位。
            query: 使用者輸入的搜尋字串。

        Returns:
            任一候選欄位符合查詢時回傳 True。
        """
        return self.matches(candidates, query)

    def _candidate_values(self, candidate: Any) -> list[Any]:
        if isinstance(candidate, Mapping):
            return list(candidate.values())
        if isinstance(candidate, (list, tuple, set, frozenset)):
            return list(candidate)
        return [candidate]


def apply_fluent_theme(*, dark: bool, accent_color: str | None = None) -> None:
    """在 qfluentwidgets 可用時套用 Fluent 主題。

    Args:
        dark: 是否套用深色主題。
        accent_color: Fluent accent 色碼；未提供時使用專案主要按鈕色。
    """

    if not FLUENT_AVAILABLE or Theme is None or setTheme is None:
        return
    try:
        setTheme(Theme.DARK if dark else Theme.LIGHT)
        if setThemeColor is not None:
            setThemeColor(accent_color or Colors.BUTTON_PRIMARY[0])
    except Exception:
        return


__all__ = [
    "FLUENT_AVAILABLE",
    "FluentLineEdit",
    "FluentProgressBar",
    "FluentPushButton",
    "FluentSearchLineEdit",
    "SearchFilter",
    "apply_fluent_theme",
]
