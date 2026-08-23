from __future__ import annotations

from src.utils import HTTPClient, UpdateParsing


def test_get_latest_release_skips_draft_and_prerelease(monkeypatch) -> None:
    payload = [
        {"tag_name": "v9.9.9", "draft": True, "prerelease": False},
        {"tag_name": "v2.0.0-rc1", "draft": False, "prerelease": True},
        {"tag_name": "v1.6.7", "draft": False, "prerelease": False},
    ]
    monkeypatch.setattr(UpdateParsing, "_GITHUB_API", "https://example.invalid")
    monkeypatch.setattr(HTTPClient, "fetch_json", lambda *_args, **_kwargs: payload)

    latest = UpdateParsing.get_latest_release("owner", "repo")
    assert latest["tag_name"] == "v1.6.7"


def test_get_latest_release_can_include_prerelease(monkeypatch) -> None:
    payload = [
        {"tag_name": "v1.7.0-rc1", "draft": False, "prerelease": True},
        {"tag_name": "v1.6.7", "draft": False, "prerelease": False},
    ]
    monkeypatch.setattr(UpdateParsing, "_GITHUB_API", "https://example.invalid")
    monkeypatch.setattr(HTTPClient, "fetch_json", lambda *_args, **_kwargs: payload)

    latest = UpdateParsing.get_latest_release("owner", "repo", include_prerelease=True)
    assert latest["tag_name"] == "v1.7.0-rc1"


def test_select_update_asset_prefers_executable() -> None:
    release = {
        "assets": [
            {"name": "notes.txt", "browser_download_url": "https://example/notes.txt"},
            {
                "name": "MinecraftServerManager-v1.6.7.zip",
                "browser_download_url": "https://example/archive.zip",
            },
            {"name": "MinecraftServerManager.exe", "browser_download_url": "https://example/app.exe"},
        ]
    }

    asset, mode = UpdateParsing.select_update_asset(release)
    assert mode == "installer"
    assert asset["name"].endswith(".exe")


def test_select_update_asset_returns_none_when_executable_missing() -> None:
    release = {
        "assets": [
            {
                "name": "MinecraftServerManager-v1.6.7.zip",
                "browser_download_url": "https://example/archive.zip",
            },
        ]
    }

    asset, mode = UpdateParsing.select_update_asset(release)
    assert mode == "none"
    assert asset == {}


def test_select_update_asset_ignores_setup_exe() -> None:
    release = {
        "assets": [
            {
                "name": "MinecraftServerManager-Setup.exe",
                "browser_download_url": "https://example/app.exe",
            },
        ]
    }

    asset, mode = UpdateParsing.select_update_asset(release)
    assert mode == "none"
    assert asset == {}


def test_select_update_asset_returns_none_when_no_valid_asset() -> None:
    release = {"assets": [{"name": "notes.txt"}]}
    asset, mode = UpdateParsing.select_update_asset(release)
    assert asset == {}
    assert mode == "none"


def test_parse_asset_digest_returns_sha256_when_present() -> None:
    digest_value = "a" * 64
    asset = {"digest": f"sha256:{digest_value}"}

    result = UpdateParsing.parse_asset_digest(asset)

    assert result == (
        "sha256",
        digest_value,
    )


def test_parse_asset_digest_returns_none_when_missing_or_invalid() -> None:
    assert UpdateParsing.parse_asset_digest({}) is None
    assert UpdateParsing.parse_asset_digest({"digest": ""}) is None
    assert UpdateParsing.parse_asset_digest({"digest": "md5:abcd"}) is None
    assert UpdateParsing.parse_asset_digest({"digest": f"sha512:{'a' * 128}"}) is None
