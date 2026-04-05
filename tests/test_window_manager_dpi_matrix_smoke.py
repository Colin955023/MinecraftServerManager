from __future__ import annotations

import pytest
import src.utils.ui_support.window_manager as window_manager_module


class _StubSettings:
    def __init__(self, dpi_scaling: float, adaptive: bool = False):
        self._dpi_scaling = dpi_scaling
        self._adaptive = adaptive

    def is_adaptive_sizing_enabled(self) -> bool:
        return self._adaptive

    def get_dpi_scaling(self) -> float:
        return self._dpi_scaling


class _StubWindow:
    def __init__(self, width: int, height: int, x: int = 10, y: int = 20, state: str = "normal"):
        self._width = width
        self._height = height
        self._x = x
        self._y = y
        self._state = state

    def update_idletasks(self) -> None:
        return None

    def state(self) -> str:
        return self._state

    def winfo_width(self) -> int:
        return self._width

    def winfo_height(self) -> int:
        return self._height

    def winfo_x(self) -> int:
        return self._x

    def winfo_y(self) -> int:
        return self._y


class _StubWindowSettings:
    def __init__(self):
        self.saved: tuple[int, int, int | None, int | None, bool] | None = None

    def is_remember_size_position_enabled(self) -> bool:
        return True

    def get_main_window_settings(self) -> dict[str, int | None | bool]:
        return {"width": 1200, "height": 800, "x": None, "y": None, "maximized": False}

    def set_main_window_settings(self, width: int, height: int, x: int | None, y: int | None, maximized: bool) -> None:
        self.saved = (width, height, x, y, maximized)


@pytest.mark.smoke
def test_window_manager_dpi_matrix_fixed_layout(monkeypatch) -> None:
    screen_info = {
        "width": 1920,
        "height": 1080,
        "usable_width": 1800,
        "usable_height": 1000,
    }
    matrix = {
        1.0: (1200, 800),
        1.25: (1500, 1000),
        1.5: (1800, 1000),
    }
    results: list[tuple[int, int]] = []

    for dpi_scale, expected in matrix.items():
        monkeypatch.setattr(
            window_manager_module,
            "get_settings_manager",
            lambda s=dpi_scale: _StubSettings(dpi_scaling=s, adaptive=False),
        )
        size = window_manager_module.WindowManager.calculate_optimal_size(screen_info)
        assert size == expected
        results.append(size)

    widths = [w for w, _ in results]
    assert widths == sorted(widths)


@pytest.mark.smoke
def test_window_manager_dpi_matrix_adaptive_layout_stays_within_usable(monkeypatch) -> None:
    screen_info = {
        "width": 1366,
        "height": 768,
        "usable_width": 1280,
        "usable_height": 720,
    }

    for dpi_scale in (1.0, 1.25, 1.5):
        monkeypatch.setattr(
            window_manager_module,
            "get_settings_manager",
            lambda s=dpi_scale: _StubSettings(dpi_scaling=s, adaptive=True),
        )
        width, height = window_manager_module.WindowManager.calculate_optimal_size(screen_info)
        assert width <= screen_info["usable_width"]
        assert height <= screen_info["usable_height"]
        assert width >= 1000
        assert height >= 700


@pytest.mark.smoke
def test_save_main_window_state_skips_transient_small_size(monkeypatch) -> None:
    settings = _StubWindowSettings()
    monkeypatch.setattr(window_manager_module, "get_settings_manager", lambda: settings)

    small_window = _StubWindow(width=200, height=200)
    window_manager_module.WindowManager.save_main_window_state(small_window)

    assert settings.saved is None


@pytest.mark.smoke
def test_save_main_window_state_persists_valid_size(monkeypatch) -> None:
    settings = _StubWindowSettings()
    monkeypatch.setattr(window_manager_module, "get_settings_manager", lambda: settings)

    valid_window = _StubWindow(width=1400, height=900, x=50, y=60)
    window_manager_module.WindowManager.save_main_window_state(valid_window)

    assert settings.saved == (1400, 900, 50, 60, False)
