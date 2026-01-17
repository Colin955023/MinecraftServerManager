#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字體管理器模組
提供統一的字體管理功能，支援 DPI 縮放和字體快取，避免重複建立字體物件
Font Manager Module
Provides unified font management functionality with DPI scaling and font caching to avoid duplicate font object creation
"""
# ====== 標準函式庫 ======
from typing import Dict, Tuple
import weakref
import customtkinter as ctk
# ======專案內部模組 ======
from src.utils import LogUtils

class FontManager:
    """
    字體管理器類別 - 單例模式，支援 UI 縮放和字體快取管理
    Font Manager class - Singleton pattern with UI scaling and font cache management support
    """

    _instance = None
    _initialized = False

    # ====== 單例模式實現 ======
    # 單例模式建構子
    def __new__(cls) -> "FontManager":
        """
        單例模式的實例建立方法，確保全域只有一個字體管理器
        Singleton pattern instance creation method ensuring only one font manager globally

        Args:
            None

        Returns:
            FontManager: 字體管理器實例
        """
        if cls._instance is None:
            cls._instance = super(FontManager, cls).__new__(cls)
        return cls._instance

    # 初始化字體管理器
    def __init__(self):
        """
        初始化字體管理器，設定預設字體和縮放參數
        Initialize font manager with default font and scaling parameters

        Args:
            None

        Returns:
            None
        """
        if not self._initialized:
            self._fonts: Dict[Tuple[str, int, str], ctk.CTkFont] = {}
            self._font_refs: Dict[Tuple[str, int, str], weakref.ref] = {}
            self._default_family = "Microsoft JhengHei"
            self._scale_factor = 1.0  # 預設縮放因子
            FontManager._initialized = True

    # ====== 縮放因子管理 ======
    # 設定全域縮放因子
    def set_scale_factor(self, scale_factor: float) -> None:
        """
        設定全域 UI 縮放因子，影響所有字體大小
        Set global UI scale factor affecting all font sizes

        Args:
            scale_factor (float): 縮放因子 (0.5-3.0)

        Returns:
            None
        """
        if 0.5 <= scale_factor <= 3.0:  # 限制在合理範圍
            self._scale_factor = scale_factor
            # 清理快取讓新的縮放生效
            self.clear_cache()

    # 取得目前縮放因子
    def get_scale_factor(self) -> float:
        """
        取得當前設定的全域縮放因子
        Get current global scale factor setting

        Args:
            None

        Returns:
            float: 當前縮放因子
        """
        return self._scale_factor

    # ====== 字體物件管理 ======
    # 取得字體物件
    def get_font(
        self, family: str = None, size: int = 12, weight: str = "normal"
    ) -> ctk.CTkFont:
        """
        取得字體物件，自動應用縮放並管理快取，避免重複建立
        Get font object with automatic scaling and cache management to avoid duplicate creation

        Args:
            family (str): 字體家族名稱，預設為 Microsoft JhengHei
            size (int): 基礎字體大小，將被縮放因子調整
            weight (str): 字體粗細 (normal, bold)

        Returns:
            ctk.CTkFont: CustomTkinter 字體物件
        """
        if family is None:
            family = self._default_family

        # 應用縮放因子
        scaled_size = int(size * self._scale_factor)
        key = (family, scaled_size, weight)

        # 檢查是否已存在且有效的字體
        if key in self._fonts:
            font = self._fonts[key]
            try:
                # 測試字體是否仍然有效
                _ = font.cget("family")
                return font
            except Exception:
                # 字體已無效，移除引用
                del self._fonts[key]
                if key in self._font_refs:
                    del self._font_refs[key]

        # 建立新字體
        try:
            font = ctk.CTkFont(family=family, size=scaled_size, weight=weight)
            self._fonts[key] = font
            # 建立弱引用用於清理
            self._font_refs[key] = weakref.ref(
                font, lambda ref: self._cleanup_font(key)
            )
            return font
        except Exception as e:
            LogUtils.error_exc(
                f"建立字體失敗 {family}, {scaled_size}, {weight}: {e}", "FontManager", e
            )
            # 回退到預設字體
            return self._get_fallback_font()

    # 清理無效字體引用
    def _cleanup_font(self, key: Tuple[str, int, str]) -> None:
        """
        清理無效的字體引用，釋放記憶體資源
        Clean up invalid font references to free memory resources

        Args:
            key (Tuple[str, int, str]): 字體識別鍵值

        Returns:
            None
        """
        if key in self._fonts:
            del self._fonts[key]
        if key in self._font_refs:
            del self._font_refs[key]

    # 取得回退字體
    def _get_fallback_font(self) -> ctk.CTkFont:
        """
        取得回退字體，當主要字體建立失敗時使用
        Get fallback font when primary font creation fails

        Args:
            None

        Returns:
            ctk.CTkFont: 回退字體物件，失敗時返回 None
        """
        try:
            scaled_size = int(12 * self._scale_factor)
            return ctk.CTkFont(
                family=self._default_family, size=scaled_size, weight="normal"
            )
        except Exception:
            # 如果連預設字體都失敗，返回 None，讓元件使用系統預設
            return None

    # ====== 快取管理功能 ======
    # 清理字體快取
    def clear_cache(self) -> None:
        """
        清理所有字體快取，釋放記憶體資源
        Clear all font cache to free memory resources

        Args:
            None

        Returns:
            None
        """
        try:
            # 清理所有字體引用
            for font in list(self._fonts.values()):
                try:
                    if hasattr(font, "destroy"):
                        font.destroy()
                except Exception as e:
                    LogUtils.error_exc(f"銷毀字體物件失敗: {e}", "FontManager", e)

            self._fonts.clear()
            self._font_refs.clear()

        except Exception as e:
            LogUtils.error_exc(f"清理字體快取時發生錯誤: {e}", "FontManager", e)

# ====== 全域實例與便利函數 ======
# 全域字體管理器實例
font_manager = FontManager()

# 便利函數：取得字體
def get_font(family: str = None, size: int = 12, weight: str = "normal") -> ctk.CTkFont:
    """
    便利函數：取得字體，自動應用當前縮放因子
    Convenience function: Get font with automatic current scale factor application

    Args:
        family (str): 字體家族名稱
        size (int): 字體大小
        weight (str): 字體粗細

    Returns:
        ctk.CTkFont: 字體物件
    """
    return font_manager.get_font(family, size, weight)

# 設定全域 UI 縮放因子
def set_ui_scale_factor(scale_factor: float) -> None:
    """
    設定全域 UI 縮放因子的便利函數
    Convenience function to set global UI scale factor

    Args:
        scale_factor (float): 縮放因子

    Returns:
        None
    """
    font_manager.set_scale_factor(scale_factor)

# 取得全域縮放因子
def get_scale_factor() -> float:
    """
    取得全域縮放因子的便利函數
    Convenience function to get global scale factor

    Args:
        None

    Returns:
        float: 縮放因子
    """
    return font_manager.get_scale_factor()

# 取得 DPI 縮放後的尺寸
def get_dpi_scaled_size(base_size: int) -> int:
    """
    取得 DPI 縮放後的尺寸，適用於非字體元素
    Get DPI scaled size for non-font elements

    Args:
        base_size (int): 基礎尺寸

    Returns:
        int: 縮放後的尺寸
    """
    return int(base_size * font_manager.get_scale_factor())

# 清理字體的便利函數
def cleanup_fonts() -> None:
    """
    清理字體快取的便利函數
    Convenience function to clean up font cache

    Args:
        None

    Returns:
        None
    """
    font_manager.clear_cache()
