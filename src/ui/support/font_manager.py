"""字體管理器模組"""

from __future__ import annotations

from contextlib import suppress
from functools import lru_cache
from typing import ClassVar

from PySide6 import QtGui

from src.utils import OperationError, get_logger

logger = get_logger().bind(component="FontManager")


PREFERRED_FONT_FAMILIES: tuple[str, ...] = (
    "Microsoft JhengHei UI",
    "Microsoft JhengHei",
    "Noto Sans CJK TC",
)


class FontManager:
    """字體管理器類別，負責 UI 字體快取"""

    _default_family_candidates: ClassVar[tuple[str, ...]] = PREFERRED_FONT_FAMILIES
    _default_family = ""

    @classmethod
    def _resolve_default_family(cls) -> str:
        if cls._default_family:
            return cls._default_family
        try:
            for family in cls._default_family_candidates:
                if QtGui.QFontDatabase.hasFamily(family):
                    cls._default_family = family
                    return family
            cls._default_family = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.GeneralFont).family()
        except Exception:
            cls._default_family = "Arial"
        return cls._default_family

    @classmethod
    def _resolve_family(cls, family: str | None) -> str:
        if not family:
            return cls._resolve_default_family()
        with suppress(Exception):
            if QtGui.QFontDatabase.hasFamily(family):
                return family
        return cls._resolve_default_family()

    @staticmethod
    @lru_cache(maxsize=128)
    def _build_font(
        family: str,
        size: int,
        weight: str,
        slant: str,
        underline: bool,
        overstrike: bool,
    ) -> QtGui.QFont:
        """建立指定樣式的 Qt 字型物件"""
        font = QtGui.QFont(family, int(size))
        font.setWeight(QtGui.QFont.Weight.Bold if weight.lower() == "bold" else QtGui.QFont.Weight.Normal)
        font.setItalic(slant.lower() in {"italic", "oblique"})
        font.setUnderline(underline)
        font.setStrikeOut(overstrike)
        return font

    @classmethod
    def get_font(
        cls,
        family: str | None = None,
        size: int = 9,
        weight: str = "normal",
        slant: str = "roman",
        underline: bool = False,
        overstrike: bool = False,
    ) -> QtGui.QFont:
        """
        取得字體物件並快取

        Args:
            family: 字體名稱；未提供時使用預設字體
            size: 基準字號
            weight: 字重
            slant: 斜體樣式
            underline: 是否加底線
            overstrike: 是否加刪除線

        Returns:
            建立或快取中的 QFont 物件
        """
        family = cls._resolve_family(family)
        try:
            return cls._build_font(family, int(size), weight, slant, underline, overstrike)
        except Exception as e:
            logger.exception(f"建立字體失敗 {family}, {size}, {weight}: {e}")
            return cls._get_fallback_font()

    @classmethod
    def _get_fallback_font(cls) -> QtGui.QFont:
        """取得回退字體"""
        try:
            return QtGui.QFont(cls._resolve_default_family(), 9)
        except Exception:
            raise OperationError("無法建立任何字體物件") from None

    @classmethod
    def clear_cache(cls) -> None:
        """
        清空字體快取

        這會使下一次取用字型時重新建立物件
        """
        cls._build_font.cache_clear()


__all__ = ["PREFERRED_FONT_FAMILIES", "FontManager"]
