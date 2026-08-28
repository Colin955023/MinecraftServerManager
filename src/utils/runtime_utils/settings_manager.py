"""
設定管理器模組
提供統一的使用者設定管理功能，包含自動更新與視窗偏好等
"""

from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from typing import Any, TypedDict, cast

from src.utils import ConfigurationError, RuntimePaths, atomic_write_json, get_logger, read_json

logger = get_logger().bind(component="SettingsManager")


class MainWindowSettings(TypedDict, total=False):
    """主視窗位置與大小的持久化 schema"""

    width: int
    height: int
    x: int | None
    y: int | None
    maximized: bool


class WindowPreferences(TypedDict, total=False):
    """視窗偏好設定的持久化 schema"""

    remember_size_position: bool
    main_window: MainWindowSettings
    auto_center: bool
    adaptive_sizing: bool
    theme_mode: str


DEFAULT_WINDOW_PREFERENCES: WindowPreferences = {
    "remember_size_position": True,
    "main_window": {"width": 1350, "height": 820, "x": None, "y": None, "maximized": False},
    "auto_center": True,
    "adaptive_sizing": True,
    "theme_mode": "system",
}
_BOOL_SETTINGS = {"auto_update_enabled": True, "first_run_completed": False}
_THEME_MODES = {"system", "light", "dark"}


def _copy_window_preferences() -> WindowPreferences:
    return cast(
        WindowPreferences,
        {
            "remember_size_position": DEFAULT_WINDOW_PREFERENCES["remember_size_position"],
            "main_window": dict(DEFAULT_WINDOW_PREFERENCES["main_window"]),
            "auto_center": DEFAULT_WINDOW_PREFERENCES["auto_center"],
            "adaptive_sizing": DEFAULT_WINDOW_PREFERENCES["adaptive_sizing"],
            "theme_mode": DEFAULT_WINDOW_PREFERENCES["theme_mode"],
        },
    )


def _get_default_settings() -> dict[str, Any]:
    """取得預設設定（根據環境動態計算）"""
    return {
        "servers_root": "",
        "auto_update_enabled": True,
        "first_run_completed": False,
        "window_preferences": _copy_window_preferences(),
    }


def _clone_settings_payload(value: Any) -> Any:
    """複製設定 payload，避免呼叫端持有內部可變物件"""
    try:
        return copy.deepcopy(value)
    except Exception as e:
        logger.debug(f"複製設定 payload 失敗，改用原值: {e}")
        return value


