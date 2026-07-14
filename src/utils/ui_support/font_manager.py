"""字體管理器模組。"""

from __future__ import annotations

import collections
from typing import ClassVar

from PySide6 import QtGui

from .. import get_logger

logger = get_logger().bind(component="FontManager")


class FontManager:
    """字體管理器類別，負責 UI 字體快取。"""

    _fonts: ClassVar[collections.OrderedDict] = collections.OrderedDict()
    _default_family_candidates: ClassVar[tuple[str, ...]] = (
        "Microsoft JhengHei UI",
        "Microsoft JhengHei",
        "Noto Sans CJK TC",
    )
    _default_family = ""
    MAX_CACHE_SIZE = 128

    @classmethod
    def _resolve_default_family(cls) -> str:
        if cls._default_family:
            return cls._default_family
        try:
            families = set(QtGui.QFontDatabase.families())
            for family in cls._default_family_candidates:
                if family in families:
                    cls._default_family = family
                    logger.debug(f"已解析預設字體為: {family}")
                    return family
            cls._default_family = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.GeneralFont).family()
            logger.debug(f"找不到首選字體，使用系統預設: {cls._default_family}")
        except Exception:
            cls._default_family = "Arial"
            logger.debug("字體解析發生例外，回退至 Arial")
        return cls._default_family

    @classmethod
    def _resolve_family(cls, family: str | None) -> str:
        if not family:
            return cls._resolve_default_family()
        try:
            if family in set(QtGui.QFontDatabase.families()):
                return family
        except Exception as exc:
            logger.debug(f"字體資料庫查詢失敗，改用預設字體: {exc}")
        return cls._resolve_default_family()

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
        取得字體物件並快取。

        Args:
            family: 字體名稱；未提供時使用預設字體。
            size: 基準字號。
            weight: 字重。
            slant: 斜體樣式。
            underline: 是否加底線。
            overstrike: 是否加刪除線。

        Returns:
            建立或快取中的 QFont 物件。
        """
        family = cls._resolve_family(family)
        key = (family, size, weight, slant, underline, overstrike)
        if key in cls._fonts:
            cls._fonts.move_to_end(key)
            font = cls._fonts[key]
            try:
                _ = font.family()
                return font
            except Exception:
                del cls._fonts[key]
        try:
            font = QtGui.QFont(family, int(size))
            font.setWeight(QtGui.QFont.Weight.Bold if weight.lower() == "bold" else QtGui.QFont.Weight.Normal)
            font.setItalic(slant.lower() in {"italic", "oblique"})
            font.setUnderline(underline)
            font.setStrikeOut(overstrike)
            cls._fonts[key] = font
            if len(cls._fonts) > cls.MAX_CACHE_SIZE:
                cls._fonts.popitem(last=False)
            return font
        except Exception as exc:
            logger.exception(f"建立字體失敗 {family}, {size}, {weight}: {exc}")
            return cls._get_fallback_font()

    @classmethod
    def _get_fallback_font(cls) -> QtGui.QFont:
        """取得回退字體。"""
        try:
            return QtGui.QFont(cls._resolve_default_family(), 9)
        except Exception:
            raise RuntimeError("無法建立任何字體物件") from None

    @classmethod
    def clear_cache(cls) -> None:
        """清空字體快取。"""
        try:
            cls._fonts.clear()
        except Exception as exc:
            logger.exception(f"清理字體快取時發生錯誤: {exc}")


__all__ = ["FontManager"]
