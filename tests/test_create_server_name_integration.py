from __future__ import annotations

from typing import Any, cast

from src.ui import CreateServerFrame


class _Var:
    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value


class _Combo:
    def __init__(self) -> None:
        self.values: list[str] = []
        self.state = "disabled"
        self.selected = ""
        self.enabled = True

    def set(self, value: str) -> None:
        self.selected = value

    def clear(self) -> None:
        self.values.clear()

    def addItem(self, text: str) -> None:
        self.values.append(text)

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.state = "normal" if enabled else "disabled"

    def setCurrentText(self, text: str) -> None:
        self.selected = text


def _make_frame(name: str, loader_type: str = "Vanilla", mc_version: str = "1.21.1") -> CreateServerFrame:
    frame = CreateServerFrame.__new__(CreateServerFrame)
    frame_any = cast(Any, frame)
    frame_any.mc_version_var = _Var(mc_version)
    frame_any.loader_type_var = _Var(loader_type)
    frame_any.server_name_var = _Var(name)
    frame_any.loader_version_var = _Var("無")
    frame_any.loader_version_combo = _Combo()
    frame_any.load_loader_versions = lambda *_args, **_kwargs: None

    class _Scope:
        def submit(self, *_args, **_kwargs):
            return None

    frame_any.scope = _Scope()
    return frame


def test_server_name_keeps_manual_suffix_when_switching_loader() -> None:
    frame = _make_frame("1.21.1 我的服")
    frame.old_mc_version = "1.21.1"

    frame.loader_type_var.set("Fabric")
    CreateServerFrame.update_server_config_ui(frame)
    assert frame.server_name_var.get() == "Fabric 1.21.1 我的服"

    frame.loader_type_var.set("Forge")
    CreateServerFrame.update_server_config_ui(frame)
    assert frame.server_name_var.get() == "Forge 1.21.1 我的服"

    frame.loader_type_var.set("Vanilla")
    CreateServerFrame.update_server_config_ui(frame)
    assert frame.server_name_var.get() == "1.21.1 我的服"


def test_server_name_keeps_manual_suffix_when_mc_version_changes() -> None:
    frame = _make_frame("Fabric 1.21.1 我的服", loader_type="Fabric", mc_version="1.20.6")
    frame.old_mc_version = "1.21.1"

    CreateServerFrame.update_server_config_ui(frame)
    assert frame.server_name_var.get() == "Fabric 1.20.6 我的服"
