from pathlib import Path
from typing import Any

from src.utils.update_utils.update_checker import UpdateChecker


class ImmediateUpdateInteraction:
    """測試用的同步更新互動介面。"""

    def __init__(self) -> None:
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
        return False

    def show_info(self, title: str, message: str, **kwargs: Any) -> None:
        _ = kwargs
        self.info_messages.append((title, message))

    def show_error(self, title: str, message: str, **kwargs: Any) -> None:
        _ = kwargs
        self.error_messages.append((title, message))

    def open_external(self, target: str) -> None:
        self.info_messages.append(("open_external", target))


def test_escape_powershell_single_quoted_literal_doubles_single_quotes() -> None:
    """測試 _escape_powershell_single_quoted_literal 是否正確轉義單引號。"""
    assert UpdateChecker._escape_powershell_single_quoted_literal("O'Brien") == "'O''Brien'"


def test_build_portable_update_script_escapes_paths_and_includes_cleanup_steps() -> None:
    source_dir = Path(r"C:\Temp\O'Brien\source")
    destination_dir = Path(r"C:\Temp\Minecraft Server\dest")
    backup_dir = Path(r"C:\Temp\backup folder")
    cleanup_dir = Path(r"C:\Temp\cleanup folder")

    script = UpdateChecker._build_portable_update_script(
        source_dir=source_dir,
        destination_dir=destination_dir,
        backup_dir=backup_dir,
        cleanup_dir=cleanup_dir,
    )

    assert "$ErrorActionPreference = 'Stop'" in script
    assert "$sourceDir = 'C:\\Temp\\O''Brien\\source'" in script
    assert "$destinationDir = 'C:\\Temp\\Minecraft Server\\dest'" in script
    assert "$backupDir = 'C:\\Temp\\backup folder'" in script
    assert "$cleanupDir = 'C:\\Temp\\cleanup folder'" in script
    assert "Remove-Item -LiteralPath $cleanupDir -Recurse -Force -ErrorAction SilentlyContinue" in script
    assert "Remove-Item -LiteralPath $backupDir -Recurse -Force -ErrorAction SilentlyContinue" in script
    assert "Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue" in script


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
