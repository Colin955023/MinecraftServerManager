"""pytest 共用設定"""

from __future__ import annotations

import atexit
import logging
import os
import socket
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT_STR = str(PROJECT_ROOT)
if PROJECT_ROOT_STR not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_STR)
REPORT_ROOT_STR = str(PROJECT_ROOT / "report")
if REPORT_ROOT_STR not in sys.path:
    sys.path.insert(0, REPORT_ROOT_STR)

_SESSION_RUNTIME = tempfile.TemporaryDirectory(prefix="minecraft-server-manager-tests-")
_ORIGINAL_POPEN = subprocess.Popen
_ALLOWED_PROCESS_COMMANDS: set[tuple[str, ...]] = set()
os.environ["MSM_USER_DATA_DIR"] = _SESSION_RUNTIME.name
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["COVERAGE_FILE"] = str(Path(_SESSION_RUNTIME.name) / ".coverage")
atexit.register(_SESSION_RUNTIME.cleanup)
atexit.register(logging.shutdown)


def _block_external_access(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("測試禁止存取外部網路或啟動未授權程序")


def _guarded_popen(command: object, *args: object, **kwargs: object) -> Any:
    key = tuple(map(os.fspath, command)) if isinstance(command, list | tuple) else ()
    if key not in _ALLOWED_PROCESS_COMMANDS:
        _block_external_access()
    return _ORIGINAL_POPEN(cast(Any, command), *cast(Any, args), **cast(Any, kwargs))


@pytest.fixture
def make_junction(tmp_path: Path) -> Iterator[Callable[[Path, Path], Path]]:
    """建立不需要系統管理員權限的 Windows 目錄 junction"""
    created: list[Path] = []
    temp_root = tmp_path.resolve()

    def _create(link: Path, target: Path) -> Path:
        if not target.is_dir():
            raise ValueError("junction 目標必須是既有目錄")
        if not target.resolve().is_relative_to(temp_root) or not link.parent.resolve().is_relative_to(temp_root):
            raise ValueError("junction 只能建立在目前測試的暫存目錄內")
        if os.path.lexists(link):
            raise ValueError("junction 路徑已存在")
        command = ("cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target))
        _ALLOWED_PROCESS_COMMANDS.add(command)
        try:
            completed = subprocess.run(  # nosec B603
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        finally:
            _ALLOWED_PROCESS_COMMANDS.discard(command)
        assert completed.returncode == 0, completed.stdout.decode(errors="replace")
        created.append(link)
        return link

    yield _create

    for link in reversed(created):
        if os.path.lexists(link):
            Path.rmdir(link)


@pytest.fixture(autouse=True)
def isolate_test_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """測試一律以無 UI effect 的替身執行，禁止通知與確認視窗阻塞"""
    from src.ui import UIUtils

    monkeypatch.setenv("MSM_USER_DATA_DIR", str(tmp_path / "runtime-data"))
    monkeypatch.setattr(socket, "create_connection", _block_external_access)
    monkeypatch.setattr(socket, "getaddrinfo", _block_external_access)
    monkeypatch.setattr(socket.socket, "connect", _block_external_access)
    monkeypatch.setattr(subprocess, "Popen", _guarded_popen)
    monkeypatch.setattr(UIUtils, "show_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(UIUtils, "ask_yes_no_cancel", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(UIUtils, "_dispatch_dialog", staticmethod(lambda *_args, **_kwargs: False))


@pytest.fixture
def create_test_server() -> Callable[..., Path]:
    """
    建立測試用標準虛擬伺服器目錄
    """

    def _create(path: Path, *, script: str = "java -Xms1G -Xmx2G -jar server.jar\n") -> Path:
        path.mkdir(parents=True, exist_ok=True)
        (path / "server.jar").write_bytes(b"not-a-real-jar")
        (path / "eula.txt").write_text("eula=true\n", encoding="utf-8")
        (path / "start.bat").write_text(script, encoding="utf-8")
        return path

    return _create
