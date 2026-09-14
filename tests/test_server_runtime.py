from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import src.core.server.server_runtime as runtime_module
from src.core import ServerConfigChangeSet, ServerCRUD, ServerRuntime
from src.core.server.process_adapters import ProcessPort
from src.models import ServerConfig


class _FakeProcess:
    pid = 731

    def __init__(self) -> None:
        self.return_code: int | None = None
        self.hang_on_stop: bool = False
        self.running = False
        self.commands: list[str] = []
        self._output = ""
        self._on_output: Callable[[], None] | None = None
        self._on_finished: Callable[[int], None] | None = None
        self._on_error: Callable[[str], None] | None = None

    def start(self) -> None:
        self.running = True
        self.return_code = None

    def is_running(self) -> bool:
        return self.running

    def returncode(self) -> int | None:
        return self.return_code

    def read_output(self, max_bytes: int) -> str:
        output = self._output[:max_bytes]
        self._output = self._output[len(output) :]
        return output

    def write_line(self, command: str) -> bool:
        if not self.running:
            return False
        self.commands.append(f"{command}\n")
        if command.strip() == "stop" and not self.hang_on_stop:
            self.finish(0)
        return True

    def wait(self, timeout_seconds: float) -> bool:
        return timeout_seconds >= 0 and not self.running

    def terminate(self) -> None:
        if not self.hang_on_stop:
            self.finish(0)

    def kill(self) -> None:
        self.finish(-9)

    def connect(
        self,
        on_output: Callable[[], None],
        on_finished: Callable[[int], None],
        on_error: Callable[[str], None],
    ) -> None:
        self._on_output = on_output
        self._on_finished = on_finished
        self._on_error = on_error

    def feed(self, text: str) -> None:
        self._output += text
        if self._on_output is not None:
            self._on_output()

    def finish(self, return_code: int = 0) -> None:
        self.return_code = return_code
        self.running = False
        if self._on_finished is not None:
            self._on_finished(return_code)

    def fail(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)

    def close(self) -> None:
        self.running = False


