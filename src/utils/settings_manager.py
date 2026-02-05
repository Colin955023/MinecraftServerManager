#!/usr/bin/env python3
"""設定管理器模組
提供統一的使用者設定管理功能，包含自動更新、視窗偏好、除錯設定等
Settings Manager Module
Provides unified user settings management including auto-update, window preferences, debug settings etc.
"""

import sys
from typing import Any

from . import PathUtils, RuntimePaths, get_logger

logger = get_logger().bind(component="SettingsManager")

# ====== 預設設定常數 Default Settings Constants ======
DEFAULT_WINDOW_PREFERENCES = {
    "remember_size_position": True,  # 記住視窗大小和位置
    "main_window": {
        "width": 1200,
        "height": 800,
        "x": None,  # None 表示置中
        "y": None,
        "maximized": False,
    },
    "auto_center": True,  # 自動置中新視窗
    "adaptive_sizing": True,  # 根據螢幕大小自動調整
    "dpi_scaling": 1.0,  # DPI 縮放因子
}


def _get_default_settings() -> dict[str, Any]:
    """取得預設設定（根據環境動態計算）"""
    # 透過檢查是否為打包環境來設定除錯日誌預設值
    # 支援 PyInstaller (frozen/MEIPASS) 和 Nuitka (__compiled__)
    is_nuitka = "__compiled__" in globals()
    is_packaged = bool(getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS") or is_nuitka)
    # 開發環境預設啟用除錯日誌，打包環境預設關閉
    default_debug_logging = not is_packaged

    return {
        "servers_root": "",
        "auto_update_enabled": True,  # 預設啟用自動更新
        "first_run_completed": False,  # 標記是否已完成首次執行提示
        "window_preferences": DEFAULT_WINDOW_PREFERENCES.copy(),
        "debug_settings": {
            "enable_debug_logging": default_debug_logging,  # 根據環境設定除錯日誌預設值
            "enable_window_state_logging": False,  # 控制視窗狀態儲存日誌
        },
    }


class SettingsManager:
    """統一管理所有使用者設定的管理器類別"""

    # ====== 初始化與檔案操作 ======
    def __init__(self):
        self.settings_path = RuntimePaths.ensure_dir(RuntimePaths.get_user_data_dir()) / "user_settings.json"
        self._settings = self._load_settings()

    def _load_settings(self) -> dict[str, Any]:
        if not self.settings_path.exists():
            # 建立預設設定
            default_settings = _get_default_settings()
            self._save_settings(default_settings)
            return default_settings

        settings = PathUtils.load_json(self.settings_path)
        if not settings:
            # 如果載入失敗，回傳預設設定
            return _get_default_settings()

        # 確保所有必要的鍵值都存在（向後相容性）
        if "auto_update_enabled" not in settings:
            settings["auto_update_enabled"] = True
        if "first_run_completed" not in settings:
            settings["first_run_completed"] = False
        if "window_preferences" not in settings:
            settings["window_preferences"] = DEFAULT_WINDOW_PREFERENCES.copy()

        return settings

    def _save_settings(self, settings: dict[str, Any]) -> None:
        if not PathUtils.save_json(self.settings_path, settings):
            logger.error("無法寫入 user_settings.json")

    # ====== 基本設定操作 ======
    def get(self, key: str, default: Any = None) -> Any:
        """取得指定鍵值的設定資料"""
        return self._settings.get(key, default)

    def set(self, key: str, value: Any, immediate_save: bool = True) -> None:
        """設定指定鍵值的資料（可選擇立即儲存或延遲儲存以支援批次更新）"""
        self._settings[key] = value
        if immediate_save:
            self._save_settings(self._settings)

    def update_batch(self, updates: dict) -> None:
        """批次更新多個設定值並一次性儲存（優化 I/O 效能）"""
        self._settings.update(updates)
        self._save_settings(self._settings)

    # ====== 伺服器根目錄管理 ======
    def get_servers_root(self) -> str:
        """取得使用者設定的伺服器根目錄路徑"""
        return str(self._settings.get("servers_root", "")).strip()

    def set_servers_root(self, path: str) -> None:
        self.set("servers_root", path)

    # ====== 自動更新設定管理 ======
    def is_auto_update_enabled(self) -> bool:
        return bool(self._settings.get("auto_update_enabled", True))

    def set_auto_update_enabled(self, enabled: bool) -> None:
        self.set("auto_update_enabled", enabled)

    # ====== 首次執行狀態管理 ======
    def is_first_run_completed(self) -> bool:
        return bool(self._settings.get("first_run_completed", False))

    def mark_first_run_completed(self) -> None:
        self.set("first_run_completed", True)

    # ====== 視窗偏好設定管理 ======
    def get_window_preferences(self) -> dict[str, Any]:
        return self._settings.get("window_preferences", {})

    def is_remember_size_position_enabled(self) -> bool:
        return self.get_window_preferences().get("remember_size_position", True)

    def set_remember_size_position(self, enabled: bool) -> None:
        prefs = self.get_window_preferences()
        prefs["remember_size_position"] = enabled
        self.set("window_preferences", prefs)

    # 取得主視窗設定
    def get_main_window_settings(self) -> dict[str, Any]:
        """取得主視窗的大小、位置和狀態設定"""
        default_settings = {
            "width": 1200,
            "height": 800,
            "x": None,
            "y": None,
            "maximized": False,
        }
        return self.get_window_preferences().get("main_window", default_settings)

    # 設定主視窗大小位置
    def set_main_window_settings(
        self,
        width: int,
        height: int,
        x: int | None = None,
        y: int | None = None,
        maximized: bool = False,
    ) -> None:
        """設定主視窗的大小、位置和最大化狀態"""
        prefs = self.get_window_preferences()
        prefs["main_window"] = {
            "width": width,
            "height": height,
            "x": x,
            "y": y,
            "maximized": maximized,
        }
        self.set("window_preferences", prefs)

    # 檢查是否自動置中新視窗
    def is_auto_center_enabled(self) -> bool:
        """檢查是否啟用自動置中新視窗的功能"""
        return self.get_window_preferences().get("auto_center", True)

    # 設定自動置中新視窗
    def set_auto_center(self, enabled: bool) -> None:
        """設定是否自動置中新視窗的功能"""
        prefs = self.get_window_preferences()
        prefs["auto_center"] = enabled
        self.set("window_preferences", prefs)

    # 檢查是否啟用自適應大小調整
    def is_adaptive_sizing_enabled(self) -> bool:
        """檢查是否啟用根據螢幕大小自適應調整視窗的功能"""
        return self.get_window_preferences().get("adaptive_sizing", True)

    # 設定自適應大小調整
    def set_adaptive_sizing(self, enabled: bool) -> None:
        """設定是否啟用根據螢幕大小自適應調整視窗的功能"""
        prefs = self.get_window_preferences()
        prefs["adaptive_sizing"] = enabled
        self.set("window_preferences", prefs)

    # 取得 DPI 縮放因子
    def get_dpi_scaling(self) -> float:
        """取得當前設定的 DPI 縮放因子，預設為 1.0"""
        return float(self.get_window_preferences().get("dpi_scaling", 1.0))

    # 設定 DPI 縮放因子
    def set_dpi_scaling(self, scaling: float) -> None:
        """設定 DPI 縮放因子，會自動限制在合理範圍內（0.5-3.0）"""
        prefs = self.get_window_preferences()
        prefs["dpi_scaling"] = max(0.5, min(3.0, scaling))  # 限制在 0.5-3.0 範圍內
        self.set("window_preferences", prefs)

    # ====== 除錯設定管理 ======
    # 取得除錯設定
    def get_debug_settings(self) -> dict[str, Any]:
        """取得所有除錯相關的設定"""
        return self._settings.get(
            "debug_settings",
            {"enable_debug_logging": False, "enable_window_state_logging": False},
        )

    # 檢查是否啟用除錯日誌
    def is_debug_logging_enabled(self) -> bool:
        """檢查是否啟用除錯日誌輸出功能"""
        return self.get_debug_settings().get("enable_debug_logging", False)

    # 設定除錯日誌開關
    def set_debug_logging(self, enabled: bool) -> None:
        """設定除錯日誌輸出功能的開關"""
        debug_settings = self.get_debug_settings()
        debug_settings["enable_debug_logging"] = enabled
        self.set("debug_settings", debug_settings)


# ====== 全域實例管理 ======
# 全域設定管理器實例
_settings_manager = None


# 取得全域設定管理器實例
def get_settings_manager() -> SettingsManager:
    """取得全域設定管理器的單例實例"""
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
    return _settings_manager
