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
    """字體管理器類別 - 單例模式，支援 UI 縮放和字體快取管理
    Font Manager class - Singleton pattern with UI scaling and font cache management support
    """

    _instance = None
    _initialized = False
    MAX_CACHE_SIZE = 128

    # ====== 單例模式實現 ======
    def __new__(cls) -> "FontManager":
        """單例模式的實例建立方法，確保全域只有一個字體管理器
        Singleton pattern instance creation method ensuring only one font manager globally

        Args:
            None

        Returns:
            FontManager: 字體管理器實例

        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._fonts: collections.OrderedDict = collections.OrderedDict()
            self._default_family = "Microsoft JhengHei"
            self._scale_factor = 1.0
            FontManager._initialized = True

    # ====== 縮放因子管理 ======
    def set_scale_factor(self, scale_factor: float) -> None:
        """設定全域 UI 縮放因子，影響所有字體大小
        Set global UI scale factor affecting all font sizes

        Args:
            scale_factor (float): 縮放因子 (0.5-3.0)

        Returns:
            None

        """
        if 0.5 <= scale_factor <= 3.0:  # 限制在合理範圍
            self._scale_factor = scale_factor
            self.clear_cache()

    def get_scale_factor(self) -> float:
        """取得當前設定的全域縮放因子
        Get current global scale factor setting

        Args:
            None

        Returns:
            float: 當前縮放因子

        """
        return self._scale_factor

    # ====== 字體物件管理 ======
    def get_font(
        self,
        family: str | None = None,
        size: int = 12,
        weight: str = "normal",
        slant: str = "roman",
        underline: bool = False,
        overstrike: bool = False,
    ) -> ctk.CTkFont:
        """取得字體物件，自動應用縮放並管理快取，避免重複建立
        Get font object with automatic scaling and cache management to avoid duplicate creation

        Args:
            family (str): 字體家族名稱，預設為 Microsoft JhengHei
            size (int): 基礎字體大小，將被縮放因子調整
            weight (str): 字體粗細 (normal, bold)
            slant (str): 字體傾斜 (roman, italic)
            underline (bool): 下底線
            overstrike (bool): 刪除線

        Returns:
            ctk.CTkFont: CustomTkinter 字體物件

        """
        if family is None:
            family = self._default_family

        scaled_size = int(size * self._scale_factor)
        key = (family, scaled_size, weight, slant, underline, overstrike)

        if key in self._fonts:
            self._fonts.move_to_end(key)
            font = self._fonts[key]
            try:
                _ = font.cget("family")
                return font
            except Exception:
                del self._fonts[key]

        try:
            font = ctk.CTkFont(
                family=family,
                size=scaled_size,
                weight=weight,
                slant=slant,
                underline=underline,
                overstrike=overstrike,
            )

            self._fonts[key] = font

            if len(self._fonts) > self.MAX_CACHE_SIZE:
                self._fonts.popitem(last=False)

            return font
        except Exception as e:
            logger.exception(f"建立字體失敗 {family}, {scaled_size}, {weight}: {e}")
            return self._get_fallback_font()

    def _get_fallback_font(self) -> ctk.CTkFont:
        """取得回退字體，當主要字體建立失敗時使用
        Get fallback font when primary font creation fails

        Args:
            None

        Returns:
            ctk.CTkFont: 回退字體物件，失敗時返回 None

        """
        try:
            scaled_size = int(12 * self._scale_factor)
            return ctk.CTkFont(family=self._default_family, size=scaled_size, weight="normal")
        except Exception:
            return None

    # ====== 快取管理功能 ======
    def clear_cache(self) -> None:
        try:
            for font in list(self._fonts.values()):
                try:
                    if hasattr(font, "destroy"):
                        pass
                except Exception as e:
                    logger.exception(f"銷毀字體物件失敗: {e}")

            self._fonts.clear()

        except Exception as e:
            logger.exception(f"清理字體快取時發生錯誤: {e}")


# ====== 全域實例與便利函數 ======
font_manager = FontManager()


def get_font(
    family: str | None = None,
    size: int = 12,
    weight: str = "normal",
    slant: str = "roman",
    underline: bool = False,
    overstrike: bool = False,
) -> ctk.CTkFont:
    """便利函數：取得字體，自動應用當前縮放因子
    Convenience function: Get font with automatic current scale factor application

    Args:
        family (str): 字體家族名稱
        size (int): 字體大小
        weight (str): 字體粗細
        slant (str): 字體傾斜
        underline (bool): 下底線
        overstrike (bool): 刪除線

    Returns:
        ctk.CTkFont: 字體物件

    """
    return font_manager.get_font(family, size, weight, slant, underline, overstrike)


def set_ui_scale_factor(scale_factor: float) -> None:
    """設定全域 UI 縮放因子的便利函數
    Convenience function to set global UI scale factor

    Args:
        scale_factor (float): 縮放因子

    Returns:
        None

    """
    font_manager.set_scale_factor(scale_factor)


def get_scale_factor() -> float:
    """取得全域縮放因子的便利函數
    Convenience function to get global scale factor

    Args:
        None

    Returns:
        float: 縮放因子

    """
    return font_manager.get_scale_factor()


def get_dpi_scaled_size(base_size: int) -> int:
    """取得 DPI 縮放後的尺寸，適用於非字體元素
    Get DPI scaled size for non-font elements

    Args:
        base_size (int): 基礎尺寸

    Returns:
        int: 縮放後的尺寸

    """
    return int(base_size * font_manager.get_scale_factor())


def cleanup_fonts() -> None:
    font_manager.clear_cache()
