#!/usr/bin/env python3
"""字體管理器模組
提供統一的字體管理功能，支援 DPI 縮放和字體快取，避免重複建立字體物件
Font Manager Module
Provides unified font management functionality with DPI scaling and font caching to avoid duplicate font object creation
"""

import collections

# typing imports removed - using | syntax instead
import customtkinter as ctk

from .logger import get_logger

logger = get_logger().bind(component="FontManager")


class FontManager:
    """字體管理器類別 - 靜態類別模式，支援 UI 縮放和字體快取管理"""

    _fonts: collections.OrderedDict = collections.OrderedDict()
    _default_family = "Microsoft JhengHei"
    _scale_factor = 1.0
    MAX_CACHE_SIZE = 128

    # ====== 縮放因子管理 ======
    @classmethod
    def set_scale_factor(cls, scale_factor: float) -> None:
        """設定全域 UI 縮放因子，影響所有字體大小"""
        if 0.5 <= scale_factor <= 3.0:  # 限制在合理範圍
            cls._scale_factor = scale_factor
            cls.clear_cache()

    @classmethod
    def get_scale_factor(cls) -> float:
        """取得當前設定的全域縮放因子"""
        return cls._scale_factor

    # ====== 字體物件管理 ======
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
        """取得字體物件，自動應用縮放並管理快取"""
        if family is None:
            family = cls._default_family

        scaled_size = int(size * cls._scale_factor)
        key = (family, scaled_size, weight, slant, underline, overstrike)

        if key in cls._fonts:
            cls._fonts.move_to_end(key)
            font = cls._fonts[key]
            try:
                # 簡單檢查字體物件是否有效
                if hasattr(font, "cget"):
                    _ = font.cget("family")
                return font
            except Exception:
                del cls._fonts[key]

        try:
            font = ctk.CTkFont(
                family=family,
                size=scaled_size,
                weight=weight,
                slant=slant,
                underline=underline,
                overstrike=overstrike,
            )

            cls._fonts[key] = font

            if len(cls._fonts) > cls.MAX_CACHE_SIZE:
                cls._fonts.popitem(last=False)

            return font
        except Exception as e:
            logger.exception(f"建立字體失敗 {family}, {scaled_size}, {weight}: {e}")
            return cls._get_fallback_font()

    @classmethod
    def _get_fallback_font(cls) -> ctk.CTkFont:
        """取得回退字體"""
        try:
            scaled_size = int(12 * cls._scale_factor)
            return ctk.CTkFont(family=cls._default_family, size=scaled_size, weight="normal")
        except Exception:
            # 極端情況下連回退字體都建立失敗
            raise RuntimeError("無法建立任何字體物件") from None

    # ====== 快取管理功能 ======
    @classmethod
    def clear_cache(cls) -> None:
        try:
            cls._fonts.clear()
        except Exception as e:
            logger.exception(f"清理字體快取時發生錯誤: {e}")

    @classmethod
    def get_dpi_scaled_size(cls, base_size: int) -> int:
        """取得 DPI 縮放後的尺寸，適用於非字體元素"""
        return int(base_size * cls._scale_factor)

    @staticmethod
    def cleanup_fonts() -> None:
        """清理字體快取"""
        FontManager.clear_cache()
