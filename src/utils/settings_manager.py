#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
設定管理器模組
提供統一的使用者設定管理功能，包含自動更新、視窗偏好、調試設定等
Settings Manager Module
Provides unified user settings management including auto-update, window preferences, debug settings etc.
"""
# ====== 標準函式庫 ======
from typing import Any, Dict
import json
import sys
# ====== 專案內部模組 ======
from src.utils import LogUtils, ensure_dir, get_user_data_dir

class SettingsManager:
    """
    統一管理所有使用者設定的管理器類別
    Centralized manager class for all user settings including auto-update and window preferences
    """
    # ====== 初始化與檔案操作 ======
    # 初始化設定管理器
    def __init__(self):
        """
        初始化設定管理器，載入或建立使用者設定檔案
        Initialize settings manager, load or create user settings file

        Args:
            None

        Returns:
            None
        """
        self.settings_path = ensure_dir(get_user_data_dir()) / "user_settings.json"
        self._settings = self._load_settings()

    # 載入設定檔案
    def _load_settings(self) -> Dict[str, Any]:
        """
        載入使用者設定檔案，如不存在則建立預設設定
        Load user settings file, create default settings if it doesn't exist

        Args:
            None

        Returns:
            Dict[str, Any]: 設定資料字典
        """
        if not self.settings_path.exists():
            # 建立預設設定
            # 透過檢查是否為打包環境來設定調試日誌預設值
            is_packaged = bool(
                getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")
            )
            # 開發環境預設啟用調試日誌，打包環境預設關閉
            default_debug_logging = not is_packaged

            default_settings = {
                "servers_root": "",
                "auto_update_enabled": True,  # 預設啟用自動更新
                "first_run_completed": False,  # 標記是否已完成首次執行提示
                "window_preferences": {
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
                },
                "debug_settings": {
                    "enable_debug_logging": default_debug_logging,  # 根據環境設定調試日誌預設值
                    "enable_window_state_logging": False,  # 控制視窗狀態儲存日誌
                },
            }
            self._save_settings(default_settings)
            return default_settings

        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)

            # 確保所有必要的鍵值都存在（向後相容性）
            if "auto_update_enabled" not in settings:
                settings["auto_update_enabled"] = True
            if "first_run_completed" not in settings:
                settings["first_run_completed"] = False
            if "window_preferences" not in settings:
                settings["window_preferences"] = {
                    "remember_size_position": True,
                    "main_window": {
                        "width": 1200,
                        "height": 800,
                        "x": None,
                        "y": None,
                        "maximized": False,
                    },
                    "auto_center": True,
                    "adaptive_sizing": True,
                    "dpi_scaling": 1.0,
                }

            return settings
        except Exception as e:
            LogUtils.error_exc(f"載入設定失敗: {e}", "SettingsManager", e)
            # 如果載入失敗，回傳預設設定
            return {
                "servers_root": "",
                "auto_update_enabled": True,
                "first_run_completed": False,
                "window_preferences": {
                    "remember_size_position": True,
                    "main_window": {
                        "width": 1200,
                        "height": 800,
                        "x": None,
                        "y": None,
                        "maximized": False,
                    },
                    "auto_center": True,
                    "adaptive_sizing": True,
                    "dpi_scaling": 1.0,
                },
            }

    # 儲存設定到檔案
    def _save_settings(self, settings: Dict[str, Any]) -> None:
        """
        將設定資料儲存到 JSON 檔案
        Save settings data to JSON file

        Args:
            settings (Dict[str, Any]): 要儲存的設定資料字典

        Returns:
            None
        """
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            LogUtils.error_exc(
                f"無法寫入 user_settings.json: {e}", "SettingsManager", e
            )
            raise Exception(f"無法寫入 user_settings.json: {e}")

    # ====== 基本設定操作 ======
    # 取得設定值
    def get(self, key: str, default: Any = None) -> Any:
        """
        取得指定鍵值的設定資料
        Get setting data for specified key

        Args:
            key (str): 設定鍵值名稱
            default (Any): 預設值，當鍵值不存在時返回

        Returns:
            Any: 設定值或預設值
        """
        return self._settings.get(key, default)

    # 設定值並儲存
    def set(self, key: str, value: Any, immediate_save: bool = True) -> None:
        """
        設定指定鍵值的資料（可選擇立即儲存或延遲儲存以支援批次更新）
        Set data for specified key (optionally immediate or deferred save for batch updates)

        Args:
            key (str): 設定鍵值名稱
            value (Any): 要設定的值
            immediate_save (bool): 是否立即儲存（預設 True）

        Returns:
            None
        """
        self._settings[key] = value
        if immediate_save:
            self._save_settings(self._settings)

    def update_batch(self, updates: dict) -> None:
        """
        批次更新多個設定值並一次性儲存（優化 I/O 效能）
        Batch update multiple settings and save once (optimize I/O performance)

        Args:
            updates (dict): 要更新的鍵值對字典

        Returns:
            None
        """
        self._settings.update(updates)
        self._save_settings(self._settings)

    # ====== 伺服器根目錄管理 ======
    # 取得伺服器根目錄
    def get_servers_root(self) -> str:
        """
        取得使用者設定的伺服器根目錄路徑
        Get user configured servers root directory path

        Args:
            None

        Returns:
            str: 伺服器根目錄路徑字串
        """
        return str(self._settings.get("servers_root", "")).strip()

    # 設定伺服器根目錄
    def set_servers_root(self, path: str) -> None:
        """
        設定伺服器根目錄路徑
        Set servers root directory path

        Args:
            path (str): 伺服器根目錄路徑

        Returns:
            None
        """
        self.set("servers_root", path)

    # ====== 自動更新設定管理 ======
    # 檢查是否啟用自動更新
    def is_auto_update_enabled(self) -> bool:
        """
        檢查是否啟用自動更新檢查功能
        Check if auto-update checking feature is enabled

        Args:
            None

        Returns:
            bool: 啟用自動更新返回 True，否則返回 False
        """
        return bool(self._settings.get("auto_update_enabled", True))

    # 設定自動更新開關
    def set_auto_update_enabled(self, enabled: bool) -> None:
        """
        設定自動更新檢查功能的開關狀態
        Set the on/off state of auto-update checking feature

        Args:
            enabled (bool): True 啟用，False 停用

        Returns:
            None
        """
        self.set("auto_update_enabled", enabled)

    # ====== 首次執行狀態管理 ======
    # 檢查是否完成首次執行
    def is_first_run_completed(self) -> bool:
        """
        檢查是否已完成首次執行的設定流程
        Check if first-run setup process has been completed

        Args:
            None

        Returns:
            bool: 已完成首次執行返回 True，否則返回 False
        """
        return bool(self._settings.get("first_run_completed", False))

    # 標記首次執行完成
    def mark_first_run_completed(self) -> None:
        """
        標記首次執行設定流程已完成
        Mark first-run setup process as completed

        Args:
            None

        Returns:
            None
        """
        self.set("first_run_completed", True)

    # ====== 視窗偏好設定管理 ======
    # 取得視窗偏好設定
    def get_window_preferences(self) -> Dict[str, Any]:
        """
        取得所有視窗相關的偏好設定
        Get all window-related preference settings

        Args:
            None

        Returns:
            Dict[str, Any]: 視窗偏好設定字典
        """
        return self._settings.get("window_preferences", {})

    # 檢查是否記住視窗大小位置
    def is_remember_size_position_enabled(self) -> bool:
        """
        檢查是否啟用記住視窗大小和位置的功能
        Check if remember window size and position feature is enabled

        Args:
            None

        Returns:
            bool: 啟用記住功能返回 True，否則返回 False
        """
        return self.get_window_preferences().get("remember_size_position", True)

    # 設定是否記住視窗大小位置
    def set_remember_size_position(self, enabled: bool) -> None:
        """
        設定是否記住視窗大小和位置的功能開關
        Set whether to remember window size and position feature

        Args:
            enabled (bool): True 啟用，False 停用

        Returns:
            None
        """
        prefs = self.get_window_preferences()
        prefs["remember_size_position"] = enabled
        self.set("window_preferences", prefs)

    # 取得主視窗設定
    def get_main_window_settings(self) -> Dict[str, Any]:
        """
        取得主視窗的大小、位置和狀態設定
        Get main window size, position and state settings

        Args:
            None

        Returns:
            Dict[str, Any]: 主視窗設定字典
        """
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
        x: int = None,
        y: int = None,
        maximized: bool = False,
    ) -> None:
        """
        設定主視窗的大小、位置和最大化狀態
        Set main window size, position and maximized state

        Args:
            width (int): 視窗寬度
            height (int): 視窗高度
            x (int): 視窗 X 座標位置，None 表示置中
            y (int): 視窗 Y 座標位置，None 表示置中
            maximized (bool): 是否最大化

        Returns:
            None
        """
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
        """
        檢查是否啟用自動置中新視窗的功能
        Check if auto-center new windows feature is enabled

        Args:
            None

        Returns:
            bool: 啟用自動置中返回 True，否則返回 False
        """
        return self.get_window_preferences().get("auto_center", True)

    # 設定自動置中新視窗
    def set_auto_center(self, enabled: bool) -> None:
        """
        設定是否自動置中新視窗的功能
        Set whether to auto-center new windows

        Args:
            enabled (bool): True 啟用，False 停用

        Returns:
            None
        """
        prefs = self.get_window_preferences()
        prefs["auto_center"] = enabled
        self.set("window_preferences", prefs)

    # 檢查是否啟用自適應大小調整
    def is_adaptive_sizing_enabled(self) -> bool:
        """
        檢查是否啟用根據螢幕大小自適應調整視窗的功能
        Check if adaptive sizing based on screen size feature is enabled

        Args:
            None

        Returns:
            bool: 啟用自適應大小返回 True，否則返回 False
        """
        return self.get_window_preferences().get("adaptive_sizing", True)

    # 設定自適應大小調整
    def set_adaptive_sizing(self, enabled: bool) -> None:
        """
        設定是否啟用根據螢幕大小自適應調整視窗的功能
        Set whether to enable adaptive sizing based on screen size

        Args:
            enabled (bool): True 啟用，False 停用

        Returns:
            None
        """
        prefs = self.get_window_preferences()
        prefs["adaptive_sizing"] = enabled
        self.set("window_preferences", prefs)

    # 取得 DPI 縮放因子
    def get_dpi_scaling(self) -> float:
        """
        取得當前設定的 DPI 縮放因子
        Get current DPI scaling factor setting

        Args:
            None

        Returns:
            float: DPI 縮放因子 (0.5-3.0)
        """
        return float(self.get_window_preferences().get("dpi_scaling", 1.0))

    # 設定 DPI 縮放因子
    def set_dpi_scaling(self, scaling: float) -> None:
        """
        設定 DPI 縮放因子，會自動限制在合理範圍內
        Set DPI scaling factor, automatically limited to reasonable range

        Args:
            scaling (float): 縮放因子，會被限制在 0.5-3.0 範圍內

        Returns:
            None
        """
        prefs = self.get_window_preferences()
        prefs["dpi_scaling"] = max(0.5, min(3.0, scaling))  # 限制在 0.5-3.0 範圍內
        self.set("window_preferences", prefs)

    # ====== 調試設定管理 ======
    # 取得調試設定
    def get_debug_settings(self) -> Dict[str, Any]:
        """
        取得所有調試相關的設定
        Get all debug-related settings

        Args:
            None

        Returns:
            Dict[str, Any]: 調試設定字典
        """
        return self._settings.get(
            "debug_settings",
            {"enable_debug_logging": False, "enable_window_state_logging": False},
        )

    # 檢查是否啟用調試日誌
    def is_debug_logging_enabled(self) -> bool:
        """
        檢查是否啟用調試日誌輸出功能
        Check if debug logging output feature is enabled

        Args:
            None

        Returns:
            bool: 啟用調試日誌返回 True，否則返回 False
        """
        return self.get_debug_settings().get("enable_debug_logging", False)

    # 設定調試日誌開關
    def set_debug_logging(self, enabled: bool) -> None:
        """
        設定調試日誌輸出功能的開關
        Set debug logging output feature on/off

        Args:
            enabled (bool): True 啟用，False 停用

        Returns:
            None
        """
        debug_settings = self.get_debug_settings()
        debug_settings["enable_debug_logging"] = enabled
        self.set("debug_settings", debug_settings)

# ====== 全域實例管理 ======
# 全域設定管理器實例
_settings_manager = None

# 取得全域設定管理器實例
def get_settings_manager() -> SettingsManager:
    """
    取得全域設定管理器的單例實例
    Get singleton instance of global settings manager

    Args:
        None

    Returns:
        SettingsManager: 設定管理器實例
    """
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
    return _settings_manager
