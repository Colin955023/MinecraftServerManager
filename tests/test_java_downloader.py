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

    with pytest.raises(JavaInstallError, match=r"透過 winget 安裝 Microsoft\.OpenJDK\.21 失敗"):
        java_downloader.JavaDownloader.install_java_with_winget(21)
