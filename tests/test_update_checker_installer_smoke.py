from typing import Any

import src.utils.update_utils.update_checker as update_checker_module
from src.utils import UpdateChecker


class ImmediateUpdateInteraction:
    """測試用的同步更新互動介面。"""

    def __init__(self, ask_result: bool | None = False) -> None:
        self.ask_result = ask_result
        self.info_messages: list[tuple[str, str]] = []
        self.error_messages: list[tuple[str, str]] = []

    def run_async(self, work) -> None:
        work()

    def call_on_ui(self, parent: Any, callback):
        _ = parent
        return callback()

    def schedule_debounce(self, widget: Any, job_attr: str, delay_ms: int, callback, *, owner: Any | None = None):
        _ = (widget, job_attr, delay_ms, owner)
        return callback()

    def ask_yes_no_cancel(self, title: str, message: str, **kwargs: Any) -> bool | None:
        _ = (title, message, kwargs)
        return self.ask_result

    def show_info(self, title: str, message: str, **kwargs: Any) -> None:
        _ = kwargs
        self.info_messages.append((title, message))

    def show_error(self, title: str, message: str, **kwargs: Any) -> None:
        _ = kwargs
        self.error_messages.append((title, message))

    def open_external(self, target: str) -> None:
        self.info_messages.append(("open_external", target))


def test_check_and_prompt_update_uses_injected_interaction(monkeypatch) -> None:
    interaction = ImmediateUpdateInteraction()
    monkeypatch.setattr(
        UpdateChecker,
        "_get_latest_release",
        staticmethod(lambda *_args, **_kwargs: {"tag_name": "v1.0.0", "name": "v1.0.0", "assets": []}),
    )

    UpdateChecker.check_and_prompt_update(
        "1.0.0",
        "owner",
        "repo",
        show_up_to_date_message=True,
        interaction=interaction,
    )

    assert interaction.info_messages
    assert interaction.info_messages[0][0] == "檢查更新"
    assert not interaction.error_messages


def test_apply_update_returns_false_when_user_cancels(tmp_path, monkeypatch) -> None:
    new_exe_path = tmp_path / "MinecraftServerManager.exe"
    new_exe_path.write_bytes(b"stub")
    interaction = ImmediateUpdateInteraction(ask_result=False)
    popen_calls: list[list[str]] = []

    monkeypatch.setattr(
        update_checker_module.SubprocessUtils,
        "popen_detached",
        lambda args, **_kwargs: popen_calls.append(args),
    )

    monkeypatch.setattr(update_checker_module.sys, "executable", str(tmp_path / "current_app.exe"))

    assert UpdateChecker._apply_update(new_exe_path, interaction=interaction) is False
    assert popen_calls == []


def test_apply_update_creates_bat_and_starts_process_when_confirmed(tmp_path, monkeypatch) -> None:
    new_exe_path = tmp_path / "MinecraftServerManager.exe"
    new_exe_path.write_bytes(b"stub")
    interaction = ImmediateUpdateInteraction(ask_result=True)
    popen_calls: list[list[str]] = []

    class StubProcess:
        pid = 1234

        def poll(self):
            return None

    def _popen_detached(args, **_kwargs):
        popen_calls.append(args)
        return StubProcess()

    monkeypatch.setattr(
        update_checker_module.SubprocessUtils,
        "popen_detached",
        _popen_detached,
    )

    current_app_exe = tmp_path / "current_app.exe"
    monkeypatch.setattr(update_checker_module.sys, "executable", str(current_app_exe))

    assert UpdateChecker._apply_update(new_exe_path, interaction=interaction) is True

    # Assert bat script was created
    bat_script_path = new_exe_path.with_suffix(".update.bat")
    assert bat_script_path.exists()
    bat_content = bat_script_path.read_text(encoding="utf-8")
    assert str(new_exe_path.resolve(strict=True)) in bat_content
    assert str(current_app_exe) in bat_content

    # Assert popen was called with the bat script
    assert popen_calls == [[str(bat_script_path)]]