class SettingsManager:
    """統一管理所有使用者設定的管理器類別"""

    def __init__(self):
        self._lock = threading.RLock()
        self.settings_path = RuntimePaths.ensure_dir(RuntimePaths.get_user_data_dir()) / "user_settings.json"
        self._settings = self._load_settings()
        self._no_change_skip_count = 0
        self._no_change_last_log_monotonic = 0.0
        self._no_change_log_interval_seconds = 60.0

    @staticmethod
    def normalize_servers_base_dir(path_str: str | Path) -> str:
        """
        正規化使用者設定的伺服器主資料夾路徑

        Args:
            path_str: 原始路徑字串或 Path

        Returns:
            正規化後的基底路徑字串
        """
        if not path_str or str(path_str).strip() == "":
            return ""
        normalized = str(Path(path_str).expanduser().resolve())
        if Path(normalized).name.lower() == "servers":
            parent = str(Path(normalized).parents[0])
            if parent:
                return parent
        return normalized

    @staticmethod
    def build_servers_root_path(base_dir: str | Path) -> Path:
        """
        從基底資料夾組合出伺服器根目錄

        Args:
            base_dir: 使用者指定的基底資料夾

        Returns:
            解析後的伺服器根目錄 Path
        """

        return (Path(base_dir).expanduser() / "servers").resolve()

    @staticmethod
    def _normalize_int_value(value: Any, default: int) -> int:
        try:
            return int(value)
        except TypeError, ValueError:
            return default

    @staticmethod
    def get_default_main_window_settings() -> MainWindowSettings:
        """
        取得主視窗預設大小，供重設與顯示目前值共用

        Returns:
            主視窗預設大小設定
        """
        return cast(MainWindowSettings, dict(DEFAULT_WINDOW_PREFERENCES["main_window"]))

    @staticmethod
    def _normalize_theme_mode(mode: Any) -> str:
        normalized = str(mode or DEFAULT_WINDOW_PREFERENCES["theme_mode"]).strip().lower()
        return normalized if normalized in _THEME_MODES else DEFAULT_WINDOW_PREFERENCES["theme_mode"]

    def get(self, key: str, default: Any = None) -> Any:
        """
        取得指定鍵值的設定資料

        Args:
            key: 設定鍵名
            default: 找不到時的預設值

        Returns:
            對應的設定值
        """
        with self._lock:
            value = self._settings.get(key, default)
            if key == "window_preferences" and isinstance(value, dict):
                return self._normalize_window_preferences(value)
            return _clone_settings_payload(value)

    def set(self, key: str, value: Any, immediate_save: bool = True) -> None:
        """
        設定指定鍵值的資料

        Args:
            key: 設定鍵名
            value: 要寫入的設定值
            immediate_save: 是否立即儲存到磁碟
        """
        with self._lock:
            self._settings[key] = _clone_settings_payload(value)
            if immediate_save:
                self._save_settings(self._settings)

    def get_servers_root(self) -> str:
        """
        取得使用者設定的伺服器主資料夾路徑

        Returns:
            目前設定的伺服器主資料夾根路徑字串；若尚未設定則回傳空字串
        """
        with self._lock:
            return str(self._settings.get("servers_root", "")).strip()

    def set_servers_root(self, path: str | Path) -> None:
        self.set("servers_root", self.normalize_servers_base_dir(path))

    def get_validated_servers_root_path(self, *, create: bool = False) -> Path:
        """
        回傳已驗證的 servers 根目錄

        Args:
            create: 若目錄不存在時是否建立

        Returns:
            已驗證的伺服器根目錄 Path
        """
        base_dir = self.get_servers_root()
        if not base_dir:
            raise ConfigurationError("尚未設定伺服器主資料夾")
        servers_root = self.build_servers_root_path(base_dir)
        if servers_root.exists():
            if not servers_root.is_dir():
                raise ConfigurationError(f"伺服器資料夾路徑無效： {servers_root}")
            return servers_root
        if not create:
            raise ConfigurationError(f"找不到伺服器資料夾： {servers_root}")
        try:
            servers_root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ConfigurationError(f"無法建立伺服器資料夾： {servers_root}") from e
        return servers_root

    def is_auto_update_enabled(self) -> bool:
        """
        檢查自動更新功能是否啟用

        Returns:
            若啟用則回傳 True，否則回傳 False
        """
        with self._lock:
            return bool(self._settings.get("auto_update_enabled", _BOOL_SETTINGS["auto_update_enabled"]))

    def set_auto_update_enabled(self, enabled: bool) -> None:
        """
        設定自動更新功能是否啟用

        Args:
            enabled: 若啟用則傳入 True，否則傳入 False
        """
        self.set("auto_update_enabled", enabled)

    def is_first_run_completed(self) -> bool:
        """
        檢查首次啟動流程是否已完成

        Returns:
            若已完成則回傳 True，否則回傳 False
        """
        with self._lock:
            return bool(self._settings.get("first_run_completed", _BOOL_SETTINGS["first_run_completed"]))

    def mark_first_run_completed(self) -> None:
        """標記首次啟動流程已完成"""
        self.set("first_run_completed", True)

    def get_window_preferences(self) -> WindowPreferences:
        """
        取得視窗偏好設定

        Returns:
            已正規化且可安全讀取的視窗偏好設定
        """
        with self._lock:
            value = self._settings.get("window_preferences", _copy_window_preferences())
            if isinstance(value, dict):
                return self._normalize_window_preferences(value)
            return _copy_window_preferences()

    def is_remember_size_position_enabled(self) -> bool:
        return self._get_window_bool("remember_size_position", True)

    def set_remember_size_position(self, enabled: bool) -> None:
        self._update_window_pref("remember_size_position", enabled)

    def is_auto_center_enabled(self) -> bool:
        return self._get_window_bool("auto_center", True)

    def set_auto_center(self, enabled: bool) -> None:
        self._update_window_pref("auto_center", enabled)

    def is_adaptive_sizing_enabled(self) -> bool:
        return self._get_window_bool("adaptive_sizing", True)

    def set_adaptive_sizing(self, enabled: bool) -> None:
        self._update_window_pref("adaptive_sizing", enabled)

    def get_main_window_settings(self) -> MainWindowSettings:
        """
        取得主視窗的大小、位置和狀態設定

        Returns:
            主視窗尺寸、位置與最大化狀態設定
        """
        with self._lock:
            return cast(
                MainWindowSettings,
                dict(self.get_window_preferences().get("main_window", self.get_default_main_window_settings())),
            )

    def set_main_window_settings(
        self, width: int, height: int, x: int | None = None, y: int | None = None, maximized: bool = False
    ) -> None:
        """
        設定主視窗的大小、位置和最大化狀態

        Args:
            width: 主視窗寬度
            height: 主視窗高度
            x: 主視窗左上角 X 座標，若不指定則保留為空
            y: 主視窗左上角 Y 座標，若不指定則保留為空
            maximized: 是否以最大化狀態儲存
        """
        with self._lock:
            prefs: dict[str, Any] = dict(self.get_window_preferences())
            prefs["main_window"] = {"width": width, "height": height, "x": x, "y": y, "maximized": maximized}
            self.set("window_preferences", prefs)

    def get_theme_mode(self) -> str:
        """取得 UI 主題模式"""
        return self._normalize_theme_mode(
            self.get_window_preferences().get("theme_mode", DEFAULT_WINDOW_PREFERENCES["theme_mode"])
        )

    def set_theme_mode(self, mode: str) -> None:
        """設定 UI 主題模式"""
        self._update_window_pref("theme_mode", self._normalize_theme_mode(mode))

    def _normalize_window_preferences(self, window_preferences: dict[str, Any]) -> WindowPreferences:
        normalized_window = _copy_window_preferences()
        normalized_window["remember_size_position"] = bool(
            window_preferences.get("remember_size_position", DEFAULT_WINDOW_PREFERENCES["remember_size_position"])
        )
        normalized_window["auto_center"] = bool(
            window_preferences.get("auto_center", DEFAULT_WINDOW_PREFERENCES["auto_center"])
        )
        normalized_window["adaptive_sizing"] = bool(
            window_preferences.get("adaptive_sizing", DEFAULT_WINDOW_PREFERENCES["adaptive_sizing"])
        )
        normalized_window["theme_mode"] = self._normalize_theme_mode(
            window_preferences.get("theme_mode", normalized_window["theme_mode"])
        )
        main_window = window_preferences.get("main_window")
        if isinstance(main_window, dict):
            normalized_window["main_window"]["width"] = self._normalize_int_value(
                main_window.get("width"), normalized_window["main_window"]["width"]
            )
            normalized_window["main_window"]["height"] = self._normalize_int_value(
                main_window.get("height"), normalized_window["main_window"]["height"]
            )
            normalized_window["main_window"]["x"] = main_window.get("x")
            normalized_window["main_window"]["y"] = main_window.get("y")
            normalized_window["main_window"]["maximized"] = bool(
                main_window.get("maximized", normalized_window["main_window"]["maximized"])
            )
        return normalized_window

    def _normalize_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(_get_default_settings())
        normalized["servers_root"] = self.normalize_servers_base_dir(
            str(settings.get("servers_root", "") or "")
        ).strip()
        for key, default in _BOOL_SETTINGS.items():
            normalized[key] = bool(settings.get(key, default))
        window_preferences = settings.get("window_preferences")
        if isinstance(window_preferences, dict):
            normalized["window_preferences"] = self._normalize_window_preferences(window_preferences)
        return normalized

    def _load_settings(self) -> dict[str, Any]:
        with self._lock:
            if not self.settings_path.exists():
                default_settings = _get_default_settings()
                self._save_settings(default_settings)
                return default_settings
            settings = read_json(self.settings_path)
            if not settings or not isinstance(settings, dict):
                return _get_default_settings()
            return self._normalize_settings(settings)

    def _save_settings(self, settings: dict[str, Any]) -> None:
        with self._lock:
            settings_snapshot = cast(dict[str, Any], _clone_settings_payload(settings))
            try:
                if self.settings_path.exists():
                    current = read_json(self.settings_path)
                    if isinstance(current, dict) and current == settings_snapshot:
                        self._no_change_skip_count += 1
                        now_monotonic = time.monotonic()
                        if (
                            self._no_change_last_log_monotonic <= 0
                            or (now_monotonic - self._no_change_last_log_monotonic)
                            >= self._no_change_log_interval_seconds
                        ):
                            logger.debug(f"settings 未變更，略過寫入（最近累計 {self._no_change_skip_count} 次）")
                            self._no_change_skip_count = 0
                            self._no_change_last_log_monotonic = now_monotonic
                        return
            except OSError as e:
                logger.debug(f"比對 settings 檔案時發生 I/O 錯誤，改為直接寫入: {e}")
            if not atomic_write_json(self.settings_path, settings_snapshot):
                logger.error("無法寫入 user_settings.json")

    def _update_window_pref(self, key: str, value: Any) -> None:
        """更新視窗偏好中的單一鍵值"""
        prefs: dict[str, Any] = dict(self.get_window_preferences())
        prefs[key] = value
        self.set("window_preferences", prefs)

    def _get_window_bool(self, key: str, default: bool = True) -> bool:
        return bool(self.get_window_preferences().get(key, default))


_settings_manager = None


def get_settings_manager() -> SettingsManager:
    """
    取得全域設定管理器的單例實例

    Returns:
        全域共用的 SettingsManager 實例
    """
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
    return _settings_manager


__all__ = ["get_settings_manager"]
