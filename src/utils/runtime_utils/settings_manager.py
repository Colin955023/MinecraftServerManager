"""設定管理器模組
提供統一的使用者設定管理功能，包含自動更新、視窗偏好與除錯設定等。
"""

import contextlib
import sys
import time
from pathlib import Path
from typing import Any, TypedDict, cast
from ...core import ConfigurationError
from .. import PathUtils
from .runtime_paths import RuntimePaths
from .. import atomic_write_json
from .. import get_logger

logger = get_logger().bind(component="SettingsManager")


class MainWindowSettings(TypedDict):
    """主視窗尺寸與狀態設定。"""

    width: int
    height: int
    x: int | None
    y: int | None
    maximized: bool


class WindowPreferences(TypedDict):
    """視窗偏好設定。"""

    remember_size_position: bool
    main_window: MainWindowSettings
    auto_center: bool
    adaptive_sizing: bool
    dpi_scaling: float


class DebugSettings(TypedDict):
    """除錯相關設定。"""

    enable_debug_logging: bool
    enable_window_state_logging: bool


class UserSettings(TypedDict):
    """使用者設定的完整資料結構。"""

    servers_root: str
    auto_update_enabled: bool
    first_run_completed: bool
    window_preferences: WindowPreferences
    debug_settings: DebugSettings


DEFAULT_WINDOW_PREFERENCES: WindowPreferences = {
    "remember_size_position": True,
    "main_window": {"width": 1200, "height": 800, "x": None, "y": None, "maximized": False},
    "auto_center": True,
    "adaptive_sizing": True,
    "dpi_scaling": 1.0,
}
DEFAULT_DEBUG_SETTINGS: DebugSettings = {"enable_debug_logging": False, "enable_window_state_logging": False}
_BOOL_SETTINGS = {"auto_update_enabled": True, "first_run_completed": False}
_WINDOW_PREF_KEYS = {
    "remember_size_position": "remember_size_position",
    "auto_center": "auto_center",
    "adaptive_sizing": "adaptive_sizing",
    "dpi_scaling": "dpi_scaling",
}


def _copy_window_preferences() -> WindowPreferences:
    return cast(
        WindowPreferences,
        {
            "remember_size_position": DEFAULT_WINDOW_PREFERENCES["remember_size_position"],
            "main_window": dict(DEFAULT_WINDOW_PREFERENCES["main_window"]),
            "auto_center": DEFAULT_WINDOW_PREFERENCES["auto_center"],
            "adaptive_sizing": DEFAULT_WINDOW_PREFERENCES["adaptive_sizing"],
            "dpi_scaling": DEFAULT_WINDOW_PREFERENCES["dpi_scaling"],
        },
    )


def _get_default_debug_settings(*, enabled: bool) -> DebugSettings:
    debug_settings = dict(DEFAULT_DEBUG_SETTINGS)
    debug_settings["enable_debug_logging"] = enabled
    return cast(DebugSettings, debug_settings)


