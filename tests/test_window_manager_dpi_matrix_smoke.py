from __future__ import annotations

import pytest
import src.utils.window_manager as window_manager_module


class _StubSettings:
    def __init__(self, dpi_scaling: float, adaptive: bool = False):
        self._dpi_scaling = dpi_scaling
        self._adaptive = adaptive

    def is_adaptive_sizing_enabled(self) -> bool:
        return self._adaptive

    def get_dpi_scaling(self) -> float:
        return self._dpi_scaling


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
