from __future__ import annotations


class _FakeWidget:
    def __init__(self) -> None:
        self.fixed_width: int | None = None
        self.text = ""
        self.visible: bool | None = None
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
