from __future__ import annotations

from typing import Any, cast

import pytest
import src.ui.create_server_frame as create_server_module


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

    def configure(self, **kwargs) -> None:
        if "values" in kwargs:
            self.values = list(kwargs["values"])
        if "state" in kwargs:
            self.state = str(kwargs["state"])

    def set(self, value: str) -> None:
        self.selected = value


class _NoopThread:
    def __init__(self, target=None, args=(), daemon=None) -> None:
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self) -> None:
        # 測試命名流程時不需要真正啟動背景載入。
        return


def _make_frame(
    name: str, loader_type: str = "Vanilla", mc_version: str = "1.21.1"
) -> create_server_module.CreateServerFrame:
    frame = create_server_module.CreateServerFrame.__new__(create_server_module.CreateServerFrame)
    frame_any = cast(Any, frame)
    frame_any.mc_version_var = _Var(mc_version)
    frame_any.loader_type_var = _Var(loader_type)
    frame_any.server_name_var = _Var(name)
    frame_any.loader_version_var = _Var("無")
    frame_any.loader_version_combo = _Combo()
    frame_any.load_loader_versions = lambda *_args, **_kwargs: None
    return frame


@pytest.mark.integration
def test_server_name_keeps_manual_suffix_when_switching_loader(monkeypatch) -> None:
    monkeypatch.setattr(create_server_module.threading, "Thread", _NoopThread)
    frame = _make_frame("1.21.1 我的服")
    frame.old_mc_version = "1.21.1"

    frame.loader_type_var.set("Fabric")
    create_server_module.CreateServerFrame.update_server_config_ui(frame)
    assert frame.server_name_var.get() == "Fabric 1.21.1 我的服"

    frame.loader_type_var.set("Forge")
    create_server_module.CreateServerFrame.update_server_config_ui(frame)
    assert frame.server_name_var.get() == "Forge 1.21.1 我的服"

    frame.loader_type_var.set("Vanilla")
    create_server_module.CreateServerFrame.update_server_config_ui(frame)
    assert frame.server_name_var.get() == "1.21.1 我的服"


@pytest.mark.integration
def test_server_name_keeps_manual_suffix_when_mc_version_changes(monkeypatch) -> None:
    monkeypatch.setattr(create_server_module.threading, "Thread", _NoopThread)
    frame = _make_frame("Fabric 1.21.1 我的服", loader_type="Fabric", mc_version="1.20.6")
    frame.old_mc_version = "1.21.1"

    create_server_module.CreateServerFrame.update_server_config_ui(frame)
    assert frame.server_name_var.get() == "Fabric 1.20.6 我的服"
