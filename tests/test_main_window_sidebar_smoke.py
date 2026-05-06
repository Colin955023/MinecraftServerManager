from __future__ import annotations

from typing import Any

from src.ui import main_window as main_window_module


class _FakeWidget:
    def __init__(self) -> None:
        self.fixed_width: int | None = None
        self.text = ""
        self.visible: bool | None = None
        self.tooltip = ""
        self.min_height: int | None = None
        self.stylesheet = ""

    def setFixedWidth(self, width: int) -> None:
        self.fixed_width = int(width)

    def setText(self, text: str) -> None:
        self.text = text

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)

    def setMinimumHeight(self, height: int) -> None:
        self.min_height = int(height)

    def setToolTip(self, tooltip: str) -> None:
        self.tooltip = tooltip

    def setStyleSheet(self, stylesheet: str) -> None:
        self.stylesheet = stylesheet


class _FakeLayout:
    def __init__(self) -> None:
        self.margins: tuple[int, int, int, int] | None = None
        self.spacing: int | None = None

    def setContentsMargins(self, left: int, top: int, right: int, bottom: int) -> None:
        self.margins = (int(left), int(top), int(right), int(bottom))

    def setSpacing(self, spacing: int) -> None:
        self.spacing = int(spacing)


def test_mini_sidebar_width_tracks_button_width_and_padding() -> None:
    manager: Any = object.__new__(main_window_module.MinecraftServerManager)
    manager.sidebar_visible = False
    manager._nav_full_width = 225
    manager._nav_mini_button_width = 36
    manager._nav_mini_side_padding = 6
    manager._nav_mini_width = manager._nav_mini_button_width + manager._nav_mini_side_padding * 2
    manager.active_nav_key = "create"
    manager.nav_container = _FakeWidget()
    manager.sidebar_toggle_btn = _FakeWidget()
    manager.sidebar_title = _FakeWidget()
    manager.sidebar_footer = _FakeWidget()
    manager.sidebar_layout = _FakeLayout()
    button = _FakeWidget()
    description = _FakeWidget()
    manager.nav_buttons = {
        "create": {
            "button": button,
            "description": description,
            "icon": "N",
            "title": "建立伺服器",
            "tooltip": "建立新的 Minecraft 伺服器",
        }
    }

    manager._apply_sidebar_visibility()

    assert manager.nav_container.fixed_width == 48
    assert button.fixed_width == 36
    assert manager.sidebar_layout.margins == (6, 10, 6, 8)
    assert description.visible is False
