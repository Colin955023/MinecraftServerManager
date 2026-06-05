from pathlib import Path
from typing import Any

from src.utils.update_utils import update_checker as update_checker_module
from src.utils.update_utils.update_checker import UpdateChecker


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


def test_build_installer_launch_args_marks_normal_install(monkeypatch) -> None:
    monkeypatch.setattr(update_checker_module.RuntimePaths, "is_portable_mode", staticmethod(lambda: False))

    args = UpdateChecker._build_installer_launch_args(Path(r"C:\Temp\MinecraftServerManager-Setup.exe"))

    assert args == [r"C:\Temp\MinecraftServerManager-Setup.exe", "/MSMPortable=0"]


def test_build_installer_launch_args_preserves_portable_directory(monkeypatch) -> None:
    monkeypatch.setattr(update_checker_module.RuntimePaths, "is_portable_mode", staticmethod(lambda: True))
    monkeypatch.setattr(
        update_checker_module.RuntimePaths,
        "get_portable_base_dir",
        staticmethod(lambda: Path(r"C:\Apps\MinecraftServerManager")),
    )

    args = UpdateChecker._build_installer_launch_args(Path(r"C:\Temp\MinecraftServerManager-Setup.exe"))

    assert args == [
        r"C:\Temp\MinecraftServerManager-Setup.exe",
        "/MSMPortable=1",
        r"/DIR=C:\Apps\MinecraftServerManager",
    ]


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


def test_launch_installer_returns_false_when_user_cancels(tmp_path, monkeypatch) -> None:
    installer_path = tmp_path / "MinecraftServerManager-Setup.exe"
    installer_path.write_bytes(b"stub")
    interaction = ImmediateUpdateInteraction(ask_result=False)
    popen_calls: list[list[str]] = []

    monkeypatch.setattr(update_checker_module.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(
        update_checker_module.SubprocessUtils,
        "popen_detached",
        lambda args, **_kwargs: popen_calls.append(args),
    )

    assert UpdateChecker._launch_installer(installer_path, interaction=interaction) is False
    assert popen_calls == []


def test_launch_installer_uses_mode_args_when_confirmed(tmp_path, monkeypatch) -> None:
    installer_path = tmp_path / "MinecraftServerManager-Setup.exe"
    installer_path.write_bytes(b"stub")
    interaction = ImmediateUpdateInteraction(ask_result=True)
    popen_calls: list[list[str]] = []

    class StubProcess:
        pid = 1234

        def poll(self):
            return None

    monkeypatch.setattr(update_checker_module.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(update_checker_module.RuntimePaths, "is_portable_mode", staticmethod(lambda: False))

    def _popen_detached(args, **_kwargs):
        popen_calls.append(args)
        return StubProcess()

    monkeypatch.setattr(
        update_checker_module.SubprocessUtils,
        "popen_detached",
        _popen_detached,
    )

    assert UpdateChecker._launch_installer(installer_path, interaction=interaction) is True
    assert popen_calls == [[str(installer_path.resolve()), "/MSMPortable=0"]]


def test_installer_script_keeps_portable_install_uninstall_free() -> None:
    script = Path("scripts/installer.iss").read_text(encoding="utf-8")

    assert "Uninstallable=not IsPortableInstall" in script
    assert "CreateUninstallRegKey=not IsPortableInstall" in script
    assert 'Type: files; Name: "{app}\\unins*.exe"; Check: IsPortableInstall' in script
    assert "IsPortableUninstall" not in script


def test_installer_script_keeps_user_data_out_of_packaged_files() -> None:
    script = Path("scripts/installer.iss").read_text(encoding="utf-8")

    assert "Excludes:" in script
    assert ".config\\*" in script
    assert ".log\\*" in script
    assert "user_settings.json" in script