def _make_runtime(
    tmp_path: Path,
    monkeypatch: Any,
    process_factory: Callable[[list[str], str], ProcessPort] | None = None,
) -> tuple[ServerRuntime, _FakeProcess]:
    servers_root = tmp_path / "servers"
    server_path = servers_root / "demo"
    server_path.mkdir(parents=True)
    (server_path / "server.jar").write_bytes(b"jar")
    (server_path / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    (server_path / "server.properties").write_text("server-port=25565\n", encoding="utf-8")
    (server_path / "run.bat").write_text("java -jar server.jar nogui\n", encoding="utf-8")
    crud = ServerCRUD(str(servers_root))
    config = ServerConfig(
        name="demo",
        minecraft_version="1.21.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(server_path),
    )
    baseline = crud.snapshot()
    assert crud.commit(ServerConfigChangeSet(upserts=(config,)), expected_revision=baseline.revision).success
    process = _FakeProcess()
    monkeypatch.setattr(
        runtime_module.SystemUtils,
        "register_managed_process",
        lambda _path, pid: type("ManagedProcess", (), {"pid": pid})(),
    )
    monkeypatch.setattr(runtime_module.SystemUtils, "unregister_managed_process", lambda *_args: None)
    monkeypatch.setattr(runtime_module.SystemUtils, "find_java_process", lambda *_args: None)
    monkeypatch.setattr(runtime_module.SystemUtils, "get_process_memory_usage", lambda *_args: 0)
    java_executable = tmp_path / "java.exe"
    java_executable.write_bytes(b"")
    monkeypatch.setattr(
        runtime_module.ServerCommands,
        "resolve_java_executable",
        staticmethod(lambda *_args, **_kwargs: str(java_executable)),
    )
    runtime = ServerRuntime(crud, process_factory=process_factory or (lambda _command, _cwd: process))
    return runtime, process


def test_runtime_reads_large_log_from_tail_without_rejecting_file(tmp_path: Path, monkeypatch: Any) -> None:
    runtime, _process = _make_runtime(tmp_path, monkeypatch)
    log_dir = tmp_path / "servers" / "demo" / "logs"
    log_dir.mkdir()
    log_file = log_dir / "latest.log"
    prefix = "x" * (2 * 1024 * 1024)
    log_file.write_text(f"{prefix}\nlatest-one\nlatest-two\n", encoding="utf-8")

    history = runtime.read_output_history("demo", max_lines=200, max_bytes=64 * 1024)

    assert history.lines[-2:] == ("latest-one", "latest-two")
    assert history.truncated is True


def test_runtime_history_preserves_repeated_process_output(tmp_path: Path, monkeypatch: Any) -> None:
    runtime, process = _make_runtime(tmp_path, monkeypatch)
    assert runtime.start("demo").success
    process.feed("same line\nsame line\n")

    history = runtime.read_output_history("demo")

    assert history.lines == ("same line", "same line")
    assert history.sequence == runtime.observe("demo").sequence


def test_runtime_owns_start_observe_command_and_stop(tmp_path: Path, monkeypatch: Any) -> None:
    runtime, process = _make_runtime(tmp_path, monkeypatch)

    result = runtime.start("demo")
    started = runtime.observe("demo")

    assert result.success
    assert started.is_running
    assert started.pid == process.pid
    assert runtime.send_command("demo", "say hello")
    assert process.commands[-1] == "say hello\n"
    assert runtime.stop("demo")
    assert runtime.observe("demo").state == "stopped"


def test_initialization_uses_same_runtime_and_stops_after_ready(tmp_path: Path, monkeypatch: Any) -> None:
    runtime, process = _make_runtime(tmp_path, monkeypatch)

    assert runtime.start("demo", intent="initialize").success
    process.feed('[Server thread/INFO]: Done (1.0s)! For help, type "help"\n')
    snapshot = runtime.observe("demo")

    assert any(event.kind == "ready" for event in snapshot.events)
    assert process.commands[-1] == "stop\n"
    assert snapshot.state == "stopped"


def test_runtime_process_error_preserves_live_process_state(tmp_path: Path, monkeypatch: Any) -> None:
    runtime, process = _make_runtime(tmp_path, monkeypatch)

    assert runtime.start("demo").success
    process.fail("模擬程序錯誤")

    snapshot = runtime.observe("demo")

    assert snapshot.is_running is True
    assert snapshot.state != "failed"
    assert runtime.begin_maintenance("demo") is False
    assert any(event.kind == "output" and "模擬程序錯誤" in event.message for event in snapshot.events)


def test_runtime_rejects_server_path_outside_root(tmp_path: Path) -> None:
    servers_root = tmp_path / "servers"
    outside = tmp_path / "outside"
    servers_root.mkdir()
    outside.mkdir()
    crud = ServerCRUD(str(servers_root))
    config = ServerConfig(
        name="escape",
        minecraft_version="1.21.1",
        loader_type="vanilla",
        loader_version="",
        memory_max_mb=2048,
        path=str(outside),
    )
    result = crud.commit(ServerConfigChangeSet(upserts=(config,)), expected_revision=crud.snapshot().revision)
    assert result.success is False

    result = ServerRuntime(crud).start("escape")

    assert result.failed
    assert result.title == "伺服器未找到"


def test_runtime_force_stop_invokes_kill_process_tree(tmp_path: Path, monkeypatch: Any) -> None:
    killed_processes: list[Any] = []
    killed_java_paths: list[Path] = []
    monkeypatch.setattr(
        runtime_module.SystemUtils, "kill_process_tree", lambda process: killed_processes.append(process)
    )
    monkeypatch.setattr(
        runtime_module.SystemUtils,
        "kill_java_processes_in_path",
        lambda path: killed_java_paths.append(path),
    )
    runtime, process = _make_runtime(tmp_path, monkeypatch)

    assert runtime.start("demo").success
    process.hang_on_stop = True
    assert runtime.stop("demo")
    assert any(getattr(target, "pid", None) == process.pid for target in killed_processes)
    assert killed_java_paths == [tmp_path / "servers" / "demo"]


def test_runtime_start_prevents_concurrent_duplicate_start(tmp_path: Path, monkeypatch: Any) -> None:
    runtime, _process = _make_runtime(tmp_path, monkeypatch)

    assert runtime.start("demo").success
    duplicate = runtime.start("demo")
    assert duplicate.failed
    assert duplicate.title == "伺服器已在執行"


def test_runtime_file_not_found_failure_releases_starting_reservation(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(runtime_module.SystemUtils, "kill_java_processes_in_path", lambda *_args: None)

    def missing_process(command: list[str], cwd: str) -> ProcessPort:
        raise FileNotFoundError(f"simulated executable disappearance: {command} ({cwd})")

    runtime, _process = _make_runtime(tmp_path, monkeypatch, process_factory=missing_process)

    result = runtime.start("demo")

    assert result.failed
    assert result.title == "啟動失敗"
    assert runtime.observe("demo").state == "stopped"
    assert runtime.begin_maintenance("demo") is True


def test_runtime_rejects_start_during_maintenance(tmp_path: Path, monkeypatch: Any) -> None:
    runtime, _process = _make_runtime(tmp_path, monkeypatch)

    assert runtime.begin_maintenance("demo") is True
    blocked = runtime.start("demo")
    assert blocked.failed
    assert blocked.title == "伺服器正在維護"

    runtime.end_maintenance("demo")
    assert runtime.start("demo").success


def test_runtime_rejects_maintenance_while_server_is_running(tmp_path: Path, monkeypatch: Any) -> None:
    runtime, _process = _make_runtime(tmp_path, monkeypatch)

    assert runtime.start("demo").success
    assert runtime.begin_maintenance("demo") is False
