"""字體管理器模組。

集中管理 UI 字體與 DPI 縮放，避免重複建立字體物件。
"""

from __future__ import annotations

import collections
from typing import ClassVar

import customtkinter as ctk

from ..utils.logger import get_logger

logger = get_logger().bind(component="FontManager")


class FontManager:
    """字體管理器類別，負責 UI 字體快取與 DPI 縮放。"""

    _fonts: ClassVar[collections.OrderedDict] = collections.OrderedDict()
    _default_family = "Microsoft JhengHei"
    _scale_factor = 1.0
    MAX_CACHE_SIZE = 128

    @classmethod
    def set_scale_factor(cls, scale_factor: float) -> None:
        """設定全域 UI 縮放因子。"""
        if 0.5 <= scale_factor <= 3.0:
            cls._scale_factor = scale_factor
            cls.clear_cache()

    @classmethod
    def get_scale_factor(cls) -> float:
        """取得目前的全域縮放因子。"""
        return cls._scale_factor

    @classmethod
    def get_font(
        cls,
        family: str | None = None,
        size: int = 12,
        weight: str = "normal",
        slant: str = "roman",
        underline: bool = False,
        overstrike: bool = False,
    ) -> ctk.CTkFont:
        """取得字體物件，並自動套用縮放與快取。

        Args:
            family: 字體名稱；未提供時使用預設字體。
            size: 基準字號。
            weight: 字重。
            slant: 斜體樣式。
            underline: 是否加底線。
            overstrike: 是否加刪除線。

        Returns:
            建立或快取中的 CTkFont 物件。
        """
        if family is None:
            family = cls._default_family
        scaled_size = int(size * cls._scale_factor)
        key = (family, scaled_size, weight, slant, underline, overstrike)
        if key in cls._fonts:
            cls._fonts.move_to_end(key)
            font = cls._fonts[key]
            try:
                if hasattr(font, "cget"):
                    _ = font.cget("family")
                return font
            except Exception:
                del cls._fonts[key]
        try:
            font = ctk.CTkFont(
                family=family, size=scaled_size, weight=weight, slant=slant, underline=underline, overstrike=overstrike
            )
            cls._fonts[key] = font
            if len(cls._fonts) > cls.MAX_CACHE_SIZE:
                cls._fonts.popitem(last=False)
            return font
        except Exception as exc:
            logger.exception(f"建立字體失敗 {family}, {scaled_size}, {weight}: {exc}")
            return cls._get_fallback_font()

    @classmethod
    def _get_fallback_font(cls) -> ctk.CTkFont:
        """取得回退字體。"""
        try:
            scaled_size = int(12 * cls._scale_factor)
            return ctk.CTkFont(family=cls._default_family, size=scaled_size, weight="normal")
        except Exception:
            raise RuntimeError("無法建立任何字體物件") from None

    @classmethod
    def clear_cache(cls) -> None:
        """清空字體快取。"""
        try:
            cls._fonts.clear()
        except Exception as exc:
            logger.exception(f"清理字體快取時發生錯誤: {exc}")

    @classmethod
    def get_dpi_scaled_size(cls, base_size: int) -> int:
        """取得 DPI 縮放後的尺寸。"""
        return int(base_size * cls._scale_factor)

    @staticmethod
    def cleanup_fonts() -> None:
        """清理字體快取。"""
        FontManager.clear_cache()


__all__ = ["FontManager"]
