from __future__ import annotations

import io
import subprocess
from pathlib import Path
from typing import Any

import src.core.server.server_runtime as runtime_module
from src.core import ServerCRUD, ServerRuntime
from src.models import ServerConfig


class _Signal:
    def __init__(self) -> None:
        self._callbacks: list[Any] = []

    def connect(self, callback: Any) -> None:
        self._callbacks.append(callback)

    def emit(self, *args: Any) -> None:
        for callback in tuple(self._callbacks):
            callback(*args)


class _Input:
    def __init__(self, process: _FakeProcess) -> None:
        self.process = process
        self.commands: list[str] = []

    def write(self, payload: str) -> None:
        self.commands.append(payload)
        if payload.strip() == "stop":
            self.process.return_code = 0

    def flush(self) -> None:
        return


class _FakeProcess:
    pid = 731

    def __init__(self) -> None:
        self.return_code: int | None = None
        self.hang_on_stop: bool = False
        self.stdout = io.StringIO()
        self.stdin = _Input(self)
        self.readyReadStandardOutput = _Signal()
        self.finished = _Signal()
        self.errorOccurred = _Signal()

    def start(self) -> None:
        return

    def poll(self) -> int | None:
        return self.return_code

    def wait(self, timeout: float = 0.0) -> int:
        if self.hang_on_stop or self.return_code is None:
            raise subprocess.TimeoutExpired("fake-server", timeout)
        return self.return_code

    def terminate(self) -> None:
        if not self.hang_on_stop:
            self.return_code = 0

    def kill(self) -> None:
        self.return_code = -9

    def feed(self, text: str) -> None:
        self.stdout = io.StringIO(text)
        self.readyReadStandardOutput.emit()


def _make_runtime(tmp_path: Path, monkeypatch: Any) -> tuple[ServerRuntime, _FakeProcess]:
    servers_root = tmp_path / "servers"
    server_path = servers_root / "demo"
    server_path.mkdir(parents=True)
    (server_path / "server.jar").write_bytes(b"jar")
    (server_path / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    (server_path / "server.properties").write_text("server-port=25565\n", encoding="utf-8")
    (server_path / "run.bat").write_text("java -jar server.jar nogui\n", encoding="utf-8")
    crud = ServerCRUD(str(servers_root))
    crud.servers["demo"] = ServerConfig(
        name="demo",
        minecraft_version="1.21.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(server_path),
    )
    process = _FakeProcess()
    monkeypatch.setattr(runtime_module.SystemUtils, "register_managed_process", lambda *_args: None)
    monkeypatch.setattr(runtime_module.SystemUtils, "unregister_managed_process", lambda *_args: None)
    monkeypatch.setattr(runtime_module.SystemUtils, "find_java_process", lambda *_args: None)
    monkeypatch.setattr(runtime_module.SystemUtils, "get_process_memory_usage", lambda *_args: 0)
    runtime = ServerRuntime(crud, process_factory=lambda _command, _cwd: process)
    return runtime, process


def test_runtime_owns_start_observe_command_and_stop(tmp_path: Path, monkeypatch: Any) -> None:
    runtime, process = _make_runtime(tmp_path, monkeypatch)

    result = runtime.start("demo")
    started = runtime.observe("demo")

    assert result.success
    assert started.is_running
    assert started.pid == process.pid
    assert runtime.send_command("demo", "say hello")
    assert process.stdin.commands[-1] == "say hello\n"
    assert runtime.stop("demo")
    assert runtime.observe("demo").state == "stopped"


def test_initialization_uses_same_runtime_and_stops_after_ready(tmp_path: Path, monkeypatch: Any) -> None:
    runtime, process = _make_runtime(tmp_path, monkeypatch)

    assert runtime.start("demo", intent="initialize").success
    process.feed('[Server thread/INFO]: Done (1.0s)! For help, type "help"\n')
    snapshot = runtime.observe("demo")

    assert any(event.kind == "ready" for event in snapshot.events)
    assert process.stdin.commands[-1] == "stop\n"
    assert snapshot.state == "stopped"


def test_runtime_rejects_server_path_outside_root(tmp_path: Path) -> None:
    servers_root = tmp_path / "servers"
    outside = tmp_path / "outside"
    servers_root.mkdir()
    outside.mkdir()
    crud = ServerCRUD(str(servers_root))
    crud.servers["escape"] = ServerConfig(
        name="escape",
        minecraft_version="1.21.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(outside),
    )

    result = ServerRuntime(crud).start("escape")

    assert result.failed
    assert result.title == "伺服器路徑無效"


def test_runtime_force_stop_invokes_kill_process_tree(tmp_path: Path, monkeypatch: Any) -> None:
    killed_pids: list[int] = []
    monkeypatch.setattr(runtime_module.SystemUtils, "kill_process_tree", lambda pid: killed_pids.append(pid))
    runtime, process = _make_runtime(tmp_path, monkeypatch)

    assert runtime.start("demo").success
    process.hang_on_stop = True
    assert runtime.stop("demo")
    assert process.pid in killed_pids


def test_runtime_start_prevents_concurrent_duplicate_start(tmp_path: Path, monkeypatch: Any) -> None:
    runtime, _process = _make_runtime(tmp_path, monkeypatch)

    assert runtime.start("demo").success
    duplicate = runtime.start("demo")
    assert duplicate.failed
    assert duplicate.title == "伺服器已在執行"
