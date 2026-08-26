from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

from src import main as main_module


def _stub_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_application: Callable[[], None],
    events: list[str] | None = None,
) -> list[str]:
    if events is None:
        events = []
    kernel32 = SimpleNamespace(CreateMutexW=lambda *_args: events.append("mutex"))
    monkeypatch.setattr(main_module.ctypes, "windll", SimpleNamespace(kernel32=kernel32), raising=False)
    monkeypatch.setattr(main_module, "run_application", run_application)
    monkeypatch.setattr(main_module, "shutdown_shared_manager", lambda **_kwargs: events.append("shutdown"))
    monkeypatch.setattr(main_module, "HTTPClient", SimpleNamespace(close=lambda: events.append("http")))
    return events


def test_main_returns_zero_after_normal_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    _stub_runtime(monkeypatch, run_application=lambda: events.append("run"), events=events)

    result = main_module.main()

    assert result == 0
    assert events == ["mutex", "run", "shutdown", "http"]


def test_main_returns_failure_after_startup_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_startup() -> None:
        raise RuntimeError("startup failed")

    events = _stub_runtime(monkeypatch, run_application=fail_startup)

    result = main_module.main()

    assert result == 1
    assert events == ["mutex", "shutdown", "http"]
