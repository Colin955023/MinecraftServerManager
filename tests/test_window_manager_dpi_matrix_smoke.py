from __future__ import annotations

from typing import Any, cast

import src.utils.ui_support.window_manager as window_manager_module


class _StubSettings:
    def __init__(self, adaptive: bool = False):
        self._adaptive = adaptive

    def is_adaptive_sizing_enabled(self) -> bool:
        return self._adaptive


class _StubWindow:
    def __init__(self, width: int, height: int, x: int = 10, y: int = 20, state: str = "normal"):
        self._width = width
        self._height = height
        self._x = x
        self._y = y
        self._state = state

    def state(self) -> str:
        return self._state

    def isMinimized(self) -> bool:
        return self._state == "iconic"

    def isMaximized(self) -> bool:
        return self._state == "zoomed"

    def geometry(self):
        return self

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height

    def x(self) -> int:
        return self._x

    def y(self) -> int:
        return self._y


class _StubWindowSettings:
    def __init__(self):
        self.saved: tuple[int, int, int | None, int | None, bool] | None = None

    def is_remember_size_position_enabled(self) -> bool:
        return True

    def get_main_window_settings(self) -> dict[str, int | None | bool]:
        return {"width": 600, "height": 400, "x": None, "y": None, "maximized": False}

    def set_main_window_settings(self, width: int, height: int, x: int | None, y: int | None, maximized: bool) -> None:
        self.saved = (width, height, x, y, maximized)


def test_window_manager_fixed_layout_uses_qt_device_independent_pixels(monkeypatch) -> None:
    screen_info = {
        "width": 1920,
        "height": 1080,
        "usable_width": 1800,
        "usable_height": 1000,
    }

    monkeypatch.setattr(window_manager_module, "get_settings_manager", lambda: _StubSettings(adaptive=False))

    assert window_manager_module.WindowManager.calculate_optimal_size(screen_info) == (1350, 820)


def test_window_manager_adaptive_layout_stays_within_usable(monkeypatch) -> None:
    screen_info = {
        "width": 1366,
        "height": 768,
        "usable_width": 1280,
        "usable_height": 720,
    }

    monkeypatch.setattr(window_manager_module, "get_settings_manager", lambda: _StubSettings(adaptive=True))

    width, height = window_manager_module.WindowManager.calculate_optimal_size(screen_info)
    assert width <= screen_info["usable_width"]
    assert height <= screen_info["usable_height"]
    assert width >= 900
    assert height >= 600


def test_save_main_window_state_skips_transient_small_size(monkeypatch) -> None:
    settings = _StubWindowSettings()
    monkeypatch.setattr(window_manager_module, "get_settings_manager", lambda: settings)
    alive_ids: set[int] = set()

    def is_qobject_alive_stub(window: Any) -> bool:
        return id(window) in alive_ids

    monkeypatch.setattr(window_manager_module, "is_qobject_alive", is_qobject_alive_stub)

    small_window = _StubWindow(width=200, height=200)
    window_manager_module.WindowManager.save_main_window_state(cast(Any, small_window))

    assert settings.saved is None


def test_save_main_window_state_persists_valid_size(monkeypatch) -> None:
    settings = _StubWindowSettings()
    monkeypatch.setattr(window_manager_module, "get_settings_manager", lambda: settings)
    alive_ids: set[int] = set()

    def is_qobject_alive_stub(window: Any) -> bool:
        return id(window) in alive_ids

    monkeypatch.setattr(window_manager_module, "is_qobject_alive", is_qobject_alive_stub)

    valid_window = _StubWindow(width=900, height=600, x=50, y=60)
    # 註冊 valid_window 為存活，模擬可安全存取的情況
    alive_ids.add(id(valid_window))
    window_manager_module.WindowManager.save_main_window_state(cast(Any, valid_window))

    assert settings.saved == (900, 600, 50, 60, False)
