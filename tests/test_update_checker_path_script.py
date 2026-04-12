from pathlib import Path

from src.utils.update_utils.update_checker import UpdateChecker


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
