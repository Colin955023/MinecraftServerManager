from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.utils.runtime_utils.subprocess_utils as subprocess_utils_module


@pytest.mark.smoke
def test_run_checked_resolves_path_entry_and_forces_shell_false(monkeypatch, tmp_path) -> None:
    resolved_executable = tmp_path / "bin" / "java.exe"
    resolved_executable.parent.mkdir(parents=True, exist_ok=True)
    resolved_executable.write_text("", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, args=cmd)

    monkeypatch.setattr(
        subprocess_utils_module.PathUtils,
        "find_executable",
        staticmethod(lambda name: str(resolved_executable) if name == "java" else None),
    )
    monkeypatch.setattr(subprocess_utils_module.subprocess, "run", fake_run)

    result = subprocess_utils_module.SubprocessUtils.run_checked(["java", "-version"], shell=True, check=False)

    assert result.returncode == 0
    assert captured["cmd"] == [str(resolved_executable), "-version"]
    assert captured["kwargs"] == {"shell": False, "check": False}


@pytest.mark.smoke
def test_popen_checked_forces_shell_false_for_absolute_path(monkeypatch, tmp_path) -> None:
    executable = tmp_path / "java.exe"
    executable.write_text("", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return SimpleNamespace(pid=12345, args=cmd)

    monkeypatch.setattr(subprocess_utils_module.subprocess, "Popen", fake_popen)

    process = subprocess_utils_module.SubprocessUtils.popen_checked(
        [str(executable), "-jar", "server.jar"],
        shell=True,
        cwd=str(tmp_path),
    )

    assert process.pid == 12345
    assert captured["cmd"] == [str(executable), "-jar", "server.jar"]
    assert captured["kwargs"] == {"shell": False, "cwd": str(tmp_path)}


@pytest.mark.smoke
@pytest.mark.parametrize(
    "method_name",
    [
        "run_checked",
        "popen_checked",
    ],
)
def test_checked_subprocess_methods_reject_executable_override(monkeypatch, tmp_path, method_name: str) -> None:
    resolved_executable = tmp_path / "bin" / "java.exe"
    resolved_executable.parent.mkdir(parents=True, exist_ok=True)
    resolved_executable.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        subprocess_utils_module.PathUtils,
        "find_executable",
        staticmethod(lambda name: str(resolved_executable) if name == "java" else None),
    )

    method = getattr(subprocess_utils_module.SubprocessUtils, method_name)
    with pytest.raises(ValueError, match="不允許覆寫 executable"):
        method(["java", "-version"], executable="cmd.exe")


@pytest.mark.smoke
def test_validate_cmd_rejects_blank_executable() -> None:
    with pytest.raises(ValueError, match="cmd\\[0\\] 不得為空"):
        subprocess_utils_module.SubprocessUtils._validate_cmd(["   "])
