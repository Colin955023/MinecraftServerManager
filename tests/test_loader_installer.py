from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.core.loader.loader_installer as loader_installer
from src.models import ProgressEvent


class _FinishedProcess:
    def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.pid = 1234
        self.returncode: int | None = returncode
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)

    def poll(self) -> int | None:
        return self.returncode


class _RunningProcess(_FinishedProcess):
    def __init__(self) -> None:
        super().__init__(0)
        self.returncode = None
        self.killed = False

    def poll(self) -> None:
        return None

    def kill(self) -> None:
        self.killed = True


def _replace_process_services(monkeypatch: pytest.MonkeyPatch, process: object) -> SimpleNamespace:
    calls = SimpleNamespace(registered=[], unregistered=[], killed=[], java_cleanup=[])

    def create_process(_args: list[str], *, cwd: str) -> object:
        del cwd
        return process

    monkeypatch.setattr(
        loader_installer.SubprocessUtils,
        "create_no_window_process",
        create_process,
    )
    monkeypatch.setattr(
        loader_installer.SystemUtils,
        "register_managed_process",
        lambda base_dir, pid: calls.registered.append((base_dir, pid)) or "managed",
    )
    monkeypatch.setattr(
        loader_installer.SystemUtils,
        "unregister_managed_process",
        lambda base_dir, managed: calls.unregistered.append((base_dir, managed)),
    )
    monkeypatch.setattr(
        loader_installer.SystemUtils,
        "kill_process_tree",
        lambda managed: calls.killed.append(managed),
    )
    monkeypatch.setattr(
        loader_installer.SystemUtils,
        "kill_java_processes_in_path",
        lambda base_dir: calls.java_cleanup.append(base_dir),
    )
    return calls


def _run(base_dir: Path, **overrides: object) -> bool | str:
    options = {
        "installer_args": ["java", "-jar", "installer.jar"],
        "base_dir": base_dir,
        "loader_type": "Fabric",
        "progress_callback": None,
        "cancel_check": lambda: False,
        "fail_callback": lambda message: f"失敗：{message}",
    }
    options.update(overrides)
    return loader_installer.run_installer_process(**options)  # type: ignore[arg-type]


def test_installer_success_reports_progress_and_post_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    process = _FinishedProcess(0, stdout="下載完成\n".encode())
    calls = _replace_process_services(monkeypatch, process)
    progress: list[ProgressEvent] = []

    result = _run(
        tmp_path,
        progress_callback=progress.append,
        post_install_result=lambda base_dir, loader_type: f"{base_dir.name}:{loader_type}",
    )

    assert result == f"{tmp_path.name}:Fabric"
    assert any("下載完成" in event.message for event in progress)
    assert progress[-1].message == "安裝成功，正在清理暫存檔案..."
    assert progress[-1].phase_percent == 100
    assert calls.registered == [(tmp_path, 1234)]
    assert calls.unregistered == [(tmp_path, "managed")]
    assert calls.killed == []
    assert calls.java_cleanup == []


def test_installer_failure_prefers_caused_by_detail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    process = _FinishedProcess(1, stderr=b"general error\nCaused by: dependency failed\n")
    calls = _replace_process_services(monkeypatch, process)

    result = _run(tmp_path)

    assert result == "失敗：Fabric 安裝程序執行失敗: Caused by: dependency failed"
    assert calls.java_cleanup == [tmp_path]
    assert calls.unregistered == [(tmp_path, "managed")]


def test_installer_cancel_terminates_managed_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    process = _RunningProcess()
    calls = _replace_process_services(monkeypatch, process)

    result = _run(tmp_path, cancel_check=lambda: True)

    assert result is False
    assert calls.killed == ["managed"]
    assert calls.java_cleanup == [tmp_path]


def test_installer_timeout_terminates_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    process = _RunningProcess()
    calls = _replace_process_services(monkeypatch, process)
    times = iter((100.0, 100.0 + loader_installer._MAX_RUNTIME_SECONDS))
    monkeypatch.setattr(loader_installer.time, "monotonic", lambda: next(times))

    result = _run(tmp_path)

    assert result == "失敗：Fabric 安裝程序執行逾時，已終止程序"
    assert calls.killed == ["managed"]


def test_installer_creation_error_is_converted_to_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def raise_creation_error(_args: list[str], *, cwd: str) -> None:
        raise OSError(f"無法啟動：{cwd}")

    monkeypatch.setattr(loader_installer.SubprocessUtils, "create_no_window_process", raise_creation_error)

    result = _run(tmp_path)

    assert result == f"失敗：執行 Fabric 安裝器時發生錯誤：無法啟動：{tmp_path}"


def test_decode_stream_line_supports_big5_and_replacement() -> None:
    assert loader_installer._decode_stream_line("錯誤".encode("big5")) == "錯誤"
    assert "�" in loader_installer._decode_stream_line(b"\xff")


def test_installer_progress_tracker_keeps_text_only_output_determinate_and_monotonic() -> None:
    tracker = loader_installer.InstallerProgressTracker("Forge")
    lines = [
        "JVM info: Microsoft - 21 - 21",
        "Installing server to current directory",
        "Considering minecraft server jar",
        "Downloading library from https://example.invalid/library.jar",
        "Running processor: DOWNLOAD_MOJMAPS",
        "Patching server jar",
    ]

    events = [tracker.update(line) for line in lines]

    assert all(event.total_units == 100 for event in events)
    percentages = [event.phase_percent for event in events]
    assert all(percent is not None for percent in percentages)
    numeric = [float(percent) for percent in percentages if percent is not None]
    assert numeric == sorted(numeric)
    assert numeric[-1] >= 84


def test_installer_progress_tracker_prefers_explicit_percent_without_regression() -> None:
    tracker = loader_installer.InstallerProgressTracker("Fabric")

    first = tracker.update("Installing Fabric Loader on the server")
    explicit = tracker.update("Downloading files 72%")
    stale = tracker.update("Downloading files 20%")

    assert first.phase_percent is not None
    assert explicit.phase_percent == 72
    assert stale.phase_percent == 72


def test_installer_progress_tracker_ignores_duplicate_generic_lines() -> None:
    tracker = loader_installer.InstallerProgressTracker("Forge")

    first = tracker.update("Resolving task")
    duplicate = tracker.update("  resolving   task  ")

    assert duplicate.phase_percent == first.phase_percent


def test_installer_progress_tracker_parses_full_line_before_truncating_display_text() -> None:
    tracker = loader_installer.InstallerProgressTracker("Forge")
    long_line = f"{'x' * 100} successfully installed"

    event = tracker.update(long_line)

    assert event.phase_percent == 98
    assert event.message.endswith("...")
    assert "successfully installed" not in event.message
