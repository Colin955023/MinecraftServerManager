from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import src.utils.runtime_utils.system_utils as system_utils_module
from src.utils import SystemUtils


class _FakeManagedProcess:
    def __init__(self, pid: int, *, running: bool = True, children: tuple[_FakeManagedProcess, ...] = ()) -> None:
        self.pid = pid
        self.running = running
        self.children_processes = children
        self.killed = False

    def is_running(self) -> bool:
        return self.running

    def children(self, *, recursive: bool = False) -> list[_FakeManagedProcess]:
        if not recursive:
            return list(self.children_processes)
        descendants: list[_FakeManagedProcess] = []
        pending = list(self.children_processes)
        while pending:
            child = pending.pop()
            descendants.append(child)
            pending.extend(child.children_processes)
        return descendants

    def kill(self) -> None:
        self.killed = True
        self.running = False


@pytest.fixture(autouse=True)
def _clear_managed_processes() -> Any:
    SystemUtils._managed_processes_by_path.clear()
    yield
    SystemUtils._managed_processes_by_path.clear()


def test_path_cleanup_skips_pid_reused_by_another_process(monkeypatch: Any, tmp_path: Path) -> None:
    old_process = _FakeManagedProcess(4101, running=False)
    monkeypatch.setattr(system_utils_module.psutil, "Process", lambda _pid: old_process)

    assert SystemUtils.register_managed_process(tmp_path, old_process.pid) is old_process

    assert SystemUtils.kill_java_processes_in_path(tmp_path) is False
    assert old_process.killed is False
    assert not SystemUtils._managed_processes_by_path


def test_old_token_unregister_does_not_remove_new_process_with_same_pid(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    old_process = _FakeManagedProcess(4102)
    new_process = _FakeManagedProcess(4102)
    processes = iter((old_process, new_process))
    monkeypatch.setattr(system_utils_module.psutil, "Process", lambda _pid: next(processes))
    monkeypatch.setattr(system_utils_module.psutil, "wait_procs", lambda *_args, **_kwargs: None)

    old_token = SystemUtils.register_managed_process(tmp_path, old_process.pid)
    new_token = SystemUtils.register_managed_process(tmp_path, old_process.pid)
    assert old_token is old_process
    assert new_token is new_process

    SystemUtils.unregister_managed_process(tmp_path, old_token)

    assert SystemUtils.kill_java_processes_in_path(tmp_path) is True
    assert old_process.killed is False
    assert new_process.killed is True


def test_register_accepts_qprocess_process_id_and_kill_tree_uses_token(monkeypatch: Any, tmp_path: Path) -> None:
    child = _FakeManagedProcess(4104)
    managed_process = _FakeManagedProcess(4103, children=(child,))
    observed_pids: list[int] = []

    def fake_psutil_process(pid: int) -> _FakeManagedProcess:
        observed_pids.append(pid)
        return managed_process

    monkeypatch.setattr(system_utils_module.psutil, "Process", fake_psutil_process)
    monkeypatch.setattr(system_utils_module.psutil, "wait_procs", lambda *_args, **_kwargs: None)
    token = SystemUtils.register_managed_process(tmp_path, managed_process.pid)

    assert token is managed_process
    assert observed_pids == [managed_process.pid]
    assert SystemUtils.kill_java_processes_in_path(tmp_path) is True
    assert managed_process.killed is True
    assert child.killed is True
