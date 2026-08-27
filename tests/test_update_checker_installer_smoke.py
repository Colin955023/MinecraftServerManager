from typing import Any

import src.utils.update_utils.update_checker as update_checker_module
from src.utils import UpdateChecker


class ImmediateUpdateInteraction:
    def __init__(self, ask_result: bool | None = False) -> None:
        self.ask_result = ask_result
        self.info_messages: list[tuple[str, str]] = []
        self.error_messages: list[tuple[str, str]] = []

    def submit(self, work, **_kwargs) -> None:
        work()

    def call_on_ui(self, callback: Any, *args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        return callback()

    def schedule_debounce(self, widget: Any, job_attr: str, delay_ms: int, callback, *, owner: Any | None = None):
        _ = (widget, job_attr, delay_ms, owner)
        return callback()

    def ask_yes_no_cancel(self, title: str, message: str, **kwargs: Any) -> bool | None:
        _ = (title, message, kwargs)
        return self.ask_result

    def show_message(self, title: str, message: str, message_level: str = "info", **kwargs: Any) -> None:
        _ = kwargs
        if message_level == "error":
            self.error_messages.append((title, message))
        else:
            self.info_messages.append((title, message))

    def open_external(self, target: str) -> None:
        self.info_messages.append(("open_external", target))


def test_check_and_prompt_update_uses_injected_interaction(monkeypatch) -> None:
    interaction = ImmediateUpdateInteraction()
    monkeypatch.setattr(
        update_checker_module.UpdateParsing,
        "get_latest_release",
        staticmethod(lambda *_args, **_kwargs: {"tag_name": "v1.0.0", "name": "v1.0.0", "assets": []}),
    )

    monkeypatch.setattr(update_checker_module, "run_on_ui_thread", interaction.call_on_ui)
    monkeypatch.setattr(update_checker_module.UIUtils, "ask_yes_no_cancel", interaction.ask_yes_no_cancel)
    monkeypatch.setattr(update_checker_module.UIUtils, "show_message", interaction.show_message)
    monkeypatch.setattr(update_checker_module.UIUtils, "schedule_debounce", interaction.schedule_debounce)
    monkeypatch.setattr(update_checker_module.UIUtils, "open_external", interaction.open_external)

    UpdateChecker.check_and_prompt_update(
        "1.0.0",
        "owner",
        "repo",
        show_up_to_date_message=True,
        parent=None,
        work_scope=interaction,
    )

    assert interaction.info_messages
    assert interaction.info_messages[0][0] == "檢查更新"
    assert not interaction.error_messages


def test_apply_update_returns_false_when_user_cancels(tmp_path, monkeypatch) -> None:
    new_exe_path = tmp_path / "MinecraftServerManager.exe"
    new_exe_path.write_bytes(b"stub")
    interaction = ImmediateUpdateInteraction(ask_result=False)
    monkeypatch.setattr(update_checker_module, "run_on_ui_thread", interaction.call_on_ui)
    monkeypatch.setattr(update_checker_module.UIUtils, "ask_yes_no_cancel", interaction.ask_yes_no_cancel)
    monkeypatch.setattr(update_checker_module.UIUtils, "show_message", interaction.show_message)
    popen_calls: list[list[str]] = []

    monkeypatch.setattr(
        update_checker_module.SubprocessUtils,
        "popen_detached",
        lambda args, **_kwargs: popen_calls.append(args),
    )

    monkeypatch.setattr(update_checker_module.sys, "executable", str(tmp_path / "current_app.exe"))

    assert UpdateChecker._apply_update(new_exe_path) is False
    assert popen_calls == []


def test_apply_update_creates_bat_and_starts_process_when_confirmed(tmp_path, monkeypatch) -> None:
    new_exe_path = tmp_path / "MinecraftServerManager.exe"
    new_exe_path.write_bytes(b"stub")
    interaction = ImmediateUpdateInteraction(ask_result=True)
    monkeypatch.setattr(update_checker_module, "run_on_ui_thread", interaction.call_on_ui)
    monkeypatch.setattr(update_checker_module.UIUtils, "ask_yes_no_cancel", interaction.ask_yes_no_cancel)
    monkeypatch.setattr(update_checker_module.UIUtils, "show_message", interaction.show_message)
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

    assert UpdateChecker._apply_update(new_exe_path) is True

    bat_script_path = new_exe_path.with_suffix(".update.bat")
    assert bat_script_path.exists()
    bat_content = bat_script_path.read_text(encoding="utf-8")
    assert str(new_exe_path.resolve(strict=True)) in bat_content
    assert str(current_app_exe) in bat_content
    assert "chcp 65001 >nul" in bat_content
    assert f"GEQ {UpdateChecker.REPLACE_RETRY_LIMIT}" in bat_content
    assert ":failed" in bat_content
    assert ":success" in bat_content

    assert popen_calls == [[str(bat_script_path)]]


def test_markdown_to_safe_text_preserves_code_text() -> None:
    rendered = UpdateChecker._markdown_to_safe_text(
        "Use `server.jar` with:\n```powershell\njava -jar server.jar nogui\n```"
    )

    assert "server.jar" in rendered
    assert "java -jar server.jar nogui" in rendered
    assert "`" not in rendered
