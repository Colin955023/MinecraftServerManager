from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest

import src.ui.services.task_coordinator as task_coordinator


class _Settings:
    def __init__(self, *, first_run: bool, auto_update: bool) -> None:
        self.first_run = first_run
        self.auto_update = auto_update
        self.auto_update_values: list[bool] = []
        self.marked = False

    def is_first_run_completed(self) -> bool:
        return self.first_run

    def is_auto_update_enabled(self) -> bool:
        return self.auto_update

    def set_auto_update_enabled(self, enabled: bool) -> None:
        self.auto_update_values.append(enabled)

    def mark_first_run_completed(self) -> None:
        self.marked = True


def test_preload_java_candidates_uses_background_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    submitted: list[tuple[Callable[[], None], str, bool]] = []
    refreshed: list[bool] = []
    scope = SimpleNamespace(
        submit=lambda callback, *, key, replace: submitted.append((callback, key, replace)),
    )
    coordinator = task_coordinator.TaskCoordinator(
        SimpleNamespace(scope=scope), _Settings(first_run=True, auto_update=False)
    )
    monkeypatch.setattr(
        task_coordinator.JavaUtils,
        "refresh_java_candidates_cache",
        lambda: refreshed.append(True),
    )

    coordinator.preload_java_candidates()
    callback, key, replace = submitted[0]
    callback()

    assert (key, replace) == ("preload_java", True)
    assert refreshed == [True]


def test_first_run_enables_updates_and_schedules_check(monkeypatch: pytest.MonkeyPatch) -> None:
    focus_calls: list[bool] = []
    messages: list[dict[str, object]] = []
    schedules: list[tuple[int, bool]] = []
    root = SimpleNamespace(setFocus=lambda: focus_calls.append(True))
    settings = _Settings(first_run=False, auto_update=False)
    coordinator = task_coordinator.TaskCoordinator(SimpleNamespace(root=root), settings)
    monkeypatch.setattr(task_coordinator.UIUtils, "show_message", lambda **kwargs: messages.append(kwargs))
    monkeypatch.setattr(
        coordinator,
        "_schedule_startup_update_check",
        lambda *, delay_ms, show_msg: schedules.append((delay_ms, show_msg)),
    )

    coordinator.handle_startup_tasks()

    assert settings.auto_update_values == [True]
    assert settings.marked is True
    assert messages[0]["message_level"] == "info"
    assert focus_calls == [True]
    assert schedules == [(900, False)]


def test_existing_user_schedules_automatic_update(monkeypatch: pytest.MonkeyPatch) -> None:
    coordinator = task_coordinator.TaskCoordinator(
        SimpleNamespace(root=object()),
        _Settings(first_run=True, auto_update=True),
    )
    schedules: list[tuple[int, bool]] = []
    monkeypatch.setattr(
        coordinator,
        "_schedule_startup_update_check",
        lambda *, delay_ms, show_msg: schedules.append((delay_ms, show_msg)),
    )

    coordinator.handle_startup_tasks()

    assert schedules == [(600, False)]


def test_scheduled_update_checks_liveness_before_running(monkeypatch: pytest.MonkeyPatch) -> None:
    callbacks: list[Callable[[], None]] = []
    root = object()
    coordinator = task_coordinator.TaskCoordinator(
        SimpleNamespace(root=root), _Settings(first_run=True, auto_update=True)
    )
    checks: list[bool] = []

    def schedule(_root: object, _key: str, _delay: int, callback: Callable[[], None], *, owner: object) -> None:
        del owner
        callbacks.append(callback)

    monkeypatch.setattr(
        task_coordinator.UIUtils,
        "schedule_debounce",
        schedule,
    )
    monkeypatch.setattr(task_coordinator, "is_qobject_alive", lambda _root: False)
    monkeypatch.setattr(coordinator, "check_for_updates", checks.append)

    coordinator._schedule_startup_update_check(delay_ms=-1, show_msg=True)
    callbacks[0]()

    assert checks == []


def test_update_check_passes_scope_and_handles_visible_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    messages: list[tuple[tuple[object, ...], dict[str, object]]] = []
    root = object()
    scope = object()
    coordinator = task_coordinator.TaskCoordinator(
        SimpleNamespace(root=root, scope=scope),
        _Settings(first_run=True, auto_update=True),
    )
    received: list[dict[str, object]] = []

    def fake_check(*args: object, **kwargs: object) -> None:
        del args
        received.append(kwargs)
        raise RuntimeError("服務不可用")

    monkeypatch.setattr(task_coordinator.UpdateChecker, "check_and_prompt_update", fake_check)
    monkeypatch.setattr(
        task_coordinator.UIUtils,
        "show_message",
        lambda *args, **kwargs: messages.append((args, kwargs)),
    )

    coordinator.check_for_updates(show_msg=True)

    kwargs = received[0]
    assert kwargs["parent"] is root
    assert kwargs["work_scope"] is scope
    assert messages[0][0][:2] == ("更新檢查失敗", "無法檢查更新：服務不可用")