def _get_default_settings() -> dict[str, Any]:
    """取得預設設定（根據環境動態計算）"""
    is_nuitka = "__compiled__" in globals()
    is_packaged = bool(getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS") or is_nuitka)
    default_debug_logging = not is_packaged
    return {
        "servers_root": "",
        "auto_update_enabled": True,
        "first_run_completed": False,
        "auto_prune_markers_on_startup": False,
        "window_preferences": _copy_window_preferences(),
        "debug_settings": _get_default_debug_settings(enabled=default_debug_logging),
    }


class SettingsManager:
    """統一管理所有使用者設定的管理器類別"""

    def __init__(self):
        self.settings_path = RuntimePaths.ensure_dir(RuntimePaths.get_user_data_dir()) / "user_settings.json"
        self._settings = self._load_settings()
        self._no_change_skip_count = 0
        self._no_change_last_log_monotonic = 0.0
        self._no_change_log_interval_seconds = 60.0

    @staticmethod
    def normalize_servers_base_dir(path_str: str | Path) -> str:
        """正規化使用者設定的伺服器主資料夾路徑。

        Args:
            path_str: 原始路徑字串或 Path。

        Returns:
            正規化後的基底路徑字串。
        """

        # 若為空字串則直接回傳，避免 resolve 成 cwd
        if not path_str or str(path_str).strip() == "":
            return ""
        normalized = str(Path(path_str).expanduser().resolve())
        if Path(normalized).name.lower() == "servers":
            parent = str(Path(normalized).parent)
            if parent:
                return parent
        return normalized

    @staticmethod
    def build_servers_root_path(base_dir: str | Path) -> Path:
        """從基底資料夾組合出伺服器根目錄。

        Args:
            base_dir: 使用者指定的基底資料夾。

        Returns:
            解析後的伺服器根目錄 Path。
        """

        return (Path(base_dir).expanduser() / "servers").resolve()

    def _normalize_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(_get_default_settings())
        normalized["servers_root"] = self.normalize_servers_base_dir(
            str(settings.get("servers_root", "") or "")
        ).strip()
        for key, default in _BOOL_SETTINGS.items():
            normalized[key] = bool(settings.get(key, default))
        window_preferences = settings.get("window_preferences")
        if isinstance(window_preferences, dict):
            normalized_window = _copy_window_preferences()
            normalized_window["remember_size_position"] = bool(
                window_preferences.get("remember_size_position", normalized_window["remember_size_position"])
            )
            normalized_window["auto_center"] = bool(
                window_preferences.get("auto_center", normalized_window["auto_center"])
            )
            normalized_window["adaptive_sizing"] = bool(
                window_preferences.get("adaptive_sizing", normalized_window["adaptive_sizing"])
            )
            with contextlib.suppress(TypeError, ValueError):
                normalized_window["dpi_scaling"] = float(
                    window_preferences.get("dpi_scaling", normalized_window["dpi_scaling"])
                )
            main_window = window_preferences.get("main_window")
            if isinstance(main_window, dict):
                normalized_window["main_window"] = {
                    "width": int(main_window.get("width", normalized_window["main_window"]["width"])),
                    "height": int(main_window.get("height", normalized_window["main_window"]["height"])),
                    "x": main_window.get("x"),
                    "y": main_window.get("y"),
                    "maximized": bool(main_window.get("maximized", normalized_window["main_window"]["maximized"])),
                }
            normalized["window_preferences"] = normalized_window
        debug_settings = settings.get("debug_settings")
        if isinstance(debug_settings, dict):
            default_debug = normalized["debug_settings"]
            normalized["debug_settings"] = {
                "enable_debug_logging": bool(
                    debug_settings.get("enable_debug_logging", default_debug["enable_debug_logging"])
                ),
                "enable_window_state_logging": bool(
                    debug_settings.get("enable_window_state_logging", default_debug["enable_window_state_logging"])
                ),
            }
        return normalized

    def _load_settings(self) -> dict[str, Any]:
        if not self.settings_path.exists():
            default_settings = _get_default_settings()
            self._save_settings(default_settings)
            return default_settings
        settings = PathUtils.load_json(self.settings_path)
        if not settings:
            return _get_default_settings()
        if not isinstance(settings, dict):
            return _get_default_settings()
        return self._normalize_settings(settings)

    def _save_settings(self, settings: dict[str, Any]) -> None:
        # 若設定內容未變更則略過寫入以減少不必要的 I/O
        try:
            if self.settings_path.exists():
                current = PathUtils.load_json(self.settings_path)
                if isinstance(current, dict) and current == settings:
                    self._no_change_skip_count += 1
                    now_monotonic = time.monotonic()
                    if (
                        self._no_change_last_log_monotonic <= 0
                        or (now_monotonic - self._no_change_last_log_monotonic) >= self._no_change_log_interval_seconds
                    ):
                        logger.debug(f"settings 未變更，跳過寫入（最近累計 {self._no_change_skip_count} 次）")
                        self._no_change_skip_count = 0
                        self._no_change_last_log_monotonic = now_monotonic
                    return
        except OSError:
            # 若比對時發生 I/O 錯誤則繼續嘗試寫入以確保設定被保留
            pass

        if not atomic_write_json(self.settings_path, settings):
            logger.error("無法寫入 user_settings.json")

    def get(self, key: str, default: Any = None) -> Any:
        """取得指定鍵值的設定資料。

        Args:
            key: 設定鍵名。
            default: 找不到時的預設值。

        Returns:
            對應的設定值。
        """
        return self._settings.get(key, default)

    def set(self, key: str, value: Any, immediate_save: bool = True) -> None:
        """設定指定鍵值的資料。

        Args:
            key: 設定鍵名。
            value: 要寫入的設定值。
            immediate_save: 是否立即儲存到磁碟。
        """
        self._settings[key] = value
        if immediate_save:
            self._save_settings(self._settings)

    def update_batch(self, updates: dict) -> None:
        """批次更新多個設定值並一次性儲存。

        Args:
            updates: 要合併寫入的設定更新項目。
        """
        self._settings.update(updates)
        self._save_settings(self._settings)

    def _get_bool_setting(self, key: str) -> bool:
        """通用的布林設定取得方法（內部使用）"""
        default = _BOOL_SETTINGS.get(key, False)
        return bool(self._settings.get(key, default))

    def _set_bool_setting(self, key: str, value: bool) -> None:
        """通用的布林設定設定方法（內部使用）"""
        self.set(key, value)

    def _update_window_pref(self, key: str, value: Any) -> None:
        """通用的視窗偏好設定更新方法（內部使用）"""
        prefs: dict[str, Any] = dict(self.get_window_preferences())
        prefs[key] = value
        self.set("window_preferences", prefs)

    def get_servers_root(self) -> str:
        """取得使用者設定的伺服器主資料夾路徑。"""
        return str(self._settings.get("servers_root", "")).strip()

    def set_servers_root(self, path: str) -> None:
        normalized_path = self.normalize_servers_base_dir(path)
        self.set("servers_root", normalized_path)

    def get_validated_servers_root_path(self, *, create: bool = False) -> Path:
        """回傳已驗證的 servers 根目錄。

        Args:
            create: 若目錄不存在時是否建立。

        Returns:
            已驗證的伺服器根目錄 Path。
        """
        base_dir = self.get_servers_root()
        if not base_dir:
            raise ConfigurationError("尚未設定伺服器主資料夾。")
        servers_root = self.build_servers_root_path(base_dir)
        if servers_root.exists():
            if not servers_root.is_dir():
                raise ConfigurationError(f"伺服器資料夾路徑無效： {servers_root}")
            return servers_root
        if not create:
            raise ConfigurationError(f"找不到伺服器資料夾： {servers_root}")
        try:
            servers_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigurationError(f"無法建立伺服器資料夾： {servers_root}") from exc
        return servers_root

    def get_validated_servers_root(self, *, create: bool = False) -> str:
        return str(self.get_validated_servers_root_path(create=create))

    def is_auto_update_enabled(self) -> bool:
        return self._get_bool_setting("auto_update_enabled")

    def set_auto_update_enabled(self, enabled: bool) -> None:
        self._set_bool_setting("auto_update_enabled", enabled)

    def is_first_run_completed(self) -> bool:
        return self._get_bool_setting("first_run_completed")

    def mark_first_run_completed(self) -> None:
        """標記首次啟動流程已完成。"""
        self._set_bool_setting("first_run_completed", True)

    def get_window_preferences(self) -> WindowPreferences:
        value = self._settings.get("window_preferences", _copy_window_preferences())
        if isinstance(value, dict):
            return cast(WindowPreferences, value)
        return _copy_window_preferences()

    def is_remember_size_position_enabled(self) -> bool:
        return bool(self.get_window_preferences().get(_WINDOW_PREF_KEYS["remember_size_position"], True))

    def set_remember_size_position(self, enabled: bool) -> None:
        key = _WINDOW_PREF_KEYS["remember_size_position"]
        self._update_window_pref(key, enabled)

    def get_main_window_settings(self) -> MainWindowSettings:
        """取得主視窗的大小、位置和狀態設定"""
        default_settings: MainWindowSettings = {"width": 1200, "height": 800, "x": None, "y": None, "maximized": False}
        return cast(MainWindowSettings, self.get_window_preferences().get("main_window", default_settings))

    def set_main_window_settings(
        self, width: int, height: int, x: int | None = None, y: int | None = None, maximized: bool = False
    ) -> None:
        """設定主視窗的大小、位置和最大化狀態"""
        prefs: dict[str, Any] = dict(self.get_window_preferences())
        prefs["main_window"] = {"width": width, "height": height, "x": x, "y": y, "maximized": maximized}
        self.set("window_preferences", prefs)

    def is_auto_center_enabled(self) -> bool:
        """檢查是否啟用自動置中新視窗的功能"""
        return bool(self.get_window_preferences().get(_WINDOW_PREF_KEYS["auto_center"], True))

    def set_auto_center(self, enabled: bool) -> None:
        """設定是否自動置中新視窗的功能"""
        key = _WINDOW_PREF_KEYS["auto_center"]
        self._update_window_pref(key, enabled)

    def is_adaptive_sizing_enabled(self) -> bool:
        """檢查是否啟用根據螢幕大小自適應調整視窗的功能"""
        return bool(self.get_window_preferences().get(_WINDOW_PREF_KEYS["adaptive_sizing"], True))

    def set_adaptive_sizing(self, enabled: bool) -> None:
        """設定是否啟用根據螢幕大小自適應調整視窗的功能"""
        key = _WINDOW_PREF_KEYS["adaptive_sizing"]
        self._update_window_pref(key, enabled)

    def get_dpi_scaling(self) -> float:
        """取得當前設定的 DPI 縮放因子，預設為 1.0"""
        return float(cast(Any, self.get_window_preferences().get(_WINDOW_PREF_KEYS["dpi_scaling"], 1.0)))

    def set_dpi_scaling(self, scaling: float) -> None:
        """設定 DPI 縮放因子，會自動限制在合理範圍內（0.5-3.0）"""
        validated_scaling = max(0.5, min(3.0, scaling))
        key = _WINDOW_PREF_KEYS["dpi_scaling"]
        self._update_window_pref(key, validated_scaling)

    def get_debug_settings(self) -> DebugSettings:
        """取得所有除錯相關的設定"""
        value = self._settings.get("debug_settings", dict(DEFAULT_DEBUG_SETTINGS))
        if isinstance(value, dict):
            return cast(DebugSettings, value)
        return cast(DebugSettings, dict(DEFAULT_DEBUG_SETTINGS))

    def is_debug_logging_enabled(self) -> bool:
        """檢查是否啟用除錯日誌輸出功能"""
        return self.get_debug_settings().get("enable_debug_logging", False)

    def set_debug_logging(self, enabled: bool) -> None:
        """設定除錯日誌輸出功能的開關"""
        debug_settings = self.get_debug_settings()
        debug_settings["enable_debug_logging"] = enabled
        self.set("debug_settings", debug_settings)


_settings_manager = None


def get_settings_manager() -> SettingsManager:
    """取得全域設定管理器的單例實例。

    Returns:
        全域共用的 `SettingsManager` 實例。
    """
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
    return _settings_manager
