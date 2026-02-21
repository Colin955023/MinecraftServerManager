from __future__ import annotations

import pytest
from src.utils import HTTPUtils, UpdateParsing


@pytest.mark.smoke
def test_get_latest_release_skips_draft_and_prerelease(monkeypatch) -> None:
    payload = [
        {"tag_name": "v9.9.9", "draft": True, "prerelease": False},
        {"tag_name": "v2.0.0-rc1", "draft": False, "prerelease": True},
        {"tag_name": "v1.6.7", "draft": False, "prerelease": False},
    ]
    monkeypatch.setattr(UpdateParsing, "_GITHUB_API", "https://example.invalid")
    monkeypatch.setattr(HTTPUtils, "get_json", lambda *_args, **_kwargs: payload)

    latest = UpdateParsing.get_latest_release("owner", "repo")
    assert latest["tag_name"] == "v1.6.7"


@pytest.mark.smoke
def test_get_latest_release_can_include_prerelease(monkeypatch) -> None:
    payload = [
        {"tag_name": "v1.7.0-rc1", "draft": False, "prerelease": True},
        {"tag_name": "v1.6.7", "draft": False, "prerelease": False},
    ]
    monkeypatch.setattr(UpdateParsing, "_GITHUB_API", "https://example.invalid")
    monkeypatch.setattr(HTTPUtils, "get_json", lambda *_args, **_kwargs: payload)

    latest = UpdateParsing.get_latest_release("owner", "repo", include_prerelease=True)
    assert latest["tag_name"] == "v1.7.0-rc1"


@pytest.mark.smoke
def test_select_update_asset_prefers_portable_zip() -> None:
    release = {
        "assets": [
            {"name": "MinecraftServerManager-Setup-1.6.7.exe", "browser_download_url": "https://example/installer.exe"},
            {"name": "MinecraftServerManager-v1.6.7-portable.zip", "browser_download_url": "https://example/portable.zip"},
        ]
    }

    asset, mode = UpdateParsing.select_update_asset(release, portable_mode=True)
    assert mode == "portable"
    assert asset["name"].endswith("-portable.zip")


@pytest.mark.smoke
def test_select_update_asset_falls_back_to_installer_when_portable_missing() -> None:
    release = {
        "assets": [
            {"name": "MinecraftServerManager-Setup-1.6.7.exe", "browser_download_url": "https://example/installer.exe"},
        ]
    }

    asset, mode = UpdateParsing.select_update_asset(release, portable_mode=True)
    assert mode == "installer_fallback"
    assert asset["name"].endswith(".exe")


@pytest.mark.smoke
def test_select_update_asset_returns_none_when_no_valid_asset() -> None:
    release = {"assets": [{"name": "notes.txt"}]}
    asset, mode = UpdateParsing.select_update_asset(release, portable_mode=False)
    assert asset == {}
    assert mode == "none"
