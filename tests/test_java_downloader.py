from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.utils.java_support.java_downloader as java_downloader
from src.utils import JavaInstallError


def test_winget_available_uses_noninteractive_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="v1.9.0\n")

    monkeypatch.setattr(java_downloader.SubprocessUtils, "run_checked", fake_run)

    assert java_downloader.JavaDownloader._is_winget_available() is True
    assert calls[0][0] == ["winget", "--version"]
    assert calls[0][1]["stdin"] is java_downloader.SubprocessUtils.DEVNULL


@pytest.mark.parametrize(
    ("major", "package"),
    ((8, "Oracle.JavaRuntimeEnvironment"), (11, "Microsoft.OpenJDK.11"), (25, "Microsoft.OpenJDK.25")),
)
def test_install_java_maps_supported_versions_without_real_winget(
    monkeypatch: pytest.MonkeyPatch, major: int, package: str
) -> None:
    commands: list[list[str]] = []

    def record_command(command: list[str]) -> int:
        commands.append(command)
        return 0

    monkeypatch.setattr(java_downloader.JavaDownloader, "_is_winget_available", staticmethod(lambda: True))
    monkeypatch.setattr(
        java_downloader.SubprocessUtils,
        "run_winget_interactive",
        record_command,
    )

    assert java_downloader.JavaDownloader.install_java_with_winget(major) is None
    assert commands == [["install", "--accept-package-agreements", "--accept-source-agreements", package]]


def test_install_java_rejects_missing_winget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(java_downloader.JavaDownloader, "_is_winget_available", staticmethod(lambda: False))

    with pytest.raises(JavaInstallError, match="無法呼叫 winget"):
        java_downloader.JavaDownloader.install_java_with_winget(21)


def test_install_java_rejects_unsupported_version_before_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def record_command(command: list[str]) -> int:
        calls.append(command)
        return 0

    monkeypatch.setattr(java_downloader.JavaDownloader, "_is_winget_available", staticmethod(lambda: True))
    monkeypatch.setattr(
        java_downloader.SubprocessUtils,
        "run_winget_interactive",
        record_command,
    )

    with pytest.raises(JavaInstallError, match="不支援自動安裝"):
        java_downloader.JavaDownloader.install_java_with_winget(22)

    assert calls == []


def test_install_java_wraps_winget_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(java_downloader.JavaDownloader, "_is_winget_available", staticmethod(lambda: True))
    monkeypatch.setattr(java_downloader.SubprocessUtils, "run_winget_interactive", lambda _command: 17)

    with pytest.raises(JavaInstallError, match=r"透過 winget 安裝 Microsoft\.OpenJDK\.21 失敗 \(結束代碼: 0x11\)"):
        java_downloader.JavaDownloader.install_java_with_winget(21)


def test_install_java_interprets_uac_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(java_downloader.JavaDownloader, "_is_winget_available", staticmethod(lambda: True))
    monkeypatch.setattr(java_downloader.SubprocessUtils, "run_winget_interactive", lambda _command: 0x800704C7)

    with pytest.raises(JavaInstallError, match="使用者取消安裝或拒絕 UAC 驗證"):
        java_downloader.JavaDownloader.install_java_with_winget(21)


def test_install_java_interprets_access_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(java_downloader.JavaDownloader, "_is_winget_available", staticmethod(lambda: True))
    monkeypatch.setattr(java_downloader.SubprocessUtils, "run_winget_interactive", lambda _command: 0x80070005)

    with pytest.raises(JavaInstallError, match="存取被拒，需要管理員權限"):
        java_downloader.JavaDownloader.install_java_with_winget(17)


def test_install_java_interprets_msi_in_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(java_downloader.JavaDownloader, "_is_winget_available", staticmethod(lambda: True))
    monkeypatch.setattr(java_downloader.SubprocessUtils, "run_winget_interactive", lambda _command: 1618)

    with pytest.raises(JavaInstallError, match="另一個安裝程式正在執行中，請稍後重試"):
        java_downloader.JavaDownloader.install_java_with_winget(21)


def test_install_java_interprets_already_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(java_downloader.JavaDownloader, "_is_winget_available", staticmethod(lambda: True))
    monkeypatch.setattr(java_downloader.SubprocessUtils, "run_winget_interactive", lambda _command: 0x8A150056)

    with pytest.raises(JavaInstallError, match="系統已安裝此版本"):
        java_downloader.JavaDownloader.install_java_with_winget(21)
